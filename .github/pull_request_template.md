## Purpose

Describe the user, business, or experimental outcome of this change.

## CTO work contract

- Issue:
- Work-order reference:
- Exact base SHA:
- Target branch:
- Workflow status:

## Scope

### In scope

- 

### Out of scope / non-goals

- 

### Allowed paths

- 

### Forbidden paths

- 

## Revision identity

- Starting base SHA:
- Final head SHA:
- Merge base:
- Ahead / behind:
- Commits:

## Changes

List the exact files or modules changed and why.

| Path | Change | Reason |
|---|---|---|
|  |  |  |

## Acceptance criteria

| ID | Criterion | Evidence | Result |
|---|---|---|---|
| AC-1 |  |  | PASS / FAIL / PENDING |

## Automated evidence

| Command/check | Commit SHA | Exit/status | Result |
|---|---|---:|---|
|  |  |  |  |

- Test pass/fail/skip counts:
- Lint/type-check results:
- Warning handling:
- Security/secret scan:
- Hosted CI run/status references:
- Missing or insufficient CI coverage:

## Local validation

- Required: yes / no
- Exact tested HEAD SHA:
- Environment:
- Source modified during validation: yes / no
- Desktop result:
- Mobile result:
- Console errors:
- Page errors:
- Failed requests:
- External integration result:
- Artifact references:
- Local verdict: `LOCAL_PASSED` / `LOCAL_FAILED` / `PENDING` / `NOT_REQUIRED`

## AI production record

- Web CTO model/provider:
- Web Developer model/provider:
- Local Validator model/provider:
- Free calls or quota used:
- Paid-model use and reason:
- Human review time:

## Security, privacy, and compatibility

- Authentication/authorization impact:
- Personal-data impact:
- Secret handling:
- Input/output validation:
- Logging/redaction:
- Dependency changes:
- Backward compatibility:
- Rollback/reversibility:

## Risks and limitations

### Known defects

- 

### Environment-limited validation

- 

### Approved non-goals

- 

### Production prerequisites

- 

## CTO final review

- Exact reviewed HEAD SHA:
- Scope verdict: PASS / FAIL / PENDING
- Automated evidence verdict: PASS / FAIL / PENDING
- Local validation verdict: PASS / FAIL / NOT_REQUIRED / PENDING
- Security and regression verdict: PASS / FAIL / PENDING
- Final status: `NOT_READY` / `CONDITIONALLY_READY` / `READY` / `PENDING`
- User merge approval: pending / granted

`READY` is not an automatic merge command. Merge or deployment requires explicit user approval.

## Completion checklist

- [ ] Repository, exact base SHA, branch, allowed paths, and forbidden paths are recorded.
- [ ] Actual changed files match the declared scope.
- [ ] Acceptance criteria are demonstrated without weakening them after implementation.
- [ ] Commands, exit codes, pass/fail/skip counts, and CI references are included.
- [ ] Required Local Validation tested the exact PR HEAD.
- [ ] Local Validator did not silently modify product source code.
- [ ] No unrelated dirty files are included.
- [ ] No secrets, tokens, credentials, or personal data were committed or exposed.
- [ ] Model/provider configuration remains replaceable where applicable.
- [ ] Documentation was updated when behavior, policy, or decisions changed.
- [ ] Deployment claims identify the deployed revision and stable URL.
- [ ] Known limitations and deferred work are disclosed.
- [ ] Final `READY`, `CONDITIONALLY_READY`, or `NOT_READY` status is assigned only by the Web CTO.
