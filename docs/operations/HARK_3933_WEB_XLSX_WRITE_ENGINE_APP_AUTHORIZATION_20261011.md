# Hark #3933 — WEB-FIRST XLSX WRITE Engine caller-app authorization

**2026-10-11 KST — source-only readiness change. Not a Production activation.**

## What this change is

The canonical P01 overlay caller authority
(`.github/scripts/b54_engine_caller_registry_overlay_rotation.py`) is extended with
the independent Hark WEB-FIRST XLSX WRITE Engine tool app:

```
allowed_app_ids = ["b54-padiem-claw", "b54-padiem-claw-drive",
                   "b54-padiem-claw-telegram", "b54-padiem-claw-calendar",
                   "padiem-web-xlsx-p01",          # READ  (#3936)
                   "padiem-web-xlsx-write-p01"]    # WRITE (#3933)
```

This is an **app-authorization entry only**. It does not enable WRITE, does not
touch a Production secret, and does not change any approval, scope or
source-verification gate.

## Why it is needed

The Engine authorizes the request-body `app_id` against the caller registry
**before any service runs**:

```
apps/padiem-ai-engine/worker.py:217        authenticate_request(env, headers, requested_app_id=app_id)
  -> app/identity_enforcement.py           authenticate_engine_caller(...)
    -> app/service_identity.py:211         if requested_app_id not in caller.allowed_app_ids:
                                              raise ServiceIdentityError("service_app_not_authorized")
      -> worker.py:225-230                 return 403
```

The Chat WRITE transport
(`apps/padiem-chat/app/web_xlsx_quote_write_engine_client.py:19`) addresses the
same `/internal/v1/tools/execute` boundary as the READ client, but with
`_APP="padiem-web-xlsx-write-p01"`. Both clients share the same caller
(`p01_engine_config_from_worker_bindings` → `config.caller_id`).

With the WRITE app absent from the registry, the Engine answered **403
`service_app_not_authorized`** before `ToolExecutionEngineService` ran, so no
independent WRITE approval pause could ever be created and the whole WRITE path
was unreachable — the same failure class as the #3936 READ defect, one app over.

### Live overlay state at the time of this change

The overlay is only rewritten by a `workflow_dispatch` of the rotation gate with
`mode=apply_overlay_credential_rotation` (PR events run the static contract tests
only). The last actual mutation was **2026-10-02T12:49:51Z @ `572699aa14`**, whose
`ALLOWED_APP_IDS` did not contain either Hark app. The overlay therefore had to be
re-rotated for the READ fix, and must be re-rotated again for this WRITE entry.

## Scope of the investigation (#3933 work order item 2)

| Area | State found |
|---|---|
| Engine WRITE tool binding | **complete** — `web_xlsx_quote_write_tool_binding.py` (separate `APP_ID`, `side_effect=WRITE`, `approval_policy=USER_CONFIRMATION`, server-only scope) |
| Independent P01 WRITE approval | **complete** — `web_xlsx_quote_write_scope_d1.py`, `..._owner_approval_d1.py`, `..._tool_pending_d1.py`, `web_xlsx_dual_tool_pending_d1.py`, and the separate resume guard in `tool_execution_service.py:665-702` |
| Production call authority | **GAP — fixed here** (this document) |
| D1 persistence | **complete at source** — engine migration `0010`, chat migrations `033`/`034`; see the migration-applier note below |
| Chat WRITE execution path | **complete** — `web_xlsx_quote_write_engine_client.py`, `claw_web_xlsx_quote_write_routes.py`, `claw_web_xlsx_quote_approval_routes.py`, `claw_web_xlsx_quote_preview_routes.py`, `claw_web_xlsx_quote_pdf.py`, stores, and route registration in `app_factory.py:424-431` |

Nothing else was missing. No READ/WRITE approval was merged, and no gate was
relaxed.

## What is deliberately NOT changed

- **Approval verification is not relaxed.** Core `USER_CONFIRMATION`, the
  server-only `TrustedQuoteWriteScope`, `verify_exact_source` /
  `verify_exact` preflights and the independent owner-WRITE D1 grant are
  untouched.
