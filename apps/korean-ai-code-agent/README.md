# B54 · Padiem Claw

Padiem Claw is Padiem's agent/business-work product. The canonical source path remains `apps/korean-ai-code-agent/**`; the package/CLI lineage `kagent` is preserved.

```text
BUSINESS_ID = B54
PRODUCT_NAME = Padiem Claw
PRODUCT_FAMILY = Padiem Agents
CANONICAL_SOURCE = apps/korean-ai-code-agent/**
PACKAGE_CLI = korean-ai-code-agent / kagent
NEW_BUSINESS_NUMBER = NO
```

Product source of truth: `docs/00_SOURCE_OF_TRUTH.md`  
Cross-layer authority: `../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`

## Product role

Claw owns the **business/product workflow around an agent**, not the generic AI platform underneath it.

B54 owns product-specific concepts such as:

- task/run/repository/revision identity;
- product run projection and user-visible lifecycle;
- local/cloud execution-target intent and sandbox product request boundary;
- product-specific file/document/business workflow semantics;
- bounded diff/test/review and Draft-PR/product workflow;
- manual intake, quote/order/document/product outputs;
- Claw-specific UX, approval presentation and managed/local/self-hosted product modes.

B54 does **not** own:

- generic Agent/Tool/Connector/Skill/Memory/RAG/Evidence/orchestration semantics — IP-CORE;
- cross-runtime execute/stream/orchestration service transport — IP-ENGINE;
- model/provider registry, route selection, inference credentials or external model execution — B14;
- canonical cross-product identity/tenant/entitlement/usage/billing truth — IP-CONTROL;
- Padiem Chat shell/product ownership — B62.

## Canonical architecture

For shared/cross-runtime AI execution:

```text
Padiem Chat shell / CLI / future Claw surface
        |
        v
B54 Padiem Claw
Task · Run · Repo · Sandbox · Business Workflow · UX
        |
        v
Claw Product Adapter
        |
        v
IP-ENGINE · Padiem AI Engine
        |
        v
IP-CORE · Padiem AI Core
Agent · Skill · Tool · Connector · Approval · Memory · Evidence
        |
        v
B14 · General AI Router Platform
        |
        v
Provider / Model
```

IP-CONTROL is cross-cutting canonical identity/workspace/entitlement/usage/audit authority where integrated.

A local/same-runtime path may use accepted Core library contracts directly where explicitly designed, but this does not make B54 a generic Agent runtime or provider router.

## Chat shell relationship

Padiem Chat now exposes Claw as a first-class workspace surface inside the shared shell.

```text
B62 Padiem Chat shell
├─ Chat workspace   -> B62 product semantics
└─ Claw workspace   -> B54 product semantics
```

The shared shell does not merge the two Businesses. B62 owns web shell/navigation/presentation; B54 owns Claw workflow/domain semantics.

## Connector relationship

Connector UX/business intent may be Claw-specific, but reusable connector execution semantics are shared platform capability:

```text
Claw connector intent
  -> Product Adapter
  -> IP-ENGINE when cross-runtime
  -> IP-CORE Tool/Connector/Approval semantics
  -> trusted connector binding
```

Gmail, Drive, Telegram, Discord, Slack and similar services are connectors, not model Providers. B14 remains model/provider routing authority.

Raw OAuth/API credentials never enter Claw task/model payloads or browser state. Credential lifecycle belongs to the explicitly assigned trusted control/credential authority.

## Padiem Routing Profile v1

Claw consumes the Padiem product routing declaration; it does not define a second model mapping.

Current product profile:

```text
Plus -> kilo/poolside-laguna-s-2.1-free
Pro  -> kilo/nvidia-nemotron-3-ultra-550b-a55b-free
Max  -> HOLD

PADIEM_PROFILE_V1_AUTO_ROUTING = NO
PADIEM_USER_VISIBLE_AUTO = NO
PADIEM_SILENT_FALLBACK = NO
```

The declaration source is `packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py`; B14 remains final executability/dispatch authority.

B14's generic autorouter remains a valid future platform capability. Padiem v1 simply does not request it now.

## Product run and sandbox boundary

A Claw product run may represent states such as queued/preparing/running/waiting-approval/completed/failed/cancelled, but B54's user-visible lifecycle is not a replacement for Core orchestration/approval/recovery semantics.

Critical invariant:

```text
SANDBOX_LEASE_ALLOCATED
!=
AGENT_EXECUTION_STARTED
```

A provider-neutral sandbox/resource boundary does not itself authorize model execution, Tool execution or Agent orchestration.

## Local CLI compatibility

The existing terminal workflow remains a valid B54 product surface and implementation lineage. Read-only inspection, bounded patch preview, explicit write permission, allowlisted command execution and review/diff evidence remain product safety features.

Historical deterministic B14 preview/mock adapters are compatibility/test seams. They do not define the canonical Production architecture and do not grant B54 provider/routing authority.

## Safety invariants

```text
GENERIC_AGENT_RUNTIME_REIMPLEMENTED_IN_B54 = NO
GENERIC_CONNECTOR_RUNTIME_REIMPLEMENTED_IN_B54 = NO
B14_ROUTING_REIMPLEMENTED_IN_B54 = NO
RAW_PROVIDER_OR_CONNECTOR_SECRET_IN_TASK = NO
SANDBOX_LEASE_IS_AGENT_AUTHORITY = NO
WRITE_SIDE_EFFECTS_REQUIRE_ACCEPTED_POLICY = YES
GIT_PUSH_MERGE_DEPLOY_BY_DEFAULT = NO
SOURCE_READY != PRODUCTION_ACTIVE
```

Material external writes/sends remain approval/policy gated. Unsupported capabilities fail closed rather than being represented as successful.

## Documentation

Canonical product docs live under `docs/**`. Issue-numbered architecture documents under repository `docs/architecture/**` provide specialized contracts/evidence but cannot override the shared vertical-stack ownership boundary.

Older references to `P01` remain historical program lineage for Core/Engine work. Canonical shared platform names are IP-CORE and IP-ENGINE.

## Tests and runtime truth

Run the current KAgent/Claw test suite and CI appropriate to the changed slice. Deterministic fakes and source contracts do not prove live connector, Provider, sandbox, database or Production activation.

Use explicit states:

```text
CONTRACT_DEFINED
SOURCE_PRESENT
INTEGRATED
CONFIGURED
DEPLOYED
PRODUCTION_ACTIVE
LIVE_VERIFIED
```

Documentation changes authorize none of the later states.