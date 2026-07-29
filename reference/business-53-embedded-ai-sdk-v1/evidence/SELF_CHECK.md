# Implementation self-check record

This evidence is produced by the implementation role. It is not independent Local Validation and does not authorize UI approval or deployment.

## Intended commands

```bash
python3 tests/validate_reference.py
node --check scripts/review.js
python3 tests/browser_self_check.py
```

## Contract covered

- exact seven visual states;
- 7/7 reciprocal tab and panel accessibility relationship;
- repository-local documented asset inventory;
- required authority and boundary labels;
- no external runtime URL or network API in source;
- deterministic asset token;
- actual final-element `animationend` and no fixed completion timeout;
- 700–800ms nominal motion invariant;
- roving keyboard controls and visible focus;
- 1440×1100, 768×1024 and 390×844 implementation browser matrix;
- Replay equality, focus/scroll/geometry stability and reduced-motion equivalence;
- mobile contract containment.

## Observed implementation results

- static contract: PASS;
- exact states / controls: 7 / 7;
- reciprocal tab-panel relationships: 7 / 7;
- documented repository-local assets: 10;
- required authority labels: 32 / 32;
- browser source matrix: 21 / 21 combinations;
- local HTTP readback: index, CSS, JavaScript and 10 SVG assets all 200;
- console / page / external runtime errors: 0 / 0 / 0;
- keyboard: ArrowLeft, ArrowRight, Home, End, Enter and Space PASS;
- final motion: actual `embedContractComplete` animation, computed 780ms;
- Replay final style, screenshot and geometry equality: PASS;
- focus and scroll stability: PASS;
- animations running after completion: 0;
- reduced motion: immediate complete;
- 390px brief required-boundary containment: PASS.

The managed Chromium environment blocks loopback navigation. The browser harness therefore verifies localhost HTTP 200 separately, then executes the exact same local HTML, CSS, JavaScript and SVG bytes in a network-free Chromium document. This remains implementation-owned evidence only.

## Explicit status

```text
IMPLEMENTATION_SELF_CHECK_ONLY
NOT_VALIDATED_BY_LOCAL
UI_APPROVED_NOT_YET
NOT_DEPLOYED
```
