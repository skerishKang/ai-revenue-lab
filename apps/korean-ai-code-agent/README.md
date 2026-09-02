# Business 54 · Padiem Claw / Korean AI Code Agent

Business 54의 canonical source는 계속 `apps/korean-ai-code-agent/**`입니다. Phase 1 CLI/TUI vertical slice(#372, #376)를 보존하면서 Issue #1383에서 **Padiem Claw**를 working product identity로 사용해 cloud/background-ready 경계를 리팩터링합니다.

```text
BUSINESS_ID = B54
CANONICAL_SOURCE = apps/korean-ai-code-agent/**
WORKING_PRODUCT_NAME = Padiem Claw
PACKAGE / CLI = korean-ai-code-agent / kagent
NEW_BUSINESS_NUMBER = NO
REAL_CLOUD_SANDBOX = NOT_CONFIGURED
```

`Padiem Claw`는 현재 별도 B65나 별도 shared runtime이 아닙니다. 이 앱은 제품 task/run/workspace/GitHub 흐름을 소유하고, 공유 Agent/Tool/Skill/approval/recovery 의미론은 P01 Padiem AI Core를 소비하며, 모델/Provider 실행은 Business 14를 소비하는 방향입니다.

## Architecture boundary

```text
Padiem Chat / CLI / future first-party surface
        │
        ▼
ClawTaskIntent                B54 product contract
        │
        ▼
ClawRun / RunProjection       B54 user-visible lifecycle
        │
        ├── local workspace   current foreground CLI
        │
        └── cloud request
              │
              ▼
        SandboxLeasePort      resource boundary only
              │
              ▼
        PREPARING             sandbox != agent execution
              │
              ▼
        future trusted P01 orchestration adapter
              │
              ▼
        Padiem AI Core
              │
              ▼
        Business 14
              │
              ▼
        Provider / model
```

Ownership locks:

- **B54 / Claw**: task identity, repository/revision reference, product run projection, workspace/sandbox resource request, product-specific diff/test/review/GitHub workflow.
- **P01 Core**: Agent planner/runtime, Tool/Connector authorization, reusable Skill execution, approval continuation, retry/recovery/delegation, Memory/RAG, Evidence/Verification and shared orchestration semantics.
- **Business 14**: Provider/model registry, Provider credentials, route selection, fallback and actual model execution.
- **Control Plane**: canonical identity, entitlement, usage/credits/subscription/audit when later integrated.

B54 must consume these shared authorities rather than recreate them.

## Phase 2 refactor

The former `AgentSession` was a practical Phase 1 façade but mixed session state, repository safety, Git probing, B14 mock logic, patch state and secret redaction. Phase 2 separates those responsibilities while preserving the existing CLI surface.

```text
kagent/security.py     output-secret redaction
kagent/adapters.py     B14 consumer preview adapter; no routing authority
kagent/contracts.py    immutable task/run/sandbox projection contracts
kagent/runs.py         B54 product lifecycle state machine only
kagent/sandbox.py      provider-neutral sandbox lease port + network-free fake
kagent/preparation.py  cloud workspace preparation only; never starts an agent
kagent/workspace.py    repository containment + read-only Git inspection
kagent/patching.py     pure proposed-patch value object; no filesystem writes
kagent/core.py         Phase 1 compatibility façade + composition root
```

`AgentSession` now remains primarily as a compatibility façade. Repository containment/Git reads, patch diff construction, B14 preview and redaction are separated behind dedicated components instead of accumulating future cloud/P01/GitHub logic in one class.

### Product run states

```text
queued
→ preparing
→ running
↔ waiting_approval
→ completed | failed | cancelled
```

Only explicit transitions are accepted. `completed`, `failed`, and `cancelled` are terminal and cannot silently resume. This lifecycle is a product-facing container, not a replacement for P01 execution/recovery events.

### Cloud preparation safety

A cloud task may request bounded resource metadata through `SandboxLeaseRequest`:

```text
execution_mode
repository_ref
requested_revision
resource_class
TTL
network_policy
writable_workspace
```

There is intentionally **no user-supplied sandbox hostname/endpoint** and no Provider/model credential in these contracts. Default network policy is `off`; TTL is bounded to 60–3600 seconds. Wire-facing enum, integer and boolean fields are validated/coerced explicitly rather than relying only on Python type hints.

The default `UnconfiguredSandboxProvider` fails closed. The committed `DeterministicFakeSandboxProvider` is for network-free tests and architecture exercises only and is not a production sandbox claim.

Most importantly:

```text
sandbox lease allocated
!=
agent is running
```

A successful lease leaves a cloud run in `PREPARING`. A later trusted P01 adapter must establish actual orchestration before the B54 projection may advance to `RUNNING`.

## Primary terminal UX — preserved

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

The Phase 1 CLI still requires the task text to contain Korean. English code/file names may be mixed into the Korean task.

The Business 14 adapter remains a **deterministic network-free preview contract**. It emits a stable request ID, normalized route marker, `resolved_not_called`, and `network_called=false`; it does not duplicate Provider selection, credentials, catalog, fallback or live model execution. Existing `AgentSession.business14_mock_response()` delegates to the separated adapter for compatibility.

`AgentSession.task_intent(...)` can now project a foreground CLI session into `ClawTaskIntent`. The session's B14 `route` is deliberately excluded from that product task contract.

## Permission defaults

```text
repository read: allowed after repository selection
file write: ask
command execution: ask
network: off
git mutation: off
push / merge / deploy: absent
```

The patch preview remains deterministic and bounded. `PendingPatch` is a pure value object; actual filesystem writes remain behind `AgentSession.apply()` and still require explicit write permission. Before apply, KAgent verifies that the selected file still matches the previewed original text. If the file changed after preview, apply fails closed instead of overwriting another change.

`RepositoryWorkspace` owns path containment and read-only repository inspection. Symbolic links are skipped during inspection, and any path resolving outside the selected root is rejected. Its Git probe runs only:

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

Committed tests cover the Phase 1 contracts plus Phase 2 boundaries:

- CLI help, Korean task contract and read-only Plan mode;
- repository-root and symlink-escape containment plus bounded inspection limits;
- clean/dirty Git status using read-only Git commands;
- deterministic network-free B14 preview compatibility;
- denied/approved bounded writes and concurrent-change fail-closed behavior;
- command allowlist, failing/passing test evidence and secret redaction;
- `ClawTaskIntent`, `RunProjection`, sandbox request/lease validation and safe serialization;
- malformed wire enum/type rejection and bounded scalar validation;
- legal/illegal run transitions and terminal-state immutability;
- approval-state projection and changed-file bounds;
- sandbox network-off default, TTL bounds, lease expiry/release and cross-run isolation;
- unconfigured cloud provider fail-closed behavior;
- explicit proof that workspace preparation stops at `PREPARING` rather than claiming P01 agent execution;
- Phase 1 `AgentSession` compatibility after workspace/patch/B14/security extraction.

## Non-goals / hard boundaries

- no new B65 or duplicate Padiem Agent product;
- no browser coding workspace in this slice;
- no Provider registry, model registry, credentials, billing or fallback duplication from Business 14;
- no P01 Agent/Tool/Skill/approval/retry/recovery reimplementation;
- no real model/API request in this slice;
- no real cloud sandbox provider or VM/container provisioning;
- no credential discovery or logging;
- no arbitrary shell execution;
- no automatic Git reset/clean/checkout/commit/push/merge;
- no deployment;
- no production sandbox claim.

```text
B54_CANONICAL
PADIEM_CLAW_WORKING_IDENTITY
CLI_TUI_COMPATIBILITY_PRESERVED
TASK_RUN_SANDBOX_BOUNDARIES_SPLIT
WORKSPACE_IO_BOUNDARY_SPLIT
PATCH_VALUE_OBJECT_SPLIT
P01_SEMANTICS_NOT_DUPLICATED
B14_ROUTING_NOT_DUPLICATED
B14_PREVIEW_NETWORK_FREE
CLOUD_PROVIDER_FAIL_CLOSED
SANDBOX_LEASE_IS_NOT_AGENT_EXECUTION
WRITE_PERMISSION_REQUIRED
COMMAND_ALLOWLIST_REQUIRED
NETWORK_OFF_BY_DEFAULT
GIT_MUTATION_OFF
NO_PRODUCTION_SANDBOX_CLAIM
```
