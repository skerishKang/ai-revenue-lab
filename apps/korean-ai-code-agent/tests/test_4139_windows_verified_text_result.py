"""#4139: the real Windows TXT READ, in the ordered pending → read → ACK → body.

The genuine ``WindowsSelectedRootFileRuntime`` reads a real file on disk through
the real ``P01LocalPermissionWindowsFileAuthorizationPort`` grant, and the real
resident host drives the canonical coordinator. Only the pinned transport is a
recording fake, so both the exact wire and the order are visible:

    pending (ADMITTED, unacknowledged) → approved READ (bytes preserved)
      → successful ACK confirmed → those preserved bytes uploaded

    REAL_PC_FILE_READ=YES (local file, real P01 grant) · REAL_BROKER=NO
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome, ApprovalPause, ApprovalRequirement,
    VerifiedApprovalDecision, tool_invocation_digest,
)

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_command_admission import AdmittedLocalCommandExecutionReceipt
from kagent.local_agent_control_plane_admission import ControlPlaneAdmittedExecutionReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceCommandEnvelope, DeviceLifecycle
from kagent.local_agent_permissions import (
    LocalPermissionRequest, LocalCapability, default_device_permission_profile,
)
from kagent.local_agent_runtime_host import InMemorySingleInstanceLock
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint, OutboundTransportConfig, OutboundTransportMode,
)
from kagent.local_agent_verified_text_result import (
    MAX_VERIFIED_TEXT_RESULT_BYTES, LocalAgentTextResultPublisher,
    VerifiedTextResultRefused,
)
from kagent.local_resident_verified_text_delivery import (
    AdmittedTextReadContext, ResidentVerifiedTextPublisher,
    TrustedP01VerifiedTextFilePlan, TrustedP01VerifiedTextFilePlanBridge,
    WindowsVerifiedTextProducer,
)
from kagent.windows_local_executor import WindowsExecutionTermination
from kagent.windows_local_filesystem import (
    LocalFileOperation, LocalFileRequest, P01LocalPermissionWindowsFileAuthorizationPort,
    WindowsFileAuthorityEvidence, WindowsSelectedRootFileRuntime, file_request_fingerprint,
    windows_file_tool_invocation,
)
from test_local_agent_runtime_host import _harness

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
#: A real multi-byte UTF-8 body: the bytes on the wire must be these bytes.
TEXT = "P01 TXT 검증: 배송 완료\n"
CREDENTIAL = b"synthetic-canonical-credential-v1"
FINGERPRINT = "a" * 64
TEXT_PATH = r"notes\report.txt"

BINDING = DeviceBinding(
    device_id="dev_host_1", binding_ref="bind_host_1", account_ref="acc_host_1",
    workspace_ref="ws_host_1", credential_ref="cred_host_1", credential_generation=1,
    issued_at=NOW - timedelta(hours=1), credential_expires_at=NOW + timedelta(hours=1),
    state=DeviceLifecycle.ONLINE,
)
COMMAND = DeviceCommandEnvelope(
    command_id="cmd_host_1", run_id="run_host_1", tool_request_ref="tool_req_host_1",
    binding_ref="bind_host_1", sequence=1, issued_at=NOW,
    expires_at=NOW + timedelta(minutes=5), revision_ref="revision_host_1",
)


def receipt(*, exit_code=0, termination=WindowsExecutionTermination.EXITED, binding_ref=None,
            fingerprint=FINGERPRINT, request_id="req_host_1", acknowledged_at=None):
    execution = AdmittedLocalCommandExecutionReceipt(
        admission_ref="admission_host_1", command_id="cmd_host_1",
        tool_request_ref="tool_req_host_1", sequence=1, session_id="session_host_1",
        binding_ref=binding_ref or BINDING.binding_ref, request_id=request_id,
        run_id="run_host_1", request_fingerprint=fingerprint,
        assembly_ref="assembly_host_1", authorization_ref="authorization_host_1",
        termination=termination, revision_ref="revision_host_1", exit_code=exit_code,
    )
    return ControlPlaneAdmittedExecutionReceipt(
        execution=execution, evidence_ref="evidence_host_1",
        acknowledged_at=acknowledged_at or (NOW + timedelta(seconds=5)),
    )


def admitted_context(*, request_id="req_host_1", fingerprint=FINGERPRINT, at=NOW):
    """The admitted (unacknowledged) correlation the resident hook carries."""
    return AdmittedTextReadContext(
        admission_ref="admission_host_1", evidence_ref="evidence_host_1",
        request_id=request_id, command_fingerprint=fingerprint, admitted_at=at,
    )


class SyntheticTextP01Authority:
    """PRE-EXISTING P01 text evidence fixture; the lane cannot mint approval."""

    def __init__(self, *, omit=False, wrong_command=False, path=TEXT_PATH, capability=None,
                 expires_before_admission=False, wrong_request=False,
                 wrong_fingerprint=False):
        self.omit = omit
        self.wrong_command = wrong_command
        self.path = path
        self.capability = capability
        self.expires_before_admission = expires_before_admission
        self.wrong_request = wrong_request
        self.wrong_fingerprint = wrong_fingerprint
        self.calls = 0

    def approved_plan_for_admitted_command(self, *, binding, command, admitted):
        self.calls += 1
        if self.omit:
            return None
        now = admitted.admitted_at
        request = LocalFileRequest(
            action_id="p01_approved_read_report_4139", run_id=command.run_id,
            device_id=binding.device_id, root_ref="root_repo",
            operation=LocalFileOperation.READ, path_relative=self.path,
            requested_at=now - timedelta(seconds=30),
        )
        fingerprint = file_request_fingerprint(request)
        invocation = windows_file_tool_invocation(request)
        pause = ApprovalPause(
            pause_id="pause_p01_text_4139", run_id=request.run_id,
            agent_runtime_id="agent_p01_text_4139", tool_id=invocation.tool_id,
            invocation_sha256=tool_invocation_digest(invocation),
            requirement=ApprovalRequirement.USER_CONFIRMATION, step_index=1,
            created_at=now - timedelta(minutes=2), expires_at=now + timedelta(minutes=5),
            approval_scope=((self.capability or request.capability).value,),
        )
        decision = VerifiedApprovalDecision(
            decision_id="decision_p01_text_4139", pause_id=pause.pause_id,
            outcome=ApprovalOutcome.APPROVED, authority_ref="trusted_p01_text_4139",
            evidence_ref="evidence_p01_text_4139", decided_at=now - timedelta(seconds=25),
        )
        evidence = WindowsFileAuthorityEvidence(
            evidence_ref="text_file_evidence_4139", request_fingerprint=fingerprint,
            permission_request=LocalPermissionRequest(
                action_id="text_permission_4139", run_id=request.run_id,
                device_id=request.device_id, capability=request.capability,
                target_ref=fingerprint, root_ref=request.root_ref,
            ),
            approval_pause=pause, approval_decision=decision,
            local_policy_ref="default_selected_root_policy_4139",
            expires_at=(now - timedelta(minutes=6) if self.expires_before_admission
                        else now + timedelta(minutes=4)),
        )
        return TrustedP01VerifiedTextFilePlan(
            binding_ref=binding.binding_ref,
            command_id="other_command" if self.wrong_command else command.command_id,
            tool_request_ref=command.tool_request_ref, run_id=request.run_id,
            request_id="req_other" if self.wrong_request else admitted.request_id,
            revision_ref=command.revision_ref,
            command_fingerprint=("d" * 64 if self.wrong_fingerprint
                                 else admitted.command_fingerprint),
            sequence=command.sequence, file_request=request, file_evidence=evidence,
        )


class RecordingTextPort:
    """Records the exact device-route wire and the broker state at each call."""

    def __init__(self, *, broker=None, refuse_content=False, fail_content=False,
                 refuse_pending=False, probe=None):
        self.broker = broker
        self.refuse_content = refuse_content
        self.fail_content = fail_content
        self.refuse_pending = refuse_pending
        #: Called with the local state at the moment each frame is sent, so the
        #: order (declared before the read, uploaded after the ACK) is pinned
        #: from the inside rather than inferred afterwards.
        self.probe = probe
        self.calls: list[dict] = []
        self.trace: list[str] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        assert config.endpoint.url.startswith("https://")
        assert operation.value == "text-result"
        assert 1 <= timeout_seconds <= 60
        state = payload["state"]
        if self.broker is not None:
            command = self.broker._commands["cmd_host_1"]
            self.trace.append(f"{state}:{command.state.value}")
        if self.probe is not None:
            self.trace.append(self.probe(state))
        self.calls.append(dict(payload))
        if state == "pending":
            if self.refuse_pending:
                return {"ok": False, "error": {"code": "text_result_not_admitted"}}
            return {"ok": True, "text_result": {
                "stored": True, "reused": False, "state": "pending",
                "content_present": False,
            }}
        if self.fail_content:
            raise ContractError("pinned text transport failed")
        if self.refuse_content:
            return {"ok": False, "error": {"code": "text_result_refused"}}
        return {"ok": True, "text_result": {
            "stored": True, "reused": False, "state": "content", "content_present": True,
        }}


class CountingFileRuntime(WindowsSelectedRootFileRuntime):
    """Real selected-root reads, counted (subclass, never a replacement)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.reads = 0

    def perform(self, request, *, now):
        result = super().perform(request, now=now)
        self.reads += 1
        return result


