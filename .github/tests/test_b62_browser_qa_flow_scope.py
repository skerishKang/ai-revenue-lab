"""#8729: single-flow Python changes select only their own QA lanes.

Unknown or mixed files keep the fail-closed full lane set, and a missing or
unproven file list is never narrowed.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'b62_qa_flow_scope', ROOT / '.github/scripts/b62_browser_qa_path_plan.py'
)
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)


def lanes(paths, statuses=None, count=None):
    statuses = statuses if statuses is not None else {p: 'modified' for p in paths}
    count = len(paths) if count is None else count
    chosen = planner.choose_lanes(set(paths), planner.load_paths(),
                                  statuses=statuses, expected_files=count)
    return {job for job, ok in chosen.items() if ok}


class FlowScopeTests(unittest.TestCase):
    def test_pc_helper_only_change_runs_no_browser_lane(self):
        self.assertEqual(lanes(['apps/padiem-chat/app/pc_helper_registration.py']), set())

    def test_project_only_change_runs_project_lanes(self):
        self.assertEqual(
            lanes(['apps/padiem-chat/app/project_delete_routes.py']),
            planner.FLOW_ONLY_PROJECT,
        )

    def test_conversation_only_change_runs_conversation_lanes(self):
        self.assertEqual(
            lanes(['apps/padiem-chat/app/conversation_export_routes.py']),
            planner.FLOW_ONLY_CONVERSATION,
        )

    def test_tests_and_evidence_files_do_not_block_flow_narrowing(self):
        paths = [
            'apps/padiem-chat/app/pc_helper_registration.py',
            'apps/padiem-chat/tests/test_8359_maintenance_host.py',
            'padiem-reports/2026-11-25/pc-helper/report.json',
        ]
        self.assertEqual(lanes(paths), set())

    def test_unknown_or_mixed_change_keeps_full_lane_set(self):
        self.assertEqual(
            len(lanes(['apps/padiem-chat/app/pc_helper_registration.py',
                       'apps/padiem-chat/static/app.js'])),
            16,
        )
        self.assertEqual(
            len(lanes(['apps/padiem-chat/app/chat_routes.py'])), 16)

    def test_unproven_status_or_count_keeps_full_lane_set(self):
        path = ['apps/padiem-chat/app/pc_helper_registration.py']
        self.assertEqual(len(lanes(path, count=2)), 16)
        self.assertEqual(len(lanes(path, statuses={path[0]: 'renamed'})), 16)
        self.assertEqual(len(lanes(path, statuses={})), 16)
        self.assertEqual(len(planner.choose_lanes(None, planner.load_paths()).keys()), 17)
        self.assertTrue(all(planner.choose_lanes(None, planner.load_paths()).values()))


if __name__ == '__main__':
    unittest.main()
