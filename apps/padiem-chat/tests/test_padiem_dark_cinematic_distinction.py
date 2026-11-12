"""#1273 — Dark and Cinematic must be visually distinct at first glance.

Dark is a flat neutral-charcoal utility mode; Cinematic owns the filmic
atmosphere (deep blue-black canvas, radial haze, glass depth, blue/gold glow).
These tests lock the token-level divergence so a future palette edit cannot
silently re-converge the two themes.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEMES_CSS = (ROOT / "static/padiem-themes.css").read_text(encoding="utf-8")
SETTINGS_CSS = (ROOT / "static/padiem-settings.css").read_text(encoding="utf-8")  # #7476-14
# #7187 R3 3차: --card-border moved to the token sheet (one owner per theme).
TOKENS_CSS = (ROOT / "static/padiem-tokens.css").read_text(encoding="utf-8")
POLISH_CSS = (ROOT / "static/padiem-bright-readability.css").read_text(encoding="utf-8")
THEME_JS = (ROOT / "static/theme.js").read_text(encoding="utf-8")
THEME_INIT_JS = (ROOT / "static/theme-init.js").read_text(encoding="utf-8")

FILMIC_TOKENS = (
    "--film-blue-glow",
    "--film-gold-glow",
    "--film-edge",
    "--film-vignette",
    "--film-grain",
)

SHARED_SURFACE_TOKENS = (
    "--bg",
    "--page-bg",
    "--panel",
    "--sidebar",
    "--card-bg",
    "--card-border",
    "--composer-bg",
    "--composer-border",
)


def _token_block(theme: str) -> str:
    # #7187 R3 5차: the theme palette (surfaces, semantic colours, shadows,
    # radii, typography) lives in padiem-tokens.css; the theme sheet keeps the
    # theme's surface/component rules.
    start = TOKENS_CSS.index(f'html[data-theme="{theme}"] {{')
    end = TOKENS_CSS.index("\n}", start)
    return TOKENS_CSS[start:end]


def _rule_section(theme: str) -> str:
    other = "cinematic" if theme == "dark" else "dark"
    start = THEMES_CSS.index(f'html[data-theme="{theme}"]')
    try:
        end = THEMES_CSS.index(f'html[data-theme="{other}"]', start + len(f'html[data-theme="{theme}"]'))
    except ValueError:
        end = len(THEMES_CSS)
    return THEMES_CSS[start:end]


def _token(block: str, name: str) -> str:
    m = re.search(re.escape(name) + r"\s*:\s*([^;]+);", block)
    assert m, f"missing token {name}"
    return m.group(1).strip()


def _hex_rgb(value: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"#([0-9a-fA-F]{6})", value)
    assert m, f"expected 6-digit hex token, got {value!r}"
    h = m.group(1).lower()
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _luma(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_dark_and_cinematic_background_tokens_differ_meaningfully():
    dark = _token_block("dark")
    cin = _token_block("cinematic")
    dark_rgb = _hex_rgb(_token(dark, "--bg"))
    cin_rgb = _hex_rgb(_token(cin, "--bg"))
    assert _token(dark, "--bg") != _token(cin, "--bg")
    assert _token(dark, "--page-bg") != _token(cin, "--page-bg")
    # #7187 R3 5차: the token sheet now carries the value that actually applied.
    # dark's canvas is #10151c (padiem-dark-contrast.css used to override the
    # theme sheet's #131417), so the distinction is measured on the real values:
    # Dark stays a lighter charcoal, Cinematic a near-black filmic canvas.
    assert _luma(dark_rgb) - _luma(cin_rgb) >= 12
    assert _luma(dark_rgb) >= 15
    assert _luma(cin_rgb) <= 10


def test_dark_and_cinematic_surface_tokens_differ():
    dark = _token_block("dark")
    cin = _token_block("cinematic")
    for token in SHARED_SURFACE_TOKENS:
        assert _token(dark, token) != _token(cin, token), f"{token} must not be shared"
    # Dark surfaces are flat opaque solids.
    for token in ("--panel", "--sidebar", "--card-bg", "--composer-bg", "--user-bubble-bg"):
        assert _token(dark, token).startswith("#"), f"dark {token} must be a flat solid"
    # Cinematic surfaces are translucent glass.
    for token in ("--panel", "--sidebar", "--card-bg", "--composer-bg"):
        assert _token(cin, token).startswith("rgba("), f"cinematic {token} must be translucent glass"


def test_cinematic_defines_filmic_tokens_absent_from_dark():
    dark = _token_block("dark")
    cin = _token_block("cinematic")
    for token in FILMIC_TOKENS:
        assert token in cin, f"cinematic missing filmic token {token}"
        assert token not in dark, f"dark must not share filmic token {token}"
        assert f"var({token})" in THEMES_CSS, f"{token} must be consumed by cinematic rules"


def test_dark_canvas_is_flat_utility_without_atmosphere():
    dark_rules = _rule_section("dark")
    assert "radial-gradient" not in dark_rules
    assert "blur(" not in dark_rules
    assert "backdrop-filter: none" in dark_rules
    assert "box-shadow: none" in dark_rules
    assert "text-shadow: none" in dark_rules


def test_cinematic_canvas_is_atmospheric_filmic():
    cin_rules = _rule_section("cinematic")
    assert "radial-gradient" in cin_rules
    assert "backdrop-filter: blur(" in cin_rules
    assert "var(--film-vignette)" in cin_rules
    assert "var(--film-grain)" in cin_rules
    assert "var(--film-edge)" in cin_rules
    assert "var(--film-blue-glow)" in cin_rules


def test_polish_layer_keeps_bounded_cinematic_atmosphere_only():
    assert 'html[data-theme="cinematic"] body {' in POLISH_CSS
    assert "rgba(108,190,255,.28)" in POLISH_CSS
    assert "rgba(239,201,132,.20)" in POLISH_CSS
    # The atmospheric polish layer must not re-inject gradients into Dark.
    assert 'html[data-theme="dark"] body {' not in POLISH_CSS
    assert 'html[data-theme="dark"] .composer {' not in POLISH_CSS


def test_settings_theme_controls_differ_between_dark_and_cinematic():
    # #7476-14: the picker rules now live in the consolidated settings sheet.
    css = THEMES_CSS + "\n" + SETTINGS_CSS
    selector = 'html[data-theme="{theme}"] .theme-option[aria-pressed="true"] {{'
    dark_active = css.split(selector.format(theme="dark"))[1].split("}")[0]
    cin_active = css.split(selector.format(theme="cinematic"))[1].split("}")[0]
    assert dark_active.strip() != cin_active.strip()
    # Dark active chip stays flat; cinematic active chip carries the film glow.
    assert "box-shadow: none" in dark_active
    assert "rgba(136,201,255" in cin_active


def test_theme_color_meta_map_matches_updated_backgrounds():
    # #7187 R3 5차: the token sheet now carries the applied dark --bg
    # (#10151c, the value the old dark-contrast override used). The meta
    # theme-color map has always kept the pre-contrast base (#131417); that is
    # existing browser-chrome behavior, not a page pixel, so the migration
    # keeps it pinned instead of silently changing it.
    dark_meta = "#131417"
    light_bg = _token(_token_block("light"), "--bg")
    cin_bg = _token(_token_block("cinematic"), "--bg")
    home_bg = _token(_token_block("padiem-home"), "--bg")
    assert f'light:"{light_bg}"' in THEME_JS
    assert f'dark:"{dark_meta}"' in THEME_JS
    assert f'cinematic:"{cin_bg}"' in THEME_JS
    assert f'"padiem-home":"{home_bg}"' in THEME_JS
    assert f'light:"{light_bg}"' in THEME_INIT_JS
    assert f'dark:"{dark_meta}"' in THEME_INIT_JS
    assert f'cinematic:"{cin_bg}"' in THEME_INIT_JS
