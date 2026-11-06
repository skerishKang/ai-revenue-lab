"""Exit-code contract tests for the queue's shell health probe."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "deploy" / "health_check.sh"
BASH_BIN = os.environ.get("PADIEM_TEST_BASH") or shutil.which("bash") or "bash"


class QueueHealthCheckExitCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mesh-queue-health-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fake_bin = self.tmp / "bin"
        self.fake_bin.mkdir()
        fake_curl = self.fake_bin / "curl"
        fake_curl.write_text(
            """#!/usr/bin/env bash
if [[ ${FAKE_CURL_EXIT:-0} != 0 ]]; then
  printf 'fixture curl failure\\n' >&2
  exit "$FAKE_CURL_EXIT"
fi
printf '%s' "${FAKE_CURL_BODY:-}"
""",
            encoding="utf-8",
        )
        fake_curl.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "MESH_QUEUE_HEALTH_URL": "http://127.0.0.1:8797/health",
            "MESH_QUEUE_HEALTH_TIMEOUT_SECONDS": "1",
            "FAKE_CURL_EXIT": "0",
        }

    def _run(self, body: str = "", curl_exit: int = 0) -> subprocess.CompletedProcess[str]:
        env = {
            **self.env,
            "FAKE_CURL_BODY": body,
            "FAKE_CURL_EXIT": str(curl_exit),
        }
        return subprocess.run(
            [BASH_BIN, str(SCRIPT)],
            cwd=self.tmp,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def test_curl_failure_returns_nonzero_and_keeps_marker(self) -> None:
        result = self._run(curl_exit=7)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "MESH_QUEUE_HEALTH=UNREACHABLE curl=7 target=http://127.0.0.1:8797/health",
        )

    def test_invalid_json_returns_nonzero_and_keeps_unparsed_marker(self) -> None:
        result = self._run("not-json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertRegex(result.stdout.strip(), r"^MESH_QUEUE_HEALTH=UNPARSED bytes=\d+$")

    def test_unexpected_json_returns_nonzero_and_keeps_shape_marker(self) -> None:
        result = self._run("[]")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout.strip(), "MESH_QUEUE_HEALTH=UNEXPECTED shape=list")

    def test_healthy_json_returns_zero_and_keeps_counts(self) -> None:
        result = self._run(
            '{"ok":true,"pending_unclaimed":2,"pending_claimed":3,"received":4}'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "MESH_QUEUE_HEALTH=OK pending_unclaimed=2 pending_claimed=3 received=4",
        )


if __name__ == "__main__":
    unittest.main()
