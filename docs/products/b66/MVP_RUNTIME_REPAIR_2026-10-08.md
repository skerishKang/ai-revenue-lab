# B66 MVP runtime repair — 2026-10-08

**Owner model decision reconciliation (2026-10-08):** The B66-specific free-first selection rule here does not authorize old B14 catalog entries excluded by the owner (Kilo Poolside Laguna, B.AI Qwen, Motif 3, GPT-5.6 Luna, NVIDIA Nemotron). See [B14 owner model decision ledger](../../operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md). Protected Production CGI Guided PDF passed, while Complete Freeform returned HTTP 502/upstream_timeout on one interpreter POST and no retries/fallback; selected exact model ID was not observed. Partial follow-up remains untested and CUSTOMER_READY=NO. Source fix evidence and real Production completion are separate.


Work contract: owner requested direct repair of the independently reproduced B66 MVP failures. This slice updates Draft PR #3762, preserving its approved registered/free-first policy and the existing CGI browser PDF delivery path.

```text
CHANGE_RISK=T2
IMPLEMENTATION_BASE=c68f64b13991fd907615eb75ea2b7cdd5aa82667
PR_BASE_HEAD=7a70d56151499405651d9c69806ab3d567f49ed7
MAIN_MERGED_FORWARD=878eda2c58a9e27e291e9967a59d64dfe92012fc
LIVE_PROVIDER_CALLS=0
PRODUCTION_MUTATION=0
CUSTOMER_READY=NO
```

## Repaired behavior

- The exact quote client checks runtime/live/binding readiness before registered-model resolution. Mock or deadman-off execution performs no registry or provider calls.
- The authenticated quote route uses the existing UsageGate after valid input and owner-scoped saved-skill lookup. Denial or unavailable admission prevents model resolution and execution. Quota denial retains Retry-After through the Pages proxy.
- B66 passes max_retries=0, max_attempts=1 and allow_external_fallback=false through the existing Core request. Other product retry defaults and model choices remain unchanged.
- Quota reservations remain active through validation and serialization. Dispatch marks a per-reservation shared state immediately before the binding/HTTP call, including Core's child task. Provable pre-dispatch failure refunds the three recorded buckets once; timeout, provider failure and ambiguous transport failure after dispatch remain consumed.
- Runtime unavailable, model selection unavailable/ambiguous, provider failure and malformed provider response have distinct bounded diagnostics. No customer text, provider bodies or exception messages enter diagnostics.
- Missing item name, quantity or unit price produces a partial candidate. Follow-up asks only for a required fact and preserves known facts, including person-only recipients. Supplied invalid booleans, numbers and text still fail validation; null is never coerced into a final zero price or quantity.
- CGI accepts at most three summary items. Freeform and guided input refuse unsupported rows before final draft acceptance; the certified preview no longer silently slices away a fourth item. CGI detail output receives an explicit unsupported-scope response. Generic skills retain their existing row/detail capability.
- Person-only recipients appear in the shared CGI preview/PDF drawing projection. QuoteCore remains the sole calculation authority; the PDF engine and private source assets are unchanged.

## Verification

Implementation self-check: 233 tests passed across 15 focused Python modules, plus nine affected Node contract scripts. These cover the actual Core payload and actual B14 gateway with an in-memory timeout provider: the repaired request invokes the provider double once, while removing max_retries invokes it three times. No real model service is used.

The focused admission tests use real UsageGate, refundable counters, authenticated ASGI requests and the actual exact-model/Core binding adapter. They verify denial before I/O, missing gate/store/salt, owner/input validation, one-time compensation, sequential requests and post-dispatch timeout/server accounting.

Client contracts cover minimal follow-up answers, multiple/duplicate item names, person-only recipients, three-row acceptance, four-row rejection, unchanged generic skill behavior, preview/PDF projection and bounded proxy headers. The existing B66 PR contract job now runs the browser PDF, follow-up and MVP runtime scripts. Original source line endings and git diff whitespace checks pass.

Independent validation must name the final exact PR head in the PR review history. CI results and that review record are separate from this implementation self-check.

## Delivery limits

This is source repair, with no merge, deployment, credential/configuration change or real provider call. After authorized deployment, the bounded CGI complete-input, missing-price follow-up and person-only-recipient account journeys still need real production PDF verification before customer handoff.

PR #3549's earlier token-budget change must be reconsidered against the current registered-model facade before merging: its TaskMode argument conflicts with the facade's skill=None contract, and its previous default-budget premise is stale. It is not required or incorporated into this repair.
