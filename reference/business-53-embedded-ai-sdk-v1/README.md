# Business 53 · Embedded AI SDK — Phase 1 visual reference

Static `UI_ONLY` visual reference for an **Embedded Capability Integration Desk / 임베드 기능 통합 설계대**.

## Product result

`HUMAN-APPROVED EMBEDDED AI INTEGRATION SPEC`

## Fictional fixture

- Host organization: Naru Civic Studio — fictional
- Host product: Naru Service Portal — fictional
- Embedded capability: convert one selected synthetic notice into a three-part plain-language assistance card
- SDK version: 0.9.0 — synthetic
- Host version: Portal 3.2 — synthetic
- Permission: selected-document read — required but not granted
- Model/provider: not connected
- Installation and execution: not performed

## Exact visual states

`cover`, `host`, `contract`, `permissions`, `fallback`, `decision`, `mobile`

## Boundary

No live host, SDK, model, account, credential, API, installation, execution, persistence, UX or backend is connected.

## Deterministic token

`eai-v1-20260730`

## Review matrix contract

- 1440×1100
- 768×1024
- 390×844
- 7 states × 3 viewports = 21 combinations

## Implementation self-check

```bash
python tests/validate_reference.py
node --check scripts/review.js
python tests/browser_self_check.py
```

These checks are implementation evidence only. Independent Local Validation, Web CTO visual approval and deployment are not performed by this branch.
