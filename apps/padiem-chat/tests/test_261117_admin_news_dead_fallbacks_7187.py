"""#7187 R3 후속 — 새 소식 시트의 죽은 fallback만 제거했음을 검사한다.

안전한 토큰 판정은 페이지별로 다르다.

* ``theme-init.js``를 로드해 ``data-theme``을 붙이는 페이지에서만 쓰이는 시트:
  ``padiem-tokens.css``의 ``:root`` ∪ 다섯 테마 블록 교집합.
* 그렇지 않은 페이지(관리 3페이지)에서 쓰이는 시트:
  ``padiem-tokens.css``의 ``:root`` ∪ 그 시트 자신의 ``:root``에 정의된 토큰만.

관리 시트의 ``var(--radius-md, 16px)``는 두 번째 경우에 해당해 fallback이
실제로 쓰이므로 유지한다. 기존 ``test_261112_dead_fallbacks_7187.py``의
단언은 바꾸지 않고 이 파일에서 검사 범위만 넓힌다.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
TOKENS = STATIC / "padiem-tokens.css"
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
ADMIN_PAGES = ("admin.html", "admin-models.html", "credential-slots.html")
ADMIN_SHEETS = ("admin.css", "admin-models.css")
MCP_SHEET = "mcp-gateway-settings.css"
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


class TestPageScopedSafeTokens(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tokens = TOKENS.read_text(encoding="utf-8")
        cls.token_root = _names(_block(cls.tokens, ":root"))
        cls.theme_blocks = {
            theme: _names(_block(cls.tokens, 'html[data-theme="%s"]' % theme))
            for theme in THEMES
        }
        cls.themed_safe = cls.token_root | set.intersection(*cls.theme_blocks.values())

    def test_admin_pages_do_not_load_theme_init(self) -> None:
        for page in ADMIN_PAGES:
            text = (STATIC / page).read_text(encoding="utf-8")
            self.assertNotIn("theme-init.js", text, page)
            self.assertNotIn("data-theme", text, page)
            self.assertIn("padiem-tokens.css", text, page)

    def test_admin_sheets_keep_fallbacks_for_theme_only_tokens(self) -> None:
        """관리 페이지는 data-theme이 없어 --radius-md fallback이 실제 값이다."""
        self.assertNotIn("--radius-md", self.token_root)
        for theme in THEMES:
            self.assertIn("--radius-md", self.theme_blocks[theme])
        for name in ADMIN_SHEETS:
            text = (STATIC / name).read_text(encoding="utf-8")
            own_root = _names(_block(text, ":root")) if ":root" in text else set()
            page_safe = self.token_root | own_root
            offenders = []
            for match in VAR.finditer(text):
                token = match.group(1)
                if token not in page_safe:
                    continue  # 테마 전용 토큰이므로 fallback이 실제로 쓰인다.
                depth = 1
                index = match.end()
                while depth and index < len(text):
                    if text[index] == "(":
                        depth += 1
                    elif text[index] == ")":
                        depth -= 1
                    index += 1
                fallback = text[match.end():index - 1].strip()
                if re.fullmatch(r"[-+]?\d*\.?\d+(px|rem|em|%)?", fallback):
                    line = text.count("\n", 0, match.start()) + 1
                    offenders.append(f"{name}:{line} {token}")
            self.assertEqual(offenders, [], "page-scope에서 죽은 fallback은 없어야 한다")
            self.assertIn("var(--radius-md, 16px)", text, name)

    def test_chat_news_is_loaded_only_from_index(self) -> None:
        users = [p.name for p in STATIC.glob("*.html")
                 if "chat-news.css" in p.read_text(encoding="utf-8")]
        self.assertEqual(users, ["index.html"])
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("theme-init.js", index)
        self.assertLess(index.index("padiem-tokens.css"), index.index("chat-news.css"))

    def test_text_is_defined_in_every_theme(self) -> None:
        for theme in THEMES:
            self.assertIn("--text", self.theme_blocks[theme], theme)

    def test_chat_news_drops_only_the_dead_fallback(self) -> None:
        text = (STATIC / "chat-news.css").read_text(encoding="utf-8")
        self.assertIn("--text", self.themed_safe)
        self.assertNotIn("var(--text, #151820)", text)
        self.assertIn("var(--text)", text)
        for theme in THEMES:
            self.assertIn("--news-dialog-surface", self.theme_blocks[theme], theme)
        self.assertNotIn("var(--surface, #fff)", text)
        self.assertIn("var(--news-dialog-surface)", text)

    def test_mcp_settings_is_loaded_only_from_index(self) -> None:
        users = [p.name for p in STATIC.glob("*.html")
                 if MCP_SHEET in p.read_text(encoding="utf-8")]
        self.assertEqual(users, ["index.html"])
        index = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("theme-init.js", index)
        self.assertLess(index.index("padiem-tokens.css"), index.index(MCP_SHEET))

    def test_mcp_settings_has_no_dead_literal_fallbacks(self) -> None:
        """theme-init이 data-theme을 항상 붙여 5테마 공통 토큰의 fallback은 죽었다."""
        for token in ("--muted", "--success", "--danger"):
            self.assertIn(token, self.themed_safe)
            self.assertNotIn(token, self.token_root)
        text = (STATIC / MCP_SHEET).read_text(encoding="utf-8")
        offenders = []
        for match in VAR.finditer(text):
            token = match.group(1)
            if token not in self.themed_safe:
                continue
            depth = 1
            index = match.end()
            while depth and index < len(text):
                if text[index] == "(":
                    depth += 1
                elif text[index] == ")":
                    depth -= 1
                index += 1
            fallback = text[match.end():index - 1].strip()
            if re.fullmatch(r"[-+]?\d*\.?\d+(px|rem|em|%)?|#[0-9a-fA-F]{3,8}", fallback):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{MCP_SHEET}:{line} {token}")
        self.assertEqual(offenders, [])
        for old in ("var(--muted, #53606c)", "var(--success, #1a6b3a)",
                    "var(--danger, #ff8a80)"):
            self.assertNotIn(old, text)
