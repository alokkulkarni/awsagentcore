"""
adapters/connect_voice.py — Amazon Connect Voice adapter via WebRTC + Polly + Transcribe.

Implements the same ``BaseAdapter`` interface as ``ConnectWebSocketAdapter`` so
the ``ScenarioRunner`` and all downstream evaluation / reporting code works
unchanged.  The channel is switched by passing ``channel="voice"`` to the CLI
(``--channel voice``) or by setting ``channel: voice`` in the scenario YAML.

Architecture
------------

    StartWebRTCContact (boto3)
            ↓
    ChimeSignalingClient (WSS)  ←→  Chime signaling protocol (JOIN / SUBSCRIBE / LEAVE)
            ↓
    aiortc RTCPeerConnection     ←→  DTLS/SRTP audio media (WebRTC)
      ├── PCMAudioTrack (send)   ←  Amazon Polly neural TTS  (customer → ARIA)
      └── received audio track   →  Amazon Transcribe Stream (ARIA → text)

Flow per ``send_message()`` call
---------------------------------
1. Synthesise customer text via Polly → 16 kHz PCM bytes.
2. Feed PCM into ``PCMAudioTrack`` (which feeds the WebRTC sender track).
3. Simulate speaking pause proportional to word count.

Flow per ``receive()`` call
----------------------------
1. The background audio receiver task continuously receives ``av.AudioFrame``
   objects from the aiortc track (ARIA's audio), resamples to 16 kHz mono, and
   puts raw PCM chunks on an ``asyncio.Queue``.
2. ``receive()`` creates a fresh ``TranscribeSTT.transcribe_utterance()`` task
   that consumes the queue until silence (3 s) or overall timeout.
3. The final accumulated transcript is returned as an ``AdapterMessage``.

Environment variables
---------------------
``CONNECT_VOICE_FLOW_ID``   — Required.  Contact flow ID for the WebRTC voice flow.
``POLLY_VOICE_ID``          — Optional.  Default: ``Brian`` (British English male neural).
``POLLY_REGION``            — Optional.  Default: value of ``CONNECT_REGION``.
``TRANSCRIBE_REGION``       — Optional.  Default: value of ``CONNECT_REGION``.
``VOICE_RESPONSE_TIMEOUT``  — Optional.  Seconds to wait for ARIA's reply.  Default: 45.
``VOICE_SILENCE_TIMEOUT``   — Optional.  Seconds of silence → end of utterance.  Default: 3.
``VOICE_PREFER_RELAY``      — Optional.  Prefer TURN relay ICE candidates. Default: 0.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Optional

import av
import boto3
import numpy as np
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import AudioStreamTrack
from botocore.exceptions import ClientError

from adapters import AdapterMessage, BaseAdapter, SessionEndedError
from adapters.chime_signaling import ChimeSignalingClient, ChimeSignalingError, TurnCredentials
from adapters.stt_transcribe import SILENCE_TIMEOUT_SECS, TranscribeSTT
from adapters.tts_polly import PollyTTS

logger = logging.getLogger(__name__)

# ── aioice TURN monkey-patch: SEND-INDICATION fallback ────────────────────────
#
# Amazon Connect's Chime TURN servers reject CHANNEL-BIND (error 403 Forbidden)
# for the peer's reflexive/relayed address.  aioice's TurnClientMixin.send_data()
# requires a bound channel before it can send any data, so without this patch
# the DTLS ClientHello is never transmitted and the WebRTC connection hangs.
#
# Fix: catch the 403 and retransmit the payload via a STUN SEND-INDICATION,
# which is the alternative TURN data-forwarding mechanism (RFC 5766 §7).
# SEND-INDICATION does not require channel binding and works fine for DTLS
# bootstrap traffic (the path is slightly less efficient but fully functional).
def _apply_aioice_send_indication_patch() -> None:
    import struct as _struct
    import aioice.stun as _stun
    import aioice.turn as _turn

    # Register STUN DATA attribute (0x0013) — aioice omits it from its table.
    if 0x0013 not in _stun.ATTRIBUTES_BY_TYPE:
        _entry = (0x0013, "DATA", _stun.pack_bytes, _stun.unpack_bytes)
        _stun.ATTRIBUTES.append(_entry)
        _stun.ATTRIBUTES_BY_TYPE[0x0013] = _entry
        _stun.ATTRIBUTES_BY_NAME["DATA"] = _entry

    _orig_send_data = _turn.TurnClientMixin.send_data

    async def _patched_send_data(
        self: _turn.TurnClientMixin, data: bytes, addr: tuple
    ) -> None:
        # Wait if a channel-bind is already in flight for this peer.
        if addr in self.peer_connect_waiters:
            loop = asyncio.get_event_loop()
            waiter = loop.create_future()
            self.peer_connect_waiters[addr].append(waiter)
            await waiter

        channel = self.peer_to_channel.get(addr)
        now = time.time()

        if channel is None:
            self.peer_connect_waiters[addr] = []
            channel = self.channel_number
            self.channel_number += 1
            try:
                await self.channel_bind(channel, addr)
                self.channel_refresh_at[channel] = now + self.channel_refresh_time
                self.channel_to_peer[channel] = addr
                self.peer_to_channel[addr] = channel
            except Exception:
                # CHANNEL-BIND rejected (403 Forbidden) — send via SEND-INDICATION.
                for waiter in self.peer_connect_waiters.pop(addr, []):
                    waiter.set_result(None)
                indication = _stun.Message(
                    message_method=_stun.Method.SEND,
                    message_class=_stun.Class.INDICATION,
                )
                indication.attributes["XOR-PEER-ADDRESS"] = addr
                indication.attributes["DATA"] = data
                self._send(bytes(indication))
                return
            for waiter in self.peer_connect_waiters.pop(addr, []):
                waiter.set_result(None)
        elif now > self.channel_refresh_at[channel]:
            try:
                await self.channel_bind(channel, addr)
                self.channel_refresh_at[channel] = now + self.channel_refresh_time
            except Exception:
                # Refresh rejected — fall back to SEND-INDICATION for this packet.
                indication = _stun.Message(
                    message_method=_stun.Method.SEND,
                    message_class=_stun.Class.INDICATION,
                )
                indication.attributes["XOR-PEER-ADDRESS"] = addr
                indication.attributes["DATA"] = data
                self._send(bytes(indication))
                return

        header = _struct.pack("!HH", channel, len(data))
        self._send(header + data)

    _turn.TurnClientMixin.send_data = _patched_send_data
    logging.getLogger(__name__).debug(
        "aioice TURN patch applied: CHANNEL-BIND 403 → SEND-INDICATION fallback"
    )


_apply_aioice_send_indication_patch()
# ── end of aioice patch ────────────────────────────────────────────────────────


def _apply_aioice_relay_transport_patch() -> None:
    """
    Force aioice transport policy to RELAY when creating ICE connections.

    In some NAT/firewall environments direct host/srflx pairs can pass checks
    but fail during DTLS media establishment. For evaluator runs we prefer
    deterministic TURN-relayed media paths.
    """
    import aioice.ice as _ice

    if getattr(_ice.Connection.get_component_candidates, "_aria_relay_patch", False):
        return

    _orig_get_component_candidates = _ice.Connection.get_component_candidates

    async def _patched_get_component_candidates(self, *args, **kwargs):
        candidates = await _orig_get_component_candidates(self, *args, **kwargs)
        # aioice builds checklists from self._protocols (not only returned candidates),
        # so host protocols must also be pruned to truly enforce relay-only checks.
        self._protocols = [
            p
            for p in self._protocols
            if getattr(getattr(p, "local_candidate", None), "type", "") == "relay"
        ]
        relay_candidates = [c for c in candidates if getattr(c, "type", "") == "relay"]
        return relay_candidates or candidates

    _patched_get_component_candidates._aria_relay_patch = True  # type: ignore[attr-defined]
    _ice.Connection.get_component_candidates = _patched_get_component_candidates
    logging.getLogger(__name__).debug(
        "aioice ICE patch applied: only relay candidates retained when available"
    )


if os.environ.get("VOICE_PREFER_RELAY", "0").strip().lower() not in {"0", "false", "no"}:
    _apply_aioice_relay_transport_patch()

# WebRTC audio frame parameters — Chime / aiortc standard
_SAMPLE_RATE = 48_000           # aiortc / Opus native rate
_CHANNELS = 1                   # mono
_FRAME_SAMPLES = 960            # 20 ms @ 48 kHz
_POLLY_RATE = 16_000            # Polly PCM output rate (upsampled for WebRTC)
_BYTES_PER_SAMPLE = 2           # signed 16-bit LE


# ── Custom aiortc audio track (PCM source) ────────────────────────────────────

class PCMAudioTrack(AudioStreamTrack):
    """
    aiortc ``AudioStreamTrack`` that sends PCM data fed in from Polly TTS.

    Sends silence when the audio queue is empty (maintains the track alive).
    Audio is fed as 16 kHz mono PCM bytes; it is upsampled to 48 kHz for Opus.
    """

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._queue: asyncio.Queue[Optional[np.ndarray]] = asyncio.Queue()
        self._pending = np.zeros(0, dtype=np.int16)

    def feed_pcm(self, pcm_bytes: bytes) -> None:
        """
        Enqueue PCM bytes (16 kHz, 16-bit mono) from Polly for transmission.
        Call this BEFORE/during the speaking simulation delay so the data is
        available when ``recv()`` is called by aiortc.
        """
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(pcm) == 0:
            return
        # Upsample 16 kHz → 48 kHz (factor 3) using linear interpolation
        n_out = len(pcm) * (_SAMPLE_RATE // _POLLY_RATE)
        x_in = np.arange(len(pcm))
        x_out = np.linspace(0, len(pcm) - 1, n_out)
        pcm_48k = np.interp(x_out, x_in, pcm.astype(np.float64)).astype(np.int16)
        self._queue.put_nowait(pcm_48k)

    async def recv(self) -> av.AudioFrame:
        """Return the next 20 ms audio frame to aiortc (silence if queue is empty)."""
        # Keep pacing aligned with real-time RTP cadence.
        pts, time_base = await self.next_timestamp()

        # Fill _pending up to one frame's worth
        while len(self._pending) < _FRAME_SAMPLES:
            try:
                chunk = self._queue.get_nowait()
                if chunk is not None:
                    self._pending = np.concatenate([self._pending, chunk])
                else:
                    break
            except asyncio.QueueEmpty:
                # Pad with silence
                silence = np.zeros(
                    _FRAME_SAMPLES - len(self._pending), dtype=np.int16
                )
                self._pending = np.concatenate([self._pending, silence])
                break

        samples = self._pending[:_FRAME_SAMPLES]
        self._pending = self._pending[_FRAME_SAMPLES:]

        frame = av.AudioFrame.from_ndarray(
            samples.reshape(1, _FRAME_SAMPLES),
            format="s16",
            layout="mono",
        )
        frame.pts = pts
        frame.sample_rate = _SAMPLE_RATE
        frame.time_base = time_base
        return frame


# ── Connect Voice Adapter ─────────────────────────────────────────────────────

class ConnectVoiceAdapterError(RuntimeError):
    """Raised on unrecoverable voice adapter errors."""


class ConnectVoiceAdapter(BaseAdapter):
    """
    Amazon Connect voice adapter for the ARIA evaluator.

    Joins an Amazon Connect WebRTC contact as a synthetic customer, sends
    scenario text via Amazon Polly TTS over WebRTC, and transcribes ARIA's
    voice responses via Amazon Transcribe Streaming.

    Parameters
    ----------
    instance_id         Connect instance UUID.
    contact_flow_id     The WebRTC voice contact flow ID (different from chat).
    region              AWS region for Connect.
    display_name        Customer display name shown in Connect CCP.
    polly_voice_id      Amazon Polly voice for customer speech.  Default: ``Brian``.
    polly_region        AWS region for Polly.  Default: *region*.
    transcribe_region   AWS region for Transcribe Streaming.  Default: *region*.
    response_timeout    Max seconds to wait for ARIA's voice reply.  Default: 45.
    silence_timeout     Seconds of silence that marks end of ARIA's utterance.  Default: 3.
    """

    def __init__(
        self,
        instance_id: str,
        contact_flow_id: str,
        region: str = "eu-west-2",
        display_name: str = "ARIAEvaluatorBot",
        polly_voice_id: str = "Brian",
        polly_region: Optional[str] = None,
        transcribe_region: Optional[str] = None,
        response_timeout: float = 45.0,
        silence_timeout: float = SILENCE_TIMEOUT_SECS,
    ) -> None:
        self._instance_id = instance_id
        self._contact_flow_id = contact_flow_id
        self._region = region
        self._display_name = display_name
        self._response_timeout = response_timeout
        self._silence_timeout = silence_timeout

        self._tts = PollyTTS(
            voice_id=polly_voice_id,
            region=polly_region or region,
        )
        self._stt = TranscribeSTT(
            region=transcribe_region or region,
        )

        # Runtime state — populated during connect()
        self._contact_id: Optional[str] = None
        self._pc: Optional[RTCPeerConnection] = None
        self._audio_track: Optional[PCMAudioTrack] = None
        self._stt_audio_queue: Optional[asyncio.Queue] = None
        self._audio_recv_task: Optional[asyncio.Task] = None
        self._chime_client: Optional[ChimeSignalingClient] = None
        self._connected = False
        self._audio_frames_received = 0

        # Per-turn STT session: started by send_message(), polled by receive()
        self._stt_task: Optional[asyncio.Task] = None
        self._stt_result_queue: asyncio.Queue = asyncio.Queue()

    # ── BaseAdapter implementation ────────────────────────────────────────────

    async def connect(
        self,
        session_id: str,
        customer_id: Optional[str] = None,
        authenticated: bool = False,
        channel: str = "voice",
        scenario_name: str = "",
    ) -> None:
        """
        Establish a WebRTC voice contact with Amazon Connect / ARIA.

        Sequence:
        1. ``StartWebRTCContact`` → Meeting + Attendee + JoinToken
        2. Connect to Chime SignalingUrl (WSS)
        3. Send JOIN → receive JOIN_ACK (TURN credentials)
        4. Create aiortc RTCPeerConnection with TURN ICE servers
        5. Add Polly audio sender track
        6. Create SDP offer (wait for ICE gathering)
        7. Send SUBSCRIBE (SDP offer) → receive SUBSCRIBE_ACK (SDP answer)
        8. Set remote description → ICE negotiation completes
        9. Start background audio-receiver → Transcribe pipeline
        """
        logger.info("ConnectVoiceAdapter: starting WebRTC contact (session=%s)", session_id)

        # ── Step 1: StartWebRTCContact ────────────────────────────────────────
        connect_client = boto3.client("connect", region_name=self._region)
        # Use the SAME attribute names as the chat widget so the contact flow
        # recognises authStatus / customerId correctly on the voice channel.
        attributes: dict[str, str] = {
            "customerId":         customer_id or "",
            "authStatus":         "authenticated" if authenticated else "unauthenticated",
            "channel":            "voice",
            "locale":             "en-GB",
            "evaluationScenario": scenario_name,
        }

        try:
            resp = connect_client.start_web_rtc_contact(
                InstanceId=self._instance_id,
                ContactFlowId=self._contact_flow_id,
                ParticipantDetails={"DisplayName": self._display_name},
                ClientToken=str(uuid.uuid4()),
                Attributes=attributes,
            )
        except ClientError as exc:
            raise ConnectVoiceAdapterError(
                f"StartWebRTCContact failed: {exc}"
            ) from exc

        self._contact_id = resp["ContactId"]
        conn_data = resp["ConnectionData"]
        meeting = conn_data["Meeting"]
        attendee = conn_data["Attendee"]
        signaling_url: str = meeting["MediaPlacement"]["SignalingUrl"]
        audio_host_url: str = meeting["MediaPlacement"]["AudioHostUrl"]
        join_token: str = attendee["JoinToken"]
        attendee_id: str = attendee.get("AttendeeId", "")

        logger.info(
            "ConnectVoiceAdapter: contact_id=%s meeting_id=%s",
            self._contact_id, meeting.get("MeetingId", "?"),
        )

        # ── Steps 2–3: Chime signaling JOIN ───────────────────────────────────
        self._chime_client = ChimeSignalingClient(
            signaling_url=signaling_url,
            join_token=join_token,
            audio_host_url=audio_host_url,
        )
        await self._chime_client.__aenter__()

        turn_creds: TurnCredentials = await self._chime_client.join()

        # ── Steps 4–5: RTCPeerConnection + audio track ────────────────────────
        ice_servers = [
            RTCIceServer(urls=uri, username=turn_creds.username, credential=turn_creds.password)
            for uri in turn_creds.uris
        ] if turn_creds.uris else []

        config = RTCConfiguration(iceServers=ice_servers)
        self._pc = RTCPeerConnection(configuration=config)
        self._audio_track = PCMAudioTrack()
        self._pc.addTrack(self._audio_track)

        # Capture received audio track
        received_track_future: asyncio.Future = asyncio.get_event_loop().create_future()

        # ── Step 6: SDP offer (wait for ICE gathering) ────────────────────────
        # Register ALL event handlers before creating the offer to avoid races
        ice_complete = asyncio.Event()
        ice_connected = asyncio.Event()

        @self._pc.on("icegatheringstatechange")
        def _on_ice_gather():
            if self._pc and self._pc.iceGatheringState == "complete":
                ice_complete.set()

        @self._pc.on("iceconnectionstatechange")
        def _on_ice_connected():
            state = self._pc.iceConnectionState if self._pc else None
            logger.info("ConnectVoiceAdapter: ICE connection state → %s", state)
            if state in ("connected", "completed"):
                ice_connected.set()

        @self._pc.on("track")
        def _on_track(track):
            if track.kind == "audio" and not received_track_future.done():
                logger.debug("ConnectVoiceAdapter: received audio track")
                received_track_future.set_result(track)

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)

        # Handle race: gathering may have already completed
        if self._pc.iceGatheringState == "complete":
            ice_complete.set()

        try:
            await asyncio.wait_for(ice_complete.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            logger.warning("ConnectVoiceAdapter: ICE gathering timed out — using partial candidates")

        sdp_offer: str = self._pc.localDescription.sdp
        cands = [l for l in sdp_offer.split("\n") if "candidate" in l]
        # Log key SDP offer attributes for DTLS/direction diagnostics
        setup_lines = [l.strip() for l in sdp_offer.split("\n") if "a=setup" in l or "a=sendrecv" in l or "a=recvonly" in l or "a=sendonly" in l]
        logger.debug("ConnectVoiceAdapter: SDP offer setup/direction: %s", setup_lines)
        logger.info("ConnectVoiceAdapter: local SDP has %d ICE candidates", len(cands))

        # ── Step 7: SUBSCRIBE → SUBSCRIBE_ACK ────────────────────────────────
        sdp_answer = await self._chime_client.subscribe(sdp_offer, attendee_id=attendee_id)
        # Mirror the JS SDK's initial unmuted state publication.
        await self._chime_client.set_audio_muted(False)

        # Log key SDP answer attributes for DTLS/direction diagnostics
        ans_setup = [l.strip() for l in sdp_answer.split("\n") if "a=setup" in l or "a=sendrecv" in l or "a=recvonly" in l or "a=sendonly" in l]
        logger.debug("ConnectVoiceAdapter: SDP answer setup/direction: %s", ans_setup)

        # ── Step 8: Set remote description ────────────────────────────────────
        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp_answer, type="answer")
        )

        # Handle race: ICE may have already reached connected/completed
        if self._pc.iceConnectionState in ("connected", "completed"):
            ice_connected.set()

        try:
            await asyncio.wait_for(ice_connected.wait(), timeout=30.0)
            logger.info("ConnectVoiceAdapter: ICE connected ✓ (state=%s)", self._pc.iceConnectionState)
        except asyncio.TimeoutError:
            logger.warning("ConnectVoiceAdapter: ICE did not complete in 30s (state=%s) — audio may not flow",
                           self._pc.iceConnectionState)

        # ── Step 9: Start background audio → STT pipeline ────────────────────
        # Use an unbounded queue so _audio_receiver never blocks (old frames
        # are dropped by the receiver itself if the queue grows too large).
        self._stt_audio_queue = asyncio.Queue(maxsize=500)

        # Wait for the remote audio track (aiortc fires the 'track' event
        # synchronously inside setRemoteDescription, so this is usually instant).
        try:
            recv_track = await asyncio.wait_for(
                asyncio.shield(received_track_future), timeout=10.0
            )
            self._audio_recv_task = asyncio.create_task(
                self._audio_receiver(recv_track),
                name="voice-audio-recv",
            )
            logger.info("ConnectVoiceAdapter: audio receiver started ✓")
        except asyncio.TimeoutError:
            logger.warning("ConnectVoiceAdapter: no incoming audio track in 10s — STT disabled")

        self._connected = True

        # ── Step 10: Drain ARIA's initial greeting ────────────────────────────
        # Mirrors the chat adapter's _drain_noise() — ARIA always plays an
        # opening prompt before the customer speaks.  We wait for it to finish
        # (silence ≥ 3 s) then return so the ScenarioRunner can send turn 1.
        # first_audio_timeout=15 s handles slow Lambda cold starts.
        if self._audio_recv_task is not None:
            print("    ⏳ waiting for ARIA greeting…", end="", flush=True)
            try:
                greeting = await self._stt.transcribe_utterance(
                    self._stt_audio_queue,
                    silence_timeout=3.0,
                    max_duration=20.0,
                    first_audio_timeout=15.0,
                )
                if greeting:
                    print(f" heard: {greeting!r}", flush=True)
                    logger.info("ConnectVoiceAdapter: ARIA greeting: %r", greeting)
                else:
                    print(" (no greeting detected — continuing)", flush=True)
                    logger.info("ConnectVoiceAdapter: no greeting audio (authenticated fast-path?)")
            except Exception as exc:
                print(f" (drain error: {exc})", flush=True)
                logger.warning("ConnectVoiceAdapter: greeting drain failed (non-fatal): %s", exc)

        logger.info("ConnectVoiceAdapter: connected and ready (contact=%s)", self._contact_id)

    async def send_message(self, content: str, simulate_typing: bool = True) -> None:
        """
        Synthesise *content* via Polly and send it over the WebRTC audio track.

        After the audio has been queued for transmission we start a background
        Transcribe session (``_stt_task``) that listens for ARIA's reply.
        ``receive()`` then polls the result of that single session rather than
        opening a new Transcribe session on every 2-second poll — this matches
        how the hosted widget handles voice turns.
        """
        if not self._connected:
            raise ConnectVoiceAdapterError("send_message called before connect()")

        # Cancel any leftover STT session from the previous turn and purge
        # stale audio so we start clean.
        await self._reset_stt_session()

        pcm_bytes = self._tts.synthesize(content)
        speaking_duration = PollyTTS.estimate_duration(content)
        word_count = len(content.split())

        if simulate_typing and self._audio_track:
            print(
                f"    🎤  speaking ({word_count} words, ~{speaking_duration:.1f}s)…",
                end=" ",
                flush=True,
            )

        if self._audio_track:
            self._audio_track.feed_pcm(pcm_bytes)

        if simulate_typing:
            await asyncio.sleep(speaking_duration)
            print("↵", flush=True)

        # Kick off the Transcribe session immediately after we finish speaking.
        # ARIA may start responding before we call receive(), and we don't want
        # to miss any leading audio.
        if self._stt_audio_queue is not None:
            self._stt_task = asyncio.create_task(
                self._run_stt_session(), name="voice-stt-session"
            )

    async def receive(self, timeout: float = 60.0) -> Optional[AdapterMessage]:
        """
        Wait up to *timeout* seconds for ARIA's voice response (transcribed text).

        Uses the background ``_stt_task`` started by ``send_message()`` instead
        of opening a fresh Transcribe session on every call.  The ScenarioRunner
        calls this in a tight 2-second loop; we transparently accumulate results
        and return as soon as the session completes.
        """
        if not self._connected or self._stt_audio_queue is None:
            return None

        # Start the STT session lazily if send_message() somehow didn't start it.
        if self._stt_task is None or self._stt_task.done():
            if not self._stt_result_queue.empty():
                pass  # result already in queue — fall through to get()
            else:
                self._stt_task = asyncio.create_task(
                    self._run_stt_session(), name="voice-stt-session"
                )

        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        text = ""
        while True:
            if (
                self._pc
                and self._pc.iceConnectionState in ("failed", "closed")
                and self._audio_frames_received == 0
            ):
                raise ConnectVoiceAdapterError(
                    "WebRTC media disconnected before any inbound audio frames were received. "
                    "This usually means the DTLS media path failed before audio started "
                    "(for example: flow media configuration mismatch, UDP/NAT/firewall path issues, "
                    "or runtime incompatibility)."
                )

            remaining = deadline - loop.time()
            if remaining <= 0:
                return None

            try:
                text = await asyncio.wait_for(
                    self._stt_result_queue.get(),
                    timeout=min(1.0, remaining),
                )
                break
            except asyncio.TimeoutError:
                continue

        if not text:
            return None
        return AdapterMessage(
            role="agent",
            content=text,
            display_name="ARIA",
        )

    # ── Internal: per-turn STT session ────────────────────────────────────────

    async def _run_stt_session(self) -> None:
        """Run one Transcribe session for ARIA's current turn, put result on queue."""
        try:
            text = await self._stt.transcribe_utterance(
                self._stt_audio_queue,
                silence_timeout=self._silence_timeout,
                max_duration=self._response_timeout + 5.0,
                first_audio_timeout=self._response_timeout,
            )
            await self._stt_result_queue.put(text or "")
        except Exception as exc:
            logger.warning("ConnectVoiceAdapter: STT session error: %s", exc)
            await self._stt_result_queue.put("")

    async def _reset_stt_session(self) -> None:
        """Cancel the current STT session and purge stale queues for next turn."""
        # Cancel running session
        if self._stt_task and not self._stt_task.done():
            self._stt_task.cancel()
            try:
                await self._stt_task
            except (asyncio.CancelledError, Exception):
                pass
        self._stt_task = None

        # Drain stale results
        while not self._stt_result_queue.empty():
            try:
                self._stt_result_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Drain stale audio (ARIA speaking from previous turn / noise)
        if self._stt_audio_queue is not None:
            drained = 0
            while not self._stt_audio_queue.empty():
                try:
                    self._stt_audio_queue.get_nowait()
                    drained += 1
                except asyncio.QueueEmpty:
                    break
            if drained:
                logger.debug("ConnectVoiceAdapter: drained %d stale audio chunks", drained)

    async def disconnect(self) -> None:
        """Close the WebRTC peer connection and end the Connect voice contact."""
        self._connected = False

        # Stop the per-turn STT session
        await self._reset_stt_session()

        # Stop audio receiver
        if self._audio_recv_task and not self._audio_recv_task.done():
            self._audio_recv_task.cancel()
            try:
                await self._audio_recv_task
            except asyncio.CancelledError:
                pass

        # Close Chime signaling (sends LEAVE)
        if self._chime_client:
            try:
                await self._chime_client.close()
            except Exception as exc:
                logger.debug("Chime close error: %s", exc)

        # Close WebRTC peer connection
        if self._pc:
            try:
                await self._pc.close()
            except Exception as exc:
                logger.debug("RTCPeerConnection close error: %s", exc)

        # End the Connect contact
        if self._contact_id:
            try:
                connect_client = boto3.client("connect", region_name=self._region)
                connect_client.stop_contact(
                    ContactId=self._contact_id,
                    InstanceId=self._instance_id,
                )
                logger.info("ConnectVoiceAdapter: contact %s ended", self._contact_id)
            except Exception as exc:
                logger.debug("StopContact error: %s", exc)

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _to_pcm16(frame: av.AudioFrame) -> np.ndarray:
        """
        Convert an av.AudioFrame payload to mono int16 PCM samples.

        Some codecs / frame paths yield float samples (e.g. fltp in [-1, 1]).
        Casting those directly to int16 collapses most values to 0 and causes STT
        starvation. We normalize explicitly when needed.
        """
        arr = frame.to_ndarray()
        if arr.ndim > 1:
            arr = arr.reshape(-1)

        if np.issubdtype(arr.dtype, np.floating):
            arr = np.clip(arr, -1.0, 1.0)
            return (arr * 32767.0).astype(np.int16)

        if arr.dtype == np.int16:
            return arr.astype(np.int16, copy=False)

        if np.issubdtype(arr.dtype, np.integer):
            info = np.iinfo(arr.dtype)
            max_abs = float(max(abs(info.min), info.max))
            if max_abs <= 32767:
                return arr.astype(np.int16)
            scaled = (arr.astype(np.float32) / max_abs) * 32767.0
            return scaled.astype(np.int16)

        return arr.astype(np.int16)

    async def _audio_receiver(self, track) -> None:
        """
        Continuously receive audio frames from aiortc and push raw 16 kHz PCM
        chunks onto ``_stt_audio_queue`` for Transcribe Streaming.

        All non-zero frames are enqueued.  Silence detection is handled inside
        ``transcribe_utterance`` by watching Transcribe result timestamps — NOT
        by checking whether this queue is empty (aiortc delivers frames at 50 fps
        regardless of audio content, so the queue never goes empty).
        """
        resampler = av.audio.resampler.AudioResampler(
            format="s16",
            layout="mono",
            rate=16_000,  # Transcribe Streaming native rate
        )
        logger.info("ConnectVoiceAdapter: audio receiver started")
        frames_received = 0
        self._audio_frames_received = 0
        chunks_enqueued = 0
        zero_chunks = 0
        try:
            while self._connected:
                try:
                    frame = await asyncio.wait_for(track.recv(), timeout=2.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as exc:
                    logger.debug("Audio track recv ended: %s", exc)
                    break

                frames_received += 1
                self._audio_frames_received = frames_received
                if frames_received <= 5 or frames_received % 200 == 0:
                    logger.debug(
                        "ConnectVoiceAdapter: audio frame #%d received", frames_received
                    )

                # Resample to 16 kHz for Transcribe
                resampled_frames = resampler.resample(frame)
                for rf in resampled_frames:
                    pcm_arr = self._to_pcm16(rf)

                    # Only skip frames that are pure digital silence (all zeros).
                    # Real codec output — even background noise — will be non-zero.
                    if not np.any(pcm_arr):
                        zero_chunks += 1
                        continue

                    pcm = pcm_arr.tobytes()
                    if self._stt_audio_queue is not None:
                        try:
                            self._stt_audio_queue.put_nowait(pcm)
                            chunks_enqueued += 1
                        except asyncio.QueueFull:
                            # Drop oldest frame to prevent unbounded backlog
                            try:
                                self._stt_audio_queue.get_nowait()
                                self._stt_audio_queue.put_nowait(pcm)
                                chunks_enqueued += 1
                            except asyncio.QueueEmpty:
                                pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("ConnectVoiceAdapter audio receiver error: %s", exc)
        finally:
            logger.info(
                "ConnectVoiceAdapter: audio receiver stopped (frames=%d, enqueued=%d, zero=%d)",
                frames_received,
                chunks_enqueued,
                zero_chunks,
            )
            # Signal end-of-stream to any waiting Transcribe session
            if self._stt_audio_queue is not None:
                try:
                    self._stt_audio_queue.put_nowait(None)
                except asyncio.QueueFull:
                    pass


# ── Factory helper ────────────────────────────────────────────────────────────

def create_voice_adapter_from_env(
    display_name: str = "ARIAEvaluatorBot",
    customer_id: Optional[str] = None,
) -> ConnectVoiceAdapter:
    """
    Instantiate a ``ConnectVoiceAdapter`` from environment variables.

    Required:
        CONNECT_INSTANCE_ID
        CONNECT_VOICE_FLOW_ID
        CONNECT_REGION (default: eu-west-2)

    Optional:
        POLLY_VOICE_ID        (default: Brian)
        POLLY_REGION          (default: CONNECT_REGION)
        TRANSCRIBE_REGION     (default: CONNECT_REGION)
        VOICE_RESPONSE_TIMEOUT (default: 45)
        VOICE_SILENCE_TIMEOUT  (default: 3)
    """
    instance_id = os.environ["CONNECT_INSTANCE_ID"]
    flow_id = os.environ["CONNECT_VOICE_FLOW_ID"]
    region = os.environ.get("CONNECT_REGION", "eu-west-2")

    return ConnectVoiceAdapter(
        instance_id=instance_id,
        contact_flow_id=flow_id,
        region=region,
        display_name=display_name,
        polly_voice_id=os.environ.get("POLLY_VOICE_ID", "Brian"),
        polly_region=os.environ.get("POLLY_REGION", region),
        transcribe_region=os.environ.get("TRANSCRIBE_REGION", region),
        response_timeout=float(os.environ.get("VOICE_RESPONSE_TIMEOUT", "45")),
        silence_timeout=float(os.environ.get("VOICE_SILENCE_TIMEOUT", "3")),
    )
