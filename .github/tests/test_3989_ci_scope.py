"""#3989 CI scope regressions for the B62 browser QA lane ownership.

Three classes are proven here:

* **normal**   - a B66-only change selects no B62 product lane, while a shared
                 Chat change keeps selecting exactly the same lanes as before;
* **mixed**    - a change that touches B66 *and* a shared file still selects the
                 full lane set, so the saving can never hide a real dependency;
* **error**    - planner/manifest edits, an unreadable PR file list or an
                 oversized PR still fail open to running every lane.

Nothing here deletes a test or an audit: it pins the routing decision so an
unrelated product's browser QA cannot silently stop covering shared files.
"""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "b62_qa_plan_3989", ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)

FOLDER = ROOT / ".github/workflows"
STATIC_AUDITS = FOLDER / "b62-static-audits.yml"
RETIRED_AUDITS = (
    "b62-dom-sink-audit.yml",
    "b62-static-origin-audit.yml",
    "b62-browser-persistence-audit.yml",
)

# One representative file per B66 surface that lives inside the shared Chat app.
B66_ONLY = (
    "apps/padiem-chat/app/b66_quote_routes.py",
    "apps/padiem-chat/app/b66_quote_conversation.py",
    "apps/padiem-chat/app/b66_reasoning_level.py",
    "apps/padiem-chat/app/b66_registered_model_boundary.py",
    "apps/padiem-chat/static/b66-quote-runtime.js",
    "apps/padiem-chat/static/b66-quote-runtime.css",
)
# Files every B62 lane genuinely depends on.
SHARED = (
    "apps/padiem-chat/app/app_factory.py",
    "apps/padiem-chat/app/b14_client.py",
    "apps/padiem-chat/static/app.js",
    "apps/padiem-chat/static/padiem-first-use.css",
)


def lanes(changed):
    return {job for job, selected in planner.choose_lanes(set(changed), planner.load_paths()).items() if selected}


class B66ScopedBrowserQA(unittest.TestCase):
    def setUp(self):
        self.paths = planner.load_paths()

    def test_b66_only_change_runs_no_b62_product_lane(self):
        for filename in B66_ONLY:
            with self.subTest(filename=filename):
                self.assertEqual(lanes({filename}), set())

    def test_shared_chat_change_keeps_its_previous_full_lane_set(self):
        """The saving must not move the boundary for files every lane reads."""
        for filename in SHARED:
            with self.subTest(filename=filename):
                # Every lane except the CSS-only touch-target lane, exactly as
                # before this change (asserted by the pre-existing contract).
                self.assertEqual(len(lanes({filename})), 16 if filename.endswith(".css") else 15)

    def test_mixed_change_still_selects_every_affected_lane(self):
        for shared in SHARED:
            for b66 in B66_ONLY:
                with self.subTest(shared=shared, b66=b66):
                    self.assertEqual(lanes({shared, b66}), lanes({shared}))

    def test_leaf_only_scope_never_suppresses_shared_or_uncertain_journeys(self):
        expected = {
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
        for path, jobs in expected.items():
            with self.subTest(path=path):
                self.assertEqual(lanes({path}), jobs)
                self.assertEqual(lanes({path, "apps/padiem-chat/static/app.js"}),
                                 lanes({"apps/padiem-chat/static/app.js"}))
        self.assertEqual(len(lanes({".github/ci/b62_browser_qa_paths.json"})), 16)
        self.assertTrue(all(planner.choose_lanes(None, self.paths).values()))

    def test_core_and_test_only_changes_keep_their_narrow_scope(self):
        self.assertEqual(
            lanes({"packages/padiem-ai-core/padiem_ai_core/router.py"}),
            {"deep-research-browser-qa", "web-search-browser-qa"},
        )
        for filename in (
            "apps/padiem-chat/tests/test_b66_3906_reasoning_level.py",
            "docs/operations/changelog.md",
            "reference/business-66-padiem-quote-v1/index.html",
        ):
            with self.subTest(filename=filename):
                self.assertEqual(lanes({filename}), set())

    def test_lane_scripts_themselves_still_select_their_own_lane(self):
        for job, patterns in self.paths.items():
            script = next(
                (p for p in patterns if p.startswith(".github/scripts/b62_")), None
            )
            if script is None:
                continue
            with self.subTest(job=job):
                self.assertIn(job, lanes({script}))

    def test_error_states_fail_open_to_every_lane(self):
        for filename in planner.PLAN_FILES:
            with self.subTest(filename=filename):
                self.assertTrue(all(planner.choose_lanes({filename}, self.paths).values()))
        self.assertTrue(all(planner.choose_lanes(None, self.paths).values()))
        with patch.object(planner, "urlopen", side_effect=URLError("no api")):
            self.assertIsNone(planner.fetch_changed_paths({"pull_request": {"number": 7}}, {}))
        event = {"pull_request": {"number": 7, "changed_files": 5000}}
        env = {
            "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_REPOSITORY": "skerishKang/ai-revenue-lab",
            "GITHUB_TOKEN": "dummy",
        }
        self.assertIsNone(planner.fetch_changed_paths(event, env))

    def test_manifest_still_declares_every_shared_dependency(self):
        """The new exclusions are additive, ordered last, and test files stay out."""
        positives = (
            "apps/padiem-chat/**",
            "apps/padiem-chat/app/**",
            "apps/padiem-chat/static/**",
        )
        for job, patterns in self.paths.items():
            with self.subTest(job=job):
                if job == "mobile-touch-target-qa":
                    continue
                self.assertIn("!apps/padiem-chat/app/b66_*", patterns)
                self.assertIn("!apps/padiem-chat/static/b66-quote-runtime.js", patterns)
                positive = max(i for i, p in enumerate(patterns) if p in positives)
                # Order matters: an exclusion listed before its positive would
                # be a silent no-op and would re-open the whole lane set.
                self.assertGreater(patterns.index("!apps/padiem-chat/app/b66_*"), positive)
                self.assertGreater(
                    patterns.index("!apps/padiem-chat/static/b66-quote-runtime.js"), positive
                )
                if "apps/padiem-chat/**" in patterns:
                    self.assertIn("!apps/padiem-chat/tests/**", patterns)


class ConsolidatedStaticAudits(unittest.TestCase):
    def test_three_audits_share_one_workflow_run_with_stable_job_ids(self):
        self.assertTrue(STATIC_AUDITS.exists())
        text = STATIC_AUDITS.read_text(encoding="utf-8")
        for job, script in (
            ("dom-sink-audit", ".github/scripts/b62_dom_sink_audit.py"),
            ("static-origin-audit", ".github/scripts/b62_static_origin_audit.py"),
            ("browser-persistence-audit", ".github/scripts/b62_browser_persistence_audit.py"),
        ):
            with self.subTest(job=job):
                self.assertIn(f"\n  {job}:\n", text)
                self.assertIn(f"python {script}", text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertIn("cancel-in-progress: true", text)

    def test_retired_audits_are_gone_and_still_retrigger_on_rollback(self):
        for name in RETIRED_AUDITS:
            with self.subTest(name=name):
                self.assertFalse((FOLDER / name).exists())
                self.assertIn(f".github/workflows/{name}", STATIC_AUDITS.read_text(encoding="utf-8"))

    def test_main_push_verification_is_preserved(self):
        text = STATIC_AUDITS.read_text(encoding="utf-8")
        self.assertIn("  push:\n", text)
        self.assertIn("apps/padiem-chat/static/**", text)


if __name__ == "__main__":
    unittest.main()
