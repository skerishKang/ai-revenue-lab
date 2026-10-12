# LOCAL2 ↔ CENTRAL contract status — #4139 Connector enrollment

**Previously:** `BASE_CENTRAL_SHA=dbbd1633dcf3509c96d7a1a996c9b851248dd938` reported three open contract
gaps. **This revision** merge-forwards CENTRAL `7184a53b31a722cbc6235ddfdc37d0db8e1b041e` into
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
readback capability is unusable, and a redeemed challenge is consumed locally on every attempt. After that
readback the device computes CENTRAL's versioned possession proof (HMAC-SHA256 over
`padiem.connector-device-install-ack.v1`, keyed by the new credential) and carries it on the confirmation;
proof vectors pinned in `tests/test_credential_install_confirmation.py` were generated against CENTRAL's own
`installation_proof`, so the transcript is byte-identical. Nothing transmits it — no sender is wired.

**Credential bound — resolved by CENTRAL Decision A**
(`PADIEM_CONNECTOR_4139_CREDENTIAL_AUTHORITY_TRANSPORT_DECISION_20261012.md`). LOCAL2 had reported that
`installation_proof` allowed 16–4096 bytes while `kagent.ProtectedFileDeviceCredentialStore` accepts up to
16384, and asked which bound governs. CENTRAL ruled the ceiling normative from the pairing protocol
(`padiem_control_plane.local_agent_broker_pairing.MAX_PAIRING_CREDENTIAL_BYTES = 4096`, default issuance 32
bytes; `kagent.local_agent_broker_pairing_client.MAX_ENROLLMENT_CREDENTIAL_BYTES = 4096`), and that the
generic DPAPI capacity is storage headroom, not permission to exceed the pairing bound. LOCAL2's pre-store
rejection is therefore kept as-is, its comment now cites the canonical source, and
`tests/test_credential_install_confirmation.py` reads both authority values plus the default factory length
from a child interpreter to pin the mirrored constants — deliberately not by mutating `sys.path`, which would
otherwise flip the in-process S1 drift guard's skip decision.

## Platform-ownership verification (LOCAL2 read of the 2026-10-13 decision)

Checked in this tree, product-neutral registration surface first, then the instance identity:

- **No product dimension in the device authority.** `claw_connect/` contains no `product_id`, `b54`, `b62` or
  `b66` identifier in code; the enrollment request body is exactly
  `challenge_id`/`device_id`/`proof_ref`; `EnrollmentRecord.RECORD_KEYS` carries
  `device_id, binding_ref, account_ref, workspace_ref, credential_generation, credential_expires_at,
  device_lifecycle, enrolled_at, revoked, blocked_reason, contract_version` — no product field and no
  credential material (pinned in `tests/test_credential_install_windows_dpapi_store.py`). Scope arrives only
  from the server receipt, so one canonical account/PC registration is what the connector remembers.
- **One credential authority, reused not cloned.** `claw_connect` imports no `kagent`; the receiver consumes
  the canonical `DeviceCredentialStore` structurally, and the new Windows test drives the real
  `ProtectedFileDeviceCredentialStore` + current-user DPAPI port through it. LOCAL2 adds no store, no
  second PC identity and no local grant.
- **Double-redeem prohibition holds.** The connector's only redemption call is the enrollment server port;
  `_pairing_client_factory` is retained as a closed migration signal and raises
  `enrollment_scoped_redemption_required` instead of being called, and
  `test_no_generic_redeem_call_survives_in_the_connector` pins that no `.redeem(` call survives in
  `enrollment.py`. LOCAL2 therefore consumes the challenge at exactly one owner — today the #4476 server-side
  route. `REDEMPTION_OWNER=NOT_YET_SECURITY_APPROVED` remains CENTRAL's choice; if the PC-initiated
  `kagent` Broker HTTPS client is selected instead, LOCAL2 retargets this adapter rather than running both.
