# Implementation self-check

This directory records implementation evidence only.

It does **not** declare independent Local Validation, a Web CTO visual verdict or UI approval.

## Commands

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
```

## Intended checks

- exact seven states and controls;
- reciprocal 7/7 tab-panel relationships;
- required product and safety boundaries;
- repository-local documented assets;
- no external runtime requests;
- keyboard review controls;
- 21 state/viewport combinations;
- actual final-element `animationend` and 760ms nominal timing;
- deterministic Replay target;
- focus, scroll and geometry stability;
- reduced-motion information equivalence;
- 390px dedicated composition.

## Gate state

```text
IMPLEMENTATION_SELF_CHECK_ONLY
NOT_VALIDATED_BY_LOCAL
NOT_REVIEWED_BY_WEB_CTO
UI_APPROVAL_NOT_PERFORMED
NOT_DEPLOYED
```
