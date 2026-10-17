"""#4139 — the executor factory must run the official client for real.

One focused check goes through ``make_oracle_mesh_executor`` so the actual
factory-built read port is exercised: the operator credential reaches the child
on stdin, the argv carries only the public marker, and the invocation is
UTF-8 text. No MeshCentral server and no live credential are involved.
"""
from __future__ import annotations

import hashlib
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from kagent.local_agent_meshcentral_private_reader import (
    MeshCentralCliFileReadPort, MeshCentralReadRefused, _PASSWORD_MARKER,
)
from kagent.local_agent_oracle_mesh_executor import (
    CHANNEL_HEADER, POLL_PATH, PRODUCT_USER_AGENT, RESULT_PATH,
    OracleMeshChannelRefused, OracleMeshDispatch, OracleMeshExecutor,
    MAX_RESULT_REJECTIONS, OracleMeshExecutionOutcome, make_oracle_mesh_executor,
)

SECRET = "deployment-channel-secret-value-261017"
PASSWORD = "op3rator-meshtr0ll-secret"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\ProgramData\\Padiem\\report.txt"


class _StubPort:
    """Stand-in read port; the channel transport is what is under test here."""

    def read_bytes(self, *, node_ref, file_path, timeout_seconds):  # noqa: D102
        del node_ref, file_path, timeout_seconds
        return b""


class ChannelTransportHeaderTests(unittest.TestCase):
    """Every channel leg must identify the product, never Python-urllib.

    Cloudflare's Browser Integrity Check refuses the default urllib signature
    with error 1010 *before* the channel secret is evaluated, so the first-party
    product token has to ride on the request while the channel auth header and
    the existing redirect refusal stay exactly as they were.
    """

    class _Response:
        status = 200

        def read(self, _n=-1):  # noqa: D102
            return b'{"ok": true, "dispatch": null}'

        def __enter__(self):  # noqa: D102
            return self

        def __exit__(self, *exc):  # noqa: D102
            return False

    def _executor(self) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
        )

    def test_poll_leg_sends_the_product_user_agent_and_keeps_channel_auth(self):
        executor = self._executor()
        sent: dict = {}

        class _Opener:
            def open(self, request, timeout=None):  # noqa: D102
                del timeout
                sent["headers"] = dict(request.header_items())
                return ChannelTransportHeaderTests._Response()

        with patch("urllib.request.build_opener", return_value=_Opener()):
            status, data = executor._https_post(POLL_PATH, None)

        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))
        lowered = {name.lower(): value for name, value in sent["headers"].items()}
        self.assertEqual(lowered["user-agent"], PRODUCT_USER_AGENT)
        self.assertNotIn("python-urllib", lowered["user-agent"].lower())
        # Channel auth and content negotiation are untouched by the fix.
        self.assertEqual(lowered[CHANNEL_HEADER.lower()], SECRET)
        self.assertEqual(lowered["content-type"], "application/json")
        self.assertEqual(lowered["accept"], "application/json")


class FactoryRunnerTests(unittest.TestCase):
    def _factory(self) -> OracleMeshExecutor:
        work = Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="oracle_exec_4139_")
        ))
        return make_oracle_mesh_executor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            meshctrl_js=str(work / "meshctrl.js"),
            login_user="padiemadmin",
            password_provider=lambda: PASSWORD,
            work_dir=str(work),
        )

    def test_factory_builds_the_real_official_client_port(self):
        executor = self._factory()
        port = executor._read_port
        self.assertIsInstance(port, MeshCentralCliFileReadPort)
        self.assertTrue(port._meshctrl_js.endswith("meshctrl.js"))

    def test_credential_reaches_the_child_on_stdin_and_never_on_argv(self):
        executor = self._factory()
        captured: dict = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = list(argv)
            captured.update(kwargs)
            # The official client stages the download; emulate that here so the
            # port's own read path is what is under test.
            target = argv[argv.index("--target") + 1]
            Path(target).write_bytes(b"PADIEM MESH\r\nEND\n")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with patch("subprocess.run", side_effect=fake_run):
            body = executor._read_port.read_bytes(
                node_ref=NODE, file_path=FILE_PATH, timeout_seconds=30,
            )

        self.assertEqual(body, b"PADIEM MESH\r\nEND\n")
        # The credential is delivered as UTF-8 text on stdin, once.
        self.assertEqual(captured["input"], PASSWORD + "\n")
        self.assertIs(captured["text"], True)
        self.assertEqual(captured["encoding"], "utf-8")
        self.assertTrue(captured["capture_output"])
        # The argv carries the public marker, never the credential.
        argv = captured["argv"]
        self.assertIn(_PASSWORD_MARKER, argv)
        self.assertNotIn(PASSWORD, argv)
        self.assertNotIn(PASSWORD + "\n", argv)
        for token in argv:
            self.assertNotIn(PASSWORD, token)

    def test_failed_client_run_still_refuses_without_leaking(self):
        executor = self._factory()

        def fake_run(argv, **kwargs):
            self.assertEqual(kwargs.get("input"), PASSWORD + "\n")
            return subprocess.CompletedProcess(argv, 1, "", "denied")

        with patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises(MeshCentralReadRefused):
                executor._read_port.read_bytes(
                    node_ref=NODE, file_path=FILE_PATH, timeout_seconds=30,
                )

    def test_no_input_means_no_forced_pipe(self):
        """A runner call without input must not fabricate an empty stdin write."""
        executor = self._factory()
        captured: dict = {}

        def fake_run(argv, **kwargs):
            captured.update(kwargs)
            return subprocess.CompletedProcess(argv, 0, "", "")

        runner = None
        port = executor._read_port
        # Reach the factory's own runner through the port's stored runner.
        runner = getattr(port, "_command_runner")
        assert callable(runner)
        with patch("subprocess.run", side_effect=fake_run):
            runner(["node", "--version"], timeout=5)
        self.assertNotIn("input", captured)
        self.assertIs(captured["text"], True)
        self.assertEqual(captured["encoding"], "utf-8")


