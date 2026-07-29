# Business 40 · Emergency Urgency AI — Phase 1 visual UI reference

`Urgency Evidence Review Desk / 긴급도 근거 검토 데스크` is a static, synthetic, UI-only review surface. It demonstrates how a fictional incident report can be organized into a **HUMAN-REVIEWED URGENCY SUPPORT RECORD** without assigning a final priority or initiating any operational action.

## Fixed state contract

Exactly seven states are implemented: `cover`, `report`, `indicators`, `conflicts`, `review`, `handoff`, `mobile`.

## Boundaries

- No autonomous triage or final-priority output.
- No medical diagnosis, threat prediction, dispatch or resource allocation.
- No live call, audio, location, sensor, biometric, health-record, model, provider, storage, analytics or database connection.
- All people, locations, statements, timestamps, indicators, corrections and decisions are synthetic.
- Missing information is retained as missing information, never treated as negative evidence.

## Local review

```bash
python3 -m http.server 4173 --directory reference/business-40-emergency-urgency-ai-v1
node reference/business-40-emergency-urgency-ai-v1/tests/static-contract.mjs
python3 reference/business-40-emergency-urgency-ai-v1/tests/browser_validation.py
```

The browser validator requires Playwright and Chromium. Implementation self-check does not constitute independent `LOCAL_VALIDATION_PASS`.

## Deployment target after explicit approval

- Business ID: `40`
- Project: `ai-revenue-business-40-emergency-urgency-ai`
- Source: `reference/business-40-emergency-urgency-ai-v1`
- Expected production: `https://ai-revenue-business-40-emergency-urgency-ai.pages.dev/`

Current phase state: `UI_REVIEW_READY`, `NOT_VALIDATED_BY_LOCAL`, `NOT_DEPLOYED_PENDING_UI_APPROVAL`, `UX_NOT_STARTED`, `BACKEND_FROZEN`, `DO_NOT_MERGE`.
