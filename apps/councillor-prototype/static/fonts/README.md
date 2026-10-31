# Self-hosted webfonts (#5972)

Two families, both self-hosted from this directory so the page never depends on a
third-party font host or on a font installed on the visitor's machine.

| Use | Family | Files | Bytes |
|---|---|---|---|
| Headings (`--font-serif`) | **MaruBuri** Bold | `maruburi/MaruBuri-Bold.woff2` | 451,596 |
| Body, menu, buttons, cards (`--font`) | **Pretendard** Variable (all weights) | `pretendard/woff2-dynamic-subset/*.woff2` × 92 | 2,957,724 |

Total vendored: 3,409,320 bytes. Only the subsets a page actually needs are
downloaded — the 92 Pretendard files are sliced by `unicode-range`, so a load is
one CSS file plus a handful of ≤43 KB font files.

## Provenance

| Font | Official distribution | Version |
|---|---|---|
| Pretendard | `https://cdn.jsdelivr.net/npm/pretendard@1.3.9/` (repo: https://github.com/orioncactus/pretendard) | 1.3.9 (pinned) |
| MaruBuri | `https://hangeul.pstatic.net/hangeul_static/webfont/MaruBuri/` (NAVER 한글한글 아름답게) | current |

Files are unmodified upstream builds. No subsetting, renaming or repacking was
done locally.

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
