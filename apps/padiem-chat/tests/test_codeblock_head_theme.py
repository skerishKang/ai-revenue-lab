"""rich-response 코드 블록 머리줄·복사 버튼 색을 토큰으로 계산해 검사한다.

PR #7808 1차는 padiem-themes.css에 테마별 덮어쓰기 규칙 8개를 새로 얹었다.
리팩터링 v2(#7809·#7811) 규칙은 "테마 차이는 토큰 값으로만 내고 구성 요소
시트에 [data-theme] 규칙을 새로 쓰지 않는다"이므로, 같은 브랜치에서 방식을
토큰으로 바꿨다.

* 바탕 선언은 padiem-rich.css:42~66이 갖고 있었다(머리줄 rgba(255,255,255,
  .035)/.46/.09, 복사 rgba(255,255,255,.05)/.66/.10). 테마와 무관한 숫자라
  다섯 테마가 같은 값을 칠했다.
* 그 숫자를 padiem-tokens.css의 --rich-code-* 토큰으로 옮겼다. 라이트 값은
  화면 그대로이고, 다크·시네마틱·홈은 그 테마의 카드 면·글자·헤어라인 토큰을,
  Glass는 어두운 면 토큰을 가리킨다.

이 시험은 글자를 읽지 않고 계산값으로 판정한다: 토큰 파일을 테마별로 풀고
(:root 위에 테마 블록), var()를 재귀 해소하고, 어두운 코드 면 위에 알파를
합성한 뒤 WCAG 상대 휘도로 대비를 낸다 — 브라우저가 칠하는 값과 같은 순서다.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

STATIC = Path(__file__).resolve().parents[1] / "static"
TOKENS = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")
RICH = (STATIC / "padiem-rich.css").read_text(encoding="utf-8")
THEMES = (STATIC / "padiem-themes.css").read_text(encoding="utf-8")

THEME_NAMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")

#: 토큰 이름 → (라이트 기대값, 나머지 테마 최소 대비)
HEADER_TOKENS = (
    "--rich-code-header-bg",
    "--rich-code-header-text",
    "--rich-code-header-border",
)
COPY_TOKENS = (
    "--rich-code-copy-bg",
    "--rich-code-copy-text",
    "--rich-code-copy-border",
)
HOVER_TOKENS = ("--rich-code-copy-hover-bg", "--rich-code-copy-hover-text")
ALL_TOKENS = HEADER_TOKENS + COPY_TOKENS + HOVER_TOKENS

#: PR 전 main에서 라이트 테마가 실제로 칠하던 값(2026-11-16 브라우저 실측).
#: padiem-rich.css가 갖고 있던 숫자 그대로다.
LIGHT_BEFORE = {
    "--rich-code-header-bg": "rgba(255,255,255,.035)",
    "--rich-code-header-text": "rgba(255,255,255,.46)",
    "--rich-code-header-border": "rgba(255,255,255,.09)",
    "--rich-code-copy-bg": "rgba(255,255,255,.05)",
    "--rich-code-copy-text": "rgba(255,255,255,.66)",
    "--rich-code-copy-border": "rgba(255,255,255,.10)",
    "--rich-code-copy-hover-bg": "rgba(255,255,255,.09)",
    "--rich-code-copy-hover-text": "#ffffff",
}

#: 코드 블록 면(padiem-rich.css .rich-code-block) — 머리줄이 얹히는 바탕.
BLOCK_BG = "rgba(8,9,11,.76)"


def _normalize(value: str) -> str:
    """'rgba(255, 255, 255, .035)'와 'rgba(255,255,255,.035)'를 같게 본다."""
    return re.sub(r"\s+", "", value).lower().replace("0.", ".")


def _theme_tokens(theme: str) -> dict[str, str]:
    """:root 위에 해당 테마 블록을 얹은 토큰 표."""
    table: dict[str, str] = {}
    rules = parse_rules(TOKENS)
    for rule in find_rules_with_selector(rules, ":root"):
        table.update(rule.declarations)
    for rule in find_rules_with_selector(rules, f'html[data-theme="{theme}"]'):
        table.update(rule.declarations)
    return table


def _resolve(value: str, table: dict[str, str], seen: tuple[str, ...] = ()) -> str:
    """var(--x)를 재귀 해소한다. 정의가 없으면 실패시킨다(흰색 fallback 금지)."""
    match = re.fullmatch(r"var\(\s*(--[A-Za-z0-9-]+)\s*\)", value.strip())
    if not match:
        return value
    name = match.group(1)
    assert name in table, f"{name} 정의가 없다"
    assert name not in seen, f"{name} 순환 참조: {seen}"
    return _resolve(table[name], table, seen + (name,))


def _color(value: str) -> tuple[float, float, float, float]:
    """#rgb/#rrggbb/rgba()를 (r, g, b, a)로."""
    text = value.strip()
    if text.startswith("#"):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        assert len(digits) == 6, f"색 형식을 읽을 수 없다: {value}"
        return (
            int(digits[0:2], 16),
            int(digits[2:4], 16),
            int(digits[4:6], 16),
            1.0,
        )
    match = re.fullmatch(r"rgba?\(([^)]+)\)", text)
    assert match, f"색 형식을 읽을 수 없다: {value}"
    parts = [part for part in re.split(r"[,\s/]+", match.group(1)) if part]
    numbers = [float(part) for part in parts]
    alpha = numbers[3] if len(numbers) > 3 else 1.0
    return (numbers[0], numbers[1], numbers[2], alpha)