class EntrypointTests(unittest.TestCase):
    def test_main_refuses_to_start_without_required_configuration(self):
        from kagent.local_agent_oracle_mesh_executor import main

        import io
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main({"ORACLE_MESH_CHAT_ORIGIN": "https://chat.padiem.net"})
        self.assertEqual(code, 2)
        self.assertIn("refused to start", err.getvalue())
        self.assertNotIn(SECRET, err.getvalue())

    def test_main_refuses_a_non_https_origin_before_reading_anything(self):
        from kagent.local_agent_oracle_mesh_executor import main

        import io
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = main({
                "ORACLE_MESH_CHAT_ORIGIN": "http://chat.padiem.net",
                "ORACLE_MESH_CHANNEL_SECRET_FILE": "/nonexistent/secret",
                "ORACLE_MESH_MESHCTRL_JS": "/nonexistent/meshctrl.js",
                "ORACLE_MESH_LOGIN_USER": "padiemadmin",
                "ORACLE_MESH_PASSWORD_FILE": "/nonexistent/password",
            })
        self.assertEqual(code, 2)


class ResultSubmitTests(unittest.TestCase):
    """0-byte outcomes carry the canonical empty digest; refusals keep the hold."""

    def _executor(self, transport) -> OracleMeshExecutor:
        return OracleMeshExecutor(
            chat_origin="https://chat.padiem.net",
            channel_secret=SECRET,
            read_port=_StubPort(),
            transport=transport,
        )

    def _dispatch(self) -> OracleMeshDispatch:
        return OracleMeshDispatch(
            dispatch_id="dsp-1", nonce="n" * 32, node_ref=NODE,
            file_path=FILE_PATH, command_id="cmd-1", run_id="run-1",
        )

    def test_empty_body_submits_the_canonical_empty_digest(self):
        seen: dict = {}

        def transport(path, payload):
            seen["path"] = path
            seen["payload"] = dict(payload)
            return 200, {"ok": True, "status": "failed"}

        executor = self._executor(transport)
        outcome = OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=b"")
        result = executor.submit(self._dispatch(), outcome)

        self.assertTrue(result.get("ok"))
        self.assertEqual(seen["path"], RESULT_PATH)
        self.assertEqual(seen["payload"]["content_bytes"], 0)
        self.assertEqual(
            seen["payload"]["content_sha256"], hashlib.sha256(b"").hexdigest()
        )

    def test_dispatch_rejection_is_retried_bounded_then_dropped(self):
        # The same 409 code is also answered while the row is still an
        # unfinished received row, so the held outcome is kept for a few
        # attempts — but never resent forever.
        attempts = []

        def transport(path, payload):
            attempts.append(path)
            return 409, {"ok": False, "error": {"code": "oracle_mesh_dispatch_rejected"}}

        executor = self._executor(transport)
        outcome = OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=b"")
        first = executor.submit(self._dispatch(), outcome)
        self.assertFalse(first.get("ok"))
        self.assertTrue(first.get("retryable"))
        self.assertTrue(executor.resend_pending)
        final = None
        for _ in range(MAX_RESULT_REJECTIONS + 1):
            if not executor.resend_pending:
                break
            final = executor.resend_pending_result()
        self.assertTrue(final.get("dropped"))
        self.assertEqual(final.get("status"), 409)
        self.assertFalse(executor.resend_pending)
        self.assertEqual(len(attempts), MAX_RESULT_REJECTIONS)

    def test_fingerprint_mismatch_is_retried_bounded_then_dropped(self):
        def transport(path, payload):
            return 409, {
                "ok": False, "error": {"code": "oracle_mesh_result_fingerprint_mismatch"}
            }

        executor = self._executor(transport)
        outcome = OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=b"abc")
        first = executor.submit(self._dispatch(), outcome)
        self.assertTrue(first.get("retryable"))
        self.assertTrue(executor.resend_pending)
        final = None
        for _ in range(MAX_RESULT_REJECTIONS + 1):
            if not executor.resend_pending:
                break
            final = executor.resend_pending_result()
        self.assertTrue(final.get("dropped"))
        self.assertFalse(executor.resend_pending)


if __name__ == "__main__":
    unittest.main()