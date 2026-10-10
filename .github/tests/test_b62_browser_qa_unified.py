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

    def test_one_workflow_owns_all_16_original_jobs_and_manual_selection(self):
        self.assertEqual(len(self.paths), 16)
        master = MASTER.read_text(encoding="utf-8")
        self.assertIn("  pull_request:", master)
        self.assertIn("  workflow_dispatch:", master)
        self.assertIn("  pull-requests: read", master)
        self.assertIn("cancel-in-progress: true", master)
        self.assertIn("python .github/scripts/b62_browser_qa_path_plan.py", master)
        self.assertIn("B62_MANUAL_LANE:", master)
        self.assertIn("needs: plan", master)
        self.assertIn("          - all", master)
        for job, patterns in self.paths.items():
            with self.subTest(job=job):
                self.assertIn("\n  " + job + ":\n", master)
                self.assertIn("needs.plan.outputs." + job.replace("-", "_"), master)
                self.assertIn("          - " + job + "\n", master)
                self.assertIn("Cache pinned Playwright Chromium", master)
        self.assertEqual(master.count("Cache pinned Playwright Chromium"), 16)
        # No standalone QA workflow is retained just for a duplicate manual trigger.
        self.assertEqual(
            [file.name for file in FOLDER.glob("b62-*-browser-qa.yml")],
            [],
        )

    def test_official_ubuntu_mirror_pilot_preserves_full_browser_dependency_contract(self):
        master = MASTER.read_text(encoding="utf-8")
        self.assertEqual(master.count("run: uv run playwright install --with-deps chromium"), 16)
        self.assertEqual(
            master.count("run: bash ../../.github/scripts/b62_playwright_apt_mirror_3989.sh"),
            2,
        )
        # Match anchored top-level YAML job headers only; splitting on
        # "\\n  " also splits deeper indented lines and loses the job IDs.
        import re
        headings = list(re.finditer(r"(?m)^  ([a-z][a-z0-9-]+):$", master))
        job_sources = {}
        for index, heading in enumerate(headings):
            name = heading.group(1)
            if name in self.paths:
                end = headings[index + 1].start() if index + 1 < len(headings) else len(master)
                job_sources[name] = master[heading.end():end]
        self.assertEqual(len(job_sources), 16)
        for name, source in job_sources.items():
            with self.subTest(name=name):
                expected = name in ("error-retry-browser-qa", "saved-outputs-browser-qa")
                self.assertEqual("b62_playwright_apt_mirror_3989.sh" in source, expected)
                self.assertIn("uv run playwright install --with-deps chromium", source)
        script = (ROOT / ".github/scripts/b62_playwright_apt_mirror_3989.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("ubuntu-24.04", script)
        self.assertIn("azure.archive.ubuntu.com/ubuntu/", script)
        self.assertIn("archive.ubuntu.com/ubuntu/", script)
        self.assertIn("set -euo pipefail", script)
        self.assertIn("B62_APT_INSTALL_CONTRACT=PLAYWRIGHT_WITH_DEPS_UNCHANGED", script)
        self.assertNotIn("apt-get install", script)
        self.assertNotIn("apt-get update", script)
        self.assertNotIn("http://security.ubuntu.com", script)

    def test_targeted_manual_dispatch_matches_original_one_job_behavior(self):
        for lane in self.paths:
            with self.subTest(lane=lane):
                actual = planner.choose_manual_lanes(lane, self.paths)
                self.assertEqual([job for job, enabled in actual.items() if enabled], [lane])
        self.assertTrue(all(planner.choose_manual_lanes("all", self.paths).values()))
        for invalid in ("", "ALL", "unknown-job", " b62 ", "production-deploy"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    planner.choose_manual_lanes(invalid, self.paths)

    def test_runtime_changes_select_affected_lanes(self):
        chosen = planner.choose_lanes({"apps/padiem-chat/static/app.js"}, self.paths)
        self.assertEqual(sum(chosen.values()), 15)
        self.assertFalse(chosen["mobile-touch-target-qa"])
        self.assertTrue(chosen["browser-qa"])
        self.assertTrue(chosen["accessibility-browser-qa"])

    def test_css_touch_target_selects_all_sixteen(self):
        chosen = planner.choose_lanes({"apps/padiem-chat/static/padiem-first-use.css"}, self.paths)
        self.assertEqual(sum(chosen.values()), 16)

    def test_leaf_owned_ui_modules_select_only_related_browser_journeys(self):
        # Explicit exact leaf paths; shared app, auth, CSS, and unknown scope stay broad.
        cases = {
            "apps/padiem-chat/static/claw-web-xlsx-sources.js": {
                "accessibility-browser-qa", "auth-history-browser-qa",
                "browser-qa", "document-browser-qa", "project-files-browser-qa",
            },
            "apps/padiem-chat/static/conversation-export.js": {
                "accessibility-browser-qa", "auth-history-browser-qa",
                "browser-qa", "conversation-export-browser-qa",
                "error-retry-browser-qa", "saved-outputs-browser-qa",
            },
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual({j for j, enabled in planner.choose_lanes({path}, self.paths).items()
                                  if enabled}, expected)
                for shared in ("apps/padiem-chat/static/app.js",
                               "apps/padiem-chat/app/app_factory.py"):
                    self.assertEqual(planner.choose_lanes({path, shared}, self.paths),
                                     planner.choose_lanes({shared}, self.paths))
                self.assertTrue(all(planner.choose_lanes(
                    {path, ".github/ci/b62_browser_qa_paths.json"}, self.paths).values()))
                for job, patterns in self.paths.items():
                    if job == "mobile-touch-target-qa":
                        continue
                    excl = "!" + path
                    if job in expected:
                        self.assertNotIn(excl, patterns)
                    else:
                        self.assertIn(excl, patterns)
                        self.assertGreater(patterns.index(excl),
                                           patterns.index("!apps/padiem-chat/static/b66-quote-runtime.js"))
        self.assertEqual(sum(planner.choose_lanes(
            {"apps/padiem-chat/static/claw-local-handoff.js"}, self.paths).values()), 15)
        self.assertEqual(sum(planner.choose_lanes(
            {"apps/padiem-chat/static/padiem-first-use.css"}, self.paths).values()), 16)

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

    def test_own_dispatcher_changes_trigger_all_lane_checks(self):
        for path in planner.PLAN_FILES:
            self.assertTrue(all(planner.choose_lanes({path}, self.paths).values()))



if __name__ == "__main__":
    unittest.main()