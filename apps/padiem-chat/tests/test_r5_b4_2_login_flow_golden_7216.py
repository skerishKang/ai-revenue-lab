"""#7216 R5 B4-2 — login-flow golden captured from clean origin/main.

The observation is produced by the same Node VM harness the step4 auth contract
uses; ``_r5_b4_2_login_golden`` only parameterises the static tree. The snapshot
was generated from origin/main ``043a31450`` (before this branch's module split)
and covers login success/failure, logout, session expiry and dialog open/close.
This test proves the refactor kept request addresses, methods, body keys and
screen copy byte-identical without touching a real account.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.r5_browser_golden_source import app_context_js, app_js, login_golden_json, strict_deps_js

import json
from pathlib import Path

from _r5_b4_2_login_golden import login_golden

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SNAPSHOT = json.loads(
    login_golden_json()
)


def test_login_flow_golden_matches_main_snapshot() -> None:
    assert SNAPSHOT["source"].startswith("origin/main ")
    assert len(SNAPSHOT["paths"]) == 5
    assert login_golden(STATIC) == SNAPSHOT["observation"]


def test_branches_wire_the_moved_login_listeners() -> None:
    app = app_js()
    for call in (
        "authModule().wireSessionRefresh();",
        "authModule().wireLoginButton();",
        "authModule().wireLogoutButton();",
        "loginDialogModule().wireGuestLogin();",
        "loginDialogModule().wireDialogClose();",
        "loginDialogModule().wireGoogleLogin();",
        "loginDialogModule().wireProfileToggle();",
        "loginDialogModule().wireProfileSettings();",
        "loginDialogModule().wireProfileDismiss();",
    ):
        assert call in app, call
