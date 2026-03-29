# ARIA — Banking Audit Event Architecture

## What is an audit event in banking?

An audit event is an **immutable, timestamped record** of every consequential action
taken on behalf of or affecting a customer. In regulated banking:

- **FCA (Financial Conduct Authority)** requires firms to record all instructions,
  orders, and customer-affecting actions with sufficient detail to reconstruct events
- **PCI-DSS** requires audit trails for all access to cardholder data environments
- **GDPR** requires a lawful basis record for every access to personal data
- **SOX** requires immutable records for financial data changes
- **Internal governance** requires a complete trail for complaints, disputes, and
  agent quality review

Audit events are **not the same as logs or transcripts**:

| | Logs | Transcripts | Audit events |
|---|---|---|---|
| Purpose | Debugging, operations | Training, QA | Regulatory compliance |
| Format | Unstructured text | Markdown conversation | Structured JSON, immutable |
| Retention | 30–90 days | 1–7 years | 7 years minimum (FCA) |
| Tamper-proof | No | No | Yes (WORM / cryptographic) |
| Queryable | CloudWatch Insights | Athena on S3 | SQL (CloudTrail Lake / DynamoDB) |

---

## Which ARIA tools generate audit events?

### Tier 1 — Critical (irreversible or high-value actions)

These must be audited before and after every invocation, including failures.

| Tool | Action | Regulatory trigger |
|---|---|---|
| `block_debit_card` | Card block — irreversible | PCI-DSS, FCA COBS |
| `escalate_to_human_agent` | Routing of vulnerable/distressed customer | FCA CONC, vulnerability rules |
| `validate_customer_auth` | Authentication attempt (success or failure) | FCA, fraud prevention |
| `verify_customer_identity` | KBA pass/fail | FCA SYSC, fraud |
| `cross_validate_session_identity` | Cross-channel identity confirmation | FCA SYSC |

> **Future tools** that will also be Tier 1: `replace_card`, `update_address`,
> `change_contact_details`, `order_statement`, `set_up_standing_order`,
> `make_payment`, `increase_credit_limit`, `close_account`

### Tier 2 — Significant (data access, PII, financial data)

These must be audited for GDPR data access records and PCI-DSS cardholder data access.

| Tool | Action | Regulatory trigger |
|---|---|---|
| `get_customer_details` | Access to PII profile | GDPR Article 5, PCI-DSS |
| `get_account_details` | Access to account and balance data | GDPR, FCA COBS |
| `get_debit_card_details` | Access to cardholder data | PCI-DSS Requirement 10 |
| `get_credit_card_details` | Access to cardholder data | PCI-DSS Requirement 10 |
| `get_mortgage_details` | Access to mortgage/lending data | FCA MCOB |
| `analyse_spending` | Access to transaction history | GDPR, FCA COBS |
| `initiate_customer_auth` | Start of auth flow | FCA SYSC |
| `pii_vault_store` | PII token stored | GDPR |
| `pii_vault_retrieve` | PII token accessed | GDPR |

### Tier 3 — Informational (no customer data affected)

Audit optional — good practice for completeness but not regulatory-critical.

| Tool | Action |
|---|---|
| `get_product_catalogue` | Public product data |
| `search_knowledge_base` | Public KB search |
| `get_feature_parity` | Feature comparison data |
| `generate_transcript_summary` | Internal summarisation |
| `pii_detect_and_redact` | PII detection (no storage) |
| `pii_vault_purge` | PII deletion (log the purge as Tier 2) |

---

## Audit event record structure

Every audit event is a structured JSON object:

```json
{
  "event_id":     "a3f7c2d1-...",
  "event_type":   "CARD_BLOCK",
  "category":     "CARD_MANAGEMENT",
  "tier":         1,
  "severity":     "HIGH",

  "timestamp":    "2026-03-29T10:58:32.123Z",
  "session_id":   "3f7a1b2c-...",
  "customer_id":  "CUST-001",
  "channel":      "voice",

  "actor":        "ARIA",
  "actor_type":   "AI_AGENT",
  "tool_name":    "block_debit_card",

  "action":       "BLOCK_DEBIT_CARD",
  "parameters": {
    "card_last_four": "1234",
    "card_type":      "debit",
    "reason":         "lost"
  },

  "outcome":        "SUCCESS",
  "error_message":  null,

  "authenticated":  true,
  "risk_level":     "HIGH",
  "pii_accessed":   false,

  "source_ip":      null,
  "user_agent":     "ARIA/1.0 AgentCore"
}
```

