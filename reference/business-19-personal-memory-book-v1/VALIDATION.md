# Validation Record

Validation target: local static workspace rendered in Chromium headless.

- viewport captures: 1440×1100, 768×1024, 390×844;
- seven states rendered;
- horizontal overflow checked at all required viewports;
- keyboard focus and arrow-key state navigation checked;
- browser console error count: 0;
- failed page/asset requests: 0;
- external runtime requests: 0;
- deterministic CSS/JS query: `business19-20260727-1`;
- synthetic and date-confidence labels present;
- signature motion and reduced-motion captures generated;
- local reference integrity and `git diff --check` passed after CSS file splitting.

The machine-readable report is committed under `evidence/validation-report.json`. Binary PNG/GIF captures were generated from this workspace and are handed off separately because the connected repository writer supports UTF-8 source files but not local binary-path upload. Their names and SHA-256 values are recorded in `evidence/README.md`.

This remains a Phase 1 visual reference, not accepted UX or production functionality.
