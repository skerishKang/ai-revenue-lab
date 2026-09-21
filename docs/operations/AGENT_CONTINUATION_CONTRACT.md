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

## 3. Field sources

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
COVERED
  projection contract fields and their trusted sources
  owner derived from the binding, never from request input
  task contract unaffected (backward compatibility)
  authority summary exposes no authority material
  approval-delta flag reflects the caller assertion
  projection rejects non-core inputs
  provider-free (runtime call count 0)
  coordinator guards before Core resume: store unavailable, unknown continuation,
    missing app_id, malformed decision, decision/continuation mismatch, cancel unsupported fields

DEFERRED (tracked, not asserted here)
  happy-path resume, completed-task resume, duplicate resume, invalid transition
  — these need a genuine Core approval pause; they are the first tests to add when a
    paused-run fixture lands
```

## 8. Non-goals

```text
no continuation_id exposure on run responses (Phase 1 decision)
no cancel contract (Phase 2)
no consumer wiring, no Claw/Chat surface
no durable continuation history, no new storage, no migration
no preview wire, no production deployment
```

## 9. Rollback

Additive projection plus a response-assembly hook: reverting the change restores the previous response shape. The
continuation store, its CAS semantics, the resume flow and the authorization rules are untouched, so no data
migration or core rollback is involved. Production rollback continues to use the deploy gate with an explicit
`rollback_version_id`.
