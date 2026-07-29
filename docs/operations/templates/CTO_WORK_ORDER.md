# CTO Work Order

## 1. Work identity

- Repository:
- Default branch:
- Issue:
- Exact base SHA:
- Target branch:
- Current relevant PRs/issues:
- Workflow status: `WORK_ORDER_READY`

## 2. Product objective

Describe the user or business outcome this change must create.

## 3. Current verified state

Record only facts verified from current GitHub, code, tests, deployment, or supplied evidence.

- Current behavior:
- Current limitations:
- Existing implementation evidence:
- Conflicting or stale reports rejected:

## 4. Scope

### Allowed paths

- 

### Forbidden paths

- 

### Non-goals

- 

## 5. Required implementation

1. 
2. 
3. 

## 6. Contracts and invariants

- Existing behavior that must remain:
- API/data/schema contracts:
- Security and privacy boundaries:
- Compatibility requirements:
- Error/fail-closed behavior:

## 7. Acceptance criteria

| ID | Criterion | Required evidence |
|---|---|---|
| AC-1 |  |  |
| AC-2 |  |  |
| AC-3 |  |  |

Acceptance criteria must not be weakened after implementation begins without explicit Product Owner approval and a recorded work-order revision.

## 8. Required automated checks

- Unit:
- Integration:
- Static/lint/type:
- Security:
- Existing regression suites:
- Hosted CI:

## 9. Required Local Validation

- Required: yes / no
- Reason:
- OS/runtime/browser:
- Desktop viewport:
- Mobile viewport:
- External services:
- Required user flows:
- Required console/page/network evidence:

## 10. Required developer report

Use `WEB_DEVELOPER_REPORT.md` and include:

- exact starting base and final HEAD
- changed files and diff statistics
- commands, exit codes, pass/fail/skip counts
- CI runs
- known limitations
- Local Validation handoff

## 11. Completion definition

The Web Developer may report implementation complete when:

- all scoped implementation is committed to the target branch;
- required automated checks pass on the reported HEAD;
- a Draft PR exists;
- the report identifies remaining Local Validation and limitations;
- no forbidden-path or unrelated changes are present.

This does not grant `READY`. Final status is assigned by the Web CTO after required evidence is reviewed.
