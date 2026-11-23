"""#7476 2번 범위: the settings dialog joins the advanced-settings system.

Pins items 1·3·5·6·8·9·10·12·13:
* one close control (×), no Done footer;
* one big heading per section, no duplicate admin title;
* one settings-choice pill for theme / Glass background / edge blur / language;
* three action levels, with logout as secondary;
* the advanced-settings entry lines up with the section content;
* the edge-blur wording in both locales;
* one on/off switch for alerts (aria-checked), wired to the existing toggle.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from _r5_auth_module_harness import observations as auth_observations
from css_rules import declaration, find_rules_with_selector

# #8060 51차: 원문 읽기는 _support(settings_dialog_source)가 담당하고 시험은
# 파싱된 HTML 요소·CSS 선언·토큰 값·로케일 맵과 실행 관찰 값으로 단언한다.
from _support.settings_dialog_source import (  # noqa: E402
    by_id,
    by_locale_key,
    dialog_elements,
    index_elements,
    locale_map,
    settings_rules,
    theme_class_assignments,
    theme_strings,
    token_value,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


_PUSH_SWITCH_NODE = r"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
function makeElement(id) {
  const attributes = new Map();
  const listeners = new Map();
  return {
    id, hidden: false, disabled: false, textContent: "", dataset: {},
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
    removeAttribute(name) { attributes.delete(name); },
    addEventListener(type, handler) { listeners.set(type, handler); },
    click() { const handler = listeners.get("click"); return handler ? handler() : undefined; },
  };
}
const elements = {
  clawPushSetting: makeElement("clawPushSetting"),
  clawPushToggle: makeElement("clawPushToggle"),
  clawPushStatus: makeElement("clawPushStatus"),
};
const context = {
  console, window: {}, navigator: {}, setTimeout, clearTimeout,
  document: { readyState: "loading", getElementById: (id) => elements[id] || null,
    addEventListener() {} },
};
vm.createContext(context);
vm.runInContext(source, context, { filename: "claw-push.js" });
const seen = {};
for (const state of ["on", "off", "denied", "unsupported", "error", "unconfigured"]) {
  context.renderPushToggle(state);
  seen[state] = {
    settingHidden: elements.clawPushSetting.hidden,
    checked: elements.clawPushToggle.getAttribute("aria-checked"),
    pressed: elements.clawPushToggle.getAttribute("aria-pressed"),
    label: elements.clawPushToggle.getAttribute("aria-label"),
    disabled: elements.clawPushToggle.disabled,
    status: elements.clawPushStatus.textContent,
    statusHidden: elements.clawPushStatus.hidden,
  };
}
process.stdout.write(JSON.stringify(seen));
"""


