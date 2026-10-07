# Local handoff — Agnes AI first B14 provider candidate

> **History corrected 2026-10-07 (#3554).** This banner previously asserted that
> the Agnes route was "no longer registered in production code or the catalog"
> (#1933 S2-b). #1933 retired the *first* integration only; #2126 re-approved the
> provider and #2133 re-onboarded it, and `app/pilot/agnes_provider.py` registers
> `agnes-ai/agnes-3.0-flash` into `CATALOG_BY_ID` today. This document stays a
> historical handoff record for the original `agnes-2.5-flash` slice — see
> `AGNES_AI_V1.md` for the re-verification evidence behind the 3.0 lane, which is
> what owner decision #3554 selected for the Plus TEXT role. The generic
> platform-owned credential plane and the platform adapter contract described
> below remain live code; they are exercised in tests under
> `tests/test_platform_provider_credential_plane.py` via a synthetic
> platform_secret provider, and in
> `tests/test_platform_provider_readiness.py` via SenseNova.

Repository: `skerishKang/ai-revenue-lab`

Primary issue: `#917`

Branch: `feat/b14-multiprovider-platform-secrets`

Fresh base authority at intake: `95f2ac4c7b86f2230cdd7e0def86723ac1d23b49`

## Goal

Implement Agnes AI as the first non-OpenRouter platform-owned provider route under B14's multi-provider credential plane.

## Verified provider contract

```text
provider_id = agnes-ai
base_url = https://apihub.agnes-ai.com/v1
credential binding = AGNES_API_KEY
model = agnes-2.5-flash
endpoint = POST /v1/chat/completions
OpenAI-compatible = yes
streaming = yes
```

Expose B14 model ID as a stable catalog identifier, recommended:

```text
agnes-ai/agnes-2.5-flash
```

Preserve:

```text
model=b14/auto
model=agnes-ai/agnes-2.5-flash
```

## Constraints

- Never read, print, commit, copy, scrape, or migrate any unrelated provider credential from another local AI client.
- Do not ask for the Agnes secret in code, GitHub text, logs, screenshots, fixtures, or tests.
- Actual `AGNES_API_KEY` installation is owner/local only after code acceptance.
- Fixed upstream Agnes origin only; no arbitrary user URL.
- Missing secret fails closed with zero upstream call.
- Keep existing OpenRouter route and request-scoped BYOK compatibility.
- Do not change Padiem Chat source in this slice.
- Do not enable Agnes in the public shared-free pool yet; terms confirmation remains pending.

## Tests

Add network-free tests for:

- Agnes platform secret present/missing;
- explicit Agnes model routing;
- Agnes eligibility in controlled B14 auto routing only when policy allows;
- streaming request translation;
- tool-call/message format compatibility where current B14 contract supports it;
- zero secret leakage in logs/errors/responses;
- zero upstream calls when secret missing;
- no cross-provider credential reuse;
- OpenRouter regression;
- B14/Core/B62 regression.

## Delivery

Keep Draft until exact-head tests are green. No production deployment or secret mutation from this branch.
