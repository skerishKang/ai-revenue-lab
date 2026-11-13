"""#7574 항목 5·6·8·9·10·11 브라우저 검증.

390·820·1440 에서 실제 화면을 띄워 다음을 확인한다.
5  새 사용자의 번역본 표시 기본값은 '영어 작게'이고, 사용자가 고른 값은
   다시 열어도 그대로다.
6  검색 패널은 접힌 채 한 줄(휴대폰은 44px 아이콘)이고, 펼친 결과는 본문을
   밀지 않는 드롭다운이며, "더 보기"는 앱 버튼 모양이다.
8  오늘 화면의 "← 서재", "전체 기억", "전체 기억 보기", 필터 칩, "필터 초기화"가
   44×44px 이상이다.
9  절 번호 색이 종이·밝게·세피아·어둡게·사용자 지정 어두운 종이에서 모두
   본문 바탕과 4.5:1 이상이다.
10 신약/구약 버튼 위쪽 가운데를 찍으면 그 버튼이 나오고, 책 등 글씨가 4.5:1 이상이다.
11 휴대폰 기억 시트의 위쪽 빈 줄이 줄고 "현재 읽기 / 전체 기억"이 14px 이상이다.

서버는 이 파일이 직접 띄우고(임시 포트), 브라우저는 테스트가 끝나면 닫는다.
"""

from __future__ import annotations

import http.server
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

