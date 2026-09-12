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
