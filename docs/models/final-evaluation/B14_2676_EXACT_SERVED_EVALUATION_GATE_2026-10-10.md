# B14 #2676 — Exact served-model evaluation preflight audit (2026-10-10)

## Scope and evidence

CENTRAL performs a **read-only provider-model evaluation gate review**, not a new paid performance benchmark. The canonical `apps/korean-ai-platform/app/pilot/b14_models.json` contains **11 model IDs / 8 provider IDs**. Current Production GETs (`/api/pilot/health`, `/api/pilot/models`) returned HTTP 200; compared with source, all **11 model IDs and all 11 exact (provider_id, upstream_model) pairs matched**, with no missing or extra entries. Public metadata had **11 explicit-only routes, zero auto-eligible**, not proof of customer entitlement or actual model completions.

Existing `.github/scripts/b66_quote_model_benchmark.py --preflight-live-get` returned `MATCH`, `main_model_count=11`, `served_model_count=11`, `live_post_count=0`; before #2676 hardening, that preflight compared **ID sets only**, which would not detect a changed upstream/provider behind a stable public ID. The independent CENTRAL GET comparison used provider/upstream fields and exposed the contract gap.

## #2676 fixed gate contract

- The evaluation preflight compares exact **public model ID + serving provider ID + upstream model**, not merely public ID. A stable ID with changed provider or upstream forces `BLOCKED_REGISTRY_DRIFT`; mismatches are reported by public model ID only. Missing provider/upstream metadata also blocks evaluation.
- Duplicate served model IDs, missing and extra model IDs already force a blocked result. A metadata mismatch does **not** initiate a provider POST or automatic fallback.
- The exact Owner-maintained canonical registry is the authority. Unlisted or retired models are not promoted to evaluated or live-approved by appearance in an external catalog. Direct Poolside and separately excluded Kilo Poolside Laguna remain distinct identities.
- Local Windows isolated checkout of implementation head `cc5080b8dacca701c8539526075a48a5bc97d5b5`: `python -m pytest -q .github/tests/test_b66_quote_model_benchmark.py .github/tests/test_b14_owner_evaluation_registry.py .github/tests/test_b14_model_evaluation.py .github/tests/test_b14_model_evaluation_live.py` → **91 PASSED**. All are synthetic/injected tests; no provider calls or customer data.
- Actual `GET` preflight after the hardening must be separately measured at the merged exact source revision. The 91 PASS and original GET result alone do not constitute complete live inference testing.

## Per-model quality evidence remains separate

The historical nine-model QKR comparison and selective synthetic prompt completions were recorded on earlier sources, not a completed current eleven-model leaderboard. Kira Qwen has no comparable completed quality evidence; ExLab Qwen and Agnes HTTP429, Gemma 4 31B and Atria HTTP504 are **availability/transport outcomes**, not 0-point quality grades. Atria's independent successful SSE trial does not prove Claw/Engine or quote/PDF E2E. StepFun Step 5 free 429 tests remain historical and cannot be silently retried, switched to a paid route or registered without Owner authority.

Remaining #2676: comparable **new live responses from every Owner-authorized exact model**, same corpus/real provider accepted parameter shapes, attempt_count=1, fallback=false, actual returned model pin, timing/status capture and B66 normalizer scoring, plus separately authorized cost/quota scope. Continue **OPEN** until actual evidence; no default route, model rank, credential, entitlement or Production deployment changes by this PR.
