# Agnes 3.0 Flash — safe upstream 429 provenance (issue #3913)

**Current result:** Current B14 Production returned HTTP429 for exact Agnes while a direct/local hosted credential path was observed HTTP200. This is **not yet a confirmed rate quota/WAF/credential root cause**.

## Source change
Only `platform.py` HTTP error handling for provider ID `agnes-ai` at status **429** invokes `agnes_429_diagnostics.log_agnes_429`.
- The bounded, allowlisted log fields are `media=json|html|other`, `reason_group=quota|rate_limit|capacity|policy|unclassified`, booleans for `Retry-After`, `Cf-Ray`, and `Server: cloudflare`.
- Log no raw upstream error fields/code, body, headers, key, account identity, request ID, or prompt. A `Cf-Ray` flag **does not prove WAF rejection**.
- Provider's HTTP429 contract and `upstream_rate_limited` remain **unchanged**, no new outbound request, retry, fallback, model replacement or secret reading. Completed and streaming both instrumented.

## Regression
`cd apps/korean-ai-platform && python -m pytest tests -q` — **1,092 PASS** on this branch.
New `tests/test_agnes_429_diagnostics.py`: 16 network-free tests verify classification, non-Agnes suppression, secret/non-allowlist redaction, stream/nonstream fail-closed, successful response unaffected.
`git diff --check` and Python compileall required.

## Separate next gate, after reviewed CI/merge
1. Use canonical B14 Production deploy gate only, exact current-main and immutable rollback anchor; do not read or mutate Secrets Store.
2. ONE synthetic `agnes-ai/agnes-3.0-flash` POST with `max_attempts=1, max_retries=0, allow_external_fallback=false`. No automatic retries or provider switching.
3. Read **only** the bounded `agnes_429_safe_metadata` event. Categorize by provider-returned group. If `quota` or `rate_limit`, verify provider-side entitlements and billing; if `policy` or HTML + edge metadata, ask provider/Cloudflare for egress diagnosis. Do not infer root cause from `cf_ray_present=true` alone.
4. Diagnose and fix only after evidence. Keep #3913 OPEN until **actual Agnes HTTP200** through Production B14 is demonstrated.

**Source-only fix is diagnostic, not restored Agnes service.**
