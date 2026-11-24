"""대비 수리(261124) — 저장한 답변 창과 연결 카드의 글자 대비.

두 곳 모두 "판은 밝은데 글자색이 판을 따르지 않는" 같은 모양의 결함이었다.

* 저장한 답변 창: 글자·선은 창 스킨(``padiem-cinematic-workspace.css``)이 흰
  베일 ``--ws-*`` 값으로 칠한다. 판(``--surface-panel-solid``)은 #8024부터 밝은
  테마를 따라 밝아졌는데 그 잉크는 ``:root`` 값 그대로라 light·padiem-home·
  padiem-glass에서 밝은 판 위 흰 글자가 됐다. ``outputs.css``가 이 창 안에서만
  그 이름들을 판을 따르는 ``--outputs-*`` 토큰으로 되가리킨다.
* 연결 카드: 카드 판은 다섯 테마 모두 밝게 고정인데 카드 이름은 글자색을
  지정받지 못해 테마 글자색을 상속했고 상태 줄은 테마 ``--muted``를 읽어,
  dark·cinematic에서 흰 판 위 밝은 글자가 됐다. ``connector-pages.css``의 타일
  규칙과 상태 줄 규칙이 판을 따르는 ``--connector-card-*`` 잉크를 읽는다.

앞쪽 시험은 토큰 값으로 대비를 계산해 브라우저 없이 매 PR에서 돈다. 맨 아래
시험은 다섯 테마 × 두 폭에서 실제로 칠해진 픽셀로 같은 기준을 다시 잰다
(Playwright가 있는 환경에서만 실행).
"""
from __future__ import annotations

import io
import json
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from _support import contrast_repair_source as source

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"

THEMES = source.THEMES
BRIGHT_PANEL_THEMES = ("light", "padiem-home", "padiem-glass")
DARK_PANEL_THEMES = ("dark", "cinematic")

TEXT_AA = 4.5
LARGE_OR_ICON_AA = 3.0

#: 저장한 답변 창 잉크: --outputs 토큰 → 창 스킨이 읽는 이름.
SAVED_TEXT = {
    "--outputs-kicker-text": "--ws-dialog-kicker-text",
    "--outputs-control-text": "--ws-control-muted-text",
    "--outputs-control-hover-text": "--ws-control-hover-text",
    "--outputs-input-text": "--ws-input-text",
    "--outputs-content-text": "--ws-output-text",
    "--outputs-secondary-text": "--ws-secondary-text",
    "--outputs-primary-text": "--text-veil-strong",
    "--outputs-danger-text": "--ws-danger-text",
}
#: 같은 창의 선(입력칸·단추 경계, 구분선).
SAVED_EDGES = {
    "--outputs-rule-edge": "--ws-dialog-edge",
    "--outputs-content-edge": "--line-veil-dim",
    "--outputs-control-edge": "--ws-input-edge",
    "--outputs-control-focus-edge": "--ws-input-focus-edge",
    "--outputs-primary-edge": "--ws-control-hover-edge-strong",
    "--outputs-primary-hover-edge": "--line-veil-mist",
}
SAVED_TOKENS = {**SAVED_TEXT, **SAVED_EDGES}

CARD_INK = "--connector-card-ink"
CARD_MUTED_INK = "--connector-card-muted-ink"
#: 밝은 판을 정하는 규칙(standalone-views.css)과, 그 판 위 타일(connector-pages.css).
CARD_SELECTOR = "#connectorsViewBody .capability-card"
TILE_SELECTOR = "#connectorsGrid .capability-card.connector-tile"


# ── 저장한 답변 창: 토큰 계약 ────────────────────────────────────────────


def test_saved_output_inks_default_to_the_skin_values() -> None:
    """기본값은 창 스킨 값을 그대로 가리킨다 — dark·cinematic은 전과 같다."""
    root = source.root_declarations()
    for name, skin in SAVED_TOKENS.items():
        assert root.get(name) == f"var({skin})", name
    for theme in DARK_PANEL_THEMES:
        themed = source.theme_declarations(theme)
        for name, skin in SAVED_TOKENS.items():
            assert name not in themed, (theme, name)
            assert source.resolve(theme, f"var({name})") == source.resolve(theme, f"var({skin})"), (theme, name)


