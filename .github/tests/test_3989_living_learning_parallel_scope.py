"""#3989: both original Living Learning/Core suites must run and fail closed."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/living-learning-padiem-core-ci.yml"
SCRIPT = ROOT / ".github/scripts/living_learning_core_parallel_3989.sh"


class ParallelSuiteContract(unittest.TestCase):
    def test_workflow_keeps_full_suite_names_trigger_and_mock_gate(self):
        source = WORKFLOW.read_text(encoding="utf-8")
        for marker in (
            "Living Learning full tests",
            "Padiem AI Core full tests",
            "Prove default provider remains mock",
            "LL_PROVIDER_TYPE",  # contract now carried by the wrapper
            "living_learning_core_parallel_3989.sh",
            "test_3989_living_learning_parallel_scope.py",
            "  cancel-in-progress: true",
            "contents: read",
        ):
            # LL_PROVIDER_TYPE is inside the script; other markers are in workflow.
            if marker == "LL_PROVIDER_TYPE":
                self.assertIn("export LL_PROVIDER_TYPE=mock", SCRIPT.read_text(encoding="utf-8"))
            else:
                self.assertIn(marker, source)
        self.assertIn("run: bash .github/scripts/living_learning_core_parallel_3989.sh", source)
        self.assertIn("run: python .github/tests/test_3989_living_learning_parallel_scope.py", source)

    def test_unabridged_both_test_commands_and_independent_wait(self):
        source = SCRIPT.read_text(encoding="utf-8")
        for required in (
            'cd "$root/apps/living-learning"',
            'cd "$root/packages/padiem-ai-core"',
            "export LL_PROVIDER_TYPE=mock",
            "pytest -q",
            'wait "$ll_pid" || ll_status=$?',
            'wait "$core_pid" || core_status=$?',
            'if [[ "$ll_status" -ne 0 || "$core_status" -ne 0 ]]',
            'LIVING_LEARNING_CORE_PARALLEL=PASS',
        ):
            self.assertIn(required, source)
        self.assertEqual(source.count("  pytest -q"), 2)
        for forbidden in ("--ignore", "--deselect", "--last-failed", "--lf", "-k ", "|| true", "continue-on-error:"):
            self.assertNotIn(forbidden, source)

    def test_actual_child_exit_codes_are_not_masked(self):
        # No real pytest runs in this contract probe: exercise the exact wrapper
        # against two controlled child processes, including independent failures.
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / ".github/scripts").mkdir(parents=True)
            (p / "apps/living-learning").mkdir(parents=True)
            (p / "packages/padiem-ai-core").mkdir(parents=True)
            shutil.copyfile(SCRIPT, p / ".github/scripts/living_learning_core_parallel_3989.sh")
            bin_dir = p / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "pytest"
            fake.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$PWD\" == */apps/living-learning ]]; then\n"
                "  [[ \"${LL_PROVIDER_TYPE:-}\" == mock ]] || exit 40\n"
                "  echo FAKE_LIVING_LEARNING_EXECUTED\n"
                "  exit \"${FAKE_LL_EXIT:-0}\"\n"
                "fi\n"
                "if [[ \"$PWD\" == */packages/padiem-ai-core ]]; then\n"
                "  echo FAKE_CORE_EXECUTED\n"
                "  exit \"${FAKE_CORE_EXIT:-0}\"\n"
                "fi\n"
                "exit 41\n", encoding="utf-8")
            fake.chmod(0o755)
            for ll_code, core_code in ((0, 0), (2, 0), (0, 3), (4, 5)):
                with self.subTest(ll=ll_code, core=core_code):
                    env = dict(os.environ,
                               PATH=str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                               FAKE_LL_EXIT=str(ll_code), FAKE_CORE_EXIT=str(core_code))
                    result = subprocess.run(
                        ["bash", str(p / ".github/scripts/living_learning_core_parallel_3989.sh")],
                        env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        timeout=15, check=False,
                    )
                    self.assertIn("FAKE_LIVING_LEARNING_EXECUTED", result.stdout)
                    self.assertIn("FAKE_CORE_EXECUTED", result.stdout)
                    self.assertIn(f"LIVING_LEARNING_TEST_EXIT={ll_code}", result.stdout)
                    self.assertIn(f"PADIEM_CORE_TEST_EXIT={core_code}", result.stdout)
                    self.assertEqual(result.returncode == 0, ll_code == core_code == 0)


if __name__ == "__main__":
    unittest.main()
