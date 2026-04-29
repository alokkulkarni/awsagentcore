"""
adapters/stt_transcribe.py — Amazon Transcribe Streaming STT helper.

Consumes chunks of raw 16-bit PCM audio from an asyncio.Queue and streams
them to Amazon Transcribe Streaming.  Final transcript results (after ARIA
stops speaking) are placed on an output queue for the voice adapter to collect.

The ``TranscribeSTT`` class manages one Transcribe session per *utterance*
(start → feed audio → end → final text).  The voice adapter creates a new
session for each turn (after sending the customer's audio and before waiting
for ARIA's response).

Silence detection
-----------------
Silence is detected by monitoring **Transcribe result timestamps**, not by
watching whether the audio queue is empty.  aiortc delivers audio frames at
~50 fps regardless of content (silence + speech both arrive continuously), so
queue-emptiness is not a reliable signal.  Instead:

1. We first wait for the *first audio chunk* before even opening a Transcribe
   session — this avoids the 15-second server-side idle-timeout that fires
   when a stream is opened but no audio is sent.
2. Once audio starts flowing, we run Transcribe and track ``last_result_at``
   (wall-clock time of the most recent final transcript segment).
3. A ``_monitor_silence`` coroutine declares the utterance finished when
   ``now - last_result_at > silence_timeout`` (default 3 s).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

logger = logging.getLogger(__name__)

# British English — matches ARIA's deployment language.
DEFAULT_LANGUAGE_CODE = "en-GB"
# 16 kHz matches the Polly output and is natively supported by Transcribe.
DEFAULT_SAMPLE_RATE = 16_000
# How long to wait for ARIA to stop speaking before closing the session.
SILENCE_TIMEOUT_SECS = 3.0
# Hard upper bound per turn — prevents hanging if audio never terminates.
MAX_TURN_SECS = 45.0


class TranscribeSTT:
    """
    Async Amazon Transcribe Streaming wrapper for voice evaluation.

    Usage::

        stt = TranscribeSTT(region="eu-west-2")
        # audio_q receives bytes objects of 16 kHz 16-bit mono PCM
        text = await stt.transcribe_utterance(audio_q, first_audio_timeout=30.0)
        print("ARIA said:", text)

    The caller is responsible for feeding PCM bytes onto *audio_q* as audio
    arrives (from the aiortc track).  Putting ``None`` on the queue signals an
    explicit end-of-stream.
    """

    def __init__(
        self,
        region: str = "eu-west-2",
        language_code: str = DEFAULT_LANGUAGE_CODE,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        self._region = region
        self._language_code = language_code
        self._sample_rate = sample_rate

    # ── Public API ────────────────────────────────────────────────────────────

    async def transcribe_utterance(
        self,
        audio_queue: asyncio.Queue,
        silence_timeout: float = SILENCE_TIMEOUT_SECS,
        max_duration: float = MAX_TURN_SECS,
        first_audio_timeout: float = MAX_TURN_SECS,
    ) -> str:
        """
        Stream audio from *audio_queue* to Transcribe until silence or timeout.

        Parameters
        ----------
        audio_queue           asyncio.Queue of ``bytes`` (raw 16-bit PCM).
                              Put ``None`` to signal end of stream explicitly.
        silence_timeout       Seconds after the last Transcribe *result* with no
                              new results before the session is closed.
        max_duration          Hard maximum seconds before forcibly ending.
        first_audio_timeout   How long to wait for the *first* audio chunk to
                              arrive before giving up entirely (no Transcribe
                              stream is opened until audio is ready).

        Returns
        -------
        Accumulated final transcript text, stripped of leading/trailing spaces.
        Returns ``""`` if no speech was detected.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max_duration

        # ── Phase 1: Wait for first audio chunk ───────────────────────────────
        # Do NOT open a Transcribe stream yet — the Transcribe server closes the
        # connection after 15 s of receiving no audio, which would surface as a
        # confusing "no new audio was received" error.
        first_wait = min(first_audio_timeout, max(0.1, deadline - loop.time()))
        try:
            first_chunk = await asyncio.wait_for(
                audio_queue.get(), timeout=first_wait
            )
        except asyncio.TimeoutError:
            logger.debug(
                "STT: no audio within %.0fs first_audio_timeout — ARIA silent",
                first_audio_timeout,
            )
            return ""

        if first_chunk is None:
            return ""

        # ── Phase 2: Open Transcribe and stream ───────────────────────────────
        client = TranscribeStreamingClient(region=self._region)
        stream = await client.start_stream_transcription(
            language_code=self._language_code,
            media_sample_rate_hz=self._sample_rate,
            media_encoding="pcm",
        )

        handler = _FinalResultHandler(stream.output_stream)
        stop_event = asyncio.Event()

        async def _feed_audio() -> None:
            try:
                # Send the first chunk already dequeued above.
                await stream.input_stream.send_audio_event(audio_chunk=first_chunk)

                # Stream remaining audio until stopped or deadline.
                while not stop_event.is_set() and loop.time() < deadline:
                    try:
                        chunk = await asyncio.wait_for(
                            audio_queue.get(), timeout=0.3
                        )
                    except asyncio.TimeoutError:
                        continue  # re-check stop_event / deadline
                    if chunk is None:
                        break
                    await stream.input_stream.send_audio_event(audio_chunk=chunk)
            except Exception as exc:
                logger.warning("STT audio feeder error: %s", exc)
            finally:
                try:
                    await stream.input_stream.end_stream()
                except Exception:
                    pass

        async def _monitor_silence() -> None:
            """
            Set stop_event when:
            - silence_timeout seconds have elapsed with no new Transcribe result, OR
            - max_duration is exceeded.
            Always sets stop_event on exit so _feed_audio terminates cleanly.
            """
            try:
                while loop.time() < deadline and not stop_event.is_set():
                    await asyncio.sleep(0.2)
                    lra = handler.last_result_at
                    if lra is not None and (loop.time() - lra) > silence_timeout:
                        logger.debug(
                            "STT: %.1fs since last result — declaring end of utterance",
                            loop.time() - lra,
                        )
                        stop_event.set()
                        break
            finally:
                # Guarantee _feed_audio always terminates.
                stop_event.set()

        await asyncio.gather(
            _feed_audio(),
            handler.handle_events(),
            _monitor_silence(),
            return_exceptions=True,
        )

        result = handler.final_text.strip()
        logger.debug("STT utterance result: %r", result[:120])
        return result


class _FinalResultHandler(TranscriptResultStreamHandler):
    """Accumulate final (non-partial) Transcribe results into ``final_text``."""

    def __init__(self, output_stream) -> None:
        super().__init__(output_stream)
        self.final_text: str = ""
        self.last_result_at: Optional[float] = None

    async def handle_transcript_event(self, transcript_event: TranscriptEvent) -> None:
        results = transcript_event.transcript.results
        for result in results:
            if result.is_partial:
                continue
            if result.alternatives:
                sentence = result.alternatives[0].transcript
                if sentence:
                    self.final_text += (" " if self.final_text else "") + sentence
                    self.last_result_at = asyncio.get_event_loop().time()
                    logger.debug("STT final segment: %r", sentence)


class TranscribeSTTError(RuntimeError):
    """Raised when Transcribe Streaming setup or streaming fails."""
