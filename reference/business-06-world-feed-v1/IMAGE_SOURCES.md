# Image and Font Sources

## Policy result

- Runtime external image hotlinks: **none**
- Third-party screenshots embedded in product UI: **none**
- Downloaded fonts: **none**
- Runtime font requests: **none**
- All visual assets are local SVG illustrations created specifically for this Phase 1 reference.
- Rights classification is conservative: every illustration is marked `reference-only` until a separate production asset review.

## Image manifest

| Local file | Source URL | Creator / rights holder | License or use basis | Acquisition / creation date | Used in | Status |
|---|---|---|---|---|---|---|
| `assets/images/hero-harbor.svg` | N/A — created in repository workspace | AI Revenue Lab Phase 1 UI worker | Original synthetic vector composition created for this reference; no third-party image copied | 2026-07-26 | home, story, mobile, motion, adjusted | `reference-only` |
| `assets/images/night-market.svg` | N/A — created in repository workspace | AI Revenue Lab Phase 1 UI worker | Original synthetic vector composition created for this reference | 2026-07-26 | home, mobile | `reference-only` |
| `assets/images/ceramic-hands.svg` | N/A — created in repository workspace | AI Revenue Lab Phase 1 UI worker | Original synthetic vector composition created for this reference | 2026-07-26 | why, adjusted, topic alternate, motion | `reference-only` |
| `assets/images/small-cinema.svg` | N/A — created in repository workspace | AI Revenue Lab Phase 1 UI worker | Original synthetic vector composition created for this reference | 2026-07-26 | topic | `reference-only` |
| `assets/images/stadium-culture.svg` | N/A — created in repository workspace | AI Revenue Lab Phase 1 UI worker | Original synthetic vector composition created for this reference | 2026-07-26 | home sports-culture item | `reference-only` |
| `assets/images/sea-train.svg` | N/A — created in repository workspace | AI Revenue Lab Phase 1 UI worker | Original synthetic vector composition created for this reference | 2026-07-26 | home | `reference-only` |

## Font manifest

No font files are stored under `assets/fonts/**`.

The CSS uses a system-first stack:

- sans-serif: `Pretendard`, `Noto Sans KR`, `Apple SD Gothic Neo`, `Malgun Gothic`, Arial, sans-serif;
- editorial serif: `Iowan Old Style`, `Noto Serif KR`, `Nanum Myeongjo`, Georgia, serif.

These are requested only when already installed on the reviewing device. No remote font CDN or runtime request is used.
