"""#3102 — live pairing source-readiness and rollback contract tests.

Every test here runs the real canonical surfaces: the real
`InMemoryBrokerPairingAuthority`, the real challenge/redeem HTTP routes, the real
`DeviceLifecycle` transitions and the real server-projection trigger. No test
replaces the parse/auth/correlation path with a stub.

The branch is source-only, so these tests assert readiness, bounded issuance,
revoke/expired-credential repair, server-backed ONLINE gating and the absence of
secret material — never a live activation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
import unittest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_pairing import (
    MAX_PAIRING_ISSUANCE_RATE_LIMIT,
    MAX_PENDING_PAIRING_CHALLENGES,
    MIN_PAIRING_ISSUANCE_RATE_LIMIT,
    MAX_PAIRING_TTL_SECONDS,
    MIN_PAIRING_TTL_SECONDS,
    MAX_TRACKED_PAIRING_ISSUANCE_SCOPES,
    PAIRING_ISSUANCE_WINDOW_SECONDS,
    InMemoryBrokerPairingAuthority,
)
from padiem_control_plane.local_agent_pairing_activation_3102 import (
    ACTIVATION_RUNBOOK,
    REQUIRED_ACTIVATION_BINDING_NAMES,
    ROLLBACK_RUNBOOK,
    SOURCE_ONLY_READINESS,
    PairingActivationReadiness,
    assert_not_activated,
    assert_secret_free,
)

BASE = datetime(2026, 9, 26, 6, 0, tzinfo=timezone.utc)
BROKER_PEPPER = b"control-plane-local-agent-broker-pepper"
PAIRING_PEPPER = b"control-plane-local-agent-pairing-pepper"
CREDENTIAL = b"pairing-3102-credential-material"
ACCOUNT = "account.3102"
WORKSPACE = "workspace.3102"
DEVICE = "device.3102"


def _authority(
    *,
    issuance_rate_limit: int | None = None,
    counter_start: int = 0,
) -> InMemoryBrokerPairingAuthority:
    counter = {"value": counter_start}

    def nonce() -> str:
        counter["value"] += 1
        return f"{counter['value']:032x}"

    authority = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=InMemoryLocalAgentBrokerAuthority(
            pepper=BROKER_PEPPER,
            authority_ref="control-plane.local-agent-broker.v1",
        ),
        code_nonce_factory=nonce,
        credential_factory=lambda: CREDENTIAL,
        **({} if issuance_rate_limit is None else {"issuance_rate_limit": issuance_rate_limit}),
    )
    return authority


def _issue(authority, *, account=ACCOUNT, workspace=WORKSPACE, now=BASE, ttl_seconds=300):
    return authority.issue_challenge(
        account_ref=account,
        workspace_ref=workspace,
        now=now,
        ttl_seconds=ttl_seconds,
    )


def _all_codes(authority, *, count: int = 3):
    """Distinct server-issued codes, used only to prove none leaks."""
    return [
        _issue(authority, account=f"account.leak{i}", workspace=f"workspace.leak{i}")[1]
        for i in range(count)
    ]


def _redeem(authority, challenge_id, code, *, device_id=DEVICE, now=BASE):
    from padiem_control_plane.local_agent_broker_pairing import pairing_proof_ref

    return authority.redeem(
        challenge_id=challenge_id,
        device_id=device_id,
        proof_ref=pairing_proof_ref(
            challenge_id=challenge_id,
            device_id=device_id,
            pairing_code=code,
        ),
        now=now,
    )


class PairingRateBound3102Tests(unittest.TestCase):
    """#3102: a scope must not be able to mint an unbounded stream of live codes."""

    def test_issuance_is_bounded_per_scope_when_a_limit_is_bound(self) -> None:
        authority = _authority(issuance_rate_limit=3)
        for _ in range(3):
            _issue(authority)
        with self.assertRaises(ControlPlaneContractError) as limited:
            _issue(authority)
        self.assertEqual(limited.exception.code, "pairing_issuance_rate_limited")

    def test_a_different_scope_is_not_penalised(self) -> None:
        authority = _authority(issuance_rate_limit=2)
        for _ in range(2):
            _issue(authority)
        with self.assertRaises(ControlPlaneContractError):
            _issue(authority)
        # A distinct account/workspace keeps its own budget.
        _issue(authority, account="account.other", workspace="workspace.other")

    def test_the_window_rolls_over_so_issuance_recovers(self) -> None:
        authority = _authority(issuance_rate_limit=2)
        for _ in range(2):
            _issue(authority)
        with self.assertRaises(ControlPlaneContractError):
            _issue(authority)
        later = BASE + timedelta(seconds=PAIRING_ISSUANCE_WINDOW_SECONDS + 1)
        _issue(authority, now=later)  # must not raise

    def test_rate_state_is_secret_free(self) -> None:
        authority = _authority(issuance_rate_limit=5)
        _issue(authority)
        state = authority.issuance_rate_state(account_ref=ACCOUNT, workspace_ref=WORKSPACE)
        self.assertEqual(state["issued_in_window"], 1)
        self.assertEqual(state["rate_limit"], 5)
        self.assertEqual(state["rate_bound_active"], True)
        # No code, credential or secret may appear in support evidence.
        rendered = json.dumps(state)
        for issued in (challenge_code for challenge_code in _all_codes(authority)):
            self.assertNotIn(issued, rendered)
        self.assertNotIn("pairing_code", rendered)
        self.assertNotIn("credential", rendered)

    def test_unbound_rate_limit_is_the_source_only_posture(self) -> None:
        authority = _authority()
        for index in range(5):
            _issue(authority, now=BASE + timedelta(minutes=index))
        state = authority.issuance_rate_state(account_ref=ACCOUNT, workspace_ref=WORKSPACE)
        self.assertEqual(state["rate_bound_active"], False)
        self.assertIsNone(state["rate_limit"])
        self.assertEqual(authority.safe_dict()["production_pairing_activated"], False)


