# LOCAL2 ↔ CENTRAL contract status — #4139 Connector enrollment (2026-10-13 regeneration)

**Role:** LOCAL2 Windows Connector · **Parent issue:** #4139 · **Assigned PR:** #4490 (Draft)
**Supersedes for the increment only:** `PADIEM_CONNECTOR_LOCAL2_CENTRAL_CONTRACT_GAPS_20261012.md`

## 0. Reviewer note — why this is a new file and not an edit

`docs/architecture/PADIEM_CONNECTOR_LOCAL2_CENTRAL_CONTRACT_GAPS_20261012.md` is a **reviewed record**.
Once CENTRAL has read a revision of it, that revision has to stay byte-stable, otherwise the review cannot
be reproduced against the text it was performed on. LOCAL2 therefore does **not** edit it. This document is
a **new, dated regeneration** that carries forward only what changed after that review.

```
review_independence_greppable=true
reviewer_note=DO_NOT_MODIFY_PADIEM_CONNECTOR_LOCAL2_CENTRAL_CONTRACT_GAPS_20261012.md
original_file_status=UNTOUCHED_BYTE_IDENTICAL_TO_ITS_COMMITTED_REVISION
original_file_committed_at=e67ce1957
central_review=PASS_WITH_3_CORRECTIONS_2026_10_13
corrections=A_local_logout_is_not_transfer__B_local_refusal_is_not_server_rollback__C_damaged_binding_must_fail_closed
status=awaiting_central_re_review
```

The full unresolved-gap list (items 1–7, all CENTRAL/owner authority) is **deliberately not duplicated
here**. It remains authoritative in the 20261012 document, and this increment changes none of it. Restating
it in two places would create two sources of truth for the same blockers.

## 1. Divergence re-measured 2026-10-13 (no rebase performed)

