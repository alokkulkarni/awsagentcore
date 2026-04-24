# Secure DTMF Capture for Amazon Connect

> **AWS Marketplace Product** · Version 1.0  
> **Licence:** Apache License 2.0

## Encrypted DTMF Keypad Capture for Sensitive Data — No Agent Exposure

Collect card numbers, PINs, SSNs, and account numbers over the phone while keeping every digit invisible to agents, logs, and storage.

---

## The Problem

When customers provide sensitive numeric information over the phone, standard IVR systems face an unavoidable dilemma: either an agent hears the digits (PCI DSS violation), or the digits pass through systems in cleartext (data security risk). Even muted audio is captured in call recordings. Contact record logs, Lambda invocations, and DynamoDB tables all become potential exposure points.

**This product eliminates digit exposure at the source** — before any software reads them.

---

## Key Features

- **RSA encryption at capture** — Amazon Connect encrypts DTMF digits with your RSA public key the instant they are pressed. No software sees cleartext digits until a private Lambda decrypts them
- **Private key never exposed** — the RSA private key lives only in AWS Secrets Manager (KMS-encrypted); it is loaded into Lambda memory per-invocation and never stored or logged
- **Full card digits never persisted** — only `bin` (first 6) and `lastFour` are retained; the full number is discarded immediately after extraction
- **Real-time agent feedback** — a secure panel popup shows validation status (`✅ Card Validated — ****4567`) without revealing digits
- **Eight built-in collection purposes** — `full_card_number`, `card_last_four`, `ssn`, `account_number`, `sort_code`, `cvv`, `pin`, `generic`
- **Pluggable ownership verification** — provide your own Lambda ARN; the validate Lambda calls it to check card/data belongs to the authenticated customer
- **Luhn + BIN validation** — card numbers are checked with the ISO/IEC 7812 Luhn algorithm and optionally against a BIN prefix table
- **Fully serverless** — Lambda, DynamoDB, API Gateway, CloudFront, S3; zero infrastructure to maintain
- **PCI DSS scope reduction** — sensitive digits never enter storage, logs, or HTTP responses in cleartext

---

## Architecture Overview

The solution consists of four Lambda functions orchestrated by an Amazon Connect contact flow. When an agent triggers secure capture, the `aria-dtmf-start-session` Lambda initialises a DynamoDB session and sets a status attribute on the contact. Amazon Connect plays an IVR prompt and captures the customer's keypad digits using the "Store customer input" block, which RSA-encrypts the digits with a public key stored in the Connect Security Profile. The `aria-dtmf-decrypt` Lambda immediately decrypts the ciphertext using the private key from Secrets Manager, returning only the BIN, last four digits, and digit count. The `aria-dtmf-validate` Lambda runs Luhn checks, BIN lookups, and optional ownership verification, writing the result to contact attributes. In parallel, an agent browser panel polls the `aria-dtmf-status-proxy` Lambda via API Gateway every two seconds, displaying real-time validation status. The panel and launcher are hosted on CloudFront-backed S3 with HTTPS-only access.

For the complete architecture diagram and sequence diagrams, see [docs/architecture.md](docs/architecture.md).

---

## Quick Links

| Document | Description |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | 15-minute quick start — get running in one sitting |
| [docs/architecture.md](docs/architecture.md) | Full architecture with Mermaid diagrams, data flow, IAM matrix |
| [docs/deployment-guide.md](docs/deployment-guide.md) | Step-by-step production deployment guide |
| [docs/configuration-reference.md](docs/configuration-reference.md) | All parameters, contact attributes, API schemas, and Lambda contracts |
| [docs/key-management-guide.md](docs/key-management-guide.md) | RSA key setup, rotation, audit, and PCI DSS considerations |
| [docs/customisation-guide.md](docs/customisation-guide.md) | Adding purposes, custom IVR prompts, panel rebranding, data integrations |

---

## Repository Structure

```
marketplace/
├── README.md                          ← This file
├── QUICKSTART.md                      ← 15-minute quick start
├── docs/
│   ├── architecture.md                ← Architecture diagrams and data flow
│   ├── deployment-guide.md            ← Full deployment guide
│   ├── configuration-reference.md     ← All parameters, schemas, contracts
│   ├── key-management-guide.md        ← RSA key setup, rotation, PCI guidance
│   └── customisation-guide.md         ← Custom purposes, panel, integrations
├── cloudformation/
│   └── dtmf-secure-capture.yaml       ← CloudFormation template (all resources)
├── contact-flows/
│   ├── README.md                      ← Contact flow import instructions
│   ├── ARIA-DTMF-SecureCollection.json
│   ├── ARIA-DTMF-CardCapture-Example.json
│   ├── ARIA-DTMF-SSN-Example.json
│   └── ARIA-DTMF-GenericCapture-Example.json
└── scripts/
    ├── setup_dtmf_keys.sh             ← Generate RSA key pair + store in Secrets Manager
    └── deploy_dtmf_lambda.sh          ← Package + deploy all Lambdas + panel HTML
```

The Lambda source files are located in the parent repository:

```
scripts/lambdas/
├── aria_dtmf_decrypt.py               ← RSA decryption Lambda
├── aria_dtmf_validate.py              ← Validation Lambda
├── aria_dtmf_start_session.py         ← Session initialisation Lambda
└── aria_dtmf_status_proxy.py          ← Status API Lambda

client/
├── dtmf-status-panel/
│   └── index.html                     ← Agent popup panel
└── dtmf-launcher/
    └── index.html                     ← CCP iframe launcher
```

---

## Licence

Copyright © 2025 — All rights reserved.

Licensed under the **Apache License, Version 2.0** (the "Licence"). You may not use this software except in compliance with the Licence.

You may obtain a copy of the Licence at:

> http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed under the Licence is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the Licence for the specific language governing permissions and limitations under the Licence.

---

> **Disclaimer:** This solution supports PCI DSS scope reduction but does not constitute PCI DSS compliance by itself. Buyers are responsible for their own compliance assessments. See [docs/key-management-guide.md — PCI DSS Considerations](docs/key-management-guide.md#8-pci-dss-considerations).
