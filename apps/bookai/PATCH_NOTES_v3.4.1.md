# StoryMemory v3.4.1 — SM-083 Trust Modes + Answer Provenance

Date: 2026-08-27
Status: IMPLEMENTATION + DETERMINISTIC CONTRACT QA PASS
Deployment: DEFERRED_TO_BI_PORTAL
Business: B61
Portal target: /b61/

## What changed

- Upgraded `storymemory-universal-source-runtime-1.0` to runtime version `1.1.0`.
- Added executable Trust Modes: `EXPLORE`, `GROUNDED`, `STRICT`.
- Added answer provenance labels: `AI_NATIVE`, `SOURCE_GROUNDED`, `PACK_ASSISTED`, `VERIFIED`, `INTERPRETATION`, `UNCERTAIN`.
- Added per-Source Trust recommendation/override APIs and passed Trust options through the current Reader bridge without rebinding the production UI.
- Added post-generation validation so Grounded/Strict factual answers cannot be accepted merely because the model sounds confident.

## Trust behavior

### Explore
- Model prior knowledge and reasoning may be used actively.
- Source retrieval remains available but citation is not mandatory for every answer.
- An uncited model answer is explicitly labeled `AI_NATIVE`; it is not mislabeled as grounded.
- Existing fiction progress/spoiler visibility remains enforced.

### Grounded
- Source-specific factual provider answers require Source locator/citation.
- Provider answers without valid citations are blocked and returned as `UNCERTAIN`.
- High-risk provider claims can carry structured claim evidence for exact validation.

### Strict
- Factual claims require Source evidence or qualifying verified Pack evidence.
- Unsupported high-risk claims are blocked rather than rewritten into plausible prose.
- `UNKNOWN / NEEDS REVIEW` is a normal result.
- Low extraction quality cannot claim Strict-ready when Strict is requested at ingest.

## Source-specific policies

- Bible/Scripture defaults to Strict. Textual fact and `INTERPRETATION` are separate answer types; model/theological interpretation is never silently relabeled as textual fact.
- Contract/legal/official-record sources default to Strict. Exact claim validation supports numbers, dates, amounts, clauses, names, quotes, verses, answer/condition/exception claim kinds when the provider supplies claim metadata and source refs.
- Research/study/work documents and workbooks default to Grounded.
- Workbook answer/solution blocks are excluded from retrieval in Tutor/hidden mode and cannot be reintroduced by the provider. Explain/reveal must be explicit.
- Fiction/general reading defaults to Explore and continues to use the existing progress-bounded no-future-content gate.

## Pack trust / provenance

- Pack provenance now tracks pack id/name/version/trust tier/verification scope.
- Unverified/auto-generated Pack evidence produces `PACK_ASSISTED`.
- `VERIFIED` is emitted only when evidence came from a qualifying Gold/verified/curated/expert/official/publisher tier.
- A high Pack tier does not convert interpretation into textual fact; interpretation keeps its separate label.

## QA

PASS:
- Explore AI-native classification.
- Grounded citation-required blocking and Source-grounded pass path.
- Strict legal-like exact claim pass and wrong-number block.
- Strict unknown/needs-review path.
- PACK_ASSISTED and VERIFIED provenance.
- Pack name/version/tier traceability.
- Bible textual fact vs interpretation separation.
- Workbook answer reveal gate.
- Strict low extraction quality gate.
- All six provenance labels covered.
- SM-082 Universal Source regression PASS.
- Current Reader exact-position bridge regression PASS.
- SM-057 Hybrid AI Context regression PASS.
- SM-058 Production Runtime, Static Reader, Hybrid AI regressions PASS.
- `dist/content` vs v3.4.0: 192 files, changed 0 / missing 0 / extra 0.
- JavaScript syntax and six inline scripts PASS.

## Explicit non-claims / deferred

- This does not claim semantic verification of arbitrary free-form model prose without structured claims/source refs. The Harness enforces the evidence contract it can inspect.
- Raw PDF OCR/parser acquisition and live URL/YouTube/STT acquisition remain upstream/deferred.
- Mixed-Source Trust/Pack UI is still SM-087.
- Executable Pack format lifecycle is expanded in SM-084; Marketplace remains SM-085.
- Odyssey Books 21–24 remain no-precompute blind evaluation material for SM-088.
- Browser/live deployment acceptance is not claimed.

## Mutation boundary

- Neon mutation: NONE
- Cloudflare mutation: NONE
- BI Portal mutation: NONE
- DNS mutation: NONE
- Odyssey Book 21+ manual knowledge expansion: NONE
