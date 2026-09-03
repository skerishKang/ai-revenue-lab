from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority

from kagent.contracts import ContractError
from kagent.control_plane_broker_conformance import (
    CONTROL_PLANE_RUNTIME_DEPENDENCY_IN_B54,
    CONTROL_PLANE_TO_B54_ADMISSION_CONFORMANCE,
    CONTROL_PLANE_TO_B54_COMMAND_CONFORMANCE,
    EVIDENCE_REF_PRESERVED,
    EXPECTED_CREDENTIAL_GENERATION_EXACT,
    NETWORK_CONFIGURED,
    NUMERIC_COERCION,
    PRODUCTION_READY,
    UNKNOWN_WIRE_FIELDS_FAIL_CLOSED,
    parse_control_plane_broker_admission,
    parse_control_plane_broker_command,
)


BASE = datetime(2026, 9, 3, 13, 45, tzinfo=timezone.utc)
CREDENTIAL = b"deterministic-device-credential-for-conformance"
FINGERPRINT = "a" * 64


def _authority_fixture():
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
        ttl_seconds=300,
    )
    return authority, binding, session, command


class ControlPlaneBrokerCommandConformanceTests(unittest.TestCase):
    def test_real_control_plane_queued_projection_maps_to_b54_command(self) -> None:
        authority, binding, session, command = _authority_fixture()
        polled = authority.poll(
            session_id=session.session_id,
            binding_ref=binding.binding_ref,
            credential=CREDENTIAL,
            after_sequence=0,
            now=BASE + timedelta(seconds=20),
        )
        self.assertEqual(polled, (command,))

        conformed = parse_control_plane_broker_command(
            polled[0].safe_dict(),
            expected_binding_ref=binding.binding_ref,
            expected_credential_generation=binding.credential_generation,
            now=BASE + timedelta(seconds=20),
        )
        self.assertEqual(conformed.envelope.command_id, command.command_id)
        self.assertEqual(conformed.envelope.run_id, command.run_id)
        self.assertEqual(conformed.envelope.tool_request_ref, command.tool_request_ref)
        self.assertEqual(conformed.envelope.sequence, command.sequence)
        self.assertEqual(conformed.request_fingerprint, FINGERPRINT)
        self.assertEqual(conformed.credential_generation, binding.credential_generation)
        safe = conformed.safe_dict()
        self.assertFalse(safe["raw_argv"])
        self.assertFalse(safe["raw_file_content"])
        self.assertFalse(safe["raw_device_credential"])
        self.assertFalse(safe["control_plane_runtime_dependency"])

    def test_command_schema_unknown_or_missing_fields_fail_closed(self) -> None:
        _, binding, _, command = _authority_fixture()
        payload = command.safe_dict()
        payload["unexpected_authority"] = True
        with self.assertRaisesRegex(ContractError, "schema mismatch"):
            parse_control_plane_broker_command(
                payload,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=binding.credential_generation,
                now=BASE + timedelta(seconds=20),
            )

        payload = command.safe_dict()
        del payload["request_fingerprint"]
        with self.assertRaisesRegex(ContractError, "schema mismatch"):
            parse_control_plane_broker_command(
                payload,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=binding.credential_generation,
                now=BASE + timedelta(seconds=20),
            )

    def test_generation_binding_and_numeric_types_are_exact(self) -> None:
        _, binding, _, command = _authority_fixture()
        payload = command.safe_dict()
        with self.assertRaisesRegex(ContractError, "credential_generation mismatch"):
            parse_control_plane_broker_command(
                payload,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=2,
                now=BASE + timedelta(seconds=20),
            )

        payload = command.safe_dict()
        payload["credential_generation"] = True
        with self.assertRaisesRegex(ContractError, "without coercion"):
            parse_control_plane_broker_command(
                payload,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=1,
                now=BASE + timedelta(seconds=20),
            )

        payload = command.safe_dict()
        payload["sequence"] = "1"
        with self.assertRaisesRegex(ContractError, "without coercion"):
            parse_control_plane_broker_command(
                payload,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=1,
                now=BASE + timedelta(seconds=20),
            )

    def test_command_must_be_queued_clean_and_current(self) -> None:
        _, binding, _, command = _authority_fixture()
        payload = command.safe_dict()
        payload["state"] = "admitted"
        with self.assertRaisesRegex(ContractError, "must be queued"):
            parse_control_plane_broker_command(
                payload,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=1,
                now=BASE + timedelta(seconds=20),
            )

        payload = command.safe_dict()
        payload["raw_argv"] = True
        with self.assertRaisesRegex(ContractError, "must remain false"):
            parse_control_plane_broker_command(
                payload,
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=1,
                now=BASE + timedelta(seconds=20),
            )

        with self.assertRaisesRegex(ContractError, "not currently valid"):
            parse_control_plane_broker_command(
                command.safe_dict(),
                expected_binding_ref=binding.binding_ref,
                expected_credential_generation=1,
                now=command.expires_at,
            )


