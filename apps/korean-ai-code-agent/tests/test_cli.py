from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from kagent.cli import allowed_test_command, main
from kagent.core import AgentBoundaryError


class CliTests(unittest.TestCase):
    def test_help_starts(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("kagent", out.getvalue().lower())

    def test_plan_mode_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.py").write_text("print('x')\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main([str(root), "plan", "이 코드를 분석해줘"])
            self.assertEqual(code, 0)
            self.assertIn("PLAN MODE", out.getvalue())
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "print('x')\n")

    def test_command_allowlist_rejects_arbitrary_shell(self):
        with self.assertRaises(AgentBoundaryError):
            allowed_test_command("git push")

    def test_command_allowlist_has_no_git_or_network_command(self):
        for value in ("python -m unittest", "python -m unittest discover", "python -m compileall ."):
            command = allowed_test_command(value)
            rendered = " ".join(command).lower()
            self.assertNotIn("git", rendered)
            self.assertNotIn("curl", rendered)
            self.assertNotIn("wget", rendered)


if __name__ == "__main__":
    unittest.main()
