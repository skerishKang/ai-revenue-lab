# Browser validation commands

```bash
python tests/validate_reference.py
python tests/browser_validate.py
git diff --cached --check
```

The Chromium harness inlines repository-local HTML, CSS, JavaScript, and SVG files only for deterministic execution in an environment that may block `file:` or localhost navigation. No external runtime request is permitted.
