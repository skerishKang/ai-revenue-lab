# CTO Final Review

## 1. Review identity

- Repository:
- Issue:
- Pull Request:
- Base branch:
- Exact base SHA:
- Exact reviewed HEAD SHA:
- Merge base:
- Ahead/behind:
- Review date/time and timezone:
- Workflow status: `CTO_REVIEW`

## 2. Evidence inspected

- [ ] CTO work order
- [ ] Actual changed-file list and diff
- [ ] Commit history
- [ ] Automated test results
- [ ] Hosted CI status/logs
- [ ] Local Validation report
- [ ] Browser/UI artifacts
- [ ] Deployment evidence, when applicable
- [ ] Known limitations and non-goals

List exact references:

- 

## 3. Scope review

### Allowed paths

- 

### Actual changed paths

- 

### Forbidden or unrelated changes

- None / details

### Scope verdict

- PASS / FAIL

## 4. Acceptance criteria

| ID | Criterion | Evidence | Verdict |
|---|---|---|---|
| AC-1 |  |  | PASS / FAIL / DEFERRED |
| AC-2 |  |  | PASS / FAIL / DEFERRED |

A deferred criterion must identify whether it is an approved non-goal, a post-merge condition, or a blocker.

## 5. Automated validation review

- Tested HEAD matches reviewed HEAD: yes / no
- Required checks present:
- Required checks passed:
- Failed/skipped/warning disclosure:
- CI coverage sufficiency:
- Regression-suite adequacy:

Verdict: PASS / FAIL

## 6. Local Validation review

- Required: yes / no
- Tested HEAD matches reviewed HEAD: yes / no / not applicable
- Source modification during validation: no / yes
- Desktop evidence:
- Mobile evidence:
- Console/page/network evidence:
- External integration evidence:
- Blocking local failures:

Verdict: PASS / FAIL / NOT REQUIRED

## 7. Security, privacy, and architecture

- Secret/credential exposure:
- Personal-data boundary:
- Authentication/authorization impact:
- Input/output validation:
- Logging/redaction:
- Dependency/supply-chain risk:
- Architecture boundary and coupling:
- Rollback/reversibility:

Verdict: PASS / FAIL

## 8. Report-to-diff consistency

- Developer report matches actual diff:
- Test claims match logs/statuses:
- Deployment claims match revision:
- Known limitations are complete:
- Stale or unsupported claims removed:

Verdict: PASS / FAIL

## 9. Remaining risks and conditions

### Blocking

- 

### Non-blocking

- 

### Conditions for `CONDITIONALLY_READY`

For each condition include owner, deadline or trigger, validation method, and rollback/stop condition.

- 

## 10. Final CTO status

Choose exactly one:

- `NOT_READY`
- `CONDITIONALLY_READY`
- `READY`

### Decision

- Status:
- Reviewed HEAD:
- Rationale:
- Required next action:
- User merge approval: pending / granted
- Merge recommendation: do not merge / may merge after condition / may merge after user approval

`READY` is not an automatic merge command. The User / Product Owner must explicitly approve merge or deployment.
