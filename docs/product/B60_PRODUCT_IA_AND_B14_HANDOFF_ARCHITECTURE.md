# Business 60 · AI API — Product IA, UX Architecture, and B14 Handoff Authority

Issue: #663  
Visual-direction baseline: #652 / PR #662  
B60 source/intake authority: #654  
B14 execution authority: #371 / #377 / #387  
Status: `UX_ARCHITECTURE_REVIEW_READY`

---

## 1. Decision

The current B60 cinematic direction is accepted as the working visual baseline for the next phase.

This document does **not** declare every cinematic frame final. It declares that the next product work is no longer a visual-direction search. The priority is now:

```text
INFORMATION ARCHITECTURE
→ USER JOURNEYS
→ PROVIDER / MODEL / OFFER DETAIL UX
→ DISCOVERY-TO-EXECUTION HANDOFF
→ RESPONSIVE NAVIGATION
→ RETENTION / WATCH UX
```

The existing cinematic entry remains the frontdoor and narrative metaphor. Product UX must grow behind it without turning the opening into a generic SaaS dashboard.

---

## 2. Product definition

B60 should be treated as an **AI Access Hub**, not merely a free-API list and not an execution gateway.

Product promise:

> Find AI models and access providers, understand the real access terms and verified evidence, compare usable routes and offers, then move into an execution surface when you want to connect or try one.

The public experience may feel unified, but product/runtime authority remains explicit:

```text
B60 · AI API
DISCOVER / VERIFY / COMPARE / EXPLAIN ACCESS
                    │
                    │ explicit handoff
                    ▼
B14 · Korean AI Platform
CONNECT / EXECUTE / ROUTE / METER / OBSERVE
```

This separation is architectural, security-relevant, and product-relevant.

B60 must not silently become a second Router Core, second provider adapter layer, second BYOK vault, or second usage/billing system.

---

## 3. Primary navigation authority

Long-term primary navigation:

```text
Discover | Providers | Models | Connect | Watch
```

The navigation is object/action oriented rather than status-tab oriented.

### 3.1 Discover

Purpose: acquisition, freshness, urgency, and broad exploration.

Sub-surfaces:

```text
Discover
├─ Featured
├─ Free Now
├─ New Today
├─ Ending Soon
├─ Changes
└─ All Access
```

`Featured` may later become personalized, but personalization is not required for the current phase.

### 3.2 Providers

Purpose: understand where access is actually available.

The UI may use the familiar word `Providers`, but the data layer must distinguish several provider-like roles:

```text
DIRECT_MODEL_PROVIDER
INFERENCE_PROVIDER
GATEWAY
ROUTER
CLOUD_AI_PLATFORM
LOCAL_OR_SELF_HOSTED_ROUTE
```

Examples of concepts that must not be flattened into one semantic type:

- a model vendor exposing its own API;
- an inference platform serving third-party/open models;
- a multi-model gateway;
- a router aggregating multiple upstreams;
- a cloud AI service;
- a configured local/OpenAI-compatible route.

### 3.3 Models

Purpose: start from the model rather than the access vendor.

A model is not owned by one access path in the UX. A single model may be reachable through multiple providers/gateways/routes.

Core relationship:

```text
MODEL
  ├─ ACCESS ROUTE → Provider A
  ├─ ACCESS ROUTE → Gateway B
  └─ ACCESS ROUTE → Provider C
```

This is required for future questions such as:

- Where can I use this model?
- Which route is free?
- Which route is cheaper?
- Which route supports the capability I need?
- Which route can I actually connect to through B14?

### 3.4 Connect

Purpose: bridge discovery into execution without duplicating execution ownership.

Conceptual sub-surfaces:

```text
Connect
├─ My Providers
├─ Playground
├─ Router
├─ Usage
└─ History / Logs
```

These surfaces must consume B14 capabilities where they exist.

B60 may own the shell, selected-context handoff, explanatory copy, and deep links. B14 owns credentials, provider adapters, routing, model execution, usage, fallback, and execution evidence.

### 3.5 Watch

Purpose: retention and return visits.

```text
Watch
├─ Saved
├─ Watched Providers
├─ Watched Models
├─ Watched Offers
├─ Changes
└─ Alerts        [later]
```

Current local browser persistence is valid as a transitional implementation. Account-backed persistence requires separate auth/database authority.

---

## 4. Current UI → target IA mapping

The current post-cinematic product layer already contains useful UX primitives. They should be reorganized, not discarded.