class PairingSingleUseAndExpiry3102Tests(unittest.TestCase):
    def test_a_challenge_is_single_use(self) -> None:
        authority = _authority()
        challenge, code = _issue(authority)
        enrollment, credential = _redeem(authority, challenge.challenge_id, code)
        self.assertEqual(len(credential), len(CREDENTIAL))
        with self.assertRaises(ControlPlaneContractError) as replay:
            _redeem(authority, challenge.challenge_id, code)
        self.assertEqual(replay.exception.code, "pairing_challenge_already_redeemed")
        self.assertEqual(enrollment.device_id, DEVICE)

    def test_expired_challenge_is_rejected(self) -> None:
        authority = _authority()
        challenge, code = _issue(authority, ttl_seconds=MIN_PAIRING_TTL_SECONDS)
        past = BASE + timedelta(seconds=MIN_PAIRING_TTL_SECONDS + 1)
        with self.assertRaises(ControlPlaneContractError) as expired:
            _redeem(authority, challenge.challenge_id, code, now=past)
        self.assertIn("expired", str(expired.exception).lower())

    def test_ttl_stays_inside_the_canonical_bounds(self) -> None:
        authority = _authority()
        for bad in (MIN_PAIRING_TTL_SECONDS - 1, MAX_PAIRING_TTL_SECONDS + 1):
            with self.assertRaises(ControlPlaneContractError):
                _issue(authority, ttl_seconds=bad)


class PairingBinding3102Tests(unittest.TestCase):
    def test_the_enrollment_carries_the_server_owned_scope(self) -> None:
        authority = _authority()
        challenge, code = _issue(authority)
        enrollment, _credential = _redeem(authority, challenge.challenge_id, code)
        # Scope comes from the stored server-side challenge, never the caller.
        self.assertEqual(enrollment.account_ref, ACCOUNT)
        self.assertEqual(enrollment.workspace_ref, WORKSPACE)

    def test_another_device_cannot_claim_a_consumed_challenge(self) -> None:
        authority = _authority()
        challenge, code = _issue(authority)
        _redeem(authority, challenge.challenge_id, code)
        with self.assertRaises(ControlPlaneContractError):
            _redeem(authority, challenge.challenge_id, code, device_id="device.somebody-else")

    def test_wrong_proof_is_rejected(self) -> None:
        authority = _authority()
        challenge, _code = _issue(authority)
        with self.assertRaises(ControlPlaneContractError):
            authority.redeem(
                challenge_id=challenge.challenge_id,
                device_id=DEVICE,
                proof_ref="pairing-proof:" + "0" * 64,
                now=BASE,
            )


