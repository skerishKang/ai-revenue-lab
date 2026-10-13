# #4139 CENTRAL — one-socket outbound Gateway rendezvous v1 (SOURCE ONLY)

**2026-10-13 KST · CENTRAL CTO · PR #4476**

Status: `DRAFT`, `NOT MOUNTED`, `SCHEMA NOT INSTALLED`, `PRODUCTION OFF`,
`WINDOWS REAL PC E2E NOT PROVEN`. This document is a deliberately narrow
wire handover and security blocker register, not approval to enable a gateway.

## Why one socket

The existing `CanonicalConnectorEnrollmentAsyncHost.redeem` is the **only**
Broker challenge redemption owner. It consumes the canonical Broker challenge,
then immediately waits for a protected Windows DPAPI save/readback ACK. There
is no trusted credential inside a never-enrolled PC, so ordinary registered
`/session` is unusable. A separate public redeem/credential GET would create
a second owner or expose a raw secret before session authentication.

CENTRAL now implements an **unmounted** one-session WSS orchestrator at
`apps/padiem-chat/app/connector_gateway_websocket_session.py`.
It injects the existing Host with `CanonicalGatewayProtectedHandoff`, using
`SingleSocketAuthenticatedGateway` for the same PC-originated socket.
It never stores the credential in a new DB, memory-global registry, public
JSON receipt or asynchronous queue.

## Wire frames and the existing Broker ledger

Only the *client* initiates a `wss://` connection. The trusted ingress port
must separately authenticate server-terminated TLS provenance, not merely
trust `x-forwarded-proto`, a caller device_id or WebSocket URL. Browser
Origin or Cookie is refused. A production proxy must impose a frame-size
limit **before** reading into application memory (the source applies an
additional 8192-character bound after receipt).

1. PC → server `begin`: closed JSON `{type,challenge_id,device_id,proof_ref}`.
   `proof_ref` is the canonical pairing-code HMAC already minted by the PC.
   **New security fix:** the canonical Broker verifies the proof against
   OWNER-bound challenge/scope **before** writing a Gateway nonce row. An
   attacker knowing only a challenge_id/device_id cannot reserve or squat its
   one-use slot.
2. Broker DO returns nonce/lease/expiry without a credential; server forwards
   the bounded no-store `nonce` frame.
3. PC → server `finish`: `{type,lease_ref,proof_hex}`. The client signs the
   Broker-issued nonce/lease with the original pairing code, using
   `bootstrap_mac` and the v1 domain-separated transcript. Broker compares
   in constant time and durably records the verified lease; 3 invalid
   submitted MACs lock the challenge lease.
4. PC → server `credential_fetch`: `{type,counter:1,proof_hex}`. PC signs
   the SHA-256 of **empty bytes** with the v1 session MAC. Broker DO advances
   the durable action counter 1→2 once; retry/duplicate or forged values fail.
   This is authorization to START the existing Host, not Broker redemption.
5. CENTRAL Host independently rechecks current Identity OWNER consent and
   canonical pairing proof, then single-use **Broker redemption**. Only after
   the post-redeem consent recheck, the same WSS connection receives one
   `credential_once` frame containing 7 canonical binding fields + the raw
   newly minted Broker credential Base64. This is deliberately a **private
   WSS-only secret frame**, never returned by an HTTP redeem JSON.
6. LOCAL2 PC performs DPAPI durable store/readback before constructing the
   existing 8-field `DeviceCredentialInstallAck` (credential-keyed HMAC).
   The PC then sends a single signed `install_ack` frame
   `{type,counter:2,proof_hex,body_b64}`. `body_b64` is exact Base64 of
   the UTF-8 JSON object with **only those 8 approved ACK fields**. The
   signature is the v1 session MAC over SHA-256 of those exact body bytes.
   The canonical Broker DO verifies action counter 2 and that this challenge
   has truly been redeemed to the SAME device before advancing. The
   `CanonicalGatewayProtectedHandoff` then independently validates ACK
   challenge/device/binding/generation, key possession proof and same-socket
   Broker-authenticated sender. An untrusted ACK bool, browser claim or copied
   JSON cannot finish enrollment.
