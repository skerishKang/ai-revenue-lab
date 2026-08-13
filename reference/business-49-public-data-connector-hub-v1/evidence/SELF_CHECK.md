# Implementation self-check

This evidence is implementation-worker self-check only. It is not independent `LOCAL_VALIDATION_PASS`.

## Commands

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
git diff --check
```

## Expected matrix

- 7 states × 3 viewports = 21 combinations
- 1440×1100
- 768×1024
- 390×844

## Boundaries checked

- official fictional source versus unofficial mirror
- access method versus actual connection
- licence statement versus legal advice
- source versus normalized field
- raw versus transformed value
- publication versus retrieval date
- current, stale and unknown freshness
- missing versus zero
- known limitation and incomplete coverage
- connector readiness versus connected state
- no official endorsement
- no live API, scraping, credential or ingestion

## Browser harness note

The worker environment may block browser navigation to localhost. The browser test therefore verifies local asset HTTP 200 responses separately, then inlines the exact local HTML/CSS/JavaScript/SVG bytes into a network-free Chromium document for layout, keyboard and motion checks.
