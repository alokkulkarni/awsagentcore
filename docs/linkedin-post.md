# LinkedIn Post — ARIA Banking Agent Stack

> **Copy-paste ready for LinkedIn.**
> Optimal length: ~2,400 characters (within LinkedIn's sweet spot for algorithmic reach).
> Recommended: post without the image first line, then edit to attach a screenshot of
> `docs/diagrams/05_agentcore_deployed_stack.png` as the post image.

---

## Post

I built a production-ready AI banking agent that handles voice and chat — compliantly — on AWS.

Here's what "production-ready" actually means when your industry is banking. 🧵

---

**The agent is called ARIA.**
Meridian Bank's Automated Responsive Intelligence Agent.

She can:
→ Authenticate you with knowledge-based questions
→ Tell you your balance, transactions, statements
→ Block a lost or stolen debit or credit card — instantly
→ Handle mortgage queries, spending insights, product recommendations
→ Escalate to a human with a full, PII-safe handoff transcript
→ Do all of that over **voice** — in real-time, speech-to-speech

No IVR menus. No "press 1 for balance". Just conversation.

---

**The interesting engineering:**

🔒 **PII never enters the model context.**
Every customer input is tokenised first. The LLM sees `vault://session/DOB` — not your date of birth. Raw values are retrieved just-in-time, in-process only, then discarded.

🎙️ **Voice is a single model, not a pipeline.**
Amazon Nova Sonic 2 handles speech-in → reasoning → tool calls → speech-out in one bidirectional stream. No STT → Claude → Polly chain. Lower latency, natural interruption (barge-in), and the model *understands* tone.

📋 **Audit is non-blocking.**
Every tool call — card block, account lookup, auth attempt — emits a structured compliance event. It fans out to CloudTrail Lake (7-year immutable, SQL-queryable), DynamoDB (90-day hot queries for complaints), and S3 WORM (PCI-DSS COMPLIANCE mode). Zero latency added to the agent. The customer never waits for compliance.

☁️ **One command deploys the entire stack.**
`./scripts/deploy.sh deploy`
That's it. It creates the S3 buckets, DynamoDB table, EventBridge bus, CloudTrail Lake, Lambda audit writers, Kinesis Firehose, patches the config, builds an ARM64 Docker image via CodeBuild (no local Docker needed), deploys to Amazon Bedrock AgentCore Runtime, and attaches all IAM policies.

---

**The stack, if you're curious:**

→ **Amazon Bedrock AgentCore** — managed session isolation, ARM64 containers, Memory API
→ **Strands Agents** (AWS open-source) — @tool decorator pattern, Bedrock-native
→ **Claude Sonnet 4.6** (eu-west-2) — reasoning, tool orchestration, banking empathy
→ **Nova Sonic 2** (eu-north-1) — speech-to-speech, cross-region from the same runtime
→ **EventBridge → CloudTrail Lake + DynamoDB + S3** — three-tier compliance audit
→ **20 modular banking tools** — one file per capability, domain-grouped, independently testable
→ **10 Architecture Decision Records** — every significant engineering choice documented, with context and alternatives rejected

---

**The part most AI demos skip:**

Vulnerability detection. ARIA identifies distress, confusion, and third-party coercion — from live speech or typed cues — and halts irreversible actions if pressure is suspected. Empathy isn't a nice-to-have in banking. It's a regulatory requirement.

---

We're at an inflection point.

The same stack that would have taken 18 months and a team of specialists to build in 2022 now takes weeks with the right primitives.

The primitives are here. The compliance patterns are solvable. The voice models are good enough.

The only question is whether your team builds this before your competitors do.

---

What aspect would you want to dig into?
The voice architecture, the PII vault design, the compliance audit stack, or the AgentCore deployment model?

Drop a comment. Happy to go deep on any of it. 👇

---

#AI #GenerativeAI #AWSBedrock #BankingTechnology #ConversationalAI #VoiceAI #FinTech #MachineLearning #CloudArchitecture #AmazonBedrock #AgentCore #LLM #AIAgents #FCA #PCISD #SoftwareEngineering #Innovation

---

## Suggested image

Attach `docs/diagrams/05_agentcore_deployed_stack.png` — the full deployed stack diagram
showing mobile/web → Cognito → AgentCore Runtime → all AWS services.
It gives the post an instant visual anchor and stops the scroll.

## Suggested posting time

Tuesday–Thursday, 08:00–09:30 or 17:00–18:30 in your timezone.
These windows consistently outperform for technical content on LinkedIn.

## First comment (pin immediately after posting)

> 🧵 For those who want to go deeper:
>
> → GitHub: github.com/alokkulkarni/awsagentcore
> → Architecture diagrams, 10 ADRs, and the full deployment guide are all in the repo.
>
> One-command deploy: `./scripts/deploy.sh deploy`
> Tears everything down cleanly too: `./scripts/deploy.sh teardown`
