"""#8715/8712/8706: browser QA must wait for visibility and settled animation.

The assertions and their time budgets are unchanged. These tests only pin that
the flaky click/scroll checks gained a precise wait condition instead.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class BrowserWaitContract(unittest.TestCase):
    def test_sidebar_profile_click_waits_for_visible_toggle(self):
        text = (SCRIPTS / "b62_sidebar_ia_browser_qa.py").read_text(encoding="utf-8")
        marker = '#7780: 설정은 프로필 메뉴 안에 있다.'
        block = text.split(marker, 1)[1].split('await settings_row.wait_for', 1)[0]
        self.assertIn('wait_for_function', block)
        self.assertIn("state === 'guest' || state === 'expired'", block)
        self.assertIn('await settings.wait_for(state="visible"', block)
        self.assertIn('await settings.click()', block)

    def test_visual_qa_profile_click_waits_for_visible_toggle(self):
        text = (SCRIPTS / "b62_browser_visual_qa.py").read_text(encoding="utf-8")
        block = text.split('APPEARANCE controls must expose', 1)[1].split(
            'await page.locator("#settingsButton").click()', 1)[0]
        self.assertIn('wait_for_function', block)
        self.assertIn('await profile.wait_for(state="visible"', block)
        self.assertIn('await profile.click()', block)

    def test_glass_zoom_waits_for_scroll_to_settle_after_fixed_sleep(self):
        text = (SCRIPTS / "b62_glass_zoom_visual_qa.py").read_text(encoding="utf-8")
        block = text.split('await page.wait_for_timeout(350)', 1)[1].split(
            'followed = await page.evaluate(', 1)[0]
        self.assertIn('wait_for_function(', block)
        self.assertIn('scrollHeight - conv.scrollTop - conv.clientHeight <= 4', block)
        self.assertIn('timeout=5_000', block)
        self.assertIn('latest-answer growth was not followed', text)

    def test_no_wait_timeout_was_shortened(self):
        for name, forbidden in (
            ("b62_sidebar_ia_browser_qa.py", "timeout=100"),
            ("b62_browser_visual_qa.py", "timeout=100"),
            ("b62_glass_zoom_visual_qa.py", "wait_for_timeout(100)"),
        ):
            text = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