---

## Where to store audit events

### Local mode (running via `main.py`)

Write audit events to JSONL files in an `audit/` directory, structured by customer
ID and date — the same pattern as transcripts:

```
audit/
  CUST-001/
    2026-03-29/
      audit.jsonl        ← one JSON object per line, append-only
  CUST-002/
    2026-03-29/
      audit.jsonl
```

JSONL (one event per line) makes the files easily ingestible into any analytics
pipeline without parsing structure. Each line is a complete, self-contained
audit event.

### Cloud / AgentCore mode — three-tier storage

#### Tier 1: AWS CloudTrail Lake (primary — immutable, SQL-queryable)

CloudTrail Lake supports **custom events** via `cloudtrail:PutAuditEvents`. This
is the purpose-built AWS service for immutable audit trails:

- Events are **cryptographically verifiable** — CloudTrail signs event data
- **Immutable** — events cannot be deleted or modified after ingestion
- Retention up to **7 years** (configurable)
- **SQL queryable** via CloudTrail Lake query editor — find all card blocks for
  a customer, all auth failures in a time window, etc.
- Integrates with AWS Security Hub and Amazon GuardDuty for anomaly detection
- Directly satisfies FCA, PCI-DSS Requirement 10, and SOX audit requirements

```python
# How ARIA emits a custom audit event to CloudTrail Lake
cloudtrail = boto3.client("cloudtrail-data", region_name="eu-west-2")
cloudtrail.put_audit_events(
    auditEvents=[{
        "id":         event_id,
        "eventData":  json.dumps(audit_record),
    }],
    channelArn="arn:aws:cloudtrail:eu-west-2:<account>:channel/<channel-id>"
)
```

> You must first create a CloudTrail Lake **event data store** and a **channel**
> for custom events in the CloudTrail console. The channel ARN is then set as
> `AUDIT_CLOUDTRAIL_CHANNEL_ARN` in the Runtime env vars.

#### Tier 2: Amazon DynamoDB (hot — real-time querying, last 90 days)

A DynamoDB table provides fast lookup for:
- Customer service agents reviewing recent actions during a complaint
- Real-time fraud detection queries
- Management information dashboards

```
Table: aria-audit-events
  Partition key: customer_id     (e.g. "CUST-001")
  Sort key:      timestamp        (ISO 8601)
  GSI:           event_type + timestamp (for querying "all card blocks today")
  TTL:           90 days (auto-expire old records — keep cold copy in CloudTrail/S3)
```

#### Tier 3: Amazon S3 + Object Lock (cold — 7-year compliance archive)

S3 Object Lock in **COMPLIANCE mode** creates WORM (Write Once Read Many) objects
that cannot be deleted or overwritten — not even by the root account:

```
s3://meridian-aria-audit-<account>/
  audit-events/
    CUST-001/
      2026/03/29/
        10-58-32_a3f7c2d1.jsonl
```

- Object Lock COMPLIANCE mode: no deletion for defined retention period
- Enable S3 Versioning + MFA Delete for extra protection
- S3 Glacier Instant Retrieval for cost-efficient long-term storage
- Athena can query across all events: `SELECT * WHERE event_type='CARD_BLOCK' AND customer_id='CUST-001'`

---

## Routing: Amazon EventBridge

All audit events should be published to an **EventBridge event bus** first.
EventBridge then fans out to all three destinations (CloudTrail Lake, DynamoDB,
S3/Firehose) simultaneously, and to any additional consumers:

```
ARIA Tool Execution
        │
        ▼
  EventBridge (custom bus: aria-audit)
        │
        ├──► CloudTrail Lake (via CloudTrail channel)    — immutable, 7yr
        ├──► DynamoDB (via Lambda or Pipes)              — hot queries, 90d
        ├──► Kinesis Firehose → S3 Object Lock           — WORM archive
        ├──► Security Hub                                — anomaly detection
        └──► SIEM (Splunk / Datadog)                     — real-time monitoring
```

This decouples the ARIA code from the storage backend — a new audit consumer can
be added by creating an EventBridge rule with no code changes to ARIA.

---

## How ARIA emits audit events (implementation approach)

### AuditManager class

An `AuditManager` (similar to `TranscriptManager`) handles event construction and
routing. It sits in the tool execution path:

```python
# aria/audit_manager.py

class AuditManager:
    def record(
        self,
        tool_name: str,
        customer_id: str,
        session_id: str,
        channel: str,
        authenticated: bool,
        parameters: dict,
        outcome: str,          # "SUCCESS" | "FAILURE"
        error_message: str = None,
    ) -> None:
        event = self._build_event(...)
        self._emit(event)      # local JSONL or EventBridge depending on env
```

### Where to hook into the tool execution pipeline

The audit hook goes in the tool dispatcher in each channel:

**Chat (agentcore_app.py and main.py):** The Strands agent handles tool calls
internally. The cleanest hook is a **Strands callback handler** that fires on
`tool_use` and `tool_result` events, capturing the tool name, input, and output.

**Voice (voice_agent.py and agentcore_voice.py):** Tool calls go through
`_execute_tool()`. Wrap that method — record before execution (with parameters),
record after (with outcome). This is already a single, centralised function in both
voice modules.

```python
async def _execute_tool(self, name, use_id, content_str):
    args = json.loads(content_str)
    # --- AUDIT: before ---
    audit.record(tool_name=name, parameters=args, outcome="PENDING", ...)

    try:
        result = await asyncio.to_thread(tool._tool_func, **args)
        # --- AUDIT: after (success) ---
        audit.record(tool_name=name, parameters=args, outcome="SUCCESS", ...)
        return json.dumps(result)
    except Exception as exc:
        # --- AUDIT: after (failure) ---
        audit.record(tool_name=name, parameters=args, outcome="FAILURE",
                     error_message=str(exc), ...)
        raise
```

---

## IAM permissions for audit emission

Add to the AgentCore Runtime execution role:

```json
{
  "Sid": "AuditCloudTrailLake",
  "Effect": "Allow",
  "Action": ["cloudtrail-data:PutAuditEvents"],
  "Resource": "arn:aws:cloudtrail:eu-west-2:<account>:channel/<channel-id>"
},
{
  "Sid": "AuditEventBridge",
  "Effect": "Allow",
  "Action": ["events:PutEvents"],
  "Resource": "arn:aws:events:eu-west-2:<account>:event-bus/aria-audit"
},
{
  "Sid": "AuditDynamoDB",
  "Effect": "Allow",
  "Action": ["dynamodb:PutItem"],
  "Resource": "arn:aws:dynamodb:eu-west-2:<account>:table/aria-audit-events"
}
```

---

## Full audit architecture

```
ARIA Tool Execution  (voice_agent.py / agentcore_app.py / agentcore_voice.py)
        │
        │  wrap _execute_tool() / Strands callback
        ▼
  AuditManager.record(tool_name, customer_id, session_id, params, outcome)
        │
        ├── LOCAL MODE
        │     └── audit/{customer_id}/{date}/audit.jsonl   (append-only JSONL)
        │
        └── CLOUD MODE (AgentCore)
              │
              ▼
        EventBridge (aria-audit custom bus)
              │
              ├──► CloudTrail Lake channel        ← immutable, 7yr, SQL queryable
              │                                      PRIMARY regulatory store
              │
              ├──► Lambda → DynamoDB              ← 90-day hot table
              │     aria-audit-events               for complaints / dashboards
              │
              ├──► Kinesis Firehose → S3 WORM     ← cold archive, Athena queryable
              │     Object Lock COMPLIANCE mode      PCI-DSS, FCA, SOX retention
              │
              └──► Security Hub / SIEM            ← real-time anomaly detection
```

---

## Summary: why CloudTrail Lake is the right primary store

| Requirement | CloudTrail Lake | DynamoDB | S3 Object Lock |
|---|---|---|---|
| Immutable (FCA/PCI-DSS) | ✅ Cryptographically signed | ❌ Records can be deleted | ✅ WORM in COMPLIANCE mode |
| SQL queryable | ✅ Native SQL in console | ✅ (via Athena + export) | ✅ Athena |
| Real-time lookup | ❌ Minutes delay | ✅ Milliseconds | ❌ |
| 7-year retention | ✅ Configurable | ❌ Cost-prohibitive at 7yr | ✅ Low cost in Glacier |
| AWS-native | ✅ | ✅ | ✅ |
| Custom events | ✅ `PutAuditEvents` | Via Lambda | Via Firehose |

Use all three together: **CloudTrail Lake** for compliance authority,
**DynamoDB** for fast operational queries, **S3 WORM** for long-term archive.
EventBridge routes to all three from a single emission point in ARIA.
