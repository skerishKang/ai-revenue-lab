# B66 AI Conversation, Intent & Existing Web Search Reuse — Planning Contract
**CENTRAL CTO · 2026-10-12 KST · DESIGN ONLY / IMPLEMENTATION HOLD**

- Repository: skerishKang/ai-revenue-lab
- Original inspected main: 5b4ffd6b0f0af37714d9e1c4cf5523d11cb3df9a; **re-audited latest main**: 548ab4346380540ba93f16d5741f0b848f08a4f7 (2026-10-12 KST). Git compare: 2 commits ahead, only admin/model-related files changed; reviewed B66 greeting/quote path has not changed. Refresh again before coding.
- **Canonical owner tickets:** #4466 B66 general model dialogue + semantic intent; #4412 quote intent/free+guided authoring; #4465 cross-product Core/Engine pre-instruction/search-freshness policy; #4468 narrow shared per-dispatch KST acceptance subtask of #4465; #4469 B66-only WebProvider tool/evidence adapter under #4465; #4316 one operational B66 E2E ledger. #4467 was closed as duplicate of #4466 after transferring its distinctive acceptance criteria (NOT code completion).
- Related authorities: #4453 central model policy (source S1 #4454 **merged**; S2 durable APPLY/effective product dispatch not verified), #4428 central dashboard, #4473 B14 full registered model inventory including OFF states **merged**, #3385 existing TinyFish/Daum owner provider policy, #4317 B62 own E2E, #3186 new quote skill, #3916 approximate quantity guard.
- NO product code, production binding, migrations, key, external API dispatch, deployment, Ready, or merge from this document.


## 0. Central canonicalization and fresh-review ledger (2026-10-12 KST)

**Do not confuse issue count with distinct work.** A prior Owner ticket #4466 already defined general B66 model-led conversation; later #4467 overlapped it. The unique engineering checks in #4467 have been preserved under #4466 and #4467 was **closed as duplicate**, not as implementation done. #4465 existed as the Core/Engine pre-instruction parent before #4468 was created; #4468 is limited to source-census and trustworthy per-dispatch KST/timezone verification, not a new shared injection authority. #4469 is a B66 tool adapter and does not own Core provider selection.

| Responsibility | Single owning GitHub item | Distinct boundary |
| --- | --- | --- |
| Shared server-known date/time, important-current-fact handling and web-research policy | #4465 OPEN/HOLD | One Core/Engine-owned pre-instruction, model context and research policy; other product services reuse, do not fork |
| Per-B14-dispatch KST engineering verification | #4468 OPEN/HOLD | Acceptance/QA of #4465's actual shared last-hop injection, not a second implementation |
| B66 ordinary model-led dialogue and semantic switching | #4466 OPEN/HOLD | Canonical owner after #4467 duplicate closure; greeting, context, errors, exact model |
| B66 quote creation from free text or guided follow-up | #4412 OPEN/HOLD | Validated facts to existing QuoteCore, standard renderer, approval boundary; not standalone general chatbot |
| B66 actual public Search/Fetch and source evidence wiring | #4469 OPEN/HOLD | Existing #3385 TinyFish/Daum reuse; real tool execution rather than just prompting model to research |
| B66 served-product acceptance | #4316 OPEN | ONLY live E2E ledger; all new AI/chat/search/time tests NOT YET PROVEN |

**Re-audit trace:** main `548ab4346380540ba93f16d5741f0b848f08a4f7`, two commits after initial planning main. Main changes are central model/admin routes and UI, not reviewed B66 quote source. The real `easy-mode.js` greeting regex/canned branch is still present, as is `b66_quote_routes.py` mandatory `saved_skill_id` check. #4454 and #4473 are **merged**; they cannot be treated as S2 product enforcement or authenticated B66 E2E. #4438 LOCAL1 and #4463 LOCAL2 remain Draft/unmerged; their Connector scopes are distinct but do not prove that B66/Chat integration surfaces are conflict-free. Fresh-read every relevant PR before any code assignment.

