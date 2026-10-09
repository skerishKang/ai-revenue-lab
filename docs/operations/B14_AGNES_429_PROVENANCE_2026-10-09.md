# B14 — Agnes 3.0 Flash upstream HTTP 429 provenance (source-only)

**Date:** 2026-10-09 (KST)
**Scope:** `apps/korean-ai-platform/app/pilot/platform.py`, dedicated offline tests.
**Status:** **SOURCE-ONLY DIAGNOSTIC, NOT A LIVE FIX.** No Cloudflare deploy, account/secret change, new endpoint, additional provider call, routing/fallback change, or unverified success claim.

## Evidence and decision

- One short Korean greeting with `agnes-ai/agnes-3.0-flash` and `max_tokens=100` returns **HTTP429** `upstream_rate_limited` via the deployed B14 Worker (1,328 ms, retry 0, fallback false).
- The same greeting sent **directly** from the owner's local machine using `urllib` and subsequently local `httpx` succeeds with **HTTP200**. The explicit selected Agnes model matches.
- **Strongest control:** executing the B14 FastAPI gateway and its production platform adapter **locally** with the working local Agnes credential returned **HTTP200**, proper selected-model identity and exactly one upstream attempt, with fallback disabled. Thus the common code path is functionally capable; production Worker environment remains the divergence.
- Remote Cloudflare **Secrets Store metadata** proves `PADIEM_AGNES_API_KEY` is active, available for Workers, and present in the deployed Worker version with B14 mode live. This **does not** validate its value, account, quota or equality to the local key.
- The B14 source has no provider-specific RPM counter or configured Workers Rate Limiting binding. Input validation rejects invalid bodies with its own 422 rather than synthesizing a provider `upstream_rate_limited`.
- The *existing* adapter converts every Agnes upstream HTTP429 into the same generic error regardless of the response body. Therefore the distinction between actual vendor quota rejection versus an upstream intermediary HTML 429 or policy rate limit is **UNKNOWN**.

## Change

Agnes **only**, after receipt of an upstream 429 in the generic non-stream and stream provider adapters:

- emit one structured warning with **media class** (`json`, `html`, `other`);
- classify an allow-listed JSON `error.type/code` into broad groups (`quota`, `rate_limit`, `capacity`, `policy`, `unclassified`);
- log **presence flags only** for `Retry-After`, `Cf-Ray`, and `Server: cloudflare`. A Cloudflare header alone **does not prove a WAF block**;
- never log response body, raw provider error text, header values, tokens, keys, user prompts, account IDs, or client/user identifiers;
- retain **the existing HTTP429** `upstream_rate_limited`, stop-on-429 and no-unapproved-fallback behavior.

Tests use synthetic `httpx.MockTransport` exclusively and pin response classification, no secrets in logs, streaming and completed-JSON parity, and unchanged successful calls.

## Runtime diagnosis gate (not yet authorized/executed)

Only after the owner authorizes production diagnostic deployment:

1. Fresh main/head, conflict review and exact-head CI.
2. Deploy through canonical Git-connected path, check served version and current binding metadata. **Do not touch secret values.**
3. Trigger **one** user-selected Agnes greeting with `max_retries=0`, `max_attempts=1`, `allow_external_fallback=false`.
4. Read **only** the new bounded operator log fields, not the response body or keys.
5. If JSON quota/rate-limit signature, verify API key account/plan/entitlement with Agnes admin. If HTML/edge signature, investigate Agnes upstream WAF/routing restrictions for Cloudflare Worker requests with Agnes support. If unknown, do not blindly rotate keys or add retries.
6. Correct the proven cause separately, then rerun an exact-model greeting and quotation with no fallback; do not claim `Production-live` before evidence.

**Restriction:** metadata alone cannot distinguish Secret value mismatch from Worker egress blocking. Do not claim this diagnostic PR has fixed the provider 429.
