# Migration boundary

W2 introduces the first product-local PostgreSQL persistence contract for generalized **EARNING OPPORTUNITY** trust, inventory, evidence, versioning, and review data.

`0001_w2_generalized_opportunity.sql` persists the accepted W1 source/policy/gate semantics and adds immutable source snapshots, optional merchants, stable opportunity identities (`offers`), immutable opportunity versions, field-level evidence, requirements, generalized compensation components, windows, material-change history, and auditable review records.

Key W2 invariants:

- `offers` / `offer_versions` are implementation aliases for generalized earning opportunities; this is not a reward-only schema.
- `merchant_id` is nullable because surveys, AI/data work, testing, and remote projects may have no merchant.
- `acquisition_mode`, source lane, access mode, policy decisions, and collection gates remain distinct.
- `opportunity_class_hint` is provider metadata only and is not canonical opportunity classification.
- source snapshots and opportunity versions are append-only historical truth; material changes create a new version and review path.
- unknown payout, probability, eligibility, timing, supply, or similar values remain `NULL`; they are never coerced to zero or guaranteed values.
- probability/confidence values are constrained to `0..1` when present, monetary/time fields are non-negative when present, and windows cannot end before they start.
- prize/draw semantics are not guaranteed compensation.
- extraction/parsing alone never makes a record `VERIFIED` or `LIVE`; applicable human review remains required.

This W2 slice intentionally does **not** create users, preferences, recommendation runs/items, outcome tracking, affiliate conversion accounting, wallet/payment custody, live collectors, partner credentials, deployment configuration, or Portfolio records.
