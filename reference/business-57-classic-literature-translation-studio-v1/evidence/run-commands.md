# Validation Commands

## Static contract

```bash
cd reference/business-57-classic-literature-translation-studio-v1
python evidence/validate_static.py
```

Expected result:

```text
STATIC_CONTRACT_PASS
```

The script rewrites `evidence/validation.json` with the executed check results.

## Local server

```bash
cd reference/business-57-classic-literature-translation-studio-v1
python -m http.server 8000 --bind 127.0.0.1
```

Open:

```text
http://127.0.0.1:8000/
```

## Required browser review

Review all seven states at:

```text
1440 × 1100
768 × 1024
390 × 844
```

Also emulate:

```text
prefers-reduced-motion: reduce
```

## Browser assertions

- seven state tabs switch the matching state;
- Left/Right Arrow keys move between states and preserve visible focus;
- no horizontal overflow at the three required viewports;
- no console errors or page errors;
- no external runtime requests;
- `assets/rose-mark.svg` loads locally;
- source reveal opens and closes on the mobile state;
- Translation Weave changes only thread/emphasis layers;
- source fragments, final paragraph, review rail and replay button geometry remain fixed;
- first and second replay reach the same final frame;
- reduced-motion mode shows the complete linked state immediately.

## Evidence captures

Suggested filenames:

```text
desktop-1440-library.png
desktop-1440-fidelity-spread.png
desktop-1440-comparison.png
desktop-1440-decision-ledger.png
desktop-1440-poetry.png
mobile-390-reading.png
translation-weave-680ms.gif
reduced-motion-weave-final.png
```

Record SHA-256 and byte size for each generated binary artifact. Do not commit private contract material or living-author corpus content with the evidence.

## Current environment note

The authoring environment attempted to clone the public branch for execution, but its container could not resolve `github.com`. Therefore the committed static validator and browser checks must be run independently before the PR may claim `UI_REVIEW_READY`.
