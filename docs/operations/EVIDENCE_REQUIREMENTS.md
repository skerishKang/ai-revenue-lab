# Development Evidence Requirements

Status: Canonical

## Revision identity

Every implementation, validation, and final-review report records:

- repository and default branch;
- exact starting base SHA;
- target branch;
- exact reported or tested HEAD SHA;
- merge-base or ahead/behind relationship;
- clean/dirty worktree state, or that work was branch-only through GitHub.

Use full 40-character SHAs when available. Evidence for an older head is not automatically evidence for a newer head.

## Scope evidence

Record:

- allowed paths;
- forbidden paths;
- exact changed-file list;
- reason for each changed file;
- diff statistics;
- actual diff or compare reference;
- confirmation that unrelated files are absent.

Any unapproved path change or mismatch between report and actual diff is a blocker until reviewed.

## Web Developer evidence

The implementation report includes:

- starting base and final head;
- branch, commits, and Draft PR;
- changed files and behavior/contracts changed;
- non-goals preserved;
- each automated command, target head, exit/status, and pass/fail/skip counts;
- hosted CI check/run references when configured;
- known defects, deferred items, environment limits, and remaining validation.

Do not report a failed or unexecuted check as passing.

## Local Validator evidence

The Local Validator records:

- exact expected and actual tested HEAD;
- OS/runtime/browser or other relevant environment;
- repository state before validation;
- whether source was modified during validation;
- setup, build, run, and test commands with exit/status;
- required user flows and actual results;
- for UI work, required desktop/mobile viewport evidence, overflow, focus/keyboard observations, and visible states;
- console, page, and failed-request counts when relevant;
- artifact identifiers such as screenshots or recordings;
- reproducible failure evidence when a check fails.

If product source is modified during the validation pass, return that change to implementation; do not present the modified run as independent `LOCAL_PASSED` evidence.

## Web CTO final-review evidence

The final review records:

- exact reviewed HEAD;
- actual changed-file list and scope verdict;
- acceptance criterion by criterion verdict;
- automated evidence sufficiency;
- Local Validation requirement and exact-head match;
- security/privacy/regression considerations relevant to the work;
- known limitations and remaining conditions;
- final `READY`, `CONDITIONALLY_READY`, or `NOT_READY` status.

Only the Web CTO assigns those final statuses.

## CI rule

CI is necessary where configured for the change, but is insufficient by itself. A passing check demonstrates only what that check actually covers. Missing or insufficient CI coverage must be stated and supplemented by the required validation.

## Failure evidence

Good failure evidence separates observation from hypothesis and includes:

- expected result;
- actual result;
- exact action or command;
- exact tested SHA;
- exit code or status;
- relevant error output;
- minimal reproduction;
- environment information;
- source-modification status.

## Evidence rejection conditions

Do not rely on the following as sole completion evidence:

- test results with no revision identity;
- results from a different head without an applicability review;
- “passed” statements with no command/status evidence;
- implementer self-review presented as independent validation;
- hidden source edits during validation;
- change summaries that do not match the actual diff;
- missing failed/skipped counts;
- unverified release/operating claims;
- evidence containing secrets or personal data.

## Templates

- `docs/operations/templates/WEB_DEVELOPER_REPORT.md`
- `docs/operations/templates/LOCAL_VALIDATION_REPORT.md`
- `docs/operations/templates/CTO_FINAL_REVIEW.md`
