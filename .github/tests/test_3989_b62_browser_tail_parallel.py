"""#3989: fail-closed contracts for the B62 browser QA visual tail scheduler."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import threading
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".github/scripts/b62_browser_qa_tail_parallel.py"
WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"

spec = importlib.util.spec_from_file_location("b62_qa_tail", SOURCE)
tail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tail)


class BrowserQATailContract(unittest.TestCase):
    def test_original_three_full_suites_are_unchanged_and_all_selected(self):
        self.assertEqual(tail.SCRIPTS, (
            "b62_glass_shell_visual_qa.py",
            "b62_glass_zoom_visual_qa.py",
            "b62_chat_gutter_visual_qa.py",
        ))
        self.assertEqual(tail.MAX_PARALLEL, 1)
        self.assertEqual(tail.TIMEOUT_SECONDS, 240)
        for name in tail.SCRIPTS:
            self.assertTrue((tail.SCRIPT_DIR / name).is_file(), name)
        workflow = WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("\n  browser-qa:\n", 1)[1].split(
            "\n  conversation-delete-browser-qa:\n", 1
        )[0]
        self.assertEqual(job.count("b62_browser_qa_tail_parallel.py"), 1)
        self.assertIn("run: uv run python ../../.github/scripts/b62_browser_visual_qa.py", job)
        self.assertIn("run: uv run python ../../.github/scripts/b62_product_surface_certification_evidence_qa.py", job)
        self.assertIn("name: Upload browser evidence", job)
        self.assertIn("name: Print QA report", job)
        # Existing full suite scripts remain independently discoverable, even
        # though their three old sequential CI steps were consolidated.
        self.assertTrue(all(name not in job for name in tail.SCRIPTS))
        self.assertIn("  browser-qa:\n    needs: plan", workflow)
        self.assertIn("needs.plan.outputs.browser_qa", workflow)

    def test_child_uses_same_python_runtime_and_bounded_process_timeout(self):
        observed = []
        def fake_run(argv, **kwargs):
            observed.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "SUCCESS")
        with patch.object(tail.subprocess, "run", side_effect=fake_run):
            case, rc, _, output = tail.execute(tail.SCRIPTS[0])
        self.assertEqual((case, rc, output), (tail.SCRIPTS[0], 0, "SUCCESS"))
        argv, kw = observed[0]
        self.assertEqual(argv[0], tail.sys.executable)
        self.assertEqual(Path(argv[1]).name, tail.SCRIPTS[0])
        self.assertEqual(kw["timeout"], 240)
        self.assertFalse(kw["check"])
        self.assertEqual(kw["stderr"], subprocess.STDOUT)

    def test_timeout_and_spawn_failures_remain_blocking(self):
        with patch.object(tail.subprocess, "run", side_effect=subprocess.TimeoutExpired(
            cmd=["python"], timeout=240, output=b"PARTIAL_EVIDENCE"
        )):
            _, rc, _, output = tail.execute(tail.SCRIPTS[0])
            self.assertEqual(rc, 124)
            self.assertIn("PARTIAL_EVIDENCE", output)
            self.assertIn("TIMED_OUT=YES", output)
        with patch.object(tail.subprocess, "run", side_effect=OSError("synthetic")):
            _, rc, _, output = tail.execute(tail.SCRIPTS[0])
            self.assertEqual(rc, 127)
            self.assertIn("SPAWN_FAILED=", output)

    def test_mock_only_and_three_suite_fail_closed_aggregation(self):
        out = io.StringIO()
        with patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "prod"}):
            with redirect_stdout(out):
                self.assertEqual(tail.main(), 1)
        self.assertIn("REJECTED=NON_MOCK_RUNTIME", out.getvalue())

        observed = []
        active = 0
        maximum = 0
        lock = threading.Lock()

        def fake_execute(name):
            nonlocal active, maximum
            with lock:
                observed.append(name)
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return name, (1 if name == tail.SCRIPTS[1] else 0), 0.025, "source-evidence\n"

        out = io.StringIO()
        with patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "mock"}):
            with patch.object(tail, "execute", side_effect=fake_execute):
                with redirect_stdout(out):
                    self.assertEqual(tail.main(), 1)
        self.assertCountEqual(observed, tail.SCRIPTS)
        self.assertEqual(maximum, 1)
        self.assertEqual(observed, list(tail.SCRIPTS))
        self.assertIn("B62_VISUAL_TAIL_EXECUTED=3", out.getvalue())
        self.assertIn("B62_VISUAL_TAIL_FAIL_COUNT=1", out.getvalue())

        with patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "mock"}):
            with patch.object(tail, "execute", side_effect=lambda name: (name, 0, 0.1, "PASS")):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(tail.main(), 0)


if __name__ == "__main__":
    unittest.main()
