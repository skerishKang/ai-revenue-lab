# B14 Cloudflare Error 1010 root cause and Production models verification — 2026-10-09

**STATUS: HTTP403 client access issue identified, live smoke verified; customer end-to-end approval still OPEN.**

## Source evidence

The evaluation's ad hoc Python `urllib` script omitted `User-Agent`. On the **same deployed B14 URL and origin**, both `GET /api/pilot/health` and `GET /api/pilot/models` returned:

- HTTP403, JSON `cloudflare_error=true`, `error_code=1010`, `error_name=browser_signature_banned`, `error_category=access_denied`.
- Default Python-urllib user agent: HTTP403, repeatable.
- Explicit descriptive client `User-Agent: PADIEM-Source-Eval/1.0`: **HTTP200** on both routes.
- Other browser-like user agents: HTTP200 (but do **not** impersonate a browser in canonical clients).
- No token/key rotation, WAF edit, or deploy needed. This is a Cloudflare client-signature block, **not** a Mercury/Atria upstream 403 or missing Worker secret.

This matches [Cloudflare's Error 1010 official documentation](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/) and [Browser Integrity Check](https://developers.cloudflare.com/waf/tools/browser-integrity-check/). The official pre-existing `.github/scripts/b66_quote_model_benchmark.py` already uses this descriptive client ID, so no canonical backend change is necessary. The one-off evaluation probes missing UA were corrected.

## Production read-only readiness + live model proof

With explicit descriptive UA, GET `/health`, `/api/pilot/health`, `/api/pilot/models`, `/api/pilot/provider-readiness` all **HTTP200**, mode `b14-live`, exact model ID and upstream mapping verified; both Mercury and Atria have active binding *presence* (not key-value verification).

| Exact manual model | Standard greeting | Standard quote | Streaming-preview quote |
|---|---|---|---|
| `inception/mercury-2.5` | **HTTP200**, 2,532ms, actual answer | QKR-002 **HTTP200 / strict PASS**, 3,563ms | NOT_TESTED |
| `atria/Atria-Dawn-Preview` | **HTTP200**, 6,078ms, actual answer | QKR-001 **HTTP504 / upstream_timeout**, 10,563ms | QKR-001 **HTTP200 / strict PASS**, 50,640ms, first response 43,531ms |

All actual B14 POSTs pinned the exact model; manual route identity evidence matched, attempt_count=1, fallback_used=false on successes. For errors no model substitution/retry requested. These are independent **smoke and quote samples**, not full 10-case confidence nor F6 PDF evidence.

**Important:** Atria's streaming-preview is an explicitly designated experimental route; its success does **not** change the canonical non-stream route which still returns timeout for the tested quote.

## Hard constraints

- Keep Cloudflare Browser Integrity Check and WAF policies unchanged; do not disable protection globally to make a synthetic default UA work.
- Do not expose Cloudflare account IDs, Ray IDs, user keys or model reply body. The QA client should identify itself with its truthful product UA instead of using Python default.
- **Agnes 3.0 Flash B14 HTTP429 remains a separate, unresolved problem** under issue #3913. The original generic provider 429 cannot be assigned to this 1010 GET block without evidence.
- F1–F6 final model evaluation is **IN_PROGRESS** for both models, no automatic model choice, no fallback, no secret mutation and no live deploy.