def _push_switch() -> dict:
    """claw-push.js를 실행해 스위치가 실제로 어떻게 그려지는지 본다."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the alerts switch harness")
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "push_switch.js"
        script.write_text(_PUSH_SWITCH_NODE, encoding="utf-8")
        completed = subprocess.run(
            [node, str(script), str(STATIC / "claw-push.js")],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_one_close_control_and_no_done_footer() -> None:
    elements = dialog_elements()
    submit = [el for el in elements if el.attrs.get("type") == "submit"]
    assert len(submit) == 1
    assert submit[0].attrs.get("id") == "settingsCloseButton"
    for gone in ("settings-footer", "settings-done"):
        assert not [
            el for el in elements
            if el.attrs.get("id") == gone or gone in (el.attrs.get("class") or "").split()
        ]
    assert not by_locale_key(elements, "done")


def test_one_big_heading_per_section_and_no_duplicate_admin_title() -> None:
    elements = dialog_elements()
    assert not by_locale_key(elements, "settings-label")
    assert len(by_locale_key(elements, "admin-settings-title")) == 1
    assert not by_locale_key(elements, "admin-section")
    # Appearance owns the old 화면/테마 pair as one heading.
    appearance = by_id(elements, "appearanceTitle")
    assert len(appearance) == 1 and appearance[0].attrs.get("data-locale-key") == "appearance"
    assert not by_locale_key(elements, "theme")
    for section_id in ("appearanceTitle", "languageTitle", "clawPushTitle", "adminSettingsTitle"):
        assert len(by_id(elements, section_id)) == 1


def test_every_choice_button_wears_the_same_control_class() -> None:
    elements = dialog_elements()
    picker = by_id(elements, "themePicker")[0]
    assert len([
        el for el in picker.children
        if el.has_class("settings-choice") and el.has_class("theme-option")
    ]) == 4
    language = by_id(elements, "languagePicker")[0]
    assert len([
        el for el in language.children
        if el.has_class("settings-choice") and el.has_class("language-option")
    ]) == 2
    # theme.js injects the Glass theme and the Glass sub-options with the same class.
    classes = theme_class_assignments()
    assert "settings-choice theme-option" in classes
    assert classes.count("settings-choice glass-variant-option") == 2

    rules = settings_rules()
    base = find_rules_with_selector(rules, "#settingsDialog .settings-choice")
    assert base, "one choice-control rule must exist"
    assert declaration(base[0], "min-height") == "44px"
    # #7187 반경 스케일(261115): the sheet names the token; the token file pins
    # the value, so the painted radius is still 10px.
    assert declaration(base[0], "border-radius") == "var(--radius-sm)"
    assert token_value("--radius-sm") == "10px"
    selected = find_rules_with_selector(rules, '#settingsDialog .settings-choice[aria-pressed="true"]')
    assert selected, "selected choice rule must exist"
    assert declaration(selected[0], "background") == "var(--accent-soft)"
    assert declaration(selected[0], "color") == "var(--accent-strong)"
    assert declaration(selected[0], "font-weight") == "750"


def test_glass_options_are_one_indented_group() -> None:
    rules = find_rules_with_selector(settings_rules(), "#settingsDialog .glass-variant-control")
    group = [rule for rule in rules if declaration(rule, "margin-left") == "18px"]
    assert group, "the Glass group must be indented under the theme picker"
    assert any("#settingsDialog .glass-shell-control" in rule.selectors for rule in group)
    assert declaration(group[0], "padding-left") == "18px"
    assert declaration(group[0], "border-left") == "2px solid var(--surface-border)"


def test_three_action_levels_and_the_entry_alignment() -> None:
    elements = dialog_elements()
    for element_id, expected_class in (
        ("settingsLogoutButton", "settings-action settings-action-secondary"),
        ("adminHubLink", "settings-action settings-action-secondary settings-link"),
        ("settingsAdvancedOpen", "settings-action settings-action-primary settings-link"),
    ):
        found = by_id(elements, element_id)
        assert len(found) == 1 and found[0].attrs.get("class") == expected_class

    rules = settings_rules()
    secondary = find_rules_with_selector(rules, "#settingsDialog .settings-action-secondary")
    primary = find_rules_with_selector(rules, "#settingsDialog .settings-action-primary")
    danger = find_rules_with_selector(rules, "#settingsDialog .settings-action-danger")
    assert secondary and primary and danger
    assert declaration(secondary[0], "background") == "var(--card-bg, var(--settings-choice-fallback))"
    assert token_value("--settings-choice-fallback") == "#fafafa"
    assert declaration(primary[0], "background") == "var(--primary-bg)"
    assert declaration(primary[0], "border-radius") == "var(--radius-pill)"
    assert token_value("--radius-pill") == "999px"
    assert declaration(danger[0], "color") == "var(--danger)"

    entry = find_rules_with_selector(rules, ".settings-advanced-entry")
    assert entry and declaration(entry[0], "padding") == "18px 30px 26px"


def test_edge_blur_wording_is_localized_and_the_old_term_is_gone() -> None:
    assert locale_map("ko")["glass-mask-mode"] == "가장자리 흐림 효과"
    assert locale_map("en")["glass-mask-mode"] == "Edge blur effect"
    for lang in ("ko", "en"):
        for key, value in locale_map(lang).items():
            assert "외투 마스크" not in key and "외투 마스크" not in value
    strings = theme_strings()
    assert not any("외투 마스크" in value for value in strings)
    assert not any("Shell mask mode" in value for value in strings)
    assert "glass-mask-mode" in strings


def test_alerts_are_one_switch_and_the_old_sentence_button_is_gone() -> None:
    elements = dialog_elements()
    assert [el for el in elements if el.attrs.get("role") == "switch"]
    assert [el for el in elements if el.attrs.get("aria-checked") == "false"]
    assert not by_locale_key(elements, "claw-push-enable")
    assert by_id(elements, "clawPushStatus")
    # R2(#7186): the switch state is observed by executing claw-push.js, not by
    # reading its source. on/off write aria-checked only; the old aria-pressed
    # sentence button never comes back; only an exceptional answer keeps a line.
    seen = _push_switch()
    assert seen["on"]["checked"] == "true" and seen["on"]["pressed"] is None
    assert seen["off"]["checked"] == "false" and seen["off"]["pressed"] is None
    for state in ("on", "off"):
        assert seen[state]["statusHidden"] is True and seen[state]["status"] == ""
        assert seen[state]["label"]
    for state in ("denied", "unsupported", "error"):
        assert seen[state]["statusHidden"] is False and seen[state]["status"] != ""
    assert seen["unsupported"]["disabled"] is True and seen["on"]["disabled"] is False
    # No VAPID authority on this deployment: the section offers nothing.
    assert seen["unconfigured"]["settingHidden"] is True
    # #7485 review: the switch shares the section title line.
    heads = [el for el in elements if el.has_class("settings-section-head")]
    assert heads
    title = by_id(heads[0].children, "clawPushTitle")
    toggle = by_id(heads[0].children, "clawPushToggle")
    assert len(title) == 1 and len(toggle) == 1
    assert title[0].order < toggle[0].order
    heading_rule = find_rules_with_selector(settings_rules(), ".settings-dialog .settings-section-head h3")
    assert heading_rule and declaration(heading_rule[0], "margin") == "0"


def test_account_section_shows_the_session_email_and_logout_only() -> None:
    elements = dialog_elements()
    section = by_id(elements, "accountSettingsSection")
    assert len(section) == 1
    assert section[0].attrs.get("aria-labelledby") == "accountSettingsTitle"
    assert "hidden" in section[0].attrs
    title = by_id(elements, "accountSettingsTitle")
    assert len(title) == 1
    assert title[0].attrs.get("data-locale-key") == "account-section" and "계정" in title[0].text
    email = by_id(elements, "settingsAccountEmail")
    assert len(email) == 1
    assert email[0].has_class("settings-account-email") and "hidden" in email[0].attrs
    logout = by_id(elements, "settingsLogoutButton")
    assert len(logout) == 1
    assert logout[0].attrs.get("class") == "settings-action settings-action-secondary"
    # Risky operations stay on the advanced page (item 2 keeps them there).
    index = index_elements()
    for risky in ('passwordChangeOpen', 'accountDeleteOpen', 'accountSharedDeleteOpen'):
        assert not [
            el for el in elements
            if el.attrs.get("id") == risky or risky in (el.attrs.get("class") or "").split()
        ]
        assert by_id(index, risky)

    # R2(#7186): the section projection is observed by executing
    # chat-auth-module.js with a shipped session, not by reading its source.
    # The email is the session's own value (no request of its own) and the
    # whole section follows sign-in; the browser contract
    # (test_7476_settings_account_section_browser.py) covers the painted text.
    seen = auth_observations()["states"]
    assert seen["signed_in"]["settingsHidden"] is False
    assert seen["signed_in"]["settingsEmail"] == "member@example.com"
    assert seen["signed_in"]["settingsEmailHidden"] is False
    for state in ("guest", "expired", "stale_signed_in"):
        assert seen[state]["settingsHidden"] is True
        assert seen[state]["settingsEmailHidden"] is True

    email_rule = find_rules_with_selector(settings_rules(), ".settings-dialog .settings-account-email")
    assert email_rule and declaration(email_rule[0], "font-size") == "14px"
