# Implementation Self-check Boundary

The Web implementation worker runs static and browser self-checks for the exact local source before publishing. These checks are implementation evidence only and do not constitute independent `LOCAL_VALIDATION_PASS`.

Commands:

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
git diff --check
```

Independent Local Validator still owns official screenshot matrix, remote exact-head readback, hashes, evidence archive and final approval evidence.