7. CENTRAL Host rechecks OWNER consent after authenticated Windows ACK. Only
   then server → PC `terminal:paired_offline` (never ONLINE or P01 rights).
   Confirmed canonical Broker revoke yields `terminal:revoked` on that same
   trusted connection; unconfirmed compensation yields
   `terminal:security_hold`. A consumed challenge is never retried.
   The server closes WSS on every normal terminal or error.

## Trust and state boundaries

- The canonical Broker DO still owns challenge, credential issuance, scope,
  `binding_ref` and revocation; the Gateway ledger stores only a nonce,
  one lease and bounded failed attempts/action counters in the SAME DO SQLite.
- The `LocalStoreCredentialReceiver` and LOCAL2 `EnrollmentPersistenceError`
  preserve existing Windows DPAPI stage-then-publish semantics. In-process
  `reconciliation_hold` does **not** survive restart and cannot prove Broker
  compensation.
- All outbound action signatures are derived from the pairing code, **not**
  from the newly issued device credential. The ACK includes BOTH independent
  proofs: Broker-signed session action and the credential-keyed installation
  transcript. This remains proof of code/credential possession; it is not
  hardware attestation or proof of physical machine identity.
- No attempt is made to trust a Cloudflare Worker isolate's process-global
  memory, a user-provided origin header, an unsigned retryable pending
  credential escrow, or a second generic Broker `redeem` function.
- `revoke_verdict` action counter 3 exists in the durable ledger contract but
  a LIVE authenticated post-failure remote verdict query, especially after
  WSS disconnect, is **not yet implemented**. Do not imply the in-band
  terminal message persists or guarantees reconciliation after a crash.

## Outstanding blockers — do NOT ship as live

1. Independently reviewed **real** TLS terminator/trusted-ingress verifier,
   WSS session origin, bounded sockets/timeout/DoS/rate guard, actual private
   `gateway_bootstrap_rpc` service binding and Identity/Broker Host composition.
   No server configuration mounts `run_device_initiated_enrollment` today.
2. Explicit Broker DO additive schema install and operator feature enablement
   by a separate reviewed production procedure; flags remain unset/false.
   Pairing codes must be one-time, secret, short-lived and non-loggable.
3. **LOCAL2** outbound WSS PC client + proof MAC/counter implementation bound
   to existing device identity/DPAPI receiver. This must not implement a second
   Broker, privilege control or alternate credential store. Can be assigned
   only after CENTRAL independently approves these wire contracts.
4. Signed, authenticated server-to-PC **post-restart** revoke verdict/
   reconciliation and retry/timeout adversarial testing. Transport loss after
   single-use credential delivery cannot imply success or a verified revoke.
5. End-to-end **real** Windows #3099 signed-in consent→challenge→PC WSS→
   DPAPI save/readback→ACK→Broker paired_offline and failure matrix. Synthetic
   socket/Broker unit tests do not count as a real Windows E2E.
6. Review and reconcile #4438 → #4476 → #4490 stacked branch drift before
   exact-head merge. No current Ready, merge, Worker/Pages deploy, or DB
   migration is authorized by this source-only change.

```text
CENTRAL_BROKER_REDEMPTION_OWNER=ONE
GATEWAY_LEASE=CANONICAL_BROKER_DO_DURABLE
GATEWAY_BEGIN_REQUIRES_PAIRING_CODE_PROOF=YES_SOURCE
ONE_PC_ORIGINATED_WSS_SESSION=YES_SOURCE_ONLY
PRODUCTION_WS_ROUTE_MOUNTED=NO
PRODUCTION_GATEWAY_TLS_VERIFIER=NOT_WIRED
PRODUCTION_CREDENTIAL_DELIVERY=OFF
AUTHENTICATED_POST_RESTART_REVOKE_QUERY=NOT_WIRED
WINDOWS_DPAPI_LIVE_E2E=NOT_PROVEN
LOCAL2_WINDOWS_WSS_SENDER=NOT_WIRED
```

