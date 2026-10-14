# PADIEM per-product access read projection — contract, evidence, blocker (#4546)

| Field | Value |
| --- | --- |
| Parent issue | #4428 (PADIEM customer Home) |
| Assigned issue | #4546 (LOCAL1, canonical Control Plane) |
| Related UI PR | #4543 (Draft, independently drafted Home S1) |
| Verified against | `origin/main` = `007e68e1a9753b671513e0f9551f2ebfe34333d3` (2026-10-13) |
| Branch | `local1/4546-product-access-projection-261013` |
| Owner | LOCAL1 (Control Plane contract) — reviewed by CENTRAL |

## 1. Verified S0 — what the server actually authorizes today

Every claim below was read from source at the recorded path, not inferred.

| # | Question | Verified finding | Exact path |
| --- | --- | --- | --- |
| 1 | Does `/api/auth/status` carry product access? | **No.** It projects the B62 presentation session only: `{ready, authenticated, history_ready, user, session_state ∈ guest\|signed_in\|expired\|unavailable, methods}`. The handler even refuses to reclassify a transient profile-lookup failure as a guest/signed-in state. | `apps/padiem-chat/app/auth_routes.py:83-128` |
| 2 | Which product ids does the canonical authority know? | Exactly two: `b62`, `b54-padiem-claw`. There is no Engine product id and no B66 product id. | `packages/padiem-control-plane/identity_authority_worker.py:23` (`_ALLOWED_PRODUCTS`), `padiem_control_plane/engine_entitlement_producer.py:31` |
| 3 | What does the identity authority store? | `canonical_identity_subject`, `canonical_product_identity_link`, `canonical_auth_session`, `canonical_tenant`, `canonical_tenant_membership`. **No product-access / entitlement / product-membership table exists.** | `packages/padiem-control-plane/identity_authority_durable.py:195-238` |
| 4 | Is tenant membership a product access fact? | **No.** `resolve_active_memberships` / `resolve_active_tenant_membership` return canonical *tenant* membership ids/state, scoped to a tenant and a `TenantMembershipRole` (viewer/operator/approver/owner). A tenant role is not a PADIEM product grant. | `identity_authority_worker.py:339-357`, `padiem_control_plane/tenants.py:44-52` |
| 5 | Is `EntitlementSnapshot` a browser contract? | **No.** Its own docstring: "This value is an execution-policy input, not a browser assertion and not a subscription/payment record. Absence of a grant does not imply allow." The only consumer is the private Engine admission authority, which "exposes no browser contract". | `padiem_control_plane/entitlements.py:75-82`, `padiem_control_plane/engine_admission_authority.py:1-15` |
| 6 | Does the Engine entitlement producer grant customer product access? | **No.** It is a server-side execution policy: every *active canonical USER* may run `orchestration.run` for `b62`/`b54-padiem-claw`, with `ENGINE_CAN_INSTALL_ENTITLEMENT = False`. It explicitly "accepts no browser plan, role, paid-state … assertion". | `padiem_control_plane/engine_entitlement_producer.py:1-13, 31-41, 480` |
| 7 | Is there an existing per-product access route? | **No.** `app_factory.py` registers 81 `/api/**` routes; none projects per-product access to the browser. (Matches the independent audit in PR #4543.) | `apps/padiem-chat/app/app_factory.py:340+` |
| 8 | Where do model tiers / product routes live? | `PRODUCT_TIER_ROUTES`, `model_assignment_policy.PRODUCTS = {central, chat, claw, b66, b14-router}` and `tier_model_groups.SITE_PRODUCTS = {chat, claw, b66}` are **model-routing** vocabulary (which model, per tier), not user access. | `padiem_control_plane/product_tier_routes.py:210`, `model_assignment_policy.py:23`, `tier_model_groups.py:24` |
| 9 | Is PC / file authority reachable from product access? | Must not be. `ProductPcAccessPolicy` / `evaluate_pc_access` / `pc_dispatch_requirements` and `P01_APPROVAL_OWNER` own PC file READ/WRITE and execution approval under the separate #4139 family. This projection never imports them. | `padiem_control_plane/local_agent_pc_access.py` |
| 10 | Does PADIEM Engine have a customer-facing product identity? | **No.** It is a backend service boundary (`apps/padiem-ai-engine`, no HTML, no canonical product id). PR #4543 correctly renders no launch action for it. | `apps/padiem-ai-engine/app/*`, #4543 S1 |

### Conclusion of S0

No verified, browser-readable, per-product access authority exists for **any** of the three products. Therefore:

* **Chat (`b62`)**: a signed-in B62 session is a *presentation* session, not a product grant → `unavailable`.
* **Claw (`b54-padiem-claw`)**: identity links and the internal Engine orchestration policy are not customer access grants → `unavailable`.
* **Engine**: no product id at all → not requestable.

## 2. Disposition — feature OFF, contract implemented

Per the issue instruction ("if current authority cannot prove scoped product access, leave feature OFF and produce an evidence-backed blocker. No mock source promoted to product truth"), this change implements the **versioned read-only contract** and ships it **unwired**. No permission system, allow list, default grant, or temporary source was created.

New file: `packages/padiem-control-plane/padiem_control_plane/product_access_projection.py`
New tests: `packages/padiem-control-plane/tests/test_4546_product_access_projection.py`

No existing file is modified. In particular this change does **not** touch `app_factory.py` route registration (no route is mounted), `#4537` consent UI files, `#4543` home files, `#4476` Connector central-server files, or any Windows Connector code.

### 2.1 Contract surface

| Element | Value |
| --- | --- |
| Version | `PRODUCT_ACCESS_PROJECTION_VERSION = "product-access-projection-v1"` |
| States (closed) | `available` \| `denied` \| `unavailable` |
| Requestable catalog | `PADIEM_HOME_PRODUCT_IDS = ("b62", "b54-padiem-claw")` |
| Entry point | `build_product_access_projection(subject, *, product_ids=None, sources=None, now=None)` |
| Authority seam | `ProductAccessAuthoritySource.read_product_access(*, product_id, subject, now) -> ProductAccessFinding` |
| Shipped registry | `PRODUCT_ACCESS_AUTHORITY_SOURCES == {}` (immutable, empty) |
| Route headers | `{"cache-control": "no-store"}` (`PRODUCT_ACCESS_RESPONSE_HEADERS`) |

### 2.2 Answer rules (fail-closed, no exceptions)

| Situation | Projected answer |
| --- | --- |
| No authenticated canonical subject (guest) | `unavailable` / `no_authenticated_subject` |
| Anonymous or ACCOUNT subject | `unavailable` / `subject_not_eligible` |
| No source registered for the product (**current production state**) | `unavailable` / `no_registered_authority`, `authority="none"` |
| Source raises any exception | `unavailable` / `authority_read_failed` |
| Source returns a non-`ProductAccessFinding` | `unavailable` / `authority_response_invalid` |
| Source has missing/empty/invalid authority ID or reserved `authority="none"` | `unavailable` / `authority_response_invalid`; source not called |
| Finding product id ≠ requested product | `unavailable` / `authority_product_mismatch` |
| Finding subject ≠ caller subject | `unavailable` / `authority_subject_mismatch` |
| Finding authority ≠ registered source authority | `unavailable` / `authority_response_invalid` |
| Finding `expires_at <= now` (expired/revoked permission) | `unavailable` / `authority_finding_stale` |
| Finding `issued_at > now + 5 min` | `unavailable` / `authority_not_yet_valid` |
| Fresh explicit allow | `available` / `server_allow_confirmed` |
| Fresh explicit denial | `denied` / `server_denial_confirmed` |
| Source honestly answers `UNAVAILABLE` | `unavailable` / `authority_unconfirmed` (provenance kept) |
| Unknown / non-PADIEM product id requested | **refused** (`ProductAccessContractError: unknown_product_id`) |

A lookup failure is never converted into `available` or `denied`, and an absent authority is never converted into `denied`.

### 2.3 Browser payload

`ProductAccessProjection.to_browser_dict()` emits a closed key set — `{version, products}` with per-entry `{product_id, access, authority, reason, expires_at?}` — and nothing else. `authority` is a bounded server-owned source ref, `reason` a closed machine vocabulary, `expires_at` optional freshness. Owner, workspace, tenant, session, subject, profile, plan, role, credit, credential and cross-product (B66) facts have no field to ride in: `ProductAccessFinding` has exactly six fields, none of which is one of those.

### 2.4 Deliberately absent

* **PADIEM Engine** — no canonical product id; requests naming it are refused as unknown products. #4543 already renders no launch action for it.
* **B66** — not in the catalog, not named in the module source, and no input parameter (signature is exactly `subject, product_ids, sources, now`) can carry a brand, membership or quote fact. Signing in with a shared email cannot merge brands.
* **PC / P01 authority** — the module imports nothing from `local_agent_pc_access`, `engine_entitlement_producer`, or `b54_identity_bridge`, and mints no session, tenant, link or grant.

## 3. BLOCKER — the missing authority contract

To turn `unavailable` into a real gate, CENTRAL must supply a reviewed **product-access authority source**. Minimum required conditions:

1. **Owner/scope**: the source must be Control-Plane-owned and injected at a reviewed call site; no browser input, no `/api/auth/status` derivation, no email/plan/tier inference, no B66 role or tenant role, no locally cached product list.
2. **Session reconciliation**: before answering, the source must reconcile the live browser product session with the canonical Control Plane session (`resolve_current_auth_session` / `resolve_product_user_for_subject` family), and fail closed on user change, expiry, revocation, product/subject mismatch, and cross-tenant reads. Because the pure projection function accepts only a canonical subject, the future CENTRAL transport must bind a verified live session/tenant/workspace context to the source adapter on every request; the subject argument alone cannot authorize cross-tenant product access.
3. **Product-scoped authority decision (NOT APPROVED)**: independently identify an existing canonical product-access source or submit a separate architecture/security proposal if new authority storage is genuinely necessary. This #4546 projection does **not** authorize a new grants table, entitlement migration, or product-permission defaults; source truth, exact product/subject/tenant/owner scope, versioning, revocation and freshness must be reviewed first. With no verified source, retain `unavailable` and feature OFF. Never seed default-allow rows.
4. **Per-product gate review**: each product is enabled only after its own owner review — Chat (`b62`) and Claw (`b54-padiem-claw`) separately; Engine stays out until it has a canonical product id and a customer screen.
5. **Transport (CENTRAL-owned)**: one read-only GET route (e.g. `GET /api/padiem/products`) returning `PRODUCT_ACCESS_RESPONSE_HEADERS`, server-side authorization on every request, unknown ids refused, no-store. Mounting requires separate CENTRAL review because of `app_factory.py` overlaps (#4511/#3925/#3783); this change mounts nothing and activates nothing.
6. **Consumer discipline**: #4543 consumes this projection only after reviewed merge/contract; it must keep inventing nothing of its own.

Until 1–6 are satisfied, the honest customer-home answer is `unavailable` for every product, which is exactly what this contract ships.

## 4. Verification

| Check | Result |
| --- | --- |
| Targeted contract tests | `packages/padiem-control-plane/tests/test_4546_product_access_projection.py` (guest, non-eligible subject, user A/B isolation, explicit allow/denial, missing authority, source failure, malformed/mismatched/stale/premature findings, expiry on next read, unknown-product refusal, duplicate/bounded requests, closed browser payload, read-only source scan, doc gate) |
| Regression scope | no existing file modified → no Chat/Claw/B62 regression surface |
| Production | OFF (`AUTHORITY_WIRED=NO`, `CUSTOMER_HOME_ACCESS_GATE=UNVERIFIED`) |

```
PRODUCT_ACCESS_PROJECTION_CONTRACT=IMPLEMENTED
PRODUCT_ACCESS_AUTHORITY_SOURCES=0
AUTHORITY_WIRED=NO
CUSTOMER_HOME_ACCESS_GATE=UNVERIFIED
PADIEM_VS_B66=SEPARATE
PROD=OFF
```

## 5. Owner-confirmed Chat + Claw shared customer bundle (2026-10-14, CENTRAL follow-up)

**Supersedes the earlier *unwired / no customer policy* blocker above, once this
source PR is merged and deployed.** The earlier baseline audit and original #4550
contract remain accurate as historical evidence, not the new route's behavior.

- Customer-facing Chat (B62) and Claw (B54) share **one PADIEM account
  entitlement/bundle**. No separate per-product opt-in, extra login or paid
  membership inference is introduced. **B66** remains a separate account and
  customer-scope; future product groupings are intentionally undecided.
- The product-access rule is **only a Home availability projection**, not a
  new P01/PC/Drive/file WRITE capability, model tier, admin or billing grant.
  Existing execution/usage enforcement remains unchanged.
- The sole reviewed source for the bundled Home display is a server-verified
  **ACTIVE B62 canonical USER session**: signed cookie user ID, current
  owner-scoped HistoryStore user row, existing shadow record, and the live
  Control Plane session must match, with current revision and effective expiry
  enforced by `resolve_refreshed_session`. Expired/revoked/stale/foreign
  account or missing identity service **never projects `available`**.
- B62-authenticated bundle policy is authoritative for the **bundle**, not
  a claim that a separate B54 product session or separate B66 entitlement
  was minted. The canonical bundle source is injected **at the server route**,
  while the generic projection module's default registry stays EMPTY/OFF.
- Versioned GET `/api/home/product-access` returns only `b62` and
  `b54-padiem-claw`, closed `{version,products}` payload, no-store private
  caching, no owner/tenant/session data. No query-driven product/tenant override,
  no public POST. Any source or session uncertainty returns a bounded error,
  not an invented allow.
- The Home UI #4543 needs a separately reviewed consumer integration after
  this backend route merges; a standalone preview or signed-in presentation
  cookie cannot be called production-granted access before E2E readback.

**New source paths:** `apps/padiem-chat/app/home_product_access_routes.py`,
the exact GET mount in `app_factory.py`, and
`apps/padiem-chat/tests/test_4546_home_chat_claw_bundle.py`.

**Local targeted verification:** 80/80 PASS across bundled route, existing
#4546 projection contract and B62 auth/history tests; no model invocation,
production change or Connector/B66 modification.

`SHARED_CHAT_CLAW_POLICY=OWNER_CONFIRMED | B66_ISOLATED=YES |`
`SOURCE_ROUTE=IMPLEMENTED_IN_PR | PROD_SERVED=NOT_YET_VERIFIED |`
`ADVANCED_APPROVAL_UX=DEFERRED`.
