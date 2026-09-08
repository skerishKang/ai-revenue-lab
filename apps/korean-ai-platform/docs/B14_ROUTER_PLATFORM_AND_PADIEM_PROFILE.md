# B14 Router Platform & Padiem Routing Profile

Status: **CURRENT CANONICAL PRODUCT / ROUTING AUTHORITY**  
Business: **B14 · Korean AI Platform**  
Current first profile: **Padiem Routing Profile v1**

## 1. Canonical B14 identity

Business 14 is a **general AI Router Platform**.

Its long-term purpose is to give Padiem products and later external/customer profiles a controlled execution layer across multiple AI providers and models.

```text
B14
= provider/model registry
+ provider adapters
+ executable-route validation
+ credential-reference binding
+ manual route execution
+ generic route selection/optimization when activated
+ bounded retry/fallback policy
+ normalized response/error/evidence
+ route/usage/cost observability
+ product/customer-specific routing profiles
```

B14 is not merely a thin gateway for the current Padiem models. The current profile is the first concrete customer/product configuration on top of the broader Router Platform.

## 2. Current Padiem request

Padiem has already selected the target routes for the current MVP.

```text
Padiem Plus
  provider = kilo
  model = kilo/poolside-laguna-s-2.1-free

Padiem Pro
  provider = kilo
  model = kilo/nvidia-nemotron-3-ultra-550b-a55b-free

Padiem Max
  model = padiem-profile/max-hold
  executable = NO
```

Current success criteria are therefore:

1. the exact requested route is declared consistently;
2. B14 confirms it is registered and executable;
3. the correct provider/model is actually called;
4. Chat/Claw can use the route reliably;
5. provider/runtime failures are normalized truthfully;
6. retired/unregistered/unsupported routes fail closed;
7. no secret value is exposed to a product/browser contract.

## 3. Auto-routing rule

The following two statements are both authoritative:

```text
PADIEM_PROFILE_V1_AUTO_ROUTING = NO
B14_GENERIC_AUTOROUTER = VALID_FUTURE_CAPABILITY
```

They are not contradictory.

Padiem v1 currently requests explicit routes, so user-visible Auto, omitted-model auto selection, and silent fallback are out of scope for that profile.

B14 itself may later support automatic provider/model choice, cost-aware routing, latency-aware routing, capability-aware routing, availability-aware routing, and bounded multi-provider fallback as generic Router Platform features.

A later Padiem profile may opt into those capabilities only through an explicit, versioned policy change.

## 4. Source-of-truth hierarchy

Current architecture:

```text
Product/customer intent
  -> Padiem Routing Profile declaration
  -> packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
  -> B14 current catalog / retired-route / capability / credential readiness checks
  -> exact provider/model dispatch
  -> normalized execution result
```

Authority is deliberately split:

### Shared product/profile declaration owns

- Padiem tier label;
- intended provider/model identity;
- executable vs HOLD state;
- policy/profile version metadata suitable for product consumers.

### B14 owns

- whether a provider/model route actually exists;
- whether it is active/retired/disabled;
- provider adapter and origin/protocol;
- credential binding requirements;
- execution-time provider behavior;
- route-specific normalized errors/evidence;
- future generic router policies.

Therefore:

```text
DECLARED_ROUTE != EXECUTABLE_ROUTE automatically
CREDENTIAL_AVAILABLE != ROUTE_SELECTED
ROUTE_SELECTED != SILENT_FALLBACK_AUTHORIZED
```

## 5. Padiem consumer rules

Padiem Chat and Padiem Claw are consumers, not route authorities.

For Padiem Profile v1:

- user-facing plan labels are `Padiem Plus`, `Padiem Pro`, `Padiem Max`;
- user-visible `Auto` is not part of the profile;
- Plus/Pro use explicit routes from the shared declaration;
- Max remains HOLD until separately evidenced/approved;
- product code must not substitute a different route because the chosen route failed;
- product code must not synthesize `b14/auto` because a model field was omitted;
- raw provider keys never enter browser/product route state.

## 6. Retired routes

Retired historical model IDs are not executable merely because they appear in old issues, docs, fixtures, or decision records.

Current examples that must remain non-executable include previously retired MiniMax M3 and Tencent HY3 free lanes.

Requirements:

```text
RETIRED_ROUTE_IN_EXECUTABLE_CATALOG = NO
RETIRED_ROUTE_IN_PADIEM_EXECUTABLE_PROFILE = NO
HISTORICAL_DOC_REFERENCE_GRANTS_AUTHORITY = NO
```

## 7. Generic B14 roadmap

The following remain valid B14 platform capabilities:

### Provider/model portfolio

- Kilo/KiloCode gateway routes;
- direct provider API adapters;
- OpenAI-compatible endpoints;
- domestic/Korean providers;
- local/self-hosted inference where justified;
- additional providers after legal/security/evidence review.

No one provider family is a permanent B14-wide architectural default.

### Router policies

- explicit/manual route;
- capability-aware route selection;
- cost-aware route selection;
- latency-aware route selection;
- availability-aware route selection;
- customer/profile preference policies;
- bounded fallback/retry;
- optional multi-provider strategy;
- explicit generic autorouter contracts.

### Credentials

- platform-managed credential references;
- owner-managed credentials;
- user/customer BYOK where supported;
- rotation/revocation/readiness state;
- secret-free route declarations.

Credential policy must not become hidden route-selection authority.

### Administration and evidence

- route/catalog inspection;
- readiness state;
- policy/profile versioning;
- synthetic route smoke;
- route evidence and upstream identity;
- usage/cost/latency observation;
- auditable mapping changes and rollback anchors.

## 8. Historical-document rule

The Phase 0/1/2/3 documents under this folder record valid historical development stages. They remain useful for product history, security decisions, and implementation provenance.

They are not current model/catalog authority.

If a historical document conflicts with current source or this charter:

```text
CURRENT SOURCE + THIS CHARTER > HISTORICAL PHASE DOCUMENT
```

Do not rewrite history solely to make old experiments look current. Instead label them as historical and keep current authority centralized here and in the top-level B14 README.

## 9. Production rule

Source acceptance and Production activation are separate.

A Production deployment must:

- fresh-read current `main`;
- target the exact accepted main SHA;
- use the repository-owned B14 deployment gate;
- preserve secret/binding boundaries;
- perform post-deploy version/readback;
- run bounded synthetic first-party health/route smoke;
- retain a rollback anchor.

No issue/document/PR merge alone proves deployment.

## 10. Current issue ownership map

```text
#2085 = B14/Padiem current product objective
#2099 = Padiem profile source of truth (completed)
#2100 = Chat/Claw shared Padiem profile consumption
#2101 = remove implicit b14/auto defaults from Padiem-facing contracts
#2102 = Padiem Max evidence/selection
#2103 = generic B14 BYOK/credential policy + profile boundary
#2104 = Padiem Pro Nemotron evidence backfill
#2107 = future Padiem provider/model admin console
#1955 = exact-SHA B14 Production deploy gate
```

Generic B14 autorouting/optimization work should be tracked separately from Padiem v1 explicit-route delivery so neither blocks nor erases the other.

## 11. Canonical decision summary

> **B14 is a general AI Router Platform. Padiem is its first product/customer-specific routing profile. Padiem Profile v1 deliberately uses owner-selected explicit routes, while B14's automatic routing and optimization capabilities remain valid long-term platform work.**
