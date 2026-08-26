# Padiem AI Core

Internal shared AI runtime contracts for Padiem products.

## Slice 1 boundary

This package is intentionally contracts-only. It does not execute models, tools, browsers, databases, authentication, or product workflows.

Current ownership boundary:

```text
Padiem product
  -> product adapter (later)
  -> Padiem AI Core shared contracts/runtime (this program)
  -> Business 14 model execution foundation (existing)
```

Business 14 remains the owner of provider access, Router Core, provider adapters and model execution. Padiem Chat remains a product/reference client. Slice 1 does not modify either runtime.

## Public contracts

- `Evidence` — product-neutral provenance/evidence metadata.
- `ToolSpec` — schema, ownership, side-effect, authorization and approval contract for a tool.
- `AgentProfile` — product-neutral agent instruction and execution-policy contract.
- `RunMetadata`, `ToolEvent`, `UsageMetadata` — shared trace/observability metadata.
- explicit enums for side effects, approval, run state and error classification.

## Safety properties

- runtime dependencies: none;
- no network or environment access at import time;
- immutable tuples and deeply frozen mapping inputs;
- explicit side-effect and approval values;
- unknown provider/model/usage values remain `None`;
- no credential/secret fields in public serialization.

## Deliberately deferred

- Business 14 client extraction;
- streaming;
- tool execution;
- read-only web/browser runtime;
- grounding/deep research orchestration;
- Padiem Chat import rewiring;
- memory/RAG;
- product adapters.

Authority: GitHub Issue #809.
