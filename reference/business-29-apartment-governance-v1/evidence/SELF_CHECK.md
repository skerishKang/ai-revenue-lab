# Implementation Self-check Boundary

This evidence is produced by the Web implementation worker and does not replace independent Local validation.

Commands:

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
```

The browser harness checks 21 state/viewport combinations, state visibility, `aria-selected`, horizontal overflow, broken local images, console/page/request failures, external requests, keyboard navigation, replay focus, scroll stability, motion completion and reduced-motion completion.

It does not constitute `LOCAL_VALIDATION_PASS`, Web CTO approval, user `UI_APPROVED`, deployment authority or production verification.