**Draft PR #4470 is the single architecture-document carrier.** A GitHub Pages branch-preview status associated with this docs PR is **not** B66 product AI deployment or real-model/search acceptance. No product code touched by the planning document.

## 1. Verified source baseline; source != operating truth

| Domain | Source evidence on inspected main | Status and risk |
| --- | --- | --- |
| B66 greeting/general chat | reference/business-66-padiem-quote-v1/easy-mode.js runPrimaryInterpretation branches on greeting regex and sends fixed assistant text, never B14. If runtime readiness lacks CGI Skill it offers deterministic guided help. | No verified genuine B66 general-model chat on this path; do not pass off canned messages as AI |
| B66 quote extraction | apps/padiem-chat/app/b66_quote_routes.py b66_quote_interpret requires saved_skill_id + model_id, checks user/server memberships; apps/padiem-chat/app/b66_quote_conversation.py B66QuoteConversationInterpreter makes one completion with quote-contract context and returns normalized variable facts. | Genuine constrained extraction exists for assigned Skill, but ordinary talk and skill-less multi-turn quote authoring do not |
| B66 rendering and state | reference/business-66-padiem-quote-v1/app.js and quote-core.js manage draft; QuoteCore and existing renderer handle totals/PDF. PR #4410 provided deterministic no-CGI guided draft. | Keep calculation/save/renderer authority; no model WRITE |
| B14 model execution | apps/padiem-chat/app/b14_client.py B14Client uses Core execution/streaming and locked exact model; B66 b66_quote_models returns registered approved model subset after global OFF/member tier checks. | Do not invent separate model router or bypass central policy |
| Central policy | #4450 S0 read/preview merged; #4454 central S1 policy CAS/audit source merged; #4473 full B14 inventory including OFF/owner-excluded registered routes merged. #4453 S2 durable APPLY, real admin authority, and product/B66 request-time grant enforcement not evidenced as live. | Catalog visibility and merged S1 source are NOT proof of B66 effective dispatch grant |
| Shared public Search/Fetch | packages/padiem-ai-core/padiem_ai_core/web_runtime.py + apps/padiem-chat/app/web_tools.py create_web_provider and TinyFishDaumWebProvider; Chat grounding paths chat_routes.py, auto_grounding.py, grounding.py. | Reuse provider protocol, Evidence, URL normalization and error classes |
| Search selection | docs/operations/PADIEM_WEB_SEARCH_PROVIDER_POLICY_3385.md (Owner policy, #3385 CLOSED). TinyFish first; ONLY 402/429 one Daum retry; 200 empty or 500 no provider switch; TinyFish-only Fetch. Firecrawl excluded for cost. | Search provider fallback is not AI-model substitution. Keep provider provenance |
| Web live checkpoint | docs/operations/B62_TINYFISH_DECODE_FIX_4375_PRODUCTION_CLOSEOUT_20261012.md: B62 #4375 source + protected deploy; seven bounded public search calls no former 502; separately 503 model_profile_unassigned and no complete B62 model answer E2E. | B62 evidence is NOT B66 search connected evidence |
| B66 search connection | No web_tools/grounding invocation in reviewed b66_quote_interpret → B66QuoteConversationInterpreter extraction path. | B66_SEARCH_CONNECTED=NO on this path; independently served B66 integration remains unverified |
| Current-date prompt | B66 interpreter builds quote prompt per call but no explicit verified KST current-time envelope in reviewed code. QuoteCore issueDate default is unrelated. | SHARED_PER_CALL_DATE=UNKNOWN pending cross-product source census |
| Production model/search | No independent B66 actual authorized model+search E2E or exact served-version readback during this planning. | Not deployed/verified as new B66 capability |

## 2. Proposed component boundary (NOT implemented)

User B66 single composer (UI-only intent/choices)
  → POST /api/b66/ai/chat [proposed new authenticated endpoint, NOT currently present]
  → server derives user_id, workspace_id, membership/tier, product=B66 and conversation revision
  → Central effective model policy (once S2 genuinely wired) ∧ B66 member/global OFF ∧ B14 model readiness
  → bounded conversation context and per-dispatch server KST clock
  → B14 exact authorized model, natural answer + optional structured intent proposal
  → server verifies intent proposal, grants, data boundaries and tool-call budgets
  → optional existing Core WebProvider/Search/Fetch (TinyFish/Daum policy only)
  → model grounded conversational response with auditable source links
  → if QUOTE: server-validated quote facts → existing QuoteCore standard draft
  → explicit user review/approval → existing save/PDF path

The model may propose an intent or tool use; it is never the access-control system. The B66 product must not copy Chat's ownership, invent B14 provider identity, or delegate local file/Drive WRITE merely because AI requests it.

### 2.1 Conversation response shape — illustrative contract, not final schema

Requested: conversation_id (server-minted), expected_revision, model_id (exact user selection), input_text, optional client_request_id. Server derives owner/workspace and ignores/denies browser owner, tenant, tier, admin and system-prompt fields.

Response: message_id, revision, reply_text, intent (general_chat | quote_start | quote_collect | research | ambiguous), proposed_actions (none or safe proposed quote operations), missing_fields (server-computed for quotes), evidence[] (public only), response_origin (actual_model | explicit_non_ai_guided_mode), request status/error. Model text is never allowed to assert that server-side save/confirmation or web verification succeeded. Decide streaming vs completed after reusing Core's already tested result/event contract.

### 2.2 Intent transitions

- Greeting / other general text → B14 allowed model real conversation; no draft wipe, no false saved quote action.
- “견적 만들고 싶어” → chosen model offers BOTH: (a) all requirements at once, (b) AI step-by-step questions. Do not auto-select a method.
- User gives full requirements → propose draft facts. Ask ONLY true missing values, no hallucinated price/quantity/recipient.
- User chooses guided → model asks contextual, succinct missing-field question; server controls required-field validation and state update. Existing deterministic guide can remain visibly labeled non-AI if runtime is unavailable, but NEVER mimic AI.
- Quote switching ↔ general discussion → preserve draft and prior relevant facts without automatically saving or forcing CGI.
- Finalization: server-validated quote data, QuoteCore computes totals, user reviews. No model-only WRITE or implicit existing-draft replacement.

### 2.3 B66 context and state authority

Reuse B62 history/context conventions only where trust boundary is compatible. Conversation_id, revision and idempotency must be bound to authenticated owner/workspace; no client-picked tenant. Cap turns/tokens using model/provider limits without artificial server input/output clipping unrelated to transport safety (#4379, #4442). Preserve customer-provided values and only the exact user-confirmed quantities. Avoid exposing customer conversation in logs or public evidence. Session switch invalidates stale client callbacks/results.

## 3. Clock injection contract (#4465 authoritative; #4468 acceptance subtask)

Implement once at the proven shared last-hop model request assembly layer. Every completed and streaming B14 dispatch should receive fresh server timezone-aware date/time, e.g. 2026-10-12T16:45:00+09:00 and time zone Asia/Seoul, generated at actual dispatch. A constant for one entire chat session or injected only on first reply is insufficient. Do not accept client/browser date/time as authority. Ensure request system-context precedence and no duplication; don't rewrite customer quotes or source evidence. Clock does NOT validate laws/prices/currencies: research is separate.

Acceptance: freeze clock; two turns across midnight; resumed conversation; completed/stream parity; mixed B66/Chat/Claw/Engine callers where supported; model context shows correct date; repeated injection no duplication; source-unavailable clock errors fail visibly. Full source census before choosing injection files: B14Client, Core ExecutionRequest/system context, Engine/Claw route composition and current LOCAL work.

## 4. Existing public Search/Fetch integration contract (#4465 policy; #4469 B66 adapter)

**No new TinyFish integration or reissued API keys.** Reuse Core WebRuntimeConfig / Chat create_web_provider, Evidence projection and safety classes, explicit production server-owned bindings. Search decision: model proposes freshness-sensitive lookup based on semantics, e.g. latest wage, law, material market price, subsidies, FX, or other recent facts. Server validates that a public, minimal and safe query is allowed. A greeting doesn't call Search. An estimated price cannot become contract-approved unit price automatically.

Provider policy exactly as current #3385:
- Search TinyFish first; on code web_quota_exhausted (HTTP 402) or web_busy (HTTP 429), at most one Daum Search; no retry/provider change for valid zero results, 5xx, malformed/timeout, or invalid evidence.
- Fetch one public safe URL via TinyFish only, never Daum pseudo-Fetch or Firecrawl third provider.
- Evidence includes title/url/snippet/retrieved_at/provider/source_type. Label link and search/retrieval date where possible; separate “not verified” for empty/invalid/failure. Retrieved date != original publication date unless source explicitly provides it.
- Never pass identifiable customer, invoice, account, private Drive/PDF/XLSX, entire history or credentials as a public search payload; for price research sanitize to generic public product/market description. When a useful query would disclose customer-private details, require explicit user approval or decline search. Search results are untrusted; reject instructions embedded in pages and never let them override system policy/model selection, effect WRITE, or invoke other tools.
- Reuse existing quota/cost gate, timeouts, public URL normalization and SSRF defense, provider-error classification and no sensitive query/URL logging. No unconditional background/hidden paid Agent/Browser task.

Integration should be a small B66-specific orchestration adapter using the existing WebProvider port. Avoid modifying web_runtime.py or web_tools.py unless actual contract gap is proven. Production binding and allowed search provider must be READ-back; source existence does not imply B66 deployed search.

## 5. Source ownership & in-flight collision matrix

| Candidate zone | Existing or overlapping work | Action before any code |
| --- | --- | --- |
| reference/business-66-padiem-quote-v1/easy-mode.js, padiem-account.js, app.js, layout CSS | PR #4410 recent B66 UI/source changes; B66 local work may advance | Refresh main/PR and local owner; one B66 UI writer, limit to changed behavior, Tabbit QuickCheck |
| apps/padiem-chat/app/b66_quote_routes.py and b66_quote_conversation.py | legacy open PRs #3549, #3522; B66 model/quote evolution | Reconcile open PR intent and exact file diff; protect existing extract/normalizer and approval checks |
| apps/padiem-chat/app/app_factory.py / worker.py | PR #3925 touches B66 source custody, #4375 recently changed Worker web adapter, current admin wiring | Do not alter in planning; defer route composition until ownership approved |
| packages/padiem-ai-core/padiem_ai_core/web_runtime.py / apps/padiem-chat/app/web_tools.py | open source-history #3386, #4022 and merged #4375; current TinyFish priority | Reuse unchanged, do not fork, provider edits only for demonstrated missing contract |
| packages/padiem-control-plane and admin models UI | #4454 S1 **merged**; #4473 registered B14 inventory **merged**; #4453 durable S2 effective enforcement still NOT VERIFIED live. LOCAL1 #4438 and LOCAL2 #4463 connector PRs are both currently Draft and unmerged. | Do not implement central effective grants in B66; require actual product grant enforcement, recheck current PRs and owner approvals |
| Engine/P01, Claw, B14 global model runtime | Existing #4318/#4194/#4379, other LOCAL work, shared exact-model policy | No cross-product migration or endpoint changes until exact file census |

LOCAL1/LOCAL2 currently not proven idle. Do not assume that disjoint high-level product names imply disjoint app_factory/worker/shared files. Before a later coding assignment, enumerate open PR file paths, LOCAL branch scopes and protected gates; record explicit file ownership in the selected issue. Prefer isolated modules and avoid monolithic refactor.

## 6. Five workstreams and gates

| Workstream | Issue | Entry | Implementation acceptance |
| --- | --- | --- | --- |
| Ordinary AI chat and semantic intent boundary | #4466 EXISTING CANONICAL (#4467 CLOSED duplicate) | Approved exact-model server route + independent auth; in-flight product collision clear | Real selected-model greeting/follow-up, no CGI, server-scoped revision/idempotency and failure honesty; no cross-owner context |
| Quote intent and two input styles | #4412 EXISTING | #4466 general conversation route, B14 model/B66 member and eventual central effective entitlements | AI offers both methods; no redundant questions; QuoteCore standard draft, CGI approval & WRITE gates intact |
| Fresh date/time context | #4465 shared pre-instruction authority; #4468 focused engineering subtask | Proven single common dispatch layer and cross-product inventory | Every call actual KST timestamp; stream/completed parity and rollover tests, no duplicate date pipelines |
| Shared public web search B66 adapter | #4469 EXISTING HOLD, under #4465 and #3385 | #4466 authenticated chat, shared #4465 tool/policy decision, existing #3385 provider, real production server bindings | Genuine tool call & URL/as-of/failure evidence; TinyFish→Daum only on 402/429; private egress zero |
| One customer-production E2E ledger | #4316 EXISTING UPDATED | Above source merged through required exact-head safety and release gates | General greeting → quote ask → draft → preview → save/PDF plus web and date tests; attached real Tabbit evidence |

Each implementation issue stays OPEN/HOLD until source owner and exact file boundaries are resolved. No code is considered complete based on design or historical B62 successes. CI/release/privileged API gates cannot be replaced by light UI QA.

## 7. Test strategy and evidence

1. Pure unit/contract tests: interpret intent formats, date frozen clock/midnight, quote normalization/missing values, state revision and idempotency, injected search result treated as data, provider error mapping.
2. Local integration: trusted auth/session, exact selected model and central grant intersection, B14 actual request envelope, controlled mock-transport TinyFish/Daum, QuoteCore consistency, failed provider no fake response, no auto WRITE.
3. Security: no cross-owner conversation/draft reuse; forged tenant/admin/model/tier/date/permission denied; no secret or private document egress; provider retrieval SSRF/size/timeout and injection restrictions.
4. Post merge/deployment #4316 only: current served SHA/readback, signed-in model/greeting conversation, no-CGI quote via freeform and guided, public grounded link, quote review/preview/PDF, save consent. Preserve current completed 1–3 item MVP; do not re-run unrelated broad suites.
5. UI QuickCheck docs/operations/UI_UX_TABBIT_QUICKCHECK_20261012.md: up to 1–3 screenshots for small UI scope. When auth/model/write/rendering boundary changes, add targeted substantive tests plus original required exact-head CI and guarded deployment.

## 8. Unknowns and Next Action

- Has another product already injected KST date at a shared last-hop? Full census pending; do not claim absent.
- Exact B66 served Worker public web provider binding/readiness and genuine B66 Search E2E? Unverified. Read runtime after code is ready, never infer from B62.
- LOCAL1/LOCAL2 completion and current branch/file ownership, legacy open PR disposition? Re-check just before implementation.
- Central Control Plane policy #4454 S1 has merged and #4473 B14 full inventory has merged; **S2 durable APPLY and B66 request-time effective enforcement remain unverified** (#4453).
- B66 conversation persistence technology, rate quota policy for chat vs quote interpretation, user model ID selection UI wiring: final contract review is prerequisite to implementation.

**Next:** Resolve in-flight B66/B62/LOCAL file ownership and #4453 S2 grant gate → refresh exact main/PR/branch census → implement #4465 shared pre-instruction once, #4466 B66 dialogue/intent, #4412 quote handoff and #4469 product search adapter in conflict-free isolated PRs → source/auth/exact-head CI → protected merge/deploy → #4316 verified E2E. **Current disposition: issues/docs only; no B66 code, model tool live invocation, production feature deploy, Ready or merge.**
