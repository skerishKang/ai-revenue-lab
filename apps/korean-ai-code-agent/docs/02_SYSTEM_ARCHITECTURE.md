# Padiem Claw System Architecture

Cross-layer authority: `../../../docs/architecture/PADIEM_AI_VERTICAL_STACK.md`

## Canonical cross-runtime path

```text
Padiem Chat shell / CLI / future Claw surface
        |
        v
B54 Padiem Claw
Task · Run · Repo · Sandbox · Diff · Test · Business Workflow · UX
        |
        v
Claw Product Adapter
        |
        v
IP-ENGINE · Padiem AI Engine
trusted execute/stream/orchestration service boundary
        |
        v
IP-CORE · Padiem AI Core
Agent · Tool · Connector · Skill · Approval · Recovery · Memory · Evidence · Orchestration
        |
        v
B14 · Korean AI Platform / General AI Router Platform
model/provider registry · credentials · routing · execution
        |
        v
Provider / Model
```

IP-CONTROL / Padiem Control Plane supplies cross-cutting canonical identity/subject, workspace/tenant, entitlement, usage/credits/billing and shared audit/security truth where integrated. It is not the sandbox scheduler or a mandatory sequential hop in every model request.

A local/same-runtime integration may use accepted IP-CORE library contracts directly where explicitly designed. The ownership matrix below does not change.

## Ownership matrix

| Layer | Owns | Must not own |
|---|---|---|
| B54 Claw | task/run/repo/sandbox product lifecycle, business workflow, document/output UX, product diff/test/review/GitHub workflow | generic Agent/Tool/Connector/Skill/Memory semantics; provider routing |
| IP-ENGINE | cross-runtime service identity, execute/stream/orchestrate transport, versioned Core projection | provider policy, product DB/domain semantics |
| IP-CORE | Agent/Tool/Connector/Skill/approval/recovery/evidence/memory/orchestration semantics | Claw product persistence, sandbox scheduler, provider registry |
| B14 | models/providers/inference credentials, route selection/policy, external model execution | Claw task/run/chat/sandbox/product state |
| B62 Chat | shared shell/navigation and Chat product UX; Claw presentation surface where integrated | Claw business semantics, generic Agent loop, provider routing |
| IP-CONTROL | canonical identity/workspace/entitlement/usage/credits/audit | diff/PR/sandbox scheduling, AI reasoning, provider execution |

B54 consumes canonical shared request/event/result contracts rather than inventing a second Agent API or connector runtime.

## Padiem routing profile

Current Padiem Routing Profile v1 uses owner-selected explicit routes:

```text
Plus -> Laguna
Pro  -> Nemotron
Max  -> HOLD
```

Claw consumes the shared declaration; B14 is final route executability/dispatch authority. The current Padiem no-Auto policy is profile-specific and does not delete B14's future generic autorouter mission.

## Connector path

```text
Claw business intent / connector UX
  -> Product Adapter
  -> IP-ENGINE when cross-runtime
  -> IP-CORE Tool/Connector/Approval semantics
  -> trusted connector adapter/binding
  -> external service
```

Raw connector credentials do not enter Claw task/model context. External writes/sends require the accepted shared approval/policy boundary.

## Extraction rule

Do not create speculative shared sandbox/agent packages or product-local generic connector/AI runtimes. Keep Claw-specific infrastructure inside B54 until reusable semantics are proven; when semantics are already reusable, consume/extend the accepted IP-CORE/IP-ENGINE layer instead.

## Status rule

Architecture ownership is not runtime readiness:

```text
SOURCE_PRESENT != CONFIGURED != DEPLOYED != PRODUCTION_ACTIVE != LIVE_VERIFIED
```

Documentation changes do not authorize Production mutation.