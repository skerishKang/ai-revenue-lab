# Implementation self-check

This evidence is produced by the implementation environment and is **not** independent `LOCAL_VALIDATION_PASS`.

Commands:

```bash
python3 tests/validate_reference.py
python3 tests/browser_self_check.py
```

Coverage:

- exact seven states;
- 7 states × 3 viewports = 21 combinations;
- one visible/selected state;
- `aria-selected` and roving `tabIndex`;
- keyboard navigation and visible focus;
- horizontal overflow and clipping checks;
- 11+ local SVG request/render coverage;
- required authority labels and anti-inference boundaries;
- external runtime requests, console errors and page errors;
- Replay 1/2 computed-style and geometry equality;
- actual final `animationend` completion authority;
- focus/scroll stability;
- reduced-motion information equivalence.

Committed JSON files contain the exact result. PNG captures are local Chromium evidence for 1440×1100 cover and 390×844 mobile composition.
## Browser limitation

The environment blocked Chromium access to localhost with `ERR_BLOCKED_BY_ADMINISTRATOR`. Browser self-check therefore used a deterministic inline fallback with local CSS, JavaScript and all 12 SVGs embedded as data URIs. This is implementation self-check evidence only and is **not** independent `LOCAL_VALIDATION_PASS`.
