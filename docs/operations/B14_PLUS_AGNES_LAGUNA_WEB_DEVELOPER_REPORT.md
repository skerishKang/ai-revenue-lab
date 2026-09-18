# Web Developer Report

## Revision

- Repository: `skerishKang/ai-revenue-lab`
- Authority: `B14_PLUS_AGNES_LAGUNA_WORK_ORDER_v1.md`
- Starting base SHA: `616f4015c3d214f27bf00f1ebb060e3376d1b299`
- Branch: `fix/b14-plus-agnes-laguna`
- Final reported head SHA: implementation worktree uncommitted; exact SHA pending owner/worker commit
- Draft PR: not created in this implementation session

## Authorized gate / scope

- Product-evidence stage: `RUNTIME_PILOT`
- Visual gate: `VISUAL_GATE_NOT_REQUIRED`
- Allowed paths: work-order-listed B14 provider/routing/tier, control-plane contract/tests, Chat/Claw consumers/tests, reports
- Exact changed files: 27 source/test files plus this report, work order, and CTO review
- Unrelated files present? no in implementation worktree; owner worktree dirty files were not touched
- Non-goals preserved: no deployment, no Docker, no secret values, no admin routing change, no Preview/staging

## Implementation

- Agnes provider registration now pins `agnes-ai/agnes-3.0-flash` / `agnes-3.0-flash` under `PADIEM_AGNES_API_KEY`.
- `fixed_chain_v1` now contains exactly Agnes first and Poolside Laguna second; maximum attempts is 2.
- Control Plane Plus route is Agnes executable; Poolside direct route is credential-bound data-only.
- Legacy B14 tier registry, Chat, and Claw consume the same Plus route identity.
- SenseNova is absent from active Plus/chain authority but remains in its standalone provider and historical tests.

## Self-check evidence

| Command / check | Result | Pass / fail / skip |
|---|---:|---|
| `uv run pytest -q` in `apps/korean-ai-platform` | 889 passed | PASS |
| `uv run pytest -q` in `packages/padiem-control-plane` | 466 passed | PASS |
| Chat focused suite with target worktree `PYTHONPATH` | 53 passed | PASS |
| Claw focused suite with target source paths | 90 passed | PASS |
| `uv run python -m compileall -q app tests` in B14 | exit 0 | PASS |
| `git diff --check` | exit 0 | PASS |

The first Chat collection attempt loaded a stale globally installed control-plane package and failed collection; rerun with the target worktree dependency paths passed 53 tests. The first B14 run exposed two stale Kilo keyless expectations; tests were updated to the new credential-bound Agnes chain and the rerun passed 888 tests. Independent review then found that auto-chain 5xx calls could multiply same-route retries; the fix disables same-route retries in `route_mode == "auto"`, adds a regression assertion, and the full B14 rerun passes 889 tests.

## Independent finding response

- Finding: `fixed_chain_v1` maximum attempt budget was exceeded by per-candidate retries.
- Reproduced: Agnes 3 calls plus Poolside 3 calls under repeated 5xx.
- Fix: auto mode now treats `decision.max_attempts` as the total upstream-call budget; Agnes and Poolside each receive at most one call for the two-candidate chain.
- Preserved: explicit manual routes retain the existing bounded same-route retry behavior.
- Regression evidence: `tests/test_alpha1.py::TestFallbackActualEvidence::test_auto_chain_total_attempt_budget_is_not_multiplied_by_same_route_retries`; fallback suite 142 passed; full B14 suite 889 passed.

## Runtime/provider evidence

- Current Production health endpoint check: HTTP 200, `b14-live`, configured providers 5, Agnes/Poolside/SenseNova readiness names present. Values were not accessed.
- Current Production catalog before this implementation advertised `agnes-ai/agnes-2.5-flash`, not the requested 3.0.
- Three approved synthetic Korean fixture calls against the public Worker endpoint all returned HTTP 403 before provider execution. No model/provider/attempt evidence was available.
- Exact Agnes 3.0 live measurement: `BLOCKED`, because the current deployed revision is 2.5 and the public access boundary returned 403. This is not reported as a pass.

## Security / data / secret boundary

- Credential values used: no.
- Secret names referenced only: `PADIEM_AGNES_API_KEY`, `PADIEM_POOLSIDE_API_KEY`.
- Private data: no; fixtures are synthetic and owner-approved.
- No raw provider bodies, prompt text, or credential values were added to source, logs, or reports.
- No Production mutation or deployment was performed.

## Remaining work

- Independent Local Validator must test the exact committed head; current worktree self-check is non-independent.
- Owner decision is required to accept the blocked exact-3.0 live measurement and authorize any merge/Production activation.
- A post-deployment Production Worker measurement of Agnes 3.0 followed by the same three fixtures and the Laguna fallback path remains required for runtime acceptance.

## Developer disposition

```text
IMPLEMENTED / PARTIAL
```
