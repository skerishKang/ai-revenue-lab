"""#7172 — 유틸 첫 화면 계약.

- 제목·설명은 '유틸'(ko/en) — 도구 하나의 이름(PDF → Markdown)이 아니라.
- 카드의 열기 버튼은 #7162의 공용 주요 버튼 규칙(전송 버튼 남색 + 흰 글씨,
  알약 모양)을 입는다.
- 카드 테두리는 첫 화면 카드와 같은 옅은 토큰(var(--line)) —
  input-border-strong(진하고 두꺼움)이 아니다.
"""
from pathlib import Path
import re
import unittest

from css_rules import (
    declaration,
    find_rules_with_selector,
    is_list_items,
    parse_rules,
    rule_selector_list_contains,
    strip_comments,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.resolve().parents[0]  # apps/padiem-chat
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
UTIL_CSS = (STATIC / "util-menu.css").read_text(encoding="utf-8")
POLISH = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
UTIL_JS = (STATIC / "util-menu.js").read_text(encoding="utf-8")


def _by_state(blocks: list) -> dict:
    """Split the shared primary rule's blocks into base / hover / focus-visible."""
    states = {}
    for rule in blocks:
        state = "base"
        if any(selector.endswith(":hover") for selector in rule.selectors):
            state = "hover"
        elif any(selector.endswith(":focus-visible") for selector in rule.selectors):
            state = "focus"
        assert state not in states, f"two {state} blocks in the shared rule"
        states[state] = rule
    assert set(states) == {"base", "hover", "focus"}, states
    return states


def _targets(rule) -> frozenset:
    """Every target listed in the block's :is()/``:where()`` groups."""
    return frozenset(
        item for selector in rule.selectors for item in is_list_items(selector)
    )


class UtilFirstScreenContract(unittest.TestCase):
    def test_first_screen_heading_is_the_util_page_itself(self):
        start = INDEX.index('id="utilTitle"')
        heading = INDEX[max(0, start - 200):start + 300]
        self.assertIn('data-locale-key="util-title"', heading)
        self.assertIn('>유틸</h2>', heading)
        self.assertIn('data-locale-key="util-tagline"', heading)
        self.assertIn('자주 쓰는 문서·홍보 도구 모음', heading)
        # The PDF tool name is a CARD below, never the page heading.
        title_line = INDEX[INDEX.index('id="utilTitle"'):INDEX.index('id="utilTagline"')]
        self.assertNotIn("PDF → Markdown", title_line)

    def test_util_title_keys_exist_in_both_languages(self):
        self.assertIn('"util-title": "유틸"', LOCALE)
        self.assertIn('"util-tagline": "자주 쓰는 문서·홍보 도구 모음"', LOCALE)
        self.assertIn('"util-title": "Util"', LOCALE)
        self.assertIn('"util-tagline": "Everyday document & promo tools"', LOCALE)

    def test_open_buttons_reuse_the_shared_primary_rule(self):
        """#7162's shared primary rule names both util buttons in every state.

        #7186: the rule is read through css_rules -- selector-list membership
        and property values, not one formatted line. tests/test_css_rules_helper
        proves that reading is independent of order, wrapping and comments.
        """
        blocks = find_rules_with_selector(parse_rules(POLISH), ".util-tool-open")
        self.assertEqual(len(blocks), 3, "base, hover and focus-visible share one selector list")
        states = _by_state(blocks)
        base, hover, focus = states["base"], states["hover"], states["focus"]
        for block in blocks:
            self.assertTrue(rule_selector_list_contains(block, ".util-tool-open", ".pdfmd-btn-primary"))
        members = {_targets(rule) for rule in blocks}
        self.assertEqual(len(members), 1, "the three state blocks list the same targets")
        # #7187 R3: the rule names the tokens; the token file pins the numbers.
        self.assertEqual(declaration(base, "background"), "var(--primary-bg)")
        self.assertEqual(declaration(base, "border-color"), "var(--primary-border)")
        self.assertEqual(declaration(base, "color"), "#fff")
        self.assertEqual(declaration(hover, "background"), "var(--primary-hover-bg)")
        self.assertEqual(declaration(focus, "outline"), "3px solid var(--primary-focus)")
        # The pill shape is the util button's own rule.
        buttons = find_rules_with_selector(parse_rules(UTIL_CSS), ".util-tool-open")
        self.assertEqual(len(buttons), 1)
        self.assertEqual(declaration(buttons[0], "border-radius"), "999px")
        # The old glass-only navy override is superseded by the shared rule.
        self.assertNotIn(
            'html[data-theme="padiem-glass"] .util-tool-open', strip_comments(UTIL_CSS)
        )

    def test_card_border_uses_the_first_screen_token(self):
        """#7172: the card wears the shared hairline token, not the input token.

        #7186: the border is the rule's own declaration, so wrapping or moving
        the block does not change the verdict.
        """
        cards = find_rules_with_selector(parse_rules(UTIL_CSS), ".util-tool-card")
        self.assertEqual(len(cards), 1)
        border = declaration(cards[0], "border")
        self.assertTrue(border.startswith("1px solid var(--line"), border)
        self.assertEqual(
            [value for value in cards[0].declarations.values() if "input-border-strong" in value],
            [],
        )

    def test_reopening_the_page_resets_the_heading(self):
        # showUtil puts the UTIL first-screen heading back: a tool's title
        # (PDF → Markdown) belongs to the moments that tool is open.
        self.assertIn("function showUtil", UTIL_JS)
        reset = UTIL_JS[UTIL_JS.index("function showUtil"):UTIL_JS.index("function setUtilSubmenuOpen")]
        self.assertIn('"Util"', reset)
        self.assertIn("자주 쓰는 문서·홍보 도구 모음", reset)


if __name__ == "__main__":
    unittest.main()
