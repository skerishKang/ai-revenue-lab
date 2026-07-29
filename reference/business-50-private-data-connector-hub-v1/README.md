# Business 50 · Private Data Connector Hub

Phase 1 `UI_ONLY` static visual reference for the wholly fictional **Haneul Works** fixture.

## Product result

```text
HUMAN-APPROVED PRIVATE DATA CONNECTOR ACCESS SPEC
```

This reference shows how an authorized-purpose request is separated into requester, data-owner and connector-operator authority; reduced to least-privilege scope; mapped at field level; bounded by credential, retention, deletion, audit and revocation controls; and recorded as a human-approved connector-readiness specification.

It does **not** connect to a live system, collect credentials, display secrets, read private data, extract content, store data, run analytics or connect data to model training.

## Exact states

```text
cover
request
scope
mapping
controls
decision
mobile
```

The seven state buttons are visual-review controls only. They do not constitute accepted UX.

## Local review

From this directory:

```bash
python3 -m http.server 4173
```

Then open `http://127.0.0.1:4173/`.

## Validation

```bash
python3 tests/check_static.py
python3 tests/validate.py
```

`tests/validate.py` launches local Chromium against an HTTP server and checks the 7 × 3 viewport/state matrix, tab/panel accessibility mapping, keyboard navigation, local assets, overflow, motion completion authority, replay determinism, reduced motion, required scope boundaries and zero external requests.

## Fixed boundaries

```text
VISUAL REFERENCE ONLY
CONNECTOR READINESS — NOT CONNECTED
NO LIVE PRIVATE DATA, CREDENTIAL, EXTRACTION, OR MODEL-TRAINING CONNECTION
UX_NOT_STARTED
BACKEND_FROZEN
```
