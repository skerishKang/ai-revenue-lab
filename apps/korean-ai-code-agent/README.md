# Padiem Claw — Korean AI Code Agent (B54)

Business 54의 canonical source workspace입니다.

> Product brand: **Padiem Claw**  
> Product family/category: **Padiem Agents**  
> Stable source path: `apps/korean-ai-code-agent/**`

**Single-line promise:** A Korean-first repo workspace that gets permission for every file write or command execution.

Padiem Claw는 한국어 우선 실행형 AI Agent 제품으로, 기존 Phase 1 foreground-safe CLI를 보존하면서 local + cloud AgentOps 제품으로 발전합니다. Phase 1의 안전 계약은 Phase 2에서도 약화하지 않습니다.

## Architecture boundary

```text
B54 Padiem Claw
  owns: task/run/repository/sandbox product state, diff/test/GitHub workflow, UX
  consumes:
    P01 Padiem AI Core -> Agent/Tool/Skill/Approval/Recovery/Evidence/Orchestration
    Padiem AI Engine -> cross-runtime service boundary over Core
    B14 Korean AI Platform -> Provider/model credentials, routing, fallback, execution
    Shared Control Plane -> identity, entitlement, usage, credits, audit
    B62 Padiem Chat -> discovery/handoff/progress/result presentation only
```

B54는 별도 provider router, generic Agent runtime, Tool runtime, recovery engine을 재구현하지 않습니다.

## Phase 1 contract

### Default permissions
- Repository reads are allowed only after the user has selected a repository.
- File writes always require an explicit `write` approval.
- Command execution always requires an explicit `command` approval.
- Network, git commit, push, merge, deploy, and background execution are out of scope for this phase.

### Supported task request

```json
{
  "repositoryRef": "/absolute/path/to/repo",
  "task": "요청 내용을 한글로 설명"
}
```

`repositoryRef` is optional when the command is already running from the target repository.

### Provider execution boundary
- B54 owns the Korean CLI UX, repository reads, local patch preparation, approvals, tests, and the evidence summary.
- B14 owns model/provider registration, provider/model selection, fallback, credential ownership, usage, and actual LLM execution.
- The Phase 1 wired runtime accepts B14-compatible mock execution fields through environment placeholders so tests can exercise the integration boundary without live provider calls.
- The mock contract is intentionally narrow and does not let B54 own provider APIs.

## Local CLI

```bash
node apps/korean-ai-code-agent/cli.mjs --repo /path/to/repo "한글 작업 요청"
```

Large repositories can be scanned deterministically with:

```bash
node apps/korean-ai-code-agent/cli.mjs \
  --repo /path/to/repo \
  --max-files 64 \
  --max-scan-files 4096 \
  "분석해"
```

### Exact repository pinning

The CLI records the repository's current git HEAD in `repository.gitHead` when a commit exists. If the repository changes before the user responds to a write or command approval, the CLI pauses instead of mutating the moved state.

### Proposal safety checks

When a proposal contains a file patch:
- the target path must stay inside the selected repository,
- existing symlink targets are rejected,
- the preview records whether the file already exists,
- a moved repository or changed target invalidates the write approval before apply.

## Tests

```bash
npm run test:b54-korean-ai-code-agent
```

The deterministic suite covers:
- repository inspection and exact repository-ref behavior,
- large repository scan bounds,
- mocked B14 integration,
- write approval and rejection,
- changed-reference rejection,
- symlink-target rejection,
- command approval, rejection, and deny-by-default command policy,
- happy and failure evidence paths.

## Phase 2 — Padiem Claw cloud mode

Phase 2 adds cloud/background-ready product boundaries while consuming canonical P01 orchestration. `ClawTaskIntent`, `ClawRun`, `RunProjection`, and `SandboxLease` remain distinct contracts.

The first cloud milestone is deliberately narrow:

**one repository → one task → one isolated sandbox → verified diff**

Cloud execution is not production-ready until:
1. a reviewed sandbox threat model exists,
2. task/run/sandbox contracts are stable,
3. lifecycle controls support cancel, timeout, recovery, and audit,
4. GitHub mutation is permission-gated and begins with branch + Draft PR output,
5. exact-head verification is repeatable.

Phase 2 does **not** authorize silent commit, push, merge, or deploy. Durable background execution, resume/recovery, and later parallel fan-out come only after the single-run sandbox path is reliable.

## Key invariants

```text
sandbox lease allocated != agent execution started
RUNNING requires canonical P01 RUN_STARTED evidence
network defaults off for early cloud sandbox policy
terminal runs cannot be silently resurrected
provider/model credentials never belong in Claw task/run projections
GitHub automation defaults to Draft PR before any later merge authority
```

## Documentation

- Canonical documentation pack: [`docs/README.md`](docs/README.md)
- [Source of Truth](./docs/SOURCE_OF_TRUTH.md)
- [Product Charter & PRD](./docs/PRODUCT_CHARTER_AND_PRD.md)
- [System Architecture](./docs/SYSTEM_ARCHITECTURE.md)
- [Security & Trust](./docs/SECURITY_AND_TRUST.md)
- [Operations Runbook](./docs/OPERATIONS_RUNBOOK.md)
- [Release & Rollback](./docs/RELEASE_AND_ROLLBACK.md)
- [Reliability & Incident Response](./docs/RELIABILITY_AND_INCIDENT_RESPONSE.md)
- [Business & Pricing](./docs/BUSINESS_AND_PRICING.md)
- [Roadmap](./docs/ROADMAP.md)
- [One-page documentation portal](./docs/index.html)
- [Product landing/portal prototype](./site/index.html)

## Governance

Refs: #372, #376, #1383, #1392, #1396, #1399, P01 #1098/#1212, B62 #1224.

GitHub merged source and reviewed Markdown are canonical. Drive Docs are readable mirrors. HTML is overview/marketing surface and does not redefine runtime contracts.
