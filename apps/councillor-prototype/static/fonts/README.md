# Self-hosted webfonts (#5972)

Two families, both self-hosted from this directory so the page never depends on a
third-party font host or on a font installed on the visitor's machine.

| Use | Family | Files | Bytes |
|---|---|---|---|
| Headings (`--font-serif`) | **MaruBuri** Bold (glyph subset) | `maruburi/MaruBuri-Bold.woff2` | 36,432 |
| Body, menu, buttons, cards (`--font`) | **Pretendard** Variable (all weights) | `pretendard/woff2-dynamic-subset/*.woff2` × 92 | 2,957,724 |

Pretendard: 2,957,724 bytes of dynamic subsets; only the slices a page needs are
downloaded (the 92 files are cut by `unicode-range`, so a load is one CSS file
plus a handful of ≤43 KB files).

MaruBuri is subset to the glyphs the pages actually render (317 glyphs,
36 KB instead of the 452 KB full face) — see below.

## Provenance

| Font | Official distribution | Version |
|---|---|---|
| Pretendard | `https://cdn.jsdelivr.net/npm/pretendard@1.3.9/` (repo: https://github.com/orioncactus/pretendard) | 1.3.9 (pinned) |
| MaruBuri | `https://hangeul.pstatic.net/hangeul_static/webfont/MaruBuri/` (NAVER 한글한글 아름답게) | current |

Pretendard is an unmodified upstream build.

MaruBuri is the upstream Bold build **subset locally** to the glyphs these pages
use. Licence-clean: the OFL permits modification, the file is still called
MaruBuri (no renamed derivative), and the full licence text ships beside it.
First re-download the upstream file with the URL below, then re-cut it from the
text the pages actually render. The glyph list is written to the system temp
directory on purpose — it must not ship:

```bash
python -m pip install fonttools brotli
python - <<'EOF'
import json, pathlib, re, tempfile
from fontTools.subset import main as subset

root = pathlib.Path(".")
def rendered(p):
    s = p.read_text(encoding="utf-8")
    if p.suffix == ".html":
        s = re.sub(r"<script.*?</script>", " ", s, flags=re.S)
        return re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", " ", s)

text = "".join(rendered(p) for p in root.glob("*.html"))
text += rendered(root / "static" / "app.js") + rendered(root / "static" / "home.js")
text += json.dumps(json.loads((root / "static" / "miraen.json").read_text(encoding="utf-8")), ensure_ascii=False)

glyphs = pathlib.Path(tempfile.gettempdir()) / "maruburi-glyphs.txt"
glyphs.write_text("".join(sorted({c for c in text if not c.isspace()})), encoding="utf-8")
subset(["maruburi/MaruBuri-Bold.woff2", f"--text-file={glyphs}",
        "--flavor=woff2", "--layout-features=*", "--no-hinting",
        "--output-file=maruburi/MaruBuri-Bold.woff2"])
EOF
```

After re-cutting, load the site once and check every heading still renders in
MaruBuri (a missing glyph silently falls back to Noto Serif KR). The pytest lane
`test_the_serif_face_ships_only_the_glyphs_in_use` pins the size ceiling.

Re-vendor (from this directory):

```bash
for i in $(seq 0 91); do
  curl -sSfL -O --output-dir pretendard/woff2-dynamic-subset \
    "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/woff2-dynamic-subset/PretendardVariable.subset.$i.woff2"
done
curl -sSfL -o pretendard/pretendard-variable-dynamic-subset.css \
  "https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css"
curl -sSfL -o maruburi/MaruBuri-Bold.woff2 \
  "https://hangeul.pstatic.net/hangeul_static/webfont/MaruBuri/MaruBuri-Bold.woff2"
```

## Licence notice

Both families are licensed under the **SIL Open Font License, Version 1.1**,
which permits commercial use, bundling and redistribution provided the copyright
notice and licence travel with the files.

- **Pretendard** — Copyright (c) 2021, Kil Hyung-jin, with Reserved Font Name
  Pretendard. Full licence: [`LICENSE-Pretendard.txt`](./LICENSE-Pretendard.txt).
- **MaruBuri** — Copyright (c) 2010, NAVER Corporation, with Reserved Font Name
  MaruBuri. Full licence: [`LICENSE-MaruBuri.txt`](./LICENSE-MaruBuri.txt).

Neither font may be sold on its own. The fonts are used here, unmodified, as web
fonts in this prototype; no derivative or renamed version is distributed.

## Wiring

Each page links the two stylesheets before `styles.css`:

```html
<link rel="stylesheet" href="./static/fonts/maruburi.css" />
<link rel="stylesheet" href="./static/fonts/pretendard/pretendard-variable-dynamic-subset.css" />
<link rel="stylesheet" href="./static/styles.css" />
```
