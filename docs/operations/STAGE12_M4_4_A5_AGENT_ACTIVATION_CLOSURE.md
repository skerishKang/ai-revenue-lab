# Stage 12 / M4-4 — A5 Agent Activation FINAL Closure Record

```
PROJECT=skerishKang/ai-revenue-lab
STAGE=12  MILESTONE=M4-4  ISSUE=#2786 (E9 A5-Agent)  PROGRAM=#1743  PARENT=#1753
STATUS=FINAL CLOSED
SCOPE=documentation only — no code, no workflow, no deploy, no secret, no Cloudflare mutation
```

## 1. Final status

```text
M4_3_CAPABILITY_PROMOTION=COMPLETE
M4_4_DEPLOY_GATE=COMPLETE
M4_4_CANARY=PASS
A12_PROVIDER_INDEPENDENCE=VERIFIED
PRODUCTION_IMPACT=ZERO
M4_4_COMPLETE=FINAL
STAGE12_STATUS=COMPLETED
```

## 2. Evidence

| Item | Value | How it was read |
|---|---|---|
| `origin/main` | `026d083e46a63d5e9cc3a95906de9f77a0592599` | fresh fetch + `rev-parse` |
| main head subject | `feat(#2786): make the A12 stream-replay gate provider-independent (#2884)` | `git log -1` |
| capability ledger | `agent_runtime_projection = AVAILABLE` (`apps/padiem-ai-engine/app/contract_manifest.py:217`) | `git grep` on main |
| A12 classifier on main | `_classify_upstream_skip` present in `scripts/a12_stream_replay_production_smoke.py` | `git grep` on main |
| Production served version | `fe65ac2d-6c43-4968-8f16-878deedb52b9` | GET-only `wrangler deployments list` |
| Rollback target | `8349dc55-4f12-4ad2-8123-7e592dc3a9f3` (still selectable; 10 deployments visible) | same listing |
| Final canary | `B54 Engine Production Smoke-Only Gate`, run `35646244922`, `workflow_dispatch`, head `026d083e` — **success** | `gh run view` |
| canary preflight | `ENGINE_ACTIVE_VERSION_ID=fe65ac2d-6c43-4968-8f16-878deedb52b9` (matches the expected served version) | run log |
| canary stages | A9 `success`, A10 `success`, A11 `success`, A12 `success` | run step conclusions |
| A12 verdict | `A12_STREAM_REPLAY_SMOKE=PASS EXACT_1_REPLAY_EVENT=PASS REPLAYED_FLAG=PASS CONFLICT_409=PASS` | run log |
| A12 evidence line | `A12_REPLAY_EVIDENCE=PASS EXACT_1_REPLAY_EVENT=PASS REPLAYED_FLAG=PASS CONFLICT_409=PASS` | run log |
| Contrast: pre-change deploy gate | run `35641570110` (main `7ba03a8c`): deploy job success, A9/A10/A11 success, **A12 failure** → run failure | `gh run view` |

## 3. M4-3 — capability promotion

