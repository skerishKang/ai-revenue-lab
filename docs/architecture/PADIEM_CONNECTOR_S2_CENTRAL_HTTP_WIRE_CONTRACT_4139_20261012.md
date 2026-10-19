# PADIEM Connector S2 ↔ CENTRAL Enrollment Wire Contract (#4139)

**Scope:** Server-owned source contract for LOCAL2 #4463 / CENTRAL #4476, 2026-10-12 KST.
**Activation:** Source-only. No public route, schema migration, Windows secret handoff or operational enrollment has been activated.

## 1. Origin and request

Device redemption endpoint: **POST /api/claw/connector/enrollments/redeem**

Accepted JSON body contains **exactly** three keys:
- **challenge_id:** canonical Broker-issued pairing challenge reference
- **device_id:** requesting PC identifier
- **proof_ref:** canonical S1 pairing-proof followed by 64 lower-case hex characters

No session, owner, consent, account, workspace, browser cookie, OAuth token or raw pairing code may be submitted by the device. The trusted TLS device gateway and canonical Broker/Identity DO must independently verify the request. Unmounted/default-off routes fail closed.

The browser issue endpoint **POST /api/claw/connector/enrollments/issue** accepts only device_id after B54 session and CSRF checks. The canonical one-time code must be released only after the challenge is durably bound to the original login session and consent has been rechecked.

## 2. Success HTTP envelope

After server-side Broker redemption, fresh owner-consent revalidation and **confirmed protected credential handoff**, the only HTTP 200 response is a JSON object whose top level contains **ok=true** and **enrollment**. The enrollment object contains:

| Key | Type and required value |
| --- | --- |
| binding_ref | Canonical server reference |
| device_id | Exact requested PC |
| account_ref / workspace_ref | Canonical Broker-owned scope |
| consent_id | Fresh canonical Identity DO authorization ID, never client-supplied |
| credential_generation | Positive integer, not bool |
| credential_expires_at | Valid future timezone-aware ISO 8601 string |
| credential_installed_by_canonical_handoff | true |
| raw_device_credential | false |
| lifecycle | paired_offline |
| dispatch_authorized | false |
| grants_read / grants_write | false / false |

Both original S1 synchronous service and async Identity/Broker host now pass through the same strict HTTP success projection. Missing or extra fields, secrets such as credential_b64, altered scope, missing consent_id, expired credentials, or READ/WRITE/ONLINE claims must yield 503 refusal rather than a fabricated enrollment.

This HTTP receipt **never carries a raw credential**. It cannot independently prove local Windows installation; only a reviewed authenticated protected handoff/device acknowledgement can do so. Receipt alone is not an ONLINE / CONNECTED transition; that requires a separate canonical Broker session/device proof.

## 3. Refusal HTTP envelope

Non-2xx device failure has three bounded elements:
- **ok=false**
- **error.code:** sanitized canonical server diagnostic code (never raw exception text)
- **reason:** reviewed LOCAL2 S1-compatible refusal, and **retryable=false**

Current explicit canonical-to-LOCAL2 reason mappings:
- enrollment_consent_changed_during_redeem → enrollment_consent_withdrawn
- credential_handoff_unavailable → enrollment_dependency_unavailable
- enrollment_credential_handoff_failed → enrollment_dependency_refused
- enrollment_handoff_revoke_unconfirmed → enrollment_dependency_unavailable
- enrollment_consent_race_revoke_unconfirmed → enrollment_dependency_unavailable
- pairing_challenge_already_redeemed → enrollment_duplicate_redeem_denied
- invalid_pairing_proof → enrollment_proof_invalid

Known bounded S1 reasons pass through unchanged. Unknown/untrusted codes map to enrollment_dependency_refused; upstream messages, credentials and internal tracebacks are not echoed. All success/error responses have **Cache-Control: no-store**. The existing LOCAL2 EnrollmentRedemptionResponse remains a typed client representation built **only after** pinned TLS, exact HTTP envelope and device-field validation.

## 4. Explicit unresolved transport and release gates

CENTRAL ProtectedDeviceCredentialHandoff.ready()/deliver_once() is **an interface**, not an authenticated network channel or a Windows DPAPI installation acknowledgement. The missing device-side installer must reuse the existing kagent WindowsDpapiProtectedDataPort / ProtectedFileDeviceCredentialStore and existing Broker lifecycle. Do not place the raw Broker credential in the redemption HTTP response, invent another credential store, or trust a receipt echo. Define authenticated PC-to-host handoff identity, secret transfer, challenge-bound installation acknowledgement, retry/replay prevention, and Broker revoke compensation for failed/ambiguous installation.

Required before any production activation: signed-in canonical OWNER consent UI + CSRF; security review of legacy B62 shared connector context; explicit existing Identity and Broker DO schema installation; rate-limited trusted TLS gateway; reviewed app route mount and server-side Service Binding factory; LOCAL1 #4438 and LOCAL2 #4463 integration; real Windows #3099 E2E. PR #4476 remains Draft, unmerged, PRODUCTION_ENROLLMENT=OFF.

**Operator outcome:** GitHub-only contract implementation and tests can proceed. No production schema, secret, Windows credential, or user account is modified by this document.
