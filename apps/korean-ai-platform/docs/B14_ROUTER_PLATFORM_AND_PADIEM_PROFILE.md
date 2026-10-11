<!-- B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->
> **B14 역할 최신 원칙(2026-10-10):** [원제작사 모델·서빙 제공업체·변형 모델의 공식 사양 및 B14 실행 권한](../../../docs/architecture/B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md)을 우선 확인합니다. **B14는 정확히 사용자가 선택한 모델을 해당 업체의 공식 API로 실행**하며, temperature/토큰/리즈닝을 임의 지정하거나 옵션을 조용히 바꾸지 않습니다. 원본 모델의 공식 사양과 실제 API 제공업체의 계약은 별도 증빙합니다. 과거 코드·평가 수치는 이 원칙의 구현 증명이 아닙니다.
<!-- /B14_OWNER_ROLE_SOURCE_OF_TRUTH_20261010 -->

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

## 2. Current Padiem request — latest owner choice versus merged source

For current OWNER-approved/excluded model identities, customer-facing naming and source-versus-Production evidence, consult the [owner model decision ledger](../../../docs/operations/B14_OWNER_MODEL_DECISION_LEDGER_2026-10-08.md). Current exact model registration and provider/upstream identity are governed by `apps/korean-ai-platform/app/pilot/b14_models.json` and its validated adapter, **not** by historical `google_provider.py` registration helpers or this charter. Model/provider official parameter provenance follows the B14 role contract linked above.

The merged Control Plane product declaration still reports Plus/Pro/Max HOLD; this does not mean the OWNER has not selected models. Google four manual-pin B14 registrations are source-merged by PR #3788, but Product Plus activation and credential-backed Production readiness remain unproven. Do not silently activate, bill, or fall back. Historical fixed chains are not a single-primary mandate (#3554).

```text
CURRENT_MERGED_PLUS = padiem-profile/plus-hold
CURRENT_MERGED_PRO  = padiem-profile/pro-hold
CURRENT_MERGED_MAX  = padiem-profile/max-hold
OWNER_GOOGLE_SET_SELECTED = YES
CANONICAL_REGISTERED_MODELS_SOURCE = apps/korean-ai-platform/app/pilot/b14_models.json
GOOGLE_PRODUCTION_READY = PER_MODEL_LIVE_EVIDENCE_REQUIRED
```

## 3. Auto-routing rule

The following two statements are both authoritative:

```text
PADIEM_PROFILE_V1_AUTO_ROUTING = NO
B14_GENERIC_AUTOROUTER = VALID_FUTURE_CAPABILITY
```

They are not contradictory.

Padiem v1 currently requests explicit routes, so user-visible Auto, omitted-model auto selection, and silent fallback are out of scope for that profile.

The gateway's own `b14/auto` resolution (`app/pilot/routing_policy.py`, `fixed_chain_v1`) is an internal compatibility path, not a product selector. Older Poolside second-position data is HISTORICAL, not owner approval; the OWNER excluded Kilo Poolside Laguna. Padiem Chat has no `/poolside` selector (#2814), and no B66 selection rule may infer an excluded route.

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
- owner-selected Plus model choices exist but current merged source remains HOLD; this charter does not prove any executable Plus route;
- Pro and Max resolve to HOLD sentinels and fail closed before Provider dispatch;
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
OWNER LATEST MODEL CHOICE = APPROVED MODEL IDENTITY
CURRENT SOURCE / RUNTIME = REAL EXECUTION AVAILABILITY
THIS CHARTER = ARCHITECTURE ONLY
HISTORICAL PHASE DOCUMENT = PROVENANCE
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
#2104 = Padiem Pro Nemotron evidence backfill (closed; Pro has been HOLD since #2601)
#2107 = future Padiem provider/model admin console
#1955 = exact-SHA B14 Production deploy gate
```

Generic B14 autorouting/optimization work should be tracked separately from Padiem v1 explicit-route delivery so neither blocks nor erases the other.

## 11. Canonical decision summary

> **B14 is a general AI Router Platform. Padiem is its first product/customer-specific routing profile. Padiem Profile v1 deliberately uses owner-selected explicit routes, while B14's automatic routing and optimization capabilities remain valid long-term platform work.**