def test_only_the_bright_panel_themes_override_the_inks() -> None:
    for theme in BRIGHT_PANEL_THEMES:
        themed = source.theme_declarations(theme)
        for name in SAVED_TOKENS:
            assert name in themed, (theme, name)
            # 판을 따르는 기존 테마 토큰만 가리킨다(새 숫자 없음).
            assert re.fullmatch(r"var\(--[a-z-]+\)", themed[name]), (theme, name, themed[name])


def test_the_dialog_repoints_the_skin_names_inside_itself_only() -> None:
    declared = source.rule_declarations("outputs.css", ".saved-output-view")
    for name, skin in SAVED_TOKENS.items():
        assert declared.get(skin) == f"var({name})", skin
    # 스킨 이름 자체는 테마 블록에서 덮지 않는다 — 같은 스킨을 쓰는 다른
    # 화면의 계산값이 바뀌지 않는다.
    for theme in THEMES:
        themed = source.theme_declarations(theme)
        for skin in SAVED_TOKENS.values():
            assert skin not in themed, (theme, skin)


def _saved_output_panels(theme: str) -> list[tuple]:
    """이 창의 글자가 놓이는 면: 판, 그리고 판 위 가장 짙은 흰 베일까지."""
    page = source.resolve(theme, "var(--bg)")
    backdrop = source.over(source.resolve(theme, "var(--surface-ink-deep)"), page)
    panel = source.over(source.resolve(theme, "var(--surface-panel-solid)"), backdrop)
    veiled = source.over(source.resolve(theme, "var(--surface-veil-soft)"), panel)
    veiled = source.over(source.resolve(theme, "var(--surface-veil-dim)"), veiled)
    return [panel, veiled]


def test_saved_output_text_clears_aa_on_the_panel_in_every_theme() -> None:
    measured = {}
    for theme in THEMES:
        panels = _saved_output_panels(theme)
        for name in SAVED_TEXT:
            ink = source.resolve(theme, f"var({name})")
            measured[(theme, name)] = min(source.contrast(ink, panel) for panel in panels)
    failing = {key: round(value, 2) for key, value in measured.items() if value < TEXT_AA}
    assert not failing, failing


def test_saved_output_title_and_label_still_follow_the_panel() -> None:
    """#8024가 이미 판을 따르게 한 제목·라벨도 같은 면에서 기준을 넘는다."""
    for theme in THEMES:
        panels = _saved_output_panels(theme)
        title = source.resolve(theme, "var(--panel-text-max)")
        label = source.resolve(theme, "var(--panel-text-soft)")
        assert min(source.contrast(title, panel) for panel in panels) >= TEXT_AA, theme
        assert min(source.contrast(label, panel) for panel in panels) >= TEXT_AA, theme


# ── 연결 카드: 토큰 계약 ─────────────────────────────────────────────────


def test_connector_card_ink_defaults_to_the_theme_text() -> None:
    """기본값은 테마 글자색 — light·padiem-home·padiem-glass는 전과 같다."""
    root = source.root_declarations()
    assert root.get(CARD_INK) == "var(--text)"
    assert root.get(CARD_MUTED_INK) == "var(--muted)"
    for theme in BRIGHT_PANEL_THEMES:
        themed = source.theme_declarations(theme)
        assert CARD_INK not in themed and CARD_MUTED_INK not in themed, theme


def test_dark_themes_give_the_bright_card_its_own_ink() -> None:
    for theme in DARK_PANEL_THEMES:
        themed = source.theme_declarations(theme)
        assert themed.get(CARD_INK) == "var(--text-panel-ink)", theme
        assert themed.get(CARD_MUTED_INK) == "var(--capability-nav-connectors-ink)", theme


def test_the_tile_and_its_status_line_read_the_card_inks() -> None:
    assert source.rule_declaration("connector-pages.css", TILE_SELECTOR, "color") == f"var({CARD_INK})"
    assert source.rule_declaration(
        "connector-pages.css", ".connector-tile-status", "color") == f"var({CARD_MUTED_INK})"


