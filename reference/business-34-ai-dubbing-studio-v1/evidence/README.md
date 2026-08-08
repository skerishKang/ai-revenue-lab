# Implementation Self-Check Evidence

- `static-self-check.json`: repository-local contract checks.
- `browser-self-check.json`: 21 state/viewport Chromium implementation self-check.
- `http-readback.json`: localhost HTTP 200 results for HTML, CSS, JavaScript and 11 SVG assets.

Chromium localhost navigation was blocked by execution policy (`ERR_BLOCKED_BY_ADMINISTRATOR`), so browser matrix results use exact current source bytes in an inline fallback. This is not independent Local Validation.
