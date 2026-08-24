# Business 60 · AI API — As-Built Product IA, Truth, and B14 Handoff Authority

Issue: #663  
Documentation PR: #664  
As-built audit date: 2026-08-24  
Status: `AS_BUILT_AUTHORITY`

---

## 1. Authority and purpose

This document records the **implemented Business 60 product architecture as it exists on repository `main`**, rather than a future UI plan.

The original Phase 2 architecture proposed:

```text
Discover | Providers | Models | Connect | Watch
```

That structure has now been implemented through the B60 UX stack and is the current product authority.

The governing product boundary remains:

```text
B60 · AI API
DISCOVER / VERIFY / COMPARE / EXPLAIN ACCESS
                    │
                    │ exact, explicit handoff only
                    ▼
B14 · Korean AI Platform
CONNECT / EXECUTE / ROUTE / METER / OBSERVE
```

B60 must not become a second Router Core, provider-adapter layer, credential vault, billing layer, or execution runtime.

---

## 2. Current production authority

Current public B60 surface:

```text
https://ai-api-a9x.pages.dev/
```

Portfolio Console B60 `surfaceUrl` is aligned to that same apex.

Deployment/runtime authority:

```text
Cloudflare Pages project = ai-api
production branch        = production
source authority         = repository main B60 runtime tree
runtime mirror           = apps/portfolio-console/ai-api/**
reference mirror         = reference/business-60-ai-api-v1/**
```

The assigned `pages.dev` suffix is hosting detail, not product identity. A later custom domain may replace the public hostname without changing this architecture.

---

## 3. Implemented user journey

The current product journey is:

```text
Cinematic frontdoor
→ explicit CONNECT beat
→ practical access-discovery layer
→ Discover / Providers / Models / Connect / Watch
→ exact AccessRoute detail
→ Save / Compare / Provider / Model
→ execution-readiness inspection
→ B14 handoff details only when an exact mapping exists
```

The cinematic remains an experiential acquisition layer. It does not own access truth or execution semantics.

`prefers-reduced-motion` and direct route-detail entry must still reach the practical information layer without requiring the full cinematic sequence.

---

## 4. Implemented primary IA

Current primary navigation:

```text
Discover | Providers | Models | Connect | Watch
```

All five destinations are product-level navigation on desktop and mobile. `Watch` is no longer a future secondary-menu concept.

### Discover

Current discovery subviews:

```text
FREE NOW
NEW TODAY
ENDING SOON
CHANGES
ALL ACCESS
```

These are discovery states, not separate product identities.

### Providers

Provider index/detail is derived from current B60 access-signal data. It exposes known routes, model-bearing routes, free/credit paths, verification context, and official evidence without inventing provider metadata that is not sourced.

### Models

Model/catalog index/detail is independent from Provider. A model entry may expose one or more known AccessRoutes.

### Connect

Connect is an **execution-readiness boundary**, not a credential form or execution console.

It distinguishes:

```text
ROUTER MAPPED
INFO ONLY
```

No API key input exists in B60.

### Watch

Watch owns:

```text
SAVED
CHANGES
```

Saved items are entity-aware route presentations while persistence authority remains the existing route-id store.

---

## 5. Current entity model

The practical model is:

```text
Organization / Provider context
            │
            ├─────────────┐
            ▼             ▼
      AccessProvider     Model
            │             │
            └──────┬──────┘
                   ▼
              AccessRoute
               │       │
               │       └──── current offer/access condition
               │
               └──────────── SourceEvidence

Browser/session state
  └──────────────────────── Saved AccessRoute IDs

Execution state
  └──────────────────────── B14-owned route/credential/runtime authority
```

The central product entity is the **AccessRoute**.

A marketing/free-tier condition must resolve back to a route and evidence; it must not exist as an orphan promotional card.

---

## 6. Verification, commercial, runtime, and user state are separate dimensions

