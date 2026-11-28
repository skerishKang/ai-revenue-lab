# -*- coding: utf-8 -*-
"""#8806 홈 디자인 수리 — 첫 화면 단추(D1)·안내 줄(D1)·제목 단계(D2)·바로가기 칩(D9)·배경 사진.

정적 시험은 styles.css·빌드한 index.html·사진 파일만 읽는다(CI에서 돈다).
브라우저 시험은 빌드한 홈을 헤드리스로 띄워 실제 위치·크기를 잰다
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

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

browser_only = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
IMAGES = ROOT / "static" / "images"
CHROME = next(
    (c for c in (os.environ.get("B61_CHROME_PATH"),
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe")
     if c and Path(c).is_file()),
    None,
)
IMPORTANT_BEFORE = 5  # 수리 전 main의 !important 수 — 새로 늘리지 않는다

# 배경 사진 오른쪽 건물의 빨간 틀 둘레(사진 화소 좌표 x0, y0, x1, y1)와 수리 전 파일 크기.
RED_FRAME = {
    "hero-panorama.webp": ((3100, 495, 3600, 640), (3840, 960), 175906),
    "hero-panorama-mobile.webp": ((1032, 163, 1202, 216), (1280, 320), 28332),
}

CLEAN = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


def _media_block(query):
    """'@media (min-width: 721px)' 같은 블록의 본문(중괄호 안)을 모두 이어 붙인다."""
    out = []
    for match in re.finditer(r"@media\s*" + re.escape(query) + r"\s*\{", CLEAN):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(CLEAN[i], 0)
            i += 1
        out.append(CLEAN[match.end():i - 1])
    return "\n".join(out)


def _decls(body, selector):
    found = {}
    for sel, block in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
        if selector in [s.strip() for s in sel.split(",")]:
            for part in block.split(";"):
                if ":" in part:
                    key, value = part.split(":", 1)
                    found[key.strip()] = value.strip()
    return found


# ── 정적 시험 ─────────────────────────────────────────────────────────────
def test_hero_actions_are_a_two_column_grid_from_721px():
    """(가) 721px 이상: 1fr 1fr 격자, 간격 12px, 묶음 폭은 검색 줄과 같은 560px."""
    rule = _decls(_media_block("(min-width: 721px)"), ".hero-actions")
    assert rule.get("display") == "grid", rule
    assert rule.get("grid-template-columns") == "1fr 1fr", rule
    assert rule.get("gap") == "12px", rule
    assert rule.get("max-width") == "560px", rule
    search = _decls(CLEAN, ".home-search")
    assert search.get("max-width") == "560px", search


def test_no_new_important():
    assert CSS.count("!important") <= IMPORTANT_BEFORE


BUILD_DIR = None


@pytest.fixture(scope="module")
def build_dir(tmp_path_factory):
    global BUILD_DIR
    out = tmp_path_factory.mktemp("councillor-8806-dist")
    result = subprocess.run(
        [sys.executable, "scripts/build-dist", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    BUILD_DIR = out
    return out


def test_home_shortcuts_have_no_diamond_and_mark_only_outside_sites(build_dir):
    """(라) 바로가기에 ◆가 없고, 바깥 사이트만 글자 뒤에 ↗가 붙는다."""
    html = (build_dir / "index.html").read_text(encoding="utf-8")
    grid = re.search(r'<div class="col-tile-grid" id="homeLinks">(.*?)</div>', html, re.S).group(1)
    chips = re.findall(r'<a class="col-tile"([^>]*)>(.*?)</a>', grid, re.S)
    assert len(chips) == 6, grid
    assert "◆" not in grid
    for attrs, inner in chips:
        text = re.sub(r"<[^>]+>", "", inner).strip()
        if 'target="_blank"' in attrs:
            assert text.endswith("↗") and text.count("↗") == 1, text
            assert re.search(r'<span class="ext-mark" aria-hidden="true">↗</span>\s*$', inner), inner
        else:
            assert "↗" not in text, text


@pytest.mark.parametrize("name", sorted(RED_FRAME))
def test_hero_photo_has_no_red_frame(name):
    """(마) 빨간 틀 둘레 안에 붉은 화소가 0. 크기·파일 크기는 수리 전과 비슷하다."""
    image_mod = pytest.importorskip("PIL.Image")
    box, size, bytes_before = RED_FRAME[name]
    path = IMAGES / name
    with image_mod.open(path) as im:
        assert im.size == size, im.size
        rgb = im.convert("RGB").crop(box)
        raw = rgb.tobytes()
        red = sum(1 for i in range(0, len(raw), 3)
                  if raw[i] > 140 and raw[i] - raw[i + 1] > 50 and raw[i] - raw[i + 2] > 50)
    assert red == 0, f"{name}: 빨간 틀 둘레 안 붉은 화소 {red}개"
    assert abs(path.stat().st_size - bytes_before) <= bytes_before * 0.1, path.stat().st_size


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


def _open(browser, base_url, width, height=900, theme="light"):
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme="light")
    ctx.add_init_script(f"localStorage.setItem('theme', '{theme}');")
    page = ctx.new_page()
    page.goto(base_url + "index.html", wait_until="networkidle")
    page.evaluate("() => document.fonts.ready.then(() => true)")
    return ctx, page


BOX = "(sel) => [...document.querySelectorAll(sel)].map(e => { const r = e.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height, r: r.right, b: r.bottom}; })"


@browser_only
@pytest.mark.parametrize("width", (820, 1440))
def test_hero_buttons_share_one_width_in_two_rows(browser, base_url, width):
    """(가) 단추 4개 폭이 같고 [전화|의정활동 보기]/[이메일|의견] 두 줄, 묶음 폭 = 검색 줄 폭."""
    ctx, page = _open(browser, base_url, width)
    try:
        b = page.evaluate(BOX, ".hero-actions .btn")
        texts = page.evaluate("() => [...document.querySelectorAll('.hero-actions .btn')].map(e => e.textContent.trim())")
        assert [t.split()[0] for t in texts] == ["의원실", "의정활동", "이메일", "의회"], texts
        widths = [round(x["w"]) for x in b]
        assert max(widths) - min(widths) <= 1, f"{width}: 단추 폭 {widths}"
        assert abs(b[0]["y"] - b[1]["y"]) < 1 and abs(b[2]["y"] - b[3]["y"]) < 1, b
        assert b[2]["y"] > b[0]["b"], b
        assert abs(b[0]["x"] - b[2]["x"]) < 1 and abs(b[1]["x"] - b[3]["x"]) < 1, b
        assert abs(b[1]["x"] - b[0]["r"] - 12) < 1, f"{width}: 단추 사이 {b[1]['x'] - b[0]['r']}px"
        actions = page.evaluate(BOX, ".hero-actions")[0]
        search = page.evaluate(BOX, ".home-search")[0]
        assert abs(actions["w"] - search["w"]) < 1 and abs(actions["x"] - search["x"]) < 1, (actions, search)
        aligns = page.evaluate("() => [...document.querySelectorAll('.hero-actions .btn')].map(e => getComputedStyle(e).justifyContent)")
        assert all(a in ("normal", "flex-start", "start") for a in aligns), aligns  # 글자는 왼쪽 정렬 그대로
    finally:
        ctx.close()


@browser_only
def test_hero_buttons_stay_one_per_row_on_phones(browser, base_url):
    ctx, page = _open(browser, base_url, 390, 844)
    try:
        b = page.evaluate(BOX, ".hero-actions .btn")
        assert all(abs(x["x"] - b[0]["x"]) < 1 and abs(x["w"] - b[0]["w"]) < 1 for x in b), b
        assert all(b[i + 1]["y"] > b[i]["b"] for i in range(3)), b
    finally:
        ctx.close()


TEXT_BOX = """(sel) => { const e = document.querySelector(sel); const range = document.createRange(); range.selectNodeContents(e);
  const r = range.getBoundingClientRect(); return {x: r.x, y: r.y, r: r.right, b: r.bottom}; }"""


@browser_only
@pytest.mark.parametrize("width", (820, 1000))
def test_strip_link_is_not_left_alone_on_tablets(browser, base_url, width):
    """(나) 721~1100px: '의회 공식 페이지'가 아래 줄 왼쪽에 혼자 떨어지지 않고 오른쪽 끝에 붙는다."""
    ctx, page = _open(browser, base_url, width)
    try:
        link = page.evaluate(TEXT_BOX, ".strip-link")
        items = page.evaluate(BOX, ".strip-item")
        right = max(i["r"] for i in items)
        same_row = abs(link["y"] - items[-1]["y"]) < items[-1]["h"]
        right_aligned = abs(link["r"] - right) <= 2 and link["x"] > items[-1]["x"]
        assert same_row or right_aligned, f"{width}: 링크 {link} / 안내 오른쪽 끝 {right}"
    finally:
        ctx.close()


@browser_only
def test_strip_link_keeps_its_desktop_place(browser, base_url):
    ctx, page = _open(browser, base_url, 1440)
    try:
        link = page.evaluate(BOX, ".strip-link")[0]
        items = page.evaluate(BOX, ".strip-item")
        assert link["x"] > items[-1]["r"] and abs((link["y"] + link["h"] / 2) - (items[-1]["y"] + items[-1]["h"] / 2)) < 2, (link, items)
    finally:
        ctx.close()


@browser_only
@pytest.mark.parametrize("width", (390, 1440))
def test_media_title_uses_the_section_title_step(browser, base_url, width):
    """(다) '미디어 · 자료'와 '주요 의정활동'의 글자 크기·자간·줄 높이·글꼴이 같다."""
    ctx, page = _open(browser, base_url, width)
    try:
        got = page.evaluate("""() => ['keyActTitle', 'colsTitle'].map(id => { const c = getComputedStyle(document.getElementById(id));
          return [c.fontSize, c.letterSpacing, c.lineHeight, c.fontFamily, c.fontWeight]; })""")
        assert got[0] == got[1], got
    finally:
        ctx.close()


@browser_only
@pytest.mark.parametrize("width", (820, 1440))
def test_home_shortcut_chips_match_the_policy_chips(browser, base_url, width):
    """(라) 바로가기 칩: 테두리·둥근 모서리·높이 44px 이상·간격 8px, ◆ 없음."""
    ctx, page = _open(browser, base_url, width)
    try:
        chips = page.evaluate("""() => [...document.querySelectorAll('#homeLinks .col-tile')].map(e => { const r = e.getBoundingClientRect(), c = getComputedStyle(e);
          return {x: r.x, y: r.y, r: r.right, h: r.height, text: e.innerText.trim(), border: c.borderTopWidth, style: c.borderTopStyle,
                  radius: parseFloat(c.borderTopLeftRadius)}; })""")
        assert len(chips) == 6, chips
        for chip in chips:
            assert chip["h"] >= 44, chip
            assert "◆" not in chip["text"], chip
            assert chip["border"] == "1px" and chip["style"] == "solid", chip
            assert chip["radius"] >= chip["h"] / 2 - 0.5, chip
        gaps = [round(b["x"] - a["r"], 1) for a, b in zip(chips, chips[1:]) if abs(a["y"] - b["y"]) < 1]
        assert gaps and all(abs(g - 8) < 0.6 for g in gaps), gaps
        rows = sorted({round(c["y"]) for c in chips})
        if len(rows) > 1:
            assert all(abs(b - a - (chips[0]["h"] + 8)) < 1 for a, b in zip(rows, rows[1:])), rows
    finally:
        ctx.close()
