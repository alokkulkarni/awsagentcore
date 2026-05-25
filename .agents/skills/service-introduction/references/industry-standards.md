# Industry Standards and Reference Links

## Core Service Management Standards

- ITIL v4 — https://www.axelos.com/certifications/itil-service-management
- ISO/IEC 20000-1:2018 — https://www.iso.org/standard/72025.html
- TOGAF ADM — https://www.opengroup.org/togaf
- COBIT 2019 — https://www.isaca.org/resources/cobit
- NIST Cybersecurity Framework — https://www.nist.gov/cyberframework

## Financial Services and Resilience References

- UK FCA SYSC (Systems and Controls) — https://www.handbook.fca.org.uk/handbook/SYSC/
- EU/UK DORA — https://www.digital-operational-resilience-act.com/
- GDPR (ICO UK) — https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/
- PCI-DSS v4.0 — https://www.pcisecuritystandards.org/document_library/
- SOC 2 (AICPA) — https://www.aicpa-cima.com/resources/article/soc-2
- ISO/IEC 27001:2022 — https://www.iso.org/standard/27001

## Why these standards matter for SIDs

| Standard | SID Relevance |
| --- | --- |
| ITIL v4 | Defines service transition, service design package thinking, and governance expectations for new and changed services. |
| ISO/IEC 20000-1 | Provides formal service management system requirements across transition, catalogue, supplier, and service level management. |
| TOGAF ADM | Supports architecture governance, target-state documentation, and traceability from business capability to solution design. |
| COBIT 2019 | Adds governance and control objectives for accountability, performance, and compliance. |
| NIST CSF | Strengthens risk, detect, protect, respond, and recover coverage in operational sections. |
| FCA SYSC | Reinforces governance and operational controls for regulated UK financial services environments. |
| DORA | Emphasizes resilience, third-party oversight, testing, incident readiness, and operational continuity. |
| GDPR / PCI-DSS / SOC 2 / ISO 27001 | Inform security, compliance, data handling, and audit expectations captured in the SID. |

## Agent and Protocol References

- agentskills.io — https://agentskills.io
- MCP Protocol — https://modelcontextprotocol.io/

## Recommended usage pattern

1. Use repository scanning to pre-fill technical facts.
2. Use stakeholder interviews or `collect_info.py` to fill business, regulatory, and support information.
3. Validate the final SID before sign-off.
4. Reissue the SID whenever a significant service change affects architecture, support, compliance, or resiliency assumptions.
