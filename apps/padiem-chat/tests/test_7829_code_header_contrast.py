"""#7829 — 코드 블록 머리(언어 이름·복사 단추) 글자가 읽히는가.

읽히는지는 사람이 보지 않고 숫자로 확인한다: 테마 토큰과 그 테마가 실제로
칠하는 머리 표면 사이의 WCAG 대비를 계산한다. 기준은 머리 글자 4.5, 복사
단추 글자 4.5다.

규칙도 함께 잠근다(#7809 기능·수리 PR 규칙): 색 차이는 토큰 값으로만 내고,
`!important`나 새 `[data-theme=…]` 덮어쓰기 규칙으로 내지 않는다. 이기는 규칙은
`rich-response.css` 하나이며, `padiem-rich.css`의 겹치는 색 지정은 삭제됐다.
"""

from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.glass_contrast_source import a11y_css, chat_ui_polish_css, glass_css, glass_gutter_css, glass_portrait_css, index_html, mobile_legibility_css, rich_css, rich_response_css, surfaces_css, themes_css, tokens_css

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TOKENS = tokens_css()
RICH_BASE = rich_response_css()
RICH_DARK = rich_css()
A11Y = a11y_css()
MOBILE = mobile_legibility_css()
THEMES = themes_css()
GLASS = glass_css()

THEME_NAMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
# 머리 띠와 단추 면의 지배색. 실행 중인 앱(`?theme=<이름>`)에서 코드 블록을
# 렌더해 글자 바로 아래 띠(머리 글자)와 단추 면(복사 글자)을 샘플한 값에
# 여유 2를 더한 보수치다. 1440과 390이 같은 값을 냈다.
HEADER_SURFACE = {
    "light": (74, 74, 76),
    "dark": (21, 22, 25),
    "cinematic": (20, 21, 24),
    "padiem-home": (68, 69, 70),
    "padiem-glass": (73, 74, 75),
}
BUTTON_FACE = {
    "light": (84, 85, 86),
    "dark": (33, 34, 36),
    "cinematic": (31, 35, 39),
    "padiem-home": (78, 80, 83),
    "padiem-glass": (82, 83, 84),
}


def _block(sheet: str, theme: str) -> str:
    return sheet.split(f'html[data-theme="{theme}"] {{', 1)[1].split("}", 1)[0]


def _value(block: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}:\s*([^;]+);", block)
    assert match, name
    return match.group(1).strip()


def _rgba(value: str) -> tuple[tuple[int, int, int], float]:
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    assert match, value
    parts = [p.strip() for p in match.group(1).replace(",", " ").replace("/", " ").split()]
    return tuple(int(float(p)) for p in parts[:3]), float(parts[3])


def _token(name: str, theme: str) -> tuple[tuple[int, int, int], float]:
    for block in (_block(TOKENS, theme), TOKENS.split(":root {", 1)[1].split("}", 1)[0]):
        try:
            return _rgba(_value(block, name))
        except AssertionError:
            continue
    raise AssertionError(f"{name} not resolved for {theme}")


def _over(fg: tuple[tuple[int, int, int], float], bg: tuple[int, int, int]) -> tuple[int, int, int]:
    (r, g, b), alpha = fg
    return (
        round(r * alpha + bg[0] * (1 - alpha)),
        round(g * alpha + bg[1] * (1 - alpha)),
        round(b * alpha + bg[2] * (1 - alpha)),
    )


def _contrast(fg: tuple[tuple[int, int, int], float], bg: tuple[int, int, int]) -> float:
    def lin(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    def lum(rgb: tuple[int, int, int]) -> float:
        return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])

    ink = _over(fg, bg)
    hi, lo = max(lum(ink), lum(bg)), min(lum(ink), lum(bg))
    return (hi + 0.05) / (lo + 0.05)


def _rule_block(sheet: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}[^{{]*\{{([^}}]*)\}}", sheet)
    assert match, selector
    return match.group(1)


def _has_color_prop(block: str) -> bool:
    return re.search(r"(?<![-a-z])color\s*:", block) is not None


def test_one_rule_reads_the_tokens_and_the_overlap_is_gone() -> None:
    header = _rule_block(RICH_BASE, ".rich-code-header")
    assert "color: var(--code-header-text);" in header
    copy = _rule_block(RICH_BASE, ".rich-code-copy")
    assert "color: var(--code-header-button-text);" in copy
    # #7829: 겹쳐서 쓸모없어진 지정은 지웠다. 남으면 이 시험이 막는다.
    assert not _has_color_prop(_rule_block(RICH_DARK, ".rich-code-header"))
    assert not _has_color_prop(_rule_block(RICH_DARK, ".rich-code-copy"))
    # 나머지 두 시트는 글자색이 없고 크기만 다룬다.
    assert not _has_color_prop(_rule_block(A11Y, ".rich-code-header"))
    assert not _has_color_prop(_rule_block(MOBILE, ".rich-code-header"))


def test_no_theme_sheet_repaints_the_header_text() -> None:
    # #7809: 테마별 차이는 토큰 값으로. 테마 시트가 이 글자를 따로 덮지 않는다.
    for sheet, name in ((THEMES, "padiem-themes.css"), (GLASS, "padiem-glass.css")):
        for selector in (".rich-code-header", ".rich-code-copy"):
            assert selector not in sheet, f"{name} {selector}"


def test_every_theme_defines_both_header_tokens() -> None:
    for theme in THEME_NAMES:
        assert "--code-header-text" in _block(TOKENS, theme), theme
        assert "--code-header-button-text" in _block(TOKENS, theme), theme


def test_header_and_copy_meet_4_5_in_every_theme() -> None:
    failures = []
    for theme in THEME_NAMES:
        head = _contrast(_token("--code-header-text", theme), HEADER_SURFACE[theme])
        if head < 4.5:
            failures.append(f"{theme} 머리 {head:.2f}")
        copy = _contrast(_token("--code-header-button-text", theme), BUTTON_FACE[theme])
        if copy < 4.5:
            failures.append(f"{theme} 복사 {copy:.2f}")
    assert not failures, "코드 블록 머리 대비 4.5 미만: " + ", ".join(failures)
