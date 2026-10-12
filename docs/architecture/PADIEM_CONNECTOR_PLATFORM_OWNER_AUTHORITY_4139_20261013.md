# #4139 PADIEM Connector — platform-level ownership and product adoption decision

**Decision:** PADIEM Connector belongs to the **PADIEM canonical Identity / Control Plane**, NOT PADIEM Claw.  
**Scope:** PADIEM Chat (B62), Quote (B66), Claw (B54), Engine, and future explicitly onboarded products.  
**Status:** Control Plane source boundary refactored; registration UI/transport/live feature OFF.  
**Existing baseline:** `PADIEM_CONNECTOR_PLATFORM_DECISION_20261012.md` and merged product access contract #4429.

## Target architecture

```text
PADIEM account and integrated My Devices / operator console
    ↳ existing canonical Identity DO: subject, tenant, login and OWNER consent
    ↳ existing canonical Broker DO: device binding, challenge, revoke, ONLINE
    ↳ common ProductPcAccessPolicy (#4429): per-product entitlement, device visibility, P01
        ├── B66 Quote: approved file/quotation tasks
        ├── PADIEM Claw: approved general PC tasks
        ├── PADIEM Chat: approved PC tools when connected
        └── PADIEM Engine: approved engine tasks
                      ↓
             ONE Windows PADIEM Connector per computer
```

Device registration is account/owner scoped **once** and is not stored independently
by B66, Claw, Chat or Engine. One broker device identity can be listed in each
product **only if** that product's independent, default-off access policy allows
it. Model registration/selection belongs to B14 and cannot authorize PC actions.
P01 READ, WRITE and individual WorkTickets remain distinct, with no implicit
permissions from pairing or plan grade.

## Source refactor in CENTRAL Draft #4476

The original #4476 identity consent RPC contained a hardcoded
`session.product_id == "b54-padiem-claw"`. Its **policy owner** now lives in
`padiem_control_plane.connector_enrollment_owner_policy`, which is a
Control Plane shared registration admission contract. The existing private
Identity DO resolves the signed canonical session and the active canonical
tenant OWNER membership; the shared policy validates these facts and enforces
a small, explicit list of **reviewed login bridges**.

**Initially reviewed session bridge:** `b54-padiem-claw` **only**.
That is a staging security constraint, **NOT the scope of the Connector
product**. The remaining PADIEM products share the central Broker and
product-access model already, but they MUST NOT gain grant/revoke privilege
solely because a B14 model, same email string, page flag, claim or
`product_id` is supplied by a client.

Other product bridges require their own authenticated *current product user →
canonical Identity session and tenant* verification. In particular the
currently deployed Identity worker advertises only `b62` and
`b54-padiem-claw` in `_ALLOWED_PRODUCTS`; **B66/Engine session
eligibility is not established**. Product onboarding must implement reviewed
Identity support and signed login equivalence before the central allowlist
can expand. Do **not** enlarge the product set directly from a browser.

Existing B54 `/api/claw/connector/enrollments/*` handlers are **transitional,
unmounted** adapters; they do NOT own registration, Broker credentials,
product grants, or global device status. They must eventually delegate to a
single authenticated central enrollment API and account-level Devices UI,
rather than being copied as independent B66 or Engine endpoints.

### Recommended operator/customer surfaces — not yet implemented

- **Customer PADIEM account → Connected computers:** one authenticated device
  directory, install/connect/revoke, true Broker lifecycle/presence,
  current identity/tenant scope, user-consent records, audit and
  re-enrollment (owner-scoped, no credentials).
- **PADIEM integrated admin:** per-product PC entitlements, access audit and
  rollout gates, subject to existing central admin RBAC. Model administrator
  permissions or B66 site administrator permissions alone do not give
  visibility or control over customer PC credentials.
- **Product UIs (B66/Claw/Chat/Engine):** render authorized, product-scoped
  projections through merged `ProductPcAccessPolicy`; request actions with
  separate P01 and capability approval. No local connector installs,
  code redemption or product-specific PC binding database.

### Safe migration plan

1. **Source contract (current Draft):** centralize owner login policy and
   prove signed user + active canonical OWNER + default-off product access;
   preserve current B54 bridge only and source-only routes.
2. **Identity bridging:** separately audit each product's authenticated
   canonical current-session bridge (B62 then B66/Engine); no guessed
   email/provider subject equivalence, no implicit multi-product login.
3. **Platform account UI/route:** introduce a reviewed account-wide
   `/api/padiem/connector/*` owner API with proper CSRF for browsers and
   device-gateway authentication for non-browser traffic. Reuse the
   existing Identity/Broker Service Bindings; do not open duplicate Claw/Quote
   public enrollment endpoints. Do not mount until complete security review.
4. **Owner scope migration:** verify product-neutral account/workspace
   authority. The current read-only legacy `b62` connector-context row
   is a **candidate, not an approved global shared scope**; keep the
   `CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED` flag disabled.
5. **Single redemption owner:** choose ONE verified outbound Broker redeem
   path and enforce current canonical consent and owner/tenant at redeem.
   Existing server-side and PC-side redeem must NOT both consume a challenge.
6. **Release proof:** exact-head CI, signed-in owner and product-specific
   access tests, Windows DPAPI installation + authenticated ACK, revoke,
   P01 grant boundary, real #3099 multi-product Windows E2E; only then
   staged merge/deploy/production permission changes.

## Immutable security invariants

```makefile
OWNER_OF_PC_REGISTRATION=CANONICAL_PADIEM_CONTROL_PLANE
OWNER_OF_DEVICE_LIFECYCLE=CANONICAL_LOCAL_AGENT_BROKER
PRODUCT_ACCESS_OWNER=EXISTING_PRODUCT_PC_ACCESS_POLICY
B14_PC_AUTHORITY=NO
ONE_PC_REGISTRATION_ALL_PRODUCTS=TARGET_ARCHITECTURE
CROSS_PRODUCT_AUTOMATIC_GRANT=NO
B54_BROWSER_ROUTES=TRANSITIONAL_UNMOUNTED
REVIEWED_INITIAL_LOGIN_BRIDGE=B54_ONLY
B62_LOGIN_ENROLLMENT=NOT_APPROVED
B66_LOGIN_ENROLLMENT=NOT_APPROVED
ENGINE_LOGIN_ENROLLMENT=NOT_APPROVED
PRODUCT_NEUTRAL_SCOPE_SECURITY_APPROVAL=PENDING
PC_WORK_AUTHORIZED_BY_REGISTRATION=NO
MIGRATIONS_INSTALLED=NO
REAL_WINDOWS_E2E=NOT_PROVEN
READY=NO
MERGED=NO
PRODUCTION=OFF
```
