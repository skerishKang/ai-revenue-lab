# Browser evidence commands

Executed from the repository root against the exact authored workspace:

```bash
python3 reference/business-20-personal-memory-novel-v1/tests/validate_reference.py
python3 reference/business-20-personal-memory-novel-v1/tests/browser_validate.py
```

The browser validator uses an inlined local document in this restricted execution environment, launches local Chromium, checks desktop/tablet/mobile overflow, records console and page errors, rejects external runtime requests, verifies repository-local images, exercises keyboard tab switching, verifies deterministic version and truth labels, captures the required evidence images, and records the signature motion MP4 plus reduced-motion state.
