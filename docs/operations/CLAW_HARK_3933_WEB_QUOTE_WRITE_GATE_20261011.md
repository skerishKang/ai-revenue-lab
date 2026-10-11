# Hark WEB-FIRST #3933 — XLSX edit WRITE-gated revision and file delivery

**Status: source implementation / NOT an activated Production P01 WRITE tool.** This document is an explicit implementation boundary. Do not mark #3933 or parent #3928 complete.

## What is wired in source

- After a signed-in owner's original XLSX is independently READ-confirmed by Core/Engine and a private R2 workcopy exists, the existing Hark quote-edit preview computes the exact changed values and deterministic `edit_sha256`.
- Browser shows a **separate, explicit WRITE/Save button ONLY** if the trusted operator-owned B62 composition enables `web_xlsx_quote_write_enabled` and supplies a separately verified `confirm_exact_write` client. Both are **OFF/None** by default. User-controlled browser fields and the prior READ confirmation cannot enable either.
- On POST to `/api/claw/office/web-selections/{selection_ref}/quote-edit/commit`, B62 verifies owner/session, source/selected file, confirmed READ decision, exact workcopy D1/R2 bytes and SHA, the still-running same-owner Claw run, and the canonical edit SHA. The POST accepts only `school_name`, `supply_amount`, and `edit_sha256` (no client grant, file paths, tool args, Engine URL or callback). Unsupported templates fail closed.
- **Before** any external Engine WRITE call, a unique owner/run/selection/source/workcopy/edit D1 row is INSERTed with `dispatching`. Duplicate, timeout, unknown, rejected or unavailable Engine responses leave that row consumed; there is no automatic POST replay. Separate Engine proof must assert a completed Core EDIT/WRITE tool and match ALL exact owner, workspace, run, source ID/SHA, workcopy ID/SHA, immutable edit SHA and operation `xlsx.quote.revise_workcopy`. READ proof is not accepted.
- Only after a matched trusted WRITE confirmation does the already-reviewed `WorkspaceDocumentStore.create_authorized_web_quote_revision` read/re-verify the private workcopy and write a distinct revised XLSX to private R2 and D1 metadata; the original and original-byte workcopy are never overwritten. A final compare-and-set commit persists the revised XLSX ID+SHA in the new owner D1 receipt. If saving or receipt commit fails, the state is **unknown/dispatching**, never a claimed successful file; operator must reconcile.
- Authenticated GET `/quote-edit/status` can read the owner-scoped durable receipt; GET `/quote-edit/download` also validates current owner/session/READ receipt, exact revised object key path, D1 metadata, source/run/copy relations, R2 revision SHA and XLSX media type. No arbitrary R2 document ID is accepted from a browser. The signed-in UI can rediscover the revised XLSX download link on refresh.
- D1 schema: `apps/padiem-chat/migrations/032_claw_web_xlsx_quote_edit_receipts.sql`. It has **not** been applied to Production by this PR. Do not activate WRITE until schema is provisioned and independent Engine ToolRuntime permission exists.

## What is NOT implemented and must NOT be implied

- **No genuine Core/Engine P01 EDIT/WRITE ToolSpec, durable Engine pause/first-party decision grant or Cloudflare production Service Binding client is installed in this change.** Tests inject a separately trusted *synthetic* Engine completed-write response and verify the B62 consumer refuses false READ or mismatched receipts. The in-code check of a synthetic trusted response is not an independent real Engine verification.
- No live Worker flag change, Secrets, migrations applied to Production, customer XLSX, actual Production P01 WRITE, real customer download, XLSX self-service in Production or PDF delivery.
- PDF exporter capable of reproducing original Excel print layout/fonts/images/merged ranges is still unimplemented, so the UI and API say `pdf_exported=false`.
- Model-driven arbitrary workbook edits, auto Drive WRITE, Windows Resident processing, and same-thread agent follow-up are still out of scope.

## Remaining milestone for full product

1. Implement and test a **distinct** Core/Engine P01 WRITE ToolRuntime registration and durable one-shot Engine continuation. Verify against canonical B62 D1 receipt independently via fixed trusted Cloudflare bindings. Do not reuse previous READ tool or accept bearer browser grants.
2. Add operator-owned B62 Engine WRITE adapter + explicit independent enablement only after Production D1 032 and Engine readiness. Verify actual account-bound signed-in WEB execution.
3. Validate PDF-fidelity renderer on supported XLSX templates and expose only approved PDF; then inspect downloaded XLSX and PDF in real browsers on mobile/desktop.
4. Final owner artifacts, conversation follow-up and exact production E2E for #3928/#3932/#3933/#3936. Keep those issues OPEN.

## Source evidence

Targeted B62 synthetic Python tests: `test_3933_web_quote_write_gate.py` plus original READ/P01/workcopy/XLSX editor/preview/acceptance suites.
Shipped JavaScript exercised in `web_xlsx_p01_owner_ui_node.js`: one explicit click, no retry, no browser grant, owner-only revised download and D1 status readback. All tests use synthetic XLSX and provider ports, not a Production execution.
