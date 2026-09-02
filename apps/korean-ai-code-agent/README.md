# Business 54 · Korean AI Code Agent

Business 54의 Phase 1 CLI/TUI vertical slice입니다. 제품 권위는 Issues #372, #376이며, 이전 browser-hosted coding workspace와 독립 AI Model Router 방향은 superseded입니다.

## Padiem Claw product identity

> Product brand: **Padiem Claw**  
> Product family/category: **Padiem Agents**  
> Stable source path: `apps/korean-ai-code-agent/**`

Padiem Claw는 이 기존 B54 Korean AI Code Agent를 폐기하거나 새 제품으로 복제하지 않고, Phase 1 terminal-first 안전 계약을 그대로 기준선으로 삼아 local + cloud AgentOps 제품으로 확장하는 public/product identity입니다.

## Primary terminal UX

```text
terminal launch
→ repository selection
→ Korean task
→ read-only inspection
→ clean/dirty Git status report (read-only)
→ bounded plan
→ deterministic Business 14 mock-adapter evidence
→ unified diff preview
→ explicit write permission
→ explicit allowlisted command permission
→ review
→ user apply / reject / revise
```

## Run

Python 3.11+:

```bash
cd apps/korean-ai-code-agent
python -m pip install -e .
kagent --help
kagent . plan "인증 흐름을 분석해줘"
kagent . run "저장 버튼 오류를 찾아 테스트까지 고쳐줘"
```

Phase 1 requires the task text to contain Korean. English code/file names may be mixed into the Korean task.

The Business 14 adapter is a **deterministic mock contract** in this slice. It emits a stable request ID, normalized route marker, `resolved_not_called`, and `network_called=false`; it does not duplicate Business 14 Provider selection, BYOK, catalog, fallback, or live model execution. `BUSINESS14_BASE_URL` and `BUSINESS14_MODEL` are reported only as configuration presence/identity.

## Permission defaults

```text
repository read: allowed after repository selection
file write: ask
command execution: ask
network: off
git mutation: off
push / merge / deploy: absent
```

The patch preview is deliberately deterministic and bounded. Before apply, KAgent verifies that the selected file still matches the previewed original text. If the file changed after preview, apply fails closed instead of overwriting another change.

Repository inspection skips symbolic links. Path resolution rejects any symlink or relative path that resolves outside the selected repository root.

Git status reporting runs only:

```text
git status --porcelain=v1 --untracked-files=all
```

It never runs `git add`, `reset`, `clean`, `checkout`, `commit`, `push`, `merge`, or deployment commands.

## Allowed test commands

Only these exact command shapes are accepted:

```text
python -m unittest
python -m unittest discover
python -m compileall .
```

Captured stdout/stderr is redacted before display for Bearer tokens, `sk-*` key shapes, and common `api_key` / `token` / `secret` / `password` assignments.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Committed tests cover:

- help startup;
- Korean task contract and normal run journey;
- plan-only no-write behavior;
- repository-root and symlink-escape containment;
- clean/dirty Git status detection using read-only Git commands;
- deterministic, network-free Business 14 mock-adapter evidence;
- denied writes and bounded approved writes;
- concurrent-change fail-closed behavior;
- reject preserving the original file;
- arbitrary shell/Git/network command rejection;
- a disposable failing unittest followed by a corrected passing unittest;
- stdout/stderr secret redaction.

These tests are committed contracts. Exact-head CI for the current-main restack passed on both `ubuntu-latest` and `windows-latest` with Python 3.12, `compileall`, and the full stdlib unittest suite before merge. This validates the bounded CLI contract without making a live B14/provider call.

## Non-goals / hard boundaries

- no browser coding workspace;
- no Provider registry or billing duplication from Business 14;
- no real model/API request in this slice;
- no credential discovery or logging;
- no arbitrary shell execution;
- no automatic Git reset/clean/checkout/commit/push/merge;
- no deployment;
- no background agent;
- no production sandbox claim.

```text
CLI_TUI_FIRST
DETERMINISTIC_VERTICAL_SLICE
BUSINESS_14_DEPENDENT
B14_MOCK_ADAPTER_NETWORK_FREE
WRITE_PERMISSION_REQUIRED
COMMAND_ALLOWLIST_REQUIRED
SYMLINK_ESCAPE_BLOCKED
WORKTREE_STATE_READ_ONLY
SECRET_OUTPUT_REDACTED
NETWORK_OFF
GIT_MUTATION_OFF
WINDOWS_EXACT_HEAD_VALIDATED
DO_NOT_MERGE
```

## Phase 2 — Padiem Claw cloud mode

Phase 2 extends the product boundary without weakening the Phase 1 safety contract or duplicating shared platform authority.

The first cloud milestone is deliberately narrow:

**one repository → one task → one isolated sandbox → verified diff**

### Authority boundaries

```text
B54 Padiem Claw
  owns: task/run/repository/sandbox product state, diff/test/GitHub workflow, UX
  consumes:
    P01 Padiem AI Core -> Agent/Tool/Skill/Approval/Recovery/Evidence/Orchestration
    Padiem AI Engine -> cross-runtime service boundary over Core
    B14 Korean AI Platform -> provider/model credentials, routing, fallback, execution
    Shared Control Plane -> identity, entitlement, usage, credits, audit
    B62 Padiem Chat -> discovery/handoff/progress/result presentation only
```

B54 does not reimplement a provider router, generic Agent runtime, Tool runtime, recovery engine, or shared account/credit plane.

`ClawTaskIntent`, `ClawRun`, `RunProjection`, and `SandboxLease` remain distinct contracts. Sandbox allocation is product infrastructure state and is not proof that canonical P01 Agent execution started.

Cloud execution is not production-ready until:

1. a reviewed sandbox threat model exists;
2. task/run/sandbox contracts are stable;
3. lifecycle controls support cancel, timeout, recovery, and audit;
4. GitHub mutation is permission-gated and starts with branch + Draft PR output;
5. exact-head verification is repeatable.

Phase 2 does **not** authorize silent commit, push, merge, deploy, or automatic resurrection of a stopped terminal run. Durable background execution, resume/recovery, and later parallel fan-out come only after the single-run sandbox path is reliable.

### Cloud-mode invariants

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
- One-page product/operations overview: [`docs/index.html`](docs/index.html)
- Initial product landing/portal: [`site/index.html`](site/index.html)

The canonical documentation pack covers source-of-truth, product/PRD, architecture, security, operations, release/rollback, reliability/incident response, business/pricing, and roadmap material.

## Governance

Refs: #372, #376, #1383, #1392, #1396, #1399, P01 #1098/#1212, B62 #1224.

GitHub merged source and reviewed Markdown are canonical. Drive Docs are readable mirrors. HTML is overview/marketing surface and does not redefine runtime contracts.
