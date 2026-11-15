"""Exit-code contract tests for the queue's shell health probe."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "deploy" / "health_check.sh"
# CreateProcess prefers System32 (WSL) over PATH for "bash"; resolve it once
# through the shared locator: registry ignored, probe-verified, never WSL.
_TEST_BASH_SPEC = importlib.util.spec_from_file_location(
    "_padiem_test_bash_locator",
    HERE.parents[2] / "tests" / "_test_bash_locator.py")
_test_bash = importlib.util.module_from_spec(_TEST_BASH_SPEC)
_TEST_BASH_SPEC.loader.exec_module(_test_bash)
BASH_BIN, BASH_BIN_SKIP_REASON = _test_bash.locate_test_bash()


@unittest.skipIf(BASH_BIN is None, BASH_BIN_SKIP_REASON)
# The fake curl reaches health_check.sh through PATH; on Windows Git Bash
# prepends its own mingw64/bin and its bundled curl.exe shadows the fake, so
# the contract keeps running where the fake can win: POSIX.
@unittest.skipUnless(os.name == "posix",
                     "the fake curl arrives through PATH, which Git Bash's own "
                     "mingw64/bin shadows on Windows; run on POSIX")
class QueueHealthCheckExitCodeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="mesh-queue-health-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fake_bin = self.tmp / "bin"
        self.fake_bin.mkdir()
        fake_curl = self.fake_bin / "curl"
        # LF endings: this fake is executed by the real POSIX shell; a CRLF
        # shebang line would break the exec on Git Bash (Windows checkout).
        fake_curl.write_text(
            """#!/usr/bin/env bash
if [[ ${FAKE_CURL_EXIT:-0} != 0 ]]; then
  printf 'fixture curl failure\\n' >&2
  exit "$FAKE_CURL_EXIT"
fi
printf '%s' "${FAKE_CURL_BODY:-}"
""",
            encoding="utf-8",
            newline="\n",
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
