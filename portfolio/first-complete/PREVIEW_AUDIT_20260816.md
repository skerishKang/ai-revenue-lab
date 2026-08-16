# Portfolio Public Surface Audit — 2026-08-16

This audit was generated from fresh Chromium loads of the public product surfaces after installing `fonts-noto-cjk` on the capture runner.

Important: SVG presence is not itself a failure. Utility icons and functional visualizations are allowed. Material Authority fails only when a real subject such as a person, place, artwork, video subject, or product is being substituted by vector/CSS illustration.

|Business|Surface|SVG|Large SVG|SVG img|Large SVG img|CSS SVG bg|Canvas|Raster img|Large raster|Korean chars|Replacement chars|Machine triage|
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
|B01|Personal Edition|0|0|0|0|0|0|3|3|199|0|NO LARGE SVG SIGNAL|
|B02|Living Travel|0|0|0|0|0|0|0|0|86|0|NO LARGE SVG SIGNAL|
|B04|Living Learning|2|0|0|0|0|0|0|0|687|0|NO LARGE SVG SIGNAL|
|B05|DanjiOn|11|0|0|0|0|0|0|0|1466|0|NO LARGE SVG SIGNAL|
|B06|World Feed|0|0|0|0|0|0|0|0|784|0|NO LARGE SVG SIGNAL|
|B07|Personal Meaning Map|0|0|0|0|0|0|0|0|418|0|FUNCTIONAL VECTOR ALLOWED — semantic geometry is product evidence|
|B08|Family Newspaper|0|0|0|0|0|0|0|0|389|0|NO LARGE SVG SIGNAL|
|B09|Personalized Children’s Story|0|0|0|0|0|0|0|0|292|0|BLOCKED PUBLIC SURFACE — excluded from portfolio preview|
|B10|Fan Magazine|0|0|0|0|0|0|0|0|363|0|NO LARGE SVG SIGNAL|
|B11|Language Learning Magazine|0|0|0|0|0|0|0|0|314|0|NO LARGE SVG SIGNAL|
|B12|Creator Mini-Media|0|0|0|0|0|0|0|0|314|0|NO LARGE SVG SIGNAL|
|B13|Personal Video Archive|5|0|0|0|0|0|13|6|500|0|NO LARGE SVG SIGNAL|
|B15|Global AI Newsroom|0|0|0|0|0|0|0|0|338|0|NO LARGE SVG SIGNAL|

## Authority interpretation

- **B07**: functional semantic geometry is explicitly allowed by the portfolio Material Authority rule; SVG/geometry here is not treated as subject substitution.
- **B09**: the current public Pages surface is pre-clean-master/blocker evidence and is deliberately excluded from the portfolio preview. The portfolio shows an integration-blocker panel until clean-master PNG byte integration is complete.
- A `MIXED SVG + RASTER` row is not automatically a failure. It is a DOM signal for human semantic review. Existing PASS/FREEZE products are not reopened solely because an SVG icon, chart, mask, logo, or functional diagram exists.
- Korean `□□` seen in the prior portfolio screenshots originated in the Linux screenshot capture environment. The frozen preview assets in `previews/` were recaptured after installing Noto CJK fonts.
