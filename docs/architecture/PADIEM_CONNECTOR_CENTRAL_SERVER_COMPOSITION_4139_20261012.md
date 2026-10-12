# #4139 CENTRAL — Connector S1 server composition and HTTP product handlers

**2026-10-12 KST · SOURCE-ONLY / DEFAULT OFF · Stacked on LOCAL1 PR #4438**

## Why this slice exists

LOCAL1 #4438 implements canonical S1 enrollment consent/device-bound issue and
scoped redemption, but exposes only library methods. LOCAL2 #4463 removed the
unsafe generic redeem and now awaits an authenticated server client port. The
existing broker pairing HTTP bridge serves the **generic** proof-based route;
it cannot be used to bypass S1 enrollment-bound challenge checks.

This slice adds two independent NEW files (no existing LOCAL code modified):

- `packages/padiem-control-plane/padiem_control_plane/padiem_connector_enrollment_server.py`
  — trusted server-side issuer/redeemer assembling S1, current consent,
  original canonical session continuity, and protected credential delivery.
- `apps/padiem-chat/app/claw_connector_enrollment_routes.py`
  — Starlette product handler functions for
  `POST /api/claw/connector/enrollments/issue` and
  `POST /api/claw/connector/enrollments/redeem`. Not mounted into
  `app_factory.py` or `worker.py` and always unavailable in live production.
- `packages/padiem-control-plane/tests/test_padiem_connector_enrollment_server.py`
  — focused *synthetic in-memory* canonical authority and fail-closed tests.

## Issue route (browser only)

The existing authenticated browser host MUST resolve and provide a real
`AuthSessionSnapshot`, verify same-origin/CSRF with the reviewed existing
middleware, and match it to the signed-in subject. The request accepts exactly
`{"device_id":"..."}` and NO owner/workspace/consent input. The server
reads its canonical current per-device consent and rechecks it at actual
issuance; S1 writes a server-owned pairing challenge bound to
consent+owner+scope+device. A trusted, DURABLE session-continuity adapter
records challenge ID -> current canonical session reference. Only after that
succeeds is the one-time pairing code returned to the reviewed browser.
No code is returned on error; an orphan challenge is non-redeemable.

## Redeem route (device proof, NO browser cookies)

The connector supplies only
`{challenge_id,device_id,proof_ref}`. A trusted server gateway MUST attest
TLS/device transport; the server reads original canonical session from its
own continuity record by challenge ID and refreshes its validity. It reads the
server-owned S1 challenge binding, and current consent by ORIGINAL consent ID.
The protected credential handoff is preflighted BEFORE S1 mutation. S1 itself
again validates account/workspace/owner/device/consent and HMAC possession proof,
then mints one canonical Broker binding. The **raw device credential is delivered
exactly once** through a trusted, existing protected credential installation
authority. Only a positive delivery acknowledgement returns a secret-free
`paired_offline` result; ONLINE must be verified later by canonical Broker
session and server projection. No P01 READ/WRITE permission is created.

A final handoff failure AFTER S1 mutation invokes the **same canonical
Broker's `revoke_binding`** as compensation, then refuses success. A focused
test verifies the failed-handoff binding is REVOKED. If revocation itself
cannot be confirmed the error is `enrollment_handoff_revoke_unconfirmed`,
must be treated as a security incident, and all production activation remains
blocked. This test is synthetic, not proof of durable cross-instance
compensation/atomicity. Do not route raw credentials to JSON response,
`enrollment.json`, frontend, logs, or support evidence.

## Named missing live dependencies