def _over(top: tuple[float, ...], bottom: tuple[float, ...]) -> tuple[float, ...]:
    """알파 합성: 위 색을 아래 색 위에 칠한 결과."""
    alpha = top[3] + bottom[3] * (1 - top[3])
    if alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        (top[0] * top[3] + bottom[0] * bottom[3] * (1 - top[3])) / alpha,
        (top[1] * top[3] + bottom[1] * bottom[3] * (1 - top[3])) / alpha,
        (top[2] * top[3] + bottom[2] * bottom[3] * (1 - top[3])) / alpha,
        alpha,
    )


def _luminance(color: tuple[float, ...]) -> float:
    def channel(value: float) -> float:
        ratio = value / 255
        return ratio / 12.92 if ratio <= 0.03928 else ((ratio + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def _contrast(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _painted(theme: str, background_token: str, text_token: str) -> tuple[float, ...]:
    """테마·토큰으로 코드 면 위에 실제로 칠해지는 (글자, 바탕)을 계산한다."""
    table = _theme_tokens(theme)
    page = _color(_resolve(f"var({_page_token(theme)})", table))
    block = _over(_color(BLOCK_BG), page)
    background = _over(_color(_resolve(f"var({background_token})", table)), block)
    text = _over(_color(_resolve(f"var({text_token})", table)), background)
    return text, background


def _page_token(theme: str) -> str:
    table = _theme_tokens(theme)
    return "--page-bg" if "--page-bg" in table else "--bg"


def _rule_css(stylesheet: str, selector: str) -> dict[str, str]:
    rules = find_rules_with_selector(parse_rules(stylesheet), selector)
    assert rules, f"{selector} 규칙이 없다"
    return rules[-1].declarations


class CodeblockHeadTokenOwnership(unittest.TestCase):
    """색은 토큰이 소유하고, 테마 시트는 이 부품을 덮지 않는다."""

    def test_themes_sheet_has_no_code_header_override(self) -> None:
        for theme in THEME_NAMES:
            for part in (".rich-code-header", ".rich-code-copy"):
                self.assertNotIn(
                    f'html[data-theme="{theme}"] {part}',
                    THEMES,
                    f"{theme} {part} 덮어쓰기 규칙이 남아 있다",
                )

    def test_tokens_are_defined_for_every_theme(self) -> None:
        for theme in THEME_NAMES:
            table = _theme_tokens(theme)
            for name in ALL_TOKENS:
                self.assertIn(name, table, f"{theme}에 {name} 정의가 없다")

    def test_rich_sheet_consumes_tokens_without_important(self) -> None:
        header = _rule_css(RICH, ".rich-code-header")
        copy = _rule_css(RICH, ".rich-code-copy")
        self.assertEqual(header.get("background"), "var(--rich-code-header-bg)")
        self.assertEqual(header.get("color"), "var(--rich-code-header-text)")
        self.assertEqual(header.get("border-bottom-color"), "var(--rich-code-header-border)")
        self.assertEqual(copy.get("background"), "var(--rich-code-copy-bg)")
        self.assertEqual(copy.get("color"), "var(--rich-code-copy-text)")
        self.assertEqual(copy.get("border-color"), "var(--rich-code-copy-border)")
        for declarations in (header, copy):
            for value in declarations.values():
                self.assertNotIn("!important", value)


class LightStaysIdentical(unittest.TestCase):
    """라이트는 PR 전 main이 칠하던 값 그대로다."""

    def test_light_tokens_equal_the_pre_pr_paint(self) -> None:
        table = _theme_tokens("light")
        for name, expected in LIGHT_BEFORE.items():
            self.assertEqual(
                _normalize(table[name]),
                _normalize(expected),
                f"라이트 {name} 값이 바뀌었다",
            )

    def test_light_defaults_match_the_theme_block(self) -> None:
        """테마 적용 전 한 프레임도 라이트와 같다(:root = light)."""
        rules = parse_rules(TOKENS)
        root: dict[str, str] = {}
        for rule in find_rules_with_selector(rules, ":root"):
            root.update(rule.declarations)
        for name, expected in LIGHT_BEFORE.items():
            self.assertEqual(_normalize(root[name]), _normalize(expected), f":root {name}")


class OtherThemesFollowSurfaceTokens(unittest.TestCase):
    """다크·시네마틱·홈·Glass는 그 테마 토큰을 따르고 흰 바탕이 아니다."""

    def test_background_is_not_white(self) -> None:
        for theme in THEME_NAMES[1:]:
            for background_token, text_token in (
                ("--rich-code-header-bg", "--rich-code-header-text"),
                ("--rich-code-copy-bg", "--rich-code-copy-text"),
            ):
                _, background = _painted(theme, background_token, text_token)
                self.assertFalse(
                    background[0] >= 255 and background[1] >= 255 and background[2] >= 255,
                    f"{theme} {background_token}가 흰색으로 칠해진다",
                )

    def test_text_contrast_reaches_wcag_aa(self) -> None:
        for theme in THEME_NAMES[1:]:
            for background_token, text_token in (
                ("--rich-code-header-bg", "--rich-code-header-text"),
                ("--rich-code-copy-bg", "--rich-code-copy-text"),
            ):
                text, background = _painted(theme, background_token, text_token)
                ratio = _contrast(text, background)
                self.assertGreaterEqual(
                    round(ratio, 2),
                    4.5,
                    f"{theme} {text_token} 대비 {ratio:.2f}",
                )

    def test_theme_differs_from_the_old_fixed_paint(self) -> None:
        """예전 고정 숫자(rgba(255,255,255,…))가 그대로 남아 있지 않다."""
        for theme in THEME_NAMES[1:]:
            table = _theme_tokens(theme)
            background = _normalize(_resolve(f"var(--rich-code-header-bg)", table))
            self.assertNotEqual(
                background,
                _normalize(LIGHT_BEFORE["--rich-code-header-bg"]),
                f"{theme} 머리줄이 예전 고정값 그대로다",
            )


if __name__ == "__main__":
    unittest.main()