| Current surface | Current behavior | Target IA owner | Migration decision |
|---|---|---|---|
| `NOW` | current access-signal cards | Discover → Free Now / All Access | keep content, rename/reframe |
| `EXPIRING` | verified expiry only | Discover → Ending Soon | preserve truth-first expiry rule |
| `MODELS` | flat rows of model + provider | Models | promote into real model list/detail architecture |
| `ACCESS` | grouped access methods | Provider/Model detail + filters | remove as permanent top-level nav |
| `WATCHLIST` | browser-local saved signal IDs | Watch → Saved | preserve behavior; migrate from signal-only to entity-aware saves later |
| `CHANGES` | history/snapshot differences | Discover → Changes and Watch → Changes | one data source, two entry contexts |
| `NEW TODAY` | first-seen in current snapshot | Discover → New Today | preserve |
| `ENDING SOON` | verified official expiry ≤ 7d | Discover → Ending Soon | preserve |
| search | provider/model/access text search | global discovery search | widen to entities and routes |
| signal drawer | details + official source links | Provider/Model/Offer detail precursor | evolve into addressable detail views |

Important current behavior to preserve:

- official-source verification remains visible;
- pending promotion claims do not become verified offers;
- expiry countdowns require verified official expiry evidence;
- changes are snapshot-backed rather than invented prose;
- blocked localStorage degrades gracefully rather than killing discovery.

---

## 5. Entity model authority

The minimum conceptual model is:

```text
Organization
    │
    ├──────────────┐
    ▼              ▼
AccessProvider    Model
    │              │
    └──────┬───────┘
           ▼
      AccessRoute
       │       │
       │       └────────► Offer
       │
       └────────────────► SourceEvidence

User / Browser State
    ├──────────────► SavedItem / Watch
    └──────────────► ProviderConnection   [B14 authority]
```

### 5.1 Organization

Represents the company/project/legal or product umbrella where needed.

Candidate fields:

```text
organization_id
display_name
homepage
country_or_region (only when sourced/needed)
```

### 5.2 AccessProvider

Represents an actual access surface.

Candidate fields:

```text
provider_id
organization_id
display_name
provider_type
homepage
api_docs_url
status
verification_state
verified_at
```

### 5.3 Model

Represents model identity independently of access path.

Candidate fields:

```text
model_id
organization_id
display_name
family
capabilities
context_window
modality
model_status
verification_state
verified_at
```

Unknown or unverified facts remain absent/pending rather than guessed.

### 5.4 AccessRoute

This is the central product entity.

```text
access_route_id
provider_id
model_id
access_method
endpoint_type
auth_type
route_class
region_or_processing_scope (when verified/relevant)
availability_state
runtime_handoff_state
price_summary
free_access_summary
capabilities
source_evidence_ids
verified_at
```

Critical distinction:

```text
DISCOVERY VERIFICATION != RUNTIME EXECUTABILITY
```

A route may be officially verified and discoverable while B14 has no executable adapter for it.

### 5.5 Offer

Represents time- or eligibility-dependent commercial access conditions.

```text
offer_id
access_route_id
kind                FREE_TIER | CREDIT | TRIAL | PROMOTION | DISCOUNT
headline
eligibility
benefit
starts_at
expires_at
expiry_verification
verification_state
source_evidence_ids
verified_at
```

An Offer is never an orphan marketing object.

Required chain:

```text
Offer → AccessRoute → Provider + Model(s) → SourceEvidence
```

### 5.6 SourceEvidence

Represents why the site believes a fact.

```text
source_evidence_id
source_type
official_url
observed_at
content_hash / snapshot reference when available
verification_state
supports_fields
```

### 5.7 SavedItem / Watch

UI retention entity.

```text
saved_item_id
entity_type          PROVIDER | MODEL | ACCESS_ROUTE | OFFER
entity_id
saved_at
storage_scope        BROWSER | SESSION | ACCOUNT [later]
```

### 5.8 ProviderConnection

Execution-side relationship; **B14 owned**.

B60 may display a connection state returned by B14, but does not define credential storage semantics.

---

## 6. State vocabulary

Source truth, commercial state, runtime state, and user state must not be collapsed into one badge.

### 6.1 Verification dimension

```text
VERIFIED_OFFICIAL_WEB
OFFICIAL_PRIMARY_SIGNAL
PENDING_VERIFICATION
STALE_REVIEW_REQUIRED
REJECTED
```

### 6.2 Commercial/access dimension

```text
FREE
FREE_TIER
CREDIT
TRIAL
PROMOTION
PAID
ENDING_SOON
EXPIRED
```

### 6.3 Runtime handoff dimension

