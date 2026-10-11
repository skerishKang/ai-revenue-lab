# #3580 WEB-FIRST — owner-scoped XLSX selection ledger, pre-P01 boundary

**Date:** 2026-10-11 KST. **Actual milestone:** W1.5 / early W2 source-intent capture, **NOT** first-party P01 approval or web Excel editing.

## What changed

- An authenticated owner who previously uploaded an XLSX via W1 (`/api/claw/office/web-sources`) can now select that exact original in the browser, receiving an opaque durable server-side `sel_...` reference.
- `POST /api/claw/office/web-selections` accepts **only** an existing `document_id`. Server derives owner/workspace from its own signed session and canonical authority; does **metadata-only** D1 verification of private original SHA-256, filename, object key scope, byte size and TTL. No R2 read is allowed at selection time. Browser-provided hashes, identities, Engine run IDs, continuation refs and decisions are rejected.
- New migration `029_claw_web_xlsx_selection.sql` saves exact owner+workspace+source ID, original fingerprint, size, filename, bounded 30-minute expiry and status `source_selected_p01_not_started`. `GET /api/claw/office/web-selections` and `GET /api/claw/office/web-selections/{selection_ref}` expose only owner-scoped non-sensitive metadata. Foreign or expired references are non-disclosing 404s. Limit 20 active selections per owner/workspace.
- B62 web interface persists the selected original rather than just assigning a JavaScript variable, and confirms **no P01 approval started, no working copy, no file processing and no Drive write**.
- Production composition uses the preexisting D1 binding + private R2 availability. Absent D1, R2, identity authority, or unapplied migration -> **503 fail-closed**. No mock selection store or fake approval is added to product wiring. Migration deployment requires separate operations approval.

## Why not auto-start P01 here?

The existing `/api/claw/approvals/decision` only resumes a **real previously issued first-party Engine pause**, reconstructing the trusted request from durable server-owned history. A web XLSX metadata selection is NOT an Engine pause; copying a pause from an unrelated Claw run or asking a browser to synthesize trusted approval evidence would violate the existing P01 trust boundary. Selection must stay unapproved until a new Engine-request tool path genuinely issues an exact original-ID+SHA-bound pause.

## Next code milestone: real first-party Engine approval

1. Implement a canonical **web-workspace XLSX READ/working-copy action** in P01 Engine/Core with exact source ID, canonical owner/session/workspace, selection_ref and original SHA-256 ToolInvocation digest.
2. Issue a genuine `ApprovalPause` using the existing P01 Engine continuation machinery, and persist original owner Hark run context in the existing `claw_approval_handoff` owner+workspace durable store. The browser only sends `run_id, decision` to the existing decision API.
3. After **Engine-verified APPROVED** and one-shot continuation consumption, recheck selected source+hash/TTL, then create a **separate** non-destructive working copy; reject denied, replayed, wrong owner/run/source and storage failure.
4. Continue W3 XLSX server edits + fidelity-validated PDF; W4 owner artifacts/preview/download. Windows Resident/Excel COM optional only for explicit local-PC/fidelity fallback; Drive WRITE remains separate explicit consent/OAuth.

Proof at this milestone: `SOURCE_SELECTION_D1_R2_TEST_PASS` only. `P01_WEB_APPROVAL_E2E=NOT_YET_IMPLEMENTED`, `CUSTOMER_FILE_ACCESS=NONE`, `PRODUCTION_DEPLOYMENT=NONE`.
