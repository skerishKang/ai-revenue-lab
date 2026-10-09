"""Regression tests for B62 PR path routing and fail-open behavior."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b62_browser_qa_path_plan.py"
spec = importlib.util.spec_from_file_location("b62_qa_plan", SCRIPT)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)
FOLDER = ROOT / ".github" / "workflows"
MASTER = FOLDER / "b62-browser-qa-unified.yml"


class B62UnifiedBrowserQAContract(unittest.TestCase):
    def setUp(self):
        self.paths = planner.load_paths()

    def test_all_original_qas_migrated_to_one_dispatcher(self):
        self.assertEqual(len(self.paths), 16)
        master = MASTER.read_text(encoding="utf-8")
        self.assertIn("  pull_request:", master)
        self.assertIn("  pull-requests: read", master)
        self.assertIn("cancel-in-progress: true", master)
        self.assertIn("python .github/scripts/b62_browser_qa_path_plan.py", master)
        self.assertIn("needs: plan", master)
        for job, patterns in self.paths.items():
            with self.subTest(job=job):
                old_files = [
                    p for p in FOLDER.glob("b62-*.yml")
                    if p.name != MASTER.name
                    and ("\n  " + job + ":\n") in p.read_text(encoding="utf-8")
                ]
                self.assertEqual(len(old_files), 1)
                original = old_files[0].read_text(encoding="utf-8")
                self.assertIn("  workflow_dispatch:", original)
                self.assertNotIn("\n  pull_request:", original)
                self.assertIn("cancel-in-progress: true", original)
                self.assertIn("Cache pinned Playwright Chromium", original)
                self.assertIn("\n  " + job + ":\n", master)
                self.assertIn("needs.plan.outputs." + job.replace("-", "_"), master)
                self.assertIn(old_files[0].relative_to(ROOT).as_posix(), patterns)

    def test_original_job_steps_and_environment_are_identical(self):
        import re
        master = MASTER.read_text(encoding="utf-8")
        for job in self.paths:
            with self.subTest(job=job):
                originals = [
                    p for p in FOLDER.glob("b62-*.yml")
                    if p.name != MASTER.name
                    and ("\n  " + job + ":\n") in p.read_text(encoding="utf-8")
                ]
                self.assertEqual(len(originals), 1)
                old_text = originals[0].read_text(encoding="utf-8")
                regex = r"(?ms)^  " + re.escape(job) + r":\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)"
                before = re.search(regex, old_text)
                after = re.search(regex, master)
                self.assertIsNotNone(before)
                self.assertIsNotNone(after)
                new_lines = after.group(1).splitlines()
                self.assertEqual(new_lines[0], "    needs: plan")
                self.assertIn("needs.plan.outputs." + job.replace("-", "_"), new_lines[1])
                self.assertEqual("\n".join(new_lines[2:]).strip(), before.group(1).strip())
    def test_runtime_changes_select_affected_lanes(self):
        chosen = planner.choose_lanes({"apps/padiem-chat/static/app.js"}, self.paths)
        self.assertEqual(sum(chosen.values()), 15)
        self.assertFalse(chosen["mobile-touch-target-qa"])
        self.assertTrue(chosen["browser-qa"])
        self.assertTrue(chosen["accessibility-browser-qa"])

    def test_css_touch_target_selects_all_sixteen(self):
        chosen = planner.choose_lanes({"apps/padiem-chat/static/padiem-first-use.css"}, self.paths)
        self.assertEqual(sum(chosen.values()), 16)

    def test_test_only_and_worker_only_changes_do_not_run_browser_qa(self):
        for filename in (
            "apps/padiem-chat/tests/test_projects.py",
            "apps/padiem-chat/worker.py",
            "docs/operations/changelog.md",
            "packages/padiem-control-plane/other.py",
        ):
            with self.subTest(filename=filename):
                self.assertFalse(any(planner.choose_lanes({filename}, self.paths).values()))

    def test_core_change_selects_only_deep_research_and_web_search(self):
        chosen = planner.choose_lanes({"packages/padiem-ai-core/padiem_ai_core/router.py"}, self.paths)
        self.assertEqual({job for job, val in chosen.items() if val},
                         {"deep-research-browser-qa", "web-search-browser-qa"})

    def test_one_script_change_selects_only_its_qa(self):
        selected = planner.choose_lanes({".github/scripts/b62_projects_browser_qa.py"}, self.paths)
        self.assertEqual({job for job, val in selected.items() if val}, {"projects-browser-qa"})

    def test_planner_and_manifest_changes_fail_open_to_all(self):
        for filename in planner.PLAN_FILES:
            chosen = planner.choose_lanes({filename}, self.paths)
            self.assertTrue(all(chosen.values()))

    def test_api_or_unknown_state_fails_open_to_all(self):
        self.assertTrue(all(planner.choose_lanes(None, self.paths).values()))
        self.assertIsNone(planner.fetch_changed_paths({}, {}))
        event = {"pull_request": {"number": 123, "changed_files": 3000}}
        env = {"GITHUB_API_URL": "https://api.github.com",
               "GITHUB_REPOSITORY": "skerishKang/ai-revenue-lab", "GITHUB_TOKEN": "dummy"}
        self.assertIsNone(planner.fetch_changed_paths(event, env))
        with patch.object(planner, "urlopen", side_effect=URLError("offline")):
            self.assertIsNone(planner.fetch_changed_paths(
                {"pull_request": {"number": 123, "changed_files": 20}}, env
            ))

    def test_github_workflow_path_is_selected(self):
        self.assertTrue(planner.path_matches(".github/workflows/b62-browser-visual-qa.yml",
                                              self.paths["browser-qa"]))


if __name__ == "__main__":
    unittest.main()