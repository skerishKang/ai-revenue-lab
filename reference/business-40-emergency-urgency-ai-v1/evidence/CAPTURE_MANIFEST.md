# Capture manifest

Generated 2026-07-29 using Chromium through the inline fallback described in `SELF_VALIDATION.md`.

## Committed visual evidence

| File | Review target |
|---|---|
| `capture-contact-sheet.jpg` | Contact sheet generated from the native 1440×1100-class, 768×1024, 390×844 and 390×844 reduced-motion browser captures. The desktop pages are full-page captures and therefore exceed the viewport height while retaining the requested viewport width. |
| `browser-validation.json` | Machine-readable 21-combination and motion self-check record. |

The contact sheet is a compressed review artifact. The validator itself writes native-resolution files named `viewport-1440x1100.png`, `viewport-768x1024.png`, `viewport-390x844.png` and `reduced-motion-390x844.png` when run locally.

These captures are implementation evidence only and do not constitute independent local validation or visual approval. Independent localhost validation remains required because this execution environment blocked Chromium localhost navigation.
