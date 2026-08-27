# Business 38 · AI Exercise Coach — Phase 1 Visual UI Reference

Status: `UI_REVIEW_READY` · `NOT_VALIDATED_BY_LOCAL` · `NOT_DEPLOYED_PENDING_UI_APPROVAL`

This directory is a static, synthetic, UI-only reference for **AI 운동 코치 / AI Exercise Coach**. It converts one fictional adult beginner profile into a human-reviewed adaptive movement-plan presentation while preserving explicit non-medical, non-rehabilitation, no-camera and no-biometric boundaries.

## Exact states

`cover`, `profile`, `assessment`, `session`, `form`, `adaptation`, `mobile`

No additional visual state is implemented.

## Run

Serve this directory from localhost, then open `index.html`.

```bash
python -m http.server 4173 --directory reference/business-38-ai-exercise-coach-v1
```

The implementation uses local HTML, CSS, JavaScript and SVG only. It performs no runtime requests outside this directory.

## Fixture

- Jiyu — fictional adult
- 25-minute low-impact strength and mobility session
- beginner — synthetic
- no jumping, no floor transitions, quiet apartment
- chair and light resistance band
- reviewed practice, not medical care

## Phase boundary

No camera, pose estimation, wearable, biometric, health record, medical screening, diagnosis, treatment, rehabilitation, live coaching, repetition tracking, account, persistence, analytics, payment, model/provider API or database is present.

## Review status

Implementation self-check evidence is under `evidence/`. It is not an independent `LOCAL_VALIDATION_PASS`, does not constitute `UI_APPROVED`, and does not authorize deployment, UX or backend work.