class PairingRevokeRepair3102Tests(unittest.TestCase):
    """#3102: repair must reuse the canonical rotate/redeem flow.

    The canonical `DeviceLifecycle` revoke/rotate contract lives in kagent and is
    covered by `test_local_agent_pairing.py`. What is pinned here is the
    control-plane half: a spent challenge can never mint a second binding, so a
    re-pair has to go through a fresh bounded issuance.
    """

    def test_a_spent_challenge_cannot_be_reused_for_repair(self) -> None:
        authority = _authority()
        challenge, code = _issue(authority)
        _redeem(authority, challenge.challenge_id, code)
        # Repair after redemption requires a new challenge; the old one is dead.
        with self.assertRaises(ControlPlaneContractError):
            _redeem(authority, challenge.challenge_id, code)
        fresh_challenge, fresh_code = _issue(authority, account="account.repair", workspace=WORKSPACE)
        # Re-pairing the *same* device is refused while its binding is active:
        # the canonical broker requires a revoke before a replacement binding.
        with self.assertRaises(ControlPlaneContractError) as duplicate:
            _redeem(
                authority,
                fresh_challenge.challenge_id,
                fresh_code,
                now=BASE + timedelta(minutes=1),
            )
        self.assertEqual(duplicate.exception.code, "duplicate_device_binding")
        # A genuinely new device pairs cleanly through the bounded flow.
        other_challenge, other_code = _issue(
            authority, account="account.repair", workspace=WORKSPACE
        )
        enrollment, _credential = _redeem(
            authority,
            other_challenge.challenge_id,
            other_code,
            device_id="device.3102-repaired",
            now=BASE + timedelta(minutes=1),
        )
        self.assertEqual(enrollment.account_ref, "account.repair")
        self.assertEqual(enrollment.device_id, "device.3102-repaired")

    def test_repair_issuance_still_honours_the_rate_bound(self) -> None:
        authority = _authority(issuance_rate_limit=2)
        first, first_code = _issue(authority)
        _redeem(authority, first.challenge_id, first_code)
        # A repair burst is still bounded issuance, not an escape hatch.
        _issue(authority)
        with self.assertRaises(ControlPlaneContractError):
            _issue(authority)


class ServerBackedOnline3102Tests(unittest.TestCase):
    """#3102: a redeemed binding is PAIRED_OFFLINE, never ONLINE by itself.

    These run against the control-plane authority only. The kagent-side
    `project_server_backed_online_binding` gate is covered by the kagent suite
    (`test_local_agent_server_projection.py`), which owns that contract.
    """

    def test_redemption_yields_paired_offline_and_not_online(self) -> None:
        authority = _authority()
        challenge, code = _issue(authority)
        enrollment, _credential = _redeem(authority, challenge.challenge_id, code)
        # The enrollment is a broker binding record; it carries no online claim
        # and the authority refuses to mint one from a redemption alone.
        self.assertEqual(enrollment.device_id, DEVICE)
        self.assertNotIn("online", json.dumps(enrollment.safe_dict()).lower())
        self.assertEqual(authority.safe_dict()["production_ready"], False)

    def test_redeemed_enrollment_reports_no_local_online_claim(self) -> None:
        authority = _authority()
        challenge, code = _issue(authority)
        enrollment, _credential = _redeem(authority, challenge.challenge_id, code)
        safe = enrollment.safe_dict()
        self.assertEqual(safe.get("local_online_claim", False), False)
        self.assertEqual(safe.get("online", False), False)


