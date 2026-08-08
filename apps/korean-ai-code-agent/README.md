# Business 54 · Korean AI Code Agent

Business 54의 Phase 1 CLI/TUI vertical slice입니다. 제품 권위는 Issues #372, #376이며, 이전 browser-hosted coding workspace와 독립 AI Model Router 방향은 superseded입니다.

## Primary terminal UX

```text
terminal launch
→ repository selection
→ Korean task
→ read-only inspection
→ bounded plan
→ Business 14 route marker
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

The current route adapter is a deterministic UX contract marker. `BUSINESS14_BASE_URL` and `BUSINESS14_MODEL` are read as configuration presence/identity only; this slice does not make a live model call.

## Permission defaults

```text
repository read: allowed after repository selection
file write: ask
command execution: ask
network: off
git mutation: off
push / merge / deploy: absent
```

The patch preview is deliberately deterministic and bounded. It is not an autonomous coding implementation. It exists to prove the correct terminal interaction and permission sequence before a live Business 14 adapter is authorized.

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests
```

Tests cover help startup, plan-only no-write behavior, repository-root containment, denied writes, bounded approved writes, reject behavior, and command allowlist rejection of arbitrary shell/Git commands.

These tests are committed contracts. This connector-only implementation does **not** claim they were freshly executed in a local runtime; exact-head local terminal validation remains required by Issue #376.

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
WRITE_PERMISSION_REQUIRED
COMMAND_ALLOWLIST_REQUIRED
NETWORK_OFF
GIT_MUTATION_OFF
LOCAL_RUNTIME_VALIDATION_PENDING
DO_NOT_MERGE
```
