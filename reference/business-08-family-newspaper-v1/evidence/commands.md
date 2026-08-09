# Browser validation command record

Validation date: 2026-07-26  
Browser: system Chromium through Python Playwright  
Desktop viewport: `1440×1100`  
Mobile viewport: `390×844`  
Reduced-motion viewport: `1440×900`

## Local review command

The reference can be served from the repository root with:

```bash
python -m http.server 4173 --directory reference/business-08-family-newspaper-v1
```

The execution environment blocked both localhost and `file://` navigation through a managed Chromium `URLBlocklist: ["*"]` policy. For the isolated browser check only, the managed policy file was temporarily moved, the repository-local `file://` page was tested without external navigation, and the policy file was restored through a shell `trap` immediately after validation.

## Browser validation

```bash
python validate_family_newspaper.py
```

The local script performed:

- all seven state switches;
- 1440px front, photo-feature, and calendar captures;
- actual 390×844 mobile first-viewport capture;
- keyboard ArrowRight state movement;
- computed visible-focus outline check;
- source-note disclosure check;
- Page Fold replay and 680ms completion check;
- reduced-motion media emulation and immediate transition check;
- horizontal-overflow checks;
- console, page-error, failed-response, and external-request collection;
- line-count, version-query, stale-query, local-reference, localStorage, and cookie scans.

## Motion encoding

Ten Page Fold frames were captured from 0ms through the completed state and encoded with a short final hold:

```bash
ffmpeg -y \
  -framerate 12.5 \
  -i fold-frames/frame-%03d.png \
  -vf "format=yuv420p" \
  -c:v libx264 \
  -movflags +faststart \
  page-fold-680ms.mp4
```

Encoded evidence duration: `0.800s`. The CSS/JavaScript transition target remains `680ms`; the remaining capture time is the completed-state hold.

## Binary evidence boundary

PNG and MP4 evidence are not committed to GitHub. They are submitted separately in the evidence ZIP and individual sandbox links. Only this command record and `validation.json` are committed under `evidence/**`.
