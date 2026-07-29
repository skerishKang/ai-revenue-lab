# Business 36 · AI Women Safety — Phase 1 visual UI reference

Static, synthetic, `UI_ONLY` visual reference for the **Personal Safety Coordination Desk** direction.

## Product result

`HUMAN-REVIEWED SAFETY RESPONSE BRIEF`

The reference separates user report, observable context, interpretation, missing evidence and unresolved uncertainty. It presents bounded choices and trusted-contact coordination without predicting crime, intent, a dangerous person or a dangerous place.

## Exact states

`cover` · `situation` · `signals` · `options` · `support` · `handoff` · `mobile`

## Run locally

```bash
python3 -m http.server 4173
```

Open `http://127.0.0.1:4173/` from this directory.

## Self-check

```bash
python3 tests/validate_reference.py
python3 tests/browser_self_check.py
```

Implementation self-check is not independent `LOCAL_VALIDATION_PASS`.

## Boundaries

- synthetic fictional fixture only;
- no live location, surveillance, tracking, camera, microphone or message ingestion;
- no identity matching, danger score, crime prediction or automated action selection;
- no emergency call, alert, dispatch, legal advice or medical response;
- no account, storage, analytics, provider/model API or backend;
- `NOT A GUARANTEE OF SAFETY`;
- `EMERGENCY RESPONSE OUT OF SCOPE`.

## Deployment target after approval

- business_id: `36`
- project_name: `ai-revenue-business-36-ai-women-safety`
- source_directory: `reference/business-36-ai-women-safety-v1`
- expected production: `https://ai-revenue-business-36-ai-women-safety.pages.dev/`

No deployment is performed by this Phase 1 implementation.