class TextLane:
    """The real P01-authorized read lane plus a recording pinned transport."""

    def __init__(self, root, *, authority=None, port=None, clock=None):
        self.device = LocalAgentDeviceProfile(
            device_id="dev_host_1", workspace_ref="ws_host_1",
            platform=LocalAgentPlatform.WINDOWS,
            roots=(LocalRoot(root_ref="root_repo", windows_path=str(root)),),
        )
        self.authority = authority or SyntheticTextP01Authority()
        self.bridge = TrustedP01VerifiedTextFilePlanBridge(source=self.authority)
        self.files = CountingFileRuntime(
            device=self.device,
            authorization_port=P01LocalPermissionWindowsFileAuthorizationPort(
                permission_profile=default_device_permission_profile(device=self.device),
                evidence_port=self.bridge,
            ),
        )
        self.config = OutboundTransportConfig(
            endpoint=OutboundBrokerEndpoint(
                endpoint_ref="broker.text.4139", url="https://broker.example.test/",
                mode=OutboundTransportMode.HTTPS_LONG_POLL,
            ),
        )
        self.port = port if port is not None else RecordingTextPort()
        self.clock = clock or (lambda: NOW)
        self.producer = WindowsVerifiedTextProducer(
            files=self.files, requests=self.bridge, clock=self.clock,
        )
        self.publisher = ResidentVerifiedTextPublisher(
            approved_text=self.producer,
            publisher=LocalAgentTextResultPublisher(
                transport=self.port, config=self.config,
            ),
        )

    def declare(self, *, binding=BINDING, command=COMMAND, admitted=None,
                credential=CREDENTIAL):
        return self.publisher.declare_pending_for_admitted(
            binding=binding, command=command,
            admitted=admitted_context() if admitted is None else admitted,
            credential=credential,
        )

    def read(self, *, receipt_value=None, binding=BINDING, command=COMMAND):
        value = receipt_value or receipt()
        return self.publisher.observe_approved_read(
            binding=binding, command=command, execution=value.execution,
        )

    def deliver(self, *, receipt_value=None, command=COMMAND, binding=BINDING):
        return self.publisher.on_acknowledged(
            binding=binding, command=command,
            receipt=receipt_value or receipt(), credential=CREDENTIAL,
        )

    def run(self, *, receipt_value=None):
        assert self.declare() is True
        self.read(receipt_value=receipt_value)
        return self.deliver(receipt_value=receipt_value)

    @property
    def states(self) -> list[str]:
        return [call["state"] for call in self.port.calls]


