# Validation

## Environment

- deterministic version: `company-memory-20260728-1`
- Chromium executable: `/usr/bin/chromium`
- validation mode: inlined local HTML, CSS, JavaScript, and SVG assets
- reason: the execution environment may block localhost or file navigation; production source remains repository-local and contains no runtime hotlinks

## Commands

```bash
python tests/validate_reference.py
python tests/browser_validate.py
git diff --check --no-index /dev/null reference/business-26-company-memory-v1
```

## Required viewports

- 1440 × 1100
- 768 × 1024
- 390 × 844

## Committed machine-readable evidence

- `evidence/validation.json`
- `evidence/motion-timing.json`
- `evidence/browser-check-commands.md`

## Generated local visual evidence

The browser validator also produces `desktop-atlas.svg`, `tablet-atlas.svg`, `mobile-atlas.svg`, and `motion-sequence.svg` from actual Chromium captures. These generated review artifacts are retained in the execution workspace and are not required runtime assets. Values in the committed JSON reports are produced by runtime assertions.