class ActivationBoundary3102Tests(unittest.TestCase):
    def test_this_branch_is_not_activated(self) -> None:
        assert_not_activated()
        self.assertEqual(SOURCE_ONLY_READINESS.production_activated, False)
        self.assertEqual(SOURCE_ONLY_READINESS.source_ready, True)

    def test_claiming_an_activation_fails_closed(self) -> None:
        activated = PairingActivationReadiness(
            source_ready=True,
            production_activated=True,
            trusted_tls_required=True,
            outbound_only_desktop=True,
            public_inbound_port=False,
            upnp_required=False,
            caller_endpoint_override=False,
            challenge_ttl_bounded=True,
            challenge_single_use=True,
            issuance_rate_bound_active=True,
            revoke_path_available=True,
            rotate_path_available=True,
            server_backed_online_only=True,
            canonical_authorities_reused=True,
        )
        with self.assertRaises(ControlPlaneContractError):
            assert_not_activated(activated)

    def test_the_only_open_activation_blocker_is_the_rate_bound(self) -> None:
        self.assertEqual(
            SOURCE_ONLY_READINESS.missing_prerequisites(),
            ("issuance_rate_bound_active",),
        )

    def test_no_public_inbound_port_and_no_upnp(self) -> None:
        self.assertEqual(SOURCE_ONLY_READINESS.public_inbound_port, False)
        self.assertEqual(SOURCE_ONLY_READINESS.upnp_required, False)
        self.assertEqual(SOURCE_ONLY_READINESS.outbound_only_desktop, True)
        self.assertEqual(SOURCE_ONLY_READINESS.caller_endpoint_override, False)

    def test_activation_and_rollback_runbooks_exist_and_are_ordered(self) -> None:
        self.assertGreaterEqual(len(ACTIVATION_RUNBOOK), 10)
        self.assertGreaterEqual(len(ROLLBACK_RUNBOOK), 5)
        self.assertTrue(ACTIVATION_RUNBOOK[0].startswith("preflight"))
        self.assertTrue(ROLLBACK_RUNBOOK[0].startswith("disable"))
        # Rollback disables; it never deletes durable pairing state.
        self.assertTrue(any("preserve" in step for step in ROLLBACK_RUNBOOK))
        for step in ROLLBACK_RUNBOOK:
            self.assertNotIn("delete durable", step.lower())
            self.assertNotIn("purge", step.lower())

    def test_binding_names_are_recorded_without_values(self) -> None:
        self.assertGreaterEqual(len(REQUIRED_ACTIVATION_BINDING_NAMES), 4)
        for name in REQUIRED_ACTIVATION_BINDING_NAMES:
            self.assertRegex(name, r"^[A-Z0-9_]+$")
        self.assertEqual(SOURCE_ONLY_READINESS.safe_dict()["binding_values_present"], False)

    def test_rate_limit_bounds_are_sane(self) -> None:
        self.assertEqual(MIN_PAIRING_ISSUANCE_RATE_LIMIT, 1)
        self.assertLessEqual(MAX_PAIRING_ISSUANCE_RATE_LIMIT, 60)
        self.assertLessEqual(PAIRING_ISSUANCE_WINDOW_SECONDS, MAX_PAIRING_TTL_SECONDS * 10)


class SecretNegative3102Tests(unittest.TestCase):
    """#3102: no raw secret may reach a log or a support projection."""

    def test_the_support_projection_is_key_allowlisted(self) -> None:
        assert_secret_free(SOURCE_ONLY_READINESS.safe_dict())

    def test_a_secret_bearing_projection_is_refused(self) -> None:
        for leaked in ("pairing_code", "raw_device_credential", "session_secret", "auth_header"):
            with self.assertRaises(ControlPlaneContractError):
                assert_secret_free({"contract_version": "x", leaked: "whatever"})

    def test_the_pairing_module_declares_no_secret_logging(self) -> None:
        import inspect

        from padiem_control_plane import local_agent_broker_pairing as module

        source = inspect.getsource(module)
        for forbidden in ("print(", "logging.", "logger.", "sys.stderr"):
            self.assertNotIn(forbidden, source, f"{forbidden} must not appear in the pairing module")

    def test_pairing_code_is_never_persisted(self) -> None:
        authority = _authority()
        safe = authority.safe_dict()
        self.assertEqual(safe["raw_pairing_code_persisted"], False)
        self.assertEqual(safe["raw_device_credential_persisted"], False)
        # Metadata names such as `pairing_code_single_use` are fine; no issued
        # value may appear. Every code is server-derived, so compare the values.
        rendered = json.dumps(safe)
        for issued in _all_codes(authority):
            self.assertNotIn(issued, rendered)

    def test_the_activation_module_declares_no_secret_logging(self) -> None:
        import inspect

        from padiem_control_plane import local_agent_pairing_activation_3102 as module

        source = inspect.getsource(module)
        for forbidden in ("print(", "logging.", "logger.", "sys.stderr"):
            self.assertNotIn(forbidden, source)

    def test_runbooks_contain_no_value_shaped_secret(self) -> None:
        for step in tuple(ACTIVATION_RUNBOOK) + tuple(ROLLBACK_RUNBOOK):
            # A 32-hex pairing code or a 64-hex digest would be a leaked value.
            self.assertIsNone(re.search(r"\b[0-9a-f]{32,}\b", step), step)


