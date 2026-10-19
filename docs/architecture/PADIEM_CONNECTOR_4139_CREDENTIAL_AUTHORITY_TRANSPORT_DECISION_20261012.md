# #4139 — Canonical device credential authority and transport decision

**Decision date:** 2026-10-12 KST
**Status:** SOURCE DESIGN DECISION / NOT AN ACTIVATED TRANSPORT
**Owner:** CENTRAL CTO — #4476; Windows implementation owner: LOCAL2 #4490

## Decision A — canonical issuance size

For **new PADIEM Connector pairing-issued device credentials**, the normative upper bound is
`padiem_control_plane.local_agent_broker_pairing.MAX_PAIRING_CREDENTIAL_BYTES = 4096`.
The default pairing factory returns 32 random bytes, and the Broker pairing authority checks
`MAX_PAIRING_CREDENTIAL_BYTES` before registering the new binding. The existing
`kagent.local_agent_secure_transport._MAX_CREDENTIAL_BYTES = 16384` is the **generic
protected storage capacity**, not permission for Connector pairing issuance to exceed 4096.
The existing `kagent.local_agent_broker_pairing_client.MAX_ENROLLMENT_CREDENTIAL_BYTES`
is also 4096, consistent with the pairing contract.

CENTRAL's `canonical_connector_credential_handoff.installation_proof()` now imports the
Broker's normative `MAX_PAIRING_CREDENTIAL_BYTES` rather than hardcoding 4096.
LOCAL2's pre-store rejection of oversized Connector pairing secrets is correct; **do
not increase the pairing protocol limit to the DPAPI capacity**. The additional
current install-ACK minimum of 16 bytes is a security policy gate, not a factory
capability statement; canonical default is 32. A custom credential factory
producing less than 16 bytes would be denied at the ACK boundary and must not
be enabled for live Connector enrollment without a cross-component minimum-key
contract review.

## Decision B — choose existing Broker as the only device authority

**Reuse rather than invent:**

1. **Existing canonical Identity Durable Object** decides signed-in B54 owner,
   current canonical tenant OWNER membership, explicit per-PC consent, original
   challenge-session binding and revocation; no product UI can self-assert these.
2. **Existing canonical Local Agent Broker Durable Object** owns pairing challenge
   and consumed state, device/binding record, credential generation/digest,
   revocation, device session and ONLINE lifecycle evidence. No new Broker or
   product-specific device identity store.
3. **Existing outbound-only kagent device transport** is the preferred transport
   foundation: `kagent.local_agent_secure_transport.OutboundTransportConfig`,
   `kagent.local_agent_control_plane_https.StdlibPinnedHttpsJsonRequestPort`,
   `kagent.local_agent_broker_pairing_client.LocalAgentBrokerPairingClient`,
   `BrokerPairingHttpsOperation.REDEEM`, the reviewed **HTTPS/443 pinned Broker
   origin** and `DeviceCredentialStore` (Windows current-user DPAPI
   `WindowsDpapiProtectedDataPort` / `ProtectedFileDeviceCredentialStore`).
   It is an **existing source design**, NOT proof the live endpoint is mounted,
   authenticated or operational.
4. **LOCAL2 #4490** must integrate the existing protected-storage contracts,
   not duplicate them. One canonical PC binding is shared by B66, Claw and
   other approved products; application authorization/READ/WRITE remains separate
   at P01.

**Preferred direction:** a **PC-initiated, TLS-verified, challenge-bound Broker
redemption/credential delivery flow** through the existing outbound-only
transport, not an ad-hoc server-push, publicly reachable local listener,
browser cookie transfer or an additional second-factor/device database.

## Critical incompatibility — DO NOT WIRE YET

**Two existing source paths currently consume the same single-use challenge:**

- `#4476 CanonicalConnectorEnrollmentAsyncHost.redeem()`: B54 product server
  authorizes through Identity DO, then **server-side** Broker redeem returns the
  raw credential privately, and a not-yet-wired `ProtectedDeviceCredentialHandoff`
  is supposed to deliver it to the PC and validate an authenticated install ACK.
- `kagent.local_agent_broker_pairing_client.LocalAgentBrokerPairingClient.redeem()`:
  the **PC** calls an existing Broker HTTPS pairing REDEEM operation, receives a
  one-time credential on that Broker-specific authenticated transport, then
  saves it to existing protected storage.

**They are alternative redemption owners, not two stages of one enrollment.**
Never invoke both for the same challenge, replay/reissue a consumed challenge,
make the B54 `/api/claw/connector/enrollments/redeem` HTTP response carry
`credential_b64`, or treat a normal B54 receipt as installation proof.

