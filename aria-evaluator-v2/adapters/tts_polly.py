"""
adapters/tts_polly.py — Amazon Polly TTS helper for voice evaluation.

Converts scenario text to signed-16-bit LE mono PCM audio at 16 kHz, the
format accepted by both aiortc (after resampling) and Amazon Transcribe
Streaming.  Uses the Neural engine for the most natural-sounding speech.
"""

from __future__ import annotations

import io
import logging
import math
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Polly PCM output sample rate — Transcribe Streaming accepts 16 kHz natively.
POLLY_SAMPLE_RATE: int = 16_000
# Characters-per-second speaking rate used to estimate audio duration for
# simulating a natural speaking pause before waiting for the agent to reply.
_CHARS_PER_SECOND: float = 15.0
# Words-per-minute → chars-per-second conversion helper used for display.
_WPM: float = 130.0


class PollyTTS:
    """
    Synthesise text to raw PCM audio using Amazon Polly Neural TTS.

    Default voice: ``Brian`` — British English male neural voice, appropriate
    for a banking evaluation persona named James.

    Usage::

        tts = PollyTTS(region="eu-west-2")
        pcm_bytes = tts.synthesize("Hello, I'd like to check my balance please.")
        # pcm_bytes is 16-bit LE mono PCM at 16 kHz, ready for WebRTC or Transcribe.
    """

    def __init__(
        self,
        voice_id: str = "Brian",
        engine: str = "neural",
        region: str = "eu-west-2",
    ) -> None:
        self._voice_id = voice_id
        self._engine = engine
        self._region = region
        self._client: Optional[object] = None

    # ── Lazy-initialised boto3 client ─────────────────────────────────────────

    @property
    def _polly(self):
        if self._client is None:
            self._client = boto3.client("polly", region_name=self._region)
        return self._client

    # ── Public API ────────────────────────────────────────────────────────────

    def synthesize(self, text: str) -> bytes:
        """
        Return raw signed-16-bit LE mono PCM bytes at :data:`POLLY_SAMPLE_RATE`.

        Raises :class:`PollyTTSError` if the Polly call fails.
        """
        if not text.strip():
            return b""

        try:
            resp = self._polly.synthesize_speech(
                Text=text,
                VoiceId=self._voice_id,
                Engine=self._engine,
                OutputFormat="pcm",
                SampleRate=str(POLLY_SAMPLE_RATE),
                TextType="text",
            )
        except ClientError as exc:
            raise PollyTTSError(f"Polly synthesize_speech failed: {exc}") from exc

        audio_bytes: bytes = resp["AudioStream"].read()
        logger.debug(
            "Polly synthesized %d bytes for %d chars (%s %s)",
            len(audio_bytes), len(text), self._voice_id, self._engine,
        )
        return audio_bytes

    @staticmethod
    def estimate_duration(text: str) -> float:
        """
        Estimate speaking duration for *text* in seconds.

        Used by the voice adapter to simulate natural speaking pace before
        sending the audio chunk to the WebRTC track.
        """
        word_count = len(text.split())
        # words ÷ WPM × 60s, minimum 0.5s, maximum 30s per turn
        return max(0.5, min(30.0, word_count / _WPM * 60.0))

    @property
    def sample_rate(self) -> int:
        """Sample rate of the PCM output in Hz."""
        return POLLY_SAMPLE_RATE

    @property
    def voice_id(self) -> str:
        return self._voice_id


class PollyTTSError(RuntimeError):
    """Raised when Amazon Polly TTS synthesis fails."""
