"""#4459 proven CSS-only UI scope for the B62 browser QA lanes.

A CSS-only change (added/modified B62 Chat stylesheets with exact
status/count proof) cannot alter Python/Worker/API/auth logic, models, DB,
secrets or file writes, so the planner narrows the 16 browser QA lanes to
the presentation smoke set while every other lane set stays exactly as
before. Anything unproven (HTML/JS/Python/mixed/removed/renamed/unknown/
truncated/oversized, or missing statuses) keeps the full lane set.

Security and required checks are never narrowed here: the B62 static-UI
fast checks, the DOM/origin/persistence audits and the PR preview glass QA
still run in their own workflows for every static change.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
WORKFLOW = ROOT / ".github/workflows/b62-browser-qa-unified.yml"
CHAT = ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
AUDITS = ROOT / ".github/workflows/b62-static-audits.yml"
spec = importlib.util.spec_from_file_location("b62_ui_only_css_scope_4459", SCRIPT)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)

CSS_A = "apps/padiem-chat/static/padiem-first-use.css"
CSS_B = "apps/padiem-chat/static/padiem-glass.css"
CSS_C = "apps/padiem-chat/static/sidebar-utility.css"

SMOKE = {
    "accessibility-browser-qa",
    "auth-history-browser-qa",
    "browser-qa",
    "document-browser-qa",
    "mobile-touch-target-qa",
    "project-files-browser-qa",
}


def lanes(paths, statuses=None, expected_files=None):
    return {
        job
        for job, enabled in planner.choose_lanes(
            set(paths), planner.load_paths(),
            statuses=statuses, expected_files=expected_files,
        ).items()
        if enabled
    }


def proven(*paths, status="modified"):
    files = set(paths)
    return files, {path: status for path in files}, len(files)


class UiOnlyCssScopeContract(unittest.TestCase):
    def test_smoke_set_is_exactly_the_six_presentation_lanes(self):
        self.assertEqual(planner.UI_ONLY_CSS_SMOKE_LANES, frozenset(SMOKE))
        self.assertEqual(len(planner.load_paths()), 16)

    def test_single_stylesheet_selects_only_the_smoke_set(self):
        for css in (CSS_A, CSS_B, CSS_C):
            with self.subTest(css=css):
                paths, statuses, count = proven(css)
                self.assertEqual(lanes(paths, statuses, count), SMOKE)
                paths, statuses, count = proven(css, status="added")
                self.assertEqual(lanes(paths, statuses, count), SMOKE)

    def test_bounded_stylesheet_group_selects_only_the_smoke_set(self):
        paths, statuses, count = proven(CSS_A, CSS_B, CSS_C)
        self.assertEqual(lanes(paths, statuses, count), SMOKE)

    def test_smoke_keeps_the_core_visual_job_with_full_tail(self):
        paths, statuses, count = proven(CSS_B)
        self.assertIn("browser-qa", lanes(paths, statuses, count))
        # A generic stylesheet is not a proven Glass leaf, so the visual tail
        # still runs inside the retained browser-qa job.
        self.assertTrue(planner.require_glass_visual_tail(
            paths, statuses, expected_files=count))

    def test_isolated_surface_stylesheets_keep_their_pinned_sets(self):
        # B66-only and Claw CSS isolations own their boundaries; the generic
        # CSS smoke must never move them. Status proof does not change the
        # isolated outcomes: B66 stays at zero lanes, Claw stays at its five.
        b66 = "apps/padiem-chat/static/b66-quote-runtime.css"
        claw = "apps/padiem-chat/static/claw-manual-intake.css"
        claw_keep = {
            "accessibility-browser-qa",
            "auth-history-browser-qa",
            "browser-qa",
            "document-browser-qa",
            "project-files-browser-qa",
        }
        self.assertEqual(lanes({b66}), set())
        self.assertEqual(lanes({claw}), claw_keep)
        for paths, statuses in (
            ({b66}, {b66: "modified"}),
            ({claw}, {claw: "modified"}),
        ):
            with self.subTest(paths=sorted(paths)):
                self.assertEqual(
                    lanes(paths, statuses, len(paths)), lanes(paths))
        # An isolated B66 sheet mixed with a generic sheet keeps the full
        # lane set: after the B66 removal the proven-count guard no longer
        # matches, so the change fails closed to historical routing. The safe
        # direction is more coverage, never less.
        mixed = {b66, CSS_A}
        self.assertEqual(
            lanes(mixed, {path: "modified" for path in mixed}, len(mixed)),
            lanes(mixed),
        )
        self.assertEqual(len(lanes(mixed)), 16)

    def test_html_js_python_and_mixed_changes_keep_every_lane(self):
        hazards = (
            "apps/padiem-chat/static/index.html",
            "apps/padiem-chat/static/app.js",
            "apps/padiem-chat/static/locale.js",
            "apps/padiem-chat/app/app_factory.py",
            "apps/padiem-chat/worker.py",
            "apps/padiem-chat/tests/test_projects.py",
            "packages/padiem-ai-core/padiem_ai_core/router.py",
            ".github/scripts/b62_projects_browser_qa.py",
        )
        for hazard in hazards:
            with self.subTest(hazard=hazard):
                paths = {CSS_A, hazard}
                statuses = {path: "modified" for path in paths}
                self.assertEqual(
                    lanes(paths, statuses, len(paths)),
                    set(planner.load_paths()),
                )
        # Auth-adjacent stylesheets get no content carve-out: they run the
        # same smoke set, never fewer lanes.
        auth_css = "apps/padiem-chat/static/history.css"
        paths, statuses, count = proven(auth_css)
        self.assertEqual(lanes(paths, statuses, count), SMOKE)

    def test_unproven_status_count_and_shape_keep_every_lane(self):
        full = set(planner.load_paths())
        cases = [
            ({CSS_A}, {CSS_A: "removed"}, 1),
            ({CSS_A}, {CSS_A: "renamed"}, 1),
            ({CSS_A}, {CSS_A: ""}, 1),
            ({CSS_A}, {}, 1),
            ({CSS_A}, {CSS_A: "modified", "other.css": "modified"}, 1),
            ({CSS_A}, {CSS_A: "modified"}, 2),
            ({CSS_A}, {CSS_A: "modified"}, None),
            ({CSS_A}, {CSS_A: "modified"}, "1"),
            ({CSS_A}, None, 1),
        ]
        for changed, statuses, count in cases:
            with self.subTest(changed=sorted(changed), statuses=statuses, count=count):
                self.assertEqual(lanes(changed, statuses, count), full)
        # Oversized restyles and non-stylesheet paths fail closed to the
        # historical path-only routing: statuses add narrowing only when the
        # CSS-only change is proven, never otherwise.
        many = {f"apps/padiem-chat/static/restyle-{index}.css" for index in range(11)}
        self.assertEqual(
            lanes(many, {path: "modified" for path in many}, len(many)),
            lanes(many),
        )
        for bad in (
            "apps/padiem-chat/static/../worker.py",
            "apps/padiem-chat/static\\padiem-glass.css",
            "apps/padiem-chat/static/theme.js.css.backup",
            "apps/padiem-chat/static/image.png",
            "docs/operations/changelog.md",
        ):
            with self.subTest(bad=bad):
                self.assertFalse(
                    planner.is_css_only_ui_change({bad}, {bad: "modified"},
                                                  expected_files=1))
                self.assertEqual(lanes({bad}, {bad: "modified"}, 1), lanes({bad}))
        self.assertTrue(all(planner.choose_lanes(None, planner.load_paths()).values()))
        self.assertFalse(any(
            planner.choose_lanes(set(), planner.load_paths()).values()))

    def test_missing_statuses_preserve_historical_path_only_routing(self):
        # Offline callers without status proof keep the previous broad routing,
        # so no existing path-only expectation moves.
        self.assertEqual(len(lanes({CSS_A})), 16)
        self.assertEqual(len(lanes({"apps/padiem-chat/static/app.js"})), 15)

    def test_planner_and_manifest_changes_still_fail_open_to_all(self):
        for filename in planner.PLAN_FILES:
            with self.subTest(filename=filename):
                statuses = {filename: "modified"}
                self.assertTrue(all(
                    planner.choose_lanes({filename}, planner.load_paths(),
                                         statuses=statuses,
                                         expected_files=1).values()))

    def test_live_dispatcher_reports_the_smoke_set_for_css_only(self):
        event = {"pull_request": {"number": 4459, "changed_files": 1}}
        api_rows = [{"filename": CSS_A, "status": "modified"}]
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            event_file = folder / "event.json"
            output_file = folder / "output.txt"
            event_file.write_text(json.dumps(event), encoding="utf-8")
            output_file.write_text("", encoding="utf-8")
            env = {
                "GITHUB_EVENT_NAME": "pull_request",
                "GITHUB_EVENT_PATH": str(event_file),
                "GITHUB_OUTPUT": str(output_file),
                "GITHUB_API_URL": "https://api.github.com",
                "GITHUB_REPOSITORY": "skerishKang/ai-revenue-lab",
                "GITHUB_TOKEN": "fake-test-token",
            }
            with patch.dict(os.environ, env):
                with patch.object(planner, "urlopen", return_value=io.BytesIO(
                    json.dumps(api_rows).encode("utf-8")
                )):
                    self.assertEqual(planner.main(), 0)
            results = dict(
                line.split("=", 1)
                for line in output_file.read_text(encoding="utf-8").splitlines()
            )
        self.assertEqual(results["glass_visual_tail_required"], "true")
        running = {key for key, value in results.items() if value == "true"}
        skipped = {key for key, value in results.items() if value == "false"}
        self.assertEqual(
            {name.replace("_", "-") for name in running} - {"glass-visual-tail-required"},
            SMOKE,
        )
        self.assertEqual(len(running) + len(skipped), 17)

    def test_security_and_required_gates_stay_triggered(self):
        master = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("test_4459_b62_ui_only_css_scope.py", master)
        # Every original lane job keeps its name and plan gate: skipped lanes
        # report Skipped, never indefinite Pending.
        for job in planner.load_paths():
            self.assertIn("\n  " + job + ":\n", master)
            self.assertIn("needs.plan.outputs." + job.replace("-", "_"), master)
        # The static-UI fast checks and the three security audits are untouched
        # by this planner-only change.
        chat = CHAT.read_text(encoding="utf-8")
        self.assertIn("name: B62 static UI fast checks", chat)
        self.assertIn("b62_dom_sink_audit.py", chat)
        self.assertIn("b62_static_origin_audit.py", chat)
        self.assertIn("b62_browser_persistence_audit.py", chat)
        audits = AUDITS.read_text(encoding="utf-8")
        self.assertIn("'apps/padiem-chat/static/**'", audits)


if __name__ == "__main__":
    unittest.main()
