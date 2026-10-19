# Manifest

| File | Create as | Name | Blocks |
|---|---|---|---|
| `ai-agent/prompt/aria-orchestration-prompt-v2.yaml` | AI prompt (by `create_agent.sh`) | ARIA-Banking-Orchestration-Prompt-v2 | — |
| `ai-agent/agent/aria-conversation-agent-v2.json` | AI agent, orchestration (by `create_agent.sh`) | aria-conversation-agent-v2 | 21 tools |
| `modules/aria-contact-setup.json` | **Flow module** | ARIA - Contact setup | 8 |
| `modules/aria-customer-context.json` | **Flow module** | ARIA - Customer context | 5 |
| `modules/aria-decide-handback.json` | **Flow module** | ARIA - Decide hand-back | 19 |
| `flows/aria-conversation-bot-flow.json` | **Inbound flow** (CONTACT_FLOW) | ARIA conversation bot flow (modular) | 18 |

**Order:**
1. AI agent event logging (optional, recommended);
2. ARIA v2;
3. the three modules, published;
4. their ARNs and ARIA v2's into `config.json`, then rebuild;
5. the main flow.

**Modules or Transfer to flow:**
- **Contact setup, customer context and the hand-back decision are modules:** returnable steps mid-conversation,
  and the first two are reusable.
- **The three assistants stay Transfer to flow:** card dispute assistant, Mortgage Live Sync handover and ARIA human
  handover. Each is a hand-off with its own lifecycle. Human handover goes on to ARIA agent assist, which sets the
  adviser's assist agent (`my-agent-assistant-agent`).

**Standards applied:**
- Logging on as the first block of every flow and module.
- Recording and Contact Lens analytics set once per contact, for voice and chat.
- An error branch on every block that can fail.
- One Transfer block per destination, one Disconnect.
- Readable block IDs.
- Every resource ARN real except the four placeholders.
- Block settings unchanged from live (voice Amy generative, en-GB, Lex timeouts, Lambda timeouts, STRING_MAP).

**Links into this flow:** none are made. Everything live stays on the old flow until you switch over (README).
