# SDLC Test Validation Rules

This reference defines the ten `TST-NNN` controls enforced by `validate_tests.py`. The rules align to IEEE-style test evidence, ISTQB quality heuristics, and practical automation gates.

## Severity Model

- **CRITICAL** — the test phase is not runnable or has no test artefacts
- **HIGH** — quality gate failure that should block release or merge
- **MEDIUM** — important completeness or test-design issue
- **LOW** — advisory naming or journey-coverage improvement

## Rule Index

| Rule ID | Severity | Summary | Reference |
| --- | --- | --- | --- |
| TST-001 | CRITICAL | At least one test file exists | IEEE 829 test artefact completeness |
| TST-002 | CRITICAL | Tests can be discovered by the test runner (syntax valid) | ISTQB execution readiness |
| TST-003 | HIGH | Line coverage ≥ 80% (if coverage report available) | Google Testing guidance |
| TST-004 | HIGH | Branch coverage ≥ 70% (if coverage report available) | Coverage gate best practice |
| TST-005 | HIGH | No test that always passes (empty assertions, pass-only tests) | FIRST / self-validating |
| TST-006 | MEDIUM | Each public function/method has at least one test | TDD completeness |
| TST-007 | MEDIUM | Integration tests present for API endpoints | ISTQB system/integration testing |
| TST-008 | MEDIUM | Tests are independent (no shared mutable state between tests) | FIRST / independent |
| TST-009 | LOW | Test names are descriptive (not test1, testA, etc.) | IEEE 829 clarity |
| TST-010 | LOW | E2E tests present for critical user journeys | BDD / customer journey coverage |

## Rule Notes

- **TST-001 / TST-002** ensure the test phase is real, discoverable, and executable.
- **TST-003 / TST-004** enforce line and branch coverage targets when reports exist.
- **TST-005** blocks tautological or placeholder tests that give false confidence.
- **TST-006 / TST-007 / TST-010** improve breadth across public API, integration boundaries, and end-user journeys.
- **TST-008** protects repeatability by discouraging shared mutable state or order dependence.
- **TST-009** keeps reports and failures understandable for reviewers and CI operators.
