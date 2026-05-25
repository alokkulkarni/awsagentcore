# Google SRE Runbook Alignment Guide

## Core philosophy

Google SRE treats a runbook as an operational product, not as personal notes. A good runbook:

- reduces cognitive load under stress
- makes each action observable and reversible
- prefers automation, but still documents the safe manual fallback
- is tested often enough that responders trust it
- lets a responder stop at the first sign of drift instead of improvising

**Key principle:** a runbook must be executable by an on-call engineer at 3am with zero prior knowledge of the service.

## What “verifiable” means

A Google SRE-aligned runbook must answer these questions after every step:

1. Why am I doing this step?
2. What exact command do I run?
3. What output, metric, or state proves success?
4. What should I do if reality does not match the expected outcome?
5. Who owns escalation if I cannot proceed safely?

This is why the skill requires a numbered step, a fenced command block, a ✓ **Verify** block, and a ⚠️ **If this fails** block for every procedure step.

## Five golden signals

Use the Google SRE five golden signals before, during, and after a deployment or incident action.

| Signal | What to check during a runbook | Example verification |
|--------|--------------------------------|----------------------|
| Latency | Are user requests getting slower? | p95 / p99 latency on the primary endpoints |
| Traffic | Is expected workload still flowing? | ALB requests, queue throughput, API invocation count |
| Errors | Are failures increasing? | 4xx / 5xx rate, exceptions, DLQ growth |
| Saturation | Is capacity close to exhaustion? | CPU, memory, DB connections, throttles |
| Availability | Is the service still reachable and healthy? | health checks, synthetic probes, SLO burn-rate alarms |

A production runbook should link each promotion or rollback gate to one or more of these signals.

## Error budgets and SLO alignment

Runbooks should be written around service objectives, not only around deployment mechanics. In practice this means:

- state the SLA / SLO in the Overview section
- define promotion gates and rollback triggers from those objectives
- stop a rollout when error-budget burn becomes unacceptable
- prefer objective thresholds over subjective judgement

Useful examples:

- roll back if HTTP 5xx exceeds 2% for 5 minutes
- halt promotion if p99 latency rises above 800 ms
- escalate if queue backlog doubles and does not recover inside one verification interval

## On-call best practices from the SRE Workbook

A strong on-call runbook should:

- start with the simplest, lowest-risk action first
- tell the responder which tools, dashboards, and credentials are required
- separate fact gathering from state-changing operations
- include communications guidance for customer-facing incidents
- define when to escalate instead of retrying locally
- use one reliable path instead of many optional branches
- document follow-up toil and automation opportunities discovered during execution

## Toil reduction

Google SRE strongly prefers eliminating repetitive manual work. Every time a human repeatedly runs the same sequence, the runbook should highlight an automation opportunity.

Good automation candidates include:

- prerequisite validation scripts
- one-command smoke tests
- automated rollback target discovery
- standardized alarm or dashboard snapshots in change announcements
- SSM Automation or CI/CD wrappers for common recovery paths

## Practical checklist

When generating or reviewing a runbook, confirm that it:

- names the owning team and on-call destination
- uses real environment variables and resource names
- provides exact commands in fenced blocks
- adds verification and failure handling after every step
- lists the top failure modes in a troubleshooting table
- includes a real rollback path, not just a statement that rollback exists
- ends with a quick reference and a revision history

## Reference URLs

- Google SRE Book: https://sre.google/sre-book/table-of-contents/
- Google SRE Workbook — On-Call: https://sre.google/workbook/on-call/
- Google SRE Workbook — Alerting on SLOs: https://sre.google/workbook/alerting-on-slos/
