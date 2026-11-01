# PC remote limits: runtime wiring (#6460 §5-1)

Branch: `feat/pc-remote-limits-wire-261101`. Code only; deployment and PR remain CTO work.

The branch combines the existing output store, reference-preserving compaction,
background jobs, work metrics and batch runner. It preserves the current PC
owner/device authorization, signed product callback, queue claim/lease/cancel,
action harness and result verification.

## Runtime connections

| Connection | Runtime entry |
| --- | --- |
| Large output | Chat file/drive callbacks use `oracle_mesh_read_return_routes._engine_pc_public_output` after verifying the original result digest, then `QueueForwardingHistoryStore.store_pc_output` uploads it to the authenticated COM2 queue `/internal/store`. |
| Durable storage | Queue `PcOutputStore` uses Core `OutputStore`. Upload parts stay inside the existing RPC body limit; size and digest are checked before publishing a handle. |
| Model observation | Engine `claw_pc_query_step_driver` receives `output_ref` (head, tail, size, handle), not an unbounded copy of the original. Read/search calls use the same signed callback and selected owner/device. |
| Context | Engine `PCContextCompactor` uses Core compaction and the existing model client/model policy. The selected model catalogue supplies the context budget. User/system/developer originals retain their roles and content; archived non-user material can be recalled. |
| Background execution | Signed `job_start` stages an existing reviewed file operation with trusted background metadata. Queue dispatch ID is the job ID. The existing Mesh executor runs `RemoteBackgroundJobs` using its current remote command/read ports. |
| Queue | The 8797 service stages dispatch and background metadata atomically. Selection and claim serialize the same device/node; unrelated PCs can progress. Existing leases, cancellation and result delivery remain authoritative. |
| Batch | Core `pc_batch.run_batch` is injected with actual existing PC handlers and durable output storage. All steps pass evidence/delegation preflight before execution; each executed action retains verification. |
| Measurement | Existing turn collector and B14 reporting include `stored_output_count`, `compaction_count`, `background_job_count`. Schema v2 retains old v1 compatibility without inventing missing historical measurements. |

## Model tools

All names have the `claw.pc.` prefix.

| Tool | Arguments |
| --- | --- |
| `read_output` | `handle, offset, length` (byte ranges) |
| `search_output` | `handle, query` (literal search) |
| `start_job` | `operation: {op, ...existing file arguments}` |
| `job_status` | `job_id` |
| `job_output` | `job_id, offset, length` |
| `batch` | `operations: [{op, ...}], stop_on_error` |
| `recall_context` | `handle, source_id?, offset?, length?` (source text ranges) |

Composite operations are the existing list/read/write/move/delete actions.
They do not accept raw shell commands, nested wrappers or new file permissions.
Dangerous operations retain the action harness and delegation requirements.
Recalled/output content is source material, never a new instruction or grant.

## Persistence and operational behavior

- Output handles are scoped to verified user, subject, run and device. A handle
  alone grants no access.
- Queue output storage defaults to `pc-outputs` beside the existing queue DB.
  Existing `PADIEM_OUTPUT_STORE_DIR` can override this. The queue installer
  preserves this directory when refreshing source; Core's existing retention applies.
- Context originals use the host Engine's existing `PADIEM_ENGINE_LOCAL_DB`.
  An unknown catalogue budget is not replaced with a guessed model context size.
- Background receipts/output live under the executor's existing persistent work
  directory. Recovered completed/interrupted receipts are not re-executed.
- A pending job receipt is not verified completion. The existing remote port
  buffers output, so output becomes available after completion; status, lease and
  cancellation remain available while running.
- Output reads are paged. Bounded previews and search snippets do not delete any
  original bytes.
- No new provider/model, deployment, credential or operational setting is selected
  by this change.

## Validation (2026-11-01, isolated Windows worktree)

| Suite | Result |
| --- | --- |
| Engine integration, native calls, compaction/recall, harness/delegation, verification, metrics, orchestration (18 files) | 597 passed |
| Full COM2 queue suite + Chat remote callbacks, legacy read dispatch and endpoint contract | 159 passed |
| Remote background/batch and existing Mesh executor regressions | 150 passed, 3 skipped |
| Existing Core output-store and compaction tests | 12 passed |
| B14 work-metrics API/store tests | 29 passed |
| Total | 947 passed, 3 skipped |

The three skips are existing Unix pty/termios terminal tests on Windows.
Tests use isolated fixtures/mocked remote ports, not live customer PCs or providers.
The actual callback-to-queue-RPC-to-SQLite/disk path restores a 1.1 MB original
byte-for-byte; Engine tool integration handles a 21 MB stored output.
Coverage also includes same-PC serialization, other-PC progress, lease/cancel,
lost-response retry, immutable operation metadata, wrong-owner refusal,
batch cancellation before the next step and failed/unverified action facts.

Existing registry assertions were expanded to the seven new closed tool IDs.
The internal endpoint test now distinguishes guard-only verified delegation
roots from the public/model projection; model-path non-disclosure tests remain.

Syntax, credential-pattern, LF and git whitespace checks passed. No live
deployment, credential setting, PR or main merge was performed.
