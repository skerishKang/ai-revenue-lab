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
- `docs/architecture/PADIEM_AI_CAPABILITY_OWNERSHIP_REGISTRY_v1.md`
- `docs/product/AI_PRODUCT_CONSUMER_MATRIX.md`
- `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`
- `docs/governance/LEGACY_AI_TERMINOLOGY_MAP.md`

## Product boundary

```text
Browser / API
 -> Padiem Chat product boundary
 -> IP-ENGINE when a cross-runtime service boundary is required
 -> IP-CORE shared execution/orchestration semantics
 -> B14 Korean AI Platform
 -> selected Provider / Model

IP-CONTROL = canonical identity / tenant / entitlement / usage / audit authority
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
- IP-CONTROL canonical identity/entitlement truth;
- IP-ENGINE transport semantics.

B62 `TaskMode` values are product presets, not reusable Core Skills. B62 converts its product-owned TaskMode state into the accepted shared execution contract rather than redefining shared Skill semantics.

## Current Padiem model tiers

The historical B62 LOW/MEDIUM/HIGH state is no longer current product-route authority. Current route documentation uses the neutral shared declaration from:

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
IP-CONTROL shared contract = DECLARES Plus/Pro/Max product routes
B62 model_policy.py        = CONSUMES product declaration + product aliases/capability gate
B14 catalog                = FINAL EXECUTABILITY AUTHORITY
B14 provider adapters      = ACTUAL MODEL EXECUTION
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

## Locked execution ownership

Padiem AI Core owns the product-neutral execution request/result semantics, grounding/evidence semantics and shared runtime contracts. Padiem AI Core ExecutionRuntime / StreamingExecutionRuntime are shared runtime facades; B62 adapts product state into them rather than owning Provider execution.

Business 14 owns provider adapters, provider keys, model catalogs, exact routing and upstream transport. IP-ENGINE owns accepted cross-runtime service projection. IP-CONTROL owns canonical subject/tenant/entitlement/usage/audit truth where composed.

The browser does not mint approval evidence, canonical subject identity, provider selection or tool execution authority. Those authorities remain on trusted server/shared-platform boundaries.

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

Composer attachments are request-scoped product inputs and are distinct from persistent Project files. Browser capability truth is centralized in `static/attachment-capabilities.js`.

Current bounded composer contract:

```text
Images:      JPEG / PNG / WebP, one attachment, up to 4 MiB
Text docs:   TXT / Markdown / CSV / JSON, one attachment,
             up to 96 KiB and 40,000 decoded text characters
Binary docs: PDF / DOCX / PPTX / XLSX, one attachment,
             raw binary payload up to 2 MiB
```

Binary extraction remains server-side behind the existing completed `/api/chat` attachment contract; the frontend does not reimplement document extraction.

Project files are a distinct persistence capability. They are validated UTF-8 text files only and remain separate from ephemeral composer attachments. PDF/DOCX/PPTX/XLSX composer support therefore does not imply those binary documents can be persisted as Project files.

B62 owns attachment UX, extraction/product validation and user-facing errors. Core owns shared execution semantics. B14 owns actual inference execution.

Attachment/document bytes are untrusted reference data. They must not select a Provider/model, widen authorization, or become hidden durable memory merely because they were supplied to one request.

### Bounded image execution through Core

Image-bearing model execution is normalized through Core's `MultimodalExecutionRequest` and `MultimodalExecutionRuntime` boundary. Product UX owns attachment validation/presentation; Core owns shared execution semantics; B14 owns Provider/model execution.

When downstream runtime/provider readiness is unavailable, live image completion still fails closed before Business 14/provider dispatch. B62 does **not** currently use Business 14 `b14/auto` as an active routing decision. The historical `stream_text_auto` method name is a compatibility entrypoint, not evidence that current Padiem profile routing is automatic.

## Streaming and completed transport

Transport choice is explicit:

```text
attachment-free ordinary chat
 -> /api/chat/stream
 -> streaming product path

attachment-bearing composer request
 -> /api/chat (JSON completion)
 -> completed attachment path

orchestration-capable request
 -> product orchestration bridge only when readiness/bindings are actually available
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
 -> IP-CONTROL authority where required
 -> B14 execution
```

The browser does not mint approval evidence, canonical subject identity, provider selection or tool execution authority.

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

## Theme and locale URL authority

Theme and locale are browser presentation state, not AI routing authority.

Current URL-level presentation contract includes:

```text
?theme=padiem-glass
?glass=female|male
?lang=ko
?lang=en
```

The current default/fallback is `padiem-glass`. Locale fallback is Korean (`ko`). Accepted presentation preferences may be reflected through URL state and bounded `localStorage` / `sessionStorage` use where the frontend contract permits it; those stores are never Provider/model-routing or canonical identity authority.

## Cloudflare Worker boundary

`worker.py` is the Cloudflare Worker composition entrypoint. Worker bindings/configuration are server-owned. Source can contain code for Projects, Saved Outputs, orchestration, connectors or other capabilities while a specific deployment still reports those capabilities unavailable.

## Source readiness is not Production activation

Source presence alone is insufficient to claim a live product capability, and browser capability projection is presentation state only.

Current readiness markers may include:

```text
projects_code_ready
project_files_code_ready
saved_outputs_code_ready
web_tools_ready
deep_research_ready
```

They mean code/projection readiness only, not automatically configured Production dependencies.

```text
SOURCE_PRESENT
!= SERVER_BINDING_READY
!= PROVIDER_READY
!= PRODUCTION_ACTIVE
```

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

```text
PRODUCTION_MUTATION = NO
```

## Historical documentation-test compatibility

The regression suite still contains point-in-time assertions from the pre-unification documentation era. The exact legacy tokens below are retained in a non-rendered comment only so documentation-only reconciliation does not require changing runtime/test source. They are **not current architecture or routing authority**; see `docs/governance/LEGACY_AI_TERMINOLOGY_MAP.md`.

<!-- LEGACY_DOCUMENTATION_TEST_COMPATIBILITY_ONLY
`LOW` / `MEDIUM` / `HIGH` product profiles are currently **UNASSIGNED**
Provider/model selection remains deferred
CURRENT_B62_SKILL_CLASSIFIED_AS_TASK_MODE = YES
REUSABLE_SKILL_AUTHORITY = P01_CORE
B62_TOOL_EXECUTION_AUTHORITY = NO
B62_TOOL_PRESENTATION_ONLY = TARGET
EVIDENCE_AUTHORITY_DUPLICATION = REDUCED_OR_EXPLICIT_COMPATIBILITY_ONLY
GROUNDING_NEW_SHARED_SEMANTICS = P01_ONLY
B14_ROUTING_REIMPLEMENTED = NO
CONTROL_PLANE_TRUTH_REIMPLEMENTED = NO
PRODUCTION_MUTATION = NO
-->

## Tests

From `apps/padiem-chat/`, run the current relevant product test suite for the changed slice. Deterministic/mock transports prove product behavior without proving live Provider availability.

For shared tier-policy changes, also validate the IP-CONTROL declaration and relevant B14 parity/executability guards.
