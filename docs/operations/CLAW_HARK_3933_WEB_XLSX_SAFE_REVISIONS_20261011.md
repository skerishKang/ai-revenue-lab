# #3933 Hark WEB-FIRST — bounded XLSX revision contract (2026-10-11 KST)

## Source scope

- Deterministic, copy-on-write revision of a verified single-sheet quote: merged header `A1:D1`; school name `A1`, integer supply `B4`, constant VAT rate `B5=0.1`, preserved formulas `B6=B4*B5`, `B7=SUM(B4,B6)`. Recompute numeric formula cached values.
- Keep original private R2 object and SHA-256 immutable, write a separate revised XLSX and digest, preserve styles/merged range and other OOXML parts.
- Validate real OOXML content types/relationships/style references, ZIP CRC, size and safety. Unsupported macros, external links, drawings, arbitrary formulas, multiple sheets, PDF layout, or malformed files fail closed.
- Private `WorkspaceDocumentStore.create_authorized_web_quote_revision` requires a **separate exact P01 WRITE grant** bound to owner/workspace/run, source and workcopy refs+SHA and exact edit digest, before any processing R2 byte read; post-authority SHA verification, distinct private R2/D1 revision, new-object-only rollback.

## Not yet connected

- No Hark browser edit action, independent Core P01 WRITE ToolSpec or true runtime execution is wired by this PR. The earlier READ P01 permission must NOT be accepted as a WRITE permission.
- No faithful Excel-to-PDF renderer has been identified. PDF requests fail closed as `PDF_FIDELITY_REQUIRES_APPROVED_OFFICE_RENDERER` rather than invent a document or silently invoking B66's unrelated quote PDF renderer.
- No production deploy, feature activation, customer XLSX, Secrets, model, Drive WRITE, or Windows Resident usage. No XLSX/PDF output card, preview, download, follow-up or authenticated product E2E is claimed.
- Keep #3933, #3580, #3932, #3936 and parent #3928 OPEN.

## Next connection

1. Implement durable one-shot Core/Engine P01 WRITE tool `xlsx.quote.revise_workcopy` and independent trusted authority.
2. Connect signed-in owner edit confirmation → that exact P01 WRITE grant → revised XLSX storage → artifact registration and owner-only download.
3. Connect supported certified Office/PDF rendering with print/fidelity evidence, otherwise present truthful unsupported state; then actual signed-in desktop/mobile E2E.

## Validation

`python -m pytest -q tests/test_3933_web_quote_xlsx_editor.py tests/test_3933_web_quote_revision_storage.py tests/test_3580_web_xlsx_approved_copy_wire.py tests/test_3933_bounded_document_edit_intent.py tests/test_3936_hark_acceptance.py`

Synthetic cases cover source immutability, exact values/formulas, styles/merged range/unchanged ZIP parts, unsigned grant refusal, foreign owner/run, SHA tampering, write error rollback, and explicit PDF unsupported behavior. Synthetic tests are NOT production proof.
