# Hark WEB-FIRST: browser WRITE P01 pause→owner decision→revised XLSX

**2026-10-11 KST — Source implementation, default OFF.**

This milestone bridges previously merged 032 immutable edit reservations, 033
independent WRITE owner decision D1, and the independent Core WRITE ToolSpec
introduced by #4294. It is NOT the same as original READ P01.

## Implemented source

- B62 **migration 034** `claw_web_xlsx_quote_write_pauses` persists a unique
  owner/run/workcopy/edit-scoped WRITE Core pause and continuation. A
  `dispatching` record is INSERTed before a private Engine request. The
  write request cannot be retried after timeout or unknown response.
- Owner-authenticated Hark `POST /quote-edit/request` accepts ONLY school,
  supply and exact `edit_sha256`, validates live original READ owner/run and
  signed private R2 workcopy bytes and XLSX shape, reserves the exact edit and
  WRITE pause, then calls the fixed private Engine ToolRuntime `/execute`
  using the existing operator-managed P01 Service Binding caller. Returns
  public-safe `waiting_p01`; no browser-visible Core continuation.
- Hark `POST /quote-edit/decision` accepts **only** explicit
  `{"decision":"approve"}` or `{"decision":"deny"}`. The server rechecks
  same-owner/run/private pause/expiry, reserves a separately scoped owner
  WRITE consent row in 033 BEFORE dispatch, submits first-party Core
  decision with server-held pause/continuation, and consumes once. A
  denied or unverifiable Engine result never writes a workbook.
- For independently verified Core completion and matching owner/run/original
  SHA/workcopy/edit digest, B62 recomputes and rechecks original R2 bytes,
  uses existing #4289 private XLSX revision writer and owner D1 revision
  receipt, retains source immutable and returns owner-only XLSX download.
  Unknown Engine, D1 or R2 outcome is never automatically replayed.
- Hark browser exposes a **separate second click** "수정된 XLSX 저장 승인"
  and a distinct "파일 수정 거절"; a pause alone cannot display a download.
  Private owner-only GET `/quote-edit/approval-status` rehydrates waiting
  decision on refresh and exposes no Core pause/ref. Revisions use existing
  validated `/quote-edit/status` and `/quote-edit/download`.
- Engine **migration 0010** creates a separate WRITE D1 pause table rather
  than widening the old READ D1 schema. The new WRITE ToolInvocation is
  independently persisted with CAS and resume works across worker instances.
  Dual-store dispatcher prevents confused READ/WRITE scopes.
- Engine Worker binding registration requires all explicit operator flags:
  `PADIEM_WEB_XLSX_QUOTE_WRITE_ENGINE_ENABLED`,
  `PADIEM_WEB_XLSX_QUOTE_WRITE_DURABLE_ENABLED`,
  `PADIEM_WEB_XLSX_QUOTE_WRITE_OWNER_DECISION_ENABLED`, plus existing
  private B62 D1 and READ P01 durable binding.
- B62 Worker client composition requires operator flag
  `PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED`, existing READ decision and
  workcopy-after-grant flags, private D1 032/033/034, R2 and trusted P01
  Service Binding. All OFF/None unless an operator deliberately enables
  the complete chain after migrations and real account testing.

## Validated locally (synthetic documents)

- Two-phase signed-in server path: explicit approval, denial, one-shot replay,
  forged Engine grant rejection, original source preserved and XLSX download.
- Genuine Engine Core WRITE pause+resume across distinct D1-backed service
  instances, independent owner D1 033 grant, immutable invocation SHA,
  denial and missing/foreign owner D1 consent blocked, consumed replay.
- Fixed private Service Binding client request/response contract and refusal
  of spoofed READ ToolRuntime. Actual shipped browser JavaScript exercised
  by Node against mocked private server and verifies the separate click.
- Tests do **not** constitute deployed production E2E or actual remote
  Service Binding requests. No customer files or real financial data used.

## Still blocked / separate acceptance

- Migrations **B62 032/033/034** and **Engine 0010** have NOT been applied to
  Production by this PR; no operator secrets, flags, production Cloudflare
  Worker deployment or real owner account execution changed.
- **PDF is still unsupported.** Existing B66 certified PDF renderer is a
  *PDF-native approved template* overlay, not generic XLSX fidelity export.
  Do not mislabel an invented PDF as an Excel-identical output. Implement a
  supported-template print renderer and compare its actual fonts, merges,
  images and multi-page pagination before owner-only PDF delivery.
- Need live signed-in #3936 end-to-end browser acceptance and same-thread
  Hark artifact card #3932 after operational rollout. Keep parent #3928
  and #3933 OPEN until these prove finished.
