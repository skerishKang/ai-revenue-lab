"""Focused #4890 follow-up: one-cell project/history controls and equal home cards."""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "sidebar-section-collapse.js").read_text(encoding="utf-8")
CSS = (STATIC / "sidebar-section-polish.css").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def test_project_and_recent_have_independent_explicit_collapse_controls():
    for section, button, target in (
        ("projectsSection", "projectsToggleButton", "projectsList projectsEmpty"),
        ("historySection", "historyToggleButton", "historyList historyEmpty"),
    ):
        assert f'id="{section}"' in HTML
        match = re.search(r'<button[^>]+id="' + button + r'"[^>]*>', HTML)
        assert match is not None
        assert f'aria-controls="{target}"' in match.group()
        assert 'aria-expanded="true"' in match.group()
        assert f'"{button}"' in JS
        assert f'"{section}"' in JS
    assert 'id="projectCreateButton"' in HTML


def test_collapse_does_not_modify_auth_or_project_conversation_api_routes():
    assert "fetch(" not in JS
    assert "innerHTML" not in JS
    assert "classList.toggle" in JS
    assert "aria-expanded" in JS
    assert "localStorage" not in JS
    assert "history-actions[open]" in JS
    assert 'row.append(button, manage)' in APP
    assert 'row.append(button, actions)' in APP


def test_both_action_pairs_share_background_and_transparent_child_controls():
    assert 'background: rgba(255, 255, 255, .10) !important;' in CSS
    assert '.project-row, .history-row' in CSS
    assert 'background: transparent !important;' in CSS
    assert '.history-actions > .history-more' in CSS
    assert 'historySection.is-collapsed' in CSS
    assert 'projectsSection.is-collapsed' in CSS


def test_four_home_cards_equal_while_upload_button_remains_nested():
    assert CSS.count('grid-auto-rows: 145px;') == 1
    assert 'grid-auto-rows: 116px;' not in CSS
    assert 'grid-auto-rows: 88px;' not in CSS
    assert 'No narrower viewport override' in CSS
    assert '.document-starter-shell > .starter' in CSS
    assert 'data-state="home"' in CSS
    assert 'href="./sidebar-section-polish.css"' in HTML
    assert HTML.index('href="./sidebar-section-polish.css"') > HTML.index('href="./sidebar-unified.css"')
    assert HTML.index('src="./sidebar-section-collapse.js"') > HTML.index('src="./app.js"')

def test_owner_seamless_sidebar_cells_and_centered_secondary_controls():
    """One visible row surface; gear/menu controls share its paint & center axis."""
    assert "Owner UI: New Chat is the single-cell reference" in CSS
    assert "background: transparent !important;" in CSS
    assert "align-items: center !important;" in CSS
    assert ".project-row > .project-manage svg" in CSS
    assert ".history-row .history-more svg" in CSS
    assert "transform: none !important;" in CSS
    assert "#projectsSection #projectCreateButton" in CSS
    assert "place-items: center !important;" in CSS
    assert "width: 28px !important;" in CSS
    assert "min-width: 28px !important;" in CSS
    assert "flex: 0 0 44px;" in CSS  # minimum touch target
    assert "min-width: 44px;" in CSS
    assert "min-height: 44px;" in CSS


def test_owner_expanded_minus_collapsed_chevron_icons_are_css_only():
    """ARIA and independent collapse handlers stay from the existing module."""
    assert "Expanded = minus" in CSS
    assert ".sidebar-section-toggle > span" in CSS
    assert "width: 12px;" in CSS
    assert "height: 2px;" in CSS
    assert ".recent-section.is-collapsed .sidebar-section-toggle > span" in CSS
    assert "border-top: 2px solid currentColor;" in CSS
    assert "border-right: 2px solid currentColor;" in CSS
    assert "aria-expanded" in JS
    assert "localStorage" not in JS

def test_project_and_history_title_do_not_blur_half_of_single_cell():
    """Owner screenshot regression: both halves must share one paint surface."""
    theme = (STATIC / "padiem-glass.css").read_text(encoding="utf-8")
    assert "backdrop-filter: blur(" in theme
    # A transparent title button still creates a separate backdrop-blur region.
    # Disable the effect on the two titles, not on the entire sidebar.
    assert ":is(.project-row > .project-item, .history-row > .history-item)" in CSS
    assert "-webkit-backdrop-filter: none !important;" in CSS
    assert "backdrop-filter: none !important;" in CSS
    assert "backdrop-filter: none" not in JS
