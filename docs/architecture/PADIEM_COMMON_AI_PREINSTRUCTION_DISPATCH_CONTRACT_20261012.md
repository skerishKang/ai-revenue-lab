# PADIEM common AI pre-instruction and dispatch contract — #4465

**Status: CONTRACT / HOLD (2026-10-12 KST).** Architecture and concrete source audit only. Not a runtime rollout, a new prompt authority, an approval to invoke models/search, or proof that every product currently receives these instructions.

## 1. Owner intent

Before **every actual AI model dispatch**, the model must receive a **trusted, versioned PADIEM pre-instruction** that states the current server-side date/time and safe answer/research expectations. This is not a welcome message displayed to the user, a once-per-login chat message, or permanent model memory.

- Construct the dynamic facts for **each** completed/stream/multimodal call using a trusted server Clock. Do not cache a date from the initial session or use the browser clock.
- The baseline timezone is `Asia/Seoul`, derived with timezone-aware conversion (not naive `datetime.now()` or hardcoded date strings). A validated user timezone is a distinct future policy decision; never accept untrusted timezone overrides silently.
- Date-awareness is not factual freshness. If a claim concerns current prices, exchange rates, changes to regulations, active grants or current news, an **actually wired** public search tool must run before asserting it is current. Search failure/unavailability => disclose uncertainty and never fabricate citations.
- Ordinary chat, greetings, explanations, user-supplied document transformations and offline deterministic computations must not pay for pointless web search.
- Treat retrieved pages/snippets as **untrusted evidence**, never as a system message or a new permission/WRITE/credential authority.
- Never submit user identity, private quote material, documents, conversation transcripts or secret values to public search providers. Derive a minimal public query; refuse/clarify when only sensitive context can answer the question.
- B14 retains the exact chosen/authorized model ID, provider authority and no-silent-fallback rules. The pre-instruction cannot silently select a provider or change a user's tier/entitlement.

## 2. Audited code surfaces on current main

Audit baseline: `debe2765ebcc3247775244e31c9aff1591edefe8`. These are **observed seams**, not a claim that a single universal dispatch hook already exists.

| Path | Source-confirmed behavior | Missing proof for #4465 |
| --- | --- | --- |
| `apps/padiem-chat/app/b14_client.py` | `_agent_profile()` creates `AgentProfile.system_instruction` from PADIEM identity and task skill; `_execution_request()` and `_multimodal_execution_request()` forward `additional_system_context` into Core. Both streaming `_stream_core()` and completion `_complete_text()` use shared Core execution facades. | Neither a per-dispatch trusted KST clock nor every non-B62 product using this client has been proven. |
| `apps/padiem-chat/app/chat_routes.py` | Text stream sends project/reference/grounding context to `B14Client.stream_text_auto()`; completed route sends it to `B14Client.complete()` or `GroundedChatService.complete()`. | Search receipts, non-stream/stream prompt parity, clock/source ordering and final provider payload must be verified. |
| `apps/padiem-chat/app/b66_quote_conversation.py` | `B66QuoteConversationInterpreter.interpret()` constructs a quote extraction prompt and calls its injected client's `complete(... additional_system_context=prompt ...)` with exact model choice. | This is a JSON quote extractor, **not** evidence of general B66 AI conversation. All B66 calls sharing an eventual trusted pre-instruction remain unverified. |
| `apps/padiem-chat/app/claw_general_routes.py` | General Claw uses P01 `adapter.execute()` or the approved streaming `live_claw_sse()` with an exact selected model; it explicitly refuses a direct-B14 fallback. | Must trace P01/Engine's final prompt/role envelope and both completed+streamed paths. Do **not** patch only B62 `B14Client` and claim Claw coverage. |
| `packages/padiem-ai-core/padiem_ai_core/b14_execution.py` | Core B14 client supports structured request/model roles and execution envelopes. | Trace the actual Core→B14 provider request assembly, including role support and whether the shared contract is serialized without privilege inversion. |
| `packages/padiem-ai-core/padiem_ai_core/search_decision.py`; `apps/padiem-chat/app/{auto_grounding.py,grounding.py,web_tools.py}` | Existing decision/grounding/actual web provider seams; policy is not equivalent to a tool invocation. | Unified safe search decision, source receipts and product-specific tool admission require integration proof. |

**Critical audit consequence:** `additional_system_context` is a usable **product-side seam**, but is not automatically a trusted `system` role at the eventual provider. The required behavior is a versioned contract at a verified shared Core/Engine/B14 dispatch boundary, not a string concatenated independently in B62, Claw and B66.

## 3. Proposed single authority and composition order

