# PADIEM Phone — mock-first outbound voice task surface

Status: **LOCAL SIMULATOR ONLY / NOT READY FOR PRODUCTION**

This folder contains a small, provider-independent phone-task prototype. It has **no SIP, DTMF implementation, PSTN callout, billing, microphone, LLM invocation, or production authentication**. An offline loopback preview makes the task lifecycle, reusable script entry, history and simulated usage reviewable without external credentials or cost.

## Run locally on Windows

```powershell
cd apps/padiem-phone
python server.py 8765
# open http://127.0.0.1:8765/
```

The preview binds to `127.0.0.1` only. It stores mock task data in memory and discards it on restart. Do not deploy `server.py` publicly. Never enter real phone numbers, confidential conversations, login data, or customer records into this development preview.

## Tests

```powershell
python -m unittest discover -s tests -v
node --check static/app.js
```

Standard library only for core runtime and HTTP tests. Optional Playwright browser smoke script is separate.

## API contracts (mock only)
- `POST /api/tasks`: `{request_id, source, destination, goal, scenario}`, where source is `web` or `claw`, scenario is `standard`, `extended`, `no_answer` or `verification`.
- `GET /api/tasks/:task_id`: state and simulated usage.
- `POST /api/tasks/:task_id/cancel`: cancel, freeze elapsed mock time.
- `GET /api/tasks`: in-process list.
- `GET /api/usage`: simulated aggregate counters.

`request_id` enforces at-most-one task creation for repeated matching requests. A conflicting request with the same ID returns 409. There is a hard maximum number of mock tasks per server process. No billing or real outbound call can be triggered from any of these endpoints.

## Product boundaries
- The phone page is a **separate app** so a future independent web entry can reuse the same call service.
- "Claw" in the request source selector is **a simulated integration path only**; B54 tool registration, account authorization, microphone and production UI wiring are not part of this slice.
- Actual shared phone service authentication, persisted work queue, provider adapter, cost controls and end-to-end operational evidence are future implementation work.
- Vendor telephony/media capability should be reused from maintained official SDKs (e.g. SIP and agent frameworks) when live service integration is approved. This prototype **does not replace** LiveKit or DIDWW.

## Scope of public development
This code only documents implementation contracts and generic simulated workflows. Commercial positioning, proprietary customer segmentation, prices, business plans and private operating decisions belong to a separate private governance workspace and must not be copied into this repository.

## What was verified
- Deterministic Python task state and idempotency tests
- In-process HTTP endpoints, unknown-path protection, static files, loopback binding, and no external calls
- Browser behavior is a separate smoke check, not proof of production service

No GitHub Pages / Cloudflare / customer release is implied by this prototype.