## CENTRAL Source Composition Review — 2026-10-13

`canonical_connector_gateway_source_composition.py` now binds the
existing typed private Identity/Broker Worker RPC clients to the one-socket
`CanonicalConnectorEnrollmentAsyncHost`, behind a **test/review-only**
Starlette `WebSocketRoute`. It accepts only the already reviewed private
Broker methods and the `gateway_bootstrap_rpc` begin/finish/authorize
operations; an on-socket caller cannot invoke the private gateway schema
installer. Any missing private binding or TLS verifier prevents even route
construction, and unsigned forwarding headers never authorize a peer.

**This is NOT production routing.** The module is not imported into
`app_factory.create_app`, and Worker/Pages/Cloudflare do not mount it.
A real Cloudflare Worker ingress must verify TLS metadata from
the **trusted runtime request context**, never forwarded/supplied HTTP
headers, and bind the verified client/session to owner-assisted pairing
and one-time nonces. Cloudflare's WebSocket support does not by itself
establish this device authenticity. Production mTLS enrollment and
certificate provisioning, if chosen, require owner/operator review
because pre-enrollment machines do not yet possess an account device
credential. No silent new customer login or repetitive approval UI.

`connector_gateway_source_composition` remains explicitly offline until
that runtime attestation, rate/frame/timeout guard, authenticated recovery
verdict and real Windows PC-side WSS client are demonstrated under #3099.


## 2026-10-13 CENTRAL WSS deadline/compensation hardening

Source-only bounded waits now apply to trusted TLS verification (5s), PC
bootstrap/fetch frames (10s each), private canonical Broker gateway RPC (8s),
WSS send (8s), and Windows protected-install ACK receive (25s).
A silent client no longer holds the source session without a deadline.
Actual Cloudflare ingress MUST independently enforce pre-read frame-size,
connection concurrency, rate limiting, and trusted TLS provenance.

The gateway intentionally does **not** apply a single outer cancellation
deadline to `CanonicalConnectorEnrollmentAsyncHost.redeem`. A cancellation
after a Broker challenge is consumed can otherwise leave a live device
binding without confirmed compensation. The existing Host catches per-send
or per-ACK exceptions and requires exact canonical Broker revoke receipts.
A timeout is NEVER a claim of revoke or permission to replay the challenge.
A post-disconnect/restart authenticated reconciliation port is still missing.

Synthetic fault injection covers absent pre-redemption PC frame, delayed TLS
verifier, unresponsive private Broker, lost ACK and blocked credential send.
It is not live Windows DPAPI or Cloudflare WSS evidence. No production
routing, secret, Worker schema, feature flag or deployment was enabled.


## CENTRAL owner-session recovery projection — 2026-10-13

`canonical_connector_owner_recovery.py` implements a **source-only, read-only,
owner-authenticated** post-restart reconciliation port. Given a fresh,
server-verified canonical OWNER session, it checks the original challenge's
owner/consent/account/workspace/device binding against current per-PC consent,
then reads the **existing** canonical Broker `device_directory` (private
Service Binding, scoped entirely from Identity). It selects the exact
canonical pairing challenge + device-derived binding reference and accepts
`canonical_state=revoked` ONLY for that exact original binding.
Any missing, still-active, expired, malformed, cross-owner or duplicated
evidence gives `security_hold` or hard denial; it never claims ONLINE,
recovers a credential or retries the redeemed challenge.

**This does not solve unattended Windows-only post-restart reconciliation.**
The local PC cannot impersonate a newly authenticated owner session; there is
no device-only recovery HTTP route, signed delivery verdict to a reconnected
Windows receiver or production composition yet. `OWNER_RECOVERY_ROUTE_MOUNTED`
and `OWNER_RECOVERY_PRODUCTION_ENABLED` remain False. No Cloudflare
migration, secret change, cross-product projection or user-facing exposure.
