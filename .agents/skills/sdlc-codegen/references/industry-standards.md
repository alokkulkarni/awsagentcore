# Code Generation Industry Standards

This skill is intended to generate production-quality scaffolding that follows mainstream software engineering guidance.

## SOLID

Generated code should separate concerns, keep responsibilities focused, and avoid coupling route handlers directly to data access or infrastructure concerns.

## Clean Code

Prefer clear names, short units of work, defensive error handling, and code that explains intent without unnecessary noise.

Reference: Robert C. Martin, *Clean Code*.

## Twelve-Factor App

Scaffolds for services should remain deployable and environment-agnostic where possible: configuration belongs in the environment, dependencies are explicit, and logs are treated as event streams.

Reference: https://12factor.net/

## Style Guides

Use language-appropriate conventions:

- Python: PEP 8 and docstring-aware modules
- TypeScript / JavaScript: framework-native module layout and explicit error paths
- Go: package-oriented structure and `_test.go` coverage
- Java: class-per-file naming and test separation
- Rust: module hygiene and result-based error handling

## agentskills.io

A production agentskills.io skill should provide activation guidance, local fallback scripts, validation rules, templates, and machine-readable metadata.