| Ref | SHA |
|---|---|
| `main` | `82e4d43329767fe36d301b6ca030d7f10533f7b7` |
| LOCAL1 #4438 `local1/4139-connector-s1-enrollment-261012` | `865ad9952b4c8a9a31216dee2c7dbada16cacdcf` |
| LOCAL1 consent UI #4537 `local1/4139-connector-pc-consent-ui-261013` | `5d0246866b90827a63424bd3f91bac361be1a6cc` |
| CENTRAL #4476 `central/4139-connector-enrollment-server-261012` | `355a635a9c82fd86937f4284231558662094fd93` |
| LOCAL2 #4490 `local2/4139-windows-connector-integration` | `ba326acd86977ba892dfe1a2ffe7acfe35d81d34` |
| merge-base (#4490, #4476) | `967c3cdd9b98e28ba3f37bee8a190d4e2f4c91fc` |

`git rev-list --count` against that merge-base: `#4490` is **9 commits behind** CENTRAL and carries
**10 commits** CENTRAL does not have. The nine are:

- brand separation: `65deb9798` (cross-brand PC listings refused), `70d11d72a` (product login scope verified
  before the private Broker device lookup), `0678df930` (PADIEM vs Quote brand separation doc)
- tests: `e12977c82`, `8f1b19718` (Claw/Quote session isolation), `74875c35a` (synthetic Base64 fixture at
  runtime)
- docs: `e48576da9`, `62eb917fb` (customer-portal wording correction), `355a635a9` (GitGuardian disposition)

**Wire contract impact: none.** `git diff --name-only <merge-base>..<central>` returns no match for
`claw_connector_enrollment_routes.py` or `canonical_connector_credential_handoff.py` — the two files that
define the redeem envelope and the install-ack transcript LOCAL2 aligns to. The nine commits touch only
`apps/padiem-chat/app/padiem_pc_account_device_service.py` (+15/−15), `padiem_pc_account_devices.py` (+6),
their tests, and docs. `enrollment_http.py`'s closed key sets therefore remain correct and **no rebase was
required or performed**. The brand-separation fix is server-side; LOCAL2 adds no product dimension (§5).

## 2. LOCAL2 increment 2026-10-13 — account/scope adoption guard

`ConnectorEnrollment.complete_login` previously adopted any successful receipt in place, so a *different*
account could silently take over an already-enrolled PC. The Broker device identity is referenced by the
product sessions that were enrolled against the previous account, so re-pointing it in place would hand
those sessions to the new account. Whenever the local record already holds a binding:

| Condition | Outcome |
|---|---|
| receipt `account_ref` ≠ record `account_ref` | `EnrollmentContractError("enrollment_binding_owner_mismatch")` |
| receipt `workspace_ref` ≠ record `workspace_ref` | `EnrollmentContractError("enrollment_binding_scope_mismatch")` |
| record holds a binding but **no recorded** `account_ref` / `workspace_ref` | same bounded refusal — the record is **damaged, not unpaired**, and is repaired neither silently nor in place (CENTRAL review C) |
| same account **and** same scope | adopted (refresh / re-login unchanged) |
| no binding at all | adopted (first enrollment unchanged) |

Both refusals leave the record **byte-identical** — not revoked, `project_state` still `OFFLINE`, no binding
written — and both are existing members of the bounded S1/S2 refusal vocabulary, so nothing new is invented
and no server text or identifier is echoed.

### Two boundaries CENTRAL's review forced to be stated explicitly

**The refusal is local. It is not a server rollback.** Missing persisted owner/workspace on an
already-bound PC can be detected locally, so such a damaged record is now rejected **before remote
redemption** (two parameterized tests prove zero additional port calls). A complete local record with a
*foreign account/workspace success receipt* cannot be compared until that receipt exists; those comparisons
still run **after** the redemption call, so the request has already left the device. In that latter case
the refusal proves only that *this PC* did not adopt the receipt. It is **not**
evidence that the upstream challenge was left unconsumed, that the Broker binding was left uncreated, or that
the delivered credential was compensated — and the Connector performs no compensating call at all (no
revocation, no rollback, no challenge re-read; pinned by test). Duplicate-binding, revoke and compensation
authority stays with the canonical Broker and the enrollment server. A divergence between what the server did
and what this device recorded is a **server reconciliation/security incident**, not a routine user account
switch.

**`clear_enrollment()` is not an ownership transfer.** Logout clears only this PC's local view of the
binding. It does not revoke the canonical Broker binding, does not end an active Broker session, does not
delete the protected credential, and does not disassociate the device id — the canonical Broker refuses a
second binding for a device that already holds an active one (`duplicate_device_binding`), and S1 declares
`DEVICE_REENROLLMENT_WITHOUT_REVOKE_ALLOWED=False`. Another owner therefore still cannot adopt this device
after a local logout. A real transfer needs an owner-authorized, server-confirmed revocation/session
invalidation, a reviewed credential-store cleanup and a new enrollment — separately, and none of which the
Connector performs or claims. The stable device-id policy is preserved throughout. "After a local logout a
different account can redeem locally" is a statement about the *local record only* and must never be reported
as a supported account migration.

### Guard-flip policy (attached to the code block)

The guard carries this note at the `complete_login` refusal block:

> Flipping this guard is not a local decision. **Account switching is not a valid relaxation: a PC's device
> identity must never silently change owner.** Any future relaxation needs a reviewed justification that
> answers how the previous account's product sessions stop referring to this device identity.

Relaxing it without that justification re-opens a silent ownership transfer of live product sessions, which
is a security regression, not a UX preference.

Changed files for the increment: `apps/claw-connect/claw_connect/enrollment.py` and
`apps/claw-connect/tests/test_enrollment_contract.py` **only**, plus LOCAL2's own docs. The original
`PADIEM_CONNECTOR_LOCAL2_CENTRAL_CONTRACT_GAPS_20261012.md` is **byte-identical** to its committed revision
(`e67ce1957`), on the unmerged #4490 stack. No CENTRAL and no LOCAL1 file was modified.

## 3. Fail-closed non-regression table (§5 test set → pinning tests)

Every test below is from the increment's own revision; the full-suite and focused counts are in §4.

| §5 requirement | Pinning tests | Result |
|---|---|---|
| 1. Normal registration request contract | `test_enrollment_http_transport.py::test_normal_contract_translates_to_receipt`, `::test_request_sends_only_possession_proof_and_no_ambient_authority`; `test_enrollment_contract.py::test_successful_redemption_produces_a_paired_offline_binding`, `::test_scoped_redemption_success_records_the_server_scope` | pass |
| 2. Wrong device proof refused | `test_enrollment_contract.py::test_a_receipt_for_another_device_is_refused`, `::test_proof_vector_matches_the_s1_hmac_transcript`; `test_enrollment_http_transport.py::test_device_swap_in_success_body_is_refused` | pass |
| 3. Expired · reused token refused | `test_enrollment_contract.py::test_an_expired_credential_receipt_is_refused`, `::test_expired_and_replayed_challenges_are_refused`, `::test_expired_credential_blocks_auto_start`; `test_credential_install_confirmation.py::test_redeemed_challenge_is_single_use_even_after_a_failed_attempt` | pass |
| 4. DPAPI install failure · missing ACK | `test_credential_install_confirmation.py::test_store_failure_never_produces_a_confirmation`, `::test_installed_confirmation_without_a_valid_proof_is_unconstructible`; `test_credential_install_windows_dpapi_store.py::test_real_dpapi_save_and_readback_confirms_installation`, `::test_readback_of_a_damaged_record_refuses_confirmation`; `test_enrollment_install_gate.py::test_server_receipt_alone_never_confirms_installation` | pass |
| 5. Reconnect blocked after revocation | `test_enrollment_contract.py::test_revocation_blocks_and_survives_a_local_online_claim`, `::test_local_connected_claim_alone_never_reaches_connected`; `test_connect_lifecycle.py::test_pause_stops_reconnecting_until_the_user_resumes` | pass |
| 6. Account · brand isolation | **new** `test_enrollment_contract.py::test_account_change_on_an_enrolled_pc_is_refused_and_keeps_the_original_binding`, `::test_account_change_refusal_reports_only_the_bounded_reason`, `::test_workspace_scope_change_on_an_enrolled_pc_is_refused`, `::test_same_account_and_scope_re_enrollment_is_still_adopted`, `::test_a_local_logout_only_clears_the_local_view_of_the_binding`, `::test_a_refusal_after_a_successful_receipt_is_not_a_server_rollback`, `::test_an_enrolled_record_without_a_recorded_owner_is_refused`, `::test_an_enrolled_record_without_a_recorded_scope_is_refused`, `::test_the_connector_carries_no_product_scoped_authority_dimension`; existing `::test_cross_scope_challenge_use_is_refused`; `test_credential_install_windows_dpapi_store.py::test_connector_keeps_no_credential_and_no_product_scope_in_its_own_record` | pass |
| 7. Network failure · offline recovery | `test_enrollment_http_transport.py::test_transport_and_tls_failures_fail_closed`; `test_enrollment_contract.py::test_server_unreachable_never_shows_connected`, `::test_observed_offline_is_recorded_without_claiming_online`; `test_connect_lifecycle.py::test_network_loss_is_observed_and_moves_to_disconnected`, `::test_reconnect_backoff_is_bounded_and_capped` | pass |
| 8. No secret in logs/responses | `test_enrollment_contract.py::test_the_persisted_record_never_contains_secret_material`, `::test_the_enrollment_result_projection_is_secret_free`, `::test_status_snapshot_is_json_serialisable_and_secret_free`; `test_enrollment_install_gate.py::test_new_modules_never_log_or_print_secrets`; `test_enrollment_http_transport.py::test_success_receipt_carries_no_credential_material_to_the_ui`; `test_credential_install_windows_dpapi_store.py::test_dpapi_record_never_carries_the_plaintext_credential` | pass |

**Negative control (1st pass, 297/4 revision).** With the guard stashed, exactly the four account/scope tests
failed (`..._is_refused_and_keeps_the_original_binding`, `..._reports_only_the_bounded_reason`,
`..._workspace_scope_change_on_an_enrolled_pc_is_refused`, `..._succeeds_only_after_an_explicit_logout`) and
nothing else moved.

**Negative control (2nd pass, CENTRAL review C, 300/4 revision).** Reverting the widened guard back to
`record.account_ref is not None` makes `test_an_enrolled_record_without_a_recorded_owner_is_refused` fail
(`DID NOT RAISE`) — the C fix is the causal change. The companion
`test_an_enrolled_record_without_a_recorded_scope_is_refused` passes under **both** conditions, because the
workspace comparison was never conditional on a recorded scope; it is kept as a non-regression pin and is
*not* claimed as causal evidence.

**Mock auth is never reported as a real connection.** Every test above drives a fake
`EnrollmentServerPort` / injected probe. `WINDOWS_LIVE_E2E=NOT_PROVEN` is unchanged by this increment, and
no test asserts a real PC pairing. A green suite here means *the contract holds*, not *a PC is connected*.

## 4. Test evidence (this revision, local Windows Python 3.11, real DPAPI in-process)

| Suite | Result |
|---|---|
| `apps/claw-connect/tests/` (pytest, all) | **300 passed, 4 skipped** (1st pass was 297/4) |
| `tests/test_enrollment_contract.py` (focused) | **76 passed, 4 skipped** (was 73 + 4; +3 new) |
| `node --test tests/*.test.mjs` (tray/CLI wrapper) | **5 pass, 0 fail** |
| `claw-connect-contract-tests.yml` (CI, `windows-latest`, Python 3.12) | runs on `apps/claw-connect/**`; see the PR checks |

The 4 skips are the pre-existing `CENTRAL-CONTRACT-CONFLICT` set (the Resident/enrollment wiring CENTRAL
removed from `runtime.py`, plus the S1 drift guard that stays skipped until #4438 merges). They are not
caused by this increment.

## 5. Source-scan guard mapping

`source_scan_guard=test_the_connector_carries_no_product_scoped_authority_dimension`

The platform-ownership claim from the 20261012 document ("the registration authority is product-neutral")
was prose. It is now mechanically pinned by a test that scans `claw_connect/*.py` for `product_id`, `b54`,
`b62`, `b66` and `brand`, asserts `dataclasses.fields(EnrollmentRedemptionRequest)` is exactly
`{challenge_id, device_id, proof_ref}`, and asserts that neither the Request nor the Record field set
intersects the product / owner / workspace / consent / session field sets. If a future change introduces a
product dimension into the device authority, the suite fails rather than the claim silently going stale.

## 6. Read-only verification — scope and boundary

```
read_only_verification_scope=complete
read_only_verified_modules=claw_connect/enrollment.py, claw_connect/enrollment_http.py,
  claw_connect/credential_install.py, claw_connect/connection.py
read_only_not_verified_modules=claw_connect/tray.py, claw_connect/resident_supervisor.py,
  claw_connect/autostart.py, claw_connect/single_instance.py, claw_connect/runtime.py,
  claw_connect/__main__.py, claw_connect/menu_model.py
cpu_footprint_delta=none_no_new_process_thread_timer_socket_or_poll
tray_behaviour_delta=none
resident_behaviour_delta=none
```

Why the unverified set is safe to leave unread — stated as a mechanical fact, not a behavioural guess:

- `git diff --stat` confines the shipped change to `claw_connect/enrollment.py` and
  `claw_connect/tests/test_enrollment_contract.py`; no other module's source is touched.
- `grep -rn "complete_login\|EnrollmentService" claw_connect/` returns **no call site outside
  `enrollment.py`**, and `grep -n enroll claw_connect/{runtime,__main__,tray,menu_model,
  resident_supervisor,autostart,single_instance,connection}.py` returns **zero matches**. In this tree the
  enrollment service is not wired into the tray/Resident/autostart paths at all, so the guard is
  unreachable from them. That is also why the CPU/tray/Resident deltas above are `none`: the increment adds
  four comparisons inside an already-existing function and starts nothing.

The honest limit: this is a **static** boundary, not a runtime measurement. No process was started, no tray
icon was rendered and no Resident was supervised for this increment — that belongs to the real-PC
verification stage, which is out of scope here.

## 7. Measured, not assumed — merge status of the 20261012 document (resolved)

CENTRAL's initial instruction was that `PADIEM_CONNECTOR_LOCAL2_CENTRAL_CONTRACT_GAPS_20261012.md` was
already merged to `main`. Measured in this clone, that did **not** hold, so it was reported rather than
acted on silently. **CENTRAL's #4542 review then confirmed the measurement**, so the discrepancy is closed
and the numbers below are the record of it:

| Check | Result |
|---|---|
| `git ls-tree origin/main docs/architecture/` | the file is **absent** |
| `git log origin/main -- <that path>` | **empty** — it has never been on `main` |
| branches reachable from it | only `origin/local2/4139-windows-connector-integration` (unmerged #4490 stack) |
| PR #4529 (quoted as the merge) | `[DRAFT][#4522] B62 P01 코드 배포 전 … released_at … fail-closed`, MERGED — files are `.github/**` only, **no `docs/architecture/` file** |
| `origin/main` tip | `82e4d4332` at the time (the quoted `0b3df1e7` is **not an object in this clone**); it has since advanced to `d15c944b2` |
| `origin/central/…` tip | `355a635a9` (the quoted `93bf4662` is **not an object in this clone**) |
| quoted rev `78d7cdd` | **not an object in this clone** |

CENTRAL's ruling from the #4542 review, quoted so no future reader re-litigates it:

> "The reference discrepancies `0b3df1e7/93bf4662/78d7cdd` are **not authorized target SHAs**; use fetched
> actual refs. The 20261012 original doc is on the unmerged #4490 stack, not main, and **must remain
> byte-identical**."

The instruction's *effect* is unaffected and was followed: the 20261012 file is untouched, and the increment
lands in this new dated document.

## 8. Resolved by the same review

1. **Base of this Draft PR:** confirmed. `#4542` keeps base `local2/4139-windows-connector-integration` (#4490
   head), so its diff contains only LOCAL2's own files; CENTRAL accepted the isolation.
2. **Scope of the fix:** confirmed. Corrections were confined to `apps/claw-connect/claw_connect/enrollment.py`,
   its contract tests, and the two already-touched LOCAL2 docs. No new PR, no #4490 force push, no MAIN rebase,
   no CENTRAL/LOCAL1 code.
3. **Force-pilot refs:** answered above — `0b3df1e7/93bf4662/78d7cdd` are not authorized targets, so nothing in
   this work is anchored to them.

Still CENTRAL-owned (unchanged by this increment): mounting the enrollment routes and wiring the device
gateway, the authenticated credential delivery channel, the install-ack sender/verifier, the revoke
compensation operator, the single redemption owner, and the real-Windows E2E (#3099). See
`PADIEM_CONNECTOR_LOCAL2_CENTRAL_CONTRACT_GAPS_20261012.md` items 1–7.

## 9. Flags

```
ROLE=LOCAL2_WINDOWS_CONNECTOR
HTTP_TRANSPORT=ALIGNED_WITH_CENTRAL_355A635A9_AND_FAIL_CLOSED
SERVER_CONTRACT_MATCH=ENVELOPE_AND_RECEIPT_PINNED
LOCAL_INSTALL_PROOF=SAVE_PLUS_READBACK_CORRELATED
WINDOWS_DPAPI_INTEGRATION=CANONICAL_STORE_CONTRACT_PASSED
INSTALL_ACK_PROOF=COMPUTED_AFTER_READBACK_NOT_TRANSMITTED
CREDENTIAL_BOUND=PAIRING_PROTOCOL_4096_RESOLVED_BY_DECISION_A
ACCOUNT_ISOLATION=FAIL_CLOSED_BOUNDED_REASONS_RECORD_UNCHANGED
DAMAGED_BINDING_WITHOUT_OWNER=REFUSED_NOT_REPAIRED
LOCAL_REFUSAL_IS_NOT_SERVER_ROLLBACK=BOUNDARY_STATED_AND_TESTED
CLEAR_ENROLLMENT=LOCAL_VIEW_ONLY_NOT_OWNERSHIP_TRANSFER
PC_REGISTRATION_SURFACE=PRODUCT_NEUTRAL
INSTANCED_IDENTITY=CLAW_BRANDED_PENDING_OWNER_DECISION
GENERIC_REDEEM_PATH=closed_no_double_redeem
REDEEMED_CHALLENGE=single_use_local_and_server_side
INSTALL_FAILURE_RECOVERY=CONTRACT_AND_TESTS_ONLY
CREDENTIAL_HANDOFF=NOT_WIRED
WINDOWS_LIVE_E2E=NOT_PROVEN
PRODUCTION=OFF
REBASE_PERFORMED=no
STATUS=awaiting_central_re_review
```
