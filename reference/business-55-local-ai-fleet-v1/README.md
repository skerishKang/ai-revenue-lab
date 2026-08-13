# Business 55 · Local AI Fleet — Phase 1 visual reference

Static `UI_ONLY` reference for Proposed Business 55.

## Result

`HUMAN-APPROVED LOCAL MODEL FLEET OPERATIONS PLAN`

## Scope and authority

- Parent: #154
- Product decision: #320
- Phase 1 execution contract: #321
- Scope: `reference/business-55-local-ai-fleet-v1/**`
- Stable slug: `local-ai-fleet`
- Visual direction: `Local Model Engine Room / 로컬 모델 기관실`

This reference uses fictional devices, synthetic models and planned jobs. It performs no model download, hardware discovery, inference, SSH, remote control, scaling, billing, persistence or deployment.

## States

`cover`, `fleet`, `jobs`, `capacity`, `incidents`, `decision`, `mobile`

## Review

Open `index.html`. Tabs support click, ArrowLeft, ArrowRight, Home and End. The decision state contains the deterministic `Fleet-Inventory-to-Approved-Operations-Plan` signature motion.

## Self-check

```bash
python tests/validate_reference.py
python tests/browser_self_check.py
```

These are implementation self-checks, not independent Local Validation or UI approval.
