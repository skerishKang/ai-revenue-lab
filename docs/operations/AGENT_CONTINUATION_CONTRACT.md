# Agent Continuation Contract (Phase 1 — Resume)

```
Issue      #2786 (E9 A5-Agent) — Stage 13, S13-4 Phase 1
Scope      additive projection of the execution *lifecycle* contract on resume responses
Source     apps/padiem-ai-engine/app/agent_skill_continuation_projection.py
Version    padiem.engine.agent-continuation/1.0
```

## 1. Purpose

A continuation could already be resumed, but the response said nothing about the lifecycle: which
continuation ran, whose task it is, what state it left and reached, and whether the verified approval delta was
applied. This contract names those facts. It is the lifecycle counterpart of the task contract
(`AGENT_TASK_CONTRACT.md`), which stays untouched.

## 2. Where it appears

Resume responses carry a **top-level sibling key**, so the two contracts keep separate responsibilities:

```json
{
  "ok": true,
  "agent_skill": { "...execution capability contract (unchanged)..." },
  "continuation": {
    "continuation_contract_version": "padiem.engine.agent-continuation/1.0",
    "continuation_id": "cont_ref_…",
    "task_id": "orch_run_…",
    "owner_identity": { "subject_id": "actor:…" },
    "current_state": "active",
    "resume_target_state": "completed",
    "resume_authority": { "approval_delta_applied": true, "capability_required": ["…"] },
    "audit_event": { "trace_id": "agtr_…", "event_count": 6, "terminal_kind": "run_completed" }
  }
}
```

```text
agent_skill   = execution capability contract
continuation  = execution lifecycle contract
```

## 3. Cancel responses (Phase 2)

A cancel response keeps its existing shape and gains the same sibling key:

```json
{
  "ok": true,
  "status": "cancelled",
  "events": [ "…unchanged…" ],
  "continuation": {
    "continuation_contract_version": "padiem.engine.agent-continuation/1.0",
    "continuation_id": "cont_ref_…",
    "task_id": "bridge_run_…",
    "current_state": "active",
    "terminal_state": "cancelled",
    "cancel_reason": "user_cancelled",
    "audit_event": { "trace_id": "agtr_…", "event_count": 1, "terminal_kind": "run_cancelled" }
  }
}
```

```text
NO owner identity on cancel: the cancel path has no trusted execution selection, so the Engine has no
  trusted subject source on this route. That gap is recorded rather than filled with an invented identity
  or a new runtime lookup (Phase 2 decision: OWNER_IDENTITY_ON_CANCEL=DEFERRED, NO_TRUSTED_SOURCE).
NO claim tokens, cancel fingerprints, request fingerprints or authority material.
```

## 4. Field sources

| Field | Source (trusted) |
|---|---|
| `continuation_contract_version` | constant |
| `continuation_id` | the server-issued continuation reference (`record.continuation_ref`) |
| `task_id` | canonical alias of the paused run id (`record.pause.run_id`), same rule as the task contract |
| `owner_identity.subject_id` | trusted binding state — the transporting caller identity is never projected |
| `current_state` | `record.state` before the resume |
| `resume_target_state` | state reached by the resumed run (`execution_state`, else run status) |
| `resume_authority` | summary only: whether the verified approval delta was applied, plus the trusted capability requirement |
| `audit_event` | in-response evidence (`trace_id`, event count, terminal kind) |

Cancel-specific:

| Field | Source (trusted) |
|---|---|
| `current_state` | `record.state` before the cancellation claim |
| `terminal_state` | the persisted state after `commit_cancel` (`cancelled`) |
| `cancel_reason` | the persisted cancel reason (falls back to the parsed request reason) |

## 4. What never crosses

```text
approval decision bodies, decision/evidence references, invocation digests
claim tokens, store fingerprints, authority material, grants, entitlement state
transport caller identity (owner is the bound subject)
raw tool arguments/results
```

## 5. Lifecycle states

The contract reports the states the runtime already produces; it does not introduce a new state machine.

```text
record.state        active        (store-managed, CAS transitions)
run states          created → running → paused → (resumed) → completed / failed / cancelled
resume_target_state the state the resumed run reached
```

## 6. Failure behaviour (unchanged)

```text
continuation store unavailable / no atomic cancellation   -> 503 continuation_store_unavailable
malformed continuation_ref or decision                    -> 400 invalid_request / invalid_decision
decision for another continuation                         -> 409 continuation_identity_mismatch
approval denied / expired continuation                    -> 409 approval_denied / continuation_expired
authority widening or missing approval authorization      -> 403 (unchanged mapping)
```

## 7. Test coverage in this phase

```text
COVERED — resume
  projection contract fields and their trusted sources
  owner derived from the binding, never from request input
  task contract unaffected (backward compatibility)
  authority summary exposes no authority material · approval-delta flag · foreign-input rejection
  provider-free · coordinator guards before Core resume (store unavailable, unknown continuation,
  malformed decision, decision/continuation mismatch)
COVERED — paused-run lifecycle (shared fixture: a genuine Core approval pause)
  pause response carries a continuation reference and a paused approval block
  resume happy path publishes the continuation contract
  resume without the trusted approval delta → 409 continuation_authority_mismatch
  duplicate resume → 409 continuation_consumed
  resume after cancel → 409 continuation_cancelled
COVERED — cancel
  contract fields · owner omitted · no authority material · response backward compatibility
  cancel happy path (active → cancelling → cancelled) · already cancelled → 409
  unknown continuation → 409 invalid_continuation · expired continuation → 409 continuation_expired
  foreign application → 409 invalid_continuation · unsupported fields → 400
  trusted trace identity required · provider-free
DEFERRED
  T13 concurrent cancel race (to be judged after this phase)
```

## 8. Non-goals

```text
no continuation_id exposure on run responses (Phase 1 decision; the paused-run 202 keeps returning the
  continuation reference it already returned before this contract existed)
no owner identity on cancel responses (Phase 2 decision: no trusted source on that route)
no consumer wiring, no Claw/Chat surface
no durable continuation history, no new storage, no migration
no preview wire, no production deployment
```

## 9. Rollback

Additive projection plus a response-assembly hook: reverting the change restores the previous response shape. The
continuation store, its CAS semantics, the resume flow and the authorization rules are untouched, so no data
migration or core rollback is involved. Production rollback continues to use the deploy gate with an explicit
`rollback_version_id`.
