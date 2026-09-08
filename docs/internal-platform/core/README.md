# IP-CORE — Padiem AI Core

```text
INTERNAL_PLATFORM_ID = IP-CORE
CANONICAL_NAME = Padiem AI Core
REPOSITORY = skerishKang/ai-revenue-lab
SOURCE = packages/padiem-ai-core/
LOCAL_WORKTREE_REFERENCE = E:\padiem-ai-core
BUSINESS_NUMBER = NONE
```

## Role

Shared product-neutral AI contracts and runtimes.

Use IP-CORE when a capability is generic AI execution semantics rather than one product's domain behavior.

Current capability families include execution, Evidence/grounding, streaming, Tool, Web/research foundations, retrieval/memory, context permissions, and orchestration contracts/runtimes.

## Boundary

IP-CORE does not own:

- product-specific semantics or UI;
- product persistence policy;
- cross-runtime Cloudflare service identity;
- provider/model selection or provider credentials.

Provider/model execution authority remains B14 Korean AI Platform. Cross-runtime access is normally mediated by IP-ENGINE.

## Start here

- Source: `packages/padiem-ai-core/`
- Boundary authority: `packages/padiem-ai-core/BOUNDARY.md`
- Platform registry: `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`
- Adoption playbook: `docs/internal-platform/AI_ADOPTION_PLAYBOOK.md`

Canonical Issue prefix for new work: `[IP-CORE]`.

Refs #1707.
