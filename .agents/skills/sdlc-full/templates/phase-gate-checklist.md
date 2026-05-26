# SDLC Phase Gate Checklist

Use this checklist when manually reviewing a full pipeline run or when validating a resumed run from a later phase.

## Analysis

### Pre-phase checklist
- [ ] Feature scope or problem statement is defined
- [ ] Repository context is available
- [ ] Existing documentation has been scanned

### Post-phase checklist
- [ ] Requirements were extracted
- [ ] Dependency and quality findings were captured
- [ ] Validation gate returned GREEN

## Architecture

### Pre-phase checklist
- [ ] Analysis outputs are available
- [ ] Business and technical constraints are known
- [ ] Target platform assumptions are recorded

### Post-phase checklist
- [ ] HLD exists
- [ ] Components and interfaces are defined
- [ ] Validation gate returned GREEN

## Refinement

### Pre-phase checklist
- [ ] Architecture artefacts are approved
- [ ] Delivery boundaries are understood
- [ ] Ticketing or backlog destination is known

### Post-phase checklist
- [ ] Epics and stories were generated
- [ ] Acceptance criteria exist
- [ ] Validation gate returned GREEN

## Development

### Pre-phase checklist
- [ ] Approved stories exist
- [ ] Coding targets and runtime stack are confirmed
- [ ] Destination paths are known

### Post-phase checklist
- [ ] Source files were created or modified
- [ ] Implementation summary exists
- [ ] Validation gate returned GREEN

## Test

### Pre-phase checklist
- [ ] Development outputs are present
- [ ] Test framework is known
- [ ] Coverage target is set to at least 80%

### Post-phase checklist
- [ ] Tests were generated or executed
- [ ] Coverage result is recorded
- [ ] Validation gate returned GREEN

## Review

### Pre-phase checklist
- [ ] Full diff or changed file set is available
- [ ] Dependency manifests are available
- [ ] Test results are available

### Post-phase checklist
- [ ] Review report exists
- [ ] CRITICAL/HIGH findings are zero
- [ ] Validation gate returned GREEN or PASSED
