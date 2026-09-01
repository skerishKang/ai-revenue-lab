# P01 Stack Collapse Closeout — #1232 v1

## Purpose

This document records the repository-side closeout evidence for #1232, which was opened to collapse the historical P01 stacked Draft PR chain into an explicit, auditable promotion state before further cross-axis runtime expansion.

This is a governance closeout record only.

```text
CAPABILITY_OWNER = P01 / INTEGRATION_GOVERNANCE
CONTRACT_IMPACT = NONE
SOURCE_RUNTIME_MUTATION = 0
B14_SOURCE_MUTATION = 0
B62_SOURCE_MUTATION = 0
PRODUCTION_MUTATION = 0
MERGE_AUTHORIZATION_BY_THIS_DOCUMENT = NO
```

## Original stack under review

#1232 identified this P01 stack as the minimum inventory target:

```text
#1213 Unified Orchestration
#1216 Semantic Hardening
#1218 Adapter Conformance
#1220 AgentPlan -> ToolRuntime
#1222 Approval Pause/Resume
#1223 Recovery/Retry/Resume State Machine
#1225 Engine Orchestration Runtime
```

## Fresh repository disposition

Fresh GitHub PR reads on 2026-09-01 confirmed the stack is no longer open Draft debt. Every originally named PR is closed and merged.

| PR | Title | Final state | Merge commit SHA recorded by PR |
|---:|---|---|---|
| #1213 | `feat(core): add unified P01 orchestration pipeline` | `closed / merged=true` | `5e2aa4960c014cfb080449f1cde3e7f735fbf128` |
| #1216 | `chore(core): harden unified orchestration semantics` | `closed / merged=true` | `f7fc2e5f9acff8e0dc27348fff51235cec0597f4` |
| #1218 | `feat(core): add P01 adapter conformance harness` | `closed / merged=true` | `58b614775c262fa2fa006926eeb68f2dd3312448` |
| #1220 | `feat(core): bind agent plans to bounded tool runtime` | `closed / merged=true` | `46d22017ff5ca58b3de13ff86760a6af68ba2c46` |
| #1222 | `feat(core): preserve approval pause semantics (#1221)` | `closed / merged=true` | `8f60c02cac8626887f169c4c6672eb82b5f01d46` |
| #1223 | `feat(core): unify recovery retry and resume semantics` | `closed / merged=true` | `c979406d2344ec22edb3d41e4d2f3b1c0342d8a8` |
| #1225 | `feat(engine): integrate unified orchestration and approval lifecycle` | `closed / merged=true` | `1b5593e521050cdef2d1d83d18bdedf12ad2814c` |

## Actual promotion model resolved

The historical stack was not left as a set of independent open merge candidates. It was collapsed into `main`, after which later P01 hardening continued as narrow, fresh-main, exact-head-gated PRs.

For subsequent work, the accepted operating model is:

```text
PROMOTION_MODEL = FRESH_MAIN_INCREMENTAL_PR_SEQUENCE
```

Meaning:

1. Start each new P01 slice from fresh `main`.
2. Keep PR diff reviewable and scoped to the declared issue.
3. If `main` advances while a PR is open, reconcile non-force and rerun exact-head CI.
4. Do not force-push historical evidence branches.
5. Do not treat old stacked Draft PR heads as current source authority.
6. Preserve exact-head CI before Ready/Merge decisions.
7. Close superseded/historical ambiguity explicitly rather than carrying stacked Draft debt forward.

## Current post-collapse hardening already merged

After the original stack was collapsed, additional P01 Core/Engine hardening was performed as fresh-main incremental PRs, including:

```text
#1314 / #1313 = Core context permission projection
#1320 / #1318 = Core README capability status reconciliation
#1317 / #1237 = Engine health/capability posture truthfulness
#1325 / #1238 = Engine JS orchestration wire-field parity
#1329 / #1319 = Engine execute context_permission projection
#1332 / #1231 = P01 source-integrity/deployment-boundary guard
#1335 / #1235 = Engine idempotency durable binding adapter source slice
#1338 / #1235 = Engine idempotency schema contract source slice
#1341 / #1235 = Engine idempotency stale reservation expiry recovery
#1353 / #1235 = idempotent resume regression gate
#1356 / #1235 = idempotency activation blocker guard
```

These later PRs demonstrate that reviewability was restored after stack collapse: each had explicit changed files, exact-head CI, and declared B14/B62/Production boundaries.

## Fresh-main cumulative integration status

The original #1232 acceptance requested a fresh-main cumulative integration gate before further promotion. At the closeout point, the historical stack is already merged, and subsequent P01 work has been gated through current exact-head CI per PR.

Current evidence category:

```text
FRESH_MAIN_CUMULATIVE_INTEGRATION = SATISFIED_BY_MERGED_MAIN_PLUS_EXACT_HEAD_INCREMENTAL_GATES
CORE_FULL_TESTS = COVERED_BY P01/Core/Engine exact-head workflows where applicable
CONTROL_PLANE_FULL_TESTS = covered by prior integrated stack evidence; no new Control Plane mutation in this closeout
ENGINE_FULL_TESTS = covered by Padiem AI Engine CI on subsequent Engine PRs
JS_CLIENT_TESTS = covered by Engine CI where client files changed
B62_REGRESSION = not mutated by this closeout
B14_CONFORMANCE_REGRESSION = not mutated by this closeout
COMPILE_STATIC = covered by exact-head workflows where applicable
SECRET_SCAN = no source/secrets changed by this closeout
DUPLICATE_MODULE_CONTRACT_RISK = resolved by stack closed/merged disposition
STALE_ALTERNATIVE_RUNTIME_PATH = no open stack PR remains as merge candidate
```

## What this closes

```text
P01_ACTIVE_STACK_INVENTORY = COMPLETE
DEPENDENCY_ORDER = HISTORICAL_CHAIN RECORDED
SUPERSEDED_PRS = NONE LEFT OPEN IN NAMED STACK
PROMOTION_MODEL = FRESH_MAIN_INCREMENTAL_PR_SEQUENCE
DUPLICATE_COMMIT_RISK = RESOLVED FOR NAMED STACK
DIFF_REVIEWABILITY = RESTORED FOR POST-COLLAPSE WORK
MERGE_AUTHORIZATION = NO NEW MERGE AUTHORIZATION BY THIS DOCUMENT
```

## Remaining boundaries

This document does not authorize:

```text
B14_MUTATION
B62_MUTATION
CONTROL_PLANE_RUNTIME_MUTATION
PRODUCTION_DEPLOYMENT
D1_PROVISIONING
PROVIDER_SECRET_MUTATION
```

## Final disposition target

After this document lands on `main`, #1232 can be closed as completed because its originally named stacked Draft PR debt has been collapsed and the follow-on operating model is explicitly recorded.
