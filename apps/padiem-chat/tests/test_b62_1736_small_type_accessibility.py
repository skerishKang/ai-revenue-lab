from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
POLISH = (STATIC / "accessibility-polish.css").read_text(encoding="utf-8")
UTILITY = (STATIC / "sidebar-utility.css").read_text(encoding="utf-8")


def test_accessibility_polish_is_loaded_after_base_theme_stack() -> None:
    assert UTILITY.startswith('@import url("./accessibility-polish.css");')
    assert "styles.css" not in POLISH
    assert "@font-face" not in POLISH


def test_meaningful_small_copy_has_12_to_13px_floor() -> None:
    for selector in (
        ".mini-badge",
        ".demo-label",
        ".attachment-copy small",
        ".message-attachment-meta",
        ".composer-note",
        ".project-banner-copy small",
        ".project-form label span",
        ".project-files-note",
        ".saved-output-header p",
        ".answer-source-copy small",
        ".document-attachment-icon",
        ".project-banner-actions button",
        ".project-file-add",
        ".answer-action",
        ".theme-option",
        ".language-option",
    ):
        assert selector in POLISH
    assert "font-size: 12px;" in POLISH
    assert "font-size: 13px;" in POLISH


def test_compact_controls_keep_practical_40_to_44px_targets() -> None:
    for selector in (
        ".attachment-remove",
        ".section-add-button",
        ".project-dialog-close",
        ".project-banner-actions button",
        ".project-file-add",
        ".project-file-row button",
        ".saved-output-close",
        ".answer-action",
        ".rich-code-copy",
        ".rich-table-download",
        ".settings-close",
        ".theme-option",
        ".language-option",
        ".settings-done",
    ):
        assert selector in POLISH
    assert "min-width: 40px;" in POLISH
    assert "min-height: 40px;" in POLISH
    assert "min-width: 44px;" in POLISH
    assert "min-height: 44px;" in POLISH


def test_glass_small_copy_uses_contrast_floor_and_bottom_home_utility() -> None:
    assert 'html[data-theme="padiem-glass"] .starter small' in POLISH
    assert "color: #394955 !important;" in POLISH
    assert 'html[data-theme="padiem-glass"] body .app-shell .sidebar-bottom .home-link' in POLISH
    assert "position: static !important;" in POLISH
    assert "min-height: 44px !important;" in POLISH
    assert 'html[data-theme="padiem-glass"] body .app-shell .sidebar-bottom .home-link::before' in POLISH
    assert "content: none !important;" in POLISH


def test_no_runtime_or_authority_behavior_is_embedded_in_css() -> None:
    lowered = POLISH.lower()
    for forbidden in ("/api/", "fetch(", "localstorage", "sessionstorage", "document.cookie", "provider"):
        assert forbidden not in lowered
