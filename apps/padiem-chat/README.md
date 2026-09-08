# B62 · Padiem Chat

Padiem Chat is Padiem's Korean-first general AI front door and shared product shell for first-party conversational/workspace experiences, including the current first-class Claw workspace surface.

```text
BUSINESS_ID = B62
PRODUCT = Padiem Chat
CANONICAL_SOURCE = apps/padiem-chat/**
```

Cross-layer authority: `../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`

## Product boundary

B62 owns:

- general chat UX and conversation lifecycle;
- conversation/history product persistence;
- Projects and project-owned context/files;
- attachment selection/presentation and product validation;
- Saved Outputs / copy / download product UX;
- Chat/Claw shell navigation and workspace presentation;
- product tier/mode presentation;
- browser/mobile/accessibility/theme/locale behavior;
- product-specific admission/abuse controls;
- safe presentation of shared Agent/Tool/Connector/Memory/approval events after those shared contracts are available.

B62 does **not** own:

- reusable Agent/Tool/Connector/Skill/Memory/RAG/Evidence semantics — IP-CORE;
- cross-runtime AI service transport/identity — IP-ENGINE;
- model/provider catalog, routing, inference credentials or external model execution — B14;
- canonical cross-product identity/tenant/entitlement/usage/billing truth — IP-CONTROL;
- B54 Claw business-workflow semantics merely because Claw appears in the shared shell.

## Canonical execution topology

Cross-runtime default:

```text
Browser
  -> Padiem Chat product API
  -> B62 Product Adapter
  -> IP-ENGINE · Padiem AI Engine
  -> IP-CORE · Padiem AI Core
  -> B14 · General AI Router Platform
  -> Provider / Model
```

Current B62 source also contains accepted **same-runtime Core composition** for ordinary product execution paths:

```text
B62 server
  -> IP-CORE
  -> B14
```

That is an explicit composition seam, not a second architecture. Cross-runtime orchestration/shared-service paths use IP-ENGINE. B62 must never become the shared Engine or Router authority.

## Current Padiem Routing Profile v1

The older README state that described LOW/MEDIUM/HIGH as unassigned is superseded.

User-visible product tiers are:

```text
Padiem Plus
Padiem Pro
Padiem Max
```

Current shared declaration:

```text
Plus -> provider_id=kilo
        model_id=kilo/poolside-laguna-s-2.1-free

Pro  -> provider_id=kilo
        model_id=kilo/nvidia-nemotron-3-ultra-550b-a55b-free

Max  -> HOLD / non-executable
```

Source of product declaration:

`packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`

B14 remains final executability/dispatch authority. A product declaration does not force B14 to execute a retired, unregistered, unavailable or credential-incompatible route.

Current Padiem v1 policy:

```text
PADIEM_PROFILE_V1_AUTO_ROUTING = NO
PADIEM_USER_VISIBLE_AUTO = NO
PADIEM_SILENT_FALLBACK = NO
```

Compatibility names such as LOW/MEDIUM/HIGH or historical method identifiers such as `stream_text_auto` may remain internally while migration is completed. They are **not** user-visible routing authority and do not mean that current Padiem v1 uses B14's generic autorouter.

B14's generic future Auto Router remains a valid platform capability; a future Padiem profile may explicitly opt into it after product authorization.

## Chat and Claw in the shared shell

```text
Padiem Chat shell
├─ Chat  -> B62 conversation workspace
└─ Claw  -> B54 business-work workspace surface
```

The shell relationship does not merge product ownership.

- B62 owns shell/navigation/presentation.
- B54 owns Claw task/business-workflow semantics.
- IP-CORE owns generic Agent/Tool/Skill/Connector/Memory semantics.
- IP-ENGINE owns cross-runtime projection.
- B14 owns model/provider execution.
- IP-CONTROL owns shared account/control truth.

A disabled/unavailable Claw action must not be promoted merely because UI exists.

## Connector boundary

Connector entrypoints/status may be visible in the Chat/Claw shell, but generic connector runtime is shared platform capability.

```text
B62/B54 connector UX
  -> Product Adapter
  -> IP-ENGINE when cross-runtime
  -> IP-CORE Tool/Connector/Approval semantics
  -> trusted connector binding
```

B62 must not store raw provider/connector credentials in browser state or implement a second generic connector runtime.

## Attachments and files

B62 owns the product UX and bounded product validation/extraction seams for composer attachments and Project files.

Generic model-execution semantics remain Core/B14-owned. An attachment appearing in the UI does not prove that an image/vision/model route is available. Capability/model support must fail closed when the shared runtime cannot prove it.

Persistent Project files and request-scoped composer attachments remain separate product capabilities; support in one does not silently imply support in the other.

## Auth, history, Projects and Saved Outputs

Product-local conversations/Projects/files/outputs remain B62 product state, while canonical cross-product account/subject/entitlement authority belongs to IP-CONTROL where integrated.

Browser-supplied identifiers never bypass server-side ownership checks.

Saved Outputs are user-selected library state and are not automatically future model memory. Generic Memory/RAG semantics remain Core-owned.

## Orchestration / approval boundary

The browser may render progress, approval-required, resume/cancel and result states. UI intent is not approval authority.

```text
Browser intent/presentation
  -> B62 server bridge
  -> IP-ENGINE
  -> IP-CORE orchestration/approval semantics
  -> B14 when model execution is required
```

Canonical subject/entitlement/audit projections come from IP-CONTROL where required.

The browser does not mint canonical identity, approval evidence, tool authority, connector grants, provider selection or model credentials.

## Runtime modes and Production truth

B62 supports deterministic/mock and B14-backed source paths according to current source/configuration. Source code can contain a capability while a particular deployment leaves the required binding/configuration unavailable.

Use this distinction:

```text
SOURCE_PRESENT
SERVER_READY
BINDING_CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Examples:

- source for Projects does not prove D1 is bound;
- connector cards do not prove OAuth is live;
- a B14-backed route in source does not prove current Production binding/transport health;
- a deployed UI does not prove a model request succeeds.

Production claims require exact deployment/version/readback and bounded live QA evidence.

## Security invariants

- no browser-supplied provider endpoint or provider credential;
- no raw provider/connector secret in product state/logs/docs;
- no product-local provider registry/fallback policy;
- no hidden `Auto`/silent fallback for Padiem Profile v1;
- no product-local generic Agent/Tool/Memory authority;
- incomplete/failed output must not masquerade as completed output;
- product capability visibility is presentation only, not execution authority.

## Tests

Run the current B62 test suite and repository CI appropriate to the changed slice. Deterministic/mock tests do not prove live Provider/connector/Production readiness.

Documentation changes authorize no Production deployment, binding, secret, database or provider mutation.