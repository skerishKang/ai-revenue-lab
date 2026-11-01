# StoryMemory v3.4.8

SM-091 Paid Entitlement + Settlement Boundary.

- FREE vs PAID access gate.
- Purchase intent never grants paid access.
- Only provider-verified payment reconciliation may grant entitlement.
- Refund/chargeback/revoke/expiry remove paid access.
- Purchase restore imports verified entitlements only.
- Settlement `paid` requires verified provider result and payout reference.
- Neon stores monetary durable metadata only; no Source body or knowledge DB expansion.
- Live payment collection is NOT connected in this release.