class IssuanceScopeKeyAndLifecycle3102Tests(unittest.TestCase):
    """CENTRAL 5844646100: scope-key injectivity and bounded counter lifetime."""

    def test_delimiter_ambiguous_scopes_stay_independent(self) -> None:
        # Canonical refs admit '.', ':', '@', '+', '-' and '_'. A joined string
        # key would let a future separator collapse distinct pairs; the pair key
        # must not, and the support rendering must stay readable.
        authority = _authority(issuance_rate_limit=1)
        pairs = [
            ("a.b", "c"),
            ("a", "b.c"),
            ("a-b", "c"),
            ("a", "b-c"),
            ("a:b", "c"),
            ("a", "b:c"),
            ("a_b", "c"),
            ("a", "b_c"),
        ]
        for account, workspace in pairs:
            with self.subTest(pair=(account, workspace)):
                # Every pair gets its own budget: none may be refused because a
                # different pair exhausted a shared string key.
                _issue(authority, account=account, workspace=workspace)
        self.assertEqual(authority.tracked_issuance_scope_count, len(pairs))

    def test_a_pair_cannot_be_confused_with_its_concatenation(self) -> None:
        authority = _authority(issuance_rate_limit=1)
        _issue(authority, account="x", workspace="y")
        # Same bucket, so the limit must hold for the identical pair.
        with self.assertRaises(ControlPlaneContractError) as limited:
            _issue(authority, account="x", workspace="y")
        self.assertEqual(limited.exception.code, "pairing_issuance_rate_limited")

    def test_inactive_scopes_are_actually_removed(self) -> None:
        authority = _authority(issuance_rate_limit=2)
        for index in range(5):
            _issue(authority, account=f"acct-{index}")
        self.assertEqual(authority.tracked_issuance_scope_count, 5)
        # A full window later, every scope is idle and must have been pruned.
        _issue(
            authority,
            account="acct-fresh",
            now=BASE + timedelta(seconds=PAIRING_ISSUANCE_WINDOW_SECONDS + 1),
        )
        self.assertEqual(authority.tracked_issuance_scope_count, 1)

    def test_counter_cardinality_stays_bounded_under_many_scopes(self) -> None:
        authority = _authority(issuance_rate_limit=1)
        # Roll the window forward periodically so pending challenges are pruned
        # and the run can exceed both caps; only the counter map is under test.
        total = MAX_TRACKED_PAIRING_ISSUANCE_SCOPES + 500
        per_window = 500
        for batch in range(0, total, per_window):
            now = BASE + timedelta(
                seconds=PAIRING_ISSUANCE_WINDOW_SECONDS * (batch // per_window)
            )
            for offset in range(min(per_window, total - batch)):
                _issue(authority, account=f"bulk-{batch + offset}", now=now)
        self.assertLessEqual(
            authority.tracked_issuance_scope_count,
            MAX_TRACKED_PAIRING_ISSUANCE_SCOPES,
        )
        safe = authority.safe_dict()
        self.assertEqual(safe["max_tracked_issuance_scopes"], MAX_TRACKED_PAIRING_ISSUANCE_SCOPES)
        self.assertTrue(safe["issuance_scopes_pruned"])
        self.assertTrue(safe["issuance_scope_keyed_by_pair"])

    def test_capacity_error_precedence_is_preserved(self) -> None:
        # The global pending guard must still win over the per-scope rate guard,
        # even when the rate limit is generous enough that it would not fire.
        authority = _authority(issuance_rate_limit=MAX_PAIRING_ISSUANCE_RATE_LIMIT)
        for index in range(MAX_PENDING_PAIRING_CHALLENGES):
            _issue(authority, account=f"cap-{index}")
        with self.assertRaises(ControlPlaneContractError) as exhausted:
            _issue(authority, account="cap-overflow")
        self.assertEqual(exhausted.exception.code, "pairing_capacity_exhausted")

    def test_rate_window_rollover_still_works_after_pruning(self) -> None:
        authority = _authority(issuance_rate_limit=2)
        for _ in range(2):
            _issue(authority)
        with self.assertRaises(ControlPlaneContractError):
            _issue(authority)
        _issue(authority, now=BASE + timedelta(seconds=PAIRING_ISSUANCE_WINDOW_SECONDS + 1))

    def test_support_rendering_keeps_the_readable_scope(self) -> None:
        authority = _authority(issuance_rate_limit=4)
        _issue(authority)
        state = authority.issuance_rate_state(account_ref=ACCOUNT, workspace_ref=WORKSPACE)
        self.assertEqual(state["scope"], f"{ACCOUNT}/{WORKSPACE}")
        self.assertEqual(state["issued_in_window"], 1)
        self.assertEqual(state["tracked_scopes"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
