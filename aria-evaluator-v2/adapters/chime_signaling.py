"""
adapters/chime_signaling.py — Minimal Amazon Chime SDK WebSocket signaling client.

Implements the binary WebSocket protocol used by the Amazon Chime SDK to join a
Chime meeting as an audio-only attendee.  This is the signaling layer required
by ``StartWebRTCContact`` (Amazon Connect voice/WebRTC contacts).

Protocol overview
-----------------
All messages are encoded as Protocol Buffers (protobuf) and sent as binary
WebSocket frames.  Each WebSocket message is prefixed with a 1-byte
``FRAME_TYPE_RTC`` marker (``0x05`` from client, ``0x02`` from server) followed
by exactly one ``SdkSignalFrame`` protobuf message.

Sequence for joining a meeting::

    Client ──── JOIN ──────────────────► Chime
    Chime  ──── JOIN_ACK (TURN creds) ──► Client
    Client creates RTCPeerConnection with TURN ICE servers
    Client creates SDP offer
    Client ──── SUBSCRIBE (SDP offer) ──► Chime
    Chime  ──── SUBSCRIBE_ACK (SDP ans) ► Client
    Client sets remote description → ICE negotiation (via DTLS/SRTP)
    Client ──── PING ────────────────────► Chime (keepalive every 10s)
    Chime  ──── PONG ────────────────────► Client
    Client ──── LEAVE ───────────────────► Chime (on disconnect)

Protobuf
--------
Field numbers and enum values follow the public Chime SDK proto definition:
  https://github.com/aws/amazon-chime-sdk-js/blob/main/src/signalingprotocol/SignalingProtocol.proto

This module uses a hand-written minimal protobuf encoder/decoder so there is no
.proto compilation step and no grpcio-tools dependency.
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

import websockets
import websockets.asyncio.client
from websockets.connection import State as _WsState
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

def _ws_is_open(ws: Optional["websockets.asyncio.client.ClientConnection"]) -> bool:
    """Return True if the websockets connection is in OPEN state."""
    return ws is not None and ws.state == _WsState.OPEN


# ── Wire-level framing ────────────────────────────────────────────────────────
# Every Chime SDK WebSocket message is prefixed with a 1-byte frame type marker.
# The client sends 0x05 (FRAME_TYPE_RTC) and the server sends 0x02.
# Source: amazon-chime-sdk-js DefaultSignalingClient.prependWithFrameTypeRTC /
#         stripFrameTypeRTC  (DefaultSignalingClient.FRAME_TYPE_RTC = 0x5)

_FRAME_TYPE_RTC = 0x05


def _prepend_frame_type(data: bytes) -> bytes:
    """Prepend the 1-byte Chime frame-type marker to a serialised protobuf frame."""
    return bytes([_FRAME_TYPE_RTC]) + data


def _strip_frame_type(data: bytes) -> bytes:
    """Strip the leading 1-byte Chime frame-type marker from a received frame."""
    return data[1:] if data else data


# ── SdkSignalFrame.Type enum values ──────────────────────────────────────────

_TYPE_JOIN = 1
_TYPE_JOIN_ACK = 2
_TYPE_SUBSCRIBE = 3
_TYPE_SUBSCRIBE_ACK = 4
_TYPE_LEAVE = 9
_TYPE_AUDIO_CONTROL = 16
_TYPE_PING_PONG = 19

# ── SdkPingPongFrame.Type enum values ─────────────────────────────────────────

_PING = 1
_PONG = 2


# ── Minimal protobuf encoder ──────────────────────────────────────────────────

def _varint(value: int) -> bytes:
    """Encode a non-negative integer as protobuf varint."""
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def _field_tag(field_num: int, wire_type: int) -> bytes:
    return _varint((field_num << 3) | wire_type)


def _encode_uint32(field_num: int, value: int) -> bytes:
    return _field_tag(field_num, 0) + _varint(value)


def _encode_uint64(field_num: int, value: int) -> bytes:
    return _field_tag(field_num, 0) + _varint(value)


def _encode_bool(field_num: int, value: bool) -> bytes:
    return _field_tag(field_num, 0) + _varint(1 if value else 0)


def _encode_string(field_num: int, value: str) -> bytes:
    enc = value.encode("utf-8")
    return _field_tag(field_num, 2) + _varint(len(enc)) + enc


def _encode_bytes(field_num: int, value: bytes) -> bytes:
    return _field_tag(field_num, 2) + _varint(len(value)) + value


def _embed(field_num: int, data: bytes) -> bytes:
    """Embed a serialised sub-message as a length-delimited field."""
    return _field_tag(field_num, 2) + _varint(len(data)) + data


# ── Minimal protobuf decoder ──────────────────────────────────────────────────

def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def _decode_message(data: bytes) -> dict:
    """
    Decode a flat protobuf message into a dict of {field_num: value_or_list}.

    For length-delimited fields (wire_type=2) the raw bytes are stored.
    For varint fields (wire_type=0) the integer is stored.
    Repeated fields are accumulated into lists.
    """
    fields: dict = {}
    pos = 0
    length = len(data)
    while pos < length:
        tag, pos = _decode_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x7

        if wire_type == 0:
            value, pos = _decode_varint(data, pos)
        elif wire_type == 2:
            length_val, pos = _decode_varint(data, pos)
            value = data[pos:pos + length_val]
            pos += length_val
        elif wire_type == 1:
            value = struct.unpack_from("<Q", data, pos)[0]
            pos += 8
        elif wire_type == 5:
            value = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        else:
            raise ValueError(f"Unknown protobuf wire type {wire_type} at pos {pos}")

        existing = fields.get(field_num)
        if existing is None:
            fields[field_num] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            fields[field_num] = [existing, value]

    return fields


# ── High-level Chime message builders ─────────────────────────────────────────

def _build_join_frame(join_token: str) -> bytes:
    """Encode a SdkSignalFrame with type=JOIN."""
    # SdkClientDetails (field 4 of SdkJoinFrame)
    client_details = (
        _encode_string(1, "Python-aria-evaluator")  # platform_name
        + _encode_string(2, "2.0.0")                # platform_version
        + _encode_string(3, "aria-evaluator")        # client_source
    )
    # SdkJoinFrame fields (verified against amazon-chime-sdk-js SignalingProtocol.js):
    #   field 1: protocolVersion (uint32)
    #   field 2: maxNumOfVideos (uint32)
    #   field 3: flags (uint32)
    #   field 4: clientDetails (SdkClientDetails, length-delimited)
    #   field 6: audioSessionId (uint64)
    join_frame = (
        _encode_uint32(1, 2)            # protocolVersion=2
        + _encode_uint32(2, 0)          # max_num_of_videos=0 (audio-only)
        # SdkJoinFlags.HAS_STREAM_UPDATE = 2 (used by the JS SDK).
        + _encode_uint32(3, 2)
        + _embed(4, client_details)     # client_details
        + _encode_uint64(6, int(uuid.uuid4()) & 0xFFFF_FFFF_FFFF_FFFF)  # audio_session_id
    )
    # SdkSignalFrame:  field 1=timestampMs, field 2=type, field 4=join
    frame = (
        _encode_uint64(1, int(time.time() * 1000))  # timestamp_ms
        + _encode_uint32(2, _TYPE_JOIN)              # type
        + _embed(4, join_frame)                      # join
    )
    return frame


def _build_subscribe_frame(sdp_offer: str, audio_host_url: str, attendee_id: str = "") -> bytes:
    """Encode a SdkSignalFrame with type=SUBSCRIBE.

    Field numbers verified against amazon-chime-sdk-js SignalingProtocol.js.
    For audio-only (no video) duplex=RX(1); receiveStreamIds is omitted.
    """
    # SdkStreamDescriptor fields:
    #   1=streamId, 2=framerate, 3=maxBitrateKbps, 4=trackLabel,
    #   6=groupId, 7=avgBitrateBps, 8=attendeeId, 9=mediaType
    send_stream = (
        _encode_uint32(1, 1)                            # streamId=1
        + _encode_uint32(2, 15)                         # framerate=15
        + _encode_uint32(3, 600)                        # maxBitrateKbps=600
        + _encode_string(4, "AmazonChimeExpressAudio")  # trackLabel
        + _encode_uint32(6, 1)                          # groupId=1
        + _encode_uint32(7, 400000)                     # avgBitrateBps=400000
        + (_encode_string(8, attendee_id) if attendee_id else b"")  # attendeeId
        + _encode_uint32(9, 1)                          # mediaType: AUDIO=1
    )
    # SdkSubscribeFrame fields:
    #   1=duplex, 2=sendStreams, 4=sdpOffer, 5=audioHost, 6=audioCheckin, 7=audioMuted
    # AudioDuplex enum: RX=1, TX=2, DUPLEX=3
    # Amazon Connect WebRTC contacts use RX=1 — Chime rejects duplex=3 with LEAVE.
    sub_frame = (
        _encode_uint32(1, 1)                 # duplex: RX=1 (Connect voice contact)
        + _embed(2, send_stream)             # sendStreams[0]
        + _encode_string(4, sdp_offer)       # sdpOffer
        + _encode_string(5, audio_host_url)  # audioHost
        + _encode_bool(6, False)             # audioCheckin
        + _encode_bool(7, False)             # audioMuted
    )
    frame = (
        _encode_uint64(1, int(time.time() * 1000))
        + _encode_uint32(2, _TYPE_SUBSCRIBE)
        + _embed(6, sub_frame)
    )
    return frame


def _build_leave_frame() -> bytes:
    """Encode a SdkSignalFrame with type=LEAVE."""
    # SdkLeaveFrame has no fields (empty message in the proto schema).
    # SdkSignalFrame field 11 = leave (verified against SignalingProtocol.js)
    frame = (
        _encode_uint64(1, int(time.time() * 1000))
        + _encode_uint32(2, _TYPE_LEAVE)
        + _embed(11, b"")  # leave: empty SdkLeaveFrame (field 11, not 10)
    )
    return frame


def _build_pong_frame(ping_id: int) -> bytes:
    """Respond to a PING with a PONG."""
    pp_frame = (
        _encode_uint32(1, _PONG)        # type=PONG
        + _encode_uint32(2, ping_id)    # echo the same ping_id
    )
    # SdkSignalFrame field 20 = pingPong (verified against SignalingProtocol.js)
    frame = (
        _encode_uint64(1, int(time.time() * 1000))
        + _encode_uint32(2, _TYPE_PING_PONG)
        + _embed(20, pp_frame)  # pingPong at field 20 (not 17)
    )
    return frame


def _build_ping_frame(ping_id: int) -> bytes:
    """Send an active keepalive PING."""
    pp_frame = (
        _encode_uint32(1, _PING)        # type=PING
        + _encode_uint32(2, ping_id)    # ping_id
    )
    frame = (
        _encode_uint64(1, int(time.time() * 1000))
        + _encode_uint32(2, _TYPE_PING_PONG)
        + _embed(20, pp_frame)
    )
    return frame


def _build_audio_control_frame(muted: bool) -> bytes:
    """Send local audio mute state to the signaling service."""
    # SdkAudioControlFrame: field 1 = muted
    audio_control = _encode_bool(1, muted)
    # SdkSignalFrame field 17 = audioControl
    frame = (
        _encode_uint64(1, int(time.time() * 1000))
        + _encode_uint32(2, _TYPE_AUDIO_CONTROL)
        + _embed(17, audio_control)
    )
    return frame


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class TurnCredentials:
    """TURN server credentials returned in JOIN_ACK."""
    username: str
    password: str
    uris: list[str] = field(default_factory=list)
    ttl: int = 300


# ── Main signaling client ─────────────────────────────────────────────────────

class ChimeSignalingClient:
    """
    Minimal Amazon Chime SDK WebSocket signaling client.

    Usage::

        async with ChimeSignalingClient(signaling_url, join_token, audio_host_url) as chime:
            turn_creds = await chime.join()
            # create RTCPeerConnection with turn_creds, generate SDP offer
            sdp_answer = await chime.subscribe(sdp_offer)
            # set remote description → WebRTC connection starts
    """

    def __init__(
        self,
        signaling_url: str,
        join_token: str,
        audio_host_url: str,
        connect_timeout: float = 15.0,
        ping_interval: float = 10.0,
    ) -> None:
        self._signaling_url = signaling_url
        self._join_token = join_token
        self._audio_host_url = audio_host_url
        self._connect_timeout = connect_timeout
        self._ping_interval = ping_interval
        self._ws: Optional[websockets.asyncio.client.ClientConnection] = None
        self._recv_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._ping_id: int = 0
        self._join_ack_event = asyncio.Event()
        self._subscribe_ack_event = asyncio.Event()
        self._turn_creds: Optional[TurnCredentials] = None
        self._sdp_answer: Optional[str] = None
        self._closed = False

    # ── Context manager ───────────────────────────────────────────────────────

    async def __aenter__(self) -> "ChimeSignalingClient":
        await self._open()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def _open(self) -> None:
        # URL format and subprotocol from amazon-chime-sdk-js SignalingClientConnectionRequest:
        #   URL:          {signalingURL}?X-Chime-Control-Protocol-Version=3&X-Amzn-Chime-Send-Close-On-Error=1
        #   subprotocols: ['_aws_wt_session', joinToken]
        ws_url = (
            f"{self._signaling_url}"
            f"?X-Chime-Control-Protocol-Version=3"
            f"&X-Amzn-Chime-Send-Close-On-Error=1"
        )
        logger.debug("Chime: connecting to %s…", ws_url[:100])
        self._ws = await asyncio.wait_for(
            websockets.connect(
                ws_url,
                subprotocols=["_aws_wt_session", self._join_token],
                max_size=2 ** 20,
                open_timeout=self._connect_timeout,
                ping_interval=None,  # we handle PING/PONG ourselves
            ),
            timeout=self._connect_timeout,
        )
        # Start background receiver task
        self._recv_task = asyncio.create_task(self._receive_loop(), name="chime-recv")
        self._ping_task = asyncio.create_task(self._ping_loop(), name="chime-ping")
        logger.debug("Chime: WebSocket connected")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if _ws_is_open(self._ws):
            try:
                await self._ws.send(_prepend_frame_type(_build_leave_frame()))
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ping_task and not self._ping_task.done():
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass

    # ── High-level signaling steps ────────────────────────────────────────────

    async def join(self, timeout: float = 10.0) -> TurnCredentials:
        """
        Send a JOIN frame and wait for JOIN_ACK.

        Returns TURN server credentials that must be used when creating the
        aiortc ``RTCPeerConnection``.
        """
        if self._ws is None:
            raise ChimeSignalingError("Not connected — call __aenter__ first")
        await self._ws.send(_prepend_frame_type(_build_join_frame(self._join_token)))
        logger.debug("Chime: JOIN sent")
        try:
            await asyncio.wait_for(self._join_ack_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ChimeSignalingError("Timeout waiting for Chime JOIN_ACK") from None
        if self._turn_creds is None:
            raise ChimeSignalingError("JOIN_ACK received but no TURN credentials found")
        logger.debug("Chime: JOIN_ACK received, %d TURN URIs", len(self._turn_creds.uris))
        return self._turn_creds

    async def subscribe(self, sdp_offer: str, attendee_id: str = "", timeout: float = 15.0) -> str:
        """
        Send a SUBSCRIBE frame (with the SDP offer) and wait for SUBSCRIBE_ACK.

        Returns the SDP answer from the Chime server which must be set as the
        remote description of the aiortc ``RTCPeerConnection``.
        """
        if self._ws is None:
            raise ChimeSignalingError("Not connected")
        await self._ws.send(_prepend_frame_type(
            _build_subscribe_frame(sdp_offer, self._audio_host_url, attendee_id=attendee_id)
        ))
        logger.debug("Chime: SUBSCRIBE sent (%d bytes SDP offer)", len(sdp_offer))
        try:
            await asyncio.wait_for(self._subscribe_ack_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ChimeSignalingError("Timeout waiting for Chime SUBSCRIBE_ACK") from None
        if self._sdp_answer is None:
            raise ChimeSignalingError("SUBSCRIBE_ACK received but no SDP answer found")
        logger.debug("Chime: SUBSCRIBE_ACK received, SDP answer %d bytes", len(self._sdp_answer))
        return self._sdp_answer

    async def set_audio_muted(self, muted: bool = False) -> None:
        """Publish local mute state (parity with SDK signaling behavior)."""
        if self._ws is None or not _ws_is_open(self._ws):
            return
        await self._ws.send(_prepend_frame_type(_build_audio_control_frame(muted)))

    # ── Background receive loop ───────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """Consume Chime WebSocket messages and dispatch by type."""
        try:
            assert self._ws is not None
            async for raw_msg in self._ws:
                if isinstance(raw_msg, str):
                    logger.debug("Chime: unexpected text message: %s", raw_msg[:100])
                    continue
                # Strip the leading 1-byte frame-type marker before decoding
                payload = _strip_frame_type(raw_msg)
                await self._handle_frame(payload)
        except ConnectionClosed as exc:
            logger.debug("Chime: WebSocket closed: %s", exc)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Chime receive loop error: %s", exc)

    async def _ping_loop(self) -> None:
        """
        Send active signaling PING keepalives every `ping_interval` seconds.

        The JavaScript Chime SDK sends regular PING_PONG frames from the client.
        Without these keepalives some sessions can be torn down server-side, which
        then causes ICE consent expiry shortly after subscribe.
        """
        try:
            while not self._closed and _ws_is_open(self._ws):
                self._ping_id = (self._ping_id + 1) & 0xFFFFFFFF
                if self._ws is not None:
                    await self._ws.send(
                        _prepend_frame_type(_build_ping_frame(self._ping_id))
                    )
                await asyncio.sleep(self._ping_interval)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Chime ping loop ended: %s", exc)

    async def _handle_frame(self, data: bytes) -> None:
        """Parse and dispatch one binary Chime WebSocket message."""
        try:
            frame = _decode_message(data)
        except Exception as exc:
            logger.debug("Chime: failed to decode frame (%d bytes): %s", len(data), exc)
            return

        frame_type = frame.get(2, 0)

        if frame_type == _TYPE_JOIN_ACK:
            self._parse_join_ack(frame)
            self._join_ack_event.set()

        elif frame_type == _TYPE_SUBSCRIBE_ACK:
            self._parse_subscribe_ack(frame)
            self._subscribe_ack_event.set()

        elif frame_type == _TYPE_PING_PONG:
            # PING received — send PONG
            # SdkSignalFrame field 20 = pingPong (SdkPingPongFrame)
            pp_data = frame.get(20)
            if isinstance(pp_data, bytes):
                pp = _decode_message(pp_data)
                pp_type = pp.get(1, 0)
                if pp_type == _PING:
                    ping_id = pp.get(2, 0)
                    if isinstance(ping_id, int) and _ws_is_open(self._ws):
                        await self._ws.send(_prepend_frame_type(_build_pong_frame(ping_id)))
                        logger.debug("Chime: PING → PONG (id=%d)", ping_id)
                elif pp_type == _PONG:
                    ping_id = pp.get(2, 0)
                    logger.debug("Chime: received PONG (id=%s)", ping_id)

        else:
            logger.debug("Chime: received frame type=%d (ignored)", frame_type)

    # ── JOIN_ACK parsing ──────────────────────────────────────────────────────

    def _parse_join_ack(self, frame: dict) -> None:
        joinack_bytes = frame.get(5)
        if not isinstance(joinack_bytes, bytes):
            logger.warning("Chime JOIN_ACK: missing joinack field (5)")
            return
        joinack = _decode_message(joinack_bytes)
        turn_bytes = joinack.get(1)
        if not isinstance(turn_bytes, bytes):
            logger.warning("Chime JOIN_ACK: no turn_credentials field")
            return
        turn_data = _decode_message(turn_bytes)
        username = _str(turn_data.get(1, b""))
        password = _str(turn_data.get(2, b""))
        ttl = turn_data.get(3, 300)
        uris_raw = turn_data.get(4, [])
        if isinstance(uris_raw, bytes):
            uris_raw = [uris_raw]
        uris = [_str(u) for u in uris_raw if isinstance(u, (bytes, str))]
        self._turn_creds = TurnCredentials(
            username=username,
            password=password,
            ttl=ttl if isinstance(ttl, int) else 300,
            uris=uris,
        )

    # ── SUBSCRIBE_ACK parsing ─────────────────────────────────────────────────

    def _parse_subscribe_ack(self, frame: dict) -> None:
        # Check for an error frame embedded in the SUBSCRIBE_ACK response
        # (SdkSignalFrame field 3 = SdkErrorFrame when server rejects the SUBSCRIBE)
        error_bytes = frame.get(3)
        if isinstance(error_bytes, bytes):
            err = _decode_message(error_bytes)
            status = err.get(1, 0)
            description = _str(err.get(2, b""))
            logger.warning(
                "Chime SUBSCRIBE_ACK: server returned error %s: %s", status, description
            )
            return

        suback_bytes = frame.get(7)
        if not isinstance(suback_bytes, bytes):
            logger.warning("Chime SUBSCRIBE_ACK: missing suback field (7), frame_fields=%s", list(frame.keys()))
            return
        suback = _decode_message(suback_bytes)
        sdp_ans_raw = suback.get(3)
        if sdp_ans_raw is None:
            logger.warning("Chime SUBSCRIBE_ACK: no sdp_answer field (3), suback_fields=%s", list(suback.keys()))
            return
        self._sdp_answer = _str(sdp_ans_raw)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _str(value) -> str:
    """Convert bytes or str to str."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class ChimeSignalingError(RuntimeError):
    """Raised when the Chime signaling protocol fails."""
