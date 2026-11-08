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

HERE = Path(__file__).resolve().parent
ROOT = HERE.resolve().parents[0]  # apps/padiem-chat
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
UTIL_CSS = (STATIC / "util-menu.css").read_text(encoding="utf-8")
POLISH = (STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
UTIL_JS = (STATIC / "util-menu.js").read_text(encoding="utf-8")


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
        # #7162's shared primary rule lists .util-tool-open: navy + white.
        self.assertIn(".claw-inbox-primary, .util-tool-open, .pdfmd-btn-primary, #meetingStart) {", POLISH)
        rule_start = POLISH.index(".claw-inbox-primary, .util-tool-open, .pdfmd-btn-primary, #meetingStart) {")
        block = POLISH[rule_start:POLISH.index("}", rule_start)]
        self.assertIn("background: #355977", block)
        self.assertIn("border-color: #294b64", block)
        self.assertIn("color: #fff", block)
        # The pill shape is the util button's own rule.
        self.assertIn("border-radius: 999px", UTIL_CSS)
        # The old glass-only navy override is superseded by the shared rule.
        self.assertNotIn("html[data-theme=\"padiem-glass\"] .util-tool-open", UTIL_CSS)

    def test_card_border_uses_the_first_screen_token(self):
        card = UTIL_CSS[UTIL_CSS.index(".util-tool-card {"):UTIL_CSS.index("}", UTIL_CSS.index(".util-tool-card {"))]
        self.assertIn("border: 1px solid var(--line", card)
        self.assertNotIn("input-border-strong", card)

    def test_reopening_the_page_resets_the_heading(self):
        # showUtil puts the UTIL first-screen heading back: a tool's title
        # (PDF → Markdown) belongs to the moments that tool is open.
        self.assertIn("function showUtil", UTIL_JS)
        reset = UTIL_JS[UTIL_JS.index("function showUtil"):UTIL_JS.index("function setUtilSubmenuOpen")]
        self.assertIn('"Util"', reset)
        self.assertIn("자주 쓰는 문서·홍보 도구 모음", reset)


if __name__ == "__main__":
    unittest.main()
