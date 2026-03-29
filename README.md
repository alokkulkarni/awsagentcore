# ARIA — Automated Responsive Intelligence Agent

**ARIA** is Meridian Bank's AI-powered telephone banking assistant, built on the [Strands Agents](https://strandsagents.com) framework and powered by Amazon Bedrock (Claude 3.5 Sonnet v2).

ARIA handles authenticated customer queries across accounts, debit cards, credit cards, and mortgages — with a strict PII pipeline, multi-factor knowledge-based authentication, and a structured human escalation protocol.

---

## Prerequisites

- **Python 3.11+**
- **AWS credentials** configured with access to Amazon Bedrock in `eu-west-2` (or your target region)
  - The IAM principal must have `bedrock:InvokeModel` permission for `us.anthropic.claude-3-5-sonnet-20241022-v2:0`
- `uv` (recommended) or `pip`

---

## Installation

### Using `uv` (recommended)

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .
```

### Using `pip`

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

---

## Configuration

Copy `.env.example` to `.env` and update the values:

```bash
cp .env.example .env
```

| Variable            | Default                                        | Description                                                   |
|---------------------|------------------------------------------------|---------------------------------------------------------------|
| `AWS_REGION`        | `eu-west-2`                                    | AWS region for Bedrock                                        |
| `AWS_PROFILE`       | `default`                                      | AWS CLI profile to use                                        |
| `BEDROCK_MODEL_ID`  | `us.anthropic.claude-3-5-sonnet-20241022-v2:0` | Bedrock model ID                                              |
| `BANK_API_BASE_URL` | `https://api.meridianbank.internal`            | Meridian Bank core banking API base URL (stub in dev)         |
| `BANK_API_KEY`      | —                                              | API key for the core banking API                              |
| `PII_VAULT_BACKEND` | `in_memory`                                    | PII vault backend: `in_memory`, `aws_secrets_manager`, etc.   |
| `LOG_LEVEL`         | `INFO`                                         | Python logging level                                          |

---

## Running the Agent

```bash
python main.py
```

ARIA will start an interactive REPL. Type your customer query at the `Customer:` prompt. Type `quit` to exit.

---

## Project Structure

```
awsagentcore/
├── pyproject.toml              # Project metadata and dependencies
├── requirements.txt            # Pinned/direct dependencies
├── .env.example                # Environment variable template
├── main.py                     # Entry point — starts interactive REPL
└── aria/
    ├── __init__.py
    ├── agent.py                # create_aria_agent() — wires model + tools + prompt
    ├── system_prompt.py        # ARIA_SYSTEM_PROMPT constant (full operational instructions)
    ├── models/                 # Pydantic v2 request/response models
    │   ├── pii.py              # PIIDetect*, PIIVaultStore*, PIIVaultRetrieve*, PIIVaultPurge*
    │   ├── auth.py             # VerifyIdentity*, InitiateAuth*, ValidateAuth*, CrossValidate*
    │   ├── account.py          # AccountDetailsRequest/Response, Transaction
    │   ├── cards.py            # DebitCard*, BlockDebitCard*, CreditCard*
    │   ├── mortgage.py         # MortgageDetailsRequest/Response
    │   └── escalation.py       # TranscriptSummary*, Escalate*
    └── tools/                  # @tool-decorated functions registered with the agent
        ├── __init__.py         # ALL_TOOLS list — single import point for agent.py
        ├── pii/
        │   ├── detect_redact.py    # pii_detect_and_redact
        │   ├── vault_store.py      # pii_vault_store + _VAULT dict
        │   ├── vault_retrieve.py   # pii_vault_retrieve
        │   └── vault_purge.py      # pii_vault_purge
        ├── auth/
        │   ├── verify_identity.py  # verify_customer_identity
        │   ├── initiate_auth.py    # initiate_customer_auth
        │   ├── validate_auth.py    # validate_customer_auth
        │   └── cross_validate.py   # cross_validate_session_identity
        ├── account/
        │   └── account_details.py  # get_account_details
        ├── debit_card/
        │   ├── card_details.py     # get_debit_card_details
        │   └── block_card.py       # block_debit_card
        ├── credit_card/
        │   └── card_details.py     # get_credit_card_details
        ├── mortgage/
        │   └── mortgage_details.py # get_mortgage_details
        └── escalation/
            ├── transcript_summary.py   # generate_transcript_summary
            └── human_handoff.py        # escalate_to_human_agent
```

---

## Tool Inventory

