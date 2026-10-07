# Repository-wide Test Scope and Delivery Policy

- Status: **CANONICAL REPOSITORY-WIDE POLICY**
- Applies to: every Business, app, package, Engine/Core/Control Plane, Chat, Claw, Desktop, operations and documentation change
- Parent authority: `AI_DEVELOPMENT_OPERATING_POLICY.md`

## 1. Decision

AI Revenue Lab optimizes for **minimum sufficient validation that supports a decision**.

More tests are not automatically better evidence. A check is required only when it protects a concrete claim affected by the change, an explicit work-contract gate, a real high-risk boundary, or a platform-required merge condition.

```text
TEST_COUNT != CONFIDENCE
RELEVANT_EVIDENCE = CONFIDENCE
UNRELATED_GREEN != REQUIRED_EVIDENCE
```

No product or Business may override this policy by treating every available test, browser matrix, CI job or historical acceptance journey as mandatory.

## 2. Change classes

Choose the smallest class that truthfully describes the change.

### T0 — documentation / metadata only

Default evidence:

```text
diff/scope review
+ directly relevant policy/link/schema guard
```

No product runtime suite, browser QA, independent validator or Production smoke unless the document itself controls executable behavior that requires it.

### T1 — bounded implementation fix

Examples: one bug, tiny glue, narrow parser/adapter/composition fix, isolated UI correction.

Default evidence:

```text
focused load-bearing regression
+ relevant configured CI for affected dependencies
```

Default:

```text
REPORT_MODE=COMPACT
INDEPENDENT_LOCAL_VALIDATION=NOT_REQUIRED
FULL_PRODUCT_RETEST=NO
```

### T2 — bounded surface / integration change

Use focused unit/contract evidence plus the affected integration or browser journey. Do not test unrelated product surfaces.

### T3 — high-blast-radius change

Examples: auth/authz authority, shared Engine/Core contract, persistence/migration, billing, destructive actions, secrets/bindings, broad shared runtime composition.

Require full **relevant** coverage of the changed high-risk boundary, recovery evidence and affected downstream consumers.

```text
FULL_RELEVANT_BOUNDARY_COVERAGE=YES
AUTOMATIC_WHOLE_REPOSITORY_SUITE=NO
```

A whole-repository/product suite is required only when the change actually spans that whole surface or an explicit contract says so.

## 3. Test selection

Before running or waiting for a check, answer:

```text
CHECK=
PROTECTED_CLAIM=
AFFECTED_BY_THIS_CHANGE=YES|NO
BLOCKING_IF_FAILED=YES|NO
```

If `AFFECTED_BY_THIS_CHANGE=NO`, the check is observational/non-blocking unless GitHub branch protection or another explicit owner-approved gate requires it.

Do not add tests because they are available, historically used, or already running.

## 4. CI classification

Every review distinguishes:

```text
HANDOFF_REQUIRED_CHECK
RELEVANT_REVIEW_CHECK
OBSERVATIONAL_NONBLOCKING_CHECK
```

An automatically triggered workflow does not become required evidence merely because GitHub started it.

Agents and reviewers must not wait for observational/non-blocking jobs before completing a review, merge decision or customer handoff unless a new failure provides concrete relevant blocker evidence.

Platform-enforced required checks remain required; if an unrelated required check is structurally over-broad, fix the workflow/ruleset scope rather than normalizing repeated unnecessary testing.

## 5. Workflow design

CI triggers should match actual dependency/blast radius.

- browser/UI QA should be triggered by files that can affect that browser/UI claim;
- test-file-only changes should not trigger unrelated browser matrices;
- a deployment/Worker entrypoint change should not trigger unrelated mock-browser UI suites when those suites do not execute that entrypoint;
- product-specific checks should not fan out across unrelated Businesses;
- shared Engine/Core/Control Plane changes may intentionally trigger multiple consumers when the shared contract can affect them.

When a workflow is discovered to be structurally over-broad, classify narrowing it as operations maintenance. Do not use the over-broad fan-out as justification for making all its jobs handoff blockers.

## 6. Main drift / evidence carry-forward

Evidence belongs to the tested revision, but later repository movement does not automatically require execution again.

```text
UNRELATED_DRIFT != RETEST
RELEVANT_DRIFT = REVALIDATE_AFFECTED_CLAIM
```

Applicability review asks whether intervening changes affect the behavior, transitive dependency, authority, configuration, deployment target or user-facing surface.

## 7. Independent validation

Independent validation is selective.

Require it when the claim materially depends on a distinct browser/OS/hardware/local-service environment, a high-risk runtime boundary not represented in CI, or an explicit work-contract gate.

Do not commission a second validator merely because an issue is P0/P1.

## 8. Reporting

Default for T0/T1:

```text
REPORT_MODE=COMPACT
```

Use LONG reporting only for materially complex/high-risk work, large evidence packages, independent environment validation, incidents, migrations/destructive/billing/auth-secret work, or an explicit CENTRAL request.

Reporting is evidence transport, not a separate completion project.

## 9. Production smoke

After the final Production-changing revision, run the smallest accepted primary-journey smoke once.

Repeat only when:

- a new deployed revision affects the journey;
- the prior smoke failed or was ambiguous;
- a newly reproduced concrete blocker affects the journey.

```text
UNCHANGED_DEPLOY + CLEAR_PASS != REPEAT_SMOKE
```

## 10. Stop rule

Stop pre-delivery validation when:

```text
ACCEPTED_BLOCKERS=0
FOCUSED_REGRESSION=PASS
REQUIRED_RELEVANT_CI=PASS
REQUIRED_PRODUCTION_SMOKE=PASS   # when applicable
```

Further exploratory QA is post-delivery work unless it produces new concrete blocker evidence.

## 11. Safety boundaries that remain blocking

This policy never downgrades concrete failures involving:

- authentication/authorization bypass;
- secret/private-data leakage;
- data corruption or uncontrolled destructive behavior;
- migration/billing/irreversible external action integrity;
- explicitly accepted customer-critical P0/P1 failures;
- an actual platform-required merge check that is legitimately relevant.

The rule is **test what can invalidate the claim, not everything that can be tested**.
