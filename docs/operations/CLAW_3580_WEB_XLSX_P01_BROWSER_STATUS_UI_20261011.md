# #3580 Hark WEB-FIRST — Browser P01 owner decision UI / server truth

**Date:** 2026-10-11 KST. Source implementation and local tests; not a Production deployment.

## Scope

- The existing Hark chat `index.html` web Office panel now has a separately labeled `P01` status panel and **원본 확인 승인 / 거절** buttons. The panel is `hidden` by default; buttons are both `hidden disabled` by default. The existing XLSX upload and immutable source selection remain available without Windows Resident.
- The owner-scoped **GET** `/api/claw/office/web-selections/{selection_ref}/p01-status` re-reads B62 private D1 selection, P01 request, and the one-shot decision receipt, and—only on `waiting_p01`—rechecks the authenticated owner/workspace, original immutable document SHA/name/size, and a recent running conversation-linked Claw run. Response exposes **only** selection/document/source SHA, display filename and size, stage, booleans. It never exposes internal Engine pause/run/continuation references, proof/credentials, tool arguments or a grant.
- The eight explicit server statuses are `not_requested`, `request_unknown`, `waiting_p01`, `decision_unknown`, `confirmed`, `denied`, `expired`, and `manual_review`. `owner_decision_enabled` is **true only** with an unexpired, verified, owner-bound `waiting_p01` Engine pause **and** an explicitly configured private owner decision client. Inability to query D1, corrupted owner receipt, stale run, expired or mismatched source disables both buttons. Status is no-store, safe to refresh, and cannot mint a pause.
- Browser code `static/claw-web-xlsx-sources.js` now validates that status response against the **currently selected immutable owner XLSX**. It renders buttons only when the server returns exact `waiting_p01` plus `owner_decision_enabled=true`; sends **only** `{"decision":"approve"|"deny"}` to the #4258 POST route. It re-reads **GET** status after a decision. One POST attempt per selection is retained in page memory, including transport timeouts; no automatic retry, no switch from approve to deny and no submission of browser-created SHA/grants/Engine identifiers. A refreshed page can only act if a trusted current D1 response permits it.
- The existing source list remains usable if *separate selection history* is unavailable. Previously created server selection entries can be reopened from a verified owner-scoped `GET /web-selections` list. Selection history cannot grant P01 processing permission. No hidden auto-approval, auto-P01 dispatch, background poll, autosubmit, local PC or Drive write.

## Proven local behavior

- Actual ASGI + real SQLite B62 migrations (including 029/030/031) owner status tests: not-requested, pending, Engine pause + live owner run, foreign/anonymous 401/404, configured/off client, confirmed/denied persist, uncertain one-shot, expired/changed SHA/deleted original, corrupted owner receipt, and no internal Engine refs in JSON.
- Node executes the **actual static browser script** with a network-free minimal DOM and verifies: pending buttons appear, approve/deny each send exactly one signed-in POST, original decision remains locked after status refresh/revisit, uncertain dispatch never retries, inactive/expired/mismatched states never show controls, and original processing remains false. Node test is discovered and run through the B62 Python pytest lane.
- All modifications are source-only; existing generic Claw approvals and B62 normal chat behavior are untouched.

## Remaining

1. The **start P01 request** endpoint presently requires an existing authenticated running Claw `run_id` and is not yet automatically launched by the new UI; merely selecting an XLSX **does not** start approval. An owner-run binding/selection-to-P01 dispatch UI flow is a separate milestone, not invented by this panel.
2. Cloudflare D1 read-after-write behavior and the independently bound Engine-private B62 D1 must be proven under authorized Production flags before enabling any actual user approval. Migration 031 and earlier prerequisite migrations must be deployed by a separate authorized rollout.
3. `confirmed` means **P01 original-read intent confirmed**, NOT that the workbook was read, modified, copied, made into PDF or displayed as a result. Separate immutable original SHA verification, safe workcopy, XLSX processing and web preview still remain.
4. On an ambiguous one-shot Engine response, leave the decision receipt in an unknown state requiring operator reconciliation; GET is safe to repeat, POST is not.

**Gates:** `WEB_OWNER_DECISION_UI_CODE=YES` / `WEB_OWNER_APPROVE_DENY_PRODUCTION=OFF` / `XLSX_WORKCOPY_E2E=NO`. Keep issue #3580 OPEN.
