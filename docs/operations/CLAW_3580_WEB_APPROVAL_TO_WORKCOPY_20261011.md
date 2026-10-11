# WEB-FIRST Hark — P01 owner approval to private XLSX workcopy (#3580)

Status: SOURCE-ONLY; not authorized for Production activation or customer-file processing.

## Bounded processing contract

1. Signed-in owner selects an immutable browser-uploaded XLSX and starts the existing Engine P01 continuation. B62 validates owner, CP workspace, original document, SHA-256, running Claw run and unexpired approval pause.
2. Browser posts **only** `{"decision":"approve"}`. B62 reserves one D1 decision receipt, sends one authenticated Service Binding request to fixed Engine `/internal/v1/tools/resume`; the Engine validates its own durable Core ToolRuntime pause and independently checks owner consent. No second approval or replay.
3. New backend consumer requires exact `tool:padiem:web-xlsx-confirm@1` completed tool, `p01_intent_confirmed=true`, no workcopy/read claimed by the Engine tool itself, and exact internal original SHA from the Core result. B62 must match that digest to the persisted owner run/selection **before** committing confirmed decision.
4. **Only after** confirmation is durably committed, the private R2/D1 store performs an additional owner/workspace/source/expiry preflight and exact scoped verifier. A fresh R2 byte read checks original SHA-256 again, and a separate private object plus D1 metadata row is written under owner/workspace/run/source identity. Original R2 bytes remain untouched. New-object rollback on D1 insertion failure is independent of original.
5. The authenticated owner GET P01 status reads the existing D1 decision and, only on `confirmed`, queries exactly one current owner/run/source-scoped workcopy metadata receipt. It returns a workcopy document ID (not R2 key/grant/Engine pause); it does **not** claim the modified XLSX, PDF, preview or Drive delivery exists.

## Gates and failure behavior

- Default: `web_xlsx_p01_workcopy_after_grant_enabled=False`. Trusted B62 Worker sets it true **only** when `PADIEM_WEB_XLSX_WORKCOPY_AFTER_P01_ENABLED=true`, runtime `b14`, an actual verified Engine owner-decision client, and real D1/R2 storage are present. Existing independent Engine/P01/owner-decision/durable-D1 activation gates are also required.
- No flag activation, Production deployment, Production D1 migration, Secrets, model or Drive WRITE in this source PR.
- Denial: no source content read or workcopy. Mismatched/absent Engine SHA: one-shot reservation stays dispatching, never copied, never auto-retried. R2 SHA failure or D1 copy insert failure: confirmed intent may exist, but copy is **not** reported ready; GET is read-only and the incident requires operator-safe reconciliation. No automatic repeated Engine continuation or copy.
- This code is not a generic workcopy-by-ID route. A browser cannot supply Core grant, callback, source fingerprint, engine tool args or arbitrary file path.
- **Unfinished:** genuine Production flag/operator release and same-session canary; deterministic XLSX edits, supported-fidelity PDF, owner-scoped downloadable artifact/UI cards and authenticated mobile/desktop end-to-end. Keep #3580, #3933, #3936 and parent #3928 OPEN.

## Source tests

`python -m pytest -q tests/test_3580_web_xlsx_approved_copy_wire.py tests/test_3580_web_xlsx_approved_workcopy.py tests/test_3580_web_xlsx_p01_owner_decision.py tests/test_3580_web_xlsx_engine_transport.py`

All tests use generated synthetic XLSX, private memory R2/D1 simulator and mocked authenticated Engine response. Do not label them Production E2E.
