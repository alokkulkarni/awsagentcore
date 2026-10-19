# ARIA v2: the orchestration agent for the modular flow

A new copy of ARIA (`my-conversation-agent`) with the **same business logic**: a cleaned prompt, and the same tools
minus one that's never used. The live agent and prompt are not touched. **[COMPARISON.md](COMPARISON.md)** has the
review: every tool's verdict, every prompt section live vs v2, and the decisions to check.

| File | What |
|---|---|
| `prompt/aria-orchestration-prompt-v2.yaml` | The prompt (paste-ready, or created by the script) |
| `agent/aria-conversation-agent-v2.json` | The agent: tools, Money Hub collaborator, guardrail, prompt settings |
| `build_agent.py` | Builds both from `reference/`. Edit this, not the outputs |
| `create_agent.sh` | Creates ARIA v2's prompt and agent as **new** resources, tagged, and stops if either name exists (dry run unless `--apply`). `--update` publishes a new version of those tagged resources only |
| `qconnect_agent.py` | Creates or updates the agent with boto3 for `create_agent.sh`, after checking the request offline against boto3's model. The AWS CLI 2.35 model rejects `multiAgentConfigurations` |
| `enable_ai_agent_logging.sh` | Sends the assistant's AI agent event logs (turns, tool calls) to CloudWatch (dry run unless `--apply`) |
| `reference/` | The live agent (v38, built from; v37 kept for history), prompt v27, guardrail v3 and the other agents, as read on 18 Oct 2026 |
| `COMPARISON.md` | The review |

The prompt keeps ARIA's warm, calm voice:
- the voice fillers (three-tier bridging, small talk, silence safety net);
- filler turns while she works;
- empathy-first wording, now stated plainly in Tone & Voice.

## Create it and test it in the modular flow

```bash
cd /Users/alokkulkarni/Documents/Development/awsagentcore
python3 -m unittest discover -s connect-bot-flow-modular/tests       # same logic, still importable
./connect-bot-flow-modular/ai-agent/create_agent.sh                    # dry run
./connect-bot-flow-modular/ai-agent/create_agent.sh --apply            # new prompt + agent + versions + profiles
```

Put the `ARIA v2: arn:…:<version>` it prints into `connect-bot-flow-modular/config.json` as `"aria"` (the modular
flow uses ARIA v2 by default and won't build without it). Then rebuild the modular flow:

```bash
python3 connect-bot-flow-modular/build_flows.py --config connect-bot-flow-modular/config.json
```

Then test through the modular flow (its README, "Test it without touching the live flow"). Try:
- a dispute from Cards;
- a mortgage application on a call;
- a payment request at Level 3 (app approval);
- "can someone call me back" (D1);
- asking for a person;
- a goodbye.

**Don't save ARIA v2 in the AI agent designer** after creating it: the designer's Save can replace security
profiles. Use `create_agent.sh --update --apply` instead.
