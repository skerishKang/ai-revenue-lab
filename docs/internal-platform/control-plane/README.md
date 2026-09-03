# IP-CONTROL — Padiem Control Plane

```text
INTERNAL_PLATFORM_ID = IP-CONTROL
CANONICAL_NAME = Padiem Control Plane
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = packages/padiem-control-plane/
BUSINESS_NUMBER = NONE
```

## Role

Shared platform control-plane and policy contracts.

Use IP-CONTROL when reusable platform governance/control state should be shared across products and does not belong to one Business's local authorization or records.

## Boundary

IP-CONTROL does not automatically own:

- product membership/role authorization;
- product records or persistence;
- UI state;
- Core runtime semantics;
- Engine Service Binding identity;
- B14 provider/model credentials or routing.

## Start here

- Source: `packages/padiem-control-plane/`
- Platform registry: `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- Adoption playbook: `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`

Canonical Issue prefix for new work: `[IP-CONTROL]`.

Refs #1707.
