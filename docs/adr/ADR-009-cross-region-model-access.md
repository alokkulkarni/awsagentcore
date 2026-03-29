# ADR-009: Cross-Region Model Access — Claude in eu-west-2, Nova Sonic in eu-north-1

**Status:** Accepted  
**Date:** 2026-03-29  
**Deciders:** ARIA Engineering  

---

## Context

ARIA targets UK banking customers, so primary compute and data storage should reside in `eu-west-2` (London) for data residency and regulatory alignment with UK GDPR (post-Brexit) and FCA requirements. However:

- Amazon Bedrock model availability varies by region and changes over time.
- **Claude Sonnet** (used for chat/text inference) was available in `eu-west-2` at time of deployment.
- **Amazon Nova Sonic 2** (used for voice/speech-to-speech) was **not** available in `eu-west-2` at time of deployment; the closest available regions were `eu-north-1` (Stockholm) and `us-east-1` (N. Virginia).

A decision is required on how to handle model availability gaps without relocating the entire stack out of London.

## Decision

- **AgentCore Runtime** is hosted in `eu-west-2` (London).
- **Chat agent (Claude Sonnet)** is invoked in `eu-west-2` — same region as the Runtime; no cross-region call.
- **Voice agent (Nova Sonic 2)** is invoked via a cross-region call to `eu-north-1` (Stockholm) — the nearest EU region where Nova Sonic 2 is available.

Two separate boto3 clients are constructed with different region configurations:

```python
import os
import boto3

BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "eu-west-2")      # Claude / chat
NOVA_SONIC_REGION = os.environ.get("NOVA_SONIC_REGION", "eu-north-1")  # Nova Sonic / voice

chat_bedrock_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
voice_bedrock_client = boto3.client("bedrock-runtime", region_name=NOVA_SONIC_REGION)
```

Both regions are configurable via environment variables, allowing region overrides at deployment time without code changes.

**Supporting infrastructure region assignments:**

| Component | Region | Rationale |
|---|---|---|
| AgentCore Runtime | eu-west-2 | Primary UK compute |
| AgentCore Memory API | eu-west-2 | Co-located with Runtime |
| Claude Sonnet (chat) | eu-west-2 | Available; no cross-region needed |
| Nova Sonic 2 (voice) | eu-north-1 | Not yet available in eu-west-2 |
| Transcript S3 bucket | eu-west-2 | UK GDPR / data residency |
| Audit EventBridge bus | eu-west-2 | Co-located with Runtime and audit consumers |

**Cross-region latency analysis:**

- `eu-west-2` → `eu-north-1` round-trip: ~15–25 ms (within Europe, AWS backbone).
- A Nova Sonic voice turn is ~1,500–3,000 ms end-to-end (speech recognition + inference + speech synthesis).
- The 15–25 ms cross-region hop is <2% of total turn latency — negligible in practice.
- Nova Sonic uses a **bidirectional streaming session** — the cross-region latency cost is paid once at session open, not repeated per utterance within the session.

**IAM configuration note:**

The AgentCore execution role must have `bedrock:InvokeModel` (and `bedrock:InvokeModelWithResponseStream`) permission scoped to the `eu-north-1` endpoint for Nova Sonic 2. The resource ARN format is:

```
arn:aws:bedrock:eu-north-1::foundation-model/amazon.nova-sonic-v2:0
```

This must be explicitly included in the role's permission policy — it is not implied by a `eu-west-2` wildcard.

**GDPR / UK GDPR note:**

Nova Sonic audio buffers transit through `eu-north-1` (Stockholm, Sweden). This is within the EU and compliant with EU GDPR (GDPR Regulation 2016/679). However, post-Brexit, UK GDPR (UK Data Protection Act 2018) applies to UK customer data. Transfer of personal data from a UK-based service to an EU country (Sweden) is permitted under the UK GDPR adequacy decision for the EU (as of the date of this ADR). This should be reviewed with the Data Protection Officer (DPO) and documented in the Privacy Notice, particularly if the adequacy decision is revised or if the customer base includes data subjects requiring stricter UK-only residency.

## Consequences

### What this enables

- Voice capability (Nova Sonic 2) is available without waiting for `eu-west-2` regional rollout — which had no published timeline at time of deployment.
- Primary compute, storage, and audit infrastructure remain in London, satisfying FCA and UK GDPR data residency requirements for the majority of data flows.
- Region assignments are environment-variable driven; if Nova Sonic 2 becomes available in `eu-west-2`, the deployment can switch with a config change and redeploy — no code change required.

### Trade-offs and limitations

- Audio buffers for voice sessions transit through EU infrastructure outside the UK. Acceptable under current GDPR adequacy rules but should be reviewed if the legal basis changes.
- Two AWS regions are used, adding minor complexity to IAM policy management and cost attribution.
- If `eu-north-1` has an availability event, voice capability is degraded. Chat continues unaffected in `eu-west-2`.
- Bedrock cross-region inference profiles (for automatic multi-region failover) are not used — direct model ARN access is sufficient for the current single-region voice target and avoids added configuration complexity.

### Alternatives considered

| Alternative | Reason rejected |
|---|---|
| Deploy everything in us-east-1 | Wrong jurisdiction for UK banking customers; GDPR/UK GDPR data residency concern |
| Deploy in eu-north-1 | Claude Sonnet availability uncertain in eu-north-1; primary compute should be in London (eu-west-2) for UK banking |
| Wait for Nova Sonic in eu-west-2 | No published timeline; voice feature deployment would be blocked indefinitely |
| Use Amazon Polly TTS + Transcribe STT + Claude in eu-west-2 | Loses native speech-to-speech capability; higher latency (two extra API calls per turn); see ADR-005 for voice model decision |
| Bedrock inference profiles for cross-region failover | Adds configuration complexity; direct model ARN sufficient for current single-region voice target |

## Implementation reference

| File | Role |
|---|---|
| `aria/voice_agent.py` | Constructs `voice_bedrock_client` with `NOVA_SONIC_REGION`; Nova Sonic session management |
| `aria/agentcore_voice.py` | Same `voice_bedrock_client` pattern for AgentCore-hosted voice sessions |
| `aria/agent.py` | Constructs `chat_bedrock_client` with `BEDROCK_REGION` for Claude Sonnet |
| `.bedrock_agentcore.yaml` | Declares `BEDROCK_REGION` and `NOVA_SONIC_REGION` environment variables for the container |

## Related documents

- [ADR-005](ADR-005-nova-sonic-voice-model.md) — decision to use Nova Sonic 2 for speech-to-speech
- [ADR-007](ADR-007-agentcore-docker-ecr.md) — AgentCore Runtime deployment in eu-west-2
- [docs/agentcore-deployment-guide.md](../agentcore-deployment-guide.md) — IAM role configuration for cross-region Bedrock access
