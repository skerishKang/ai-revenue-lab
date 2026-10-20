# #4469 — Claw shared web search evidence/UX gap

STATUS: DRAFT / IMPLEMENTATION_NOT_STARTED
OWNER: LOCAL IMPLEMENTATION
BASE_MAIN: d0684b3c9bb95f1ab3511ed1d671102924a8624d
ISSUE: https://github.com/skerishKang/ai-revenue-lab/issues/4469

## Existing authorities
- #3385: implemented IP-CORE WebProvider and search/fetch source contracts.
- #4761: merged shared search guard.
- #4469: single cross-product acceptance tracker for Chat, Claw and B66.
- #3936/#4318: separate Claw P01/model/runtime acceptance boundaries.

## Implementation scope
1. Inspect current main and live-surface wiring in Claw to identify the first actual missing connection between existing shared Core WebProvider results/evidence and Claw's user-visible conversation answer.
2. Reuse existing search provider and evidence normalization. Add only a thin product display/response adapter if genuinely absent, without creating a second search engine.
3. Present grounded source URLs, titles and source/reference date when available. Never fabricate a source or label a model-only answer as an executed search.
4. Focused tests: authenticated result display; no-results; denied/unavailable tool; stale or missing citation; correct owner/conversation attribution; no raw credentials or hidden reasoning.
5. Preserve completed Chat/B66 search work. Report exact tested scope, any remaining live account E2E, CI, merge, deployment independently.

## Excluded
All PC/Drive/mobile connectors, local devices, broker and Mesh changes. No new web-search provider, API key, model routing, quota or pricing policy.
Do not run live external search in production as a side effect of a scope-only PR.

This is a LOCAL handoff, not a working product implementation.