class ControlPlaneBrokerAdmissionConformanceTests(unittest.TestCase):
    def _admitted(self):
        authority, binding, session, command = _authority_fixture()
        conformed_command = parse_control_plane_broker_command(
            command.safe_dict(),
            expected_binding_ref=binding.binding_ref,
            expected_credential_generation=binding.credential_generation,
            now=BASE + timedelta(seconds=20),
        )
        admission = authority.admit_command(
            admission_ref="broker_admission_1",
            evidence_ref="broker_evidence_1",
            session_id=session.session_id,
            binding_ref=binding.binding_ref,
            credential=CREDENTIAL,
            command_id=command.command_id,
            request_fingerprint=FINGERPRINT,
            now=BASE + timedelta(seconds=30),
        )
        return binding, session, conformed_command, admission

    def test_real_control_plane_admission_preserves_ack_evidence_ref(self) -> None:
        _, session, command, admission = self._admitted()
        conformed = parse_control_plane_broker_admission(
            admission.to_public_dict(),
            command=command,
            expected_authority_ref="local_agent_broker_authority",
            expected_session_id=session.session_id,
            now=BASE + timedelta(seconds=30),
        )
        self.assertEqual(conformed.evidence_ref, "broker_evidence_1")
        self.assertEqual(conformed.evidence.command_id, command.envelope.command_id)
        self.assertEqual(conformed.evidence.request_fingerprint, command.request_fingerprint)
        self.assertEqual(conformed.evidence.sequence, command.envelope.sequence)
        self.assertEqual(conformed.evidence.session_id, session.session_id)
        safe = conformed.safe_dict()
        self.assertEqual(safe["evidence_ref"], "broker_evidence_1")
        self.assertFalse(safe["raw_argv"])
        self.assertFalse(safe["raw_device_credential"])

    def test_admission_schema_and_authority_are_closed(self) -> None:
        _, session, command, admission = self._admitted()
        payload = admission.to_public_dict()
        payload["raw_file_content"] = False
        with self.assertRaisesRegex(ContractError, "schema mismatch"):
            parse_control_plane_broker_admission(
                payload,
                command=command,
                expected_authority_ref="local_agent_broker_authority",
                expected_session_id=session.session_id,
                now=BASE + timedelta(seconds=30),
            )

        with self.assertRaisesRegex(ContractError, "authority_ref mismatch"):
            parse_control_plane_broker_admission(
                admission.to_public_dict(),
                command=command,
                expected_authority_ref="different_authority",
                expected_session_id=session.session_id,
                now=BASE + timedelta(seconds=30),
            )

    def test_admission_exact_correlations_and_no_numeric_coercion(self) -> None:
        _, session, command, admission = self._admitted()
        payload = admission.to_public_dict()
        payload["request_fingerprint"] = "b" * 64
        with self.assertRaisesRegex(ContractError, "request_fingerprint mismatch"):
            parse_control_plane_broker_admission(
                payload,
                command=command,
                expected_authority_ref="local_agent_broker_authority",
                expected_session_id=session.session_id,
                now=BASE + timedelta(seconds=30),
            )

        payload = admission.to_public_dict()
        payload["sequence"] = True
        with self.assertRaisesRegex(ContractError, "without coercion"):
            parse_control_plane_broker_admission(
                payload,
                command=command,
                expected_authority_ref="local_agent_broker_authority",
                expected_session_id=session.session_id,
                now=BASE + timedelta(seconds=30),
            )

    def test_admission_cannot_widen_command_lifetime(self) -> None:
        _, session, command, admission = self._admitted()
        payload = admission.to_public_dict()
        payload["expires_at"] = (command.envelope.expires_at + timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(ContractError, "cannot outlive"):
            parse_control_plane_broker_admission(
                payload,
                command=command,
                expected_authority_ref="local_agent_broker_authority",
                expected_session_id=session.session_id,
                now=BASE + timedelta(seconds=30),
            )


class BrokerConformanceStatusTests(unittest.TestCase):
    def test_repository_only_status_is_explicit(self) -> None:
        self.assertTrue(CONTROL_PLANE_TO_B54_COMMAND_CONFORMANCE)
        self.assertTrue(CONTROL_PLANE_TO_B54_ADMISSION_CONFORMANCE)
        self.assertTrue(EVIDENCE_REF_PRESERVED)
        self.assertTrue(EXPECTED_CREDENTIAL_GENERATION_EXACT)
        self.assertTrue(UNKNOWN_WIRE_FIELDS_FAIL_CLOSED)
        self.assertFalse(NUMERIC_COERCION)
        self.assertFalse(CONTROL_PLANE_RUNTIME_DEPENDENCY_IN_B54)
        self.assertFalse(NETWORK_CONFIGURED)
        self.assertFalse(PRODUCTION_READY)


if __name__ == "__main__":
    unittest.main()
