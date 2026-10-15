"""Claw Focus UI: source-owned workbench design without changing AI/Office authority.

This verifies the scoped presentation contract, first-run entry clarity and
retention of all existing functional controls across PC/mobile breakpoints.
It intentionally tests no model/provider or production API.
"""
from pathlib import Path
import re
from html.parser import HTMLParser

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "claw-focus-layout.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")


class _ClawNodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.by_id = {}
        self.stylesheets = []
        self.locale_keys = {}
        self._element_stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.by_id[attrs["id"]] = (tag, attrs)
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.stylesheets.append(attrs.get("href"))
        if attrs.get("data-locale-key"):
            self.locale_keys.setdefault(attrs["data-locale-key"], 0)
            self.locale_keys[attrs["data-locale-key"]] += 1


def _nodes():
    p = _ClawNodes()
    p.feed(HTML)
    return p


def test_focus_stylesheet_is_last_and_loads_after_complex_claw_layout():
    links = _nodes().stylesheets
    # Keep the final shared six-panel frame after Claw focus and voice CSS.
    # The later voice-composer.css is component-local (#voiceMicButton and
    # .voice-interim-preview), not a Claw layout override.
    focus = links.index("./claw-focus-layout.css")
    trailing = links[focus + 1:]
    assert trailing == ["./voice-composer.css", "./shared-six-panel-frame.css"]
    if trailing:
        voice_css = (STATIC / "voice-composer.css").read_text(encoding="utf-8")
        assert "#voiceMicButton" in voice_css
        assert ".voice-interim-preview" in voice_css
        assert ".claw-workspace" not in voice_css
    assert links.index("./claw-task-hub.css") < links.index("./claw-focus-layout.css")
    assert links.index("./claw-workspace.css") < links.index("./claw-focus-layout.css")
    assert links.index("./b66-quote-runtime.css") < links.index("./claw-focus-layout.css")


def test_claw_only_selectors_keep_shared_first_use_portrait_and_workbench_separation():
    assert '.app-shell[data-state="claw"]' in CSS
    assert '.main-panel::before' in CSS
    assert ':not(:has(.claw-workspace[data-view="general"]' in CSS
    assert 'content: none;' in CSS
    assert '.app-shell[data-state="claw"] .conversation' in CSS
    assert ".composer-wrap" in CSS
    assert '.app-shell[data-state="chat"]' not in CSS
    assert '.app-shell[data-state="home"]' not in CSS
    assert not re.search(r'(^|\n)\s*html\[data-theme="padiem-glass"\]\s+\.main-panel', CSS)


def test_three_workflow_actions_and_approved_model_selection_stay_functional():
    nodes = _nodes().by_id
    for id_ in ("clawExcelStartButton", "clawCompareStartButton",
                "clawDocumentStartButton", "clawWebOfficeDetails",
                "clawVerifiedModelSelect", "clawModelIdInput",
                "messageInput", "sendButton",
                "clawMobileComposerToggle", "clawManualForm", "clawRetryButton"):
        assert id_ in nodes, id_
    assert nodes["clawVerifiedModelSelect"][0] == "select"
    assert nodes["messageInput"][0] == "textarea"
    assert not nodes["clawExcelStartButton"][1].get("disabled")
    assert '#composerForm > .claw-model-choice' in CSS
    assert '#composerForm > .claw-model-advanced' in CSS
    assert '#composerForm > #messageInput' in CSS
    assert '#composerForm > .composer-actions' in CSS
    assert 'data-claw-composer-collapsed="true"' in CSS


def test_first_run_text_invites_freeform_not_only_excel_and_is_localized():
    nodes = _nodes()
    assert nodes.locale_keys.get("claw-focus-heading") == 1
    assert nodes.locale_keys.get("claw-focus-description") == 1
    assert "입력창에 직접 요청하세요" in HTML
    assert "Reading or editing files needs separate approval." in LOCALE
    ko, en = LOCALE.split("en: {", 1)
    for key in ("claw-focus-heading", "claw-focus-description"):
        assert f'"{key}"' in ko
        assert f'"{key}"' in en


def test_fewer_busy_controls_without_hiding_authorized_workflows():
    assert '.claw-task-option-primary' in CSS
    assert 'min-height: 105px' in CSS
    assert '.conversation:has(#messageList:not([hidden]) .message) #clawTaskHub' in CSS
    assert '.conversation:has(#clawRequestEcho:not([hidden])) #clawTaskHub' in CSS
    # Only already disabled navigation disappears; enabled routes still visible.
    assert '#workspaceNav .side-item:disabled' in CSS
    assert '#workspaceNav .side-item:not(:disabled)' not in CSS
    # Backend and P01 workflow remain unmodified by this stylesheet.
    assert 'fetch(' not in CSS
    assert 'data-claw-state=' not in CSS


def test_responsive_layout_and_keyboard_focus_preserve_mobile_sheet_behavior():
    for threshold in (1100, 920, 760, 600):
        assert f"@media (max-width: {threshold}px)" in CSS
    assert '#clawMobileComposerToggle' in CSS
    assert 'min-height: 44px' in CSS
    assert ':focus-visible' in CSS
    assert 'width: calc(100vw - 24px)' in CSS
    assert 'max-height: calc(100dvh - 92px)' in CSS
    assert "--claw-composer-clearance" in CSS
    assert 'display: none' not in CSS.split('#composerForm > .claw-model-choice', 1)[1].split('{', 1)[1].split('}', 1)[0]
