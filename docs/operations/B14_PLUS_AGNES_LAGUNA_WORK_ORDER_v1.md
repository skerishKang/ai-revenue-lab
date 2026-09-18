# Web CTO Work Order: B14 Plus Agnes + Laguna

## Authority / revision

- Issue / owner request: Plus tier model swap handoff, 2026-09-18
- Repository: `skerishKang/ai-revenue-lab`
- Default branch: `main`
- Exact current base SHA: `616f4015c3d214f27bf00f1ebb060e3376d1b299` (`origin/main`)
- Target branch: `fix/b14-plus-agnes-laguna`
- Product-evidence stage: `RUNTIME_PILOT`

## Objective

Replace the executable Padiem Plus route with `agnes-ai/agnes-3.0-flash` and make the owner-designated `fixed_chain_v1` route order Agnes first and `poolside/laguna-s-2.1` second. Preserve fail-closed routing and the existing fallback trigger allow-list. Remove SenseNova from the executable Plus declaration and consumer projections.

The requested exact `agnes-3.0-flash` live measurement is blocked before implementation because the currently deployed Worker advertises `agnes-ai/agnes-2.5-flash`, and the public endpoint returned HTTP 403 for all three approved synthetic fixtures. No credential value was accessed.

## Product / visual gate

- Material new art direction/redesign? no
- Current visual gate: `VISUAL_GATE_NOT_REQUIRED`
- Reason: provider/model routing and runtime evidence only; no user-facing visual change.

## Scope

- Allowed paths:
  - `docs/operations/B14_PLUS_AGNES_LAGUNA_WORK_ORDER_v1.md`
  - `apps/korean-ai-platform/app/pilot/agnes_provider.py`
  - `apps/korean-ai-platform/app/pilot/routing_policy.py`
  - `apps/korean-ai-platform/app/pilot/tier_registry_v1.py`
  - `apps/korean-ai-platform/tests/**` for route/provider contract updates
  - `packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`
  - `packages/padiem-control-plane/tests/test_product_tier_routes.py`
  - `apps/padiem-chat/app/model_policy.py` (consumer comments only if needed)
  - `apps/padiem-chat/tests/**` for updated route expectations
  - `apps/korean-ai-code-agent/src/kagent/p01_adapter.py` (consumer comments only if needed)
  - `apps/korean-ai-code-agent/tests/**` for updated route expectations
  - implementation and validation reports under `docs/operations/`
- Forbidden paths: unrelated dirty files in the owner worktree, secrets or `.env` files, deployment configuration, `.github/**`, Engine source, Docker artifacts, and any Production mutation.
- Non-goals: admin routing mode, direct Production deployment, Preview/staging, provider credential value access, broad provider refactors, user-visible provider/model catalog disclosure.
- Preserve: stdlib-only control-plane contract, no user-visible `auto`/`fallback` route labels, Kilo retirement locks, fallback only for timeout/transport/429/5xx, no fallback for other 4xx/malformed/unknown errors, AttemptEvidence as response truth, mock mode zero upstream calls.
- SenseNova handling: remove SenseNova from executable Plus and active fixed chain. Do not delete the standalone provider module or unrelated historical tests; no other tier may be re-routed.

## Evidence dimensions

- Technical implementation: REQUIRED
- Backend/runtime: REQUIRED
- Security/privacy: REQUIRED
- Runtime/provider live evidence: REQUIRED for final activation; currently BLOCKED for exact 3.0 by deployed-version/access boundary
- Production: DEFERRED_WITH_REASON, owner-authorized deployment only
- Visual/UX/market/commercial: NOT_REQUIRED

## Role plan

- Web CTO: contract, scope, acceptance, final review
- Web Developer: implementation and non-independent self-check
- Independent Local Validator: REQUIRED, different actor, exact-head checks before merge
- Owner-only decision: REQUIRED for accepting live measurement gap and any Production merge/deployment

## Acceptance criteria

1. All four Plus pins agree on Agnes `agnes-ai/agnes-3.0-flash` and `PADIEM_AGNES_API_KEY`; no executable Plus route or fixed-chain position references SenseNova.
2. `fixed_chain_v1` is exactly Agnes first, Poolside Laguna second, with at most two attempts and the existing fallback error allow-list unchanged. No fallback occurs for non-allow-listed errors.
3. Poolside remains server-owned and credential-bound as the second route; user-facing catalogs do not expose provider/model authority.
4. Existing Kilo retirement and no-auto/no-silent-fallback locks remain intact; control-plane import remains stdlib-only and side-effect-free.
5. Mock mode and focused/full relevant tests pass on the exact implementation head. Exact 3.0 live measurement remains explicitly reported as blocked unless a separately authorized Production Worker run exposes the new deployed model.

## Required checks

- `git status --short --branch`, remote re-read immediately before mutation/review
- `apps/korean-ai-platform`: `uv run pytest -q`, focused routing/provider tests, compileall
- `packages/padiem-control-plane`: focused contract tests
- `apps/padiem-chat`: focused model policy/catalog tests
- `apps/korean-ai-code-agent`: focused P01 adapter tests
- mock-mode proof with no upstream calls
- exact-head and changed-file scope evidence
- no Production deployment in this work order

## Failure handling

Classify failures as `ROUTE_PARITY_BREAK`, `CHAIN_ORDER_BREAK`, `FALLBACK_BOUNDARY_BREAK`, `USER_SURFACE_LEAK`, `SECRET_BOUNDARY_BREAK`, `CONTROL_PLANE_SIDE_EFFECT`, `SCOPE_VIOLATION`, or `LIVE_EVIDENCE_BLOCKED` before changing scope.

## Merge / deployment authority

- Merge authorization: owner after Web CTO final review and independent exact-head validation
- Expected head required: yes
- Deployment risk/lane: D3 provider/secrets/runtime; Git-connected Production path only after separate authorization
- Preview/staging exception: none
