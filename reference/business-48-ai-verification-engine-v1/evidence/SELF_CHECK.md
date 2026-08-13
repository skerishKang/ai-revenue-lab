# Implementation self-check

This is implementation evidence only. It is not independent `LOCAL_VALIDATION_PASS`.

## Matrix

- states: 7
- viewports: 1440×1100, 768×1024, 390×844
- combinations: 21

## Required assertions

- exactly one selected and visible state;
- `aria-selected` and roving `tabIndex`;
- keyboard navigation and visible focus;
- horizontal overflow 0;
- Korean/English labels contained;
- label overlap 0;
- exactly 10 repository-local SVG assets render;
- worker claim versus verified fact separated;
- self-check versus independent check separated;
- passed / failed / skipped / unavailable separated;
- stale evidence rejected;
- exact-version match visible;
- exceptions and residual condition preserved;
- validator verdict separated from human approval;
- approval scope limited;
- no universal certification;
- deployment not authorized;
- console/page/failed/external requests 0;
- Replay 1/2 style, screenshot and geometry equality;
- actual `briefComplete` animationend authority at 770ms;
- focus, scroll and board geometry stable;
- reduced-motion immediate completion;
- decision state: 8/8 retained boundaries visible after normal completion at all three viewports;
- decision state: 8/8 retained boundaries visible after reduced-motion completion at all three viewports;
- mobile state: 8/8 retained boundary meanings visible at 390×844.

Browser results are written to `browser-self-check.json`; static results to `static-self-check.json`.
