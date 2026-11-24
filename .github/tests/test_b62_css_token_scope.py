"""#8688: CSS + colour-token tests + reports evidence is a proven narrow change.

The same predicate drives the browser QA planner and the B62 Chat CI classifier.
A JS line, a QA-referenced helper, a renamed/removed file, a truncated listing
or a missing count must still run every lane.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
SPEC = importlib.util.spec_from_file_location(
    "b62_css_token_scope", SCRIPTS / "b62_css_token_scope.py"
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SPEC_PLAN = importlib.util.spec_from_file_location(
    "b62_qa_plan_css", SCRIPTS / "b62_browser_qa_path_plan.py"
)
plan = importlib.util.module_from_spec(SPEC_PLAN)
SPEC_PLAN.loader.exec_module(plan)

# Exact shape of PR #8688: two stylesheets, three token tests, fourteen
# padiem-reports evidence files.
CSS = (
    "apps/padiem-chat/static/answer-actions.css",
    "apps/padiem-chat/static/padiem-tokens.css",
)
TESTS = (
    "apps/padiem-chat/tests/_support/calendar_palette.py",
    "apps/padiem-chat/tests/test_261109_primary_tokens_7187.py",
    "apps/padiem-chat/tests/test_261124_answer_actions_tokens_7811.py",
)
EVIDENCE = (
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/dark__actions__after.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/dark__actions__before.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/light__actions__after.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/light__actions__before.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/padiem-glass__actions__after.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/padiem-glass__actions__before.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/tamper_clean.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/captures/tamper_mutated.png",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/compare_report.json",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/computed_report.json",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/control_report.json",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/manifest.json",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/scope_report.json",
    "padiem-reports/2026-11-24/7811-answer-actions-tokens/tamper_report.json",
)
CHANGED = CSS + TESTS + EVIDENCE


def statuses(paths, status="modified"):
    return {p: status for p in paths}


class CssTokenScopeTests(unittest.TestCase):
    def test_8688_shape_selects_only_the_ui_smoke_lanes(self):
        changed = set(CHANGED)
        proof = module.css_token_proof([{"filename": p, "status": "modified"} for p in CHANGED])
        self.assertIsNotNone(proof)
        self.assertTrue(module.is_css_token_evidence_change(
            proof[0], proof[1], expected_files=proof[2]
        ))
        chosen = plan.choose_lanes(changed, plan.load_paths(),
                                   statuses=statuses(changed), expected_files=len(changed))
        selected = {job for job, enabled in chosen.items() if enabled}
        self.assertEqual(selected, set(plan.UI_ONLY_CSS_SMOKE_LANES))
        self.assertEqual(module.token_test_modules(changed), (
            "tests/test_261109_primary_tokens_7187.py",
            "tests/test_261124_answer_actions_tokens_7811.py",
        ))

    def test_css_only_keeps_the_existing_static_only_contract(self):
        self.assertFalse(module.is_css_token_evidence_change(
            set(CSS), statuses(CSS), expected_files=len(CSS)
        ))

    def test_js_mixed_in_still_runs_every_lane(self):
        changed = set(CHANGED) | {"apps/padiem-chat/static/app.js"}
        self.assertFalse(module.is_css_token_evidence_change(
            changed, statuses(changed), expected_files=len(changed)
        ))
        chosen = plan.choose_lanes(changed, plan.load_paths(),
                                   statuses=statuses(changed), expected_files=len(changed))
        self.assertTrue(all(chosen.values()))

    def test_unknown_status_truncated_and_renamed_still_run_every_lane(self):
        changed = set(CHANGED)
        cases = (
            (changed, statuses(changed), len(changed) + 1),
            (changed, statuses(changed, "renamed"), len(changed)),
            (changed, {p: statuses(changed)[p] for p in changed if p != CSS[0]}, len(changed)),
            (changed, None, len(changed)),
        )
        for paths, st, count in cases:
            with self.subTest(status=str(st)[:24], count=count):
                self.assertFalse(module.is_css_token_evidence_change(
                    paths, st, expected_files=count
                ))
                chosen = plan.choose_lanes(paths, plan.load_paths(),
                                           statuses=st, expected_files=count)
                self.assertTrue(all(chosen.values()))

    def test_excluded_css_still_runs_every_lane(self):
        changed = set(CHANGED) | {"apps/padiem-chat/static/b66-quote-runtime.css"}
        self.assertFalse(module.is_css_token_evidence_change(
            changed, statuses(changed), expected_files=len(changed)
        ))

    def test_qa_referenced_helper_is_not_allow_listed(self):
        changed = set(CHANGED)
        with patch.object(module, "BROWSER_QA_REFERENCED_FILES",
                          frozenset({"calendar_palette.py"})):
            self.assertFalse(module.is_css_token_evidence_change(
                changed, statuses(changed), expected_files=len(changed)
            ))

    def test_browser_qa_scripts_do_not_reference_allow_listed_files(self):
        """The grep proof behind BROWSER_QA_REFERENCED_FILES stays honest."""
        ignored = {
            "b62_css_token_scope.py",
            "b62_browser_qa_path_plan.py",
            "b62_ci_impact_scope_3989.py",
            "test_b62_css_token_scope.py",
        }
        script_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(SCRIPTS.glob("b62*.py")) if path.name not in ignored
        )
        names = {Path(p).stem for p in TESTS}
        names |= {p.stem for p in (ROOT / "apps/padiem-chat/tests").glob("test_*_tokens_*.py")}
        names |= {p.stem for p in (ROOT / "apps/padiem-chat/tests").glob("test_*_7187.py")}
        names |= {p.stem for p in (ROOT / "apps/padiem-chat/tests").glob("test_*_7811.py")}
        referenced = {name for name in names if name in script_text}
        self.assertEqual(referenced, set(module.BROWSER_QA_REFERENCED_FILES | frozenset()), referenced)


if __name__ == "__main__":
    unittest.main()
