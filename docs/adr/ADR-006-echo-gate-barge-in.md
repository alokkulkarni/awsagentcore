# ADR-006: PyAudio Echo Gate + NOVA_BARGE_IN Opt-In for Local Voice

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

ARIA's local voice mode (`aria/voice_agent.py`) uses PyAudio to capture microphone input and play speaker output simultaneously. On standard desktop hardware without a headset, the microphone picks up ARIA's speaker output, creating an **acoustic echo loop**:

1. ARIA speaks a response through the speaker
2. The microphone captures ARIA's speaker audio
3. Nova Sonic receives ARIA's own voice as if it were the customer speaking
4. Nova Sonic generates a USER `textOutput` event from ARIA's own speech
5. ARIA responds to its own voice — the session spirals into a self-conversation

The official AWS Nova Sonic React sample application does not exhibit this problem because browsers expose `getUserMedia({ echoCancellation: true })`. The operating system or browser provides hardware/software **Acoustic Echo Cancellation (AEC)** at the media capture layer. PyAudio provides no AEC functionality.

This problem is fundamental to any raw microphone capture on desktop: without AEC or physical separation of input/output devices (i.e. headphones), the mic will capture speaker output.

## Decision

**Two-mode design with an echo gate as the default and opt-in barge-in mode via `NOVA_BARGE_IN=true`.**

### Default mode — Echo gate ON

During ARIA's audio playback, set a silence window:

```python
# When audio playback begins:
playback_duration = len(audio_bytes) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
self._silence_until = time.time() + playback_duration + SILENCE_BUFFER_SECS
```

In the microphone capture loop, check the silence window before sending audio to Nova Sonic:

```python
def _capture_audio_frame(self) -> bytes:
    raw = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
    if time.time() < self._silence_until:
        # Send silence instead of real mic audio — prevents echo feedback
        return b'\x00' * len(raw)
    return raw
```

`SILENCE_BUFFER_SECS` (default: 0.15 s) adds a short tail after playback ends to absorb reverb and speaker decay. The gate is purely time-based — no signal processing required.

**Effect:** ARIA's speaker output is never sent to Nova Sonic's STT. The customer cannot interrupt ARIA while ARIA is speaking. After ARIA finishes, the gate lifts and normal microphone capture resumes.

### Barge-in mode — `NOVA_BARGE_IN=true`

Set the environment variable `NOVA_BARGE_IN=true` to remove the echo gate entirely:

```python
BARGE_IN_ENABLED = os.getenv("NOVA_BARGE_IN", "false").lower() == "true"

def _capture_audio_frame(self) -> bytes:
    raw = self._stream.read(CHUNK_SIZE, exception_on_overflow=False)
    if not BARGE_IN_ENABLED and time.time() < self._silence_until:
        return b'\x00' * len(raw)
    return raw
```

In barge-in mode, real microphone audio is sent at all times, including during ARIA's playback. This enables the customer to interrupt ARIA mid-sentence — a natural conversational capability.

**Interrupt handling:** Nova Sonic detects that the customer has spoken over ARIA and sends a `textOutput` event with `role=ASSISTANT` and `content='{"interrupted": true}'`. On receipt:

```python
async def _handle_interrupt(self):
    # Clear queued audio — stop playing what ARIA was saying
    while not self._audio_queue.empty():
        self._audio_queue.get_nowait()
    # Reset echo gate (irrelevant in barge-in mode, but defensive)
    self._silence_until = 0.0
    # Log interrupt for transcript
    self._transcript_buffer.append("[INTERRUPTED]")
```

**Requirement:** Barge-in mode requires headphones. Without physical separation of input and output, the mic will pick up ARIA's speaker audio and cause the echo loop the gate prevents.

### Why this two-mode design

**Works with any hardware by default:** The echo gate allows ARIA to function correctly on a laptop with built-in speakers and microphone — no peripheral requirement for basic use or development.

**Makes the headphone requirement explicit:** Rather than silently degrading (self-conversation loop) or hard-failing (refusing to start without headphones), the opt-in flag makes the trade-off visible. `NOVA_BARGE_IN=true` is a deliberate choice with a documented requirement.

**Lightweight implementation:** RMS-based or time-based silence gating requires no signal processing library. `numpy`, `webrtcvad`, or `webrtc-noise-cancellation` are not needed. The gate is a single `time.time()` comparison.

**Matches production voice banking patterns:** IVR systems (Interactive Voice Response) do not support barge-in by default — customers must wait for the prompt to finish before speaking. Contact centre voice agents support barge-in for trained agents using headsets. This two-mode design mirrors that established pattern.

## Consequences

### What this enables

- Local voice mode works on any development laptop with built-in speakers, with no hardware requirements
- Barge-in (natural interruption) is available for demos and production use with headphones via a single env var
- Interrupt handling is clean — queued audio is cleared immediately on Nova Sonic's interrupt signal
- No additional Python dependencies for echo suppression in default mode

### Trade-offs and limitations

- **Default mode only:** The customer must wait for ARIA to finish speaking before responding. This is acceptable for banking interactions (where ARIA speaks relatively short responses) but is noticeable in longer explanations
- **No partial barge-in:** There is no mode where barge-in works without headphones. Software AEC could theoretically enable this but is not implemented (see alternatives)
- **AgentCore cloud mode:** In `aria/agentcore_voice.py` (WebSocket server), echo gate is the client application's responsibility. The ARIA server streams audio bytes; the mobile or web client must apply native AEC (Web Audio API, iOS AVAudioSession, Android AudioRecord). Browser-based clients using the Web Audio API will not exhibit the echo problem
- **Silence buffer tuning:** `SILENCE_BUFFER_SECS` may need adjustment for environments with long reverb (large rooms, external speakers). Currently hardcoded; could be made configurable

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| Always require headphones | Degrades developer and demo UX significantly; makes the project unusable without a peripheral; not appropriate for a development tool |
| Software AEC via `numpy` + signal correlation | High complexity; platform-specific behaviour; added latency (correlation window must be large enough to capture speaker delay); brittle in practice — room acoustics vary |
| `webrtc-noise-cancellation` / `webrtcvad` | Additional native dependency with C extension; adds build complexity; `webrtcvad` only detects voice activity, it does not perform echo cancellation |
| Separate record/playback threads with RMS comparison | Complex synchronisation required; requires estimating speaker delay to correlate signals; brittle — delay varies by hardware and OS audio stack |
| Disable microphone during playback (OS-level mute) | Platform-specific (macOS, Linux, Windows each differ); unreliable timing; OS mute operations introduce audible artefacts |

## Implementation reference

| File | Role |
|---|---|
| `aria/voice_agent.py` | `_capture_audio_frame()` — echo gate and barge-in logic |
| `aria/voice_agent.py` | `_handle_interrupt()` — clears audio queue on Nova Sonic interrupt signal |
| `aria/voice_agent.py` | `_silence_until` — float timestamp set when audio playback begins |
| `aria/voice_agent.py` | `BARGE_IN_ENABLED` — reads `NOVA_BARGE_IN` env var at module import |
| `aria/agentcore_voice.py` | Cloud voice WebSocket server — echo gate is client responsibility |

## Related documents

- [ADR-005: Nova Sonic 2 S2S — Direct aws_sdk_bedrock_runtime API](ADR-005-nova-sonic-direct-api.md)
