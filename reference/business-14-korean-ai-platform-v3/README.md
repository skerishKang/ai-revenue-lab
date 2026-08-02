# Business 14 · Visual Upgrade v3

Status: competitive frontend evidence, Draft.

Authority: Issue #380.

## Product decision

Business 14 is beginner-first, not beginner-only. The default experience lets a Korean individual user estimate cost and make a first request without understanding tokens, BYOK, Provider routing or SDKs. Developer mode preserves direct API and routing controls.

## Included evidence

- Easy / Developer mode
- Beginner-first first request
- Model pricing contract with KRW and USD
- Verified, catalog, configured and unknown price states
- Cost calculator
- Free / PAYG / Personal Plus product architecture
- Credits and budget controls
- Mobile-specific table transformation
- Deterministic interactions only

## Local review

```bash
python -m http.server 8140 --bind 127.0.0.1
```

Open `http://127.0.0.1:8140/`.

## Truth boundary

No real Provider calls, payment, authentication, billing, secret storage or live price synchronization occur in this reference. Prices and exchange rates are dated product-evidence snapshots and are labeled in the UI.
