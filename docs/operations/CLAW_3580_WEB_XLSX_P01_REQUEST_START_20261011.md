# #3580 Hark WEB-FIRST — selected XLSX → P01 request start

**Date:** 2026-10-11 KST. Source-only milestone; Production remains OFF.

## User workflow

1. Signed-in owner uploads or reopens an immutable XLSX and selects the exact source.
2. Browser reads owner-scoped P01 status. If the status is `not_requested` and the private server adapters plus owner-run creation are configured, a **P01 승인 요청 시작** button appears.
3. An explicit click sends `POST /api/claw/office/web-selections/{selection_ref}/start-p01` with **exactly `{}`**. No browser owner, workspace, run_id, conversation_id, SHA, Engine tool/continuation/credentials or grants are accepted.
4. Server rechecks selected source owner/workspace, exact immutable original metadata, SHA-256, source expiry, D1 schema and absence of earlier P01 request. It creates an **actual owner-bound conversation and 'running' Claw run** in the existing D1 history (without fake user or assistant messages, without a model request), then invokes the existing canonical `dispatch_owner_web_xlsx_p01` path.
5. One-shot B62 D1 reservation precedes private Engine dispatch. Browser sends this POST **at most once per selection per page lifetime**; on any ambiguous response, it uses safe GET `p01-status` to reconcile and does not retry POST. D1 uniqueness prevents replay even after browser refresh.
6. Once a genuine Engine pause exists, the already merged owner UI displays **원본 확인 승인 / 거절**, with the server-only authority checks of PR #4265.

## Evidence / boundaries

- Actual ASGI + B62 SQLite migrations 029/030/031 test authenticated source/start, foreign owner, bad body, expired/tampered XLSX, missing D1 migration, concurrent/repeated request and unknown Engine dispatch. Actual `D1HistoryStore` tested with migrations 001/002/009/014/015 for a new owner-bound conversation/run and **zero fabricated messages**.
- Actual shipped browser JS executed under offline Node minimal DOM; start is one-shot, post timeout doesn't retry, previous approval and denial behavior remains working.
- **Source metadata only**: this milestone never reads R2 XLSX bytes, creates a workcopy, edits sheets, exports PDF, writes Drive, calls a paid model or invokes Windows Resident.
- `PADIEM_WEB_XLSX_P01_TOOL_DISPATCH_ENABLED`, `PADIEM_WEB_XLSX_P01_ENGINE_SCOPE_ENABLED`, `PADIEM_WEB_XLSX_P01_DURABLE_TOOL_ENABLED`, `PADIEM_WEB_XLSX_P01_OWNER_DECISION_ENABLED` and separately provisioned verified B62/Engine D1 bindings remain operator-controlled and OFF in Production. No Production migration, secrets, deploy or feature enablement in this PR.
- A dedicated `running` run represents a P01 workflow awaiting subsequent phases; it **must not be shown as completed processing**. Follow-up milestone must provide terminal lifecycle and immutable SHA recheck before any workbook read or artifact generation.
- A crash between creating a conversation/run and D1 dispatch reservation can leave an owner-scoped inactive run. This is safe (no grant/file read), but operational reconciliation/cleanup remains an enhancement.

**Gates:** `WEB_P01_START_SOURCE=YES`, `WEB_P01_START_PRODUCTION=OFF`, `XLSX_BYTES_READ=NO`, `WEB_WORKCOPY=NO`, `PDF_PREVIEW=NO`. Keep #3580 OPEN.
