# Validation Record

Validation date: 2026-07-27 KST

## Environment limitation

A local static server was started with:

```bash
python3 -m http.server 4181
```

Chromium navigation to `http://127.0.0.1:4181/` failed with `ERR_BLOCKED_BY_ADMINISTRATOR`. Therefore the result is **not** described as hosted or public URL verification.

The authored `index.html`, three CSS files, JavaScript and seven local SVG assets were loaded into an in-memory Chromium document. Runtime SVG references were converted to data URIs only inside the validator; the repository source retains normal local paths. File-system checks independently confirmed every authored local path exists.

## Commands

```bash
python3 evidence/validate.py
git diff --cached --check
```

## Results

- seven visual states: pass;
- 1440×1100, 768×1024 and 390×844: pass;
- horizontal overflow: 0 in all seven states at all three viewports;
- keyboard state navigation: pass;
- visible focus: pass;
- accessible control names: pass;
- console errors: 0;
- page errors: 0;
- failed local assets: 0;
- missing local paths: 0;
- external runtime requests: 0;
- all SVG images loaded: pass;
- deterministic CSS/JS version: `founder-strategy-letter-20260727-1`;
- synthetic and non-live labels: pass;
- Argument Thread focus and scroll stability: pass;
- reduced-motion equivalent final state: pass;
- `git diff --check`: pass.

Machine-readable detail is stored in `evidence/validation-report.json`.
