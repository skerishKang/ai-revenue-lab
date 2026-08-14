# Business 34 · AI Dubbing Studio Phase 1 Visual Reference

Static UI-only reference for `HUMAN-APPROVED LOCALIZED MASTER`.

## Fixture
- The Lantern Room — synthetic, 42 seconds
- Korean source → English localized master
- Mira and Jun — fictional
- repository-created synthetic source and synthetic voices only

## Review
```bash
python3 -m http.server 8000 --bind 127.0.0.1
python3 tests/validate_static.py
python3 tests/validate_browser.py
```

No upload, playback, recording, generation, voice cloning, provider call, account, storage or release occurs.
