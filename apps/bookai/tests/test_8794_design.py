"""#8794 성경 검색: 실제 화면의 일곱 디자인 계약."""
import os
import unittest
from playwright.sync_api import sync_playwright

BASE = os.environ.get("BOOKAI_BASE_URL", "http://127.0.0.1:9527/")
CHROME = os.environ.get("BOOKAI_CHROME_PATH")
HINT = "성경 전체에서 찾습니다. 결과를 눌러도 읽던 곳은 그대로입니다."

def luminance(rgb):
    channels = [int(x) / 255 for x in __import__("re").findall(r"[\d.]+", rgb)[:3]]
    adjusted = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return sum(a * b for a, b in zip(adjusted, (.2126, .7152, .0722)))

def ratio(a, b):
    x, y = luminance(a), luminance(b)
    return (max(x, y) + .05) / (min(x, y) + .05)

class BibleSearchDesign(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runner = sync_playwright().start()
        cls.browser = cls.runner.chromium.launch(headless=True, **({"executable_path": CHROME} if CHROME else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.runner.stop()

    def open_reader(self, width=390, theme="default"):
        page = self.browser.new_page(viewport={"width":width, "height":844 if width==390 else 900},
                                     reduced_motion="reduce")
        page.add_init_script("window.__smBibleSearchNoPrefetch=true")
        page.goto(BASE, wait_until="load")
        page.locator("#library.active").wait_for(timeout=30000)
        page.locator("#openBook").click()
        page.locator("#index.active").wait_for(timeout=30000)
        page.locator("#resume").click()
        page.locator("#reader.active").wait_for(timeout=30000)
        page.locator("#readerPageBody .sm-source-passage").first.wait_for(timeout=30000)
        if theme != "default":
            page.evaluate("theme => {document.body.classList.remove('smr-theme-dark','smr-theme-light','smr-theme-glass','smr-theme-sepia');document.body.classList.add('smr-theme-'+theme)}", theme)
        page.locator("#bibleSearchPanel summary").click()
        page.wait_for_timeout(400)
        return page

    def query(self, page, value):
        page.locator("#bibleSearchInput").fill(value)
        page.locator("#bibleSearchForm").press("Enter")
        page.wait_for_function("""() => {
          const s=document.querySelector('#bibleSearchStatus')?.textContent||'';
          return /구절을 찾았어요|개 결과 중|검색 결과가 없어요/.test(s);
        }""", timeout=180000)

    def test_1_opaque_panel(self):
        for theme in ("default", "dark", "glass", "light", "sepia"):
            page=self.open_reader(1440, theme)
            try:
                x=page.locator(".bible-search-content").evaluate(
                    "e=>getComputedStyle(e).backgroundColor")
                self.assertEqual(page.evaluate("c=>{let a=c.match(/^rgba?\\(([^)]*)\\)$/);return a&&a[1].split(',').length===4?Number(a[1].split(',')[3]):1}",x), 1, f"{theme}: {x}")
            finally: page.close()

    def test_2_1440_panel_width_matches_box(self):
        page=self.open_reader(1440)
        try:
            rect=page.evaluate("""() => {
              let p=document.querySelector('#bibleSearchPanel').getBoundingClientRect();
              let c=document.querySelector('.bible-search-content').getBoundingClientRect();
              return {left:Math.abs(p.left-c.left),right:Math.abs(p.right-c.right),p:p.width,c:c.width};
            }""")
            self.assertLessEqual(rect["left"],2,str(rect))
            self.assertLessEqual(rect["right"],2,str(rect))
        finally: page.close()

    def test_3_cancel_only_during_loading(self):
        page=self.open_reader(390)
        try:
            self.query(page, "요 3:16")
            self.assertTrue(page.locator("#bibleSearchCancel").evaluate("e=>e.hidden"),
                            "구절을 찾은 뒤 취소 단추가 남음")
            self.query(page, "태초에")
            self.assertTrue(page.locator("#bibleSearchCancel").evaluate("e=>e.hidden"),
                            "본문 결과가 나타난 뒤 취소 단추가 남음")
            self.query(page, "시그니처검색불가값구백팔십칠")
            self.assertTrue(page.locator("#bibleSearchCancel").evaluate("e=>e.hidden"),
                            "검색 결과가 없어도 취소 단추가 남음")
        finally: page.close()

    def test_4_confirmed_guidance(self):
        page=self.open_reader(390)
        try:
            self.assertEqual(page.locator(".bible-search-hint").inner_text().strip(),HINT)
        finally: page.close()

    def test_5_type_size_and_contrast(self):
        for width in (390,1440):
            for theme in ("default","dark","glass","light","sepia"):
                page=self.open_reader(width,theme)
                try:
                    self.query(page,"요 3:16")
                    data=page.evaluate("""() => {
                      const css=s=>getComputedStyle(document.querySelector(s));
                      return {
                        label:[css('.bible-search-content form label').fontSize,css('.bible-search-content form label').color],
                        status:[css('#bibleSearchStatus').fontSize,css('#bibleSearchStatus').color],
                        preview:[css('.bible-search-result span').fontSize,css('.bible-search-result span').color],
                        panelBg:css('.bible-search-content').backgroundColor,
                        resultBg:css('.bible-search-result').backgroundColor
                      };
                    }""")
                    self.assertGreaterEqual(float(data["label"][0][:-2]),12,str(data))
                    self.assertGreaterEqual(float(data["status"][0][:-2]),13,str(data))
                    self.assertGreaterEqual(float(data["preview"][0][:-2]),13,str(data))
                    self.assertGreaterEqual(ratio(data["label"][1],data["panelBg"]),4.5,str(data))
                    self.assertGreaterEqual(ratio(data["status"][1],data["panelBg"]),4.5,str(data))
                    self.assertGreaterEqual(ratio(data["preview"][1],data["resultBg"]),4.5,str(data))
                finally: page.close()

    def test_6_fade_and_twenty_more_each_click(self):
        page=self.open_reader(1440)
        try:
            self.query(page,"예수께서")
            count=lambda: page.locator("#bibleSearchResults .bible-search-result").count()
            self.assertEqual(count(),20)
            more=page.locator(".bible-search-more")
            self.assertEqual(more.inner_text().strip(),"결과 더 보기")
            self.assertGreaterEqual(more.bounding_box()["height"],44)
            fade=page.locator(".bible-search-list-wrap")
            self.assertTrue(fade.evaluate("e=>e.classList.contains('has-scroll-more')"),"목록 아래 흐림이 없음")
            for expected in (40,60,80):
                more.click()
                self.assertEqual(count(),expected,f"다음 20개: {expected}")
        finally: page.close()

    def test_7_query_bold_in_preview(self):
        page=self.open_reader(390)
        try:
            self.query(page,"예수께서")
            found=page.locator("#bibleSearchResults .bible-search-result span strong")
            self.assertGreater(found.count(),0,"검색어 강조 없음")
            self.assertIn("예수께서",found.first.inner_text())
        finally: page.close()

if __name__ == "__main__":
    unittest.main(verbosity=2)
