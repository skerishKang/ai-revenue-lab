# LOCAL2 → CENTRAL contract gaps — #4139 Connector enrollment

**BASE_CENTRAL_SHA:** `dbbd1633dcf3509c96d7a1a996c9b851248dd938` (PR #4476)
**S2_SOURCE_SHA:** `ca8c8c23ef293f1451f7829831cbc4a483694940` (PR #4463)
**Role:** LOCAL2 Windows Connector integration. This document reports gaps only;
no central file was modified.

## Summary

The LOCAL2 HTTP transport adapter is implemented against the central redeem
route and fails closed on every mismatch. Three contract gaps remain and need a
central CTO decision. Until then `CREDENTIAL_HANDOFF=NOT_WIRED` and production
enrollment is refused.

## Gap 1 — redeem HTTP envelope and field differences

Central success body
(`apps/padiem-chat/app/claw_connector_enrollment_routes.py:263`):
`{"ok": true, "enrollment": {...}}`, where the inner object is built in
`apps/padiem-chat/app/canonical_connector_enrollment_async_host.py:186-198`:

`binding_ref, device_id, account_ref, workspace_ref, credential_generation,
credential_expires_at, lifecycle, credential_installed_by_canonical_handoff,
raw_device_credential, dispatch_authorized, grants_read, grants_write`

LOCAL2 receipt (`apps/claw-connect/claw_connect/enrollment.py:513`,
`EnrollmentRedemptionResponse`) is **flat** and requires, on success,
`binding_ref, device_id, account_ref, workspace_ref, consent_id`
(`enrollment.py:542-549`).

| Difference | Central | LOCAL2 | Adapter behaviour |
|---|---|---|---|
| Envelope | `{ok, enrollment:{...}}` | flat `ok + fields` | unwrapped |
| `consent_id` | **not sent** | **required** | fail closed: `enrollment_response_consent_id_missing` |
| Error shape | `{ok:false, error:{code}}` | bounded `reason` | mapped, see below |
| Request keys | exactly `challenge_id, device_id, proof_ref` (`routes.py:242`) | `safe_dict()` emits 8 keys (`enrollment.py:499`) | adapter sends only the 3 central keys |

**Request needed:** add `consent_id` to the central success body, or confirm the
S2 receipt should not require it.

Central refusal codes **not present** in the S2 vocabulary
(`ENROLLMENT_REFUSAL_REASONS`), so the adapter drops them to
`enrollment_dependency_refused`:
`connector_enrollment_csrf_denied`, `connector_enrollment_explicit_consent_required`,
`connector_enrollment_receipt_invalid`, `connector_enrollment_invalid_request`,
`connector_enrollment_device_gateway_denied`, `enrollment_credential_handoff_failed`,
`credential_handoff_unavailable`, `enrollment_server_dependency_unavailable`,
`invalid_enrollment_request`, `invalid_pairing_proof`.

**Request needed:** decide whether to widen the S2 refusal vocabulary or accept
the fallback collapse (which also makes those refusals non-retryable).

Also noted: the route is not mounted (`ENROLLMENT_PRODUCT_HTTP_MOUNTED = False`,
`routes.py:34`) and requires a device gateway (`gateway.verify(request)`) that is
not wired, so live calls 503 today.

## Gap 2 — `deliver_once()` ↔ Windows receiver

Central contract
(`apps/padiem-chat/app/canonical_connector_enrollment_async_host.py:22-29`):

```
class ProtectedDeviceCredentialHandoff(Protocol):
    async def ready(*, challenge_id, device_id) -> bool
    async def deliver_once(*, challenge_id, device_id, credential: bytes, enrollment, now) -> bool
```

Called at `async_host.py:116-133` (ready) and `:162` (deliver_once). No transport
channel, device identity/attestation, or acknowledgement semantics are defined,
and `ENROLLMENT_PRODUCT_CREDENTIAL_HANDOFF_WIRED = False` (`routes.py:37`).

LOCAL2 side: no receiver existed. This PR adds
`apps/claw-connect/claw_connect/credential_install.py` with a structural port and
a **disabled** default (`CREDENTIAL_HANDOFF_WIRED = False`). The canonical store
(`kagent.WindowsDpapiProtectedDataPort` + `ProtectedFileDeviceCredentialStore`) is
reused through a structural protocol; no second store is created.

**Request needed:** define the authenticated delivery channel, the device
identity the PC must present, and how the server confirms the PC actually
installed the credential (server flag alone is not accepted).

## Gap 3 — redeemed credential: install failure, duplicate delivery, revoke recovery

Central behaviour today
(`canonical_connector_enrollment_async_host.py:170-182`):
handoff failure → revoke Broker binding → `enrollment_credential_handoff_failed`
(503); unconfirmed revoke → `enrollment_handoff_revoke_unconfirmed` (503).
Consent race → revoke → `enrollment_consent_changed_during_redeem` (403).

LOCAL2 side: the adapter keeps refusals bounded and non-retryable (the central
dependency codes are not in the S2 vocabulary, so `retryable` is always False).

**Request needed:** define recovery for a credential that was redeemed but not
installed — is a new challenge issued, or is there an idempotent replay window?
And confirm the canonical revoke path LOCAL2 should call when its local store
fails after a successful server redeem.

## Flags

```
HTTP_TRANSPORT=IMPLEMENTED_FAIL_CLOSED
SERVER_CONTRACT_MATCH=PARTIAL
CREDENTIAL_HANDOFF=NOT_WIRED
CENTRAL_CONTRACT_GAPS=3
PRODUCTION=OFF
```