```text
CONNECTABLE
CONNECTED
DISCOVERABLE_ONLY
ROUTE_UNAVAILABLE
CREDENTIAL_REQUIRED
NO_SAFE_ROUTE
```

### 6.4 User state dimension

```text
SAVED
WATCHING
CHANGED_SINCE_LAST_VISIT
```

A single card/detail view may show one state from several dimensions, but labels must communicate the dimension rather than producing a misleading universal “status”.

---

## 7. Site map

Conceptual route authority:

```text
/
└─ cinematic → Discover handoff

/discover
├─ /free
├─ /new
├─ /ending-soon
└─ /changes

/providers
└─ /providers/:provider

/models
└─ /models/:model

/compare

/connect
├─ /connect/providers
├─ /connect/playground
├─ /connect/router
└─ /connect/usage

/watch
├─ /watch/saved
└─ /watch/changes

/about/verification
```

The current runtime is a static page and may initially emulate routes with sections/state rather than a full router. The conceptual hierarchy is authoritative even if physical URLs arrive incrementally.

---

## 8. Page and screen contracts

### 8.1 Cinematic → Discover transition

The cinematic remains the emotional entry.

The transition must answer the user’s first practical question immediately after the film:

> “What can I actually access now?”

Do not land on an abstract brand slogan after the cinematic.

Landing composition target:

```text
freshness/verification context
→ high-signal discovery modules
→ search
→ provider/model pivots
```

The cinematic vocabulary already expresses:

```text
INTENT → ACCESS → MODEL → API
```

The product layer should make those concepts navigable rather than replacing them with unrelated taxonomy.

### 8.2 Discover landing

Required above-the-fold or first practical viewport priorities:

1. clear discovery heading;
2. freshness/verification date or state;
3. search;
4. `Free Now`, `New Today`, `Ending Soon`, `Changes` entry points;
5. a restrained number of high-value access cards;
6. pivots to Providers and Models.

Avoid recreating a dense admin dashboard.

### 8.3 Provider list

Each provider item should expose only enough information to choose whether to inspect it:

```text
name
provider type
verified state
free/current-access summary
number of known model routes
capability/access-method hints
change marker when relevant
```

Primary action: open Provider detail.

### 8.4 Provider detail

Required sections:

```text
Provider identity
Verification / last checked
Provider type
Current access summary
Available models / routes
Free tier and current offers
Access methods
Capability summary
Pricing/access notes
Official evidence
TRY / CONNECT action area
```

`TRY` and `CONNECT` must be route-aware.

If B14 does not support the selected route:

```text
DISCOVERABLE_ONLY
```

must be shown instead of a fake runnable CTA.

### 8.5 Model list

Each item should prioritize:

```text
model identity
capabilities
verified metadata
number of access routes
free-route availability
lowest known verified price summary when comparison is sound
```

Do not present one provider as intrinsic to the model unless that relationship is actually direct/canonical.

### 8.6 Model detail

Required sections:

```text
Model identity
Verified model facts
Capabilities
All known AccessRoutes
Provider/gateway comparison
Free/paid distinction
Offer badges attached to routes
Evidence
TRY / CONNECT per eligible route
```

This page is the foundation for future “best way to access model X” UX.

### 8.7 Offer detail / drawer

Offer-led cards can remain acquisition surfaces, but the detail view must show context in this order:

```text
Offer
→ who is eligible
→ what exactly is received
→ when it ends (only if verified)
→ applicable AccessRoute
→ Provider
→ Model(s)
→ official evidence
→ runnable/connectable state
```

### 8.8 Compare

The comparison surface should compare like entities or route alternatives, not arbitrary marketing cards.

Initial useful comparisons:

```text
AccessRoute vs AccessRoute for one Model
Provider vs Provider for a capability/use case
```

Comparison dimensions may include:

```text
verification
access method
free tier
known price
context/capabilities
runtime-connectable state
region/privacy metadata when actually sourced
```

Unknown values must remain unknown.

### 8.9 Connect

Connect is a UX façade over B14 authority.

Possible states:

```text
NOT_CONNECTED
CONNECTABLE
CONNECTED
DISCOVERABLE_ONLY
CREDENTIAL_REQUIRED
ROUTE_UNAVAILABLE
```

The surface must clearly separate:

- “we verified this provider exists”;
- “B14 can connect to this provider”;
- “you have connected a credential”;
- “this particular route is runnable now”.

### 8.10 Watch

Saved content should become entity-aware.

A user should eventually be able to watch:

```text
Provider
Model
AccessRoute
Offer
```

Change notifications or future alerts should resolve back to the changed entity and evidence, not just a generic activity row.

---

## 9. Primary UX journeys

