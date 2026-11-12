"""#7187 R3 6·7차 — 정의가 보장된/보장되도록 채운 토큰의 fallback 정리.

6차는 ``padiem-tokens.css``가 **다섯 테마 모두**에서 값을 정의하는 토큰의
죽은 ``var(--token, 숫자)`` fallback을 제거했다(4차(#7494)·5차(#7499) 뒤).
7차는 그 자리에서 남긴 일부 테마 빈칸 토큰 중 값이 하나로 모이는 것
(``--radius-md``·``--glass``)을 다섯 테마 모두에 정의하고, 그 결과 죽는
fallback 하나를 지웠다. 사용처마다 fallback 값이 달랐던 ``--card-shadow``와,
fallback 없는 사용처가 이미 다른 글꼴로 해소 중이던 ``--font-label``은
화면 작업이므로 손대지 않고 남긴다. 8차는 유틸·연결 화면 시트
(``util-*``·``connector-pages``·``capability-nav``)에 같은 기준을 적용해
89개를 지웠고, 다섯 테마 어디에도 정의가 없는 ``--card-bg``·``--brand-soft``·
``--input-border``·``--surface-muted`` fallback은 실제 값이므로 남긴다.
판단 근거는 PR 본문과 ``padiem-reports/2026-11-12/7187-r3-6-dead-fallbacks``/
``7187-r3-7-token-fill``/``7187-r3-8-util-connector`` 에 있다.

읽는 법:

* ``SAFE`` — 다섯 테마에서 항상 정의되므로 fallback이 도달 불가능한 토큰.
* ``EDITED`` — 이번에 fallback을 지운 시트. 전부 ``padiem-tokens.css``를
  로드하는 화면(index.html, React 클론, council 진입점)만 소비한다.
* ``KEPT`` — 토큰이 일부 테마에만 정의돼 fallback이 실제로 쓰이는 시트.
  ``help.css``는 help/install(토큰 로드)과 help-tutorials(토큰 미로드)가
  함께 쓰므로 남긴다. ``padiem-home.css``는 padiem-home.html이 토큰 시트를
  로드하지 않아 남긴다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
COUNCIL = Path(__file__).resolve().parents[2] / "padiem-council-apps" / "static"

TOKENS = STATIC / "padiem-tokens.css"
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")

EDITED = (
    STATIC / "b66-quote-runtime.css",
    STATIC / "capability-presentation.css",
    STATIC / "claw-connection-guide.css",
    STATIC / "claw-focus-layout.css",
    STATIC / "claw-quote-compare.css",
    STATIC / "history.css",
    STATIC / "library.css",
    STATIC / "meeting-capture.css",
    STATIC / "mode-presentation.css",
    STATIC / "pc-file-exchange.css",
    STATIC / "projects.css",
    STATIC / "sidebar-history-scroll.css",
    STATIC / "sidebar-section-polish.css",
    COUNCIL / "council-app.css",
    # 8차: 유틸·연결 화면 시트. index.html 안에서만 열리고 padiem-tokens.css를
    # 먼저 로드하므로 같은 기준(다섯 테마 공통 정의 토큰)을 적용했다.
    STATIC / "util-menu.css",
    STATIC / "util-app.css",
    STATIC / "util-tools.css",
    STATIC / "util-chat-mode.css",
    STATIC / "util-excel.css",
    STATIC / "util-quote.css",
    STATIC / "connector-pages.css",
    STATIC / "capability-nav.css",
)

#: 토큰이 일부 테마에만 정의돼 있어 이번에 지우지 않은 시트(경계 고정).
KEPT = (
    STATIC / "help.css",
    STATIC / "help-tutorials" / "tutorial.css",
    STATIC / "padiem-home.css",
    STATIC / "mcp-gateway-settings.css",
)

#: glass의 --card-bg는 padiem-glass-portrait.css가 로드 순서상 소유한다(5차 예외).
GLASS_CARD_BG_EXCEPTION = "--card-bg"

#: 7차: 값이 하나로 모여 다섯 테마 모두에 정의한 토큰.
ROUND7_FILLED = ("--radius-md", "--glass")
#: 7차: 사용처별 값이 갈리거나 fallback 없는 사용처가 있어 손대지 않은 토큰.
ROUND7_SKIPPED = ("--card-shadow", "--font-label")

VAR = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*,")


def _block(text: str, selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{", text)
    assert match is not None, selector
    start = match.end()
    depth = 1
    index = start
    while depth and index < len(text):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
        index += 1
    return text[start:index - 1]


def _names(block: str) -> set[str]:
    return set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", block))


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


class TestDeadFallbacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tokens = TOKENS.read_text(encoding="utf-8")
        cls.root = _names(_block(cls.tokens, ":root"))
        cls.theme_names = {
            theme: _names(_block(cls.tokens, 'html[data-theme="%s"]' % theme))
            for theme in THEMES
        }
        cls.safe = cls.root | set.intersection(*cls.theme_names.values())

    def test_the_safe_set_really_covers_every_theme(self) -> None:
        self.assertTrue(self.safe)
        for token in self.safe:
            for theme, names in self.theme_names.items():
                if token in self.root:
                    continue
                self.assertIn(token, names, f"{token} missing in {theme}")

    def test_edited_sheets_do_not_keep_safe_literal_fallbacks(self) -> None:
        offenders = []
        for path in EDITED:
            text = _strip_comments(path.read_text(encoding="utf-8"))
            for match in VAR.finditer(text):
                token = match.group(1)
                if token not in self.safe or token == GLASS_CARD_BG_EXCEPTION:
                    continue
                # fallback이 var(...)인 경우는 중첩 값이라 이번 범위(숫자 fallback)가 아니다.
                depth, index = 1, match.end()
                while depth and index < len(text):
                    if text[index] == "(":
                        depth += 1
                    elif text[index] == ")":
                        depth -= 1
                    index += 1
                fallback = text[match.end():index - 1]
                if "var(" in fallback:
                    continue
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.name}:{line} {token}")
        self.assertEqual(offenders, [], "dead fallbacks reintroduced")

    def test_kept_sheets_still_rely_on_the_fallback(self) -> None:
        """토큰을 로드하지 않는 화면이 쓰는 시트는 fallback이 실제 값이다."""
        tutorial = (STATIC / "help-tutorials" / "01-first-visit.html").read_text(encoding="utf-8")
        self.assertNotIn("padiem-tokens.css", tutorial)
        self.assertIn("../help.css", tutorial)
        self.assertRegex(
            (STATIC / "help.css").read_text(encoding="utf-8"),
            r"var\(--(muted|text|panel),\s*[^)v]",
        )
        home = (STATIC / "padiem-home.html").read_text(encoding="utf-8")
        self.assertNotIn("padiem-tokens.css", home)
        self.assertIn("./padiem-home.css", home)

    def test_tokens_sheet_is_loaded_before_consumers_on_edited_pages(self) -> None:
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertLess(index.index("styles.css"), index.index("padiem-tokens.css"))
        self.assertLess(index.index("padiem-tokens.css"), index.index("b66-quote-runtime.css"))
        council = (COUNCIL / "index.html").read_text(encoding="utf-8")
        self.assertIn("/padiem-tokens.css", council)
        self.assertLess(council.index("/padiem-tokens.css"), council.index("council-app.css"))


class TestRound7ThemeFill(unittest.TestCase):
    """7차: 값이 모인 토큰만 빈 테마 블록을 채우고, 그 결과 죽은 fallback을 지운다."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tokens = TOKENS.read_text(encoding="utf-8")
        cls.theme_blocks = {
            theme: _block(cls.tokens, 'html[data-theme="%s"]' % theme)
            for theme in THEMES
        }

    def test_filled_tokens_are_defined_in_every_theme(self) -> None:
        for token in ROUND7_FILLED:
            for theme, block in self.theme_blocks.items():
                self.assertIn(
                    f"{token}:", block, f"{token} missing in {theme}"
                )

    def test_radius_fill_uses_the_single_value_in_use(self) -> None:
        for theme, block in self.theme_blocks.items():
            match = re.search(r"--radius-md:\s*([^;]+);", block)
            self.assertIsNotNone(match, f"--radius-md missing in {theme}")
            self.assertEqual(match.group(1).strip(), "16px")

    def test_glass_fill_moves_the_fallback_value_only(self) -> None:
        """fallback이 실제 값이던 테마만 var(--panel)로 채우고, 기존 정의는 둔다."""
        for theme in ("dark", "cinematic", "padiem-home"):
            match = re.search(r"--glass:\s*([^;]+);", self.theme_blocks[theme])
            self.assertIsNotNone(match, f"--glass missing in {theme}")
            self.assertEqual(match.group(1).strip(), "var(--panel)")
        light = re.search(r"--glass:\s*([^;]+);", self.theme_blocks["light"])
        glass = re.search(r"--glass:\s*([^;]+);", self.theme_blocks["padiem-glass"])
        self.assertEqual(light.group(1).strip(), "rgba(255,255,255,.72)")
        self.assertEqual(
            glass.group(1).strip(), "rgba(244, 247, 249, .42)"
        )

    def test_glass_fallback_gone_where_value_is_defined(self) -> None:
        interaction = (STATIC / "interaction-polish.css").read_text(encoding="utf-8")
        self.assertNotIn("var(--glass, var(--panel))", interaction)
        self.assertIn("var(--glass)", interaction)

    def test_skipped_tokens_keep_their_live_fallbacks(self) -> None:
        """--card-shadow: 사용처별 fallback이 갈리고, --font-label: bare 사용처가 있다."""
        interaction = (STATIC / "interaction-polish.css").read_text(encoding="utf-8")
        self.assertIn("var(--card-shadow, var(--shadow))", interaction)
        meeting = (STATIC / "meeting-capture.css").read_text(encoding="utf-8")
        self.assertIn(
            "var(--card-shadow, 0 14px 45px rgba(20,30,44,.10))", meeting
        )
        for name in ("answer-actions.css", "shared-tooltip.css"):
            text = (STATIC / name).read_text(encoding="utf-8")
            self.assertIn(
                'var(--font-label, "SUIT Variable", system-ui, sans-serif)', text
            )
        # bare 사용처(fallback 없음)는 정의를 넣으면 값이 바뀌므로 미정의가 맞다.
        cinematic = (
            STATIC / "padiem-cinematic-workspace.css"
        ).read_text(encoding="utf-8")
        self.assertIn("font-family: var(--font-label);", cinematic)

    def test_skipped_tokens_are_still_theme_gap_tokens(self) -> None:
        for token in ROUND7_SKIPPED:
            for theme in ("dark", "cinematic", "padiem-home"):
                self.assertNotIn(f"{token}:", self.theme_blocks[theme])


