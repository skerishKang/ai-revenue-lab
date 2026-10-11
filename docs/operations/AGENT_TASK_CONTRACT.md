# Bounded Agent Task Contract

```
Issue      #2786 (E9 A5-Agent) — Stage 13, S13-3b
Scope      projection contract only: additive keys on the existing agent_skill result block
Source     apps/padiem-ai-engine/app/agent_skill_projection.py
Version    padiem.engine.agent-task/1.0
```

## 1. What this contract is for

The runtime could already execute a bounded agent task, but a caller had to infer the task identity, the owner and
the audit evidence from lifecycle fields. This contract names them explicitly so a product surface can adopt the
capability without guessing, and without the Engine widening any authority.

It is **additive**: every key that existed before keeps its exact previous meaning.

## 2. Fields

Returned inside the existing `agent_skill` block of `POST /internal/v1/agent-skill/run`:

| Field | Source (trusted) | Meaning |
|---|---|---|
| `task_contract_version` | constant | `padiem.engine.agent-task/1.0` |
| `task_id` | canonical alias of the runner's run id (the id already emitted on every orchestration event) | task identity — **no new identifier is minted** |
| `owner_identity.subject_id` | trusted binding state (`selection.subject_id`) | who owns the task; the transporting caller identity is deliberately not projected |
| `capability_required` | trusted agent definition (`required_capabilities`) | capability the task required — a server-side requirement, never a caller claim |
| `execution_status` | `execution_state` when set, otherwise `run_status` | canonical status for the task |
| `result_reference` | result projection | `{run_id, answer_present, resolved_tool_ids, tool_event_count}` — a bounded pointer, not the result payload |
| `audit_event` | projected event chain | `{trace_id, event_count, terminal_kind}` — in-response evidence |

Example:

```json
{
  "agent_skill": {
    "contract_version": "padiem.engine.agent-skill/1.0",
    "execution_state": "completed",
    "task_contract_version": "padiem.engine.agent-task/1.0",
    "task_id": "orch_run_414f998706f24d41",
    "owner_identity": {"subject_id": "actor:a5-synthetic"},
    "capability_required": ["agent_task_execution"],
    "execution_status": "completed",
    "result_reference": {
      "run_id": "orch_run_414f998706f24d41",
      "answer_present": true,
      "resolved_tool_ids": ["a5-agent-probe.tool"],
      "tool_event_count": 1
    },
    "audit_event": {"trace_id": "agtr_79b89087…", "event_count": 6, "terminal_kind": "run_completed"}
  }
}
```

## 3. What is not projected

```text
caller / transport identity        (not the product owner identity)
raw tool arguments and results
planner objectives and scratchpad
compiled policy bodies, grants, entitlement state, provider routing
hidden reasoning
```

## 4. Authority and failure behaviour (unchanged)

```text
unbound application                       -> 503 agent_skill_runtime_unavailable
caller-supplied authority fields           -> caller_agent_authority_not_allowed
required capability not trusted            -> 403 capability_missing
same idempotency key, different request    -> 409 idempotency_conflict
skill enablement cannot widen tool authority; inactive skill state fails closed
```

## 5. Test coverage

`apps/padiem-ai-engine/tests/test_agent_task_contract.py`

```text
contract fields present · existing keys unchanged · projection rejects foreign inputs
caller authority injection rejected (subject_id / provider_route / authorization / connector_grants)
unbound application 503 · capability_missing 403 · idempotency_conflict 409
provider-free (runtime call count 0) · two executions are two distinct task ids
```

## 6. Non-goals of this contract

```text
no consumer wiring (Claw/Chat adoption is a separate step)
no durable audit storage (in-response evidence only; a later stage)
no artifact storage or artifact references
no multi-agent chaining, long memory or autonomous planning
no new secret, workflow, deployment or production change
```

## 7. Rollback

The change is additive and reversible: reverting the projection commit restores the previous response shape. No
data migration and no production contract removal is involved; production rollback continues to use the deploy gate
with an explicit `rollback_version_id`.
