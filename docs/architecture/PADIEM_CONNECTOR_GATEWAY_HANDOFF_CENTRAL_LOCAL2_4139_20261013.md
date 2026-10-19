# #4139 — CENTRAL↔LOCAL2 credential handoff and recovery contract (source-only)

**Owner:** CENTRAL CTO / PR #4476; Windows receiver owner LOCAL2 / PR #4490
**Decision:** one canonical Identity DO + one Broker DO; CENTRAL's async host is the only currently reviewed **source candidate** for challenge redemption, **not** a deployed redemption service.
**Status:** DRAFT, NOT MOUNTED, NOT LIVE. `GATEWAY_TRANSPORT_PRODUCTION_ENABLED=False`; no credentials, public route, Cloudflare secrets, migrations or production state touched.

## What CENTRAL implemented here

- `CanonicalConnectorEnrollmentAsyncHost.redeem` consumes the Broker's one-time challenge at exactly **one** server owner after fresh Identity OWNER consent checks. No generic kagent Broker redemption fallback; no raw credential in product HTTP receipt.
- All **three** compensation boundaries — consent lost just after redemption, invalid/failed Windows handoff, and consent lost after authenticated ACK — now accept **only** an exact `{"binding_ref": expected, "state": "revoked"}` from the canonical Broker private revoke RPC. A truthy `True`, `None`, stale/wrong binding, status `active`, or additional unexpected keys is a **security HOLD** (`enrollment_*_revoke_unconfirmed`), not a compensated success. A consumed challenge cannot be replayed. 21 new synthetic negative tests cover all phases.
- `canonical_connector_gateway_handoff.py` defines the CENTRAL *injection-only* `TrustedConnectorGateway` port and `CanonicalGatewayProtectedHandoff`. The port reserves a short-lived **pre-enrollment** gateway lease, independently authenticates its source, transfers the one-use canonical Broker credential once, receives only the eight closed install-ACK fields, and independently authenticates the ACK sender. The host still verifies keyed HMAC and three consent reads.
- The gateway may receive only the seven canonical install-binding fields `binding_ref`, `device_id`, `account_ref`, `workspace_ref`, `credential_ref`, `credential_generation`, `credential_expires_at` **plus a separate one-time raw credential over the trusted private channel**. No owner session, product privilege, OAuth token, email, private quote material, P01 grant or device runtime permission.
- Synthetic fake-gateway tests exercise wrong-PC lease, expiry, untrusted bootstrap, wrong/false ACK, absence of authenticated sender, metadata swaps/invalid expiry and repeat local delivery. These tests **do not attest** to actual Windows DPAPI or trust in a real gateway.

## 2026-10-13 incremental security step — nonconsuming Broker pairing HMAC preflight

CENTRAL added an internal, source-only **pre-redemption proof check** spanning
`InMemoryBrokerPairingAuthority.verify_enrollment_bootstrap` →
`DurableBrokerPairingAuthority.verify_enrollment_bootstrap` (same existing Broker DO SQLite, read-only transaction) →
`CanonicalBrokerPairingRPC.verify_enrollment_bootstrap` (private Service Binding only) →
`CloudflareCanonicalBrokerPairingClient.verify_enrollment_bootstrap` →
`CanonicalConnectorEnrollmentAsyncHost.redeem`. The Host now requires the
exact closed `{challenge_id,device_id,proof_valid:true,challenge_consumed:false}`
Broker response **before the Gateway lease is requested and before the final
Broker redemption can consume the challenge**. It checks the original issued
HMAC proof against the existing code nonce, current pending/expiry state, and
the original canonical OWNER, consent, account/workspace and device binding.
Final Broker redemption still atomically rechecks it.

Wrong pairing proof, cross-device/scope/consent/OWNER, expired or previously
consumed challenges must fail closed without new credential, device binding or
Gateway delivery. New durable SQLite, private RPC, product client, and host
negative tests pin this sequence. No new public route, pairing secret, second
broker, store or activation flag. The existing Cloudflare Worker thin entrypoint
limit remains in force.

**Critical:** possession of the pairing-code proof is **not** physical PC
identity, DPAPI installation attestation, or a durable Gateway session. A
malicious party that steals a pairing code could otherwise impersonate the
first PC. The actual outbound Gateway still must authenticate the same
proof-presenting peer on a nonce-bound live session, atomically/durably claim
its one-time lease, authenticate ACK sender and protect the one-use credential
on verified TLS. This preflight only eliminates the previous gap where an
arbitrary syntactically valid proof could reach Gateway reservation. It does
NOT clear production or #3099 holds.

