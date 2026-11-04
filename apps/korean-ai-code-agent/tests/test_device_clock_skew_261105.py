"""261105: 장치가 서버 시각을 검증할 때 기기 시계 허용 오차를 둔다(#6875 시계 점검 후속).

브로커 승인의 accepted_at과 서버 하트비트의 last_seen_at은 Control Plane이
자기 시계로 찍은 값이고, 이를 장치 시계와 비교한다. 기기 시계가 느리면 서버
시각이 미래로 보이므로 기기 허용(300초) 안의 앞섬은 받아들이고, 그 밖은
거절하며, 명령·세션 수명 검사는 그대로임을 확인한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority

from kagent.contracts import ContractError
from kagent.control_plane_broker_conformance import (
    parse_control_plane_broker_admission,
    parse_control_plane_broker_command,
)
from kagent.local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession
from kagent.local_agent_server_projection import project_server_backed_online_binding

BASE = datetime(2026, 11, 5, 5, 30, tzinfo=timezone.utc)
CREDENTIAL = b"deterministic-device-credential-for-conformance"
FINGERPRINT = "a" * 64
# 기기 허용(300초)을 넘는 앞섬도 명령·승인 창 안에서 시험하기 위한 넉넉한 TTL.
COMMAND_TTL_SECONDS = 900
NOW = BASE


def _admission_fixture(accepted_at: datetime):
    authority = InMemoryLocalAgentBrokerAuthority(
        pepper=b"deterministic-control-plane-broker-pepper",
        authority_ref="local_agent_broker_authority",
    )
    binding = authority.register_binding(
        binding_ref="device_binding_1",
        device_id="device_win_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        credential=CREDENTIAL,
        now=BASE,
    )
    session = authority.open_session(
        session_id="device_session_1",
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        account_ref=binding.account_ref,
        workspace_ref=binding.workspace_ref,
        now=BASE + timedelta(seconds=5),
    )
    command = authority.enqueue_command(
        command_id="device_command_1",
        binding_ref=binding.binding_ref,
        run_id="run_exec_1",
        tool_request_ref="tool_request_exec_1",
        request_fingerprint=FINGERPRINT,
        now=BASE + timedelta(seconds=10),
        ttl_seconds=COMMAND_TTL_SECONDS,
    )
    conformed_command = parse_control_plane_broker_command(
        command.safe_dict(),
        expected_binding_ref=binding.binding_ref,
        expected_credential_generation=binding.credential_generation,
        now=accepted_at,
    )
    admission = authority.admit_command(
        admission_ref="broker_admission_1",
        evidence_ref="broker_evidence_1",
        session_id=session.session_id,
        binding_ref=binding.binding_ref,
        credential=CREDENTIAL,
        command_id=command.command_id,
        request_fingerprint=FINGERPRINT,
        request_id="request.conformance.1",
        now=accepted_at,
    )
    return binding, session, conformed_command, admission


class DeviceClockSkewConformanceTests(unittest.TestCase):
    def test_admission_within_device_skew_is_tolerated(self):
        accepted_at = BASE + timedelta(seconds=30)
        _, session, command, admission = _admission_fixture(accepted_at)
        conformed = parse_control_plane_broker_admission(
            admission.to_public_dict(),
            command=command,
            expected_authority_ref="local_agent_broker_authority",
            expected_session_id=session.session_id,
            expected_request_id="request.conformance.1",
            now=accepted_at - timedelta(seconds=2),  # 장치 시계가 2초 느리다
        )
        self.assertEqual(conformed.evidence_ref, "broker_evidence_1")

    def test_admission_beyond_device_skew_is_refused(self):
        accepted_at = BASE + timedelta(seconds=400)
        _, session, command, admission = _admission_fixture(accepted_at)
        with self.assertRaisesRegex(ContractError, "cannot be from the future"):
            parse_control_plane_broker_admission(
                admission.to_public_dict(),
                command=command,
                expected_authority_ref="local_agent_broker_authority",
                expected_session_id=session.session_id,
                expected_request_id="request.conformance.1",
                now=accepted_at - timedelta(seconds=301),
            )


def _projection(last_seen_at: datetime):
    current = DeviceSession(
        session_id="session.1",
        device_id="device.1",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.1",
        workspace_ref="workspace.1",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=15),
    )
    heartbeat = ControlPlaneHeartbeatReceipt(
        session_id=current.session_id,
        binding_ref=current.binding_ref,
        device_id=current.device_id,
        account_ref=current.account_ref,
        workspace_ref=current.workspace_ref,
        credential_generation=1,
        last_seen_at=last_seen_at,
        session_expires_at=current.expires_at,
    )
    binding = DeviceBinding(
        device_id="device.1",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential_ref="pairing-credential." + "a" * 32,
        credential_generation=1,
        issued_at=NOW - timedelta(minutes=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=DeviceLifecycle.PAIRED_OFFLINE,
    )
    return project_server_backed_online_binding(
        binding=binding,
        session=current,
        heartbeat=heartbeat,
        now=NOW,
    )


class DeviceClockSkewProjectionTests(unittest.TestCase):
    def test_heartbeat_within_device_skew_is_tolerated(self):
        online = _projection(NOW + timedelta(seconds=60))
        self.assertEqual(online.state, DeviceLifecycle.ONLINE)

    def test_heartbeat_beyond_device_skew_is_refused(self):
        with self.assertRaisesRegex(ContractError, "cannot be in the future"):
            _projection(NOW + timedelta(seconds=301))