B60 must not collapse unrelated dimensions into one status badge.

### Verification dimension

Current data may contain states such as:

```text
VERIFIED_OFFICIAL_WEB
PARTIALLY_VERIFIED_OFFICIAL_WEB
PENDING_WEB_VERIFICATION
```

User-facing Korean copy maps internal enums into understandable labels. Internal identifiers remain stable contracts.

### Commercial/access dimension

Examples:

```text
FREE
FREE_TIER
CREDIT
TRIAL
PROMOTION
PAID
```

### Runtime dimension

Current public runtime states:

```text
ROUTER MAPPED
INFO ONLY
```

Internal mapping values may use `CONNECTABLE` / `DISCOVERABLE_ONLY`, but those values must not imply that a live target is bound.

### User state

Current browser/session state includes:

```text
SAVED
SELECTED FOR COMPARE
```

No server-side unread, alert, or notification state is claimed.

---

## 7. Route comparison authority

B60 compares **AccessRoutes**, not generic provider marketing cards.

Current compare contract:

```text
maximum selected routes = 3
minimum to open compare = 2
```

Comparison includes available route facts such as:

```text
Provider
Model/catalog item
Access methods
Free/credit condition
Price summary
Context
Verification date/state
Execution readiness
Official source
```

Unknown facts remain unknown. Provider-dependent pricing must not be flattened into one fixed route price unless the route is actually pinned to that provider.

---

## 8. Unified route-detail authority

There is one current route-detail owner.

Discovery cards, Provider/Model route rows, keyboard activation, Watch reopen, and public deep links must resolve to that same detail implementation.

Public deep-link state is based only on the public signal identifier:

```text
?route=<signal-id>#explore
```

No user ID, API key, credential, auth token, or secret may enter the URL.

The route detail presents:

```text
Access route
Current access condition
Provider / Model context
Price / context / access methods
Verification state and timestamp
Official evidence
Pending evidence separately from verified facts
Save
Compare
Provider jump
Model jump when applicable
Handoff details when exactly mapped
```

---

## 9. B60 → B14 exact handoff contract

B60 currently carries a static, reviewable execution-handoff mapping contract.

Current exact mapping count:

```text
1
```

Current mapped discovery route:

```text
B60 signal        = openrouter-free-router
B60 provider      = OpenRouter
B60 model         = openrouter/free
B14 model id      = openrouter/free
B14 route id      = openrouter:openrouter/free
credential mode   = BYOK_B14_OWNED
workspace path    = /workspace
handoff binding   = CONTRACT_ONLY
target URL        = null
```

Therefore the correct user-facing state is:

```text
ROUTER MAPPED
EXECUTION TARGET = NOT BOUND
```

This does **not** authorize a live execution button.

Other current B60 routes remain `INFO ONLY` unless an exact B14 identifier/access-path mapping is later reviewed and added.

Direct-provider discovery must never be treated as equivalent to an OpenRouter-mediated execution route merely because the underlying model family is similar.

---

## 10. B60 / B14 ownership matrix

| Capability | B60 | B14 |
|---|---:|---:|
| provider/model discovery | OWNER | may consume |
| official-source evidence | OWNER | may consume |
| free tier / promotion intelligence | OWNER | may consume |
| expiry / eligibility verification | OWNER | no |
| route comparison | OWNER | no |
| snapshot/change intelligence | OWNER | no |
| browser-local saved routes | OWNER | no |
| exact execution mapping display | OWNER of UX contract | authority source |
| provider adapter | no | OWNER |
| API-key/BYOK handling | no | OWNER |
| credential persistence | no | OWNER |
| actual model execution | no | OWNER |
| routing / fallback | no | OWNER |
| usage / metering | no | OWNER |
| execution logs / route evidence | display later if exposed | OWNER |

---

## 11. Watch authority

Persistence authority remains:

```text
localStorage key = b60.ai-api.watchlist.v1
value authority  = saved AccessRoute/signal IDs
```