### Journey A — free access seeker

```text
Cinematic
→ Discover / Free Now
→ offer/access card
→ route detail
→ evidence
→ TRY
→ B14 playground if executable
```

### Journey B — model-first developer

```text
Search model
→ Model detail
→ compare AccessRoutes
→ choose Provider route
→ CONNECT or TRY
→ B14
```

### Journey C — provider-first developer

```text
Providers
→ Provider detail
→ inspect free tier + models
→ select route
→ connect key
→ B14 connection flow
```

### Journey D — returning watcher

```text
Watch
→ Changed Since Last Visit
→ changed model/provider/offer
→ before/after evidence
→ re-evaluate route
→ TRY / CONNECT if useful
```

### Journey E — promotion-led acquisition

```text
Ending Soon / New Today
→ Offer
→ eligibility + evidence
→ applicable route
→ model/provider context
→ connect/try
```

---

## 10. B60 → B14 handoff contract

B60 sends context, not secrets.

Conceptual handoff payload:

```json
{
  "source": "b60",
  "intent": "try",
  "provider_id": "provider-id",
  "model_id": "model-id",
  "access_route_id": "route-id",
  "offer_id": "optional-offer-id",
  "evidence_ref": "optional-safe-reference"
}
```

Allowed `intent` baseline:

```text
try
connect
```

B14 decides:

```text
adapter availability
credential requirement
credential storage/handling
route eligibility
manual/auto routing behavior
fallback
actual upstream execution
usage
cost evidence
request logs / route evidence
```

B60 must accept bounded return states rather than infer execution capability itself.

Candidate response contract for UX integration:

```json
{
  "handoff_state": "CONNECTABLE",
  "provider_id": "provider-id",
  "model_id": "model-id",
  "selected_route_id": "b14-route-id-or-null",
  "credential_state": "REQUIRED",
  "reason_codes": []
}
```

Exact API shape belongs to the later integration issue. The UX semantics above are authoritative.

---

## 11. Ownership matrix

| Capability | B60 | B14 |
|---|---:|---:|
| provider discovery | OWNER | consumer/context |
| model discovery | OWNER | runtime catalog consumer/owner of executable registry |
| official-source evidence | OWNER | may consume |
| free tier / offer discovery | OWNER | may display context |
| expiry/eligibility verification | OWNER | no |
| source snapshots / diffs | OWNER | no |
| watch/saved discovery entities | OWNER | no |
| provider adapter | no | OWNER |
| BYOK credential handling | no | OWNER |
| provider connection state | display/consume | OWNER |
| model execution | no | OWNER |
| routing/fallback | no | OWNER |
| usage/metering | no | OWNER |
| execution logs / route evidence | display/consume | OWNER |
| billing/platform credits | no current authority | B14/future authority only |

---

## 12. Responsive navigation contract

### Desktop

Persistent primary navigation:

```text
Discover | Providers | Models | Connect | Watch
```

Search may remain prominent in Discover and later become globally accessible.

### Mobile

Initial baseline:

```text
Discover | Providers | Models | Connect
```

`Watch` can be exposed through a saved/star action or secondary menu if five permanent destinations make the bottom/navigation treatment too crowded.

Rules:

- cinematic must remain usable on 390px;
- the first practical action after cinematic must not require hunting through a menu;
- filters should not consume the entire viewport;
- drawers must become full-width sheets or dedicated detail states when required for readability;
- evidence and CTA must remain reachable by keyboard/touch;
- motion-reduced users must reach the same information-complete state.

Final mobile navigation requires rendered review rather than source-only approval.

---

## 13. UX writing hierarchy

Use concise product language.

Preferred user vocabulary:

```text
Free Now
New Today
Ending Soon
Changes
Providers
Models
Try
Connect
Saved
Verified
Official source
```

Internal concepts such as `AccessRoute` should not become unexplained user-facing jargon.

Where useful, expose it as:

```text
Access route
Available through
Use via
```

`Provider` remains acceptable as a broad navigation label even though internal provider types are more precise.

---

## 14. Search and filtering

Search must evolve from current string matching across signal fields into entity-aware discovery.

Minimum future searchable dimensions:

```text
provider name
organization
model name/family
capability
access method
free/current offer state
```

Filter candidates:

```text
Free
Officially verified
Provider type
Capability
API / Gateway / Playground / Router / Local
Connectable through B14
```

Do not expose filters for facts the source pipeline does not reliably maintain.

---

## 15. What is intentionally not being built yet

This UX architecture does not authorize:

