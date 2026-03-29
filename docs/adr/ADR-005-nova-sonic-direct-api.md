# ADR-005: Nova Sonic 2 S2S — Direct aws_sdk_bedrock_runtime API over Strands Bidi SDK

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

ARIA's voice channel requires speech-to-speech capability. The customer speaks to ARIA; ARIA reasons, calls banking tools, and responds in natural voice. Two architectural approaches were evaluated:

**Option A — TTS pipeline (three services):**  
Customer speech → Whisper/Amazon Transcribe (STT) → Claude text agent → Amazon Polly / ElevenLabs (TTS) → customer audio

**Option B — Nova Sonic 2 S2S (single model):**  
Customer speech → Nova Sonic 2 bidirectional stream (STT + reasoning + tool calling + TTS) → customer audio

Within Option B, two implementation paths were available:

- **Path B1:** Strands bidi SDK — `strands-agents[bidi]`, `BidiAgent`, `BidiNovaSonicModel`
- **Path B2:** Direct `aws_sdk_bedrock_runtime` API — `InvokeModelWithBidirectionalStream`

Path B1 was implemented first and abandoned. Path B2 is the implemented solution.

## Decision

**Nova Sonic 2 S2S via the direct `aws_sdk_bedrock_runtime` API (`InvokeModelWithBidirectionalStream`).**

### Why Nova Sonic 2 S2S over the TTS pipeline (Option A vs B)

- **Latency:** Single model eliminates the STT → LLM → TTS chain. Each hop in Option A adds 100–500 ms; Nova Sonic handles all three in one bidirectional stream
- **Voice quality:** Nova Sonic produces natural speech with prosody and emphasis; Polly neural voices are good but cannot match a native S2S model's emotional range
- **Barge-in / interrupt support:** Nova Sonic sends an `{"interrupted": true}` signal in `textOutput` when the customer speaks over ARIA. Option A has no native interrupt mechanism — the application would need silence detection + manual TTS cancellation
- **Tool calling:** Nova Sonic 2 handles tool calling natively inside the bidirectional stream — `toolUse` events arrive in the event stream alongside audio; Option A routes all tool calls through a separate Claude text agent

### Why direct API over Strands bidi SDK (Path B1 → Path B2)

Path B1 (`BidiAgent` + `BidiNovaSonicModel`) was implemented and tested. It was abandoned due to the following breaking issues encountered at time of implementation:

**Issue 1 — Premature `stop_conversation`:**  
Injecting session context via `messages=[...]` on `BidiAgent` caused a premature `stop_conversation` signal to be sent before the customer spoke. The session terminated immediately after the system prompt preamble. Root cause: `BidiAgent` sent a contentEnd event on the injected messages before the microphone stream opened.

**Issue 2 — `KeyError: 'maxTokens'`:**  
The Strands bidi SDK used camelCase keys internally (`maxTokens`) but the `aws_sdk_bedrock_runtime` client expected snake_case keys (`max_tokens`). This caused a `KeyError` on the first inference config serialisation. Workaround was possible but fragile.

**Issue 3 — `SmithyIdentityError: 'Credentials' object has no attribute 'resolve'`:**  
`BidiNovaSonicModel`'s credential resolver was incompatible with the boto3 credential chain (env vars, `~/.aws`, instance profile). It required wrapping frozen credentials in a `_StaticResolver` class to satisfy the Smithy identity protocol — an undocumented workaround that would break on any SDK update.

**Issue 4 — Experimental status:**  
`strands-agents[bidi]` is explicitly marked `experimental` in the Strands SDK. No SLA, no stability guarantee, breaking changes expected in future minor versions.

The direct API gives full control over the bidirectional event protocol with no abstraction layer between ARIA and Bedrock.

### Implementation: `ARIANovaSonicSession`

`aria/voice_agent.py` implements `ARIANovaSonicSession`:

**Credential setup:**

```python
def _build_boto_session(self) -> boto3.Session:
    # Full credential chain: env vars → ~/.aws → instance profile → role assumption
    session = boto3.Session(region_name=self.region)
    if self.role_arn:
        creds = session.get_credentials().get_frozen_credentials()
        session = _assume_role(session, self.role_arn)
    return session

def _initialize_client(self):
    frozen = self._boto_session.get_credentials().get_frozen_credentials()
    resolver = _StaticResolver(frozen)  # wraps boto3 creds into Smithy identity
    config = Config(aws_credentials_identity_resolver=resolver)
    self._client = bedrock_runtime.BedrockRuntimeClient(
        region=self.region, config=config
    )
```

**Session context injection via system prompt preamble:**

