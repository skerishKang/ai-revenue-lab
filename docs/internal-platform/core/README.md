# IP-CORE · Padiem AI Core

```text
DOC_STATUS = CANONICAL_COMPONENT_GUIDE
PLATFORM_ID = IP-CORE
SOURCE = packages/padiem-ai-core/**
LAST_VERIFIED = 2026-09-08
```

Padiem AI Core는 제품 중립적인 **공용 AI 의미론과 계약**을 소유합니다.

## Owns

- normalized execution and streaming semantics
- bounded multimodal execution contracts
- Evidence / grounding / source quality
- Context Permission / Knowledge Boundary
- retrieval and Memory/RAG semantics
- Tool / Connector authorization contracts
- Skill package/registry/activation semantics
- Agent planning/approval/delegation/recovery semantics
- orchestration and adapter conformance
- bounded shared error/metadata behavior

## Does not own

- 제품 UX 또는 제품 도메인 상태
- StoryMemory Bible/classic-work locator grammar
- Chat conversation/history/Projects
- Claw repository/task/GitHub product workflow
- Provider/model catalog, inference credentials or a second router
- cross-runtime network/service identity boundary

## Dependency direction

```text
Product adapter
 -> IP-CORE
 -> B14 execution boundary
```

Cross-runtime exposure is owned by IP-ENGINE.

## Current detailed source documentation

See `packages/padiem-ai-core/README.md` for module-level capability details and tests. That README is the component implementation guide; the platform ownership boundary is defined by:

- `docs/architecture/PADIEM_AI_VERTICAL_STACK.md`
- `docs/internal-platform/INTERNAL_PLATFORM_REGISTRY.md`

Source presence does not imply Production activation or an Engine projection.
