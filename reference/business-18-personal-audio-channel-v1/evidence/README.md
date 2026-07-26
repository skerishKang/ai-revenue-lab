# Browser evidence

The required PNG and GIF captures were generated from the exact static source with `tools/capture_evidence.py`.

The execution environment blocked navigation to both `http://127.0.0.1` and `file://` with `ERR_BLOCKED_BY_ADMINISTRATOR`. The script therefore loads the same HTML, CSS, JavaScript and local SVG bytes into a Playwright in-memory document through `page.set_content()`.

This is local in-memory rendering evidence. It is not localhost hosting, a branch preview, or Hosted URL verification.

## Generated captures

- `today-edition-1440x1100.png`
- `listening-view-1440x1100.png`
- `source-shelf-1440x1100.png`
- `episode-script-1440x1100.png`
- `audio-letter-1440x1100.png`
- `channel-archive-1440x1100.png`
- `mobile-composition-1440x1100.png`
- `listening-view-768x1024.png`
- `mobile-listening-390x844.png`
- `chapter-pulse.gif`
- `reduced-motion-1440x1100.png`
- `validation-report.json`

## Reproduction

```bash
python tools/capture_evidence.py
```

Requirements: Python, Pillow, Playwright and Chromium at `/usr/bin/chromium`.

The GitHub connector used for this implementation can write UTF-8 repository files and Git objects but cannot ingest local binary files directly. The generated PNG/GIF captures are therefore supplied with the implementation report as separate artifacts; the reproducible script and JSON result remain in the reference workspace.
