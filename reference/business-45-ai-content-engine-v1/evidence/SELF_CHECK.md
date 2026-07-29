# Implementation self-check

This evidence is produced by the implementation environment and is not an independent Local Validator result.

## Commands

```bash
python3 tests/validate_reference.py
python3 tests/browser_self_check.py
```

## Coverage target

- exact seven states;
- 1440×1100, 768×1024, 390×844;
- 21 state/viewport combinations;
- exactly one selected and visible state;
- synchronized `aria-selected` and roving `tabIndex`;
- Arrow, Home and End keyboard navigation;
- visible focus;
- horizontal overflow and clipping checks;
- 10 documented local assets, including four substantial editorial focal illustrations;
- console, page, failed and external requests;
- final-element actual `animationend` completion authority;
- Replay 1/2 computed-style, screenshot and geometry equality;
- focus and scroll stability;
- reduced-motion information-complete equivalence.

## Authority

```text
NOT_VALIDATED_BY_LOCAL
```

## Recorded implementation result

- static contract: `PASS`
- browser inline fallback: `PASS`
- exact states: `7`
- state/viewport combinations: `21`
- horizontal overflow: `0`
- text clipping: `0`
- console errors: `0`
- page errors: `0`
- external runtime requests: `0`
- Replay 1/2 computed style, screenshot hash and geometry: equal
- focus and scroll: stable
- reduced motion: immediately complete

Browser limitation: direct `file://` and localhost navigation were blocked by Chromium administrator policy (`ERR_BLOCKED_BY_ADMINISTRATOR`). The check embedded local CSS, JavaScript and all repository-local assets as data URIs. This remains implementation self-check evidence only.
