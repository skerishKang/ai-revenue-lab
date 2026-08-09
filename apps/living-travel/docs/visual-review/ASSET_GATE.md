# Destination asset gate

The V2 layout/art-direction reset is implemented, but the repository's existing Busan demo image files are still the older synthetic/procedural set. They are intentionally not treated as final destination photography.

Before final owner visual review:

- replace hero / alley / sea / food / edition cover visuals with local licensed/CC0 or intentionally generated assets;
- record author/source/license and any transformation in `docs/IMAGE_SOURCES.md`;
- keep runtime fully local (no external image CDN dependency);
- verify cover crops at desktop, tablet, and mobile widths.

## Verified CC0 candidate set

These are **source candidates only**. They are not yet imported into the repository and must not be referenced as runtime remote URLs.

| Intended use | Candidate | Author / date | License | Source page |
|---|---|---|---|---|
| Hero / neighborhood | Gamcheon Culture Village | Bernard Gagnon, 2022-10-02 | CC0 1.0; Wikimedia Quality Image | https://commons.wikimedia.org/wiki/File:Gamcheon_Culture_Village.jpg |
| Market / food | Jagalchi Market 02 | Bernard Gagnon, 2022-10-02 | CC0 1.0; Wikimedia Quality Image | https://commons.wikimedia.org/wiki/File:Jagalchi_Market_02.jpg |
| Market / street | Gukje Market Busan South Korea 02 | Hankook12, 2024-02-09 | CC0 1.0 | https://commons.wikimedia.org/wiki/File:Gukje_Market_Busan_South_Korea_02.jpg |
| Sea / coast | Busan's seaside | WANGYIFAN2024, 2024-05-17 | CC0 1.0 | https://commons.wikimedia.org/wiki/File:Busan%27s_seaside.jpg |
| Street texture / secondary | Street views in Busan | Syced, 2007-08-24 | CC0 1.0 | https://commons.wikimedia.org/wiki/File:Street_views_in_Busan.jpg |
| Beach / cover alternative | Busan beach | Syced, 2007-08-23 | CC0 1.0 | https://commons.wikimedia.org/wiki/File:Busan_beach.jpg |

### Import rules

1. Download the source or an appropriately sized derivative during build/repository preparation, not at browser runtime.
2. Convert/crop locally to the existing WebP inventory where appropriate so current HTML paths can remain stable.
3. Record original filename, source page, author, license, downloaded pixel size, local transform/crop, final filename, and SHA256 in `docs/IMAGE_SOURCES.md`.
4. Keep source photographs geographically honest: do not label a generic Busan beach as a specific neighborhood if the source does not establish that location.
5. After replacement, rerun the exact 24-screen Chromium gate and inspect crops manually before changing `B2_V2_UI_REVIEW_READY`.
