"""rich-response 코드 블록 머리줄이 테마 표면·글자 토큰을 따른다."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")
RICH = (STATIC / "rich-response.css").read_text(encoding="utf-8")


def _header_block(theme: str) -> str:
    marker = f'html[data-theme="{theme}"] .rich-code-header'
    assert marker in THEMES, f"{theme} 머리줄 덮어쓰기가 없다"
    return THEMES.split(marker, 1)[1].split("}", 1)[0]


def test_dark_glass_cinematic_header_is_not_white() -> None:
    for theme in ("dark", "padiem-glass", "cinematic", "padiem-home"):
        block = _header_block(theme)
        assert "var(--card-bg)" in block
        assert "var(--muted)" in block
        assert "#fff" not in block and "#f7f8fa" not in block


def test_light_keeps_rich_original_header() -> None:
    assert 'html[data-theme="light"] .rich-code-header' not in THEMES
    assert "background: #f7f8fa" in RICH
