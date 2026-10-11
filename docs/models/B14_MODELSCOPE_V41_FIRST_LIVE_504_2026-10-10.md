# ModelScope DeepSeek V4.1 Flash — First Owner-approved Production trial

**Date:** 2026-10-10 KST. **Issue:** [#4176](https://github.com/skerishKang/ai-revenue-lab/issues/4176). **Boundary:** Model registered and deployed; first actual provider response did **not** complete.

## Release proof — completed

- Source registry registration [PR #4177](https://github.com/skerishKang/ai-revenue-lab/pull/4177) merged `158a243d02fb81fb24e40a0ad49c039524cb8fac`. Registered `modelscope/deepseek-ai/DeepSeek-V4.1-Flash` is the exact ModelScope API-Inference namespace, not DeepSeek's own direct API model.
- Owner-approved **one** canonical Production dispatch via [B14 Gate run #38052450837](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38052450837): **SUCCESS**, source `8dad72e611f0deb49b0faf6a7acc7325f627a0f0`, Worker **v611** `b83e3714-5cf8-4949-9489-6c2eb50b0696` **100%** traffic. Prior Worker v610 `eeb1ab94-59db-4de2-99de-ef60b69b3d4d` preserved as rollback anchor. No Secrets Store value read/changed. Existing ModelScope binding name `PADIEM_MODELSCOPE_API_KEY` was metadata-only verified present.
- Independent read-only `/api/pilot/models` GET and preflight: **12 canonical source and served model IDs MATCH**, zero provider/upstream mismatches, zero fallback, 9 providers. Before test API POST count 0.

## Exact one-shot ModelScope request — error, no retries

- Owner explicitly approved **one** possible quota-consuming ModelScope live text request. Called **exactly once**, via deployed B14 POST `/api/pilot/v1/chat/completions`, manual `model=modelscope/deepseek-ai/DeepSeek-V4.1-Flash`, upstream `deepseek-ai/DeepSeek-V4.1-Flash`, minimal English OK greeting, all native sampling/reasoning/output defaults omitted, `stream=false`, `business14.allow_paid=true`, attempts=1, max_retries=0, no external fallback.
- Client received **HTTP 504 in 10,515 ms**, B14 error code **`upstream_timeout`**, request ID **`b14req_da2c052c2af7`**, one attempt, fallback=false, 601 response bytes. No completed model content, no quality score, no actual ModelScope quota/billing readback. Atomic single-use lock `E:\\b14-modelscope-dsv41-production-once-20261010.lock` exists. Private sanitized response metadata `E:\\b14-modelscope-dsv41-production-once-20261010-safe-evidence.json` remains off-Git. Actual Provider POST count **1** only.
- Live Cloudflare Worker v611 tail successfully connected and matched `POST /api/pilot/v1/chat/completions` + `alpha_error request_id=b14req_da2c052c2af7 code=upstream_timeout status=504 attempt=1`. **No** `b14_safe_timeout provider=modelscope phase=...` marker because the pre-existing fixed provider diagnostic allowlist omitted the newly registered `modelscope`. Thus the precise HTTPX timeout phase **IS UNKNOWN**; do not label it CONNECT by inference.
- 10.515s is consistent with one of B14 generic 10-second timeout phases (`connect`, `write` or `pool`; read=30s), but cannot establish which. Credentials/auth failures would normally fail with different error classes, yet successful account access is **not** established just by binding name or 504.

## Scoped speculative remediation in follow-up PR (NOT deployed)

- Add only `modelscope` to the fixed diagnostic allowlist so future actual HTTPX timeout logs record sanitized `phase=connect|read|write|pool|other` without exception messages, headers, account data or prompt.
- Give only ModelScope `httpx.connect=30s`, matching the previously observed Kira mitigation. Keep Kira connect=30s and **all other** Providers connect=10s; for ALL models keep read=30s, write/pool=10s and B14 gateway 45s overall. This is a **hypothesis-driven bounded mitigation**, not proven solution. No automatic retry, model change or fallback.
- Exact-code offline MockTransport tests for ModelScope/Kira/SenseNova normal+stream prove provider scoping and one synthetic exception with safe phase logging; existing security/provider tests preserved.
- **No second ModelScope provider POST, Secrets change or Production deploy authorized or executed.** Follow-up source PR/CI merge is separate from actual live readiness. If Owner later approves a controlled Production deploy and new one-shot POST, verify read-only model parity and real-time phase marker first. Do not repeatedly run 10-case QKR or Sol PDF just to accept basic model registration.

**Current:** ModelSource registration/Production catalog **DONE**, actual ModelScope inference **FAILED 504**, phase **UNKNOWN**, quota >=100/day **OWNER_EXPECTATION / NOT VERIFIED**, commercial availability **NOT CERTIFIED**, issue remains OPEN.
