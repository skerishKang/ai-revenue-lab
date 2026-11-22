"""Actual child-process coverage for the bounded tests-only runner."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/b62_run_tests_only_modules.py"
SPEC = importlib.util.spec_from_file_location("b62_run_tests_only_modules", SCRIPT)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class ModuleRunnerTest(unittest.TestCase):
    def run_selected(self, modules, child, timeout=5):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = runner.run_modules(modules, timeout_seconds=timeout,
                                    command=(sys.executable, "-c", child))
        return rc, out.getvalue()

    def test_each_module_has_start_and_end(self):
        rc, output = self.run_selected(["one.py", "two.py"], "pass")
        self.assertEqual(rc, 0)
        self.assertIn("START 1/2 one.py", output)
        self.assertIn("END 1/2 one.py status=PASS", output)
        self.assertIn("START 2/2 two.py", output)
        self.assertIn("END 2/2 two.py status=PASS", output)

    def test_nonzero_exit_is_not_hidden(self):
        rc, output = self.run_selected(
            ["bad.py", "later.py"], "import sys; sys.exit(7)")
        self.assertEqual(rc, 7)
        self.assertIn("END 1/2 bad.py status=FAIL exit=7", output)
        self.assertNotIn("later.py", output)

    def test_timeout_identifies_module_and_fails_closed(self):
        rc, output = self.run_selected(
            ["hang.py", "later.py"], "import time; time.sleep(60)", timeout=0.5)
        self.assertEqual(rc, runner.TIMEOUT_EXIT)
        self.assertIn("START 1/2 hang.py", output)
        self.assertIn("END 1/2 hang.py status=TIMEOUT exit=124", output)
        self.assertNotIn("later.py", output)

    def test_empty_selection_fails_closed(self):
        rc, output = self.run_selected([], "pass")
        self.assertEqual(rc, 1)
        self.assertIn("B62_TESTS_ONLY=EMPTY", output)


if __name__ == "__main__":
    unittest.main()
