# Implementation self-check evidence

This directory records Web Implementation Developer self-checks only. It is not independent Local Validator evidence and does not authorize UI approval or deployment.

- `static-self-check.json`: repository-local contract checks and JavaScript syntax.
- `browser-self-check.json`: Chromium checks across 7 states × 3 viewports, keyboard/focus, motion replay equivalence, and reduced motion.

The runtime allowed HTTP readback from Python and returned 200 for HTML/CSS/JS/SVG. Chromium navigation to localhost was blocked by the execution environment (`ERR_BLOCKED_BY_ADMINISTRATOR`), so the browser harness used exact current HTML/CSS/JS/SVG bytes in an inline document. The limitation is recorded in `navigation_mode`. Independent Local Validator must repeat normal checkout/server/browser validation.
