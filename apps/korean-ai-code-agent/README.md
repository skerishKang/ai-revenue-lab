# Korean AI Code Agent / Padiem Claw

Business 54의 canonical source workspace입니다.

> Product brand: **Padiem Claw**  
> Product family/category: **Padiem Agents**  
> Stable source path: `apps/korean-ai-code-agent/**`

Padiem Claw는 한국어 우선 실행형 AI Agent 제품으로, repository 선택 → task 입력 → context inspection → plan → bounded workspace → P01 orchestration → diff/test/evidence → human approval/result 흐름을 목표로 합니다.

## Architecture boundary

```text
B54 Padiem Claw
  owns: task/run/repository/sandbox product state, diff/test/GitHub workflow, UX
  consumes:
    P01 Padiem AI Core -> Agent/Tool/Skill/Approval/Recovery/Evidence/Orchestration
    B14 Korean AI Platform -> Provider/model credentials, routing, fallback, execution
    Shared Control Plane -> identity, entitlement, usage, credits, audit
```

B54는 별도 provider router, generic Agent runtime, Tool runtime, recovery engine을 재구현하지 않습니다.

## Current phase

Phase 1 terminal-first vertical slice는 repository containment, read-only Git inspection, deterministic B14 preview, diff-before-write, permission-gated mutation, allowlisted command execution, secret redaction, no automatic commit/push/merge/deploy 계약을 갖습니다.

Phase 2는 cloud/background-ready product boundaries를 추가하는 단계입니다. `ClawTaskIntent`, `ClawRun`, `RunProjection`, `SandboxLease` 계층을 분리하고 canonical P01 orchestration을 소비하는 방향으로 진행합니다.

## Documentation

- Canonical documentation pack: [`docs/README.md`](docs/README.md)
- One-page product/operations overview: [`docs/index.html`](docs/index.html)
- Initial product landing/portal: [`site/index.html`](site/index.html)

## Key invariants

```text
sandbox lease allocated != agent execution started
RUNNING requires canonical P01 RUN_STARTED evidence
network defaults off for early cloud sandbox policy
terminal runs cannot be silently resurrected
provider/model credentials never belong in Claw task/run projections
GitHub automation defaults to Draft PR before any later merge authority
```

## Governance

Refs: #372, #376, #1383, #1392, #1396, #1399, P01 #1098/#1212, B62 #1224.

GitHub merged source and reviewed Markdown are canonical. Drive Docs are readable mirrors. HTML is overview/marketing surface and does not redefine runtime contracts.
