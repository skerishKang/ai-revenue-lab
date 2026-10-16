"""#4139 — the executor factory must run the official client for real.

One focused check goes through ``make_oracle_mesh_executor`` so the actual
factory-built read port is exercised: the operator credential reaches the child
on stdin, the argv carries only the public marker, and the invocation is
UTF-8 text. No MeshCentral server and no live credential are involved.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from kagent.local_agent_meshcentral_private_reader import (
    MeshCentralCliFileReadPort, MeshCentralReadRefused, _PASSWORD_MARKER,
)
from kagent.local_agent_oracle_mesh_executor import (
    OracleMeshExecutor, make_oracle_mesh_executor,
)

SECRET = "deployment-channel-secret-value-261017"
PASSWORD = "op3rator-meshtr0ll-secret"
NODE = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
FILE_PATH = "C:\\ProgramData\\Padiem\\report.txt"


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


if __name__ == "__main__":
    unittest.main()