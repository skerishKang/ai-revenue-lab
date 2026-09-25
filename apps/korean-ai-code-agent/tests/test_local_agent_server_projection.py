from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path

from kagent.contracts import ContractError
from kagent.local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_server_projection import (
    CANONICAL_DEVICE_TRUTH_OWNED_BY,
    DESKTOP_SHELL_ONLINE_RULE_REUSED,
    LOCAL_ONLINE_CLAIM,
    ONLINE_REQUIRES_SERVER_PROJECTION,
    PAIRED_OFFLINE_IS_PROJECTION_SOURCE,
    RENDERER_OR_LOCAL_SUPERVISION_MAY_FORGE_ONLINE,
    SECOND_DEVICE_LIFECYCLE_AUTHORITY,
    SERVER_PROJECTION_TRIGGER,
    SESSION_AND_HEARTBEAT_REQUIRED,
    online_binding_evidence,
    project_server_backed_online_binding,
)

NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
REPO_ROOT = Path(__file__).resolve().parents[3]


def binding(state: DeviceLifecycle = DeviceLifecycle.PAIRED_OFFLINE) -> DeviceBinding:
    return DeviceBinding(
        device_id="device.1",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential_ref="pairing-credential." + "a" * 32,
        credential_generation=1,
        issued_at=NOW - timedelta(minutes=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=state,
    )


def session(**overrides) -> DeviceSession:
    values = dict(
        session_id="session.1",
        device_id="device.1",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.1",
        workspace_ref="workspace.1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    values.update(overrides)
    return DeviceSession(**values)


def heartbeat(current: DeviceSession | None = None, **overrides) -> ControlPlaneHeartbeatReceipt:
    current = current or session()
    values = dict(
        session_id=current.session_id,
        binding_ref=current.binding_ref,
        device_id=current.device_id,
        account_ref=current.account_ref,
        workspace_ref=current.workspace_ref,
        credential_generation=1,
        last_seen_at=NOW,
        session_expires_at=current.expires_at,
    )
    values.update(overrides)
    return ControlPlaneHeartbeatReceipt(**values)


class ServerBackedOnlineProjectionTests(unittest.TestCase):
    def test_server_session_and_heartbeat_produce_the_online_projection(self):
        current = session()
        online = project_server_backed_online_binding(
            binding=binding(),
            session=current,
            heartbeat=heartbeat(current),
            now=NOW,
        )
        self.assertEqual(online.state, DeviceLifecycle.ONLINE)
        self.assertEqual(online.binding_ref, binding().binding_ref)
        self.assertEqual(online.credential_generation, 1)

        evidence = online_binding_evidence(
            binding=binding(),
            session=current,
            heartbeat=heartbeat(current),
            now=NOW,
        )
        self.assertTrue(evidence["evidence_backed"])
        self.assertEqual(evidence["state"], DeviceLifecycle.ONLINE.value)
        self.assertEqual(evidence["server_projection_trigger"], "server_projection")
        self.assertFalse(evidence["local_online_claim"])
        self.assertFalse(evidence["public_inbound_port"])
        self.assertFalse(evidence["raw_device_credential"])

    def test_missing_session_or_heartbeat_can_never_produce_online(self):
        current = session()
        for case_session, case_heartbeat in ((None, heartbeat()), (current, None), (None, None)):
            with self.subTest(session=case_session, heartbeat=case_heartbeat):
                with self.assertRaises(ContractError):
                    project_server_backed_online_binding(
                        binding=binding(),
                        session=case_session,
                        heartbeat=case_heartbeat,
                        now=NOW,
                    )

    def test_unrelated_or_stale_server_evidence_is_refused(self):
        current = session()
        stale = session(issued_at=NOW - timedelta(minutes=5))
        cases = {
            "session of another device": (session(device_id="device.2"), heartbeat(current), NOW),
            "session of another binding": (
                session(binding_ref="pairing-binding." + "b" * 32),
                heartbeat(current),
                NOW,
            ),
            "heartbeat of another session": (current, heartbeat(current, session_id="session.2"), NOW),
            "heartbeat of another credential generation": (
                current,
                heartbeat(current, credential_generation=2),
                NOW,
            ),
            "heartbeat with a different session expiry": (
                current,
                heartbeat(current, session_expires_at=current.expires_at + timedelta(minutes=1)),
                NOW,
            ),
            "heartbeat acknowledged before the session existed": (
                current,
                heartbeat(current, last_seen_at=current.issued_at - timedelta(seconds=1)),
                NOW,
            ),
            "heartbeat acknowledged in the future": (
                current,
                heartbeat(current, last_seen_at=NOW + timedelta(seconds=1)),
                NOW,
            ),
            "expired session": (current, heartbeat(current), current.expires_at),
            "session issued before the redeemed binding": (stale, heartbeat(stale), NOW),
        }
        for label, (case_session, case_heartbeat, now) in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(ContractError):
                    project_server_backed_online_binding(
                        binding=binding(),
                        session=case_session,
                        heartbeat=case_heartbeat,
                        now=now,
                    )

        # Defence in depth: such a receipt cannot even be constructed, so it can
        # never reach the projection gate either.
        with self.assertRaises(ContractError):
            heartbeat(current, last_seen_at=current.expires_at)

    def test_only_a_redeemed_paired_offline_binding_is_a_projection_source(self):
        current = session()
        for state in (
            DeviceLifecycle.UNPAIRED,
            DeviceLifecycle.ONLINE,
            DeviceLifecycle.REVOKED,
            DeviceLifecycle.CREDENTIAL_EXPIRED,
            DeviceLifecycle.UPDATE_REQUIRED,
        ):
            with self.subTest(state=state.value):
                with self.assertRaises(ContractError):
                    project_server_backed_online_binding(
                        binding=binding(state),
                        session=current,
                        heartbeat=heartbeat(current),
                        now=NOW,
                    )
        with self.assertRaises(ContractError):
            project_server_backed_online_binding(
                binding="not-a-binding",  # type: ignore[arg-type]
                session=current,
                heartbeat=heartbeat(current),
                now=NOW,
            )
        with self.assertRaises(ContractError):
            project_server_backed_online_binding(
                binding=binding(),
                session=current,
                heartbeat={"last_seen_at": NOW},  # type: ignore[arg-type]
                now=NOW,
            )

    def test_truth_constants_and_3083_shell_rule_stay_pinned(self):
        self.assertTrue(ONLINE_REQUIRES_SERVER_PROJECTION)
        self.assertTrue(SESSION_AND_HEARTBEAT_REQUIRED)
        self.assertTrue(PAIRED_OFFLINE_IS_PROJECTION_SOURCE)
        self.assertTrue(DESKTOP_SHELL_ONLINE_RULE_REUSED)
        self.assertEqual(SERVER_PROJECTION_TRIGGER, "server_projection")
        self.assertEqual(CANONICAL_DEVICE_TRUTH_OWNED_BY, "3080")
        self.assertFalse(LOCAL_ONLINE_CLAIM)
        self.assertFalse(RENDERER_OR_LOCAL_SUPERVISION_MAY_FORGE_ONLINE)
        self.assertEqual(SECOND_DEVICE_LIFECYCLE_AUTHORITY, 0)

        shell_contract = REPO_ROOT / "apps" / "padiem-desktop-shell" / "src" / "contract" / "device-lifecycle.ts"
        self.assertTrue(shell_contract.is_file(), "the merged #3083 desktop-shell lifecycle contract must exist")
        source = shell_contract.read_text(encoding="utf-8")
        self.assertIn("ONLINE requires the canonical server_projection", source)
        self.assertIn("'server_projection'", source)
        self.assertIn("CANONICAL_TRUTH_OWNED_BY: '#3080'", source)
        self.assertIn("RENDERER_MAY_FORGE_ONLINE: false", source)


if __name__ == "__main__":
    unittest.main()
