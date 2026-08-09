# Browser and Static Check Commands

```bash
python -m http.server 4173 --directory reference/business-15-global-ai-newsroom-v1
python evidence/validate_reference.py  # local helper used outside the committed scope
```

Executed checks are recorded in `validation.json` and the final worker report.

Required browser targets:

- 1440 × 1100
- 768 × 1024
- 390 × 844
- reduced-motion desktop
- Signal Convergence motion capture
