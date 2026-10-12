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