When localStorage is unavailable, the current UX degrades to session-only state instead of breaking discovery.

Watch presents saved routes with Provider/Model/access-condition/verification/execution context and reuses the unified route detail and compare tray.

Change semantics are evidence-aware:

```text
FIRST_SEEN               = baseline, not a changed notification
PENDING_CLAIM_RECORDED   = pending evidence event, not verified commercial change
CHANGED                  = only a real verified before → after change
```

No fake unread count or server alert is allowed.

---

## 12. Official-source intake and publication boundary

The repository contains a read-only official-source intake and explicit human-review pipeline.

Current authority flow:

```text
OFFICIAL URL
  ↓ fetch
FETCHED evidence envelope + SHA-256
  ↓ extract observations
NEEDS_REVIEW candidate
  ↓ deterministic review packet
EXPLICIT HUMAN approve | reject
  ↓ approved candidates only
SNAPSHOT PROPOSAL + FIELD-LEVEL CHANGE LEDGER
  ↓ STOP
SEPARATE HUMAN PUBLICATION AUTHORITY REQUIRED
```

There is no allowed path from network fetch directly to published `VERIFIED_OFFICIAL_WEB` product data.

Promotion artifacts carry:

```text
publishAuthorized = false
publicationAuthority = HUMAN_EXPLICIT_PUBLISH_REQUIRED
```

The review/promotion CLI does not edit runtime `data/snapshots.js` and does not deploy the site.

---

## 13. Field-level provenance authority

Fresh verification applies only to fields supported by approved evidence.

For approved fields, `fieldVerification.<field>` records source/review evidence metadata.

Unobserved historical values may be retained for continuity under:

```text
carriedForwardFields
```

They do not inherit fresh verification.

Record-level scope is:

```text
FULL_RECORD
```

only when no claim-bearing field was carried forward; otherwise:

```text
OBSERVED_FIELDS_ONLY
PARTIALLY_VERIFIED_OFFICIAL_WEB
```

Carried-forward fields must never appear as fresh verified changes in the Change Ledger.

---

## 14. Snapshot and Change Ledger authority

B60 maintains normalized snapshot data and adjacent-snapshot comparison for current access truth.

Important event semantics:

```text
NEW
REMOVED
PRICE_CHANGED
FREE_TIER_CHANGED
ACCESS_CHANGED
EXPIRES_AT_CHANGED
MODEL_CHANGED
VERIFICATION_CHANGED
```

`ENDING SOON` requires an actual expiry plus verified official expiry evidence. Pending claims do not generate countdowns.

A re-verified unchanged field is not a commercial change.

A verified field delta is distinct from a carried-forward or pending claim.

---

## 15. Korean-first presentation layer

The current public document declares:

```html
<html lang="ko">
```

A dedicated Korean presentation layer maps visible navigation, buttons, evidence labels, route states, and data prose without changing machine identifiers/contracts.

Examples of user-facing semantics include:

```text
공식 확인 완료
추가 확인 필요
정보만 제공
실행 경로 연결됨
현재 이용 조건
출처 신뢰도
저장 / 저장됨
비교 / 선택됨
변경 기록
```

Provider names, model IDs, route IDs, source URLs, localStorage keys, and B14 identifiers remain unchanged.

---

## 16. Runtime/reference mirror rule

Public runtime files live under:

```text
apps/portfolio-console/ai-api/**
```

The review/reference mirror lives under:

```text
reference/business-60-ai-api-v1/**
```

When a B60 product/data file is intentionally mirrored, changes must keep the corresponding runtime/reference files aligned. QA should reject accidental semantic drift between the two trees.

Collector-only implementation remains under the reference collector directory and is not a browser runtime dependency.

---

## 17. Current implementation layers

The current static runtime is intentionally layered rather than framework-migrated:

```text
cinematic-v2..v5 + cinematic polish/autoplay
  → cinematic narrative and CONNECT interaction

product-v6
  → original access discovery primitives

product-v7
  → local save/history primitives

product-v8 + snapshot-diff-v8
  → freshness / adjacent snapshot change behavior

product-v9-ia
  → Discover / Providers / Models / Connect / Watch IA

product-v10-route-compare
  → max-3 AccessRoute compare + exact handoff presentation

product-v11-route-detail
  → unified route detail + public route deep link

product-v12-watch
  → entity-aware Saved / Changes retention surface

korean-v1
  → Korean-first visible copy/localization mapping
```

A full SPA/framework rewrite is not required merely to preserve this authority.

---

## 18. Current security and product non-authorities

The following remain **not implemented / not authorized in B60** unless a later issue explicitly changes the boundary:

```text
B60-owned provider execution
B60 API-key input or vault
user auth/account persistence
Neon/database persistence
server-side Watch sync
alerts/notifications
billing/provider resale
automatic crawler publication
scheduler-driven auto-publication
invented provider equivalence
unverified promotion countdowns
live B14 target URL guessed from infrastructure
```

A scheduler may later fetch and emit `NEEDS_REVIEW` artifacts, but it must not become publication authority.

---

## 19. Current UX acceptance baseline

The implemented UX stack has already been rendered and reviewed at desktop and true 390px mobile during its integration sequence.

The standing acceptance baseline is:

```text
PRIMARY_IA = Discover / Providers / Models / Connect / Watch
ROUTE_COMPARE_MAX = 3
ONE_ROUTE_DETAIL_OWNER = YES
PUBLIC_ROUTE_DEEP_LINK = YES
EXACT_B14_MAPPING_COUNT = 1
OTHER_CURRENT_ROUTES_INFO_ONLY = YES
ENTITY_AWARE_WATCH = YES
LOCAL_STORAGE_FAILURE_GRACEFUL = YES
PENDING_NOT_LABELED_VERIFIED_CHANGE = YES
NO_FAKE_ALERTS_OR_UNREAD = YES
NO_CREDENTIAL_STORAGE = YES
NO_PROVIDER_CALLS = YES
DESKTOP_RENDER = PASS BASELINE
MOBILE_390_RENDER = PASS BASELINE
NO_HORIZONTAL_OVERFLOW = PASS BASELINE
```

Any later change touching these contracts requires new exact-head QA appropriate to the changed surface.

---

## 20. Current next-step boundary

Phase 2 IA is no longer pending implementation. Future work should start from this as-built state.

Reasonable later work may include:

```text
more official-source coverage
reviewed snapshot publication
scheduled read-only intake artifacts
additional exact B14 mappings when runtime truth supports them
custom domain
account persistence / alerts only under separate security authority
```

These are follow-up scopes, not unfinished Phase 2 requirements.

---

## 21. Authority markers

```text
B60_PRODUCT_IDENTITY = AI_ACCESS_HUB
B60_PHASE2_IA_IMPLEMENTED = YES
PRIMARY_IA = DISCOVER_PROVIDERS_MODELS_CONNECT_WATCH
ACCESS_ROUTE_IS_CENTRAL_ENTITY = YES
ROUTE_COMPARE_IMPLEMENTED = YES
UNIFIED_ROUTE_DETAIL_IMPLEMENTED = YES
ENTITY_AWARE_WATCH_IMPLEMENTED = YES
B60_B14_EXACT_MAPPING_PRESENT = YES
B14_EXECUTION_AUTHORITY_PRESERVED = YES
B60_PROVIDER_CALLS = 0
B60_SECRET_STORAGE = 0
HUMAN_PUBLICATION_AUTHORITY_REQUIRED = YES
KOREAN_FIRST_PRESENTATION = YES
CANONICAL_PUBLIC_SURFACE = https://ai-api-a9x.pages.dev/
DOCUMENT_STATUS = AS_BUILT_AUTHORITY
```
