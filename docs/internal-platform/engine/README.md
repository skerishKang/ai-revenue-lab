# IP-ENGINE — Padiem AI Engine

```text
INTERNAL_PLATFORM_ID = IP-ENGINE
CANONICAL_NAME = Padiem AI Engine
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = apps/padiem-ai-engine/
WORKER = padiem-ai-engine
BUSINESS_NUMBER = NONE
```

## Role

Cross-runtime AI service boundary around Padiem AI Core.

IP-ENGINE owns internal execution transport, Service Binding hosting, trusted first-party caller identity/authentication, and the runtime projection required for independent products to consume shared Core capabilities without owning Provider infrastructure.

## Boundary

IP-ENGINE does not own:

- product/domain semantics;
- generic Core AI semantics that already belong to IP-CORE;
- Provider/model routing or credentials;
- browser-visible secrets.

## Current work

```text
#1698
[IP-ENGINE] multi-caller service identity registry
```

This platform prerequisite preserves the existing B61 StoryMemory identity while allowing LoveBud and future products to use independent caller identities and credentials.

## Start here

- Source: `apps/padiem-ai-engine/`
- Worker entry: `apps/padiem-ai-engine/worker.py`
- Deployment config: `apps/padiem-ai-engine/wrangler.toml`
- Identity boundary: `apps/padiem-ai-engine/app/identity_enforcement.py`
- Platform registry: `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- Adoption playbook: `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`

Canonical Issue prefix for new work: `[IP-ENGINE]`.

Refs #1707 #1698.
