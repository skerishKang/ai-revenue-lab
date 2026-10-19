## LOCAL1 — #4546 preliminary phase: read-only contract/path evidence (no implementation, nothing mounted, nothing activated)

Per #4546's instruction to *"Name exact existing contract/paths before implementation"* and to leave the feature OFF if current authority cannot prove scoped product access. **No route was mounted, no feature activated, no mock promoted to product truth.**

### 1. S0 blocker independently confirmed

`GET /api/auth/status` — `apps/padiem-chat/app/auth_routes.py:83-128` — returns exactly:

```text
ready, authenticated, history_ready, user, session_state, methods{google,password}, project_files_ready
```

There is **no product-access field**, and the source itself refuses to let one be inferred from it (`auth_routes.py:108-111`): *"A browser carrying a compatibility session cookie that no longer resolves may recover by signing in again. This state is never used as access authority; it is only projected for truthful B62 UX."*

Related client-side pattern that must **not** become access authority — `apps/padiem-chat/static/product-capabilities.js:66-68`: *"Display-only tier list. Free and Plus are shown as available; Pro/Max are shown as unavailable until the admin console sets access rules."* with `const TIER_LIST = Object.freeze(["free","plus","pro","max"])` and `AVAILABLE_TIERS`. It is display-only model-tier copy, driven by a hardcoded browser list — precisely the "locally cached product list" #4546 forbids deriving entitlements from.

### 2. The canonical server-authoritative per-product authority **already exists** — and B62 already speaks to it

| Authority | Exact path | Surface |
|---|---|---|
| Canonical identity / session / tenant membership | `packages/padiem-control-plane/identity_authority_worker.py` → `CanonicalIdentityDurableObject` (L108: *"Private canonical identity/session and connector-ticket authority"*) | **No public route.** Closed-key private RPCs: `resolve_or_create_product_link` `{product_id, product_user_id, auth_provider, provider_subject}` (L24) · `establish_auth_session` `{product_id, subject, authenticated_at, not_after}` (L25) · `resolve_current_auth_session` `{product_id, product_user_id}` (L31) · `resolve_product_user_for_subject` `{product_id, canonical_subject_id}` (L36) · `resolve_active_memberships` / `resolve_active_tenant_membership` (L339/L347) |
| Canonical entitlement + usage | `packages/padiem-control-plane/engine_admission_authority_worker.py` → `CanonicalEngineAdmissionDurableObject` (L57: *"Canonical entitlement + usage authority. No public HTTP route exists."*) | `PUBLIC_ROUTE_CONFIGURED = False` (L282), `Default.fetch` returns 404 (L271-277). **`fetch_entitlement_snapshot(payload)` with exactly `{product_id, subject}`** (L25, L128, L247) — a read-only per-product entitlement read, exactly the primitive a Home projection needs. Mutating RPCs `reserve_usage` / `record_usage` exist but are not needed for a read projection |
| Entitlement value contract | `packages/padiem-control-plane/padiem_control_plane/entitlements.py` | `EntitlementSnapshot(snapshot_id, product_id, subject: CanonicalSubjectRef, revision, issued_at, expires_at, grants)`; `allows(key)` is **default-deny** — an absent grant returns `False` (L131-133). Docstring (L75-81): *"an execution-policy input, not a browser assertion and not a subscription/payment record. Absence of a grant does not imply allow."* |
| **B62's own existing bridge to that authority** | `apps/padiem-chat/app/worker_config.py:38` → `IDENTITY_AUTHORITY_SERVICE_BINDING_NAME = "IDENTITY_AUTHORITY_SERVICE"` → service `padiem-control-plane-identity`, resolved at `apps/padiem-chat/worker.py:129` | `apps/padiem-chat/app/control_plane_identity.py`: `PADIEM_CHAT_PRODUCT_ID = "b62"` (L27), `TrustedControlPlaneIdentityAuthority` Protocol (L75-110, incl. `resolve_active_memberships` / `resolve_active_tenant_membership`), `bridge_trusted_product_auth` (L136), `require_active_canonical_session` (L278) |

