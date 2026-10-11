# Hark #3933 — independent Engine/Core XLSX WRITE ToolSpec

**2026-10-11 KST — source-only Core authority milestone. Not a Production activation.**

## Implemented

- Independent Engine `APP_ID=padiem-web-xlsx-write-p01`, Runtime `workspace.xlsx.quote.revise_workcopy`, canonical tool `tool:padiem:web-xlsx-quote-write@1`; ToolSpec `side_effect=WRITE`, `approval_policy=USER_CONFIRMATION`. It does **not** reuse `workspace.xlsx.confirm_original_read`.
- Exact owner/workspace/run/selection/original SHA/workcopy SHA/immutable edit digest ToolInvocation constructed from a **server-only** `TrustedQuoteWriteScope` and `D1WebQuoteWriteScopeResolver`. The resolver checks private B62 D1 unique `dispatching` claim from migration 032, owner-confirmed original READ receipt (different approval), original and private workcopy metadata/key/expiry, active running owner job, and digest of actual school name and supply amount. No client callback, URL, approval bit, workcopy path or bare model arguments may issue the authority. No Engine R2 read or original overwrite.
- Core tool handler rechecks the same D1 identity AFTER a confirmed execution and emits an exact scope-bound `core_tool_completed` acknowledgment with `pdf_exported=false`. This is confirmation only; the separate B62 R2 XLSX writer remains distinct.
- Engine `ToolExecutionEngineService` blocks resuming this separate WRITE app when no independent owner-approved WRITE grant has been installed, including **denied** and **approved** states; it checks canonical agent/tool, requires first-party verifier with a durable Engine pending-tool store to configure such a grant, and grants only the new WRITE runtime ID. Existing READ P01 grant cannot reach it.
- Source-level Engine tests use synthetic B62 private D1 and check exact Core pending-user-confirmation behavior, independent identity and D1 expiry, owner/foreign/tamper/READ-only/extra-fields guard, default-off registration, and Engine rejection without a durable separate WRITE owner grant.

## Not implemented / not a completion claim

**This PR does not provide the actual signed-in owner WRITE decision receipt tied to the new Core pause ID or real private Engine-to-B62 WRITE continuation client.** The previous browser "save" is a reservation of a proposed edit, **not independently verified consent for WRITE**. The Engine resume guard intentionally refuses all WRITE attempts unless a separate verified callback/durable store is composed by the privileged host; that callback is NOT wired here. Current B62 `web_xlsx_quote_write_enabled=False`, `web_xlsx_quote_write_client=None`, and Production Engine app registration remains OFF.

Thus the end-user cannot yet use this feature in Production; no real XLSX revision is authorized under this milestone. No changes to Production D1 schema, flags, Secrets, Cloudflare bindings or customer files. PDF conversion, artifact cards and complete signed-in browser E2E remain open.

## Remaining

1. Add a new signed-in **WRITE-specific owner decision** durable D1 receipt tied to Core pause/digest and canonical `edit_sha256`, with explicit yes/no after preview. It must be separate from original READ P01 decision.
2. Add hardened Engine D1 continuation store for this app, first-party owner WRITE receipt verifier matching pause/digest and D1, and exact private B62 Engine client. Complete challenge/resume/end-state atomic/unknown-outcome reconciliation. Only then consider opt-in activation after migrations.
3. Add supported accurate Excel-to-PDF renderer and verified XLSX/PDF downloads/cards + real user E2E. Keep #3928/#3933/#3936 OPEN.

Source tests: `apps/padiem-ai-engine/tests/test_3933_web_quote_write_core.py`.
