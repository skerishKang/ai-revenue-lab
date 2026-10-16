"""#4139 trial: the MeshCentral private-read executor stays on the canonical lane.

The live proof behind this fixture: the official ``meshctrl.js download``
returned exactly 113 bytes through the private path (Claw Worker -> Workers VPC
Service -> COM1 QUIC tunnel -> 127.0.0.1 ssh -L -> Oracle MeshCentral), and the
agent-computed SHA-256 of the same file was
``a8c2ead9ce5bb71a8e2625a482dd16be0196ef92df2af4e83156db45622b473c``.
These tests pin that the executor half performs declare-pending -> one real
read -> preserved canonical body, never truncates, never re-reads on replay,
and never reports a refused broker answer as stored content.

    REAL_MESHCTRL=NO (recording fakes) · ORDER_AND_WIRE_PINNED=YES
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kagent.local_agent_control_plane_https import ControlPlaneHttpsOperation  # noqa: E402
from kagent.local_agent_meshcentral_private_reader import (  # noqa: E402
    OFFICIAL_MESHCTRL_CLIENT,
    PASSWORD_IN_MODULE_STATE,
    PUBLIC_INBOUND_PORT,
    SECOND_PC_PROTOCOL,
    SECOND_TXT_UPLOAD_PATH,
    TRUNCATION_AS_COMPLETENESS,
    MeshCentralCliFileReadPort,
    MeshCentralReadRefused,
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

BINDING_REF = "bind_mesh_1"
CREDENTIAL = b"synthetic-canonical-credential-v1"
COMMAND_ID = "cmd_mesh_1"
RUN_ID = "run_mesh_1"
REQUEST_FINGERPRINT = "c" * 64
NODE_REF = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = r"C:\Users\limone\AppData\Local\PADIEM\MeshCentralTrial\meshcentral-padiem-trial.txt"

_PENDING_WIRE_KEYS = frozenset({
    "binding_ref", "credential_b64", "contract_version", "command_id",
    "run_id", "request_fingerprint", "state",
})
_CONTENT_WIRE_KEYS = _PENDING_WIRE_KEYS | frozenset({
    "content_utf8", "content_sha256", "content_bytes",
})


def config() -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker.text.4139", url="https://broker.example.test/",
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
    )


class RecordingTransport:
    """The pinned transport, reduced to the canonical receipt shape."""

    def __init__(self, *, refuse_first: bool = False) -> None:
        self.calls: list[dict] = []
        self.refuse_first = refuse_first

    def post(self, *, config, operation, payload, timeout_seconds):
        self.calls.append({
            "operation": operation, "payload": dict(payload),
            "timeout_seconds": timeout_seconds,
        })
        if self.refuse_first and len(self.calls) == 1:
            return {"ok": False, "error": {"code": "denied"}}
        state = payload["state"]
        return {"ok": True, "text_result": {
            "stored": True, "reused": False, "state": state,
            "content_present": state == "content",
        }}


class FakeMeshPort:
    def __init__(self, payload: bytes = LIVE_TRIAL_TEXT.encode("utf-8")) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):
        self.calls.append({
            "node_ref": node_ref, "file_path": file_path,
            "timeout_seconds": timeout_seconds,
        })
        return self.payload


class ReaderFixture:
    def __init__(self, *, port=None, transport=None) -> None:
        self.transport = transport if transport is not None else RecordingTransport()
        self.port = port if port is not None else FakeMeshPort()
        self.reader = MeshCentralVerifiedTextReader(
            publisher=LocalAgentTextResultPublisher(
                transport=self.transport, config=config(),
            ),
            port=self.port,
        )

    def run(self):
        stored, result = self.reader.execute_verified_read(
            binding_ref=BINDING_REF, credential=CREDENTIAL,
            command_id=COMMAND_ID, run_id=RUN_ID,
            request_fingerprint=REQUEST_FINGERPRINT,
            node_ref=NODE_REF, file_path=FILE_PATH,
        )
        delivered = self.reader.deliver(
            binding_ref=BINDING_REF, credential=CREDENTIAL, result=result,
        )
        return stored, result, delivered


class MeshCentralPrivateReaderTests(unittest.TestCase):
    def test_the_live_trial_fixture_is_the_proven_agent_read(self):
        raw = LIVE_TRIAL_TEXT.encode("utf-8")
        self.assertEqual(len(raw), 113)
        self.assertEqual(sha256(raw).hexdigest(), LIVE_TRIAL_SHA)
        self.assertTrue(raw.startswith(b"PADIEM MESHCENTRAL"))

    def test_live_bytes_flow_in_the_canonical_order(self):
        fixture = ReaderFixture()
        stored, result, delivered = fixture.run()
        self.assertEqual(stored["state"], "pending")
        self.assertEqual(
            [call["payload"]["state"] for call in fixture.transport.calls],
            ["pending", "content"],
        )
        self.assertTrue(all(
            call["operation"] == ControlPlaneHttpsOperation.TEXT_RESULT
            for call in fixture.transport.calls
        ))
        self.assertEqual(frozenset(fixture.transport.calls[0]["payload"]),
                         _PENDING_WIRE_KEYS)
        self.assertEqual(frozenset(fixture.transport.calls[1]["payload"]),
                         _CONTENT_WIRE_KEYS)
        content = fixture.transport.calls[1]["payload"]
        self.assertEqual(content["content_utf8"], LIVE_TRIAL_TEXT)
        self.assertEqual(content["content_sha256"], LIVE_TRIAL_SHA)
        self.assertEqual(content["content_bytes"], 113)
        self.assertEqual(result.content_sha256, LIVE_TRIAL_SHA)
        self.assertTrue(delivered["stored"])
        self.assertTrue(delivered["content_present"])
        # The one real read happened exactly once, against the asserted node and
        # file, after the declaration.
        self.assertEqual(len(fixture.port.calls), 1)
        self.assertEqual(fixture.port.calls[0]["node_ref"], NODE_REF)
        self.assertEqual(fixture.port.calls[0]["file_path"], FILE_PATH)

    def test_oversize_read_is_refused_and_never_delivered(self):
        fixture = ReaderFixture(port=FakeMeshPort(("가" * 300).encode("utf-8")))
        with self.assertRaises(VerifiedTextResultRefused):
            fixture.run()
        self.assertEqual(
            [call["payload"]["state"] for call in fixture.transport.calls],
            ["pending"], "a refused read must not stage a body",
        )

    def test_control_bytes_are_refused_and_never_delivered(self):
        fixture = ReaderFixture(port=FakeMeshPort(b"bad\x00data"))
        with self.assertRaises(VerifiedTextResultRefused):
            fixture.run()
        self.assertEqual(
            [call["payload"]["state"] for call in fixture.transport.calls],
            ["pending"],
        )

    def test_empty_read_is_refused_not_reported_as_a_bodyless_success(self):
        fixture = ReaderFixture(port=FakeMeshPort(b""))
        with self.assertRaises(MeshCentralReadRefused):
            fixture.run()
        self.assertEqual(
            [call["payload"]["state"] for call in fixture.transport.calls],
            ["pending"],
        )

    def test_replay_re_sends_the_identical_bytes_without_a_second_read(self):
        fixture = ReaderFixture()
        _, result, _ = fixture.run()
        first_content = fixture.transport.calls[1]["payload"]
        replayed = fixture.reader.replay(
            binding_ref=BINDING_REF, credential=CREDENTIAL, result=result,
        )
        self.assertTrue(replayed["stored"])
        self.assertEqual(fixture.transport.calls[2]["payload"], first_content)
        self.assertEqual(len(fixture.port.calls), 1, "replay must not re-read")

    def test_a_refused_declaration_aborts_before_any_read(self):
        fixture = ReaderFixture(transport=RecordingTransport(refuse_first=True))
        with self.assertRaises(VerifiedTextResultRefused):
            fixture.run()
        self.assertEqual(fixture.port.calls, [],
                         "no file may be read when the intent was refused")

    def test_foreign_refs_and_paths_are_refused_before_the_read(self):
        fixture = ReaderFixture()
        with self.assertRaises(MeshCentralReadRefused):
            fixture.reader.read_verified_result(
                command_id=COMMAND_ID, run_id=RUN_ID,
                request_fingerprint=REQUEST_FINGERPRINT,
                node_ref="bad node!", file_path=FILE_PATH,
            )
        with self.assertRaises(MeshCentralReadRefused):
            fixture.reader.read_verified_result(
                command_id=COMMAND_ID, run_id=RUN_ID,
                request_fingerprint=REQUEST_FINGERPRINT,
                node_ref=NODE_REF, file_path="bad\x00path.txt",
            )
        self.assertEqual(fixture.port.calls, [])

    def test_contract_constants(self):
        self.assertTrue(OFFICIAL_MESHCTRL_CLIENT)
        self.assertFalse(SECOND_PC_PROTOCOL)
        self.assertFalse(SECOND_TXT_UPLOAD_PATH)
        self.assertFalse(PUBLIC_INBOUND_PORT)
        self.assertFalse(TRUNCATION_AS_COMPLETENESS)
        self.assertFalse(PASSWORD_IN_MODULE_STATE)


class MeshCentralCliPortTests(unittest.TestCase):
    """The real port: injected runner, staged temp file, bounded refusal."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="padiem_mesh_read_4139_")
        self.staged: bytes | None = None
        self.returncode = 0
        self.argv_seen: list[str] = []
        self.input_seen: str | None = None

        def runner(argv, *, timeout, input):
            self.argv_seen = list(argv)
            self.input_seen = input
            target = argv[argv.index("--target") + 1]
            if self.returncode == 0 and self.staged is not None:
                with open(target, "wb") as handle:
                    handle.write(self.staged)
            return SimpleNamespace(returncode=self.returncode)

        self.port = MeshCentralCliFileReadPort(
            command_runner=runner,
            meshctrl_js=r"C:\meshcentral-test\node_modules\meshcentral\meshctrl.js",
            login_user="padiemadmin",
            password_provider=lambda: "s3cret-at-call-time",
            url="wss://127.0.0.1:4443",
            work_dir=self.temp.name,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_download_uses_the_official_client_and_stages_cleanly(self):
        self.staged = LIVE_TRIAL_TEXT.encode("utf-8")
        raw = self.port.read_bytes(
            node_ref=NODE_REF, file_path=FILE_PATH, timeout_seconds=45,
        )
        self.assertEqual(raw, LIVE_TRIAL_TEXT.encode("utf-8"))
        self.assertEqual(sha256(raw).hexdigest(), LIVE_TRIAL_SHA)
        self.assertIn("download", self.argv_seen)
        self.assertEqual(self.argv_seen[1], "-e")
        self.assertNotIn("s3cret-at-call-time", self.argv_seen)
        self.assertEqual(self.input_seen, "s3cret-at-call-time\n")
        self.assertEqual(self.argv_seen[self.argv_seen.index("--loginpass") + 1],
                         "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__")
        self.assertEqual(self.argv_seen[self.argv_seen.index("--id") + 1], NODE_REF)
        self.assertEqual(self.argv_seen[self.argv_seen.index("--file") + 1], FILE_PATH)
        self.assertEqual(self.argv_seen[self.argv_seen.index("--url") + 1],
                         "wss://127.0.0.1:4443")
        target = self.argv_seen[self.argv_seen.index("--target") + 1]
        self.assertFalse(os.path.exists(target), "the staged read must be removed")
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_a_nonzero_client_exit_is_refused_without_staging(self):
        self.returncode = 1
        with self.assertRaises(MeshCentralReadRefused):
            self.port.read_bytes(
                node_ref=NODE_REF, file_path=FILE_PATH, timeout_seconds=45,
            )
        self.assertEqual(os.listdir(self.temp.name), [])

    def test_an_oversize_staged_read_is_refused_never_truncated(self):
        self.staged = b"x" * 769
        with self.assertRaises(MeshCentralReadRefused):
            self.port.read_bytes(
                node_ref=NODE_REF, file_path=FILE_PATH, timeout_seconds=45,
            )
        self.assertEqual(os.listdir(self.temp.name), [])


if __name__ == "__main__":
    unittest.main()
