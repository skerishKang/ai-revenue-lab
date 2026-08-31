# B62 / P01 / B14 / Control Plane Ownership Review

Date: 2026-08-31 (refresh on current main af28f6ea)
Repository: `skerishKang/ai-revenue-lab`
Supersedes: #1229 (docs/b62-p01-boundary-review-20260831 @ 0997ccc / base 17de5fc)

## Purpose

Record the current architecture decision for Padiem Chat (B62) as the product approaches functional maturity while P01 Padiem AI Platform/Core/Engine and Business 14 continue to evolve underneath it.

The central rule is:

```text
B62 = PRODUCT SURFACE + PRODUCT-OWNED CHAT DATA
P01 CORE/ENGINE = SHARED EXECUTION SEMANTICS
B14 = PROVIDER/MODEL ROUTING + EXECUTION
CONTROL PLANE = CANONICAL IDENTITY / ENTITLEMENT / USAGE / CREDIT
```

B62 should become better primarily by consuming stronger shared platform capabilities, not by reimplementing them locally.

This refresh is documentation-only, built from current origin/main af28f6ea, incorporating completions since #1229 was opened.

## Canonical ownership lock (unchanged)

| Capability | Owner |
| --- | --- |
| Chat UI / Composer / Sidebar | B62 |
| Conversation/message persistence | B62 |
| Projects / project navigation | B62 |
| Product file picker/upload UX | B62 |
| Saved Outputs / Copy / Download / Export | B62 |
| Mobile / accessibility / themes | B62 |
| Auto/Fast/Balanced/Deep presentation | B62 |
| Provider/model selection | B14 |
| Provider credentials | B14 |
| Provider fallback/retry | B14 |
| Agent / Reusable Skill / Tool execution | P01 Core |
| Memory/RAG trust, read/write policy | P01 Core |
| Evidence / verification | P01 Core |
| Cross-runtime Service Binding/API | P01 Engine |
| Canonical identity/session | Shared Control Plane |
| Canonical entitlement / usage ledger / credit | Shared Control Plane |
| Product admission/abuse quota | B62 |

## Post-merge state (as of af28f6ea / 2026-08-31 — current main)

Since #1229 (base 17de5fc) main has advanced through:

- **#1250** B62 UI settings/theme/locale — settings dialog, padiem-home default theme, KR/EN controls moved into settings, same-origin Padiem Home, in-memory theme/locale, persistence audits PASS.
- **#1252** B62 bounded document attachments — bounded OOXML/PDF handling, `binary_documents.py`, `ooxml_stdlib.py`, `document-binary.js`, unsafe-path/encrypted/size guards merged.
- **#1253** XLSX OOXML DTD guard — archive-level `b"<!DOCTYPE"` scan for `.xml`/`.rels` after size checks, XLSX regression tests, merged via follow-up.
- **#1254** Core multimodal execution facade — `MultimodalExecutionRuntime` / `MultimodalExecutionRequest` as shared Core facade; split #1068 now DONE.
- **d59804dc** B62 provider-neutral chat mode contract — `chat_modes.py` `ChatMode`/`CHAT_MODE_CATALOG`/`resolve_chat_mode` with provider-neutral catalog and fail-closed `Executable` request behavior (only `auto` accepted for now).
- **b5817b15** Control Plane identity/usage-event foundation — `IdentityLinkState`, `MonetaryCostEvidence`, `UsageEvent`/`UsageOutcome` and related contracts as canonical Control Plane foundation.
- **#1256** P01 cumulative stack merge-forward — P01 Core/Engine/Control-Plane cumulative semantics (adapter, agent, evidence, memory, orchestration, retrieval, skill, tool lifecycle) rebased onto current main, preserving B14/B62 authority and multimodal facade.
- **#1259** Core bounded retrieval trust seam — `RetrievalProvider` / `RetrievalRequest` / `RetrievedItem` / `PreparedRetrieval` with `prepare_retrieval_context` and `MAX_RETRIEVAL_NAMESPACES`/`MAX_RETRIEVAL_RESULTS` bounds.

All of the above are now present in origin/main af28f6ea. This document records them as completed, not as future work.

## Current code review findings (updated)