- **Branding/instance finding (owner decision, not fixed here).** The *authority* is product-neutral but the
  *installed identity* is Claw-branded: `@padiem/claw-connect`, `bin/claw-connect`, package description "the
  lightweight Windows tray connector for Claw Web", `CONNECT_PRODUCT = "Padiem Claw Connect"`, tray title
  and the `product` label in the local status projection (`enrollment.py:767`, `runtime.py:133`), state
  directory `%LOCALAPPDATA%\Padiem\ClawConnect`, and the single-instance mutex / quit event / HKCU `Run`
  value names `PadiemClawConnect*`. Today that is still exactly one connector per PC (one mutex, one state
  file), so registration stays single; but this naming is where a per-product fork of the one PC
  registration would originate, and the user-visible "Claw Web" label contradicts "the Connector belongs to
  the canonical Control Plane, not Claw". Renaming reaches installed users' autostart entry, mutex and
  state location, so it is left to CENTRAL/owner rather than changed unilaterally in #4490.

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
   `UnconfiguredProtectedCredentialReceiver` are still the only wired implementations. The canonical
   `kagent.WindowsDpapiProtectedDataPort` + `ProtectedFileDeviceCredentialStore` contract is now proven
   against LOCAL2's receiver on real Windows DPAPI, but nothing in the shipped runtime hands it a
   challenge-bound credential, because there is no reviewed transport to receive one from. No second store
   and no raw credential in the HTTP redeem response.
3. **Install-ack transport.** The device now computes the keyed proof after a confirmed readback, but the
   gateway that authenticates the ack *sender* and the Broker path that consumes it are unbuilt
   (`PROTECTED_INSTALL_TRANSPORT_WIRED=False`). Nothing in `claw_connect` sends an ack.
   `WINDOWS_LIVE_E2E=NOT_PROVEN`.
4. **Revoke compensation call path.** Which canonical operator the device or operator invokes after a failed
   install, and how its confirmation is authenticated, is a CENTRAL decision. Until then the security hold is
   the only honest LOCAL2 outcome for an ambiguous install.
5. **Exactly one redemption owner must be selected.** The #4139 transport decision records that
   `#4476 CanonicalConnectorEnrollmentAsyncHost.redeem()` (server-side) and
   `kagent.LocalAgentBrokerPairingClient.redeem()` (PC-side) are *alternative* consumers of the same
   single-use challenge, that running both is forbidden, and that neither is security-approved yet
   (`REDEMPTION_OWNER=NOT_YET_SECURITY_APPROVED`). LOCAL2 currently targets only the server-side route; the
   owner selection decides whether this adapter keeps that target or moves to the pinned Broker client.
6. **Account-wide surface ownership.** The B54 `/api/claw/connector/enrollments/*` handlers are transitional
   and unmounted; the single authenticated central enrollment API, the account-level Devices UI and the
   reviewed login bridges for B62/B66/Engine (`B66_LOGIN_ENROLLMENT=NOT_APPROVED`,
   `ENGINE_LOGIN_ENROLLMENT=NOT_APPROVED`) are CENTRAL ownership. LOCAL2 must not copy these routes per
   product.
7. **S1 authority merge** (LOCAL1 #4438) and the owner-consent UI/CSRF surface remain outside LOCAL2 scope;
   the in-process S1 drift guard stays skipped until then, independently of LOCAL2's subprocess authority pins.

## Flags

```
HTTP_TRANSPORT=ALIGNED_WITH_CENTRAL_7184A53B3_AND_FAIL_CLOSED
SERVER_CONTRACT_MATCH=ENVELOPE_AND_RECEIPT_PINNED
LOCAL_INSTALL_PROOF=SAVE_PLUS_READBACK_CORRELATED
WINDOWS_DPAPI_INTEGRATION=CANONICAL_STORE_CONTRACT_PASSED
INSTALL_ACK_PROOF=COMPUTED_AFTER_READBACK_NOT_TRANSMITTED
CREDENTIAL_BOUND=PAIRING_PROTOCOL_4096_RESOLVED_BY_DECISION_A
PC_REGISTRATION_SURFACE=PRODUCT_NEUTRAL
INSTANCED_IDENTITY=CLAW_BRANDED_PENDING_OWNER_DECISION
GENERIC_REDEEM_PATH=closed_no_double_redeem
REDEEMED_CHALLENGE=single_use_local_and_server_side
INSTALL_FAILURE_RECOVERY=CONTRACT_AND_TESTS_ONLY
CREDENTIAL_HANDOFF=NOT_WIRED
WINDOWS_LIVE_E2E=NOT_PROVEN
PRODUCTION=OFF
```
