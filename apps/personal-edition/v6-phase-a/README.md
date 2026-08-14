# B01 V6 Phase A — three independent static directions

Issue: #613

This folder is intentionally isolated from production Personal Edition templates and backend. It contains only the three Phase A browser-rendered concepts authorized by Issue #613:

- Entry / first viewport
- Private Library
- Edition Read opening

Open `index.html?direction=a&screen=entry` and switch:

- `direction=a|b|c`
- `screen=entry|library|read`

## Directions

- **A — Signal Ledger:** dense graphite operational surface; fragments and the edition object behave like a high-signal private workspace.
- **B — Living Index:** bright modular grid; the archive is a contemporary index rather than a paper/book simulation.
- **C — Night Reader:** immersive dark reader; luminous source cards and collectible editions without text over photography.

## Phase A boundaries

- Static concept code only.
- No Backend/Auth/DB/domain changes.
- No production route replacement.
- No deploy workflow.
- No external image/font/runtime request.
- `OWNER_UI_APPROVED=false`.

## Browser evidence

Screenshots are in `evidence/screenshots/` for every direction × surface at exactly:

- Desktop `1440×1100`
- Mobile `390×844`

Naming: `{a|b|c}-{entry|library|read}-{desktop|mobile}.png`.

Browser QA: 18/18 rendered cases passed horizontal-overflow, console/page-error, runtime-request, visible-panel, active-navigation, and H1 line-height checks. Evidence was re-rendered from the exact static source head through a localhost Chromium server after CTO audit found corrupt committed WebP binaries; the committed concept itself is ordinary static HTML and uses no external runtime dependencies.

- CTO evidence repair uses runner-installed Noto CJK fonts so Korean glyphs are visible in the committed screenshots.