`agent_skill_runtime` was promoted to `AVAILABLE` on main (#2883) and the exact-main revision containing it was
deployed. The capability plane and the engine contract feature plane stay distinct: the promotion is an
explicit, single-capability change, and `skill_runtime_projection` was deliberately left `DEFERRED`.

## 4. M4-4 — production activation

The `B54 Engine Production Deploy Gate` deployed the exact-main revision. The served version moved to
`fe65ac2d…`, the deploy job passed, and the rollback branch stayed untouched (no rollback needed). The
rollback target for any future rollback remains the previous served version `8349dc55…`, and the gate still
refuses an unnamed rollback target.

## 5. A12 provider independence — why it changed

```text
BEFORE  provider 5xx -> A12 FAIL -> the whole activation gate blocked on one external model's availability
AFTER   provider 5xx (Engine-preserved error.metadata.upstream_status_code) -> SKIPPED_UPSTREAM (recorded)
        Engine 5xx / 4xx auth or contract / idempotency / S3 conflict / S4 D1 mismatch -> FAIL
        S0 (health + manifest) and S3 (conflict) are mandatory and provider-independent
        S4 is evaluated only when an execution happened; a skipped run records NOT_APPLICABLE, never a pass
```

The gate was not relaxed: responsibility was separated. The pinned provider model is retained with no silent
fallback, so a provider outage is recorded rather than converted into a pass. Full rule:
`docs/operations/A12_STREAM_REPLAY_GATE_DEPENDENCIES.md`.

## 6. Final smoke evidence

Run `35646244922` (see §2) passed every stage **including the provider leg**, so A12 reached `PASS` rather
than `SKIPPED_UPSTREAM`. This closes the earlier `FAILED_EXTERNAL_PROVIDER` condition: the provider was
healthy at the time of the run, and the gate would now isolate it if it were not.

## 7. Rollback baseline

```text
SERVED=fe65ac2d-6c43-4968-8f16-878deedb52b9
ROLLBACK_TARGET=8349dc55-4f12-4ad2-8123-7e592dc3a9f3
PATH=dispatch `B54 Engine Production Deploy Gate` with an explicit rollback_version_id
NO ROLLBACK REQUIRED at any point in this milestone
```

## 8. Decision: preview lane retained (Option A)

```text
DECISION=KEEP_AS_INTERNAL_VALIDATION_LANE
WORKER=padiem-ai-engine-preview   (6 deployments, first 2026-09-21T17:36:53Z)
```

Retained under these documented conditions (as built — the full model is
`docs/operations/PREVIEW_AGENT_PILOT_LANE.md`):

```text
PREVIEW_ROLE=INTERNAL_ONLY
ENGINE_LANE_PUBLIC_ACCESS=NONE       (padiem-ai-engine-preview: workers_dev = false, no route, no public URL)
ENGINE_LANE_PRODUCTION_BINDING=NONE  (no services, no D1, no KV/R2, no Production binding inherited)
ENGINE_LANE_STANDING_SECRET: none    (the preview engine lane holds no standing secret)
PILOT_CALLER=EPHEMERAL               (a dedicated caller worker exists only during a pilot dispatch)
PILOT_CALLER_PUBLIC_ACCESS=WORKERS_DEV_DURING_RUN  (the caller worker is workers.dev-routable while the run lasts)
PILOT_REGISTRY_SECRET=EPHEMERAL      (a caller-registry entry is injected into the preview worker for the run
                                      and deleted by the teardown step)
PILOT_TEARDOWN=AUTOMATIC             (final workflow step `Teardown preview caller and ephemeral secret`, if: always)
```

Rationale: the standing lane costs nothing at rest, keeps a production-separated surface for future agent-runtime
validation, and removes the risk of an improvised lane being built later. The pilot path that exercised it (Stage
11-C M3-3.5: #2879, with follow-ups #2880–#2882) provisions an **ephemeral** caller worker and an ephemeral caller
registry entry for the duration of one dispatch, then deletes both; the standalone engine lane itself keeps no
caller, no secret and no public route. Retiring the lane (Option C) remains available at any time and would require
a separate, explicitly authorized Cloudflare mutation.

## 9. Known follow-ups

| # | Follow-up | Status | Owner / notes |
|---|---|---|---|
| 1 | A12 external provider availability tracking (pinned model) | DOCUMENTED — separate low-priority issue recommended | Ops · monitoring only · no production mutation · not an activation blocker |
| 2 | Preview lane lifecycle | **DECIDED — retained (Option A)** under §8 conditions | revisit only if a pilot caller is provisioned or the lane is retired |
| 3 | Records: #2786 FINAL status, #2876 E9 activation-plane reconciliation, this closure doc | this document is item 3's docs landing | issue records are separate, explicitly authorized writes |

## 10. Explicit non-claims

```text
- The A12 provider-leg result is point-in-time (provider healthy at 2026-09-21T19:40Z). A later outage
  records SKIPPED_UPSTREAM, which is the intended behaviour, not a regression.
- REFERENCE_AGENT_SLOT_GRANT_PRESENT / REFERENCE_ACTOR_AUTHORITY_PRESENT were never read (D1 row data,
  user-data adjacent) and remain unverified.
- The preview lane has never served a pilot call; its execution capability is proven in-process only.
- No claim is made about provider SLAs, and no capability other than agent_runtime_projection is claimed
  active.
```
