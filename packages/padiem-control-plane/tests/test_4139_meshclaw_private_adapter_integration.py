"""#4139 trial: the live MeshCentral read becomes the canonical Claw TXT result.

This integration pins the *whole seam that is testable without a deployment*:
the trial's real private read (official ``meshctrl.js download`` through
Cloudflare Workers VPC -> COM1 QUIC tunnel -> Oracle MeshCentral; live evidence:
113 bytes, SHA-256 ``a8c2ead9ce5bb71a8e2625a482dd16be0196ef92df2af4e83156db45622b473c``)
is carried by the REAL kagent producer into the REAL canonical Broker store and
the REAL Claw consumer, which appends it to the originating conversation
exactly once.

    REAL_BROKER_STORE=YES · REAL_CLAW_CONSUMER=YES · REAL_KAGENT_PRODUCER=YES
    LIVE_READ_BYTES=YES (fixture pinned to the live SHA-256) · DEPLOYMENT=NO

The one fake is the completed meshctrl process itself (the live run is the
evidence for that boundary); the file bytes that cross every other boundary are
the exact bytes the live agent read returned.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[3]
CHAT_APP = REPO / "apps" / "padiem-chat"
KAGENT_SRC = REPO / "apps" / "korean-ai-code-agent" / "src"
for _path in (CHAT_APP, KAGENT_SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from test_local_agent_broker_text_results_4139 import (  # noqa: E402  (test-suite fixture)
    COMMAND_ID,
    CREDENTIAL,
    REQUEST_FINGERPRINT,
    RUN_ID,
    ordered_fixture,
    rpc,
)
from test_local_agent_broker_device_http import _envelope  # noqa: E402  (test-suite fixture)
from test_local_agent_broker_text_result_race_4139 import (  # noqa: E402  (test-suite fixture)
    DURABLE_REASON,
    RealBrokerResultPort,
    ack,
    bound_history,
    poll,
)
from local_agent_broker_text_results import TEXT_RESULT_DEVICE_ROUTE  # noqa: E402

from kagent.local_agent_meshcentral_private_reader import (  # noqa: E402
    MeshCentralVerifiedTextReader,
)
from kagent.local_agent_secure_transport import (  # noqa: E402
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)
from kagent.local_agent_verified_text_result import (  # noqa: E402
    LocalAgentTextResultPublisher,
    VerifiedTextResultRefused,
)

#: The exact bytes the live trial read returned from the COM1 test file.
LIVE_TRIAL_TEXT = (
    "PADIEM MESHCENTRAL SINGLE-PC TXT TEST\n"
    "DATE=2026-10-16\n"
    "HOST=COM1\n"
    "TEST_CASE=mesh-agent-read-and-return\n"
    "END_OF_FILE\n"
)
LIVE_TRIAL_SHA = "a8c2ead9ce5bb71a8e2625a482dd16be0196ef92df2af4e83156db45622b473c"

NODE_REF = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = r"C:\Users\limone\AppData\Local\PADIEM\MeshCentralTrial\meshcentral-padiem-trial.txt"


def config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker.text.4139", url="https://broker.example.test/",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
    )


class BrokerServiceTransport:
    """The kagent pinned transport, over the real canonical device HTTP surface.

    The live production path enters the same handler through the private VPC
    tunnel (the ``WORKER_ORACLE_ROUTE=PASS`` smoke); here the exact same
    envelope is handed to the same real handler in-process. Nothing about the
    wire changes; only the hop that is not deployable yet is short-circuited.
    """

    def __init__(self, service) -> None:
        self._service = service
        self.calls: list[dict] = []

    def post(self, *, config, operation, payload, timeout_seconds):
        self.calls.append(dict(payload))
        answer = self._service.handle(
            _envelope(json.dumps(payload).encode("utf-8"),
                      route=TEXT_RESULT_DEVICE_ROUTE)
        )
        assert answer["status"] == 200, answer
        return answer["body"]


class FakeMeshCentralPort:
    """Stand-in for the already-proven meshctrl process boundary."""

    def __init__(self, payload: bytes = LIVE_TRIAL_TEXT.encode("utf-8")) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):
        self.calls.append({
            "node_ref": node_ref, "file_path": file_path,
            "timeout_seconds": timeout_seconds,
        })
        return self.payload


def build_reader(built, *, port=None):
    port = port if port is not None else FakeMeshCentralPort()
    transport = BrokerServiceTransport(built.service)
    reader = MeshCentralVerifiedTextReader(
        publisher=LocalAgentTextResultPublisher(
            transport=transport, config=config(),
        ),
        port=port,
    )
    return reader, transport, port


def test_the_live_fixture_is_the_proven_agent_read_bytes():
    raw = LIVE_TRIAL_TEXT.encode("utf-8")
    assert len(raw) == 113
    assert __import__("hashlib").sha256(raw).hexdigest() == LIVE_TRIAL_SHA


def test_live_meshcentral_bytes_reach_the_original_conversation_exactly_once():
    built = ordered_fixture(ack=False)
    reader, transport, port = build_reader(built)

    # 1. The declaration is readable BEFORE the ACK: Claw can answer "this
    #    command is a text read, the body is still coming" for the stable id.
    stored_pending, result = reader.execute_verified_read(
        binding_ref=built.binding_ref, credential=CREDENTIAL,
        command_id=COMMAND_ID, run_id=RUN_ID,
        request_fingerprint=REQUEST_FINGERPRINT,
        node_ref=NODE_REF, file_path=FILE_PATH,
    )
    assert stored_pending["state"] == "pending"
    assert rpc(built.store) == {
        "ok": True, "available": False, "kind": "file_read_text",
    }

    # 2. The real private read happened, and the preserved bytes are the live
    #    bytes (no truncation, no re-encoding).
    assert result.content_bytes == 113
    assert result.content_sha256 == LIVE_TRIAL_SHA
    assert result.content_utf8 == LIVE_TRIAL_TEXT

    # 3. Only after the successful ACK does the preserved body go up.
    ack(built)
    stored = reader.deliver(
        binding_ref=built.binding_ref, credential=CREDENTIAL, result=result,
    )
    assert stored["state"] == "content"
    assert stored["content_present"] is True

    # 4. The canonical Broker receipt answers exactly the merged consumer's
    #    shape, with the correlation served from the persisted command.
    receipt = rpc(built.store)
    assert receipt["ok"] is True and receipt["available"] is True
    assert receipt["kind"] == "file_read_text"
    assert receipt["account_ref"] == built.account_ref
    assert receipt["workspace_ref"] == built.workspace_ref
    assert receipt["run_id"] == RUN_ID and receipt["command_id"] == COMMAND_ID
    assert receipt["tool_request_ref"] == "tool.text.4139"
    assert receipt["request_id"] == "request.text.4139"
    assert receipt["request_fingerprint"] == REQUEST_FINGERPRINT
    assert receipt["content_utf8"] == LIVE_TRIAL_TEXT
    assert receipt["content_sha256"] == LIVE_TRIAL_SHA

    # 5. The REAL Claw consumer appends the live bytes to the originating
    #    conversation, exactly once, under the stable message id.
    broker_port = RealBrokerResultPort(built)
    history = bound_history(broker_port)
    first = poll(history, broker_port)
    assert first.append is True and first.status == "completed"
    assert LIVE_TRIAL_TEXT in first.content
    assert "PC 파일 읽기 결과:" in first.content
    assert len(history.messages) == 1

    # 6. Re-query, exact replay and a second poll add no second message.
    late = poll(history, broker_port)
    assert late.append is False and late.reason == DURABLE_REASON
    duplicate = reader.replay(
        binding_ref=built.binding_ref, credential=CREDENTIAL, result=result,
    )
    assert duplicate["reused"] is True
    last = poll(history, broker_port)
    assert last.append is False
    assert history.appends == 1
    assert len(port.calls) == 1, "one live read produced the one delivered body"
    states = [call["state"] for call in transport.calls]
    assert states == ["pending", "content", "content"], states
    assert transport.calls[2] == transport.calls[1], "replay is the identical body"


def test_a_poisoned_private_read_never_fabricates_a_conversation_body():
    built = ordered_fixture(ack=False)
    reader, transport, port = build_reader(
        built, port=FakeMeshCentralPort(b"corrupted\x00read"),
    )
    with pytest.raises(VerifiedTextResultRefused):
        reader.execute_verified_read(
            binding_ref=built.binding_ref, credential=CREDENTIAL,
            command_id=COMMAND_ID, run_id=RUN_ID,
            request_fingerprint=REQUEST_FINGERPRINT,
            node_ref=NODE_REF, file_path=FILE_PATH,
        )
    ack(built)
    broker_port = RealBrokerResultPort(built)
    history = bound_history(broker_port)
    outcome = poll(history, broker_port)
    assert outcome.append is False and outcome.status == "pending"
    assert history.messages == {}
    assert rpc(built.store) == {
        "ok": True, "available": False, "kind": "file_read_text",
    }
    assert [call["state"] for call in transport.calls] == ["pending"]