ROUND8_SHEETS = (
    STATIC / "util-menu.css",
    STATIC / "util-app.css",
    STATIC / "util-tools.css",
    STATIC / "util-chat-mode.css",
    STATIC / "util-excel.css",
    STATIC / "util-quote.css",
    STATIC / "connector-pages.css",
    STATIC / "capability-nav.css",
)
#: 8차: 다섯 테마 어디에도 정의가 없어 fallback이 실제 값인 토큰.
#: ``--card-bg``는 glass만 padiem-glass-portrait.css가 소유한다(5차 예외).
ROUND8_NOT_DEFINED = ("--card-bg", "--brand-soft", "--input-border", "--surface-muted")


class TestRound8UtilConnector(unittest.TestCase):
    """8차: 유틸·연결 시트는 index.html 안에서만 열리므로 같은 기준을 쓴다."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tokens = TOKENS.read_text(encoding="utf-8")
        cls.root = _names(_block(cls.tokens, ":root"))
        cls.theme_names = {
            theme: _names(_block(cls.tokens, 'html[data-theme="%s"]' % theme))
            for theme in THEMES
        }
        cls.safe = cls.root | set.intersection(*cls.theme_names.values())
        cls.theme_blocks = {
            theme: _block(cls.tokens, 'html[data-theme="%s"]' % theme)
            for theme in THEMES
        }

    def test_kept_round8_tokens_are_not_defined_in_every_theme(self) -> None:
        """다섯 테마 중 하나라도 빈칸이면 fallback은 실제 값이다."""
        for token in ROUND8_NOT_DEFINED:
            self.assertNotIn(token, self.safe, f"{token} is defined everywhere")
        for token in ROUND8_NOT_DEFINED:
            missing = [
                theme
                for theme, names in self.theme_names.items()
                if token not in names and token not in self.root
            ]
            self.assertTrue(missing, f"{token} never relies on its fallback")
        self.assertNotIn("--card-bg:", self.theme_blocks["padiem-glass"])

    def test_round8_sheets_keep_no_safe_literal_fallback(self) -> None:
        offenders = []
        for path in ROUND8_SHEETS:
            text = _strip_comments(path.read_text(encoding="utf-8"))
            for match in VAR.finditer(text):
                token = match.group(1)
                if token not in self.safe or token == GLASS_CARD_BG_EXCEPTION:
                    continue
                depth, index = 1, match.end()
                while depth and index < len(text):
                    if text[index] == "(":
                        depth += 1
                    elif text[index] == ")":
                        depth -= 1
                    index += 1
                if "var(" in text[match.end():index - 1]:
                    continue
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.name}:{line} {token}")
        self.assertEqual(offenders, [], "dead fallbacks reintroduced")

    def test_round8_sheets_are_only_loaded_inside_index_html(self) -> None:
        """유틸·연결 시트를 토큰 없이 로드하는 별도 HTML 진입점이 없어야 한다."""
        html_files = [
            p
            for p in STATIC.rglob("*.html")
            if "node_modules" not in p.parts
        ]
        for path in ROUND8_SHEETS:
            name = "./" + path.name
            consumers = [
                p.relative_to(STATIC).as_posix()
                for p in html_files
                if name in p.read_text(encoding="utf-8")
            ]
            for consumer in consumers:
                self.assertEqual(
                    consumer, "index.html", f"{path.name} loaded by {consumer}"
                )

    def test_index_loads_tokens_before_round8_sheets(self) -> None:
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        for path in ROUND8_SHEETS:
            self.assertLess(
                index.index("padiem-tokens.css"),
                index.index("./" + path.name),
                path.name,
            )


if __name__ == "__main__":
    unittest.main()
