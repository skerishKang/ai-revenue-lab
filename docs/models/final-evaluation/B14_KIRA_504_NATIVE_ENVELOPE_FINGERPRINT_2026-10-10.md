# B14 #3554 — Kira QKR-008 504 native-error fingerprint after the diagnostic Production release

**Observed:** 2026-10-10 KST. **Status:** `LOCAL_B14_NATIVE_504_FINGERPRINT=EXACT_BYTE_LENGTH_MATCH`; `HISTORICAL_EXCEPTION_STAGE=UNDETERMINED`; `REAL_KIRA_QKR_ACCURACY=UNSCORABLE`. **No new LLM request.**

## Evidence

| Fact | Evidence |
|---|---|
| Old QKR-008 user-approved Kira request | Single Production B14 POST around 18:31 KST, exact `kira/qwen3.8-flash-free`, manual/one attempt/no retry/fallback, `max_tokens=3900`, **HTTP504 after 11,094ms with a 547-byte response**. Old raw error body **was not stored**, so exact code/headers are **NOT independently observed**. See [prior incident](B14_KIRA_QKR008_ONE_SHOT_504_2026-10-10.md). |
| Kira owner's own usage dashboard | Around 18:32:18 KST, same model and one matching request recorded **2,584 prompt, 1,476 completion, 4,060 total tokens, displayed $0**. This documents that the upstream processed substantial completion tokens, not that its entire final answer was correct or ever reached the client. |
| Official B14 Production deploy | [Gate #38043543765](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38043543765): source **`733521cf24d6296d503b599c0d93d8ffb5615b28`**, new Worker version **`dc0fa2c2-9058-4b93-a372-256ef28d2abe`**, Wrangler version number 608, 100% applied, smoke and 11/11 model tuple parity passed, immutable pre-deploy rollback anchor `3894a71e-a08e-44bd-b02d-53aef4288b2c`. This version includes merged [PR #4146](https://github.com/skerishKang/ai-revenue-lab/pull/4146) phase-safe logging. |
| Local independent B14-native error serialization | Using **actual B14 Starlette app and actual existing gateway**, stub only the upstream adapter to raise `UpstreamTimeout()` one time for exact Kira/model/manual request; route returns **HTTP504**, `error.code=upstream_timeout`, `attempt_count=1`, `fallback_used=false`, exactly one `attempt_evidence` entry and **547 response bytes**. |
| Match strength | **547 exact bytes in both cases** corroborates that the historical 504 *could have been created by B14's own JSON error handler*. This is stronger than a generic Cloudflare-edge attribution, but the old error body was not saved: another 547-byte error is logically possible and the original root cause/timeout phase is **NOT proven**. |
| Tests and paid calls | Focused `python -m pytest -q tests/test_3554_kira_504_envelope_fingerprint.py tests/test_3554_provider_timeout_phase.py` **21 PASS in 0.52s**, 0 network/Secret value reads/paid provider requests, no Production changes. |

The new regression is `apps/korean-ai-platform/tests/test_3554_kira_504_envelope_fingerprint.py` and contains no real credentials, no raw model response and no external transport. It deliberately treats the 547-byte length as an **evidentiary fingerprint**, not as a permanent public API requirement. If text/route metadata changes, reconcile the forensic assertion rather than silently changing it.

## What was and was not observable

- The new B14 code can log fixed allowlisted `b14_safe_timeout provider=kira phase=connect|read|write|pool|other mode=completed` or `b14_gateway_deadline provider=kira phase=overall` for **future** matching failures; it cannot retroactively annotate an October 10 pre-deployment event.
- `wrangler tail` subscribes to *new* Worker events, not historical ones. An intentionally **GET-only** read-only log-subscription attempt yielded no attributable event during a bounded watch; this is not proof logging never works, and no provider POST was generated to force a timeout. The temporary tail session was terminated.
- Source `apps/korean-ai-platform/wrangler.toml` has **no explicit `[observability]` Workers Logs persistence configuration**. Cloudflare may turn it on automatically for some Workers; whether this existing Worker stores historical invocation logs **has not been attested**. Do not claim old logs are queryable without Cloudflare dashboard/API evidence. [Cloudflare Workers Logs documentation](https://developers.cloudflare.com/workers/observability/logs/workers-logs/) describes persistence and retention only when enabled.
- **No new Kira/other paid model calls**, no Secrets Store changes and no additional Production deploy were made in this phase.

## Next acceptance gate

1. **Read-only**: inspect the existing Cloudflare Workers Observability UI/API (if enabled), specifically historical 18:31:58–18:32:18 KST and newer version-608 errors, using restricted URL/status/error metadata only. A historical 504 from version 607 cannot produce the *new* phase log; inspect only older available error markers and old exact served SHA.
2. If there are no available phase-correlated logs, distinguish **httpx phase** vs **45s overall gateway** on a **new incident only** using the now-deployed fixed diagnostic log; the 11.094s duration and 10s connect threshold are an investigative lead, not proof of TCP connect failure. Kira dashboard vendor completion is evidence that upstream work happened.
3. Before any additional **possibly billable** actual Kira QKR-008 POST, get **fresh explicit Owner approval**, preflight current official per-model promo/charging scope, pin exact model, `max_attempts=1,max_retries=0,allow_external_fallback=false`, and capture safe error code, phase/elapsed/finish_reason and usage. Never auto-retry when upstream may already have consumed tokens.
4. Correct only the proven failing path; if long documents legitimately require more than synchronous budget, use resumable **job ID, deduplicated work and status retrieval** (separate Engine/Claw/B66 scope). A blanket 10→60s change in every timeout is not validated.

**Do not close #3554/#2676.** One historical Kira greeting passed; one real QKR call timed out; QKR quality and real Sol customer PDF remain unverified.
