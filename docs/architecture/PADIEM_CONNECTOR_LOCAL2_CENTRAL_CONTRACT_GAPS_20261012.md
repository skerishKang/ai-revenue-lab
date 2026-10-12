# LOCAL2 ↔ CENTRAL contract status — #4139 Connector enrollment

**Previously:** `BASE_CENTRAL_SHA=dbbd1633dcf3509c96d7a1a996c9b851248dd938` reported three open contract
gaps. **This revision** merge-forwards CENTRAL `26443796172f22cb7b221729db0afd9f87b98ce1` into
`local2/4139-windows-connector-integration`, so the gaps below are restated against the code that is
actually in this tree, not against the older base.
**S2 source:** `ca8c8c23ef293f1451f7829831cbc4a483694940` (PR #4463) · **Role:** LOCAL2 Windows Connector.
No CENTRAL or LOCAL1 file was modified by LOCAL2 in this revision.

## Resolved by CENTRAL (verified in this tree, no LOCAL2 duplication)

| Former gap | Now | Evidence in this merge |
|---|---|---|
| Success receipt carried no `consent_id`; S2 required one | Server-owned `consent_id` is published in the redeem receipt | `_PUBLIC_REDEEM_FIELDS` / `_redeem_success` in `apps/padiem-chat/app/claw_connector_enrollment_routes.py` |
| Refusals exposed only `error.code`; S2 needed a bounded reason | `{ok:false,error:{code},reason,retryable:false}` with a pinned alias table (`_S2_REDEEM_REFUSALS`, `_S2_REDEEM_REFUSAL_ALIASES`) | same file; every emittable reason is pinned as a member of `ENROLLMENT_REFUSAL_REASONS` by `tests/test_enrollment_http_transport.py` |
| Sync service and async host could project different bodies | One strict secret-free envelope for both paths, 503 on any forged/extra/expired/ONLINE claim | `_redeem_success` is the single success builder used by both branches |
| No device installation acknowledgement definition | Closed keyed install-ack contract, default OFF | `apps/padiem-chat/app/canonical_connector_credential_handoff.py` (`DeviceCredentialInstallAck`, `installation_proof`, `verify_install_ack`, `PROTECTED_INSTALL_TRANSPORT_WIRED=False`) |
| claw-connect had no CI job | `windows-latest` pytest + Node gate inherited from `main` | `.github/workflows/claw-connect-contract-tests.yml` |

The stale constant `CENTRAL_SUCCESS_CONSENT_ID_PRESENT=False`, the central-code→fallback collapse table, and
this document's earlier "central omits consent_id" report are all removed: `enrollment_http.py` now *requires*
the field and never synthesizes it.

## LOCAL2 side now enforced at the device boundary

`claw_connect/enrollment_http.py`: closed top-level shapes, receipt key set that must match the thirteen
published fields exactly (extra keys such as `credential_b64`, tokens, owner claims or a store fingerprint are
refused), `credential_installed_by_canonical_handoff is True`, `lifecycle == paired_offline`, all permission
booleans false, positive non-bool generation, timezone-aware future expiry, exact `device_id` correlation,
central-shaped refs, `retryable` accepted only as `false`, and `error.code` shape-checked then discarded.
Status/body disagreement is refused in both directions.

`claw_connect/credential_install.py`: a confirmation requires the store's projection to name the *same*
`binding_ref`, `device_id` and `credential_generation` as the binding handed to `save`, plus a protected
`load` readback of the identical bytes under that binding context. Only
`protected_store_save_readback` — the proof kind CENTRAL's install ack accepts — is citable, a store without
readback capability is unusable, and a redeemed challenge is consumed locally on every attempt.

`plan_install_failure_recovery` encodes CENTRAL's recovery decision: confirmed canonical revocation →
`new_challenge_required`; unconfirmed or refused revocation → `security_hold_reconciliation_required`. Both
carry `report_enrolled=false`, `retry_same_challenge=false`, `retransmit_credential=false` and require a fresh
OWNER consent, and the unsafe variants are unconstructible. LOCAL2 never revokes a Broker binding itself and
never claims a revocation result.

## Remaining gaps (CENTRAL / owner authority, not closable by LOCAL2 source)

1. **Route still unmounted, gateway still unwired.** `ENROLLMENT_PRODUCT_HTTP_MOUNTED`,
   `ENROLLMENT_PRODUCT_AUTHENTICATION_WIRED`, `ENROLLMENT_PRODUCT_DURABLE_CONSENT_WIRED`,
   `ENROLLMENT_PRODUCT_CREDENTIAL_HANDOFF_WIRED` and `ENROLLMENT_PRODUCT_PRODUCTION_ACTIVE` are all `False`
   in this tree, so `HttpsEnrollmentServerPort` refuses before any socket opens
   (`CENTRAL_DEVICE_GATEWAY_WIRED=False`).
2. **No authenticated delivery channel for the credential.** `UnconfiguredProtectedDeviceHandoff` and
   `UnconfiguredProtectedCredentialReceiver` are the only wired implementations. The PC-side installer must
   reuse `kagent.WindowsDpapiProtectedDataPort` + `ProtectedFileDeviceCredentialStore` through the structural
   port here — no second store, and no raw credential in the HTTP redeem response.
3. **Install-ack transport.** The keyed transcript exists, but the gateway that authenticates the ack sender
   and the Broker path that consumes it are unbuilt. `WINDOWS_LIVE_E2E=NOT_PROVEN`.
4. **Revoke compensation call path.** Which canonical operator the device or operator invokes after a failed
   install, and how its confirmation is authenticated, is a CENTRAL decision. Until then the security hold is
   the only honest LOCAL2 outcome for an ambiguous install.
5. **S1 authority merge** (LOCAL1 #4438) and the owner-consent UI/CSRF surface remain outside LOCAL2 scope;
   the S1 drift guard stays skipped until then.

## Flags

```
HTTP_TRANSPORT=ALIGNED_WITH_CENTRAL_264437961_AND_FAIL_CLOSED
SERVER_CONTRACT_MATCH=ENVELOPE_AND_RECEIPT_PINNED
LOCAL_INSTALL_PROOF=SAVE_PLUS_READBACK_CORRELATED
REDEEMED_CHALLENGE=single_use_local_and_server_side
INSTALL_FAILURE_RECOVERY=CONTRACT_AND_TESTS_ONLY
CREDENTIAL_HANDOFF=NOT_WIRED
WINDOWS_LIVE_E2E=NOT_PROVEN
PRODUCTION=OFF
```
