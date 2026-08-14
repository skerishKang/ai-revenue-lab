from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kagent.cli import allowed_test_command, main, run_allowed_test
from kagent.core import AgentBoundaryError


class CliTests(unittest.TestCase):
    def test_help_starts(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("kagent", out.getvalue().lower())

    def test_plan_mode_is_read_only_and_shows_mock_route(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("print('x')\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main([str(root), "plan", "이 코드를 분석해줘"])
            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("PLAN MODE", rendered)
            self.assertIn("B14 MOCK", rendered)
            self.assertIn("network_called=False", rendered)
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "print('x')\n")

    def test_normal_korean_run_journey_can_reject_write_and_command(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "a.py"
            target.write_text("print('x')\n", encoding="utf-8")
            out = io.StringIO()
            with mock.patch("builtins.input", side_effect=["n", "n"]):
                with contextlib.redirect_stdout(out):
                    code = main([str(root), "run", "저장 버튼 오류를 분석해줘"])
            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("[B14 MOCK ADAPTER]", rendered)
            self.assertIn("쓰기 거부: 파일 변경 없음", rendered)
            self.assertIn("명령 실행 거부: 실행 없음", rendered)
            self.assertIn("자동 commit/push/merge/deploy는 없습니다", rendered)
            self.assertEqual(target.read_text(encoding="utf-8"), "print('x')\n")

    def test_english_only_task_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main([td, "plan", "fix the save button"])
            self.assertEqual(code, 2)
            self.assertIn("한국어 작업 설명", err.getvalue())

    def test_command_allowlist_rejects_arbitrary_shell(self):
        for raw in ("git push", "git commit -am x", "curl https://example.com", "rm -rf ."):
            with self.assertRaises(AgentBoundaryError):
                allowed_test_command(raw)

    def test_command_allowlist_has_no_git_or_network_command(self):
        for value in ("python -m unittest", "python -m unittest discover", "python -m compileall ."):
            command = allowed_test_command(value)
            rendered = " ".join(command).lower()
            self.assertNotIn("git", rendered)
            self.assertNotIn("curl", rendered)
            self.assertNotIn("wget", rendered)
            self.assertNotIn("deploy", rendered)

    def test_failing_then_corrected_passing_test_evidence_in_disposable_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            test_file = root / "test_fixture.py"
            test_file.write_text(
                "import unittest\n"
                "class Fixture(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        self.assertEqual(1, 2)\n",
                encoding="utf-8",
            )
            command = allowed_test_command("python -m unittest discover")
            failing = run_allowed_test(command, root)
            self.assertNotEqual(failing.returncode, 0)
            self.assertIn("FAILED", failing.stderr + failing.stdout)

            test_file.write_text(
                "import unittest\n"
                "class Fixture(unittest.TestCase):\n"
                "    def test_value(self):\n"
                "        self.assertEqual(2, 2)\n",
                encoding="utf-8",
            )
            # The purpose of this fixture is to prove the corrected source, not
            # a cached .pyc. Remove bytecode explicitly so both fast Linux and
            # Windows filesystems execute the rewritten test source.
            shutil.rmtree(root / "__pycache__", ignore_errors=True)
            passing = run_allowed_test(command, root)
            self.assertEqual(passing.returncode, 0)
            self.assertIn("OK", passing.stderr + passing.stdout)

    def test_allowed_test_output_is_secret_redacted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "test_secret.py").write_text(
                "import unittest\n"
                "class Fixture(unittest.TestCase):\n"
                "    def test_output(self):\n"
                "        print('OPENROUTER_API_KEY=sk-or-v1-abcdef1234567890')\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            result = run_allowed_test(
                allowed_test_command("python -m unittest discover"), root
            )
            self.assertEqual(result.returncode, 0)
            rendered = result.stdout + result.stderr
            self.assertNotIn("abcdef1234567890", rendered)
            self.assertIn("[REDACTED", rendered)


if __name__ == "__main__":
    unittest.main()
