# PC read latency review — 2026-11-05 (pc_read over the PADIEM connector)

One `pc_read` from the external connector took 22–30 s on 2026-11-05 evening even for a 17 KB file on an idle PC. This note records what the chain is, where the seconds went, what was changed (all merged and deployed the same night), the measured effect, and what is still open. Numbers are from the COM2 journals (`padiem-chat-com2`, `padiem-p01`, `padiem-oracle-mesh-executor`) and the Chat `/api/mcp` timing line.

## The chain
connector → Chat `/api/mcp` (OAuth token → identity RPCs → P01) → P01 engine (admission → PC-files handler: context → dispatch → `command_status` polls → result) → queue (COM2 loopback) → executor (kagent) → MeshCentral → PC agent → executor → Chat result route → P01 → Chat → connector.

Hard limits: Chat→P01 transport 30 s; the handler waits up to 14 s (`PC_FILES_WAIT_SECONDS`, anchored at handler entry) and otherwise hands back a `job_id` for continuation.

## Baseline (21:30–21:35 KST, after #6951 added `identity_rpc_slow` lines)
| read | total | Chat identity | P01 | P01 admission | P01 core |
|---|---|---|---|---|---|
| COM1 | 25.9 s | 5.7 s (5 RPC) | 20.1 s | 6.3 s | 13.2 s |
| CGI-1 | 27.3 s | 7.8 s (5 RPC) | 19.4 s | 3.2 s | 15.6 s |
| COM2 | 22.1 s | 0.4 s (cache hit) | 21.6 s | 4.0 s | 17.1 s |

Where the time went:
- Chat identity: 5 RPCs per request (`resolve_current_auth_session` ×2 for two products, `resolve_auth_session` ×2 uncached, `resolve_connector_owner_scope`), 0.4–3.4 s each.
- P01 admission: two Control Plane RPCs; a new TLS connection cost ~2 s (2,672 ms cold vs 635 ms warm, keepalive expiry 60 s).
- Handler polls: each P01→Chat internal call paid an uncached `resolve_product_user_for_subject` (0.4–5 s) — 8–11 per read — so polls ran every 2.4–4 s instead of 2 s.
- Executor: dispatch pickup 4–8 s (idle long-poll gap up to 8 s), PC read 4.5 s (two MeshCentral logins: reparse guard `runcommand` + `download`), result submission 3.0–4.5 s (posted to the public hostname through the edge from the same machine, new TLS context per request).
- Identity Worker: single Durable Object, every RPC = replay write + read; `resolve_current_auth_session` filtered/sorted all of a subject's sessions in Python; `resolve_connector_owner_scope` ran 8 queries, 3 duplicated.

## Changes (all merged to `main` and deployed 2026-11-05/06)
| PR | Where | What |
|---|---|---|
| #6951 | Chat | `identity_rpc_slow method= ms= outcome= request_id=` journal line (threshold env, default 250 ms) |
| #6956 | P01 | admission client keepalive 60→300 s + 45 s keep-warm request |
| #6957 | identity Worker | session selection in SQL with LIMIT 1 + index; owner scope 8→5 queries; DO init skips DDL when schema is current |
| #6959 | executor | result lane over loopback with the COM2 edge proof headers; one opener/TLS context per executor; config `ORACLE_MESH_CHAT_ORIGIN` → loopback; unit drop-in idle poll ceiling 8→2 s |
| #6960 | executor | small-file read in one PowerShell round trip (guard + bytes, length/sha verified, fallback to the two-step path) |
| #6963 | executor | `phase=claimed` / `phase=guard_done` journal markers |
| #6964 | Chat | file tools record the job receipt so `job_id` continuation passes `owns_job_receipt` (it had never passed since 2026-11-04) |
| #6965 | Chat | `resolve_product_user_for_subject` (60 s) and `resolve_auth_session` (20 s) join the identity call cache |
| #6954 | issue | P01→B14 pc-turn-metrics: ledger row never matches → 409 `ledger_pending` retried for 5 s per turn |

## Measured effect
| segment | before | after |
|---|---|---|
| result submission (`submit→submit_ok`) | 3,020–4,520 ms | 186–333 ms (0.3–1.7 s under host load) |
| dispatch → claimed (pickup) | 4–8 s | 0.2–2.1 s |
| PC read, idle PC (CGI-1) | ~4.5 s | 0.58–1.05 s |
| PC read, developer PCs running lanes | ~4.5 s | 5–27 s (host load, not code) |
| P01 admission, warm | 2.6 s (p50) | 1.4–1.8 s; first-of-burst still 2.3–3.7 s (keep-warm under review) |
| identity `resolve_current_auth_session` / `owner_scope` | 1,607 / 1,008 ms avg | ~450 / 459 ms |
| handler poll identity cost | 0.4–5 s per poll | 0 ms after the first context call |
| `pc_read` end to end, CGI-1 | ~26 s | 17.5 s (01:24 KST) |

## Still open (2026-11-06 01:30)
1. `job_id` continuation: ownership now passes; the continuation run calls Chat `mode=context` without a scope claim and is refused `403 pc_scope_required` (the run has a saved scope). Fix in the P01/kagent gateway path (admit the declared plan before `context`, or skip `context` for continuations).
2. Keep-warm effectiveness for the admission client and a matching keep-warm for the Chat identity binding (keepalive 75 s; connector reads are usually further apart).
3. Executor: 1.1–2.8 s between `read_ok` and `submit` is unexplained.
4. #6954 metrics: skip the report when the turn made no model call; attach the same identity headers when it did; back off instead of 50 ms retries.
5. Periodic measurement (every 30 min, one read on CGI-1 and COM2) so regressions show up in a table instead of ad hoc probes.
6. Raise `PC_FILES_WAIT_SECONDS` once the fixed overhead above is confirmed smaller (budget accounting test in `test_6919_pc_files_wait_anchored_at_entry.py`).

## Lessons
- Instrument end to end before changing anything: the four journal lines added that night (`identity_rpc_slow`, `engine_timing`, executor `phase=`, Chat `timings_ms`) found every cause above within minutes each.
- Defects were integration seams between pieces built separately: receipts written by one lane and checked by another, a metrics report waiting for a ledger row that no one writes, two services on one host talking through the public edge, CRLF bytes from a Windows checkout. Each needs a contract test that exercises both sides.
- Measure on an idle PC. Developer PCs that run lanes answer PC commands 10–40× slower and hide the real numbers.
- MeshCentral was not the problem at any point.
