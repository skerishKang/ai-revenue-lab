# PADIEM Phone — mock-first outbound voice task surface

Status: **LOCAL SIMULATOR ONLY / NOT READY FOR PRODUCTION**

This folder contains a small, provider-independent phone-task prototype. It has **no SIP, DTMF implementation, PSTN callout, billing, microphone, LLM invocation, or production authentication**. An offline loopback preview makes the task lifecycle, reusable script entry, history and simulated usage reviewable without external credentials or cost.

## Run locally on Windows

```powershell
cd apps/padiem-phone
python server.py 8765
# open http://127.0.0.1:8765/
```

The preview binds to `127.0.0.1` only and rejects unexpected Host and cross-origin requests. **Mock task history** persists outside the Git worktree at `%LOCALAPPDATA%\PadiemPhonePreview\mock_tasks.json`; incomplete simulations are marked `INTERRUPTED` after a server restart, not fabricated as successful completed calls. The demo script library persists at `%LOCALAPPDATA%\PadiemPhonePreview\scripts.json`. Both files are local-only test records, not a shared enterprise/customer database. Do not deploy `server.py` publicly. Never enter real phone numbers, confidential conversations, login data, or customer records into this development preview. Remove both files to reset demo state; never commit them.

## Tests

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
python tests/browser_smoke.py  # optional: local installed Playwright + Chrome/chromium
```

Standard library only for core runtime and HTTP tests. Optional Playwright browser smoke script is separate.

## API contracts (mock only)
- `POST /api/tasks`: `{request_id, source, destination, goal, scenario, script_id?}`, where source is `web` or `claw`, scenario is `standard`, `extended`, `no_answer` or `verification`. When a script ID is provided, the server verifies it against a saved/built-in script and snapshots its questions and constraints into the new mock task; client-supplied mismatched text is rejected.
- `GET /api/tasks/:task_id`: state and simulated usage.
- `POST /api/tasks/:task_id/cancel`: cancel, freeze elapsed mock time.
- `GET /api/tasks`: in-process list.
- `GET /api/usage`: simulated aggregate counters.
- `GET /api/usage/stages`: derived aggregate per-phase simulated minutes and entries. Never provider minutes or billing.
- `GET /api/tasks/:task_id/timeline`: stages reached by a mock task, each explicitly simulation-only. Not a carrier event log.
- `GET /api/tasks/:task_id/report`: bounded Korean UTF-8 text/plain report labelled simulation-only with zero actual calls/charges. No actual transcript, recording or live consultation evidence.
- `GET /api/scripts`: built-in and saved custom demo script library.
- `POST /api/scripts`: add bounded `title`, `destination`, `goal`, `questions`, `notes`.
- `PUT /api/scripts/:script_id`: update a custom demo script using its revision (409 on stale version).
- `DELETE /api/scripts/:script_id`: remove a custom demo script using its revision. The built-in sample scripts are immutable.

The phone UI supports creating, updating, deleting and reusing scripts. Task history detail views expose the snapshot of questions and notes that existed when a task was created; subsequent script changes do not rewrite task history. The detail view also offers the stages reached so far and a download of the explicit mock-only report as .txt. The Usage page shows simulated stage time breakdown. On browser reload, an in-progress local mock task is rediscovered from the same server-side task ID without creating a second task.

`request_id` enforces at-most-one task creation for repeated matching requests. A conflicting request with the same ID returns 409. There is a hard maximum of 100 locally retained mock tasks in this prototype (including saved history). No billing or real outbound call can be triggered from any of these endpoints.

## Product boundaries
- The phone page is a **separate app** so a future independent web entry can reuse the same call service.
- "Claw" in the request source selector is **a simulated integration path only**. An importable `ClawPhoneTaskBridge` in `phone_tool_bridge.py` now defines `start_mock` / `status` / `cancel` for future P01 registration, but **it is NOT registered in B54/P01/Engine**. By default, it always returns 403 unless the existing canonical server authorization is explicitly injected by a trusted host. Scope isolation is an in-process mock proof only; cross-device/durable tenancy remains unimplemented. Do not expose this bridge as a production tool or bypass the Core tool authorization layer.
- Actual shared phone service authentication, canonical owner/workspace persistence, durable work queue, provider adapter, cost controls and end-to-end operational evidence remain future work. The local demo persistence is not a replacement for PADIEM's existing authenticated history/tenant authority.
- Vendor telephony/media capability should be reused from maintained official SDKs (e.g. SIP and agent frameworks) when live service integration is approved. This prototype **does not replace** LiveKit or DIDWW.

## Scope of public development
This code only documents implementation contracts and generic simulated workflows. Commercial positioning, proprietary customer segmentation, prices, business plans and private operating decisions belong to a separate private governance workspace and must not be copied into this repository.

## What was verified
- Deterministic Python task state, script persistence/revision/conflict, scoped tool bridge and idempotency tests
- An actual Python subprocess restart smoke with temp local data verifies unfinished tasks become `INTERRUPTED`, and local mock data survives restart.
- In-process HTTP endpoints, unknown-path protection, report/timeline/usage projections, static files, loopback binding, and no external calls
- Browser behavior is a separate smoke check, not proof of production service

No GitHub Pages / Cloudflare / customer release is implied by this prototype.
