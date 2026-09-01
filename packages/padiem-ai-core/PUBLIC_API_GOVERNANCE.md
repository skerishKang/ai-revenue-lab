# Padiem AI Core public API governance

This document records the compatibility policy for the `padiem_ai_core` package root. It is governance for the existing API surface, not authorization to remove or deprecate exports.

## Current compatibility authority

At the start of this policy the package is `0.6.x` and the package-root surface is frozen for compatibility.

```text
ROOT_EXPANSION_POLICY = FREEZE
EXISTING_ROOT_EXPORTS = PRESERVE
DEPRECATED_EXPORTS_APPROVED = NONE
ROOT_EXPORT_REMOVAL = EXPLICIT_BREAKING_CHANGE_ONLY
OPTIONAL_TOOL_RUNTIME_LAZY_BEHAVIOR = PRESERVE
```

Repository AST inventory established that package-root imports are active runtime dependencies in Living Learning, Padiem AI Engine, and Padiem Chat. Repository evidence does not establish the full set of external consumers, so absence of a known external consumer must never be treated as permission to remove an export.

## Export status

### PUBLIC_STABLE

The stable package-root family is intentionally narrow. It includes foundational contracts and primary execution entry concepts such as:

- `AgentProfile`, `ApprovalPolicy`, `ErrorClass`, `Evidence`;
- `RunMetadata`, `RunStatus`, `ToolEvent`, `ToolSideEffect`, `ToolSpec`, `UsageMetadata`;
- `ExecutionRequest`, `ExecutionResult`, `ExecutionRuntime`, `ExecutionRuntimeError`;
- `MultimodalExecutionRequest`, `MultimodalExecutionRuntime`;
- `StreamingExecutionEvent`, `StreamingExecutionRuntime`.

### PUBLIC_COMPATIBILITY

Every other name currently exposed by package-root `__all__` or its lazy Tool Runtime lookup remains supported for compatibility unless a later approved versioned deprecation changes that status.

`PUBLIC_COMPATIBILITY` means existing imports remain supported. It does not mean new callers should prefer the root over the owning submodule.

### INTERNAL_SHOULD_NOT_EXPAND

Do not add new package-root re-exports by default for low-level or implementation-detail categories, including:

- `MAX_*` implementation limits;
- provider-specific origins and route/path constants;
- low-level B14 transport details;
- `Prepared*` intermediate structures;
- registry snapshots and bounded registry internals;
- parser, dedupe, validator and fingerprint helpers;
- adapter-conformance internals;
- provider-specific implementation helpers;
- new low-level evidence/orchestration implementation types.

Existing names in these categories remain `PUBLIC_COMPATIBILITY` until an approved migration is complete.

### DEPRECATED_CANDIDATE

None are approved at this time.

## Owning submodule rule

For every current package-root export, the owning submodule is the relative module that supplies the name to `padiem_ai_core.__init__`.

For lazy-only Tool Runtime names, the owner is `tool_runtime`.

The ownership contract is validated by `tests/test_package_root_ownership.py`, which requires every `__all__` name to resolve to exactly one owning submodule and requires that owning module to exist.

Current owner modules are:

```text
contracts
web_runtime
b14_execution
b14_multimodal
b14_transport
b14_streaming
grounding_runtime
execution_runtime
multimodal_execution_runtime
streaming_runtime
execution_state_machine
execution_context
contextual_execution
retrieval
memory
memory_read
memory_receipt
memory_context
agent_approval
agent_definition
agent_profile_adapter
agent_planner
agent_recovery
agent_delegation
agent_events
skill_package
skill_versioning
skill_registry
skill_activation
skill_runtime_adapter
tool_registry
connector_registry
tool_resource_policy
tool_lifecycle
evidence_graph
evidence_verification
evidence_citation
evidence_assessment
orchestration_events
orchestration
agent_execution_bridge
adapter_conformance
tool_runtime
```

## Recommended import path

Existing root imports remain valid compatibility imports. New specialized code should normally import from the owning submodule:

```python
from padiem_ai_core.<owning_module> import <name>
```

Examples for currently observed low-level runtime dependencies:

```python
from padiem_ai_core.b14_execution import B14_CHAT_COMPLETIONS_PATH
from padiem_ai_core.b14_streaming import B14_STREAM_PREVIEW_PATH
from padiem_ai_core.b14_execution import MAX_B14_RESPONSE_BYTES
from padiem_ai_core.execution_context import request_fingerprint
```

This policy does not require existing consumers to migrate merely to satisfy style preference. Migration must have a concrete compatibility or architecture benefit and its own reviewed scope.

## Versioning and deprecation policy

Project compatibility policy is intentionally stricter than the minimum latitude normally associated with a pre-1.0 semantic version.

### Patch releases

Within an existing minor line such as `0.6.x`:

- do not remove or rename package-root exports;
- do not change the meaning of an existing root export;
- do not break lazy optional-dependency behavior;
- do not introduce a deprecation warning without a separately approved API-governance change.

### Minor releases

A new minor release may add specialized APIs in their owning submodules. A new package-root re-export still requires explicit public-API approval and must not be added automatically.

Introducing a deprecation requires all of the following first:

1. a repository consumer inventory and best-effort known external consumer inventory;
2. a stable replacement import path in the owning submodule;
3. migration documentation and compatibility tests;
4. an explicit deprecation issue/PR and version decision;
5. exact-head CI proving existing non-deprecated behavior remains intact.

### Migration window

An export must not be removed in the same released minor line in which its deprecation warning first appears. At least one released minor-version migration window must exist between first warning and removal, and the actual removal version requires separate approval.

If material external-consumer uncertainty remains, removal stays blocked even after a warning window.

### Breaking removal or rename

Any root export removal or rename is a public breaking change. It requires:

- explicit owner approval;
- exact affected-consumer evidence;
- a separately reviewed version bump;
- completed migration or an explicitly accepted compatibility break;
- exact-head compatibility CI.

No current issue or document authorizes such a removal.

## Lazy Tool Runtime contract

`Tool Runtime` remains an optional dependency surface. Lazy-only exports are owned by `padiem_ai_core.tool_runtime`; importing the base package must not require `jsonschema`, and accessing a lazy Tool Runtime export without the optional dependency must preserve the existing normalized `ImportError` guidance.

The current lazy-only set is contract-tested. Some eagerly imported orchestration names also appear in the historical lazy-export declaration; that redundancy is preserved for now and is not an authorization to alter lazy behavior.

## Evidence boundaries

The repository inventory is reproducible from checked-out source and is protected by CI. It does not prove that no external package, deployment, notebook, unpublished service, or downstream repository imports the package root.

Therefore:

```text
REPOSITORY_CONSUMER_INVENTORY = PROVEN
EXTERNAL_CONSUMER_INVENTORY = NOT_COMPLETE
ROOT_REMOVAL_AUTHORITY = NO
```

Refs: #1347, #1346, PR #1348, PR #1350.