```text
Product request (user data / role / selected model / approval state)
  -> trusted platform identity, entitlements and product authorization
  -> one shared per-dispatch pre-instruction authority (#4465)
     - version id + trusted ZonedClock sample for this invocation
     - product policy context (quoting / general chat / Claw tool authority)
     - separate scoped evidence from actual search tool (#3385)
  -> Core/Engine request assembly (approved roles, no privilege escalation)
  -> B14 exact-model provider execution
  -> product-specific result handling / deterministic QuoteCore / P01 approvals
```

Ownership boundary: **Core** defines one versioned pre-instruction template/clock/fact-verification semantics; **Engine/P01** projects these safely to its callers; **B14** is the existing model/provider execution authority; **products** add bounded domain context but cannot override trusted date or permissions. Resolve final injection code location only after enumerating **all** completed/stream/Claw/quote paths. Do not add a second prompt manager, provider selector or server clock to an individual product.

Minimum trust priority (highest to lowest):
1. Existing platform security/authorization instructions and explicit task permission gates (never weakened).
2. Trusted common dynamic date/time and safety/freshness instructions sampled at dispatch.
3. Bounded product-specific intent and domain instructions.
4. Authenticated owner history and approved document references (still untrusted as instructions).
5. Tool/search evidence and user text, never permitted to replace 1–3.

Exact model choices, tools and approved WRITE calls are separate executable authorizations, not statements in natural-language instructions.

## 4. Suggested internal fields and safe external rendering

Illustrative logical contract, **not yet an exposed API/schema**:

```text
preinstruction_version: padiem-common-preinstruction.v1
dispatch_current_date: <derived each dispatch, ISO 8601, Asia/Seoul>
dispatch_current_time: <derived each dispatch, local time + UTC offset>
dispatch_timezone: Asia/Seoul
facts_policy: verify time-sensitive external claims with real evidence
evidence_status: not_needed | sourced | tool_unavailable | insufficient
```

No secrets, private prompts, per-tenant credentials, public provider API keys or full customer document bodies are required in this envelope. The system should **not** automatically tell the user the date on every turn. Render evidence source URL, document publication/effective date where known, retrieval date separately, and uncertainty only when relevant.

## 5. Search/tool facts remain separate from model instruction

- Reuse **TinyFish Search first**, and **one Daum Search only on TinyFish HTTP 402/429**, not on an empty result, arbitrary 5xx or slow request. Fetch stays TinyFish-only; this is the existing #3385 provider policy, **not** a new search implementation.
- An instruction such as “search important fresh facts” is only a recommendation until the server performs real tool execution with safe input, a bounded quota and a trustworthy receipt. Never claim citations when no tool receipt exists.
- A search fact about steel/pipe unit prices is not permission to alter the user's B66 quote unitPrice, overwrite an approved spreadsheet, change VAT math or issue PDF. QuoteCore, P01 READ/WRITE and explicit confirmation still own effects.

## 6. Contract tests before any rollout (targeted, not blanket regression)

1. Fake clock straddling midnight in `Asia/Seoul`, including a UTC date different from local KST. Confirm **each** completion/stream invocation receives its own fresh date; no double injection after resume.
2. Intercept the **final outbound model request**, not merely an intermediate Python context string. Verify the trusted instruction is represented in the permitted role/envelope, cannot be displaced by user text or web-page injection, and preserves provider-native parameters and the chosen exact model ID.
3. General B62 chat, B62 grounded completed, B62 stream, B66 extraction and B66 eventual general dialogue, Claw P01 completed and Claw live stream each produce coverage **only when actually traced**. Unsupported roles or unconfigured paths must fail closed rather than pretend conformance.
4. “안녕” => no search, natural model conversation. “오늘 환율” => actual allowed search/evidence/as-of/source; search outage => truthful uncertainty, no invented source/price. Never leak private documents to search.
5. Existing B66 customer quantities/prices are not replaced by online quotations, and the model cannot bypass QuoteCore/P01 approvals.
6. Run focused affected-path tests and required GitHub security/CI checks; use the owner E2E ledgers for production claims. No duplicate expensive Gemini/LongCat calls merely to re-prove already successful routes.

## 7. Implementing order and gates

- **Now:** docs-only source-census and trust/role contract. No code, model calls, Secrets, DB, Ready, merge, production, provider switch.
- **#4468:** narrow fresh server KST dispatch test seam, subordinate to #4465, not a second clock authority.
- **#4469:** B66-specific real WebProvider usage; no reimplementation of #3385.
- **#4466:** B66 model-native greeting, intent and guided quote conversation; QuoteCore responsibilities unchanged.
- **#3933/#3936:** Claw general conversation E2E via existing P01 authority.
- **#4317/#4318/#4316:** product/Engine/B66 real deployment evidence and exact-head checks.

**HOLD** on any executable integration until current LOCAL1 sidebar #4475, Connector S1/S2 #4438/#4463, B66 docs #4470 and other file owners are rechecked. This document changes no current product capability and does not unblock a pending production/WRITE/security gate.