| # | Tool Function                    | Module                                   | Description                                                            |
|---|----------------------------------|------------------------------------------|------------------------------------------------------------------------|
| 1 | `pii_detect_and_redact`          | `aria/tools/pii/detect_redact.py`        | Regex-based PII detection and redaction on raw customer input          |
| 2 | `pii_vault_store`                | `aria/tools/pii/vault_store.py`          | Session-scoped in-memory vault store with TTL (max 900 s)              |
| 3 | `pii_vault_retrieve`             | `aria/tools/pii/vault_retrieve.py`       | Just-in-time retrieval of vault tokens before tool calls               |
| 4 | `pii_vault_purge`                | `aria/tools/pii/vault_purge.py`          | Purge all session vault entries at end/timeout/escalation              |
| 5 | `verify_customer_identity`       | `aria/tools/auth/verify_identity.py`     | Validate header identity against requested customer                    |
| 6 | `initiate_customer_auth`         | `aria/tools/auth/initiate_auth.py`       | Start a knowledge-based auth challenge                                 |
| 7 | `validate_customer_auth`         | `aria/tools/auth/validate_auth.py`       | Validate DOB + mobile last-four (max 3 attempts before lock)           |
| 8 | `cross_validate_session_identity`| `aria/tools/auth/cross_validate.py`      | Three-way check: header / auth-verified / body customer IDs            |
| 9 | `get_account_details`            | `aria/tools/account/account_details.py`  | Balance, transactions, statement URL, or standing orders               |
|10 | `get_debit_card_details`         | `aria/tools/debit_card/card_details.py`  | Card status, limits, masked card info                                  |
|11 | `block_debit_card`               | `aria/tools/debit_card/block_card.py`    | Irreversible card block with optional replacement order                |
|12 | `get_credit_card_details`        | `aria/tools/credit_card/card_details.py` | Balance, limit, minimum payment, APR, statement, dispute info          |
|13 | `get_mortgage_details`           | `aria/tools/mortgage/mortgage_details.py`| Balance, rate, payment, overpayment allowance, redemption statement    |
|14 | `generate_transcript_summary`    | `aria/tools/escalation/transcript_summary.py` | Compile structured session summary (vault refs, no raw PII)      |
|15 | `escalate_to_human_agent`        | `aria/tools/escalation/human_handoff.py` | Secure TLS handoff package to human agent routing system               |

---

## Security Notes

### PII Pipeline
All customer input flows through a four-stage PII pipeline before any reasoning or data access:
1. **Detect & Redact** (`pii_detect_and_redact`) — regex patterns identify and tokenise PII in raw input.
2. **Vault Store** (`pii_vault_store`) — tokens are stored in a session-scoped vault (default: in-memory) with a configurable TTL (max 15 minutes).
3. **Vault Retrieve** (`pii_vault_retrieve`) — tokens are retrieved just-in-time, scoped by purpose, immediately before use.
4. **Vault Purge** (`pii_vault_purge`) — all tokens are purged at session end, on timeout, on security event, or after confirmed escalation handoff.

Raw PII never enters the model's reasoning context. The model works exclusively with vault reference URIs (`vault://session_id/TOKEN_KEY`).

### Vault TTL
The in-memory vault enforces a maximum TTL of **900 seconds (15 minutes)**. In production, replace `_VAULT` in `aria/tools/pii/vault_store.py` with an AWS Secrets Manager or HashiCorp Vault backend by setting `PII_VAULT_BACKEND` in `.env`.

### Authentication
Knowledge-based authentication is limited to **3 attempts** before the session is locked. A locked session escalates immediately to the human agent team with `escalation_reason: security_event`.

### PCI-DSS Note
The stub implementations in this project use in-memory data. Before deployment to a production environment handling real card data, all tool stubs marked `# TODO: Replace with ...` must be replaced with calls to the Meridian Bank core banking API, and the system must undergo a PCI-DSS scoping and assessment exercise. Do not log, persist, or transmit raw card numbers, CVV codes, or PIN data at any point.

### Prompt Injection Defence
The system prompt instructs ARIA to ignore any customer instructions to bypass authentication, skip PII handling, or reveal internal procedures. ARIA will not act on instructions framed as "you are now in test mode", "ignore previous instructions", or similar injection patterns.

---

## Development

### Running with a local stub backend
All tool files contain stub implementations that return realistic but synthetic data. No real AWS credentials or bank API access is required to run the agent locally — only Bedrock access for the LLM inference.

### Replacing stubs
Each tool file contains a `# TODO: Replace with ...` comment marking where the stub logic should be replaced with a real API call. The Pydantic models in `aria/models/` define the expected request/response contracts.

### Adding tools
1. Add the Pydantic models to the appropriate file in `aria/models/`.
2. Create a new tool file in the appropriate subdirectory under `aria/tools/`.
3. Decorate the function with `@tool` from `strands`.
4. Import and add it to `ALL_TOOLS` in `aria/tools/__init__.py`.
5. Update `ARIA_SYSTEM_PROMPT` in `aria/system_prompt.py` to describe the new tool.