class VerifiedTextResultTests(unittest.TestCase):
    def setUp(self):
        InMemorySingleInstanceLock.reset()
        self.temp = tempfile.TemporaryDirectory(prefix="padiem_verified_text_4139_")
        self.root = Path(self.temp.name)
        (self.root / "notes").mkdir(parents=True)
        self.write_file(TEXT.encode("utf-8"))

    def tearDown(self):
        self.temp.cleanup()
        InMemorySingleInstanceLock.reset()

    def write_file(self, content: bytes, name: str = "report.txt"):
        (self.root / "notes" / name).write_bytes(content)

    def lane(self, **kwargs) -> TextLane:
        return TextLane(self.root, **kwargs)

    # -- the ordered contract: pending, then the file, then the ACK ----------
    def test_pending_is_declared_before_the_read_and_the_body_only_after_the_ack(self):
        lane = self.lane()
        assert lane.declare() is True
        # Declared, and nothing has been read yet: the declaration precedes the
        # approved READ, so a refused declaration cannot be followed by a read.
        self.assertEqual(lane.states, ["pending"])
        self.assertEqual(lane.files.reads, 0)

        assert lane.read() is not None
        # The real read happened, and no body has travelled yet.
        self.assertEqual(lane.files.reads, 1)
        self.assertEqual(lane.states, ["pending"])

        delivery = lane.deliver()
        assert delivery is not None
        self.assertEqual(lane.states, ["pending", "content"])
        # The bytes uploaded are the bytes that read produced: never re-read.
        self.assertEqual(lane.files.reads, 1)
        pending, content = lane.port.calls
        self.assertEqual(set(pending), {
            "binding_ref", "credential_b64", "contract_version", "command_id",
            "run_id", "request_fingerprint", "state",
        })
        self.assertEqual(pending["contract_version"], "claw-local-agent-text-result.v1")
        self.assertEqual(pending["command_id"], "cmd_host_1")
        self.assertEqual(pending["run_id"], "run_host_1")
        self.assertEqual(pending["request_fingerprint"], FINGERPRINT)
        self.assertEqual(pending["state"], "pending")
        self.assertEqual(set(content) - {"binding_ref", "credential_b64"}, {
            "contract_version", "command_id", "run_id", "request_fingerprint", "state",
            "content_utf8", "content_sha256", "content_bytes",
        })
        self.assertEqual(content["content_utf8"], TEXT)
        self.assertEqual(content["content_sha256"], sha256(TEXT.encode("utf-8")).hexdigest())
        self.assertEqual(content["content_bytes"], len(TEXT.encode("utf-8")))
        # The device never asserts its own owner/scope: the broker reads them
        # back from the canonical command.
        self.assertNotIn("account_ref", content)
        self.assertNotIn("workspace_ref", content)
        safe = delivery.safe_dict()
        self.assertTrue(safe["pending_before_ack"] and safe["read_before_ack"])
        self.assertTrue(safe["content_uploaded"] and safe["pending_before_body"])
        self.assertFalse(safe["file_reread_after_ack"])
        self.assertTrue(safe["returned_to_claw"])
        self.assertNotIn(TEXT, str(safe))

    def test_a_refused_declaration_stops_before_the_read_and_before_any_body(self):
        lane = self.lane(port=RecordingTextPort(refuse_pending=True))
        with self.assertRaises(VerifiedTextResultRefused):
            lane.declare()
        self.assertEqual(lane.states, ["pending"])
        self.assertEqual(lane.files.reads, 0)
        # Nothing was staged, so the completion path has no body to send.
        self.assertIsNone(lane.deliver())

    def test_the_body_is_the_file_and_not_the_command_stdout_or_a_prefill(self):
        second = "different customer file: 주문 2\n"
        self.write_file(second.encode("utf-8"))
        lane = self.lane()
        lane.run()
        content = lane.port.calls[1]
        self.assertEqual(content["content_utf8"], second)
        self.assertEqual(content["content_bytes"], len(second.encode("utf-8")))
        # Nothing from the executed command's own terminal output is trusted.
        self.assertNotIn("python", content["content_utf8"])
        self.assertEqual(lane.files.reads, 1)

    # -- bounded, never truncated -------------------------------------------
    def test_exactly_768_utf8_bytes_is_returned_and_769_is_refused(self):
        at_bound = "x" * MAX_VERIFIED_TEXT_RESULT_BYTES
        self.write_file(at_bound.encode("utf-8"))
        lane = self.lane()
        lane.run()
        self.assertEqual(lane.port.calls[1]["content_bytes"], MAX_VERIFIED_TEXT_RESULT_BYTES)
        self.assertEqual(lane.port.calls[1]["content_utf8"], at_bound)

        self.write_file(("x" * (MAX_VERIFIED_TEXT_RESULT_BYTES + 1)).encode("utf-8"))
        over = self.lane()
        assert over.declare() is True
        with self.assertRaises(ContractError):
            over.read()
        # Oversized is refused outright: no truncation, and the read is never
        # turned into an acknowledged body.
        self.assertEqual(over.states, ["pending"])
        self.assertEqual(over.files.reads, 1)
        self.assertIsNone(over.deliver())
        # A read that can never become a body releases its slot: repeated
        # refusals cannot wedge the bounded declaration map.
        self.assertEqual(over.publisher.safe_dict()["declared_pending_count"], 0)

    def test_non_utf8_file_is_refused_and_never_transcoded(self):
        self.write_file(b"\xff\xfe\x00binary not text")
        lane = self.lane()
        assert lane.declare() is True
        with self.assertRaises(ContractError):
            lane.read()
        self.assertEqual(lane.states, ["pending"])
        self.assertIsNone(lane.deliver())

    # -- scope: only an approved txt read of this command --------------------
    def test_non_text_command_declares_and_uploads_nothing(self):
        lane = self.lane(authority=SyntheticTextP01Authority(omit=True))
        self.assertIs(lane.declare(), False)
        self.assertIsNone(lane.read())
        self.assertIsNone(lane.deliver())
        self.assertEqual(lane.port.calls, [])
        self.assertEqual(lane.files.reads, 0)

    def test_foreign_command_or_non_text_path_is_refused(self):
        lane = self.lane(authority=SyntheticTextP01Authority(wrong_command=True))
        with self.assertRaises(ContractError):
            lane.declare()
        self.assertEqual(lane.port.calls, [])

        workbook = self.lane(authority=SyntheticTextP01Authority(path=r"reports\quote.xlsx"))
        with self.assertRaises(ContractError):
            workbook.declare()
        self.assertEqual(workbook.port.calls, [])

    def test_revoked_local_read_permission_refuses_before_any_upload(self):
        lane = self.lane(
            authority=SyntheticTextP01Authority(capability=LocalCapability.FILESYSTEM_WRITE),
        )
        assert lane.declare() is True
        with self.assertRaises(ContractError):
            lane.read()
        self.assertEqual(lane.states, ["pending"])

    def test_expired_p01_approval_never_reaches_the_read(self):
        lane = self.lane(
            authority=SyntheticTextP01Authority(expires_before_admission=True),
        )
        with self.assertRaises(ContractError):
            lane.declare()
        self.assertEqual(lane.port.calls, [])
        self.assertEqual(lane.files.reads, 0)

    def test_the_admitted_correlation_is_the_broker_command_correlation(self):
        # The context is validated as an exact SHA-256/ref shape: a truncated or
        # non-hexdigest correlation cannot be expressed at all.
        for bad in ("b" * 63, "B" * 64, ""):
            with self.assertRaises(ContractError):
                admitted_context(fingerprint=bad)
        # And a P01 plan that names a different request or a different command
        # fingerprint than the admitted correlation is refused before the read.
        for authority in (
            SyntheticTextP01Authority(wrong_request=True),
            SyntheticTextP01Authority(wrong_fingerprint=True),
        ):
            lane = self.lane(authority=authority)
            with self.assertRaises(ContractError):
                lane.declare()
            self.assertEqual(lane.port.calls, [])
            self.assertEqual(lane.files.reads, 0)

    # -- a failed or missing ACK is never a text result ---------------------
    def test_staged_read_with_a_failed_or_foreign_ack_is_refused(self):
        for value in (receipt(exit_code=1), receipt(binding_ref="bind_other")):
            lane = self.lane()
            assert lane.declare() is True
            lane.read()
            with self.assertRaises(ContractError):
                lane.deliver(receipt_value=value)
            self.assertEqual(lane.states, ["pending"])

    def test_a_failed_execution_is_not_read_and_not_uploaded(self):
        lane = self.lane()
        assert lane.declare() is True
        self.assertIsNone(lane.read(receipt_value=receipt(exit_code=1)))
        self.assertIsNone(lane.read(receipt_value=receipt(
            termination=WindowsExecutionTermination.TIMED_OUT, exit_code=None)))
        self.assertEqual(lane.files.reads, 0)
        self.assertEqual(lane.states, ["pending"])
        self.assertIsNone(lane.deliver())
        self.assertEqual(lane.publisher.safe_dict()["declared_pending_count"], 0)

    def test_an_execution_without_the_admitted_correlation_is_refused(self):
        foreign = receipt()
        foreign = replace(
            foreign,
            execution=replace(foreign.execution, request_fingerprint="c" * 64),
        )
        for value in (receipt(request_id="req_other"), foreign):
            lane = self.lane()
            assert lane.declare() is True
            with self.assertRaises(ContractError):
                lane.read(receipt_value=value)
            self.assertEqual(lane.files.reads, 0)
            self.assertIsNone(lane.deliver())

    def test_broker_refusal_is_never_reported_as_returned(self):
        lane = self.lane(port=RecordingTextPort(refuse_content=True))
        assert lane.declare() is True
        lane.read()
        with self.assertRaises(VerifiedTextResultRefused):
            lane.deliver()
        # The declaration and the body both went out, the body was refused, and
        # no caller received a "the file reached Claw" object.
        self.assertEqual(lane.states, ["pending", "content"])

        failed = self.lane(port=RecordingTextPort(fail_content=True))
        assert failed.declare() is True
        failed.read()
        with self.assertRaises(ContractError):
            failed.deliver()
        self.assertEqual(failed.states, ["pending", "content"])

    def test_exact_replay_reuses_the_same_bytes_without_re_reading(self):
        lane = self.lane()
        delivery = lane.run()
        first = dict(lane.port.calls[1])
        lane.port.calls.clear()
        lane.publisher.replay(
            delivery=delivery, binding_ref=BINDING.binding_ref, credential=CREDENTIAL,
        )
        self.assertEqual(lane.port.calls, [first])
        self.assertEqual(lane.files.reads, 1)  # never re-executed, never re-read

    # -- the real host drives the same order --------------------------------
    def test_resident_host_declares_while_admitted_and_uploads_after_the_ack(self):
        host, _runtime, port, clock = _harness()
        lane = TextLane(
            self.root, port=RecordingTextPort(broker=port.broker_authority),
            # The real host clock: the P01 grant is time-bounded, so the read
            # must happen on the same clock the acknowledgement came from.
            clock=lambda: clock.now,
        )
        lane.port.probe = lambda state: (
            f"probe:{state}:reads={lane.files.reads}"
        )
        # The host deliberately swallows a side-effect failure, so record the
        # lane's own reason here instead of guessing from an empty call list.
        errors: list[str] = []
        upload = lane.publisher.on_acknowledged

        def spy(**kwargs):
            try:
                return upload(**kwargs)
            except Exception as exc:  # pragma: no cover - failure path only
                errors.append(repr(exc))
                raise

        lane.publisher.on_acknowledged = spy
        host._verified_text_lane = lane.publisher
        host.start()
        clock.advance(5)
        self.assertEqual(host.run_once(now=clock.now), 1)
        self.assertEqual(errors, [])
        # The declaration left while the command was still admitted and
        # unacknowledged, and the read had not happened yet; the body left only
        # after the canonical ACK, from bytes already read.
        self.assertEqual(lane.port.trace, [
            "pending:admitted", "probe:pending:reads=0",
            "content:acknowledged", "probe:content:reads=1",
        ])
        self.assertEqual(lane.states, ["pending", "content"])
        self.assertEqual(lane.files.reads, 1)
        self.assertEqual(lane.port.calls[1]["content_utf8"], TEXT)
        # The ACKed command truth is untouched by the text lane.
        command = port.broker_authority._commands["cmd_host_1"]
        self.assertEqual(command.exit_code, 0)
        host.stop()
        host._durable_store.close()

    def test_resident_host_refused_declaration_never_executes_or_acknowledges(self):
        host, _runtime, port, clock = _harness()
        lane = TextLane(
            self.root,
            port=RecordingTextPort(
                broker=port.broker_authority, refuse_pending=True,
            ),
            clock=lambda: clock.now,
        )
        host._verified_text_lane = lane.publisher
        host.start()
        clock.advance(5)
        with self.assertRaises(VerifiedTextResultRefused):
            host.run_once(now=clock.now)
        self.assertEqual(lane.states, ["pending"])
        self.assertEqual(lane.files.reads, 0)
        # No execution and no completion acknowledgement for a read the broker
        # never accepted as pending.
        command = port.broker_authority._commands["cmd_host_1"]
        self.assertEqual(command.state.value, "admitted")
        self.assertIsNone(command.exit_code)
        codes = [event.code for event in host.diagnostics()]
        self.assertIn("PENDING_REFUSED", codes)
        # The refusal rides the resident's existing execution-refusal path: the
        # command is reported as a refusal, never as an executed or text-returning
        # one.
        self.assertEqual(codes[-1], "EXECUTION_ERROR")
        host.stop()
        host._durable_store.close()


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