def test_connector_card_text_clears_aa_in_every_theme() -> None:
    surface = source.rule_declaration("standalone-views.css", CARD_SELECTOR, "background")
    measured = {}
    for theme in THEMES:
        card = source.over(source.resolve(theme, surface), source.resolve(theme, "var(--bg)"))
        for name in (CARD_INK, CARD_MUTED_INK):
            measured[(theme, name)] = source.contrast(source.resolve(theme, f"var({name})"), card)
    failing = {key: round(value, 2) for key, value in measured.items() if value < TEXT_AA}
    assert not failing, failing


# ── 실제로 칠해진 픽셀: 다섯 테마 × 두 폭 ────────────────────────────────

VIEWPORTS = ((1440, 950), (390, 844))

FETCH_STUB = r"""(() => {
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = String(typeof input === "string" ? input : input.url || "");
    if (!url.includes("/api/")) return original(input, init);
    const auth = url.includes("/api/auth/status");
    const body = auth ? {
      ready: true, authenticated: true, user: {email: "qa@padiem.local", name: "QA"},
      session_state: "active", shared_login_enabled: false, shared_session_present: false,
      status_reachable: true, history_ready: true, project_files_ready: true,
      model_requires_session: false
    } : {ok: false};
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: auth ? 200 : 404, headers: {"content-type": "application/json"}
    }));
  };
})()"""

#: 글자를 지우고 면만 찍기 위한 시험 전용 스타일.
HIDE_TEXT = (
    "*,*::before,*::after{color:transparent!important;-webkit-text-fill-color:transparent!important;"
    "text-shadow:none!important;caret-color:transparent!important;transition:none!important}"
)

OPEN_SAVED_OUTPUT = r"""() => {
  const dialog = document.getElementById('savedOutputDialog');
  document.getElementById('savedOutputTitleInput').value = 'Weekly report draft';
  document.getElementById('savedOutputContent').textContent = 'Line one\nLine two\nLine three';
  const status = document.getElementById('savedOutputStatus');
  status.textContent = 'Saved.';
  status.dataset.state = 'normal';
  if (!dialog.open) dialog.showModal();
  return dialog.open;
}"""

#: selector, 기준(본문 4.5 / 큰 글자·아이콘 3)
SAVED_OUTPUT_TARGETS = (
    (".saved-output-header p", TEXT_AA),
    (".saved-output-header h2", LARGE_OR_ICON_AA),
    ("#savedOutputClose", LARGE_OR_ICON_AA),
    (".saved-output-view label", TEXT_AA),
    ("#savedOutputTitleInput", TEXT_AA),
    ("#savedOutputContent", TEXT_AA),
    ("#savedOutputStatus", TEXT_AA),
    ("#savedOutputCopy", TEXT_AA),
    ("#savedOutputDownload", TEXT_AA),
    ("#savedOutputRename", TEXT_AA),
    ("#savedOutputDelete", TEXT_AA),
)

TEXT_BOX = r"""(selector) => Array.from(document.querySelectorAll(selector)).map((el) => {
  const style = getComputedStyle(el);
  let opacity = 1;
  for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
    opacity *= parseFloat(getComputedStyle(node).opacity || '1');
  }
  const rect = el.getBoundingClientRect();
  let box = [rect.left, rect.top, rect.right, rect.bottom];
  const px = (value) => parseFloat(value) || 0;
  if (el.tagName === 'INPUT') {
    // 글자는 내용 상자 안에 놓인다 — 테두리·안쪽 여백은 뺀다.
    box = [rect.left + px(style.borderLeftWidth) + px(style.paddingLeft),
           rect.top + px(style.borderTopWidth) + px(style.paddingTop),
           rect.right - px(style.borderRightWidth) - px(style.paddingRight),
           rect.bottom - px(style.borderBottomWidth) - px(style.paddingBottom)];
  } else {
    const range = document.createRange();
    range.selectNodeContents(el);
    const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0 && r.height > 0);
    if (rects.length) {
      box = [Math.min(...rects.map((r) => r.left)), Math.min(...rects.map((r) => r.top)),
             Math.max(...rects.map((r) => r.right)), Math.max(...rects.map((r) => r.bottom))];
    }
  }
  return {color: style.color, opacity, box, theme: document.documentElement.dataset.theme,
          shown: rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden'};
})"""