```python
def _build_voice_system_prompt(self) -> str:
    preamble = (
        "VOICE PREAMBLE: You are speaking to a customer over voice. "
        "Keep responses concise and conversational. "
        "Do not use markdown, bullet points, or formatting. "
    )
    return preamble + ARIA_SYSTEM_PROMPT
```

Session context is injected via the `systemPrompt` field in the `sessionStart` event — not via `messages`. This is the correct method for Nova Sonic S2S session initialisation.

**Event dispatch:**

```python
async def _handle_event(self, event: dict):
    match event:
        case {"textOutput": {"role": "ASSISTANT", "content": content}}:
            if '"interrupted": true' in content:
                await self._handle_interrupt()
            else:
                self._transcript_buffer.append(content)
        case {"audioOutput": {"content": audio_bytes}}:
            await self._audio_queue.put(audio_bytes)
        case {"toolUse": tool_event}:
            await self._dispatch_tool(tool_event)
        case {"contentEnd": _}:
            await self._flush_transcript()
        case {"completionEnd": _}:
            self._turn_complete.set()
```

**Tool dispatch — direct, not via Strands Agent:**

```python
async def _dispatch_tool(self, tool_event: dict):
    tool_name = tool_event["toolName"]
    tool_input = json.loads(tool_event["content"])
    tool_fn = self._tool_map.get(tool_name)
    result = await asyncio.to_thread(tool_fn, **tool_input)
    await self._send_tool_result(tool_event["toolUseId"], result)
```

`_tool_map` is built from `ALL_TOOLS` at session initialisation: `{fn.__name__: fn for fn in ALL_TOOLS}`. Tools are called directly — the Strands `Agent` object is not used in the voice path, as it is designed for the text Converse API, not the Nova Sonic event stream.

## Consequences

### What this enables

- Full speech-to-speech with sub-second perceived latency on tool calls
- Native barge-in / interrupt support via Nova Sonic's `{"interrupted": true}` signal
- No external TTS or STT services — single Bedrock API call per session
- Complete control over the bidirectional event protocol — any event type can be handled without SDK workarounds
- Credentials resolved via the standard boto3 chain — works with env vars, AWS profiles, and IAM roles

### Trade-offs and limitations

- The voice path (`aria/voice_agent.py`) does not use the Strands `Agent` object — tools must be registered in both `ALL_TOOLS` (for Strands) and `_tool_map` (for voice). Adding a new tool requires updating both
- `_StaticResolver` is an internal workaround for Smithy credential compatibility — must be reviewed on `aws_sdk_bedrock_runtime` SDK upgrades
- Nova Sonic 2 is a preview model — tool calling spec and event format may change before GA
- Local voice mode requires PyAudio (see ADR-006 for echo gate design)

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| Strands bidi SDK (`BidiAgent` + `BidiNovaSonicModel`) | Tried and abandoned: premature `stop_conversation`, `KeyError: 'maxTokens'`, `SmithyIdentityError` credential incompatibility, marked `experimental` |
| Polly TTS + Transcribe STT + Claude text agent | Three services: higher latency (3 × network hops), no native barge-in, more complex error handling, higher per-session cost |
| Amazon Connect (contact centre platform) | Not appropriate for programmatic agent-driven calls; requires Connect instance setup; designed for human-agent routing, not LLM-driven banking sessions |
| ElevenLabs TTS | External third-party service; data sharing implications for banking PII; higher latency than native Bedrock |

## Implementation reference

| File | Role |
|---|---|
| `aria/voice_agent.py` | `ARIANovaSonicSession` — full bidirectional stream implementation |
| `aria/voice_agent.py` | `_StaticResolver` — Smithy identity wrapper for boto3 credentials |
| `aria/voice_agent.py` | `_build_voice_system_prompt()` — VOICE PREAMBLE + ARIA_SYSTEM_PROMPT |
| `aria/voice_agent.py` | `_dispatch_tool()` / `_execute_tool()` — direct tool dispatch via `_tool_map` |
| `aria/tools/__init__.py` | `ALL_TOOLS` — source for `_tool_map` construction |
| `aria/agentcore_voice.py` | AgentCore WebSocket voice endpoint wrapping `ARIANovaSonicSession` |

## Related documents

- [ADR-002: Strands Agents as the AI Agent Framework](ADR-002-strands-agents-framework.md)
- [ADR-006: PyAudio Echo Gate + NOVA_BARGE_IN Opt-In](ADR-006-echo-gate-barge-in.md)
- [ADR-003: Modular One-File-Per-Tool Architecture](ADR-003-modular-tool-architecture.md)
