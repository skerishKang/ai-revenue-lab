# B14 #3554 — Kira QKR-008 exact real CONNECT timeout phase and proposed bounded mitigation

**UTC evidence:** 2026-10-10 10:49:53 KST 19:49:53. **State:** `PROD_B14_CONNECT_PHASE_504_PROVEN`; `MITIGATION_OFFLINE_TESTED_ONLY`; `LIVE_KIRA_QKR_QUALITY=UNSCORABLE`.

## Authenticated source and live evidence

- Owner approved Cloudflare Workers Logs inspection/activation, one canonical B14 Production deployment to turn on persistent logs and one subsequent Kira QKR-008 possibly charged call. No blanket authorization for a further Provider request or this follow-up timeout-code Production deploy.
- [Observability PR #4156](https://github.com/skerishKang/ai-revenue-lab/pull/4156) merged `7bfc78144b926034531b2c5780bc07c54d90b941`, `wrangler.toml` explicitly sets `[observability] enabled=true, head_sampling_rate=1`. Current new Worker **version 609**, ID `091988c5-0737-4671-8292-1c1ed2e5085e`, **100% served**, from same SHA per successful [B14 official Production Gate #38045927604](https://github.com/skerishKang/ai-revenue-lab/actions/runs/38045927604). Prior version `dc0fa2c2-9058-4b93-a372-256ef28d2abe` is rollback anchor.
- Live `wrangler tail` connected for this exact version and showed a successful `GET /api/pilot/models` (preflight: **11/11** canonical model ID/provider/upstream tuples MATCH, no API POST) and then a **POST** event for the subsequent single authorized actual Kira QKR-008 request. A keepalive disconnect recovered via Wrangler reconnect; the necessary request and warnings were captured afterward.
- A fresh public official Kira exact model page GET before the call showed the temporary `qwen3.8-flash-free` zero-token-cost offer/countdown, **not evidence for permanent free model prices or the Owner account ledger**.
- Request: real existing B14 Production `POST /api/pilot/v1/chat/completions`, manually selected exact `kira/qwen3.8-flash-free`, canonical synthetic Korean **QKR-008 12-item** reference prompt, `stream=false`, `max_tokens=3900`, `business14.allow_paid=true`, `max_attempts=1`, `max_retries=0`, `allow_external_fallback=false`. No native reasoning or temperature override.
- **Client response:** **HTTP504** in **11,078ms**, **547 bytes**, sanitized `error.code=upstream_timeout`, `request_id=b14req_197394074353`, `attempt_count=1`, `fallback_used=false`, one `attempt_evidence` outcome `upstream_timeout`. Client sent **exactly one** POST, no retry, no model fallback, no second Provider call; no completed model answer or usage returned.
- **Exact matching Worker logs:**
  `b14_safe_timeout provider=kira phase=connect mode=completed`
  `alpha_error request_id=b14req_197394074353 code=upstream_timeout status=504 attempt=1`.
  **Conclusion for this request:** actual application `httpx.ConnectTimeout` in B14 adapter, not `httpx.ReadTimeout` or gateway 45s overall deadline. Logs prove the **B14 reported timeout phase**, but not independently the low-level TLS/TCP cause in Cloudflare's Python Workers runtime. Previous Kira dashboard recording completion tokens was for the *earlier* test; its correctness and this trial's actual billing remain unknown.
- Private sanitized evidence outside Git at `E:\\b14-3554-kira-qkr008-logged-once-20261010-safe-evidence.json`, single-use lock `E:\\b14-3554-kira-qkr008-logged-once-20261010.lock`. Provider keys, raw model output and customer documents were not printed/stored in Git.

## Small isolated mitigation, not yet Production deployed

Current B14 source `app/pilot/platform.py` builds `httpx.Timeout(connect=10,read=30,write=10,pool=10)` for both completed JSON and streaming. In this scoped change:
- **Kira only:** `connect=30s`, within existing **45-second** B14 gateway wall-clock budget, to prevent premature 10s connect-phase cancellation. This is a **bounded hypothesis-driven mitigation**, not guaranteed provider response success: the next genuine request could encounter read timeout, another gateway limit or non-JSON output.
- **All other Provider routes:** existing `connect=10s` unchanged. For **all** models, read=30s, write=10s, pool=10s, global B14 attempt deadline=45s, credentials, routing, manual model choice and retry/fallback logic unchanged.
- Both completed and streaming adapters use the same centralized allowlisted Provider-specific timeout helper. No new alternate route or second charge; no UI, Sol, QuoteCore, Engine or Claw code changes.
- Focused offline `httpx.MockTransport` tests assert exact Kira and SenseNova client timeouts in both completed and streaming modes, one synthetic exception and safe provider-phase log. **No live Provider request** in tests.

## Release and independent acceptance gates

1. Exact-head GitHub CI green and code review before squash merge. **Merge does not deploy.**
2. Obtain **new explicit Production approval** before deploying this *behavior-changing* timeout adjustment; previous approval was for log activation and the one now-spent Kira request. Keep Worker v609 as rollback anchor and use official exact-main Production deploy gate, not an ad-hoc hotfix.
3. Before a subsequent possibly billed Kira model POST, get **separate new Owner authorization**, verify published model rate/quota, pin exactly one model, attempt 1/retries 0/fallback 0 and collect matching redacted phase/request-ID logs. A future HTTP200 must still be assessed against actual 12-row QKR facts using existing imported-receipt assessor; absence of 504 alone does not prove quality.
4. Consider asynchronous customer document jobs separately when request/response lengths regularly exceed synchronous 45s. Do not escalate every model's timeout or introduce unauthorized automatic retry.

**Remaining:** `B14_CONNECT_TIMEOUT_PHASE=PROVEN`, `KIRA_30S_CONNECT_PATCH=OFFLINE_ONLY`, `PRODUCTION_RETEST=NOT_AUTHORIZED`, `QKR_MODEL_QUALITY=UNSCORABLE`, `SOL_PDF_CUSTOMER_E2E=OPEN`. Maintain #3554 and #2676 OPEN.
