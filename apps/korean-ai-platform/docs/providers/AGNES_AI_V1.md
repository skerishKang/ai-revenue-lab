# Agnes AI Provider Intake — B14 V1

Status: **RE-REGISTERED, PLUS TEXT ROLE SELECTED** — see the reconciliation below
before using the historical banner wording further down.

Historical accuracy note (corrected 2026-10-07, #3554): this record previously
carried a blanket `RETIRED (#1933 S2-b, 2026-09-07)` banner claiming the Agnes
route "is no longer registered in production code or the catalog". That statement
was false against the tree it lived in: `app/pilot/agnes_provider.py` registers
`agnes-ai/agnes-3.0-flash` into the exact-ID `CATALOG_BY_ID` table (manual-pin
only, deliberately absent from `CATALOG_MODELS`), `apps/korean-ai-platform/wrangler.toml`
carries the `PADIEM_AGNES_API_KEY` secret-store binding, and
`tests/test_agnes_provider.py` pins both facts. #1933 S2-b retired the *first*
integration; #2126/#2133 re-approved and re-onboarded the provider. The banner is
replaced here by that sequence so the provenance chain is auditable.

Current owner decision (2026-10-07, #3554): `agnes-ai/agnes-3.0-flash` is the
Padiem Plus **text** primary. Vision stays unselected, `image` capability is not
claimed for Plus, and no lane may act as a silent fallback.

Original status: CANDIDATE / OWNER_TEST_ONLY

## Verified public integration facts

- Provider: Agnes AI
- International OpenAI-compatible base URL: `https://apihub.agnes-ai.com/v1`
- Authentication: Bearer API key
- Key environment name for local/owner setup: `AGNES_API_KEY`
- Primary text model candidate: `agnes-2.5-flash`
- Chat endpoint: `POST /v1/chat/completions`
- Capabilities advertised in current public catalog: chat, streaming, tool calling, coding, reasoning, multi-turn dialogue, image understanding, agent workflows
- Current public free/default text rate reference: 20 executable RPM (30 public-request RPM reference)

## B14 route proposal

```text
provider_id = agnes-ai
model_id = agnes-ai/agnes-2.5-flash
upstream_model = agnes-2.5-flash
credential_source = platform_secret
credential_binding = AGNES_API_KEY
base_url = fixed https://apihub.agnes-ai.com/v1
```

`b14/auto` and explicit model selection must both remain supported.

## Security boundary

- No Agnes key in Git, registry JSON, logs, screenshots, fixtures, issues, PR text, or API responses.
- Actual key installation is owner/local only after code acceptance.
- Fixed upstream origin only; no user-supplied base URL.
- Missing secret fails closed with zero upstream calls.
- Agnes credential cannot be reused for another provider.

## Public/shared-use boundary

Current public Agnes materials clearly support developer API integration and document a Free/default API-key tier. Public materials reviewed for this intake did not provide a sufficiently explicit statement authorizing or prohibiting use of one free/default key as a shared public multi-user inference pool.

Therefore V1 disposition is:

```text
B14_CODE_INTEGRATION = ALLOWED
OWNER/LOCAL_SMOKE = ALLOWED
LIMITED_FIRST_PARTY_TEST = ALLOWED
PUBLIC_SHARED_FREE_POOL = HOLD_PENDING_TERMS_CONFIRMATION
```

Do not mark this provider as generally public/shared-free until terms or account-level guidance is confirmed.

## Source date

Research snapshot: 2026-08-27 Asia/Seoul. That snapshot covers `agnes-2.5-flash`
and is NOT the evidence for the currently registered model id below.

## Re-verification evidence for `agnes-3.0-flash` (2026-10-07, #3554)

`app/pilot/agnes_provider.py` previously stamped this provider's registration
with `source_checked_at="2026-08-27"` while registering `agnes-3.0-flash`, a
model that the 2026-08-27 intake never named. The stamp is corrected to the date
the lane was actually re-verified, from these observations:

```text
MODEL_ID_EVIDENCE = POST https://apihub.agnes-ai.com/v1/chat/completions with
                    model="agnes-3.0-flash" -> HTTP 200 and the provider echoed
                    model="agnes-3.0-flash" in the response body. The exact model id is
                    therefore accepted by the registered origin.
CATALOG_GET       = NOT PERFORMED against apihub.agnes-ai.com (#3554 recorded
                    new_catalog_gets=0). The id claim rests on the accepted request plus
                    the provider echo above, not on a /v1/models listing.
THIRD-PARTY_NOTE  = agnes-3.0-flash also appears in third-party router catalogues
                    (aihubmix.com, api.unorouter.com, kiosapi.com). Those are NOT
                    evidence for the direct origin and were not used as such.
EXTRACTION_CASE   = owner-approved single direct-provider call, synthetic Korean
                    quotation, temperature 0, strict JSON only:
                    7/7 exact facts, 0 extra keys, 0 prose, no code fence,
                    1.41s, HTTP 200, finish_reason=stop
COST              = the response carried no cost / market_cost /
                    upstream_inference_cost field → COST_STATUS=UNCONFIRMED
```

Two honesty limits on this evidence, both material to registration review:

1. The calls used the operator's locally configured CLI credential, **not** the
   Cloudflare secret-store `PADIEM_AGNES_API_KEY` binding. Production binding
   readiness is a separate, still-pending check (`#3554` step 6/7).
2. Extraction quality is `n=1` — one lane-verification `PONG` probe (HTTP 200,
   660 ms) and the single structured case above. That proves transport and
   structured-output shape, not answer quality at volume, and no rate-limit or
   daily-quota behaviour was measured.
