# Agent Continuation Contract (Phase 1 — Resume · Phase 2 — Cancel · Phase 3 — Lifecycle Events)

```
Issue      #2786 (E9 A5-Agent) — Stage 13, S13-4 Phase 1/2/3
Scope      additive projection of the execution *lifecycle* contract on continuation responses
Source     apps/padiem-ai-engine/app/agent_skill_continuation_projection.py
Version    padiem.engine.agent-continuation/1.0
Lifecycle  padiem.engine.agent-continuation-lifecycle/1.0  (Phase 3, internal-only)
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
    "lifecycle_contract_version": "padiem.engine.agent-continuation-lifecycle/1.0",
    "lifecycle_events": [ { "kind": "resume_requested", "sequence": 1, … }, { "kind": "resumed", "sequence": 2, "terminal": true, … } ],
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
    "lifecycle_contract_version": "padiem.engine.agent-continuation-lifecycle/1.0",
    "lifecycle_events": [ { "kind": "cancel_requested", "sequence": 1, … }, { "kind": "cancelled", "sequence": 2, "terminal": true, … } ],
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
COVERED — lifecycle events (Phase 3, tests/test_agent_lifecycle_events.py)
  ordering: lifecycle-local sequence, independent of the core sequence that resets to 1 on the cancel path
  a repeat transition emits no duplicate lifecycle event · the projection itself is deterministic
  pause → resume response projects the `resumed` lifecycle event · resume and cancel streams are disjoint
  exactly one terminal lifecycle event per transition
  response backward compatibility: pause/resume/cancel/error shapes and continuation block key sets
  no authority material in the lifecycle stream · audit_event unchanged and consistent with the run events
  expiry observed lazily and idempotently (no sweep, no second terminal state)
DEFERRED
  T13 concurrent cancel race — MERGED (#2891)
  consumer wiring · durable lifecycle history
```

## 8. Lifecycle events (Phase 3)

Phase 3 adds a continuation **lifecycle** stream next to the untouched run event plane. The two planes stay separate
on purpose: `events` keeps carrying the frozen core run events (20 kinds; existing consumers such as
`apps/korean-ai-code-agent/src/kagent/p01_adapter.py` are unchanged), while `lifecycle_events` carries the
continuation transitions.

```json
"continuation": {
  "lifecycle_contract_version": "padiem.engine.agent-continuation-lifecycle/1.0",
  "lifecycle_events": [
    {
      "event_id": "lce_…",           // deterministic: sha256(continuation_id|kind|sequence)[:12]
      "continuation_id": "cont_ref_…",
      "task_id": "orch_run_…",
      "trace_id": "agtr_…",
      "sequence": 1,                  // lifecycle-local, 1-based
      "kind": "cancel_requested",
      "terminal": false,
      "timestamp_iso": "…",           // taken from the run event that evidences the transition
      "derived_from": "store_transition",
      "source_event_id": null
    },
    {
      "sequence": 2,
      "kind": "cancelled",
      "terminal": true,
      "derived_from": "run_events",
      "source_event_id": "evt_…"
    }
  ]
}
```

```text
transitions
  resume   resume_requested -> resumed
  cancel   cancel_requested -> cancelled
  expired  expiration_observed                    (lazy, read-observed only)

derived_from
  store_transition   the transition the coordinator performed (claim / claim_cancel)
  run_events         backed by a core run event (run_resumed / run_cancelled)
  store_record       the persisted record state, when no run event is available
  read_observation   the expiry was observed by a read (no sweep, no timer)

ordering
  each lifecycle event carries its own 1-based `sequence`; the core event sequence restarts at 1 on the cancel
  path, so `sequence` — not `timestamp_iso` — establishes order. A request/state pair may share one timestamp
  because both are derived from the same transition.

exposure
  INTERNAL ONLY. No compatibility guarantee, not an external API promise, no SDK contract. It is published so
  the contract can be observed and tested; treat every field as subject to change.
```

Expiry stays lazy by decision: nothing sweeps continuations in the background, so `expiration_observed` is projected
only when a read observes the expiry (`_get` / `release` / `release_cancel`). A background sweeper, and attaching a
lifecycle event to the expiry 409 (where the failed read leaves no trusted record to name), are both out of scope
for this phase.

## 9. Non-goals

```text
no continuation_id exposure on run responses (Phase 1 decision; the paused-run 202 keeps returning the
  continuation reference it already returned before this contract existed)
no owner identity on cancel responses (Phase 2 decision: no trusted source on that route)
no audit_event expansion (Phase 3 decision: deferred to the durable-audit stage — `actor` has no trusted source
  on the cancel route, and the other candidates duplicate the lifecycle stream)
no durable lifecycle history, no event store (deferred to consumer adoption; the D1 continuation adapter exists
  but stays unwired)
no lifecycle events on error responses (an expired read has no trusted record to name)
no consumer wiring, no Claw/Chat surface
no durable continuation history, no new storage, no migration
no preview wire, no production deployment
```

## 10. Rollback

Additive projection plus a response-assembly hook: reverting the change restores the previous response shape. The
continuation store, its CAS semantics, the resume flow and the authorization rules are untouched, so no data
migration or core rollback is involved. The Phase 3 lifecycle stream is additive in the same way: removing the
projection removes the two keys and leaves every other block byte-identical. Production rollback continues to use
the deploy gate with an explicit `rollback_version_id`.
