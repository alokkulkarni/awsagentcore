# aria-evaluator-v2

LLM-as-judge evaluator for Amazon Connect AI Agents (and any other agent via the pluggable adapter interface).

## How it differs from v1

| | v1 | v2 |
|---|---|---|
| Connection | `CONNECTION_CREDENTIALS` → polling | `WEBSOCKET + CONNECTION_CREDENTIALS` → push |
| Message receipt | `get_transcript` every 1–5 s | WebSocket push (sub-second, same as chat widget) |
| Transcript | Read from Connect API | Local JSON file built during run |
| Evaluation timing | Inline during conversation | Post-conversation (decoupled) |
| Replay | Must re-run conversation | Re-evaluate saved transcript JSON |
| Agent support | Connect only | Generic `BaseAdapter` interface |

## Architecture

```
YAML Scenario
     ↓
ScenarioRunner (asyncio)
     ↓
BaseAdapter (pluggable)
  └─ ConnectWebSocketAdapter
       ├── start_chat_contact (boto3)
       ├── create_participant_connection(WEBSOCKET + CONNECTION_CREDENTIALS)
       ├── WebSocket receiver → asyncio.Queue (no polling)
       └── send_message / typing events (boto3)
     ↓
Local Transcript JSON   ← saved to transcripts/ after each run
     ↓
LLM Judge (Bedrock Converse)
     ↓
Report Generator (HTML + JSON)
```

## Install

```bash
cd aria-evaluator-v2
python3 -m venv venv
source venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env with your values
```

## Environment variables (`.env`)

| Variable | Required | Description |
|---|---|---|
| `CONNECT_INSTANCE_ID` | ✅ | Amazon Connect instance ID |
| `CONNECT_REGION` | ✅ | AWS region (e.g. `eu-west-2`) |
| `CONNECT_CONTACT_FLOW_ID` | one of | Contact flow ID |
| `CONNECT_CONTACT_FLOW_NAME` | one of | Contact flow name (auto-discovers ID) |
| `CONNECT_VOICE_FLOW_ID` | recommended for voice | Explicit WebRTC voice flow ID (used by `--channel voice`) |
| `CONNECT_VOICE_FLOW_NAME` | optional | Voice flow name (auto-discovers ID if `CONNECT_VOICE_FLOW_ID` is unset) |
| `JUDGE_MODEL_ID` | ✅ | Bedrock model for LLM judge |
| `BEDROCK_REGION` | | Bedrock region (defaults to CONNECT_REGION) |
| `EVAL_CUSTOMER_ID` | | Customer ID injected into SESSION_START |
| `EVAL_DISPLAY_NAME` | | Display name in Connect transcript |
| `EVAL_CHAT_DURATION_MINUTES` | | Chat session lifetime (min 60, default 60) |
| `EVAL_RESPONSE_TIMEOUT_SECONDS` | | Per-turn agent response timeout (default 90) |
| `EVAL_REPORT_OUTPUT_DIR` | | Report output directory (default `./reports`) |
| `WEBSOCKET_IDLE_TIMEOUT_SECONDS` | | WebSocket idle reconnect timeout (default 120) |
| `VOICE_PREFER_RELAY` | | Prefer TURN relay ICE candidates for voice (`0` default, set `1` to enable) |

> For voice evaluations, set `CONNECT_VOICE_FLOW_ID` (or `CONNECT_VOICE_FLOW_NAME`) to a **WebRTC-capable voice flow**. Reusing a chat-only flow typically results in first-turn voice timeouts with no inbound audio.

## Running

```bash
# All scenarios (conversation + evaluation + report)
python scripts/run_evaluation.py

# One scenario by path fragment
python scripts/run_evaluation.py --scenario banking/account_query

# Re-evaluate a saved transcript (no conversation re-run needed)
python scripts/run_evaluation.py --transcript transcripts/account_query_2026-04-28T09-52-00.json

# Conversation only — save transcripts, skip LLM judge and report
python scripts/run_evaluation.py --conversation-only

# Custom report output directory
python scripts/run_evaluation.py --report-dir reports/sprint-42
```

## Saved transcript format

Each run saves a JSON file to `transcripts/`:

```json
{
  "schema_version": "2.0",
  "scenario_id": "account_balance_enquiry_authenticated",
  "scenario_name": "Account — Balance Enquiry Authenticated",
  "customer_id": "CUST-001",
  "channel": "chat",
  "mode": "agent",
  "started_at": "2026-04-28T09:52:00Z",
  "ended_at": "2026-04-28T09:53:42Z",
  "metadata": { "contact_id": "abc-123", "goal_achieved": true },
  "turns": [
    { "role": "customer", "content": "Hi, I'd like to check my balance", "timestamp": "...", "latency_ms": null },
    { "role": "agent",    "content": "Hi Emma, your balance is ...",     "timestamp": "...", "latency_ms": 840 }
  ]
}
```

## Adding a new agent adapter

1. Create `adapters/my_agent.py` subclassing `BaseAdapter`:

```python
from adapters import BaseAdapter, AdapterMessage

class MyAgentAdapter(BaseAdapter):
    async def connect(self, session_id, customer_id=None, authenticated=False, **kw): ...
    async def send_message(self, content, simulate_typing=True): ...
    async def receive(self, timeout=60.0) -> AdapterMessage | None: ...
    async def disconnect(self): ...
```

2. Pass an instance to `ScenarioRunner` — no other changes needed.

## Directory structure

```
aria-evaluator-v2/
├── adapters/
│   ├── __init__.py          # BaseAdapter + AdapterMessage
│   └── connect_ws.py        # Amazon Connect WebSocket adapter
├── conversation/
│   ├── driver.py            # AgentDriver (LLM-as-customer)
│   └── runner.py            # ScenarioRunner
├── transcript/
│   └── models.py            # Transcript, Turn, TurnRole
├── judge/                   # LLM-as-judge (ported from v1)
├── report/                  # Report generator (ported from v1)
├── scenarios/               # Symlink → ../aria-evaluator/scenarios
├── evaluator_configs/       # Symlink → ../aria-evaluator/evaluator_configs
├── transcripts/             # Auto-saved JSON transcripts
├── reports/                 # Generated HTML/JSON reports
└── scripts/
    └── run_evaluation.py    # CLI entry point
```
