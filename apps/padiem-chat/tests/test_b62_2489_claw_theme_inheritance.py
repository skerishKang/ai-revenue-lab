"""#2489/#7187: Claw inherits Chat theme tokens without a private palette."""
from __future__ import annotations

from _support.claw_theme_inheritance import (
    REQUIRED_TOKENS,
    SURFACE_DECLARATIONS,
    THEMES,
    facts,
)

EXPECTED_ACCENT_CONTRAST = {
    "light": "#ffffff",
    "dark": "#131417",
    "cinematic": "#04070d",
    "padiem-home": "#0b0f14",
    "padiem-glass": "#17202a",
}


def _relative_luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    channels = [int(raw[index:index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = [linear(channel) for channel in channels]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float:
    fg = _relative_luminance(foreground)
    bg = _relative_luminance(background)
    lighter, darker = max(fg, bg), min(fg, bg)
    return (lighter + 0.05) / (darker + 0.05)


def _composite_rgb(foreground: tuple[int, int, int], alpha: float, background: str) -> str:
    raw = background.lstrip("#")
    bg = [int(raw[index:index + 2], 16) for index in (0, 2, 4)]
    out = [
        round(channel * alpha + base * (1 - alpha))
        for channel, base in zip(foreground, bg)
    ]
    return "#" + "".join(f"{channel:02x}" for channel in out)


def test_claw_shared_roles_use_chat_theme_tokens():
    result = facts()
    assert result["fallback_tokens"] == ()
    assert len(result["required_tokens"]) == len(REQUIRED_TOKENS)


def test_claw_has_no_padiem_glass_palette_override():
    assert facts()["glass_rules"] == []


def test_all_chat_themes_define_accent_contrast():
    blocks = facts()["theme_blocks"]
    assert set(THEMES).issubset(blocks)
    for theme, value in EXPECTED_ACCENT_CONTRAST.items():
        assert ("--accent-contrast", value) in blocks[theme]


def test_claw_does_not_restore_legacy_shared_aliases():
    assert facts()["legacy_aliases"] == ()


def test_status_and_compact_labels_use_accessible_theme_tokens():
    result = facts()
    assert result["forbidden_colors"] == ()
    declarations = result["workspace_declarations"]
    for declaration in (("color", "var(--success)"), ("color", "var(--danger)"),
                        ("color", "var(--text)")):
        assert declaration in declarations
    for selector in (".claw-result-success-note", '.claw-status[data-state="success"]',
                     ".claw-workspace-chip", ".claw-result-badge"):
        assert any(selector in entry for entry in result["workspace_selectors"])
    assert result["success_count"] >= 4
    assert ("--success", "#14532d") in result["token_declarations"]
    capability = result["capability_declarations"]
    assert ("color", "var(--text)") in capability


def test_glass_status_surface_contract_uses_browser_audit_anchors():
    result = facts()
    tokens = result["token_declarations"]
    for declaration in (("--success", "#14532d"), ("--danger", "#7f1d1d"),
                        ("--success-surface", "rgba(247, 251, 249, .92)"),
                        ("--danger-surface", "rgba(253, 247, 247, .92)")):
        assert declaration in tokens
    workspace = result["workspace_declarations"]
    for declaration in SURFACE_DECLARATIONS:
        assert declaration in workspace
    success_surface = _composite_rgb((247, 251, 249), 0.92, "#839293")
    error_surface = _composite_rgb((253, 247, 247), 0.92, "#afa7ac")
    assert _contrast_ratio("#14532d", success_surface) >= 4.5
    assert _contrast_ratio("#7f1d1d", error_surface) >= 4.5
    assert ("--success", "#14532d") in result["theme_blocks"]["padiem-home"]
    assert _contrast_ratio("#14532d", "#f2f4f7") >= 4.5


def test_result_supporting_copy_uses_primary_text_on_translucent_surfaces():
    result = facts()
    assert set(result["result_blocks"]) == {".claw-result-note", ".claw-result-empty"}
    for block in result["result_blocks"].values():
        assert ("color", "var(--text)") in block
    assert ("color", "var(--text)") in result["hint_block"]