class _StaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    handler = partial(_StaticHandler, directory=str(STATIC))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _rgba(value: str) -> tuple[float, float, float, float]:
    numbers = [float(x) for x in re.findall(r"[\d.]+", value)]
    return (numbers[0], numbers[1], numbers[2], numbers[3] if len(numbers) > 3 else 1.0)


def _painted_contrast(page, selectors) -> dict:
    """선택자별 최소 대비: 계산된 글자색을 글자를 지운 화면의 픽셀 위에 놓고 잰다."""
    from PIL import Image

    found = {selector: page.evaluate(TEXT_BOX, selector) for selector in selectors}
    style = page.add_style_tag(content=HIDE_TEXT)
    page.wait_for_timeout(150)
    image = Image.open(io.BytesIO(page.screenshot(animations="disabled"))).convert("RGB")
    style.evaluate("el => el.remove()")
    width, height = image.size
    result = {}
    for selector, items in found.items():
        ratios = []
        for item in items:
            left, top, right, bottom = item["box"]
            box = (max(0, int(left)), max(0, int(top)),
                   min(width, int(right + 0.999)), min(height, int(bottom + 0.999)))
            if not item["shown"] or box[2] <= box[0] or box[3] <= box[1]:
                continue  # 화면 밖(접힌 영역)
            color = _rgba(item["color"])
            ink = color[:3] + (color[3] * item["opacity"],)
            ratios.append(min(source.contrast(ink, pixel + (1.0,))
                              for pixel in set(image.crop(box).getdata())))
        result[selector] = ratios
    return result


@pytest.mark.skipif(sync_playwright is None, reason="playwright not installed")
def test_painted_contrast_matrix(site):
    observations = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for theme in THEMES:
                for width, height in VIEWPORTS:
                    page = browser.new_page(viewport={"width": width, "height": height},
                                            reduced_motion="reduce")
                    page.route("**/*", lambda route: route.continue_()
                               if "127.0.0.1" in route.request.url else route.abort())
                    page.add_init_script(FETCH_STUB)
                    page.goto(site + "?theme=" + theme, wait_until="load")
                    page.wait_for_timeout(1600)
                    assert page.evaluate("document.documentElement.dataset.theme") == theme

                    # 1) 연결 화면의 카드(이름·상태 줄).
                    page.evaluate("document.getElementById('connectorsNavButton').click()")
                    page.wait_for_timeout(900)
                    cards = _painted_contrast(page, (
                        "#connectorsViewBody .capability-card > strong",
                        "#connectorsViewBody .capability-card > .connector-tile-status",
                    ))
                    for selector, ratios in cards.items():
                        assert len(ratios) >= 3, (theme, width, selector, ratios)
                        observations.append((theme, width, selector, TEXT_AA, round(min(ratios), 2)))

                    # 2) 저장한 답변 창(정상 상태 문구, 그다음 오류 상태 문구).
                    assert page.evaluate(OPEN_SAVED_OUTPUT) is True
                    page.wait_for_timeout(500)
                    limits = dict(SAVED_OUTPUT_TARGETS)
                    dialog = _painted_contrast(page, tuple(limits))
                    for selector, ratios in dialog.items():
                        assert len(ratios) == 1, (theme, width, selector, ratios)
                        observations.append((theme, width, selector, limits[selector], round(ratios[0], 2)))
                    page.evaluate("document.getElementById('savedOutputStatus').dataset.state = 'error'")
                    page.wait_for_timeout(300)
                    error = _painted_contrast(page, ("#savedOutputStatus",))["#savedOutputStatus"]
                    observations.append((theme, width, "#savedOutputStatus[error]", TEXT_AA, round(error[0], 2)))
                    page.close()
        finally:
            browser.close()
    print(json.dumps(observations), flush=True)
    failing = [row for row in observations if row[4] < row[3]]
    assert not failing, failing