## Exact integration port (CENTRAL owns gateway implementation/review)

```python
reserve_authenticated_bootstrap(challenge_id, device_id) -> GatewayBootstrapLease
authenticate_bootstrap_lease(lease, challenge_id, device_id) -> bool
transfer_credential_once(lease, credential: bytes, binding: dict) -> None
receive_authenticated_install_ack(lease) -> dict  # exact 8-field ACK only
authenticate_ack_sender(lease, ack: DeviceCredentialInstallAck) -> bool
```

`GatewayBootstrapLease` contains only `lease_ref`, `challenge_id`, `device_id` and timezone-aware `expires_at`. **It is not evidence of identity by itself.** The reviewed gateway (not Python dataclass assertions) MUST establish the actual outbound PC's challenge-bound bootstrap identity **before any Broker redemption**, authenticate sender/session correlation independently of `device_id` claims and ACK HMAC, hold a durable single-use reservation, enforce bounded response time and rate limits, and never send raw credentials in the normal 13-field product redeem response.

**Bootstrap circular dependency:** the already-enrolled `kagent.local_agent_control_plane_https` session transport authenticates using a credential that a never-enrolled PC does not possess. Its ordinary `/session` cannot bootstrap enrollment. The generic `LocalAgentBrokerPairingClient.redeem` is a different redemption owner and cannot be run after the CENTRAL host redeems the same single-use challenge. A pre-enrollment challenge-bound **authenticated** outbound gateway path is therefore necessary; it is NOT delivered by this source port. Never infer a safe path from TLS alone, a user-supplied `device_id`, a gateway receipt boolean, or a constructed `GatewayBootstrapLease`.

## LOCAL2 exact responsibility after CENTRAL gateway review

1. Adapt the existing Windows `LocalStoreCredentialReceiver.install_once` to a reviewed gateway **PC-initiated** session, matching all seven canonical binding fields to the protected `DeviceCredentialStore`; preserve its D1 alias-safe stage-then-publish fix from HEAD `d4cf25542`. Do NOT create a second PC account, Broker, device identity, persisted challenge store or product-specific Connector.
2. The device computes the closed eight-field ACK **only after** the installed credential has been read back from DPAPI and checked against the canonical binding/scope/generation. It sends ACK once over the same authenticated session; `proof_hex` HMAC alone does NOT establish PC identity.
3. On any local disk/DPAPI/install ACK failure, local enrollment remains uncommitted. The central Broker may already have consumed the challenge: LOCAL2 must remain security HOLD until a **separately authenticated** canonical revoke result is received. No existing public refusal body or local bool is evidence of Broker revocation.
4. No reconnect/retry of the consumed challenge; no implicit P01 READ/WRITE/ONLINE; do not change the product-independent account/device scope or migration/branding in this slice.

## Still missing — operational gates

1. Real authenticated **pre-enrollment** device gateway with independently verified bootstrap identity, durable challenge-bound reservation, nonce/replay and timeout semantics and a private one-use credential transport on HTTPS/443. A test fake is not a live gateway.
2. LOCAL2 outbound client/DPAPI sender and a secure **post-failure revoke verdict delivery** mechanism. CENTRAL exact-checked private Broker revoke receipt is not yet something a device can learn from the public HTTP response; do not expose it unauthenticated.
3. Owner-facing consent UI and route/CSRF mounts, canonical Identity/Broker schema install authorization, product-neutral scope security approval, correct gateway Service Binding and strict production feature flags.
4. Signed-in production Worker/Pages served-SHA proof, operator-approved enablement, actual Windows #3099 E2E, ACK replay/swap and failure-reconciliation matrix. **All are still NOT PROVEN**.

```text
REDEMPTION_OWNER=CANONICAL_CENTRAL_ASYNC_HOST_SOURCE_ONLY
GENERIC_BROKER_REDEEM_FALLBACK=FORBIDDEN
CANONICAL_REVOKE_RECEIPT=EXACT_BINDING_AND_REVOKED_STATE_REQUIRED
TRUSTED_GATEWAY=PORT_ONLY_NOT_IMPLEMENTED
WINDOWS_SENDER=NOT_WIRED
WINDOWS_INSTALLATION_ACK_LIVE=NOT_PROVEN
AUTHENTICATED_REVOKE_VERDICT_TO_PC=NOT_WIRED
PRODUCTION_DEVICE_GATEWAY=OFF
CONSENT_PUBLIC_ROUTE=UNMOUNTED
WINDOWS_LIVE_E2E=NOT_PROVEN
PR_4476=DRAFT_UNMERGED
PR_4490=DRAFT_UNMERGED
```
