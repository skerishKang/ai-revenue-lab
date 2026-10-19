"""#4139 output fidelity at the CLI and disk boundaries.

Two loss mechanisms are covered here that no other lane test can see:

* the official meshctrl client prints a device transcript with ``console.log``
  and calls ``process.exit`` in the same tick, which Node documents as exiting
  "as quickly as possible even if there are still asynchronous operations
  pending" for stdout — the tail of a large reply used to die in the pipe;
* a held result was rewritten with ``O_TRUNC`` on every plain resend, and a
  failed write was ignored, so the only durable copy of an execution the PC
  already ran could be destroyed by the retry that was meant to protect it.

The client-side case runs the real ``node`` interpreter against a fake
meshctrl module (the same shape the executor spawns). The disk cases use real
temporary files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from kagent.local_agent_meshcentral_command_port import (
    MAX_COMMAND_BYTES, parse_transcript,
)
from kagent.local_agent_meshcentral_private_reader import _MESHCTRL_STDIN_BOOTSTRAP
from kagent.local_agent_oracle_mesh_executor import (
    MAX_COMMAND_BYTES as EXECUTOR_ENVELOPE,
    POLL_PATH,
    OracleMeshDispatch, OracleMeshExecutionOutcome, OracleMeshExecutor,
)

SECRET = "deployment-channel-secret-value-261017"
NODE_REF = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
SIZE = 2_200_001
POLL = POLL_PATH


def _dispatch(**overrides) -> OracleMeshDispatch:
    fields = dict(
        dispatch_id="dsp-fidelity", nonce="n" * 32, node_ref=NODE_REF,
        file_path="C:\\temp\\a.txt", command_id="cmd-1", run_id="run-1",
        kind="command", command_text="hostname.exe",
    )
    fields.update(overrides)
    return OracleMeshDispatch(**fields)


def _outcome(body: bytes) -> OracleMeshExecutionOutcome:
    return OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=body)


class StdoutFlushTests(unittest.TestCase):
    """The bootstrap must deliver the whole transcript before the child exits."""

    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which("node")

    def setUp(self):
        if not self.node:
            self.skipTest("node is not installed on this runner")
        self.work = Path(tempfile.mkdtemp(prefix="meshctrl_flush_"))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _fake_client(self, *, keepalive: bool) -> Path:
        fake = self.work / "fake-meshctrl.js"
        fake.write_text(
            "const n = Number(process.argv[2]);\n"
            "const code = Number(process.argv[3]);\n"
            "console.log('a'.repeat(n));\n"
            + ("setInterval(() => {}, 1000);\n" if keepalive else "")
            + "process.exit(code);\n",
            encoding="utf-8",
        )
        return fake

    def _run(self, fake: Path, size: int) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.node, "-e", _MESHCTRL_STDIN_BOOTSTRAP, str(fake), str(size), "7",
             "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__"],
            input=b"operator-password\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )

    def test_whole_transcript_survives_the_clients_own_exit(self):
        fake = self._fake_client(keepalive=True)
        completed = self._run(fake, SIZE)
        self.assertEqual(completed.stdout, b"a" * SIZE + b"\n")
        self.assertEqual(completed.returncode, 7, "the client's own code is kept")

    def test_barrier_exits_promptly_when_nothing_is_pending(self):
        fake = self._fake_client(keepalive=False)
        completed = self._run(fake, 16)
        self.assertEqual(completed.stdout, b"a" * 16 + b"\n")
        self.assertEqual(completed.returncode, 7)

    def test_the_bootstrap_defers_the_exit_instead_of_ending_it_sync(self):
        """OS-independent half of the flush proof.

        Whether a pipe write is still pending when ``process.exit`` runs depends
        on the platform, so this asserts the property the barrier exists for:
        ``process.exit`` returns and the child still finishes with the code the
        client asked for. With the stock client-side exit, nothing after the
        call can run at all, so the marker line is the discriminator.
        """
        probe = self.work / "probe.js"
        probe.write_text(
            "process.exit(5);\n"
            "console.log('AFTER_EXIT');\n",
            encoding="utf-8",
        )
        completed = subprocess.run(
            [self.node, "-e", _MESHCTRL_STDIN_BOOTSTRAP, str(probe),
             "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__"],
            input=b"operator-password\n",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
        )
        self.assertIn(b"AFTER_EXIT", completed.stdout)
        self.assertEqual(completed.returncode, 5, "the deferred exit keeps the code")

    def test_parser_accepts_a_transcript_above_the_old_pipe_cap(self):
        """64 KiB was a truncated pipe, not a transport limit: prove the parse."""
        transcript = ("z" * 40 + "\n") * (SIZE // 41 + 1)
        payload = (transcript + "__PADIEM_EXIT__0\n").encode("utf-8")
        self.assertGreater(len(payload), 65_536)
        termination, code, output = parse_transcript(payload)
        self.assertEqual((termination, code), ("exited", 0))
        self.assertEqual(output.decode("utf-8"), transcript)


class _StubPort:
    def read_bytes(self, *, node_ref, file_path, timeout_seconds):  # noqa: D102
        del node_ref, file_path, timeout_seconds
        return b"never"


class HeldResultAtomicityTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="oracle_hold_"))

    def tearDown(self):
        shutil.rmtree(self.work, ignore_errors=True)

    def _executor(self, transport) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net", channel_secret=SECRET,
            read_port=_StubPort(), transport=transport,
            pending_dir=str(self.work),
        )

    def _manifest(self) -> tuple[dict, Path]:
        meta = json.loads((self.work / "pending-result.json").read_text(encoding="utf-8"))
        return meta, self.work / meta["body_name"]

    def test_a_failed_body_write_leaves_the_previous_copy_intact(self):
        body = "첫 결과\r\n".encode("utf-8")
        executor = self._executor(lambda path, payload: (503, {"ok": False}))
        executor.submit(_dispatch(), _outcome(body))
        meta, body_path = self._manifest()
        good_body = body_path.read_bytes()

        def transport(path, payload):
            return 503, {"ok": False}

        second = self._executor(transport)
        self.assertTrue(second.load_pending())

        def failing_write(directory, name, payload):
            raise OSError(28, "No space left on device")

        second._atomic_write = staticmethod(failing_write)
        result = second.submit(
            _dispatch(dispatch_id="dsp-other", nonce="m" * 32),
            _outcome("두 번째 결과\r\n".encode("utf-8")),
        )
        # The refusal is reported instead of hidden, and the already-held
        # result on disk is untouched by the write that could not land.
        self.assertEqual(result.get("persist_error"), "OSError")
        self.assertEqual(body_path.read_bytes(), good_body)
        self.assertEqual(
            json.loads((self.work / "pending-result.json").read_text(encoding="utf-8")),
            meta,
        )

    def test_recovery_after_a_restart_resends_without_re_execution(self):
        body = ("출력 " + "가" * 90_000 + "\r\n").encode("utf-8")
        executor = self._executor(lambda path, payload: (503, {"ok": False}))
        executor.submit(_dispatch(), _outcome(body))

        posts = []

        def transport(path, payload):
            posts.append((path, dict(payload)))
            return 200, {"ok": True}

        revived = self._executor(transport)
        self.assertTrue(revived.load_pending())
        report = revived.run_once()
        self.assertTrue(report.get("ok"))
        self.assertEqual(posts[0][0], "/api/claw/connector/mesh-reads/result")
        self.assertEqual(posts[0][1]["content_bytes"], len(body))
        self.assertEqual(posts[0][1]["content_sha256"], hashlib.sha256(body).hexdigest())
        self.assertFalse((self.work / "pending-result.json").exists())

    def test_a_crash_between_the_two_writes_keeps_the_previous_result_whole(self):
        """Commit order is the durability guarantee: body first, manifest last.

        If the manifest were committed first, it would name a body that never
        landed, and the result that *was* durable would become unreadable.
        """
        first = "첫 결과\r\n".encode("utf-8")
        holder = self._executor(lambda path, payload: (503, {"ok": False}))
        holder.submit(_dispatch(), _outcome(first))
        manifest = json.loads((self.work / "pending-result.json").read_text(encoding="utf-8"))
        first_body = self.work / manifest["body_name"]

        calls = []

        def crash_on_the_second_write(directory, name, payload):
            calls.append(name)
            if len(calls) == 2:
                raise OSError(5, "the process died between the two writes")
            return OracleMeshExecutor._atomic_write(directory, name, payload)

        survivor = self._executor(lambda path, payload: (503, {"ok": False}))
        survivor._atomic_write = staticmethod(crash_on_the_second_write)
        report = survivor.submit(
            _dispatch(dispatch_id="dsp-second", nonce="m" * 32),
            _outcome("두 번째 결과\r\n".encode("utf-8")),
        )
        self.assertEqual(report.get("persist_error"), "OSError")
        # The pair that was durable before the crash is still consistent.
        self.assertTrue(first_body.exists())
        self.assertEqual(first_body.read_bytes(), first)

        delivered = []

        def succeeding(path, payload):
            delivered.append(dict(payload))
            return 200, {"ok": True}

        revived = self._executor(succeeding)
        self.assertTrue(revived.load_pending(), "the first result must stay recoverable")
        self.assertTrue(revived.resend_pending_result().get("ok"))
        self.assertEqual(delivered[0]["content_sha256"], hashlib.sha256(first).hexdigest())
        self.assertFalse((self.work / "pending-result.json").exists())
        self.assertFalse(first_body.exists(), "an accepted hold is cleaned up")

    def test_a_long_command_survives_the_poll_response_read(self):
        """The poll response carries the command; a 64 KiB read truncated it."""
        command = "Get-Item 'C:\\temp\\a.txt'\n" * 9_000  # ~225 KB
        self.assertGreater(len(command.encode("utf-8")), 65_536)
        encoded = json.dumps({
            "ok": True,
            "dispatch": {
                "dispatch_id": "dsp-fidelity", "nonce": "n" * 32,
                "node_ref": NODE_REF, "file_path": "", "command_id": "cmd-1",
                "run_id": "run-1", "kind": "command", "command_text": command,
            },
        }).encode("utf-8")
        self.assertGreater(len(encoded), 65_536)
        self.assertLess(len(encoded), EXECUTOR_ENVELOPE)

        executor = self._executor(lambda path, payload: (200, {}))
        with _stubbed_opener(encoded) as posts:
            status, data = executor._https_post(POLL, None)
        self.assertEqual(status, 200)
        self.assertEqual(data["dispatch"]["command_text"], command)
        self.assertGreater(posts["read_limit"], 65_536)

    def test_a_response_over_the_envelope_is_refused_not_truncated(self):
        from kagent.local_agent_oracle_mesh_executor import OracleMeshChannelRefused

        executor = self._executor(lambda path, payload: (200, {}))
        huge = b"x" * (MAX_COMMAND_BYTES + 10)
        with _stubbed_opener(huge):
            with self.assertRaises(OracleMeshChannelRefused):
                executor._https_post(POLL, None)

    def test_a_korean_result_is_not_inflated_by_ascii_escaping(self):
        """UTF-8 JSON keeps a Korean body inside the envelope it is judged by.

        Measured: 4.9 MB of Korean content escapes to 9.5 MB of JSON, which the
        server refuses as an over-envelope body, while the same content as
        UTF-8 JSON is 5.3 MB and is delivered.
        """
        from kagent.local_agent_oracle_mesh_executor import RESULT_PATH

        text = "리포트 행\n" * 350_000
        self.assertLess(len(text.encode("utf-8")), MAX_COMMAND_BYTES)
        executor = self._executor(lambda path, payload: (200, {}))
        with _stubbed_opener(b'{"ok":true}') as reads:
            status, _data = executor._https_post(RESULT_PATH, {"content_utf8": text})
        sent = reads["sent"]
        self.assertEqual(status, 200)
        self.assertIn("리포트".encode("utf-8"), sent)
        self.assertLess(len(sent), MAX_COMMAND_BYTES)
        self.assertGreater(
            len(json.dumps({"content_utf8": text}).encode("utf-8")),
            MAX_COMMAND_BYTES,
        )


class _StubResponse:
    def __init__(self, data: bytes, reads: dict):
        self._data = data
        self._reads = reads

    status = 200

    def read(self, maximum):
        self._reads["read_limit"] = maximum
        return self._data[:maximum]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@contextmanager
def _stubbed_opener(payload: bytes):
    """Serve one fixed body through the executor's real HTTPS client path."""
    import urllib.request

    reads: dict = {}

    class _Opener:
        def open(self, request, timeout=None):
            reads["sent"] = request.data
            return _StubResponse(payload, reads)

    with mock.patch.object(
        urllib.request, "build_opener", lambda *a, **k: _Opener()
    ):
        yield reads


if __name__ == "__main__":
    unittest.main()