### 1. B62 multimodal path — RESOLVED via #1068 / #1254

**Historical finding (as of #1229, now resolved):** `apps/padiem-chat/app/b14_client.py` `_complete_image()` previously constructed low-level B14 multimodal request/routing objects directly.

**Current state (af28f6ea):** The shared Core multimodal facade is now DONE (`#1068` → `#1254`). `padiem_ai_core/multimodal_execution_runtime.py` exposes `MultimodalExecutionRequest` / `MultimodalExecutionRuntime`, and `apps/padiem-chat/app/b14_client.py` now consumes that facade. The previous B62 → B14MultimodalChatRequest direct construction is retained only as a resolved historical reference, not as a current fact.

```
Historical:
B62 -> B14MultimodalChatRequest/B14RoutingOptions -> B14

Current (resolved):
B62 -> Core multimodal execution facade (MultimodalExecutionRuntime) -> B14
```

Disposition: **DONE** — #1068 closed via #1254. Do not reintroduce direct B14 image assembly in B62. B62 image path should now consume `MultimodalExecutionRuntime`.

### 2. Current B62 `Skill` is semantically a Task Mode, not a canonical Reusable Skill

`apps/padiem-chat/app/skills.py` currently defines lightweight product presets such as:

```text
auto
explain
plan
write
translate
summarize
code
brainstorm
```

These are B62-owned Task Modes / presets. Canonical Reusable Skill semantics are now P01 Core-owned and include registry, versioning, installation/enablement, trusted compilation, tool/connector requirements and bounded runtime execution.

Disposition:
- taxonomy authority: #1105;
- implementation cleanup: #1226 (still relevant).

### 3. B62 ToolSpec wrapper should converge toward presentation metadata

`apps/padiem-chat/app/tools.py` currently subclasses shared Core ToolSpec for `web_search`, `web_fetch`, and `deep_research`.

Long-term B62 should own presentation metadata only, for example:

```text
canonical_tool_id
label
description
icon
visibility/order
```

Canonical side-effect, approval, auth scope, handler registration and resource limits remain Core ToolRegistry/ToolRuntime authority.

Disposition: #1226 (still relevant).

### 4. B62 Evidence wrapper should remain compatibility-only

`apps/padiem-chat/app/evidence.py` is currently a compatibility view over Core Evidence. As P01 Evidence/Verification and grounded citation projections mature, B62 should consume bounded public projections rather than retain a second evidence authority.

Disposition: #1226 (still relevant).

### 5. Grounding / Deep Research is a useful compatibility adapter, not the final orchestration authority

`apps/padiem-chat/app/grounding.py` correctly reuses Core GroundedResearchRuntime, but still composes planner/synthesizer behavior inside B62.

Long-term target:

```text
B62 user intent
 -> P01 orchestration/capability request
 -> normalized events + final result
 -> B62 product presentation
```

New recovery, agent, tool, evidence or approval semantics must be implemented in P01, not duplicated in B62.

Disposition: #1226 and #1227 (still relevant).

### 6. B62 model policy is currently in the correct direction

Current B62 ordinary chat delegates to `b14/auto`; the legacy `/poolside` alias is a compatibility no-op and does not establish Provider authority in B62. Provider-neutral chat mode contract (`chat_modes.py`) now centralizes B62 mode presentation without claiming provider routing.

Preserve:

```text
B62 = provider-neutral mode/presentation (ChatMode catalog, fail-closed executable request: only auto accepted)
B14 = actual model/provider route authority
```

Do not reintroduce B62-owned Provider/model registry or fallback semantics.

### 7. Existing B62 auth is functional but canonical identity/session belongs to Control Plane

B62 currently owns Google OAuth, signed product session cookies and product user/history continuity. Shared Control Plane now defines canonical subject and AuthSession lifecycle contracts (b5817b15).

Migration should be non-destructive:

```text
existing B62 user
 -> ProductIdentityLink
 -> CanonicalSubjectRef
 -> AuthSessionSnapshot
```

Conversation/history/project persistence remains B62-owned.

Disposition: #1228 (still relevant).

### 8. B62 admission quota remains B62-owned, but private refund coupling should be removed

`apps/padiem-chat/app/dispatch_quota.py` currently obtains compensation behavior via private store method `_refund`.

The reliability invariant is valid:

```text
provably NOT_DISPATCHED -> safe product quota refund
DISPATCHED/UNKNOWN -> conservative count remains
```

But the adapter should eventually use an explicit public reservation protocol such as `reserve / commit / release` rather than `getattr(..., "_refund")`.

Disposition: existing #830 updated with architecture review note (still relevant).

## B62 development that remains appropriate

B62 may continue substantial product work in these areas:

1. terminal-aware streaming UX and action lifecycle;
2. conversation/history/search/rename/delete UX;
3. Projects and Project Files UX;
4. attachment picker/upload/progress/retry/remove UX (bounded document attachments now merged);
5. Saved Outputs / Copy / Download / Export;
6. Light/Dark/Cinematic/Padiem Home themes;
7. mobile and accessibility hardening;
8. provider-neutral Mode presentation (now via `chat_modes.py` catalog);
9. normalized P01 progress/approval/result presentation.

## B62 work that must be reassigned

Do not implement these in B62:

```text
Agent execution loop
Reusable Skill execution semantics
Tool Runtime
Memory/RAG ranking or durable-write authority
Evidence verification authority
Provider/model registry
Provider credentials
Provider fallback/retry
canonical entitlement
canonical usage/credit ledger
cross-product AI service API
```

Route them to P01 Core/Engine, B14, or Shared Control Plane as appropriate.

## Recommended implementation order (updated post-#1254)

```text
1. DONE — #1068 / #1254 Core multimodal facade; B62 now consumes MultimodalExecutionRuntime (was: remove B62 direct B14 image assembly)
2. #1226  Thin B62 compatibility layer: TaskMode / ToolPresentation / Evidence adapters (still relevant)
3. #1227  Consume normalized P01 lifecycle + approval/resume events in B62 UI (still relevant)
4. #1228  Bridge B62 auth/session to Shared Control Plane canonical identity (still relevant)
5. #830   Replace private quota refund coupling with explicit reservation protocol when touched (still relevant)
6. Continue B62 product UX polish independently (including bounded document UX and provider-neutral mode polish)
```

## Governing issues (updated)

- #713 — B62 product authority
- #1098 — P01 Padiem AI Platform roadmap
- #1100 — B62 Phase 2
- #1101 — Padiem AI Core Phase 2
- #1102 — B14 Phase 5
- #1103 — Shared Control Plane Phase 1
- #1105 — capability taxonomy
- #1224 — B62 product boundary guard
- #1068 — multimodal Core facade — **DONE via #1254**
- #1254 — Core multimodal execution facade — **MERGED (af28f6ea)**
- #1252 — B62 bounded document attachments — **MERGED**
- #1253 — XLSX OOXML DTD guard — **MERGED**
- #1256 — P01 cumulative stack — **MERGED (re-merged onto b5817b15)**
- #1259 — Core bounded retrieval trust seam — **MERGED**
- d59804dc — B62 provider-neutral chat mode contract — **MERGED**
- b5817b15 — Control Plane identity/usage-event foundation — **MERGED**
- #1226 — B62 compatibility-layer cleanup — still relevant
- #1227 — normalized orchestration/approval UI consumption — still relevant
- #1228 — Control Plane identity/session bridge — still relevant
- #830 — B62 pre-dispatch quota compensation reliability — still relevant

## Final architecture

```text
User
  |
  v
B62 Padiem Chat
  UX / Conversations / Projects / Files / Saved Outputs
  |
  v
P01 Core / Engine
  Context / Memory / Agent / Skill / Tool / Evidence / Recovery / Approval
  Retrieval (bounded trust seam) / Multimodal (facade)
  |
  v
B14 Router
  Model / Provider / Credentials / Routing / Fallback / Execution

Shared Control Plane
  Identity / Entitlement / Usage / Credit / Subscription / Audit
  (now with IdentityLinkState / UsageEvent foundations)
```

The desired long-term product rule is:

> Make B62 a better product by making P01 smarter and by improving how B62 presents and persists product experience — not by duplicating shared AI infrastructure inside Padiem Chat.
