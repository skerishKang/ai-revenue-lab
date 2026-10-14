# B66 quotation model response memory policy - 2026-10-13

## Scope and rationale

The live B66 quote interpreter runs a trusted one-shot exact-model request
using B14Client.complete_registered_quote_model through shared Core. B14's
Worker supports a finite 8MiB in-memory completed JSON resource budget,
but B66 previously instantiated the Core collector at its obsolete default
1MiB limit. This could refuse otherwise valid >1MiB completed responses
before B66 could parse/validate its quote fields.

B66's quote-only completed call now uses Core's existing
MAX_CONFIGURED_B14_RESPONSE_BYTES resource ceiling, leaving all general B62
Chat and Claw completion callers at their original default. The resource
ceiling is not a model output token or character limit. No client-visible
wire change, no new retry/fallback, no model activation or account grants.

The quote schema/integrity checks (item count, prices, allowed keys, quote
facts, QuoteCore totals), membership/auth, saved-skill ownership, one-shot
usage reservation, 6MB HTTP input memory guard, provider keys and worker
overload checks remain independent and unchanged.

## Focused proof

- RED: 1.1 million Korean characters in one synthetic correct B14 response
  was refused by B66's 1MiB Core collector before the fix.
- GREEN: exactly one synthetic B14 POST returns the answer verbatim and
  preserves one-shot max_retries=0. Core legacy general Chat config unchanged.
- Oversize beyond Core's existing finite maximum still fails explicitly as
  upstream_response_too_large; no silent truncation.
- B66 retired document-extraction successor lane remains OFF; its historical
  32k text constant is not a live model input/output restriction.
- Experimental Kira/Experiential direct adapters have no production caller
  reference in the tracked main app; no dormant pilot activation.
- Synthetic B66 model quote regression suite 131 tests PASS.
  CI/GitGuardian/production release checked separately.
