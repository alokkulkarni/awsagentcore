# SDLC Review Report

## Report metadata

- Date: {{DATE}}
- Reviewer: {{REVIEWER}}
- Branch: {{BRANCH}}
- Files reviewed:
{{FILES_REVIEWED}}

## Executive Summary

**Status:** {{STATUS_BADGE}}

{{EXECUTIVE_SUMMARY}}

## Critical Findings

| ID | File | Line | Issue | CWE | Severity | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
{{CRITICAL_FINDINGS_ROWS}}

## High Findings

| ID | File | Line | Issue | CWE | Severity | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
{{HIGH_FINDINGS_ROWS}}

## Medium/Low Findings

| ID | File | Line | Issue | CWE | Severity | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
{{MEDIUM_LOW_FINDINGS_ROWS}}

## Dependency CVE Summary

| Package | Version | CVE | CVSS | Fixed In |
| --- | --- | --- | --- | --- |
{{DEPENDENCY_CVE_ROWS}}

## Coverage Summary

- Line coverage: {{LINE_COVERAGE}}
- Branch coverage: {{BRANCH_COVERAGE}}
- Coverage source: {{COVERAGE_SOURCE}}

## Merge Recommendation

**{{MERGE_DECISION}}** — {{MERGE_REASONING}}

## Remediation Guidance

{{REMEDIATION_GUIDANCE}}
