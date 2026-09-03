# Padiem Sidecar Adoption and Reuse Matrix

## Purpose

Use existing Padiem products as evidence for reusable Sidecar capabilities without moving their domain semantics into the shared runtime.

## Classification vocabulary

```text
B53_PRODUCT
IP_SIDECAR
IP_ENGINE
IP_CORE
B14
CONTROL_PLANE
PRODUCT_ADAPTER_ONLY
DO_NOT_SHARE
```

## B30 / 400 AI Finder

| Capability | Classification | Direction |
|---|---|---|
| right-side AI conversation surface | IP_SIDECAR | generalize panel shell and streaming UX |
| target-site/clone layout/content fidelity | PRODUCT_ADAPTER_ONLY | remains B30/Site platform concern |
| current page/site navigation context | IP_SIDECAR + PRODUCT_ADAPTER_ONLY | generic host bridge + B30 semantics |
| knowledge/evidence retrieval | IP_CORE | reuse shared Evidence/Web/Research when integrated |
| bounded Browser Use/action navigation | IP_CORE / PRODUCT_ADAPTER_ONLY | generic tool semantics + B30 action mapping |
| model/provider execution | B14 | never copy B30 provider path into Sidecar |

## B61 / StoryMemory

| Capability | Classification | Direction |
|---|---|---|
| embedded contextual AI panel | IP_SIDECAR | reusable presentation/runtime |
| streaming answer lifecycle | IP_SIDECAR / IP_ENGINE | generic presentation + transport |
| reading position/spoiler boundary | PRODUCT_ADAPTER_ONLY | B61 authority |
| annotations/book locators | PRODUCT_ADAPTER_ONLY | B61 domain model |
| retrieval/evidence/memory semantics | IP_CORE | shared runtime authority |
| service identity/execute transport | IP_ENGINE | shared execution boundary |
| model/provider routing | B14 | shared routing authority |

## B23 / LoveBud

| Capability | Classification | Direction |
|---|---|---|
| Scout panel/suggestion surface | IP_SIDECAR candidate | extract only generic shell/primitives |
| artist/fandom/LoveTree intent | PRODUCT_ADAPTER_ONLY | LoveBud authority |
| current URL/page/excerpt bridge | IP_SIDECAR + PRODUCT_ADAPTER_ONLY | generic bridge + LoveBud normalization |
| web/research/grounding | IP_CORE | shared Core capability |
| Engine transport | IP_ENGINE | already moving to shared boundary |
| Memory draft/save semantics | PRODUCT_ADAPTER_ONLY + IP_CORE | LoveBud owns save meaning; Core owns generic Memory semantics |
| provider fallback/routing | B14 | never move to Sidecar |

## B62 / Padiem Chat

| Capability | Classification | Direction |
|---|---|---|
| composer/message/streaming presentation patterns | IP_SIDECAR candidate | selectively reuse UI primitives, not B62 product state |
| standalone chat history/projects | DO_NOT_SHARE by default | B62 product feature unless generic primitive proven |
| shared AI execution | IP_ENGINE / IP_CORE / B14 | Sidecar consumes same platform, never B62 backend |
| product model/mode presentation | B53_PRODUCT candidate | Sidecar may expose provider-neutral modes if policy-backed |

## B54 / Padiem Claw

| Capability | Classification | Direction |
|---|---|---|
| public-safe run/progress/approval rendering | IP_SIDECAR candidate | generic event/UI primitive after shared contract |
| task/run/sandbox/repository semantics | PRODUCT_ADAPTER_ONLY / DO_NOT_SHARE | remain Claw authority |
| generic Agent/Tool/approval semantics | IP_CORE | shared platform |
| model/provider routing | B14 | shared authority |

## Reuse rules

1. Do not move working product code merely to satisfy architectural aesthetics.
2. Extract only after a generic contract can be named and tested independently.
3. Keep product-specific data models and user promises in adapters/products.
4. Generic browser/UI/runtime primitives go to IP-SIDECAR after #1707/#1713 lands.
5. AI semantics go to Core; transport to Engine; provider/model to B14; identity/billing truth to Control Plane.
6. First migration target should be the smallest low-risk shared primitive, not a wholesale rewrite.

## Candidate extraction order

```text
1. panel shell + open/close/responsive/accessibility
2. streaming lifecycle + public-safe error/retry states
3. context bridge contract
4. evidence/citation presentation
5. file/image input primitives
6. approval/action confirmation primitives
7. adapter/bootstrap/version diagnostics
```

## Standing review field

Future relevant PRs should include:

```text
SIDECAR_REUSE_CHECK = PASS
GENERIC_CAPABILITY_DISCOVERED = YES/NO
GENERIC_OWNER = <classification>
PRODUCT_SPECIFIC_ADAPTER_ONLY = YES/NO
```

Refs #1722 #1723 #1224