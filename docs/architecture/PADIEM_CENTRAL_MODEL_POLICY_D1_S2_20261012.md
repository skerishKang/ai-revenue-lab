# PADIEM 중앙 모델 정책 S2 — 공통 D1 원장 (코드 준비, 운영 미적용)

Owner issue [#4453](https://github.com/skerishKang/ai-revenue-lab/issues/4453), parent #4428. Follows S1 Control Plane policy #4454 and B14 full inventory #4473.

**Status: CODE PREPARED; MIGRATION 039 NOT APPLIED; OWNER RBAC NOT PROVISIONED; POLICY APPLY NOT ROUTED; ALL LIVE B14 AND PRODUCT GRANTS UNCHANGED.**

## Why

A registered B14 model must be registered once and discovered centrally. The prior S1 policy authority was a synchronous, local SQLite proof only. This slice establishes the **asynchronous Cloudflare D1** persistence port in the existing canonical `PADIEM_CHAT_DB` account database. It does NOT create another model registry or credentials. Product routing is intentionally not connected until owner-approved rollout.

## Schema

`apps/padiem-chat/migrations/039_central_model_policy.sql` is a **new, independently approved, additive migration**.

- `central_model_policy_state` — tenant/workspace revision CAS; **no seed rows, no automatic activation**.
- `central_model_policy_rules` — `(workspace_id, product, tier, model_id)` with explicit `allow`/`block` only; `inherit` means absence.
- `central_model_policy_nonces` — one-use 32-char verification nonces, scoped per tenant; duplicate rejection.
- `central_model_policy_history` — immutable per-revision full snapshot (metadata only) for audited restoration.
- `central_model_policy_audit` — actor user ID, operation, timestamp and bounded policy diff, no prompt/response/secret.

All models default **unassigned**. Central `block` overrides product `allow` in the previously merged policy evaluator. The D1 store does not change actual B14 enabled flags or deliver grants to Chat, Claw, B66, or Router. Existing B66 D1 policies and memberships remain untouched and retain their existing authority.

## Atomic adapter

`app/central_model_policy_d1.py`: `D1CentralModelPolicyStore` uses the existing trusted host `PADIEM_CHAT_DB` `prepare/bind/first/run/batch` contract.

- `snapshot`, `previous_revision`, `nonce_consumed`, `audit` are bounded and tenant-scoped.
- `commit` requires an already-verified `VerifiedModelAdminGrant`, exact actor/workspace scope, valid exact B14 `CatalogModel` input, 1–20 changes, expected revision, unique one-use nonce, and an atomic D1 `batch()`.
- CAS `UPDATE` is followed immediately by a `changes()`-guarded nonce `INSERT` with NOT NULL constraint: stale CAS forces **transaction rollback**, not a successful partial write. Full snapshot history and audit are in the **same batch**.
- B14 owner excluded/offline models cannot receive new `allow` grants; `block` may be stored without turning on a route.
- **NO public apply route is provided.** A future operator APPLY controller must validate the **signed 5-minute actor/workspace/scope/nonce/revision-bound S1 confirmation receipt on the server**, CSRF, rate limit and current B14 readiness; product enforcement and policy revision propagation must be separately proven. Direct customer changes are prohibited.

## Safe read visibility only

The existing `create_app(..., d1_binding=...)` composes `D1CentralModelPolicyStore` **read-only** when a valid batch-capable D1 binding is available. No request-time DDL is attempted.

A signed-in, **separately verified global model administrator** may query the existing `GET /api/admin/models/snapshot` endpoint, which reports `products.central.status=stored_only`, `revision`, `rule_count`, `runtime_enforced=false`, `write_enabled=false`, and canonical rule metadata. If migration 039 is missing or D1 fails, `status=unavailable` without claiming zero rules. Anonymous/product-only admins remain 401/403 and cannot reach D1 data. The UI's collapsed "연결 정보" reads "저장 원장만 연결 · 실제 실행 미적용" rather than green runtime ON. The existing preview-only POST is unchanged.

## Release blockers and acceptance

1. **Owner Google identity:** production `PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL` is separately provisioned with the owner's explicit verified account decision; never infer from B66 admin or OAuth email submitted in browser. Until then requests remain 503/403 fail-closed.
2. **D1 migration:** create explicit independently reviewed Cloudflare gate to back up/check/execute migration `039` on the exact canonical DB ID and verify schema read-back. **Do not call `wrangler d1 execute --remote` as a side effect of code deployment.** Schema rollout approval separate from model enablement.
3. **Signed APPLY:** implement end-to-end preview → confirm with S1 HMAC receipt, replay denial, expected-revision CAS, CSRF and audit, requiring server Google admin. Initially store-only; product entitlement and B14 last-hop enforcement remain OFF until separate tests.
4. **Runtime integration:** verified owner chooses rollout tier/scope, B66 parity migration adapters and P01 safeguards proven, exact-model no fallback, representative real completion. Per-model limits/health flow and scoped product-admin roles are separate features, not part of this patch.
5. **Current tests:** migration empty by default, SQLite-backed D1 batch execution, CAS conflict forced rollback and immutable audit, tenant/scope denial, owner exclusion, rollback revisions, canonical admin read-only snapshot + unauthorized isolation, existing backend & Chromium.

```text
D1_MIGRATION_039=SOURCE_ONLY
PRODUCTION_SCHEMA_APPLY=NO
GLOBAL_OWNER_ADMIN_PROVISIONED=NO
SIGNED_APPLY_ROUTE=ABSENT
LIVE_MODEL_POLICY_WRITE=OFF
PRODUCT_RUNTIME_ENFORCEMENT=UNWIRED
B14_MODEL_FLAGS_UNCHANGED=YES
```
