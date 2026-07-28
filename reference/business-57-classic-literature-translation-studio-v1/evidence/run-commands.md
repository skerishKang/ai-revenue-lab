# Validation Commands and Executed Environment

Execution date: `2026-07-28`

## Static contract

```bash
cd reference/business-57-classic-literature-translation-studio-v1
python evidence/validate_static.py
```

Expected and observed status:

```text
STATIC_CONTRACT_PASS
```

The script generates `evidence/validation.json` from current implementation bytes.

## Browser validation

```bash
cd reference/business-57-classic-literature-translation-studio-v1
python evidence/validate_browser.py
```

Environment:

```text
Browser: /usr/bin/chromium
Automation: Python Playwright
Navigation mode: page.set_content inline local harness
Reason: localhost and file:// navigation blocked by the container policy
Runtime source: current index.html, styles/main.css, scripts/review.js, assets/rose-mark.svg
External runtime requests: prohibited and asserted zero
```

Required viewport matrix:

```text
1440 × 1100
768 × 1024
390 × 844
prefers-reduced-motion: reduce
```

Generated machine-readable output:

```text
evidence/browser-validation.json
```

Generated visual evidence:

```text
evidence/screenshots/desktop-1440-library.png
evidence/screenshots/desktop-1440-source-fidelity.png
evidence/screenshots/desktop-1440-comparison.png
evidence/screenshots/desktop-1440-ledger.png
evidence/screenshots/desktop-1440-poetry.png
evidence/screenshots/desktop-1440-mobile.png
evidence/screenshots/desktop-1440-weave.png
evidence/screenshots/tablet-768-source-fidelity.png
evidence/screenshots/mobile-390-reading.png
evidence/screenshots/weave-before.png
evidence/screenshots/weave-midpoint.png
evidence/screenshots/weave-complete.png
evidence/screenshots/reduced-motion-weave-final.png
evidence/screenshots/translation-weave-680ms.gif
```

## Git whitespace validation

```bash
git diff --check
```

## Evidence integrity

```bash
python evidence/build_manifest.py
python -m zipfile -t <evidence-archive.zip>
sha256sum <evidence-archive.zip>
```

Binary screenshots and GIF are kept in the private evidence archive rather than committed to the public source branch. `evidence/evidence-manifest.json` records filename, pixel size, byte size and SHA-256.
