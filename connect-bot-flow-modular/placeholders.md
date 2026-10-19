# Placeholders

Only the main flow has placeholders: things that exist once you've created them.

| Token | What it is | Where it goes | Comes from |
|---|---|---|---|
| `${ARIA_AGENT_V2_ARN}` | ARIA v2's version ARN | main flow, block `talkToAria` (Lex `ai-agent-arn`) | `ai-agent/create_agent.sh --apply` prints it |
| `${MODULE_ARN_AriaContactSetup}` | Flow module "ARIA - Contact setup" | main flow, block `contactSetup` | the module's details after publishing |
| `${MODULE_ARN_AriaCustomerContext}` | Flow module "ARIA - Customer context" | main flow, block `customerContext` | the same |
| `${MODULE_ARN_AriaDecideHandback}` | Flow module "ARIA - Decide hand-back" | main flow, block `decideHandback` | the same |

Put them in `config.json` and run `python3 build_flows.py --config config.json`. It prints any still missing.

Everything else is the live resource's real ARN: the three transfer flows, both Lambdas, the Lex bot alias and the
assistant.
