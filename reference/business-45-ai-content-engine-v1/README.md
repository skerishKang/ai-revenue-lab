# Business 45 · AI Content Engine — Phase 1 visual UI reference

## Status

```text
UI_REVIEW_READY
NOT_VALIDATED_BY_LOCAL
NOT_DEPLOYED_PENDING_UI_APPROVAL
UX_NOT_STARTED
BACKEND_FROZEN
PR_OPEN_DRAFT_UNMERGED
DO_NOT_MERGE
```

This workspace is a static `UI_ONLY` visual reference for **Editorial Production Foundry / 콘텐츠 제작 주조실**. It converts one wholly synthetic, repository-created source brief into visual content structure, four format transformations, quality holds and a human-approved reusable production kit.

## Exact states

`cover`, `brief`, `structure`, `variants`, `quality`, `kit`, `mobile`

## Fixture

- Organization: Namu Culture Lab — fictional
- Source: fictional community lantern workshop
- Audience: families and local volunteers — synthetic
- Formats: article opening, event letter, learning card, magazine module
- Rights: repository-created synthetic source
- Publication: not performed

## Runtime boundary

Local semantic HTML, CSS, JavaScript and repository-local assets only. No live generation, upload, model/provider, CMS, publishing connection, account, storage, analytics, personalization, feedback engine, database or backend.

## Review controls

The state tablist supports click, Arrow Left/Right, Home and End. It synchronizes `aria-selected`, roving `tabIndex`, exactly one visible panel and a stable hash. `kit` contains the deterministic `Brief-to-Content-Production-Kit` motion preview.

## Self-check

```bash
python3 tests/validate_reference.py
python3 tests/browser_self_check.py
```

Implementation self-check is not an independent `LOCAL_VALIDATION_PASS`.