The existing Broker HTTPS client route is **not yet proven to implement** the
new #4139 current OWNER/consent/session revalidation and trusted device
ingress contract before releasing a credential. Also, authenticated device
identity before first enrollment cannot be inferred from a claimed device_id
or from ordinary TLS alone. Therefore the existing transport code **must not
be enabled as a bypass** to #4476's sealed private consent checks.

### Required integration/review sequence

1. Select **exactly one** authorized redemption owner for #4139 (recommended:
   PC-initiated existing canonical Broker HTTPS client, subject to security
   validation). A single-use challenge can be consumed only there.
2. Ensure that the canonical Broker **atomically** checks its persisted
   challenge/owner/consent/scope/device identity and enforces a **fresh,
   verified canonical owner authorization** before release. Review how to
   verify current Identity DO OWNER session and consent at redemption time,
   including withdrawal races, without trusting caller-supplied account refs,
   authorizations, dates or an unsigned boolean. A safe narrowly scoped,
   expiring, replay-resistant Identity-to-Broker ticket/authorization seam may
   be needed, but is NOT implemented by this decision.
3. Review deployment/service-binding routing to the existing Broker HTTPS/443
   endpoint and the exact allowed request/reply shapes. Do not assume the
   existing client is a live public gateway or activate it without proof.
4. Retain existing `kagent` DPAPI save/readback verification and the
   versioned #4139 HMAC installation transcript, but do not claim the transcript
   alone proves Windows persistence or authenticated physical PC identity.
   Review the server's authoritative confirmation path using the existing
   authenticated Broker session/binding; do not accept a client self-assertion.
5. On delivery/install failure revoke the canonical Broker binding; if
   revocation is unconfirmed, security HOLD and operator reconciliation.
   Retry requires a **new** one-time challenge and current OWNER consent.
6. Only after exact-head CI, explicit consent UX, security-approved shared PC
   scope, deployed route proof and real Windows #3099 E2E may activation be
   considered. Registration alone never grants P01 READ/WRITE execution rights.

## Acceptance markers

```makefile
PAIRING_CREDENTIAL_MAX_BYTES=4096
DEFAULT_PAIRING_CREDENTIAL_BYTES=32
GENERIC_WINDOWS_PROTECTED_STORE_CAPACITY_BYTES=16384
CREDENTIAL_SIZE_MISMATCH=RESOLVED_BY_PROTOCOL_BOUND
IDENTITY_AUTHORITY=EXISTING_CANONICAL_IDENTITY_DO
DEVICE_AUTHORITY=EXISTING_CANONICAL_BROKER_DO
PREFERRED_DELIVERY_FOUNDATION=EXISTING_KAGENT_OUTBOUND_PINNED_HTTPS_BROKER
REDEMPTION_OWNER=NOT_YET_SECURITY_APPROVED
SERVER_REDEEM_AND_CLIENT_REDEEM_SIMULTANEOUS=FORBIDDEN
LIVE_AUTHENTICATED_BROKER_INGRESS=NOT_PROVEN
WINDOWS_DPAPI_ACK_CHANNEL=NOT_WIRED
PRODUCTION=OFF
READY=NO
MERGED=NO
WINDOWS_LIVE_E2E=NOT_PROVEN
```

## 2026-10-13 — Synthetic credential security scan disposition (source audit)

- GitGuardian incident [#37629511](https://dashboard.gitguardian.com/workspace/795790/incidents/37629511) grouped 11 historic occurrences of a **synthetic test fixture** (the Base64 encoding of the literal word `credential`, not a provider/API/device production key); two historical occurrences in `apps/padiem-chat/tests/test_4139_canonical_broker_pairing_client.py` on commit `5686c51` were reported on this PR. Prior test files in the same incident contain the same value.
- At CENTRAL PR #4476 commit `74875c35aa2669c3d00f34b94aa95f0765d0e468`, the two current-file occurrences were replaced by runtime encoding of a plainly labeled synthetic fixture, preserving the test double behavior. GitGuardian incident details show **zero files requiring code fix** and record those two lines as removed on that commit. This does **not erase historic git occurrences**.
- Authorized owner session on PC1 reviewed the incident and selected GitGuardian **Ignore → This is a test credential**. This is a scoped test-fixture disposition only; it is **not** a policy to ignore other secret incidents or a license to publish actual credentials. No real secret was rotated because this particular evidence contains no actual credential.
- GitHub's existing GitGuardian check on the prior PR HEAD remains a historic completed failure until the provider publishes a **fresh passing check**. Do not infer a PASS merely from the dashboard label; check the exact current HEAD and do not mark Ready/merge or enable Connector while either provider check or the unrelated enrollment security gates are pending.