- **WRITE stays OFF.** `PRODUCTION_HARK_WEB_QUOTE_WRITE_COMPOSED = False`
  (`web_xlsx_quote_write_tool_binding.py:244`), `web_xlsx_quote_write_enabled`
  defaults `False`, `web_xlsx_quote_write_client` defaults `None`
  (`app_factory.py:610-611`), and the Engine WRITE composition still requires all
  three `PADIEM_WEB_XLSX_QUOTE_WRITE_*` flags (`worker_identity.py:1091-1097`).
- **PDF stays OFF.** `PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED` is unset; the renderer
  stays `None` (`worker.py:990-1003`).
- **READ is not reachable from WRITE and vice versa.** Distinct app ids,
  distinct canonical/runtime tool ids, distinct agent ids and distinct auth
  scopes; the resume guard grants only the app's own runtime tool.
- **No base V1 mutation, no secret value touched, no WRITE/PDF flag enabled.**
- **B14 / B66 / PR #4360 untouched.**

## Verification performed (source-level, local)

| Check | Result |
|---|---|
| `python .github/tests/test_b54_p01_overlay_caller_id_parity.py` | `P01_OVERLAY_CALLER_ID_PARITY=PASS` |
| `python .github/tests/test_b54_engine_caller_registry_overlay_rotation_gate.py` | `B54_ENGINE_CALLER_REGISTRY_OVERLAY_ROTATION_GATE_TESTS=PASS` |
| Engine WRITE + composition + READ suites | 83 passed |
| Chat WRITE + PDF + READ suites | 112 passed |
| New composition test (`test_3933_web_quote_write_app_composition.py`) | 4 passed |
| New PDF 422 test (`test_unsupported_print_layout_is_rejected_not_silently_rendered`) | passed |
| Revert-probe (WRITE entry removed) | both gate tests fail on the expected assertions → the tests are load-bearing |
| Consolidated synthetic E2E (26 checks) | all pass — see below |

Synthetic E2E used school `광주대학교`, supply **99,200,000**, VAT **9,920,000**,
total **109,120,000**; asserted original SHA-256 preservation, formula/style/merge
retention, byte-identical non-sheet ZIP parts, honest `UNSUPPORTED` PDF fidelity
verdict, the certified single-sheet summary layout, and explicit refusal of
SHA mismatch, unsafe school name, non-integer VAT, PDF output requests and rich
(VBA / external-link / extra-sheet) packages.

## PDF honesty contract (work-order item 6)

The summary PDF is a clearly labelled standard quote print, **not** a
pixel-identical Excel workbook. `supported_quote_print_html`
(`claw_web_xlsx_quote_pdf.py:29-93`) certifies only the single supported sheet
(`A1,B4,B5,B6,B7`, one merge `A1:D1`, no print options/page setup/drawings) and
the rendered document states:

> 원본 Excel 서식과 동일한 인쇄본이 필요한 경우 XLSX 파일을 사용하세요.

Anything uncertifiable raises `WebQuoteEditUnsupported`, and the route answers
**422 `web_xlsx_quote_pdf_unsupported_print_layout`** without rendering
(`claw_web_xlsx_quote_pdf.py:143-146`). `revise_single_sheet_quote` likewise
reports `print_pdf_fidelity = UNSUPPORTED_REQUIRES_APPROVED_RENDERER`.

## Remaining Production activation steps (operator-owned)

1. **Apply the durable-table migrations.** The engine provision gate applies only
   `0001..0008`; migrations `0009` (READ continuations), **`0010`
   (`web_quote_write_tool_continuations`)** and `0011` have **no applier in the
   repository**. Confirm the tables exist on the `ENGINE_CONTINUATION` D1 before
   enabling WRITE, or the durable WRITE pause will fail to persist.
2. **Re-rotate the overlay** from the merged exact main SHA with
   `mode=apply_overlay_credential_rotation` so the 6-app authority is actually
   served.
3. **Activate in order**: `engine_write` → `chat_write` → `chat_pdf`
   (`.github/scripts/hark_web_first_runtime_activation.py`), each requiring its
   peer prerequisites. `chat_pdf` additionally requires the `BROWSER` binding.
4. **Run a fresh one-shot live E2E** with a new synthetic XLSX and a new
   selection reference; never retry a consumed selection.
5. Keep #3933 / #3936 OPEN until the live E2E passes.
