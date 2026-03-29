# ARIA — Transcript Storage Architecture

ARIA saves every conversation as a Markdown transcript, structured by customer ID
and timestamp.  The storage backend switches automatically based on the deployment
context: local `.md` files when running on your machine, Amazon S3 when running
on Amazon Bedrock AgentCore.

---

## Transcript format

Each transcript is a self-contained Markdown file:

```markdown
# ARIA Session Transcript

| Field | Value |
|-------|-------|
| **Session ID** | `3f7a1b2c-...` |
| **Customer ID** | `CUST-001` |
| **Channel** | chat |
| **Started** | 2026-03-29 10:47:06 UTC |
| **Authenticated** | Yes |

---

**[10:47:08] ARIA:** Hello James! How can I help you today?

**[10:47:15] Customer:** What is my current balance?

**[10:47:17] ARIA:** Your current balance is £5,240.00.
Your available balance is £5,240.00.

---

*Session ended: 2026-03-29 10:48:30 UTC*
*Duration: 1m 24s*
```

Both chat and voice channels produce the same format.  Voice transcripts contain
Nova Sonic's speech-to-text output; chat transcripts contain the raw typed input.

---

## Local mode (``main.py``)

When you run ARIA locally, transcripts are written to the `transcripts/` directory
in the project root.

### Directory layout

```
transcripts/
  CUST-001/
    2026-03-29/
      10-47-06_3f7a1b2c.md    ← {HH-MM-SS}_{session_id[:8]}.md
      14-22-11_9e3d45fa.md
  CUST-002/
    2026-03-30/
      09-05-33_bb12ef78.md
  anonymous/
    2026-03-29/
      11-30-00_c44a2190.md    ← unauthenticated session
```

### Configuration

| Environment variable | Default | Description |
|---|---|---|
| `TRANSCRIPT_DIR` | `./transcripts` | Root directory for local .md files |
| `TRANSCRIPT_STORE` | auto | Set to `local` to force local even when S3 is configured |

### Notes

- `transcripts/` is excluded from git (see `.gitignore`) — do not commit transcripts.
- Each session creates one file.  The file is written atomically at session end.
- For chat sessions the file is written when the customer types `quit` or
  presses Ctrl-C.  For voice sessions it is written after the farewell exchange
  completes or on Ctrl-C.

---

## AgentCore / cloud mode

When deployed on Amazon Bedrock AgentCore, the container has an **ephemeral
filesystem** — any files written to disk are lost when the microVM is recycled.
Transcripts must be persisted to an external store.

ARIA uses **Amazon S3** as the transcript store for AgentCore deployments.

### S3 key structure

```
s3://<bucket>/
  transcripts/
    CUST-001/
      2026/03/29/
        10-47-06_3f7a1b2cdef012345678.md
      2026/03/30/
        14-22-11_9e3d45fa...md
    CUST-002/
      2026/03/29/
        09-05-33_bb12ef78...md
    anonymous/
      2026/03/29/
        11-30-00_c44a2190...md
```

The year/month/day partitioning enables efficient querying with **Amazon Athena**
(for bulk analysis or model training dataset preparation) and lifecycle policies
(e.g., move transcripts older than 90 days to S3 Glacier).

### Configuration

| Environment variable | Required | Description |
|---|---|---|
| `TRANSCRIPT_S3_BUCKET` | **Yes** (cloud) | S3 bucket name |
| `TRANSCRIPT_S3_PREFIX` | No | Key prefix.  Default: `transcripts` |
| `TRANSCRIPT_STORE` | No | Set to `both` to write local + S3 simultaneously |
| `AWS_REGION` | Yes | Region for S3 client (same as Bedrock region) |

### IAM permissions required

Add to the AgentCore Runtime execution role:

```json
{
  "Effect": "Allow",
  "Action": [
    "s3:PutObject",
    "s3:PutObjectAcl"
  ],
  "Resource": "arn:aws:s3:::<bucket>/transcripts/*"
}
```

### Durability behaviour (AgentCore chat)

For chat sessions over AgentCore (`POST /invocations`), each invocation call is
independent — there is no persistent connection.  The transcript manager therefore
**saves after every turn** (overwrites the S3 object with the latest cumulative
content).  This means:

- If the microVM is recycled mid-session, the transcript up to the last completed
  turn is preserved in S3.
- The final save on session end (farewell detected) closes the transcript cleanly
  with a session-ended timestamp and duration.

For voice sessions (`WebSocket /ws`), the transcript is saved once at session end
since the connection is persistent.

---

## Why not CloudWatch Logs?

AgentCore Observability (CloudWatch + OTEL) records **metrics and spans** — latency,
token usage, error rates, trace trees.  It is the right place for operational
monitoring.

Conversation transcripts serve a different purpose: training data curation,
compliance audit, quality assurance, and model fine-tuning.  For these workloads:

| Requirement | CloudWatch Logs | Amazon S3 |
|---|---|---|
| Store full conversation text | Possible but costly at scale | ✅ Purpose-built |
| Query by customer ID / date range | Requires Log Insights (slow/expensive) | ✅ Athena + Glue |
| Lifecycle management (archive / delete) | Limited | ✅ S3 Lifecycle rules |
| ML training pipeline input | Not native | ✅ Direct SageMaker / Bedrock input |
| Per-file retention control | No | ✅ Object tags + policies |
| Cost at scale (millions of sessions) | High | Low (S3 Standard ~$0.023/GB) |

CloudWatch Logs should still be used for operational metrics and OTEL spans.
S3 is the correct store for transcript files.

---

## Using transcripts for training / validation

### Athena query example

```sql
-- Find all sessions for a customer in March 2026
SELECT *
FROM aria_transcripts
WHERE customer_id = 'CUST-001'
  AND year = '2026' AND month = '03'
ORDER BY day, session_time;
```

### Preparing a fine-tuning dataset

1. Query S3 transcripts with Athena or AWS Glue.
2. Filter by channel, date range, or outcome labels.
3. Convert to JSONL format for Bedrock model customisation:

```python
{"prompt": "Customer: What is my balance?",
 "completion": "ARIA: Your current balance is £5,240.00."}
```

4. Upload the JSONL to S3 and create a Bedrock model customisation job.

### Validation

Transcripts can be used as ground-truth data for:
- **Regression testing** — replay customer turns through the agent and diff ARIA's
  responses against the saved transcript.
- **Tool accuracy** — verify that ARIA called the correct tool(s) for a given query.
- **Empathy scoring** — run a secondary model or rule set over the transcript to
  check that ARIA acknowledged vulnerability or distress appropriately.

---

## Summary

| Context | Storage | File path |
|---|---|---|
| Local (`main.py --channel chat`) | Local `.md` | `transcripts/{cid}/{date}/{time}_{sid8}.md` |
| Local (`main.py --channel voice`) | Local `.md` | Same pattern, channel=voice |
| AgentCore chat (`/invocations`) | Amazon S3 | `s3://bucket/transcripts/{cid}/{yyyy}/{mm}/{dd}/{time}_{sid}.md` |
| AgentCore voice (`/ws`) | Amazon S3 | Same pattern, channel=agentcore-voice |
| `TRANSCRIPT_STORE=both` | Local + S3 | Both paths simultaneously |
