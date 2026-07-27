# Proposed Business 26 — Company Memory / 회사 기억

Phase 1 visual UI reference for Issue #227.

## Product object

- Company Memory Thread / 회사 기억 실마리
- Institutional Memory Atlas / 회사 기억 아틀라스
- Synthetic company: 새벽선 로보틱스, 2018–2026
- Synthetic project: Project HARBOR

## Scope

This workspace is `UI_ONLY`. It contains seven visual review states, repository-created synthetic assets, deterministic review controls, and a product-specific motion preview. It does not implement ingestion, search, AI answers, authentication, permissions, persistence, connectors, export, deployment, UX completion, or backend behavior.

## Run locally

Open `index.html` in a browser, or run the deterministic validators:

```bash
python tests/validate_reference.py
python tests/browser_validate.py
```

The browser validator uses an inlined Chromium document when local URL navigation is unavailable. Production files retain repository-local relative paths.

## Final worker state

```text
UI_REVIEW_READY
NOT_DEPLOYED_PENDING_UI_APPROVAL
```
