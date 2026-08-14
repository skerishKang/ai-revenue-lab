# Business 54 · Korean AI Code Agent

Business 54의 Phase 1 CLI/TUI vertical slice입니다. 제품 권위는 Issues #372, #376이며, 이전 browser-hosted coding workspace와 독립 AI Model Router 방향은 superseded입니다.

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

These tests are committed contracts. This Web/connector implementation does **not** claim fresh Windows exact-head execution. Issue #376 still requires final independent Windows/local validation of the exact final head before merge readiness.

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
WINDOWS_EXACT_HEAD_VALIDATION_PENDING
DO_NOT_MERGE
```
