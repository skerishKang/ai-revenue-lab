# -*- coding: utf-8 -*-
"""#8805 공통 틀 디자인 수리 — 어둡게 글자 대비(D3)·낱말 줄바꿈(D2)·글씨 크게 검색 줄(D1).

정적 시험은 브라우저 없이 styles.css의 토큰과 규칙만 읽어 대비를 계산한다(CI에서 돈다).
브라우저 시험은 빌드한 7쪽을 헤드리스로 띄워 실제로 계산된 색·줄바꿈·검색 줄 위치를 잰다
(Playwright와 Chrome이 있는 곳에서만 돈다).
"""
from __future__ import annotations

import http.server
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from css_source import read_site_css

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

browser_only = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
CSS = read_site_css()
CHROME = next(
    (c for c in (os.environ.get("B61_CHROME_PATH"),
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe")
     if c and Path(c).is_file()),
    None,
)
PAGES = ("index.html", "about.html", "activity.html", "policy.html", "media.html", "news.html", "404.html")
WIDTHS = ((390, 844), (1440, 900))
DARK_GROUND = "#0b1a2e"  # 어둡게 --bg: 쪽 바탕·첫 화면 띠
DARK_SOFT = "#13233a"    # 어둡게 --navy-soft: 머리줄·아래 탭·카드
LIGHT_GROUNDS = ("#ffffff", "#f5f1e8")
IMPORTANT_BEFORE = 5  # 수리 전 main의 !important 수 — 새로 늘리지 않는다

# ── styles.css 읽기 ───────────────────────────────────────────────────────
CLEAN = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
RULES = []
for _sel, _body in re.findall(r"([^{}]+)\{([^{}]*)\}", CLEAN):
    _decls = {}
    for _part in _body.split(";"):
        if ":" in _part:
            _key, _value = _part.split(":", 1)
            _decls[_key.strip()] = _value.strip()
    RULES.append(([s.strip() for s in _sel.split(",")], _decls))


def _block(selector):
    for sels, decls in RULES:
        if sels == [selector]:
            return decls
    raise AssertionError(f"{selector} 블록이 없다")


DARK = dict(_block(":root"))  # :root 기본값이 어둡게
LIGHT = {**DARK, **_block('[data-theme="light"]')}


def _resolve(value, tokens, depth=0):
    match = re.fullmatch(r"var\((--[\w-]+)\)", value.strip())
    if not match:
        return value.strip().lower()
    assert depth < 6, value
    name = match.group(1)
    assert name in tokens, f"{name} 토큰이 없다"
    return _resolve(tokens[name], tokens, depth + 1)


def _decl(selector, prop):
    """그 선택자의 마지막 값. 어둡게 덮어쓰기([data-theme="dark"] ...)가 있으면 그것."""
    value = None
    for sels, decls in RULES:
        if selector in sels and prop in decls:
            value = decls[prop]
    for sels, decls in RULES:
        if f'[data-theme="dark"] {selector}' in sels and prop in decls:
            value = decls[prop]
    assert value is not None, f"{selector} {{ {prop} }} 이 없다"
    return value


def _lum(hex_value):
    hex_value = hex_value.lstrip("#")
    assert len(hex_value) == 6, hex_value
    channels = [int(hex_value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(fg, bg):
    a, b = _lum(fg), _lum(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


# CTO 판정에서 짚은 글자·선택 표시 (#8805 고칠 것 1)
DARK_TARGETS = [
    (".top-nav a:hover", "color", DARK_SOFT, 4.5),             # 머리줄 메뉴 마우스 올림
    (".top-nav a.active", "border-bottom-color", DARK_SOFT, 3.0),  # 머리줄 현재 쪽 밑줄
    (".mobile-tabbar a.active", "color", DARK_SOFT, 4.5),      # 아래 탭 선택 글자
    (".mobile-tabbar a.active", "border-top-color", DARK_SOFT, 3.0),  # 아래 탭 선택 윗줄
    (".hero-eyebrow", "color", DARK_GROUND, 4.5),              # 쪽 이름 위 눈썹 글자
    (".section-eyebrow", "color", DARK_GROUND, 4.5),
    (".ka-date", "color", DARK_SOFT, 4.5),                     # 카드 날짜
    (".ka-foot", "color", DARK_SOFT, 4.5),
    (".activity-item .item-date", "color", DARK_GROUND, 4.5),  # 목록 날짜
    (".activity-item .item-more", "color", DARK_GROUND, 4.5),  # '자세히 ›'
    (".section-more", "color", DARK_GROUND, 4.5),              # '전체 →'
    (".strip-link", "color", DARK_SOFT, 4.5),
]


def test_text_accent_tokens_read_on_both_grounds():
    for name in ("--accent-text", "--accent-2-text"):
        assert name in DARK, f"{name} 토큰이 :root에 없다"
    assert DARK["--accent-text"].lower() == "#7cc0ea"
    assert LIGHT["--accent-text"].lower() == "#004884"
    for name in ("--accent-text", "--accent-2-text"):
        for ground in (DARK_GROUND, DARK_SOFT):
            assert ratio(_resolve(f"var({name})", DARK), ground) >= 4.5, (name, ground)
        for ground in LIGHT_GROUNDS:
            assert ratio(_resolve(f"var({name})", LIGHT), ground) >= 4.5, (name, ground)


@pytest.mark.parametrize("selector,prop,ground,floor", DARK_TARGETS)
def test_dark_theme_marked_words_reach_contrast(selector, prop, ground, floor):
    value = _resolve(_decl(selector, prop), DARK)
    got = ratio(value, ground)
    assert got >= floor, f"어둡게 {selector} {prop} {value} / {ground} = {got:.2f}:1 (기준 {floor}:1)"


def test_light_theme_keeps_its_blues():
    """밝게 화면의 글자색은 수리 전과 같은 값이어야 한다(비교 화면 밖 차이 0)."""
    assert _resolve("var(--accent-text)", LIGHT) == _resolve("var(--accent)", LIGHT) == "#004884"
    assert _resolve("var(--accent-2-text)", LIGHT) == _resolve("var(--accent-2)", LIGHT) == "#00609c"


def test_no_text_colour_reads_a_fill_accent():
    """글자색은 글자용 토큰만 쓴다. 바탕·테두리용 --accent/--accent-2를 글자색으로 쓰면 어둡게에서 묻힌다."""
    bad = [", ".join(sels) for sels, decls in RULES
           for key, value in decls.items()
           if key == "color" and re.search(r"var\(--accent(-2)?\)", value)]
    assert not bad, bad


def test_fills_and_borders_keep_their_accent():
    """단추 바탕·테두리는 그대로."""
    assert _decl(".btn.primary", "background") == "var(--accent)"
    assert _decl(".btn.primary:hover", "background") == "var(--accent-2)"
    assert _decl(".top-cta", "background") == "var(--accent)"
    assert _decl(".top-cta:hover", "background") == "var(--accent-2)"
    assert _decl(".home-search-go:hover", "background") == "var(--accent)"
    assert _decl(".brand-mark", "background") == "var(--accent)"
    assert _decl(":focus-visible", "outline") == "2px solid var(--accent-2)"


def test_body_breaks_korean_at_words():
    body = {}
    for sels, decls in RULES:
        if sels == ["body"]:
            body.update(decls)
    assert body.get("word-break") == "keep-all", body.get("word-break")
    assert body.get("overflow-wrap") == "break-word", body.get("overflow-wrap")


def test_home_search_input_can_shrink_beside_its_button():
    assert _decl(".home-search-input", "min-width") == "0"


def test_no_new_important():
    assert CSS.count("!important") <= IMPORTANT_BEFORE


# ── 브라우저 시험 ────────────────────────────────────────────────────────
class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BUILD_DIR), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


BUILD_DIR = None


@pytest.fixture(scope="module")
def build_dir(tmp_path_factory):
    global BUILD_DIR
    out = tmp_path_factory.mktemp("councillor-8805-dist")
    result = subprocess.run(
        [sys.executable, "scripts/build-dist", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    BUILD_DIR = out
    return out


@pytest.fixture(scope="module")
def base_url(build_dir):
    server = StaticServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None or not CHROME:
        pytest.skip("playwright or Chrome is not installed")
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(headless=True, executable_path=CHROME)
        yield launched
        launched.close()


def _open(browser, base_url, page_name, width, height, theme="light", text_size=None):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme="light")
    script = f"localStorage.setItem('theme', '{theme}');"
    if text_size:
        script += f"localStorage.setItem('textSize', '{text_size}');"
    ctx.add_init_script(script)
    page = ctx.new_page()
    page.goto(base_url + page_name, wait_until="networkidle")
    page.evaluate("() => document.fonts.ready.then(() => true)")
    assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == theme
    return ctx, page


# 어둡게에서 파란 계열(#004884·#00609c·#7cc0ea)로 칠해진 글자·아이콘을 모두 찾아 대비를 잰다.
ACCENT_COLOURS = ["rgb(0, 72, 132)", "rgb(0, 96, 156)", "rgb(124, 192, 234)"]
CONTRAST_JS = r"""(accents) => {
  const parse = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lin = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  const lum = c => 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]);
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const ground = el => { const layers = [];
    for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    let rgb = [255, 255, 255];
    for (let i = layers.length - 1; i >= 0; i--) { const [r, g, b, a] = layers[i];
      rgb = [r * a + rgb[0] * (1 - a), g * a + rgb[1] * (1 - a), b * a + rgb[2] * (1 - a)]; }
    return rgb; };
  const opacity = el => { let a = 1; for (let e = el; e; e = e.parentElement) a *= parseFloat(getComputedStyle(e).opacity); return a; };
  const out = { checked: 0, fails: [] };
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    const prop = el.dataset.checkProp || 'color';
    const colour = cs.getPropertyValue(prop);
    if (!accents.includes(colour)) continue;
    const own = [...el.childNodes].some(n => n.nodeType === 3 && n.data.trim());
    const icon = !!el.querySelector(':scope > svg');
    if (prop === 'color' && !own && !icon) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.right < 0 || cs.visibility === 'hidden') continue;
    const bg = ground(prop === 'color' ? el : el.parentElement);
    const fg0 = parse(colour); const a = opacity(el) * fg0[3];
    const fg = [0, 1, 2].map(i => fg0[i] * a + bg[i] * (1 - a));
    const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight, 10);
    const need = prop !== 'color' || (icon && !own) || size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
    const value = ratio(fg, bg);
    out.checked++;
    if (value < need) out.fails.push(`${el.tagName}.${el.className} "${(el.innerText || '').trim().slice(0, 20)}" ${prop} ${colour} / rgb(${bg.map(Math.round)}) = ${value.toFixed(2)}:1 (기준 ${need})`);
  }
  return out;
}"""


@browser_only
@pytest.mark.parametrize("width,height", WIDTHS)
@pytest.mark.parametrize("page_name", PAGES)
def test_dark_accent_words_reach_contrast_in_the_browser(browser, base_url, page_name, width, height):
    ctx, page = _open(browser, base_url, page_name, width, height, theme="dark")
    try:
        result = page.evaluate(CONTRAST_JS, ACCENT_COLOURS)
        if page_name == "index.html":  # 새 소식처럼 파란 글자가 없는 쪽도 있다
            assert result["checked"] > 0, "홈에서 파란 글자를 하나도 찾지 못했다"
        assert not result["fails"], result["fails"]
    finally:
        ctx.close()


@browser_only
def test_dark_header_menu_hover_and_current_marks(browser, base_url):
    ctx, page = _open(browser, base_url, "activity.html", 1440, 900, theme="dark")
    try:
        page.hover(".top-nav a:not(.active)")
        page.wait_for_timeout(400)
        hovered = page.evaluate(CONTRAST_JS.replace("document.querySelectorAll('body *')",
                                                    "document.querySelectorAll('.top-nav a:hover')"),
                                ACCENT_COLOURS)
        assert hovered["checked"] == 1 and not hovered["fails"], hovered
        page.evaluate("() => { const a = document.querySelector('.top-nav a.active'); a.dataset.checkProp = 'border-bottom-color'; }")
        mark = page.evaluate(CONTRAST_JS.replace("document.querySelectorAll('body *')",
                                                 "document.querySelectorAll('.top-nav a.active')"),
                             ACCENT_COLOURS)
        assert mark["checked"] == 1 and not mark["fails"], mark
    finally:
        ctx.close()
    ctx, page = _open(browser, base_url, "activity.html", 390, 844, theme="dark")
    try:
        page.evaluate("() => { const a = document.querySelector('.mobile-tabbar a.active'); a.dataset.checkProp = 'border-top-color'; }")
        mark = page.evaluate(CONTRAST_JS.replace("document.querySelectorAll('body *')",
                                                 "document.querySelectorAll('.mobile-tabbar a.active')"),
                             ACCENT_COLOURS)
        assert mark["checked"] == 1 and not mark["fails"], mark
    finally:
        ctx.close()


# 한 낱말(글자·숫자가 이어진 묶음)이 두 줄로 갈라진 곳을 찾는다. 그 낱말이 칸보다 넓어
# 어쩔 수 없이 갈라진 경우는 세지 않는다.
SPLIT_JS = r"""() => {
  const word = /[\p{L}\p{N}]+/gu;
  const skip = 'script,style,noscript,select,option,textarea,[hidden]';
  const found = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node.parentElement;
    if (!el || el.closest(skip)) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const box = el.getBoundingClientRect();
    if (box.width < 4 || box.height < 4) continue;
    let block = el;
    while (block && getComputedStyle(block).display.startsWith('inline')) block = block.parentElement;
    const bcs = getComputedStyle(block);
    const room = block.clientWidth - parseFloat(bcs.paddingLeft) - parseFloat(bcs.paddingRight);
    let m;
    word.lastIndex = 0;
    while ((m = word.exec(node.data))) {
      if (m[0].length < 2) continue;
      const range = document.createRange();
      range.setStart(node, m.index); range.setEnd(node, m.index + m[0].length);
      const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0).sort((a, b) => a.top - b.top);
      if (rects.length < 2) continue;
      let lines = 1;
      for (let i = 1; i < rects.length; i++) if (rects[i].top - rects[i - 1].top > rects[i - 1].height / 2) lines++;
      if (lines < 2) continue;
      const wide = rects.reduce((s, r) => s + r.width, 0);
      if (wide > room) continue;
      found.push(`${m[0]} — "${node.data.trim().slice(0, 30)}" (${el.className || el.tagName})`);
    }
  }
  return found;
}"""


@browser_only
@pytest.mark.parametrize("width,height", WIDTHS)
@pytest.mark.parametrize("page_name", PAGES)
def test_no_word_splits_across_lines(browser, base_url, page_name, width, height):
    ctx, page = _open(browser, base_url, page_name, width, height)
    try:
        splits = page.evaluate(SPLIT_JS)
        assert splits == [], f"{page_name} {width}: 낱말 갈라짐 {len(splits)}곳 {splits[:12]}"
        overflow = page.evaluate("() => document.body.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"{page_name} {width}: 가로 넘침 {overflow}px"
    finally:
        ctx.close()


@browser_only
@pytest.mark.parametrize("width,height", ((360, 800), (390, 844)))
def test_large_text_home_search_button_stays_in_its_row(browser, base_url, width, height):
    ctx, page = _open(browser, base_url, "index.html", width, height, text_size="large")
    try:
        assert page.evaluate("() => document.documentElement.getAttribute('data-text-size')") == "large"
        field = page.locator(".home-search-input").bounding_box()
        button = page.locator(".home-search-go").bounding_box()
        same_row = abs(button["y"] - field["y"]) < 2
        full_below = abs(button["width"] - field["width"]) < 1 and button["y"] >= field["y"] + field["height"]
        assert same_row or full_below, f"{width}: 입력칸 {field} / 단추 {button}"
        assert field["height"] >= 44 and button["height"] >= 44, (field, button)
        assert button["x"] + button["width"] <= width, button
    finally:
        ctx.close()
