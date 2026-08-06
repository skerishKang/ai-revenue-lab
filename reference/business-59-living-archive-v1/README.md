# Business 59 · Living Archive / 나의 기록서재

Browser-only MVP vertical slice for the hybrid spatial-library and precision-reader contract.

## What this proves

- three deterministic synthetic volumes appear as tactile books;
- the selected volume opens in a bounded 3D-style preview;
- `정밀 리더에서 계속` carries the current volume and page into a 2D reader;
- 2D navigation, search, bookmark and note state update the position shown after returning to 3D;
- the precision reader remains directly accessible without completing 3D motion;
- local import is shown truthfully as a concept only;
- no source, note or model data leaves the browser.

## Run

Serve this directory with any static HTTP server. Example:

```bash
python -m http.server 4173 --directory reference/business-59-living-archive-v1
```

Open `http://127.0.0.1:4173/`.

## Current boundary

This is not a production PDF reader. Fixtures are repository-local synthetic text. There is no PDF.js, OCR, DOCX conversion, persistence, authentication, cloud sync, local model, web model, analytics or deployment configuration.

## Source prototype relationship

The owner supplied a self-contained Three.js bookshelf and page-turning prototype. This workspace preserves its strongest product idea—books as spatial identity—while replacing the bundled single-file implementation with small, reviewable HTML/CSS/JavaScript and adding the required 2D precision-reader transition.

## Status

```text
HYBRID_READER_MVP_IMPLEMENTED
SYNTHETIC_LOCAL_FIXTURES_ONLY
NO_PRIVATE_FILE_UPLOAD
NO_MODEL_EXECUTION
NO_DEPLOYMENT
UI_REVIEW_READY
DO_NOT_MERGE
```
