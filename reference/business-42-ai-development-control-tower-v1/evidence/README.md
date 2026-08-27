# Implementation Self-Check Evidence

This evidence was produced by the implementation worker and is not independent `LOCAL_VALIDATION_PASS`.

- `static-self-check.json` — static contract checks
- `browser-self-check.json` — 7 states × 3 viewports and motion/reduced-motion checks
- `http-readback.json` — localhost HTTP status and byte counts
- `source-hashes.json` — SHA-256 inventory of committed workspace files

The browser script produces representative screenshots under `evidence/screenshots/` during execution. Screenshots are not committed in this Phase 1 implementation branch. Any localhost policy error and fallback mode are recorded explicitly in `browser-self-check.json`.
