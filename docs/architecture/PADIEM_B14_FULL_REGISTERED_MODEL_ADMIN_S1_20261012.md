# PADIEM central model administrator — full B14 registered inventory (S1 read-only)

Related: #4453, parent #4428. The deployed admin UI S0 previously displayed only B66's owner-allowed, credential-ready subset, leaving the registered OFF models invisible.

## Authority and data flow

- B14 remains the one canonical model registration and provider/credential authority: `GET /api/pilot/models` already supplies `registered_routes` (all registrations, including OFF) and `catalog` (B14-enabled registrations).
- The **existing** trusted B14 Service Binding/transport reads that single metadata GET and strips non-UI fields. No new B14 endpoint, credential, registry, provider request, network origin or model registration.
- Backend `list_registered_models()` returns exact model ID, derived display name, provider ID, B14-enabled presence, owner exclusion flag and bounded capabilities. It never exposes upstream URL/model, prices, binding name, API key or credential readiness. **B14 enabled is not an actual inference success or a product entitlement.**
- Central snapshot returns `b14.registered_models`, `complete_registration_inventory`, `registered_count`, `enabled_count` only for independently **globally authorized** administrators. Existing `b14.models` remains the ready, owner-allowed subset for preview. Registry transport inconsistency, metadata errors or missing full inventory => `registered_models=null`, `registered_count=null` and `complete_registration_inventory=false`, never fake zero or leaked provider errors.
- UI searches all registrations with an explicit ON/OFF/owner-excluded display; OFF or owner-excluded registration can be inspected but **cannot be proposed for preview, changed to ON or executed**. The only POST remains the existing non-mutating `/api/admin/models/preview`; backend separately enforces eligibility.
- The UI does not turn an ON B14 model into an actual Chat/Claw/B66 grant. It does not add a second registry. No automatic fallback, unapproved model selection or customer-facing model list change.

## Tests and gate

- Full B14 metadata transport unit tests: OFF visibility, owner exclusion, duplicate/provider/unknown catalog rejection, no secrets/provider POST.
- API tests: signed global-admin inventory, old selectable subset retained, full roster inconsistent/unavailable handling, anonymous 401 and product admin 403, unavailable/owner-excluded preview rejection.
- Chromium at 1440/768/390: all model statuses visible; OFF/excluded edit controls disabled; active choice still previews; no mutating API; no horizontal overflow.
- Keep centralized model policy S1 source-only; server-side D1 adapter, real APPLY/rollback API, product runtime grants/limits and global RBAC provisioning are S2 and are **NOT** enabled by this change.

## Operational prerequisite

`PADIEM_CENTRAL_MODEL_ADMIN_GOOGLE_EMAIL` is not provisioned in current documented production settings. The system correctly reports `central_admin_not_configured` when a signed-in user lacks host-configured global authority; do **not** infer global access from B66 admin or user email. Explicit owner-approved, independently verified account/environment binding and exact-worker deployment gate must precede real admin read validation. No Cloudflare secrets are read or modified by this S1 patch.

`REGISTERED_B14_ROSTER=READ_ONLY` `CUSTOMER_SELECTION=UNCHANGED`
`B14_ENABLED_NOT_PRODUCT_READY=ENFORCED` `PRODUCTION_POLICY_APPLY=OFF`
