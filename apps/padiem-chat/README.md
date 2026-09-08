# Padiem Chat · Business 62

```text
DOC_STATUS = CURRENT_PRODUCT
BUSINESS_ID = B62
CANONICAL_SOURCE = apps/padiem-chat/**
LAST_VERIFIED = 2026-09-08
```

Padiem Chat is Padiem's Korean-first, general-user AI front door.

Canonical platform references:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`

## Product boundary

```text
Browser / API
 -> Padiem Chat product boundary
 -> Padiem AI Core shared execution semantics
 -> Padiem AI Engine when a cross-runtime service boundary is required
 -> Business 14 Korean AI Platform
 -> selected Provider / Model
```

Padiem Chat owns:

- chat/composer/sidebar UX;
- conversation continuity/history;
- Projects and product-local project context;
- bounded ephemeral attachments and product presentation;
- Saved Outputs/copy/download UX;
- TaskMode/profile presentation and product-local context adapter;
- Korean user-facing errors and capability presentation.

Padiem Chat does **not** own:

- generic Tool/Skill/Agent/Memory/Evidence semantics;
- Provider/model catalog or inference credentials;
- a second generic model router;
- Control Plane canonical identity/entitlement truth;
- Padiem AI Engine transport semantics.

B62 `TaskMode` values are product presets, not reusable Core Skills.

## Current Padiem model tiers

The old B62 README state that LOW/MEDIUM/HIGH were all unassigned is no longer current.

B62 now consumes the neutral shared declaration from:

```text
packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py
```

Current product mapping on the verified source revision:

```text
Padiem Plus = kilo/poolside-laguna-s-2.1-free
Padiem Pro  = kilo/nvidia-nemotron-3-ultra-550b-a55b-free
Padiem Max  = HOLD / padiem-profile/max-hold

DEFAULT GENERAL CHAT = Padiem Pro
```

Ownership remains separated:

```text
Control Plane shared contract = DECLARES Plus/Pro/Max product routes
B62 model_policy.py            = CONSUMES product declaration + product aliases/capability gate
B14 catalog                    = FINAL EXECUTABILITY AUTHORITY
B14 provider adapters          = ACTUAL MODEL EXECUTION
```

Current product policy:

```text
AUTO_PROVIDER_SELECTION = NO
AUTO_MODEL_SELECTION = NO
USER_VISIBLE_AUTO_LABEL = NO
SILENT_FALLBACK = NO
```

Historical `b14/auto` compatibility identifiers must not silently become the ordinary Padiem product route. Retired MiniMax M3 and Tencent HY3 lanes must not re-enter an executable product tier through stale documentation or fallback.

For exact current IDs and hold/retirement state, current `product_tier_routes.py`, B62 `model_policy.py`, and B14 catalog/source are stronger authority than an old issue or phase document.

## Runtime modes

### Mock

```bash
PADIEM_CHAT_RUNTIME_MODE=mock \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

Mock mode is deterministic and makes zero upstream model calls.

### B14-backed execution

```bash
PADIEM_CHAT_RUNTIME_MODE=b14 \
PADIEM_CHAT_B14_BASE_URL=https://<approved-b14-host> \
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

The browser does not supply Provider keys or arbitrary upstream origins. Ordinary text requests are adapted to product-neutral Core execution inputs; B14 performs the actual Provider/model execution beneath the shared boundary.

`b14` source mode is not by itself proof that a deployed Production Worker has all required service bindings, abuse/quota gates, credentials or Provider readiness.

## Attachments

Composer attachments are request-scoped product inputs and are distinct from persistent Project files.

Current bounded product contract includes:

```text
Images:         JPEG / PNG / WebP, one attachment, up to 4 MiB
Text docs:      TXT / Markdown / CSV / JSON, one attachment,
                bounded UTF-8 text
Binary docs:    PDF / DOCX / PPTX / XLSX, one attachment,
                bounded raw payload parsed server-side
```

B62 owns attachment UX, extraction/product validation and user-facing errors. Core owns shared execution semantics. B14 owns actual inference execution.

Attachment/document bytes are untrusted reference data. They must not select a Provider/model, widen authorization, or become hidden durable memory merely because they were supplied to one request.

Persistent Project files are a separate product storage capability with their own bounded validation/ownership rules.

## Streaming and completed transport

Transport choice is explicit:

```text
ordinary attachment-free chat
 -> streaming product path

attachment-bearing request
 -> completed attachment path unless a separately accepted streaming contract exists

orchestration-capable request
 -> product orchestration bridge only when its readiness/bindings are actually available
```

The visual message lifecycle does not redefine the underlying execution transport.

## Orchestration / approval boundary

When B62 presents orchestration or approval UI, that UI is a projection surface rather than approval authority.

```text
Browser
 -> B62 presentation + user intent
 -> B62 trusted server bridge
 -> IP-ENGINE
 -> IP-CORE orchestration/approval semantics
 -> Control Plane authority where required
 -> B14 execution
```

The browser must not mint canonical subject identity, approval evidence, Provider selection or Tool execution authority.

## Auth, history, Projects and Saved Outputs

Authentication and persistence-dependent features are active only when the deployed runtime has the required server-side configuration/bindings.

When configured, the product may expose owner-scoped:

- recent conversations;
- Projects and project instructions;
- bounded project files;
- Saved Outputs;
- signed server-owned sessions.

Saved Outputs are user-selected library records. They are not automatically injected into later chats or treated as hidden model memory.

Browser-supplied product identifiers never bypass server-side ownership checks.

## Theme and locale

Theme and locale are browser presentation state, not AI routing authority.

Current supported URL-level presentation includes Korean/English locale and the product's accepted theme variants. Presentation preferences must not alter Provider/model execution authority, product identity, or shared security semantics.

## Cloudflare Worker boundary

`worker.py` is the Cloudflare Worker composition entrypoint. Worker bindings/configuration are server-owned. Source can contain code for Projects, Saved Outputs, orchestration, connectors or other capabilities while a specific deployment still reports those capabilities unavailable.

```text
SOURCE_PRESENT
!= SERVER_BINDING_READY
!= PROVIDER_READY
!= PRODUCTION_ACTIVE
```

No fake database/provider readiness should be inferred from source presence.

## Source readiness and Production activation

Public readiness/status fields and browser control visibility are presentation/projection evidence only.

A capability is Production-active only when the exact deployed revision has the required runtime mode, trusted bindings/configuration, downstream readiness and post-deploy acceptance evidence.

Provider/model route source merge and Production deployment are separate events.

## Security invariants

- raw Provider secrets stay server-side;
- browser/user content cannot select arbitrary Provider origins;
- retired/unknown/hold routes fail closed;
- user-visible Auto and silent fallback are disabled for the current Padiem profile;
- project/file/output ownership is enforced server-side;
- untrusted attachments/context do not become instruction authority;
- product UI does not reimplement Core/Engine/Control Plane authority.

## Tests

From `apps/padiem-chat/`, run the current relevant product test suite for the changed slice. Deterministic/mock transports prove product behavior without proving live Provider availability.

For shared tier-policy changes, also validate the Control Plane declaration and relevant B14 parity/executability guards.
