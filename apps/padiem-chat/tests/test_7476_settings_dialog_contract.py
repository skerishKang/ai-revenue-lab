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

from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
THEME_JS = (STATIC / "theme.js").read_text(encoding="utf-8")
PUSH_JS = (STATIC / "claw-push.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
POLISH = parse_rules((STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8"))


def _dialog() -> str:
    start = INDEX.index('<dialog class="settings-dialog"')
    return INDEX[start : INDEX.index("</dialog>", start)]


def test_one_close_control_and_no_done_footer() -> None:
    dialog = _dialog()
    assert dialog.count('type="submit"') == 1
    submit = dialog[dialog.index('type="submit"') - 80 : dialog.index('type="submit"') + 80]
    assert 'id="settingsCloseButton"' in submit
    for gone in ('settings-footer', 'settings-done', 'data-locale-key="done"'):
        assert gone not in dialog


def test_one_big_heading_per_section_and_no_duplicate_admin_title() -> None:
    dialog = _dialog()
    assert '"settings-label"' not in dialog
    assert dialog.count('data-locale-key="admin-settings-title"') == 1
    assert 'data-locale-key="admin-section"' not in dialog
    # Appearance owns the old 화면/테마 pair as one heading.
    assert 'id="appearanceTitle" data-locale-key="appearance"' in dialog
    assert 'data-locale-key="theme"' not in dialog
    for section_id in ("appearanceTitle", "languageTitle", "clawPushTitle", "adminSettingsTitle"):
        assert dialog.count(f'id="{section_id}"') == 1


def test_every_choice_button_wears_the_same_control_class() -> None:
    dialog = _dialog()
    picker = dialog[dialog.index('id="themePicker"') : dialog.index("</section>", dialog.index('id="themePicker"'))]
    assert picker.count("settings-choice theme-option") == 4
    language = dialog[dialog.index('id="languagePicker"') : dialog.index("</section>", dialog.index('id="languagePicker"'))]
    assert language.count("settings-choice language-option") == 2
    # theme.js injects the Glass theme and the Glass sub-options with the same class.
    assert 'button.className="settings-choice theme-option"' in THEME_JS
    assert THEME_JS.count('className="settings-choice glass-variant-option"') == 2

    base = find_rules_with_selector(POLISH, "#settingsDialog .settings-choice")
    assert base, "one choice-control rule must exist"
    assert declaration(base[0], "min-height") == "44px"
    assert declaration(base[0], "border-radius") == "10px"
    selected = find_rules_with_selector(POLISH, '#settingsDialog .settings-choice[aria-pressed="true"]')
    assert selected, "selected choice rule must exist"
    assert declaration(selected[0], "background") == "var(--accent-soft)"
    assert declaration(selected[0], "color") == "var(--accent-strong)"
    assert declaration(selected[0], "font-weight") == "750"


def test_glass_options_are_one_indented_group() -> None:
    rules = find_rules_with_selector(POLISH, "#settingsDialog .glass-variant-control")
    group = [rule for rule in rules if declaration(rule, "margin-left") == "18px"]
    assert group, "the Glass group must be indented under the theme picker"
    assert any("#settingsDialog .glass-shell-control" in rule.selectors for rule in group)
    assert declaration(group[0], "padding-left") == "18px"
    assert declaration(group[0], "border-left") == "2px solid var(--surface-border)"


def test_three_action_levels_and_the_entry_alignment() -> None:
    dialog = _dialog()
    assert 'class="settings-action settings-action-secondary" id="settingsLogoutButton"' in dialog
    assert 'class="settings-action settings-action-secondary settings-link" id="adminHubLink"' in dialog
    assert 'class="settings-action settings-action-primary settings-link" id="settingsAdvancedOpen"' in dialog

    secondary = find_rules_with_selector(POLISH, "#settingsDialog .settings-action-secondary")
    primary = find_rules_with_selector(POLISH, "#settingsDialog .settings-action-primary")
    danger = find_rules_with_selector(POLISH, "#settingsDialog .settings-action-danger")
    assert secondary and primary and danger
    assert declaration(secondary[0], "background") == "var(--card-bg, #fafafa)"
    assert declaration(primary[0], "background") == "var(--primary-bg)"
    assert declaration(primary[0], "border-radius") == "999px"
    assert declaration(danger[0], "color") == "var(--danger, #b3261e)"

    entry = find_rules_with_selector(POLISH, ".settings-advanced-entry")
    assert entry and declaration(entry[0], "padding") == "18px 30px 26px"


def test_edge_blur_wording_is_localized_and_the_old_term_is_gone() -> None:
    assert '"glass-mask-mode": "가장자리 흐림 효과"' in LOCALE
    assert '"glass-mask-mode": "Edge blur effect"' in LOCALE
    assert "외투 마스크" not in LOCALE
    assert "외투 마스크" not in THEME_JS
    assert "Shell mask mode" not in THEME_JS
    assert '"glass-mask-mode"' in THEME_JS


def test_alerts_are_one_switch_and_the_old_sentence_button_is_gone() -> None:
    dialog = _dialog()
    assert 'role="switch"' in dialog
    assert 'aria-checked="false"' in dialog
    assert 'data-locale-key="claw-push-enable"' not in dialog
    assert 'id="clawPushStatus"' in dialog
    assert 'setAttribute("aria-checked"' in PUSH_JS
    assert 'setAttribute("aria-pressed"' not in PUSH_JS
    # Only exceptional answers keep a visible line; on/off is the switch itself.
    assert "const exceptional = state === PUSH_STATE.denied" in PUSH_JS
    # #7485 review: the switch shares the section title line.
    assert 'class="settings-section-head"' in dialog
    head = dialog[dialog.index('class="settings-section-head"'):]
    head = head[: head.index("</div>")]
    assert head.index('id="clawPushTitle"') < head.index('id="clawPushToggle"')
    heading_rule = find_rules_with_selector(POLISH, ".settings-dialog .settings-section-head h3")
    assert heading_rule and declaration(heading_rule[0], "margin") == "0"