- B60-owned provider calls;
- API key storage in B60;
- user database/auth implementation;
- account-level watch sync;
- provider resale;
- payment/billing;
- automatic publishing of crawler candidates;
- personalized ranking claims without a later ranking design;
- universal “best model” claims;
- replacement of B14 Router Core;
- wholesale redesign of the accepted cinematic visual direction.

---

## 16. Implementation sequence

### Phase UX-1 — Shell and Discover taxonomy

Goal:

```text
CURRENT FLAT TABS
→ TARGET IA SHELL
```

Tasks:

- introduce `Discover | Providers | Models | Connect | Watch` navigation treatment;
- preserve cinematic entry;
- re-home current `NOW / NEW TODAY / ENDING SOON / CHANGES` under Discover;
- keep current search and evidence behavior;
- avoid backend changes.

Gate:

```text
IA_SHELL_RENDERED
DISCOVER_TAXONOMY_MAPPED
NO_VISUAL_DIRECTION_REGRESSION
```

### Phase UX-2 — Providers

- provider index;
- provider-type semantics;
- provider detail state/page;
- current routes/models/offers/evidence;
- connectability placeholder driven by explicit data, not assumption.

Gate:

```text
PROVIDER_LIST_DETAIL_USABLE
```

### Phase UX-3 — Models and AccessRoutes

- model index;
- model detail;
- multiple AccessRoutes per model;
- free/paid/offer context attached to routes;
- provider pivot.

Gate:

```text
MODEL_ROUTE_GRAPH_USABLE
```

### Phase UX-4 — Compare

- compare route alternatives for a model;
- truth-preserving unknown states;
- no fabricated price ranking.

Gate:

```text
ROUTE_COMPARE_USABLE
```

### Phase UX-5 — B14 TRY / CONNECT handoff

- define concrete integration endpoint/deep-link contract;
- consume B14 capability state;
- show connectable vs discoverable-only;
- no credential handling in B60.

Gate:

```text
B60_B14_HANDOFF_WORKING
NO_SECRET_CROSSING_B60
```

### Phase UX-6 — Watch migration

- entity-aware saved items;
- changed-since-last-visit;
- provider/model/offer watch context;
- preserve browser-local fallback until auth phase.

Gate:

```text
ENTITY_AWARE_WATCH_USABLE
```

### Later — Account persistence and alerts

Separate architecture/security approval required.

---

## 17. Immediate implementation mapping to current files

Current runtime files are useful prototypes, not final route architecture.

```text
product-v6.js
  NOW           → Discover / Free Now + All Access
  EXPIRING      → Discover / Ending Soon
  MODELS        → seed for Models index
  ACCESS        → seed for AccessRoute facets
  signal drawer → seed for detail view

product-v7.js
  WATCHLIST     → Watch / Saved
  CHANGES       → Watch / Changes entry
  localStorage  → keep as transitional persistence

product-v8.js
  NEW TODAY     → Discover / New Today
  ENDING SOON   → Discover / Ending Soon
  snapshot diff → Discover / Changes + Watch / Changes
```

The first UI implementation should reorganize these capabilities before introducing large new datasets or backend dependencies.

---

## 18. Review checklist

Before UI implementation is considered structurally complete:

```text
[ ] cinematic still hands off cleanly into product UI
[ ] primary navigation communicates Discover / Providers / Models / Connect / Watch
[ ] current truth-first verification is preserved
[ ] Provider and Model are independently navigable concepts
[ ] AccessRoute is represented as Provider × Model access
[ ] Offers resolve to routes and evidence
[ ] B14 connectability is explicit, never guessed
[ ] Watch supports a credible migration beyond signal-only IDs
[ ] desktop and 390px journeys are rendered and reviewed
[ ] reduced-motion reaches equivalent information
[ ] no provider credential enters B60
[ ] no B14 runtime code is duplicated
```

---

## 19. Authority markers

```text
B60_VISUAL_DIRECTION_ACCEPTED_FOR_UX = YES
B60_PRODUCT_IDENTITY = AI_ACCESS_HUB
PRIMARY_IA = DISCOVER_PROVIDERS_MODELS_CONNECT_WATCH
ACCESS_ROUTE = MODEL_X_PROVIDER
OFFERS_ARE_ROUTE_BOUND = YES
SOURCE_EVIDENCE_SEPARATE_FROM_RUNTIME_STATE = YES
B60_B14_HANDOFF_REQUIRED = YES
B14_EXECUTION_AUTHORITY_PRESERVED = YES
B60_PROVIDER_CALLS = 0
B60_SECRET_STORAGE = 0
UI_UX_IMPLEMENTATION_NEXT = YES
```