PUBLIC = Path(__file__).resolve().parents[1] / "public"
CHROME = next(
    (
        candidate
        for candidate in (
            os.environ.get("B61_CHROME_PATH"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        if candidate and Path(candidate).is_file()
    ),
    None,
)

VIEWPORTS = [
    ("phone-390", 390, 844),
    ("tablet-820", 820, 1180),
    ("desktop-1440", 1440, 900),
]


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    # The reader requests many stylesheets and scripts at once. The default
    # listen backlog (5) refuses late connections under a real Chrome, which
    # would make this UI check fail before it starts.
    request_queue_size = 256
    daemon_threads = True


@pytest.fixture(scope="module")
def base_url():
    server = StaticServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        launched = (
            playwright.chromium.launch(headless=True, executable_path=CHROME)
            if CHROME
            else playwright.chromium.launch(headless=True)
        )
        yield launched
        launched.close()


def _luminance(rgb_text: str) -> float:
    channels = [float(value) / 255 for value in rgb_text.strip("rgba() ").split(",")[:3]]

    def linear(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * linear(channels[0]) + 0.7152 * linear(channels[1]) + 0.0722 * linear(channels[2])


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _composite(color: str, background: str, alpha: float) -> str:
    fg = [float(value) for value in color.strip("rgba() ").split(",")[:3]]
    bg = [float(value) for value in background.strip("rgba() ").split(",")[:3]]
    return "rgb({})".format(", ".join(str(round(alpha * f + (1 - alpha) * b)) for f, b in zip(fg, bg)))


def _open_settings(page):
    page.locator("#smalOverflowBtn").click()
    page.locator(".smal-overflow-menu .srsg-btn").click()
    panel = page.locator(".srsg-panel")
    panel.wait_for(state="visible")
    return panel


def _inject_reader_fixture(page):
    page.evaluate(
        """() => {
          const bundle = {
            mode: 'static',
            content: {kind: 'bible'},
            work: {work_key: 'bible-web'},
            passages: [{
              id: 'fixture-act-9-1', canonicalLocator: 'bible:web:ACT:9:1',
              sequence: 1, language: 'ko', text: '한글 본문 예시',
              sourceText: 'English passage example', locator: {verse: 1},
              sourceRef: null
            }]
          };
          const built = storyMemoryBuildDynamicReaderPages(bundle);
          READER_PAGES = built.pages;
          readerPageIndex = 0;
          __smDynamicReaderState = {
            generation: 1, mode: 'static', content: bundle.content,
            work: bundle.work, unitOrdinal: 1, passages: built.passages,
            pagePassages: built.groups, pageSourceRefs: built.pageSourceRefs,
            remoteError: null
          };
          document.getElementById('readerVolumeTitle').textContent = '사도행전';
          document.getElementById('readerChapterTitle').textContent = '9장';
          document.getElementById('readerPageBody').innerHTML = built.pages[0];
        }"""
    )


def _open_reader_page(browser, base_url, width, height):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.set_default_timeout(30000)
    page.goto(base_url + "?view=reader", wait_until="domcontentloaded")
    page.wait_for_function(
        "() => window.BookAIReady && window.__smReaderSettingsV1"
        " && typeof window.__smReaderSettingsV1.get === 'function'"
    )
    page.wait_for_selector("#smalOverflowBtn")
    page.wait_for_selector("#readerPageBody")
    return page


def _verse_ink(page):
    data = page.evaluate(
        """() => {
          const vn = document.querySelector('#readerPageBody .vn');
          const paper = document.getElementById('paper');
          const style = getComputedStyle(vn);
          return {
            color: style.color,
            background: getComputedStyle(paper).backgroundColor,
            opacity: style.opacity,
            ink: paper.style.getPropertyValue('--sm-vn-ink')
          };
        }"""
    )
    return data, _contrast(data["color"], data["background"])


@pytest.mark.parametrize("label,width,height", VIEWPORTS)
def test_7574_polish_at_width(browser, base_url, label, width, height):
    page = _open_reader_page(browser, base_url, width, height)
    try:
        # ---- 5: 새 사용자 기본값 '영어 작게' --------------------------------
        assert page.evaluate("window.__smReaderSettingsV1.get().englishMode") == "compact", label
        assert page.evaluate("document.body.classList.contains('smr-en-compact')"), label
        _inject_reader_fixture(page)
        sizes = page.evaluate(
            """() => ({
              ko: parseFloat(getComputedStyle(document.querySelector('#readerPageBody .verse[lang="ko"]')).fontSize),
              en: parseFloat(getComputedStyle(document.querySelector('#readerPageBody .verse-en')).fontSize),
              vn: document.querySelectorAll('#readerPageBody .vn').length
            })"""
        )
        assert sizes["en"] < sizes["ko"], f"{label}: compact mode must keep English smaller: {sizes}"
        assert sizes["vn"] > 0, f"{label}: fixture page has no verse number"

        panel = _open_settings(page)
        language = panel.get_by_role("group", name="번역본 표시")
        assert language.get_by_role("button", name="영어 작게").get_attribute("aria-pressed") == "true", label

        # 사용자가 고른 값은 저장되고 다시 열어도 유지된다.
        language.get_by_role("button", name="한영 함께").click()
        page.evaluate("() => BookAILocalDB.flush()")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function(
            "() => window.BookAIReady && window.__smReaderSettingsV1"
            " && typeof window.__smReaderSettingsV1.get === 'function'"
        )
        assert page.evaluate("window.__smReaderSettingsV1.get().englishMode") == "show", label
        panel = _open_settings(page)
        assert panel.get_by_role("group", name="번역본 표시").get_by_role(
            "button", name="한영 함께"
        ).get_attribute("aria-pressed") == "true", f"{label}: stored choice was overwritten"
        panel.locator(".srsg-x").click()

        _inject_reader_fixture(page)

        # ---- 6: 접힌 검색 패널과 드롭다운 --------------------------------
        panel_box = page.evaluate(
            """() => { const el=document.getElementById('bibleSearchPanel'); const r=el.getBoundingClientRect();
              return {w:+r.width.toFixed(1),h:+r.height.toFixed(1),open:el.open}; }"""
        )
        assert panel_box["h"] <= 48, f"{label}: collapsed search panel is {panel_box}"
        if width <= 720:
            assert panel_box["w"] <= 48, f"{label}: phone search trigger must be one icon: {panel_box}"
        else:
            assert panel_box["w"] > 100, f"{label}: desktop search panel must stay one line: {panel_box}"

        body_before = page.evaluate("document.getElementById('readerPageBody').getBoundingClientRect().top")
        page.evaluate("() => document.querySelector('#bibleSearchPanel summary').click()")
        page.wait_for_function("() => document.getElementById('bibleSearchPanel').open")
        page.wait_for_timeout(160)
        opened = page.evaluate(
            """() => { const panel=document.getElementById('bibleSearchPanel');
              const body=document.getElementById('readerPageBody').getBoundingClientRect();
              const content=panel.querySelector('.bible-search-content');
              const rect=content.getBoundingClientRect();
              return {bodyTop:+body.top.toFixed(1),position:getComputedStyle(content).position,
                contentTop:+rect.top.toFixed(1),panelBottom:+panel.getBoundingClientRect().bottom.toFixed(1)}; }"""
        )
        assert abs(opened["bodyTop"] - body_before) < 4, f"{label}: search results moved the body: {opened}"
        assert opened["position"] in ("absolute", "fixed"), f"{label}: results must float: {opened}"
        assert opened["contentTop"] >= opened["panelBottom"] - 1, f"{label}: dropdown position: {opened}"

        more = page.evaluate(
            """() => { const panel=document.getElementById('bibleSearchPanel');
              const el=document.createElement('button'); el.type='button';
              el.className='bible-search-more'; el.textContent='더 보기';
              panel.querySelector('.bible-search-content').appendChild(el);
              const r=el.getBoundingClientRect(); const c=getComputedStyle(el);
              const result={w:+r.width.toFixed(1),h:+r.height.toFixed(1),radius:c.borderRadius,bg:c.backgroundColor,font:c.fontSize};
              el.remove(); return result; }"""
        )
        assert more["h"] >= 44, f"{label}: 더 보기 touch height {more}"
        assert more["radius"] not in ("", "0px"), f"{label}: 더 보기 keeps the browser default shape: {more}"
        assert more["bg"] not in ("", "rgba(0, 0, 0, 0)"), f"{label}: 더 보기 keeps the browser default fill: {more}"
        page.evaluate("() => { const p=document.getElementById('bibleSearchPanel'); if(p) p.open=false; }")

        # ---- 9: 테마별 절 번호 대비 --------------------------------------
        settings = _open_settings(page)
        theme = settings.get_by_role("group", name="테마 · 배경")
        theme.get_by_role("button", name="현재(#fffdf8)").click()
        for theme_name in ("현재(#fffdf8)", "밝게", "세피아", "어둡게"):
            theme.get_by_role("button", name=theme_name).click()
            page.wait_for_timeout(160)
            data, ratio = _verse_ink(page)
            assert ratio >= 4.5, f"{label}: verse number contrast {theme_name} = {ratio:.2f} ({data})"
        theme.get_by_role("button", name="현재(#fffdf8)").click()
        page.wait_for_timeout(160)
        settings.locator(".srsg-x").click()
        page.evaluate("() => setPaper('#202020')")
        page.wait_for_timeout(200)
        data, ratio = _verse_ink(page)
        assert ratio >= 4.5, f"{label}: verse number contrast on custom dark paper = {ratio:.2f} ({data})"
        page.evaluate("() => setPaper('#fffdf8')")

        # ---- 11: 휴대폰 기억 시트 ----------------------------------------
        if width <= 720:
            page.evaluate("() => document.getElementById('memoryRailTab').click()")
            page.wait_for_function("() => document.body.classList.contains('memory-open')")
            page.wait_for_timeout(500)
            memory = page.evaluate(
                """() => { const rail=document.querySelector('.reader-layout > .memory-rail');
                  const rr=rail.getBoundingClientRect();
                  const head=rail.querySelector('.side-head').getBoundingClientRect();
                  const button=rail.querySelector('.memory-scope-toggle button');
                  const br=button.getBoundingClientRect(); const style=getComputedStyle(button);
                  return {railTop:+rr.top.toFixed(1),headTop:+head.top.toFixed(1),
                    buttonW:+br.width.toFixed(1),buttonH:+br.height.toFixed(1),font:parseFloat(style.fontSize),
                    folio:getComputedStyle(rail.querySelector('.rail-folio')).display}; }"""
            )
            assert memory["headTop"] - memory["railTop"] <= 16, f"{label}: memory sheet top gap {memory}"
            assert memory["font"] >= 14, f"{label}: 현재 읽기/전체 기억 font {memory}"
            assert memory["buttonH"] >= 44, f"{label}: scope touch height {memory}"
            assert memory["folio"] == "none", f"{label}: memory sheet still shows the empty rail folio {memory}"
            page.evaluate("() => document.getElementById('memoryRailTab').click()")

        # ---- 8: 오늘 화면 터치 영역 --------------------------------------
        page.goto(base_url + "?view=today", wait_until="domcontentloaded")
        page.evaluate("() => window.BookAIReady")
        page.wait_for_function("() => typeof renderTodayHome === 'function' && typeof transitionTo === 'function'")
        page.evaluate("() => { renderTodayHome(); transitionTo('today'); }")
        page.wait_for_timeout(500)
        targets = page.evaluate(
            """() => { const list=[['#todayBack','← 서재'],['#todayOpenGlobal','전체 기억'],
                ['#todayAllMemoryBtn','전체 기억 보기'],['.sm-journal-clear','필터 초기화']];
              const out=list.map(([sel,text])=>{const el=document.querySelector(sel); if(!el) return {text,missing:true};
                const r=el.getBoundingClientRect(); return {text,w:+r.width.toFixed(1),h:+r.height.toFixed(1)};});
              const chips=Array.from(document.querySelectorAll('#today .sm-journal-chip')).map(el=>{
                const r=el.getBoundingClientRect(); return {text:el.textContent.trim(),w:+r.width.toFixed(1),h:+r.height.toFixed(1)};});
              return out.concat(chips); }"""
        )
        assert targets, label
        for target in targets:
            assert not target.get("missing"), f"{label}: missing touch target {target}"
            assert target["h"] >= 44 and target["w"] >= 44, f"{label}: touch target under 44px {target}"

        # ---- 10: 장 선택 머리줄과 책 등 글씨 ------------------------------
        # 읽던 위치가 저장돼 있으면 '책 열기'는 읽기 화면으로 이어지므로, 장 선택
        # 화면 자체의 배치는 화면 전환으로 연다.
        page.evaluate("() => transitionTo('index')")
        page.wait_for_timeout(900)
        screen = page.evaluate("() => ({active:document.querySelector('.screen.active')?.id, body:document.body.className})")
        assert screen["active"] == "index", f"{label}: index screen did not open: {screen}"
        page.wait_for_timeout(300)
        hit = page.evaluate(
            """() => { const sc=document.getElementById('index');
              const tab=document.querySelector('#index .testament-tab.on');
              if(window.innerWidth<=720) sc.scrollTop=tab.offsetTop-10;
              else sc.scrollTop=0;
              const r=tab.getBoundingClientRect();
              const target=document.elementFromPoint(r.left+r.width/2, r.top+2);
              return {top:+r.top.toFixed(1),hit:target?(target===tab||tab.contains(target)):false,
                why:target?(target.id||String(target.className).slice(0,40)):null}; }"""
        )
        assert hit["hit"] is True, f"{label}: 신약/구약 top is covered by {hit['why']} at y={hit['top']}"

        volume = page.evaluate(
            """() => { const list=Array.from(document.querySelectorAll('#index .volume'));
              const el=list.find(node=>!node.classList.contains('on'))||list[0];
              const b=el.querySelector('b'), small=el.querySelector('small');
              const body=document.getElementById('index').querySelector('.index-body');
              return {opacity:parseFloat(getComputedStyle(el).opacity),
                bg:getComputedStyle(el).backgroundColor,
                name:getComputedStyle(b).color, small:getComputedStyle(small).color,
                behind:getComputedStyle(body).backgroundColor}; }"""
        )
        alpha = volume["opacity"]
        page_bg = volume["behind"]
        for key in ("name", "small"):
            text = _composite(volume[key], page_bg, alpha)
            cloth = _composite(volume["bg"], page_bg, alpha)
            ratio = _contrast(text, cloth)
            assert ratio >= 4.5, f"{label}: book spine {key} contrast = {ratio:.2f} ({volume})"
    finally:
        page.close()
