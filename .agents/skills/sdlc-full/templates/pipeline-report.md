# SDLC Pipeline Execution Report

- Pipeline ID: `{{PIPELINE_ID}}`
- Project: `{{PROJECT}}`
- Date: `{{DATE}}`
- Feature: {{FEATURE}}

## Phase Summary Table

| Phase | Status | Gate Result | Artefacts | Duration |
| --- | --- | --- | --- | --- |
| Analysis | {{ANALYSIS_STATUS}} | {{ANALYSIS_GATE}} | {{ANALYSIS_ARTEFACTS}} | {{ANALYSIS_DURATION}} |
| Architecture | {{ARCHITECTURE_STATUS}} | {{ARCHITECTURE_GATE}} | {{ARCHITECTURE_ARTEFACTS}} | {{ARCHITECTURE_DURATION}} |
| Refinement | {{REFINEMENT_STATUS}} | {{REFINEMENT_GATE}} | {{REFINEMENT_ARTEFACTS}} | {{REFINEMENT_DURATION}} |
| Development | {{DEVELOPMENT_STATUS}} | {{DEVELOPMENT_GATE}} | {{DEVELOPMENT_ARTEFACTS}} | {{DEVELOPMENT_DURATION}} |
| Test | {{TEST_STATUS}} | {{TEST_GATE}} | {{TEST_ARTEFACTS}} | {{TEST_DURATION}} |
| Review | {{REVIEW_STATUS}} | {{REVIEW_GATE}} | {{REVIEW_ARTEFACTS}} | {{REVIEW_DURATION}} |

## Phase 1: Analysis Summary

{{ANALYSIS_SUMMARY}}

## Phase 2: Architecture Summary

{{ARCHITECTURE_SUMMARY}}

## Phase 3: Backlog Summary

{{BACKLOG_SUMMARY}}

## Phase 4: Development Summary

{{DEVELOPMENT_SUMMARY}}

## Phase 5: Test Summary

{{TEST_SUMMARY}}

## Phase 6: Review Summary

{{REVIEW_SUMMARY}}

## Overall Pipeline Status

{{OVERALL_STATUS}}

## DORA Metrics Baseline

- Lead time for changes: {{LEAD_TIME}}
- Deployment frequency: {{DEPLOYMENT_FREQUENCY}}
- Mean time to restore: {{MTTR}}
- Change failure rate: {{CHANGE_FAILURE_RATE}}

## Next Steps

{{NEXT_STEPS}}
