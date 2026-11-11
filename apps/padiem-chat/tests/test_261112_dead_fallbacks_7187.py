"""#7187 R3 6차 — 정의가 보장된 토큰의 죽은 ``var(--token, 숫자)`` fallback 제거.

4차(#7494)·5차(#7499) 뒤에 남은 fallback을 정리하는 단계다. 제거 대상은
``padiem-tokens.css``가 **다섯 테마 모두**에서 값을 정의하는 토큰만이다
(``:root`` 기본값 또는 다섯 테마 블록 전부). 그 밖의 토큰 — 예를 들어
``--card-shadow``·``--radius-md``처럼 일부 테마에만 정의된 이름 — 은 어떤
테마에서는 fallback이 실제 값이므로 이번 단계에서 지우지 않았다. 목록과
판단 근거는 PR 본문과 ``padiem-reports/2026-11-12/7187-r3-6-dead-fallbacks``
에 있다.

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
)

#: 토큰이 일부 테마에만 정의돼 있어 이번에 지우지 않은 시트(경계 고정).
KEPT = (
    STATIC / "help.css",
    STATIC / "help-tutorials" / "tutorial.css",
    STATIC / "padiem-home.css",
    STATIC / "util-menu.css",
    STATIC / "mcp-gateway-settings.css",
    STATIC / "connector-pages.css",
    STATIC / "capability-nav.css",
)

#: glass의 --card-bg는 padiem-glass-portrait.css가 로드 순서상 소유한다(5차 예외).
GLASS_CARD_BG_EXCEPTION = "--card-bg"

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


if __name__ == "__main__":
    unittest.main()