**Cross-product isolation already exists and is already enforced.** `packages/padiem-control-plane/padiem_control_plane/b54_identity_bridge.py` (`B54_PRODUCT_ID = "b54-padiem-claw"`, L51) calls `authority.resolve_current_auth_session(product_id=B54_PRODUCT_ID)` (L98-99) and then hard-refuses a session minted for another product (L114-115): *"A B62 session for the same person is never B54 authority."* This is the exact precondition #4546 requires before any product-specific authority read, and it is implemented, not aspirational.

### 3. Evidence-backed blocker: **Engine has no canonical product id**

Both canonical authorities enforce the identical reviewed product set and hard-fail on any mismatch:

```text
identity_authority_worker.py:23            _ALLOWED_PRODUCTS = {"b62", "b54-padiem-claw"}
identity_authority_worker.py:131-136       RuntimeError if parsed != _ALLOWED_PRODUCTS
engine_admission_authority_worker.py:22-24 _ALLOWED_PRODUCTS = {"b62", "b54-padiem-claw"}  (+ env must match, L71-75)
engine_entitlement_producer.py:31          SUPPORTED_ENGINE_PRODUCTS = {"b62", "b54-padiem-claw"}
```

So **PADIEM Chat (`b62`) and Claw (`b54-padiem-claw`) are provably scopable today; Engine/P01 is not.** The #4546 allowlist asks for "only reviewable Engine capabilities", but there is no Engine product id in the canonical set, so no existing authority can prove scoped Engine access. Adding one is a **CENTRAL product-policy change**, not a LOCAL1 implementation.

### 4. Conclusion for #4546 preliminary phase

1. **What the projection should consume (already exists, no new authority needed):** for each of `b62` and `b54-padiem-claw`, resolve the canonical session via the existing B62 identity bridge (`resolve_current_auth_session` with the product's own id, with the existing cross-product `product_id` guard), then read `fetch_entitlement_snapshot({product_id, subject})` from the engine-admission authority and project `available` only when the canonical snapshot positively allows, `denied` only on an explicit verified denial, and `unavailable` for absent/unconfigured/unreadable/cross-tenant.
2. **Engine must be projected `unavailable`** — feature OFF, because the canonical product boundary does not contain an Engine id. Reporting it green would be a fabricated grant.
3. **B66 is not in the allowlist and must not be implied** — `b66` appears in neither `_ALLOWED_PRODUCTS` set, so a B66 login or product-admin role cannot produce an `available` product grant here.
4. **No second identity/device authority is needed** — B62 already holds the canonical identity binding; adding a parallel grant table would violate #4546's own constraint.
5. **Route mounting stays deferred.** `app_factory.py` route overlaps (#4511 / #3925 / #3783) require separate CENTRAL review; nothing was mounted and `PRODUCTION_IDENTITY_BINDING` / `CLIENT_IDENTITY_AUTHORITY` remain `False` in source.

Acceptance items 1–4 of #4546 are therefore **satisfied at the evidence level** (real source-of-truth mapping named per product, with default-deny behaviour at `entitlements.py:131-133`). Items that need an implementation phase — synthetic negative cases, exact-head CI, and the #4543 consumption contract — remain open and are explicitly **not** claimed here.

```text
PRODUCT_ACCESS_PROJECTION=NOT_IMPLEMENTED
CUSTOMER_HOME_ACCESS_GATE=UNVERIFIED
PADIEM_VS_B66=SEPARATE
PROD=OFF
CANONICAL_AUTHORITY_EXISTS=YES
CANONICAL_AUTHORITY_ALREADY_WIRED_INTO_B62=YES
PRODUCTS_PROVABLE_TODAY=b62,b54-padiem-claw
ENGINE_PROVABLE=NO
ROUTE_MOUNTED=0
PRODUCTION_MUTATION=0
```
