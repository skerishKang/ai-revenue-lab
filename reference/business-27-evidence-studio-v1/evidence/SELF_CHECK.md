# Web Self-check

This is not Local Validator evidence.

Commands:

```bash
python tests/validate_reference.py
node tests/check_js_syntax.mjs
git diff --cached --check
```

Checks only: required files and states, local paths, runtime dependency absence, required notices, responsive and reduced-motion declarations, JavaScript syntax, asset manifest coverage and whitespace errors.

Not claimed: Chromium matrix, screenshots, network capture, computed motion timing, layout geometry, focus/scroll replay stability, hashes or deployment/public-page verification.

Status marker: `NOT_VALIDATED_BY_LOCAL`.
