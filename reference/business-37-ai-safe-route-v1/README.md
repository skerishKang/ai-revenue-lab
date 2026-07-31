# Business 37 · AI Safe Route

Phase 1 `UI_ONLY` static visual reference for a fictional safer-route comparison brief.

- Product result: `HUMAN-REVIEWED SAFER ROUTE BRIEF`
- Fixture: Morae City, entirely synthetic
- Seven states: cover, context, routes, evidence, constraints, handoff, mobile
- No live map, routing, tracking, crime data, alerting or emergency connection

Run checks:
```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
```