| Dependency | New port / exact owner | Current status |
| --- | --- | --- |
| Canonical CURRENT per-PC consent (grant/revoke/durable readback) | `DurableEnrollmentConsentAuthority.current_for_device/current_consent` from reviewed existing Control Plane grant owner | **NOT WIRED**. No new D1 migration/table created or applied |
| Original browser-session continuity through device redeem | `CanonicalSessionContinuityAuthority.bind_challenge/current_session` backed by existing session source of truth | **NOT WIRED**; no client cookie or fabricated principal |
| Trusted browser session and same-origin/CSRF | `app.state.connector_enrollment_browser_session` and `connector_enrollment_browser_csrf` | **NOT WIRED** |
| TLS/device entry attestation and rate guard | `app.state.connector_enrollment_device_gateway` | **NOT WIRED** |
| One-time credential delivery to EXISTING protected Windows credential store | `ProtectedDeviceCredentialHandoff.ready/deliver_once` | **NOT WIRED**; tested synthetic failure denial |\n| Failed-delivery compensation against the SAME canonical Broker | `CanonicalBrokerBindingRevoker.revoke_binding` | **NOT WIRED**; synthetic REVOKED path tested, durable rollback still unproven |
| Product route mounting/host composition | Existing app/Worker authority; no app_factory edit during PR #3925 overlap | **NOT MOUNTED** |
| LOCAL2 real client network transport and secure install | PR #4463 S2 owner; one-way follow-up on agreed route contract | **NOT WIRED** |
| Real stored Broker/session across Worker instances | Canonical durable Broker/pairing authority (#3099 gate) | **NOT PROVEN** |

The new `padiem_connector_enrollment_server.py` service requires ALL six
canonical dependencies (including the SAME Broker revocation port) even for issuance. It does not default to an in-memory
consent reader and cannot accidentally convert a demo/test service into a live
grant authority. This code is NOT a durable consent implementation: the
repository-wide schema/owner decision is a separate security prerequisite.

## Collision and safety

- This stacked source branch starts from exact LOCAL1 #4438 HEAD
  `865ad9952b4c8a9a31216dee2c7dbada16cacdcf`.
- Target PR base: `local1/4139-connector-s1-enrollment-261012`; new files
  only. Do not Ready/Merge this PR into a different base without rechecking.
- No modification of `apps/claw-connect/**` LOCAL2 #4463,
  `apps/padiem-chat/app/app_factory.py`, `worker.py`, B14, B66,
  `local_agent_broker_pairing.py`, production D1 schema or credentials.
- Changed policy is NOT claim of actual Cloudflare Worker route connectivity.
- Existing P01 grants are strictly separate; product owner must approve
  deployment and run exact-head required CI, authenticated runtime negative
  tests, then #3099 Windows one-shot E2E only after secure credential install.

## Current status and next owner decision

```makefile
IMPLEMENTATION=SERVER_SOURCE_SEAM_AND_DEFAULT_OFF_ROUTE_HANDLERS
DURABLE_CONSENT_AUTHORITY=NOT_WIRED
SERVER_SESSION_CONTINUITY=NOT_WIRED
CREDENTIAL_HANDOFF=NOT_WIRED
HTTP_MOUNT=NO
PRODUCTION=OFF
SIGNED_WINDOWS_E2E=NOT_PROVEN
READY=NO
MERGE=NO
```

**Next:** CENTRAL must identify and approve the existing durable consent and
session authority, and coordinate protected credential handoff with LOCAL2.
Then add real host composition (separate, conflict-free PR), validate auth/CSRF,
persistent cross-instance pairing, revoke/rotation and actual Broker device
authentication, and only then authorize #3099 E2E and live deployment.

## 2026-10-12 CENTRAL second implementation — Canonical Identity DO durable records

The repository-wide file inventory was audited, not guessed. The reviewed
source already has ONE canonical Identity Durable Object:
`packages/padiem-control-plane/identity_authority_durable.py`,
`identity_authority_worker.py`, storing canonical product links,
auth sessions, and tenant membership in `ctx.storage.sql` with
`ctx.storage.transactionSync`. It had NO dedicated durable Connector
per-device consent record or challenge-to-original-session table.

New SOURCE-ONLY files in THIS stacked PR:

- `packages/padiem-control-plane/canonical_connector_enrollment_durable.py`
  — `IdentityDurableConnectorEnrollmentRecords`: same Identity DO SQLite
  storage, exact per-PC current-grant/withdrawal lookup and **original**
  challenge→canonical session ID binding. At redemption it calls the
  EXISTING identity authority's `resolve_auth_session(session_id)` again;
  revoked/expired/missing/changed owner/product/tenant cannot redeem.
  Persisted data includes only consent metadata and session reference:
  **no browser token, password, proof, pairing code or device credential**.
  Concurrent active consent for same owner+device is prevented with a
  partial unique index; revoked consent cannot be resurrected and replacement
  requires a fresh consent ID. Mutation is `transactionSync` guarded.
- `packages/padiem-control-plane/tests/test_canonical_connector_enrollment_durable.py`
  — SQLite-backed synthetic DO adapter tests for explicit schema gate,
  owner/device isolation, denial/duplicate, revoke/regrant, expiry and
  refresh through the existing canonical current-session reader.

**Security gate:** `install_schema()` is explicit, and **is not called by
constructor, Worker startup, any API handler or migration pipeline**.
`SCHEMA_INSTALLED_BY_DEFAULT=False`; `PRODUCTION_CONSENT_RPC_EXPOSED=False`.
The existing Identity DO service, storage and authentication are not modified.
No real production D1/DO schema change was applied. A reviewed canonical OWNER
consent-grant/withdraw command is still needed; do not mistake persistence
for user approval. The existing Identity DO is the only permissible host:
a product-local D1 shadow or newly invented global consent service must not
be treated as authority.

**Still pending:** explicit operator approval and schema installation in the
canonical Identity Durable Object, private authenticated owner consent RPC,
binding to actual reviewed browser CSRF grant/revoke flow, and session
continuity composition into real S1 product HTTP and same canonical Broker.
Cross-Durable-Object consent-vs-pairing race and credential-handoff atomic
recovery require dedicated integration tests. A Source-only store is NOT
production enrollment. Keep `PRODUCTION=OFF`, `READY=NO`, `MERGED=NO`.

## 2026-10-12 CENTRAL third implementation — B54 browser identity and candidate shared scope

1. `apps/padiem-chat/app/claw_connector_enrollment_routes.py` now resolves the *CURRENT* canonical B54 session via the existing `resolve_current_b54_canonical_session(request)` bridge. The browser's signed product-user ID is NOT assumed equal to the canonical subject ID. The B54 product, active session, bound product user and canonical tenant are all verified before issuing a one-time code. A forged session from `app.state.connector_enrollment_browser_session` no longer supplies authority. Test cases cover absent, swapped product user, cross-product session, revoked session and missing canonical tenant. The route is still UNMOUNTED.
2. `packages/padiem-control-plane/canonical_connector_scope_readonly.py` is a read-only **CANDIDATE** for the existing shared PC owner scope: rechecks existing canonical ACTIVE tenant membership and reads the already-established `canonical_connector_context` row keyed by the SAME canonical subject and legacy `b62` product ID. It does **not** create context rows or infer new account/workspace aliases. It fails closed if missing, ambiguous or invalid. `SCOPE_BRIDGE_WIRED=False`; `SHARED_SCOPE_AUTHORITY_APPROVED=False`. The product-neutral meaning of the old B62 connector context must be confirmed through owner review before composing this adapter into S1.
3. Related tests exercise canonical-vs-product user identity distinction and subject/tenant/context scope mismatch. They are source-level tests, NOT proof of live authentication.

**Remaining authority decisions, do not skip:** actual reviewed explicit owner consent action (UI, CSRF and current session) → private canonical Identity DO grant/revoke RPC and guarded schema installation; canonical same-tenant scope ownership approval; production trusted gateway and exact HTTPS response encoding; durable Broker pairing/replay with concurrent revocation; existing protected Windows credential installation; LOCAL2 transport and #3099 live Windows E2E. No current PR grants product READ/WRITE or turns on enrollment.

**Status:** `B54_BROWSER_SESSION_SOURCE=VERIFIED_IMPLEMENTATION`; `SHARED_SCOPE_CANDIDATE=READ_ONLY_UNCOMPOSED`; `OWNER_CONSENT_RPC=NOT_WIRED`; `PRODUCTION_HTTP_ROUTE=UNMOUNTED`; `PRODUCTION=OFF`.

## 2026-10-12 CENTRAL fourth implementation — explicit owner-consent private RPC and B54 handlers

- The existing **private Identity Service Binding** now has gated methods for explicit enrollment schema install, consent grant, and consent withdrawal: `install_connector_enrollment_schema`, `grant_connector_enrollment_consent`, `revoke_connector_enrollment_consent`. All use exact closed payloads; RPC wrappers are reachable through `CONTROL_PLANE_IDENTITY`, while `CanonicalIdentityDurableObject.fetch()` remains 404 (no public identity route).
- Grant/revoke server contracts require the exact confirmation version `pc-enrollment-consent-v1`, strict JSON boolean `confirmed: true`, active current canonical **B54** user session, canonical tenant and active membership, pre-existing shared owner scope, explicit feature flags for RPC + reviewed shared-scope + schema-installed. Schema install is a separate private RPC requiring `CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCHEMA_INSTALL_ENABLED=true` and exact migration ID; nothing calls it from constructor/startup.
- The trusted B54 web handlers now source-confirm `/api/claw/connector/enrollments/consent/grant` and `.../consent/revoke` constants/functions using existing signed-user lookup + existing CSRF adapter + existing `resolve_current_b54_canonical_session`, then call the typed `CloudflareControlPlaneIdentityAuthority` service-binding client. Browser fields cannot set session/owner/tenant/workspace/consent ID on grant. The route methods are **NOT mounted** in `app_factory.py` or Worker and there is no new UI/consent checkbox yet. A public API caller cannot generate a consent by sending the confirmation boolean because public route mount and private RPC feature flags stay off; eventual UI needs explicit consent text + affirmative checkbox and same-origin CSRF.
- Response client verifies the consent is tied to requested device and never claims dispatch/read/write permission; revoke does NOT itself imply currently bound device is offline/unpaired. Existing canonical Broker credential revocation / live-session termination must be a separate reviewed path; issue consent withdrawal prevents outstanding/new enrollment, but a previously enrolled Broker binding is still under existing canonical revoke/lifecycle authority until unregistered.
- New test file `packages/padiem-control-plane/tests/test_identity_connector_enrollment_consent_rpc.py` exercises disabled-by-default, exact closed fields, grant/revoke owner/session scope, explicit confirmation version and schema-install gate. New `apps/padiem-chat/tests/test_4139_connector_enrollment_identity_client.py` validates typed private service-binding replies, no-overgrant and confirmation requirements; `apps/padiem-chat/tests/test_4139_connector_enrollment_consent_routes.py` covers B54 current session, CSRF, explicit owner action and fail-closed identity mismatch.

**Remaining before any live grant:** Security review and operator approval to set feature flags + run the explicit schema-install RPC in the existing Identity DO; final confirmation the old `b62` canonical connector context is approved as the shared owner scope; mount routes only with reviewed rate/CORS/CSRF/host constraints; add owner-facing clear consent prompt and confirmation UI; coordinate LOCAL2's authenticated TLS redemption transport and protected Windows credential installation; resolve withdrawal-vs-Broker-binding race/compensating revoke and run #3099 true Windows E2E. All new consent actions remain inert/disabled until flags and product mounting are separately approved.

## 2026-10-12 CENTRAL fifth implementation — existing Broker DO durable pairing and async host

**New source paths now present in this Draft PR:**

- `packages/padiem-control-plane/local_agent_broker_pairing_durable.py`
  — `DurableBrokerPairingAuthority` stores the *existing* pairing contract's pending/consumed challenge, consent/owner/scope/device binding, redeemed binding ref, and bounded per-scope issuance counters in the same `ctx.storage.sql` as the canonical Local Agent Broker Durable Object. It uses the existing `StateBackedLocalAgentBrokerAuthority` under that same `transactionSync` boundary so one successful redemption writes Broker binding state + challenge-consumed state together. The constructor never installs schema. The one-time pairing code and raw Broker credential are never stored in pairing rows; only the challenge nonce and the existing broker credential digest/state are persisted.
- `packages/padiem-control-plane/canonical_broker_pairing_rpc.py` and the existing `local_agent_broker_worker.py`
  — new private Service Binding methods: explicit gated schema install, enrollment challenge issue, server-time binding lookup, scoped redemption. There is no public fetch route. RPC calls require both `LOCAL_AGENT_BROKER_PAIRING_RPC_ENABLED=true` and `LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALLED=true`; installation additionally requires `LOCAL_AGENT_BROKER_PAIRING_SCHEMA_INSTALL_ENABLED=true`, a bounded explicit `LOCAL_AGENT_BROKER_PAIRING_ISSUANCE_RATE_LIMIT`, and the exact migration ID. No schema is automatically applied on startup.
- `apps/padiem-chat/app/control_plane_broker_pairing_client.py`
  — typed async private Broker Service Binding client; closed success/error envelope, exact challenge/binding/device/consent/scope correlation, proof shape, credential metadata and base64 validation. The raw device credential is returned to its **trusted server-side caller only**, outside any public response; host must install it securely and never log/serialize to a browser.
- `apps/padiem-chat/app/canonical_connector_enrollment_async_host.py`
  — asynchronous composition for existing Identity/Broker service bindings. Issue: refresh explicit device consent → create durable Broker challenge → durably bind challenge to original canonical B54 session → only then return one-time code. Redeem: read Broker-owned binding → refresh canonical session/active membership/current consent and exact owner/scope/device at Identity DO → preflight protected credential handoff → atomically redeem against the durable Broker → recheck consent/session immediately after cross-DO mutation → deliver credential once → return secret-free `paired_offline` metadata. Consent changes in the cross-DO window or a failed handoff trigger canonical Broker revoke compensation. If revoke cannot be confirmed, a distinct security failure is raised.
- Existing `claw_connector_enrollment_routes.py` uses the async host **only when a server operator explicitly injects it into app state**. The route constants and handler functions are still NOT mounted in `app_factory.py` or Worker. The existing `#3925` app-factory ownership conflict remains a separate reason not to wire routes in this branch.

### Focused local test evidence at this branch

- Control Plane new/related source tests: **59 passed** on the isolated Windows central workspace.
- B54/Claw product-side async orchestration + typed service-binding client + route tests: **59 passed**.
- Prior CI on an earlier head had 1,253 Control Plane tests and B62 regressions passing; those counts do NOT replace the currently running exact-head workflows.
- Current latest HEAD CI must be re-read and reported separately (Control Plane/B62 CI still running at update time).

### Remaining release blockers (explicit, not hidden)

1. **Operator-approved existing Identity DO schema installation** for per-PC consent/session rows and **existing Broker DO schema installation** for pairing challenge/rate-limit rows. Both have private migration methods but both schema-install feature flags remain OFF; no production schema has been installed by this PR.
2. **Owner-facing consent UX:** there are source handler functions and strict `confirmed=true` version gates but no UI checkbox/affirmative consent prompt or mounted routes yet. An API client cannot manufacture user consent simply by sending a boolean while the route/RPC flags remain disabled.
3. **Cross-product owner scope:** current read-only candidate reuses legacy `canonical_connector_context` row keyed `b62`. It does no writes and fails closed if missing; a designated security/identity owner must approve this legacy context as the one product-neutral PC scope before setting `CONTROL_PLANE_CONNECTOR_ENROLLMENT_SCOPE_APPROVED=true`.
4. **OS credential handoff:** the async host port is deliberately injectable and absent by default. LOCAL2 #4463 currently does not install a raw Broker credential in its existing protected Windows credential store or complete a second authenticated Broker challenge/session to prove the credential works. No handoff adapter is configured; the host therefore cannot redeem in live service and returns an unavailable refusal before consuming a challenge.
5. **Existing Broker revocation and lifecycle:** pairing code uses the current Broker's canonical persisted binding/session authority. The consent store and Broker are separate Durable Objects; post-redemption consent recheck and revoke compensation reduce the race but cannot give atomic cross-DO transaction semantics. Active binding consent withdrawal and ONLINE teardown must use a reviewed canonical revoke/lifecycle path; a withdrawn consent response does not itself imply device OFFLINE.
6. **Exact-host wiring:** private Broker/Identity Service Bindings, TLS device ingress attestation/rate limits, B54 CSRF owner routes, and app-state async-host factory/mount are not deployed. #3925 and other open local PR paths must be resolved before modifying `app_factory.py`.
7. **Operational acceptance:** LOCAL1 #4438 and LOCAL2 #4463 both remain Draft/unmerged. `#3099` remains the only signed Windows one-shot E2E acceptance ledger. Production stays OFF and no P01 READ/WRITE permission is granted.

```makefile
DURABLE_BROKER_PAIRING_SOURCE=IMPLEMENTED
BROKER_PAIRING_SCHEMA_AUTO_INSTALL=NO
BROKER_PAIRING_PRIVATE_RPC=SOURCE_IMPLEMENTED_GATED
ASYNC_IDENTITY_BROKER_HOST=SOURCE_IMPLEMENTED
DEVICE_CREDENTIAL_HANDOFF=UNWIRED
APP_FACTORY_ROUTE_MOUNT=NO
PRODUCTION=OFF
READY=NO
MERGED=NO
WINDOWS_LIVE_E2E=NOT_PROVEN
```
