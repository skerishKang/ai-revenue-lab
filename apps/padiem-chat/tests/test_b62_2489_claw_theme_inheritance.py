from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
STATIC = ROOT / "apps" / "padiem-chat" / "static"


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_claw_shared_roles_use_chat_theme_tokens():
    workspace = read("claw-workspace.css")
    manual = read("claw-manual-intake.css")

    for source in (workspace, manual):
        assert "var(--text," not in source
        assert "var(--muted," not in source
        assert "var(--accent," not in source
        assert "var(--line," not in source
        assert "var(--card-bg," not in source

    required = (
        "var(--text)",
        "var(--muted)",
        "var(--line)",
        "var(--card-bg)",
        "var(--accent)",
        "var(--accent-soft)",
        "var(--accent-contrast)",
    )
    for token in required:
        assert token in workspace


def test_claw_has_no_padiem_glass_palette_override():
    workspace = read("claw-workspace.css")

    # The only allowed Glass-specific Claw rule is the mobile portrait suppression
    # for the decorative Chat hero. Claw component colors themselves must inherit.
    glass_rules = re.findall(
        r'html\[data-theme="padiem-glass"\][^{]*\.claw[^{]*\{',
        workspace,
    )
    assert glass_rules == []


def test_all_chat_themes_define_accent_contrast():
    themes = read("padiem-themes.css")
    glass = read("padiem-glass.css")

    expected = {
        "light": "#ffffff",
        "dark": "#131417",
        "cinematic": "#04070d",
        "padiem-home": "#0b0f14",
    }

    for theme, value in expected.items():
        block_match = re.search(
            rf'html\[data-theme="{re.escape(theme)}"\]\s*\{{(.*?)\n\}}',
            themes,
            re.S,
        )
        assert block_match, theme
        assert f"--accent-contrast: {value};" in block_match.group(1)

    assert "--accent-contrast: #17202a;" in glass


def test_claw_does_not_restore_legacy_shared_aliases():
    workspace = read("claw-workspace.css")
    manual = read("claw-manual-intake.css")

    for source in (workspace, manual):
        assert "var(--ink" not in source
        assert "var(--text-muted" not in source


def test_status_and_compact_labels_use_accessible_theme_tokens():
    workspace = read("claw-workspace.css")
    themes = read("padiem-themes.css")
    glass = read("padiem-glass.css")
    capability = read("capability-nav.css")

    assert "color: #1a6b3a;" not in workspace
    assert "color: #8a1a1a;" not in workspace
    assert ".claw-result-success-note" in workspace and "color: var(--success);" in workspace
    assert '.claw-status[data-state="success"]' in workspace
    assert 'color: var(--danger);' in workspace
    assert '.claw-workspace-chip' in workspace and 'color: var(--text);' in workspace
    assert '.claw-result-badge' in workspace and 'color: var(--text);' in workspace

    assert themes.count("--success:") >= 4
    assert "--success:" in glass
    assert "var(--ink" not in capability
    assert "color: var(--text);" in capability


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


def test_glass_status_surface_contract_uses_browser_audit_anchors():
    glass = read("padiem-glass.css")
    workspace = read("claw-workspace.css")

    assert "--success: #14532d;" in glass
    assert "--danger: #7f1d1d;" in glass
    assert "--success-surface: rgba(247, 251, 249, .92);" in glass
    assert "--danger-surface: rgba(253, 247, 247, .92);" in glass

    assert "background: var(--success-surface);" in workspace
    assert "border: 1px solid var(--success-border);" in workspace
    assert "background: var(--danger-surface);" in workspace
    assert "border: 1px solid var(--danger-border);" in workspace

    # Browser-audit anchors from KILO8's rendered Glass status strip BEFORE
    # this remediation. Composite the new declared semantic surface on top of
    # those real rendered anchors as a conservative contract. Final acceptance
    # still comes from the independent frozen browser harness.
    success_surface = _composite_rgb((247, 251, 249), 0.92, "#839293")
    error_surface = _composite_rgb((253, 247, 247), 0.92, "#afa7ac")

    assert _contrast_ratio("#14532d", success_surface) >= 4.5
    assert _contrast_ratio("#7f1d1d", error_surface) >= 4.5

    themes = read("padiem-themes.css")
    home_match = re.search(
        r'html\[data-theme="padiem-home"\]\s*\{(.*?)\n\}',
        themes,
        re.S,
    )
    assert home_match
    assert "--success: #14532d;" in home_match.group(1)
    assert _contrast_ratio("#14532d", "#f2f4f7") >= 4.5

def test_result_supporting_copy_uses_primary_text_on_translucent_surfaces():
    workspace = read("claw-workspace.css")

    for selector in (".claw-result-note", ".claw-result-empty"):
        block = re.search(rf'(?m)^{re.escape(selector)}\s*\{{(.*?)\n\}}', workspace, re.S)
        assert block, selector
        assert "color: var(--text);" in block.group(1)

    hint_block = re.search(
        r'\.claw-result-hint,\s*\n\.claw-execute-hint\s*\{(.*?)\n\}',
        workspace,
        re.S,
    )
    assert hint_block
    assert "color: var(--text);" in hint_block.group(1)
