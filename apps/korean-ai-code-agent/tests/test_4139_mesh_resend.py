"""#4139 result retransmission — transient vs permanent, restart persistence.

A held outcome is resent byte-for-byte after a transient refusal, quarantined
with its cause after a permanent one, and restored from disk after a restart
without ever re-executing the PC command. No live Broker, MeshCentral or
channel is involved: the transport is injected.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from kagent.local_agent_oracle_mesh_executor import (
    MAX_RESULT_REJECTIONS, OracleMeshDispatch, OracleMeshExecutor,
    OracleMeshExecutionOutcome,
)

SECRET = "deployment-channel-secret-value-261017"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\ProgramData\\Padiem\\report.txt"


class _StubPort:
    def __init__(self) -> None:
        self.calls = 0

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):  # noqa: D102
        del node_ref, file_path, timeout_seconds
        self.calls += 1
        return b"Padiem-Command-Center\r\n"


class _StubCommandPort:
    def __init__(self, output: bytes = b"Padiem-Command-Center\r\n") -> None:
        self.calls = 0
        self._output = output

    def run_command(self, *, node_ref, command, timeout_seconds):  # noqa: D102
        del node_ref, command, timeout_seconds
        self.calls += 1
        return SimpleNamespace(
            termination="exited", exit_code=0, output=self._output,
        )


def _dispatch(**overrides) -> OracleMeshDispatch:
    fields = dict(
        dispatch_id="dsp-1", nonce="n" * 32, node_ref=NODE,
        file_path=FILE_PATH, command_id="cmd-1", run_id="run-1",
    )
    fields.update(overrides)
    return OracleMeshDispatch(**fields)


def _outcome(body: bytes = b"abc") -> OracleMeshExecutionOutcome:
    return OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=body)


class ResendSemanticsTests(unittest.TestCase):
    def _executor(self, transport, **kwargs) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
            **kwargs,
        )

    def test_transient_503_resends_the_same_bytes_with_backoff(self):
        seen = []

        def transport(path, payload):
            seen.append(dict(payload))
            return 503, {"ok": False, "error": {"code": "oracle_mesh_dispatch_unavailable"}}

        executor = self._executor(transport)
        body = "결과 본문\r\n".encode("utf-8")
        first = executor.submit(_dispatch(), _outcome(body))
        self.assertFalse(first.get("ok"))
        self.assertTrue(first.get("retryable"))
        self.assertEqual(first.get("wait_seconds"), 5)
        second = executor.resend_pending_result()
        self.assertTrue(second.get("retryable"))
        self.assertEqual(second.get("wait_seconds"), 10)
        self.assertEqual(seen[0]["content_sha256"], seen[1]["content_sha256"])
        self.assertEqual(seen[0]["content_bytes"], seen[1]["content_bytes"])
        self.assertEqual(seen[1]["content_bytes"], len(body))

    def test_backoff_grows_then_caps(self):
        def transport(path, payload):
            return 503, {"ok": False}

        executor = self._executor(transport)
        waits = [executor.submit(_dispatch(), _outcome())["wait_seconds"]]
        for _ in range(5):
            waits.append(executor.resend_pending_result()["wait_seconds"])
        self.assertEqual(waits, [5, 10, 20, 40, 60, 60])

    def test_rate_limit_and_server_errors_are_transient(self):
        for status in (429, 500, 502):
            def transport(path, payload, status=status):
                return status, {"ok": False}

            executor = self._executor(transport)
            result = executor.submit(_dispatch(), _outcome())
            self.assertTrue(result.get("retryable"), status)
            self.assertTrue(executor.resend_pending)
            self.assertIn("wait_seconds", result)

    def test_transport_refusal_is_transient(self):
        from kagent.local_agent_oracle_mesh_executor import OracleMeshChannelRefused

        def transport(path, payload):
            raise OracleMeshChannelRefused("down")

        executor = self._executor(transport)
        result = executor.submit(_dispatch(), _outcome())
        self.assertTrue(result.get("retryable"))
        self.assertTrue(executor.resend_pending)
        self.assertEqual(result.get("wait_seconds"), 5)

    def test_forbidden_is_quarantined_immediately(self):
        def transport(path, payload):
            return 403, {"ok": False, "error": {"code": "oracle_mesh_conversation_forbidden"}}

        executor = self._executor(transport)
        result = executor.submit(_dispatch(), _outcome())
        self.assertTrue(result.get("dropped"))
        self.assertTrue(result.get("quarantined"))
        self.assertFalse(result.get("retryable"))
        self.assertFalse(executor.resend_pending)

    def test_bad_request_is_quarantined_immediately(self):
        def transport(path, payload):
            return 400, {"ok": False, "error": {"code": "oracle_mesh_invalid_body"}}

        executor = self._executor(transport)
        result = executor.submit(_dispatch(), _outcome())
        self.assertTrue(result.get("quarantined"))
        self.assertFalse(executor.resend_pending)

    def test_ambiguous_rejection_is_bounded_then_quarantined(self):
        attempts = []

        def transport(path, payload):
            attempts.append(path)
            return 409, {"ok": False, "error": {"code": "oracle_mesh_dispatch_rejected"}}

        executor = self._executor(transport)
        executor.submit(_dispatch(), _outcome())
        final = None
        for _ in range(MAX_RESULT_REJECTIONS + 1):
            if not executor.resend_pending:
                break
            final = executor.resend_pending_result()
        self.assertTrue(final.get("dropped"))
        self.assertTrue(final.get("quarantined"))
        self.assertEqual(len(attempts), MAX_RESULT_REJECTIONS)

    def test_non_utf8_body_is_quarantined_without_a_post(self):
        calls = []

        def transport(path, payload):
            calls.append(path)
            return 200, {"ok": True}

        executor = self._executor(transport)
        result = executor.submit(_dispatch(), _outcome(b"\xff\xfe invalid"))
        self.assertTrue(result.get("quarantined"))
        self.assertEqual(calls, [])

    def test_resend_never_touches_either_port(self):
        read_port = _StubPort()
        command_port = _StubCommandPort()

        def transport(path, payload):
            return 503, {"ok": False}

        executor = OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=read_port,
            command_port=command_port,
            transport=transport,
        )
        dispatch = _dispatch(kind="command", command_text="hostname.exe")
        outcome = executor.execute(dispatch)
        self.assertEqual(command_port.calls, 1)
        executor.submit(dispatch, outcome)
        executor.resend_pending_result()
        executor.resend_pending_result()
        self.assertEqual(command_port.calls, 1)
        self.assertEqual(read_port.calls, 0)


class RestartPersistenceTests(unittest.TestCase):
    def _executor(self, transport, workdir, **kwargs) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
            pending_dir=str(workdir),
            **kwargs,
        )

    def test_held_result_survives_a_restart_and_resends(self):
        import tempfile

        work = Path(tempfile.mkdtemp(prefix="oracle_pending_4139_"))
        body = "재시작 후 재전송\r\n".encode("utf-8")

        def failing(path, payload):
            return 503, {"ok": False}

        first = self._executor(failing, work)
        first.submit(_dispatch(), _outcome(body))
        manifest = json.loads((work / "pending-result.json").read_text(encoding="utf-8"))
        # The body file is named after its own digest, so writing a new result
        # can never truncate the body an existing manifest points at.
        held_body = work / manifest["body_name"]
        self.assertTrue(held_body.exists())
        self.assertEqual(manifest["content_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(held_body.read_bytes(), body)

        delivered = []

        def succeeding(path, payload):
            delivered.append(dict(payload))
            return 200, {"ok": True, "status": "completed"}

        # A fresh process: nothing is executed, the held bytes are delivered.
        second = self._executor(succeeding, work)
        self.assertTrue(second.load_pending())
        self.assertTrue(second.resend_pending)
        result = second.resend_pending_result()
        self.assertTrue(result.get("ok"))
        self.assertEqual(delivered[0]["content_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(delivered[0]["content_bytes"], len(body))
        self.assertFalse((work / "pending-result.json").exists())
        self.assertFalse(held_body.exists())

    def test_legacy_fixed_name_pending_is_still_recovered(self):
        """A result held by the previous executor revision is not orphaned."""
        import tempfile

        work = Path(tempfile.mkdtemp(prefix="oracle_pending_legacy_4139_"))
        body = "구 버전이 보관한 결과\r\n".encode("utf-8")
        (work / "pending-result.json").write_text(
            json.dumps({
                "dispatch_id": "dsp-1", "nonce": "n" * 32, "node_ref": NODE,
                "file_path": FILE_PATH, "command_id": "cmd-1", "run_id": "run-1",
                "kind": "read", "command_text": None,
                "termination": "exited", "exit_code": 0,
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "content_bytes": len(body),
            }),
            encoding="utf-8",
        )
        (work / "pending-result.body").write_bytes(body)

        delivered = []

        def succeeding(path, payload):
            delivered.append(dict(payload))
            return 200, {"ok": True}

        executor = self._executor(succeeding, work)
        self.assertTrue(executor.load_pending())
        self.assertTrue(executor.resend_pending_result().get("ok"))
        self.assertEqual(delivered[0]["content_bytes"], len(body))

    def test_plain_resend_rewrites_nothing(self):
        """An identical resend must not expose the good copy to a new write."""
        import tempfile
        import time

        work = Path(tempfile.mkdtemp(prefix="oracle_pending_noop_4139_"))
        body = "동일 재전송\r\n".encode("utf-8")

        def failing(path, payload):
            return 503, {"ok": False}

        executor = self._executor(failing, work)
        executor.submit(_dispatch(), _outcome(body))
        manifest_path = work / "pending-result.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        held_body = work / manifest["body_name"]
        before = (
            manifest_path.stat().st_mtime_ns,
            held_body.stat().st_mtime_ns,
        )

        time.sleep(0.01)
        executor.resend_pending_result()
        executor.resend_pending_result()
        after = (
            manifest_path.stat().st_mtime_ns,
            held_body.stat().st_mtime_ns,
        )
        self.assertEqual(after, before, "a plain resend rewrote the held result")
        self.assertEqual(list(work.glob(".tmp-*")), [], "a temp file was left behind")

    def test_quarantine_preserves_bytes_and_cause_on_disk(self):
        import tempfile

        work = Path(tempfile.mkdtemp(prefix="oracle_quarantine_4139_"))
        body = "영구 거부된 결과".encode("utf-8")

        def refusing(path, payload):
            return 409, {"ok": False,
                          "error": {"code": "oracle_mesh_result_fingerprint_mismatch"}}

        executor = self._executor(refusing, work)
        result = executor.submit(_dispatch(), _outcome(body))
        self.assertTrue(result.get("quarantined"))
        quarantine = Path(result["quarantine_path"])
        self.assertEqual(quarantine.parent, work)
        self.assertTrue(quarantine.exists())
        record = json.loads(quarantine.read_text(encoding="utf-8"))
        self.assertEqual(record["reason"], "result_fingerprint_mismatch")
        self.assertEqual(record["content_sha256"], hashlib.sha256(body).hexdigest())
        body_path = quarantine.with_suffix(".body")
        self.assertTrue(body_path.exists())
        self.assertEqual(body_path.read_bytes(), body)
        self.assertFalse((work / "pending-result.json").exists())

    def test_corrupt_pending_file_is_set_aside_never_executed(self):
        import tempfile

        work = Path(tempfile.mkdtemp(prefix="oracle_corrupt_4139_"))
        (work / "pending-result.json").write_text("{not json", encoding="utf-8")
        (work / "pending-result.body").write_bytes(b"whatever")

        def transport(path, payload):
            raise AssertionError("no post must happen for a corrupt hold")

        executor = self._executor(transport, work)
        self.assertFalse(executor.load_pending())
        self.assertFalse(executor.resend_pending)

    def test_unsafe_dispatch_id_cannot_escape_the_pending_dir(self):
        import tempfile

        work = Path(tempfile.mkdtemp(prefix="oracle_escape_4139_"))

        def refusing(path, payload):
            return 403, {"ok": False}

        executor = self._executor(refusing, work)
        result = executor.submit(
            _dispatch(dispatch_id="../../escape-attempt"), _outcome())
        self.assertTrue(result.get("quarantined"))
        quarantine = Path(result["quarantine_path"])
        self.assertEqual(quarantine.parent, work)
        self.assertNotIn("..", quarantine.name)


if __name__ == "__main__":
    unittest.main()
