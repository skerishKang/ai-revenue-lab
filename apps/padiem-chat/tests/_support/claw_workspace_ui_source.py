"""Parsed facts for the #2114 Claw workspace UI static contracts.

Raw shipped-source reads live here (reusing claw_static); the test asserts on
named missing-token lists, counts and the existing session-storage guard.
"""
from __future__ import annotations

from _android_handoff_storage_guard import assert_session_storage_is_handoff_only
from _support.claw_static import sheet


def _present(value: str, needles) -> list[str]:
    return [needle for needle in needles if needle in value]


def _missing(value: str, needles) -> list[str]:
    return [needle for needle in needles if needle not in value]


def modal_facts() -> dict:
    html = sheet("index.html")
    app = sheet("app.js")
    line = next(line for line in html.splitlines() if 'id="clawNavButton"' in line)
    return {
        "unexpected": _present(html, ('id="clawDialog"',)) + _present(app, ("clawDialog",)),
        "missing": _missing(html, ('id="clawWorkspace"',)),
        "dialog_attrs": _present(line, ('aria-controls="clawDialog"', 'aria-haspopup="dialog"')),
    }


def shell_state_facts() -> dict:
    nav = sheet("chat-nav-module.js")
    css = sheet("claw-workspace.css")
    return {
        "nav_state_write": 'deps.shell.dataset.state = "claw"' in nav,
        "missing_css": _missing(css, (
            '.app-shell[data-state="claw"] .claw-workspace',
            '.app-shell[data-state="claw"] .conversation',
        )),
        "unexpected_css": _present(css, ('.app-shell[data-state="claw"] .composer-wrap',)),
    }


def composer_facts() -> dict:
    html = sheet("index.html")
    css = sheet("claw-workspace.css")
    intake = sheet("claw-manual-intake.css")
    return {
        "unexpected_markup": _present(html, ('class="claw-intake-hero"', 'id="clawRequestText"')),
        "missing_markup": _missing(html, ('class="claw-mode-bar" id="clawManualForm"',)),
        "missing_css": _missing(css, ('.app-shell[data-state="claw"] .composer textarea',)),
        "workspace_font_16": "font-size: 16px" in css,
        "intake_font_16": "font-size: 16px" in intake,
        "old_small_control": "0.85rem" in intake,
    }


def action_facts() -> dict:
    html = sheet("index.html")
    return {
        "chips_present": 'class="claw-chips"' in html,
        "action_count": html.count("data-claw-action="),
        "aria_pressed": 'aria-pressed="false"' in html,
        "old_grid": "claw-actions-grid" in html,
    }


def result_facts() -> dict:
    html = sheet("index.html")
    css = sheet("claw-workspace.css")
    return {
        "missing_markup": _missing(html, (
            'id="clawResultCard"', 'id="clawResultKind"', 'class="claw-result-body"',
        )),
        "max_height": "max-height: 320px" in css,
    }


def affordance_facts() -> dict:
    html = sheet("index.html")
    return {
        "disabled_action_present": (
            'class="claw-result-action" disabled aria-disabled="true"' in html
        ),
        "old_control_present": "claw-disabled-control" in html,
    }


def nav_facts() -> dict:
    app = sheet("app.js")
    css = sheet("claw-workspace.css")
    return {
        "aria_current_set": 'setAttribute("aria-current"' in app,
        "missing_css": _missing(css, (
            '#clawNavButton[aria-current="page"]', '#newChatButton[aria-current="page"]',
        )),
    }


def touch_facts() -> dict:
    css = sheet("claw-workspace.css")
    return {
        "min_44": "min-height: 44px" in css,
        "min_48": "min-height: 48px" in css,
    }


def single_h1_facts() -> dict:
    html = sheet("index.html")
    return {
        "h1_count": html.count("<h1"),
        "missing_markup": _missing(html, (
            'class="claw-workspace-title" id="clawWorkspaceTitle"',
            'aria-labelledby="clawWorkspaceTitle"',
        )),
    }


def preview_facts() -> dict:
    app = sheet("app.js")
    form = sheet("chat-claw-form-module.js")
    combined = app + form
    assert_session_storage_is_handoff_only(app)
    return {
        "preview_endpoint": "/api/claw/manual-intake/preview" in form,
        "text_content_sink": "clawResultPreview.textContent =" in form,
        "inner_html_present": "clawResultPreview.innerHTML" in combined,
        "forbidden_tokens": _present(app, ("localStorage", "indexedDB", "cookieStore", "caches.open")),
    }
