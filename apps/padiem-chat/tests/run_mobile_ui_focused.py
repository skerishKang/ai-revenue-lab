"""Run only existing mobile composer and computer-connection UI contracts.

Usage: python tests/run_mobile_ui_focused.py [--collect-only]
This is an opt-in local selection; required CI and full legacy suites stay intact.
"""
from __future__ import annotations
import os
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
FOCUSED = (
    "test_4139_claw_device_manager_browser.py::test_device_list_choice_refresh_and_approval_boundary",
    "test_4139_claw_device_manager_browser.py::test_authoritative_empty_directory_and_logged_out_are_distinct",
    "test_4139_claw_device_guidance_browser.py::test_guidance_visible_before_connection_without_any_read",
    "test_4139_claw_device_guidance_browser.py::test_guidance_adds_no_second_directory_read",
    "test_4139_claw_pc_touch_accessibility_browser.py::test_directory_controls_meet_the_44px_floor",
    "test_4139_claw_pc_touch_accessibility_browser.py::test_measured_hit_areas_are_at_least_44px",
    "test_4139_claw_shared_home_parity.py::test_first_use_claw_retains_chat_alignment_and_input_tools",
    "test_4139_claw_shared_home_parity.py::test_claw_connection_chips_keep_canonical_authority_and_do_not_forge_disconnect",
    "test_b62_1818_interaction_polish.py::test_interaction_polish_is_presentation_only_and_public_safe",
)

def main() -> int:
    for node in FOCUSED:
        filename, name = node.split("::", 1)
        path = TESTS / filename
        if not path.is_file() or f"def {name}(" not in path.read_text(encoding="utf-8"):
            print(f"Missing test node: {node}", file=sys.stderr)
            return 2
    args = [sys.executable, "-m", "pytest", "-q", *FOCUSED, *sys.argv[1:]]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TESTS.parent) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.call(args, cwd=TESTS, env=env)

if __name__ == "__main__":
    raise SystemExit(main())

