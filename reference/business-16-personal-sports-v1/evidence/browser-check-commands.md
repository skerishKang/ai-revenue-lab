# Browser validation commands

The exact Phase 1 reference folder was served locally and checked in Chromium.

```bash
python3 -m http.server 4173 --directory reference/business-16-personal-sports-v1
python3 /tmp/validate-business-16.py
```

The temporary validator checked all seven states, 1440×1100 / 768×1024 / 390×844 horizontal overflow, keyboard state movement, visible focus, console/page errors, failed local assets, external runtime requests, deterministic asset queries, reduced motion and synthetic-data labels.
