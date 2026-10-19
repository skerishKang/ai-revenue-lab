# #4139 — PADIEM Connector authenticated protected Windows credential installation acknowledgement

**Status:** CENTRAL source contract and synthetic tests only, **NOT AN INSTALLED TRANSPORT**  
**Date:** 2026-10-12 KST  
**CENTRAL:** Draft PR #4476, stacked on LOCAL1 #4438  
**LOCAL2:** Draft PR #4490, owns the Windows receiver integration  
**Production route:** OFF; **no production schema/secret change or deployed device receiver**

## Security objective

A canonical Broker's single-use device credential MUST NOT become "installed" merely because:
- an HTTPS request returned 200,
- the server successfully sent credential bytes,
- a device echoed a JSON boolean `installed: true`, or
- an unauthenticated/forwarded message claimed the existing kagent DPAPI store saved the secret.

The host must accept **all of the following** before returning a secret-free `paired_offline` receipt:

1. **Authenticated live delivery destination** through the existing trusted device gateway, bound to the exact `challenge_id` + `device_id`, before the canonical Broker redeems a one-time challenge.
2. **Actual local storage/readback confirmation** from the existing `kagent` protected credential store (`WindowsDpapiProtectedDataPort` + `ProtectedFileDeviceCredentialStore`); LOCAL2 must validate `binding_ref`, `device_id` and positive non-boolean `credential_generation` against the expected canonical Broker binding. An installer cannot just accept a server-side flag.
3. **Versioned keyed proof** over the exact install transcript using the newly installed canonical device credential and HMAC-SHA256. This only proves possession of the Broker credential and binding to the signed transcript; on its own it **does not prove DPAPI installation or authentic Windows device identity**.
4. **Independently verified authenticated source** from the existing trusted device gateway for that specific PC/session and challenge, via `verify_authenticated_ack`, which MUST NOT be implemented by trusting the ACK's own fields or forwarding the installer's `True`.
5. **Fresh OWNER consent** checked immediately after Broker redemption and again after the authenticated installation ACK. Changes trigger a revoke of the newly created canonical Broker binding, and a confirmed revoke is required before returning a refusal that is considered reconciled.

## Versioned closed ACK contract

Source file: `apps/padiem-chat/app/canonical_connector_credential_handoff.py`  
Transcript: `padiem.connector-device-install-ack.v1`

The only accepted ACK type is `DeviceCredentialInstallAck`, with these exact fields:

| Field | Source/constraint |
| --- | --- |
| `challenge_id` | canonical Broker challenge used for redemption |
| `device_id` | exact authenticated PC identity |
| `binding_ref` | canonical Broker binding being installed |
| `credential_generation` | canonical positive integer generation |
| `proof_kind` | `protected_store_save_readback` exactly |
| `transcript_version` | `padiem.connector-device-install-ack.v1` exactly |
| `local_store_confirmed` | JSON/Python boolean true, **not sufficient on its own** |
| `proof_hex` | 64 lower-case hex bytes: HMAC-SHA256 output, no raw credential |

Construct proof after local protected save/readback using a strictly encoded UTF-8 transcript with newline separators and **no trailing newline**:

```text
padiem.connector-device-install-ack.v1
<challenge_id>
<device_id>
<binding_ref>
<credential_generation_as_decimal_integer>
```

Calculate `proof_hex = HMAC_SHA256(key=raw_canonical_device_credential, message=transcript_utf8).hexdigest()`. No credential, OAuth cookie, owner-session secret, DPAPI blob, filesystem location or service token is permitted in the ACK or in the public redeem HTTP response. The server compares with `hmac.compare_digest` using the canonical Broker-issued credential before any success.

The version/binding/device/generation/secret match and the **trusted channel's authenticated source** must both pass. The existing gateway is the sole authenticating authority; neither the ACK structure nor the HMAC introduces a new device-identity authority.

## Fail-closed recovery

- Not ready/no reviewed channel: refuse **before consuming** the Broker challenge. No fallback to raw credential HTTP response.
- Installation not confirmed, invalid ACK shape, HMAC mismatch, wrong device/binding/generation, unverified gateway, timeout or send error: **revoke the newly created canonical Broker binding**, then fail without an "installed"/ONLINE response.
- Canonical OWNER consent withdrawn after redemption or after authenticated installation ACK: revoke the same binding and refuse.
- Revocation fails/cannot be confirmed: security HOLD, no new binding, no automatic replay/retry, no CONNECTED claim. Operator must reconcile the existing canonical Broker binding before a fresh one-time challenge.
- A successfully redeemed challenge remains consumed; any later retry requires a new challenge and fresh canonical OWNER consent. Never replay or retransmit the prior raw Broker credential.
- Successful install ACK only permits **`paired_offline`**, not Broker session authenticated, ONLINE, P01 READ, WRITE or job dispatch permission.

## Implementation responsibilities and activation gates

**CENTRAL #4476 implemented (source only):**
- Strict `DeviceCredentialInstallAck` and HMAC transcript verifier with exact canonical binding checks.
- `CanonicalConnectorEnrollmentAsyncHost.redeem()` no longer trusts `deliver_once -> bool`: requires a valid keyed ACK **and** independent `verify_authenticated_ack` from a reviewed device gateway adapter.
- Explicit `UnconfiguredProtectedDeviceHandoff` default-off stub.
- Test cases for wrong PC, challenge, binding, generation, proof, missing authenticated verifier, false ACK, revoked consent before and after install, and unconfirmed compensation.

**LOCAL2 #4490 to implement, in its own PR only:**
- Use existing kagent protected store, validate store projection/readback corresponds to canonical binding/device/generation; reject stale/different store projection.
- Implement the versioned transcript proof **only after protected-store save/readback**.
- An actual authenticated device-specific encrypted transport and trusted gateway identity are still **unselected/unwired**. Do not invent OAuth/cookie or build an unaudited public webhook; no raw device credential may be returned in the ordinary HTTP redeem response.
- Align with latest CENTRAL HEAD; rerun Windows exact-head CI and real Windows #3099 only after a separately reviewed device transport is wired.

**Operator release HOLD:** `PROTECTED_INSTALL_TRANSPORT_WIRED=False`, `PROTECTED_INSTALL_PRODUCTION_ENABLED=False`, consent UX not mounted, shared scope not approved, DO schema not installed, Windows live E2E not proven. Both PRs remain Draft and no production enrollment is enabled.
