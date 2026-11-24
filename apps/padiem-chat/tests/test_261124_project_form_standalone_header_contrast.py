"""대비 수리 후속(261124) — 프로젝트 창과 독립 화면 공통 머리의 글자 대비.

* 프로젝트 창: 저장한 답변 창과 같은 창 스킨(``padiem-cinematic-workspace.css``)이
  글자·선을 흰 베일 ``--ws-*`` 값으로 칠한다. 판(``--surface-panel-solid``)은
  #8024부터 밝은 테마를 따라 밝아졌는데 그 잉크는 ``:root`` 값 그대로라
  light·padiem-home·padiem-glass에서 밝은 판 위 흰 글자가 됐다(머리글·닫기·
  입력칸·단추 1.0~1.1:1). ``projects.css``의 ``.project-form``이 이 창 안에서만
  그 이름들을 판을 따르는 토큰으로 되가리킨다. 저장한 답변 창과 같은 역할은
  ``--outputs-*`` 를 재사용하고, 이 창에만 있는 역할은 ``--project-*`` 를 읽는다.
* 독립 화면 공통 머리: kicker는 테마 ``--accent``, 설명 문구는 테마 ``--muted``를
  읽는다. padiem-home은 머리가 놓이는 바탕이 어두워(좁은 화면에서 더) kicker
  2.6~3.2:1, 설명 문구 3.9:1이었다. ``standalone-views.css``의 두 규칙이
  ``--standalone-kicker-text`` / ``--standalone-tagline-text`` 를 읽고, 그 토큰은
  padiem-home 블록에서만 더 짙은 기존 잉크를 가리킨다.

앞쪽 시험은 토큰 값으로 계약과 대비를 계산해 브라우저 없이 매 PR에서 돈다. 맨
아래 시험은 다섯 테마 × 두 폭에서 실제로 칠해진 픽셀로 같은 기준을 다시 잰다
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

FORM = ".project-form"

#: 저장한 답변 창과 같은 스킨 역할: 스킨 이름 → 재사용하는 --outputs 토큰.
SHARED_TEXT = {
    "--ws-dialog-kicker-text": "--outputs-kicker-text",
    "--ws-control-muted-text": "--outputs-control-text",
    "--ws-control-hover-text": "--outputs-control-hover-text",
    "--ws-input-text": "--outputs-input-text",
    "--ws-secondary-text": "--outputs-secondary-text",
    "--text-veil-strong": "--outputs-primary-text",
    "--ws-danger-text": "--outputs-danger-text",
}
SHARED_EDGES = {
    "--ws-dialog-edge": "--outputs-rule-edge",
    "--line-veil-dim": "--outputs-content-edge",
    "--ws-input-edge": "--outputs-control-edge",
    "--ws-input-focus-edge": "--outputs-control-focus-edge",
    "--ws-control-hover-edge-strong": "--outputs-primary-edge",
    "--line-veil-mist": "--outputs-primary-hover-edge",
}
#: 이 창에만 있는 역할: 새 --project 토큰 → 창 스킨이 읽는 이름.
OWN_TEXT = {
    "--project-form-text": "--surfaces-starter-text",
    "--project-file-add-text": "--ws-file-add-text",
    "--project-file-remove-text": "--ws-label-text",
    "--project-file-remove-hover-text": "--ws-danger-hover-text",
}
OWN_EDGES = {"--project-file-row-edge": "--ws-file-row-edge"}
OWN_TOKENS = {**OWN_TEXT, **OWN_EDGES}

KICKER_INK = "--standalone-kicker-text"
TAGLINE_INK = "--standalone-tagline-text"
HEADER_THEME = "padiem-home"
TAGLINE_SELECTOR = ".standalone-view-tagline"
KICKER_SELECTOR = (
    '.app-shell:is([data-state="meeting"],[data-state="automation"],[data-state="connectors"],'
    '[data-state="calendar"],[data-state="library"],[data-state="util"],[data-state="settings"]) '
    ":is(.standalone-view-kicker,.calendar-view-kicker,.library-kicker)"
)
#: padiem-home 머리가 놓이는 바탕은 본문 그라데이션이라 토큰 하나로 정해지지
#: 않는다. 390폭에서 각 글자 자리에 실제로 칠해진 가장 어두운 바탕(측정값)을
#: 하한으로 쓴다 — kicker 자리 #c6cbd5, 설명 문구 자리 #ccd2db.
HEADER_DARKEST_PAINTED = {
    KICKER_INK: (198.0, 203.0, 213.0, 1.0),
    TAGLINE_INK: (204.0, 210.0, 219.0, 1.0),
}
HEADER_INK_BEFORE = {KICKER_INK: "var(--accent)", TAGLINE_INK: "var(--muted)"}


# ── 프로젝트 창: 토큰 계약 ───────────────────────────────────────────────


def test_project_only_inks_default_to_the_skin_values() -> None:
    """기본값은 창 스킨 값을 그대로 가리킨다 — dark·cinematic은 전과 같다."""
    root = source.root_declarations()
    for name, skin in OWN_TOKENS.items():
        assert root.get(name) == f"var({skin})", name
    for theme in DARK_PANEL_THEMES:
        themed = source.theme_declarations(theme)
        for name, skin in OWN_TOKENS.items():
            assert name not in themed, (theme, name)
            assert source.resolve(theme, f"var({name})") == source.resolve(theme, f"var({skin})"), (theme, name)


def test_only_the_bright_panel_themes_override_the_project_inks() -> None:
    for theme in BRIGHT_PANEL_THEMES:
        themed = source.theme_declarations(theme)
        for name in OWN_TOKENS:
            assert name in themed, (theme, name)
            # 판을 따르는 기존 테마 토큰만 가리킨다(새 숫자 없음).
            assert re.fullmatch(r"var\(--[a-z-]+\)", themed[name]), (theme, name, themed[name])


def test_the_form_repoints_the_skin_names_inside_itself_only() -> None:
    declared = source.rule_declarations("projects.css", FORM)
    for skin, name in {**SHARED_TEXT, **SHARED_EDGES}.items():
        assert declared.get(skin) == f"var({name})", skin
    for name, skin in OWN_TOKENS.items():
        assert declared.get(skin) == f"var({name})", skin
    # 스킨 이름 자체는 테마 블록에서 덮지 않는다 — 같은 스킨을 쓰는 다른
    # 화면의 계산값이 바뀌지 않는다.
    skins = set(SHARED_TEXT) | set(SHARED_EDGES) | set(OWN_TOKENS.values())
    for theme in THEMES:
        themed = source.theme_declarations(theme)
        for skin in skins:
            assert skin not in themed, (theme, skin)


def test_the_form_shares_the_saved_output_roles_one_to_one() -> None:
    """같은 스킨 역할은 저장한 답변 창과 같은 토큰을 읽는다 — 두 창의 값이 갈리지 않는다."""
    saved = source.rule_declarations("outputs.css", ".saved-output-view")
    form = source.rule_declarations("projects.css", FORM)
    for skin in {**SHARED_TEXT, **SHARED_EDGES}:
        assert form[skin] == saved[skin], skin


def _dialog_panels(theme: str) -> list[tuple]:
    """이 창의 글자가 놓이는 면: 판, 그리고 판 위 가장 짙은 흰 베일까지."""
    page = source.resolve(theme, "var(--bg)")
    backdrop = source.over(source.resolve(theme, "var(--surface-ink-deep)"), page)
    panel = source.over(source.resolve(theme, "var(--surface-panel-solid)"), backdrop)
    veiled = source.over(source.resolve(theme, "var(--surface-veil-soft)"), panel)
    veiled = source.over(source.resolve(theme, "var(--surface-veil-dim)"), veiled)
    return [panel, veiled]


def test_project_form_text_clears_aa_on_the_panel_in_every_theme() -> None:
    measured = {}
    for theme in THEMES:
        panels = _dialog_panels(theme)
        for name in list(SHARED_TEXT.values()) + list(OWN_TEXT):
            ink = source.resolve(theme, f"var({name})")
            measured[(theme, name)] = min(source.contrast(ink, panel) for panel in panels)
    failing = {key: round(value, 2) for key, value in measured.items() if value < TEXT_AA}
    assert not failing, failing


# ── 독립 화면 공통 머리: 토큰 계약 ──────────────────────────────────────


def test_header_inks_default_to_the_theme_tokens() -> None:
    """기본값은 지금 읽는 테마 토큰 — padiem-home 말고는 계산값이 전과 같다."""
    root = source.root_declarations()
    assert root.get(KICKER_INK) == "var(--accent)"
    assert root.get(TAGLINE_INK) == "var(--muted)"
    for theme in THEMES:
        if theme == HEADER_THEME:
            continue
        themed = source.theme_declarations(theme)
        assert KICKER_INK not in themed and TAGLINE_INK not in themed, theme
        assert source.resolve(theme, f"var({KICKER_INK})") == source.resolve(theme, "var(--accent)"), theme
        assert source.resolve(theme, f"var({TAGLINE_INK})") == source.resolve(theme, "var(--muted)"), theme


def test_padiem_home_points_the_header_at_its_darker_inks() -> None:
    themed = source.theme_declarations(HEADER_THEME)
    assert themed.get(KICKER_INK) == "var(--text)"
    assert themed.get(TAGLINE_INK) == "var(--hero-sub-color)"


def test_the_shared_header_rules_read_the_header_inks() -> None:
    assert source.rule_declaration("standalone-views.css", KICKER_SELECTOR, "color") == f"var({KICKER_INK})"
    assert source.rule_declaration("standalone-views.css", TAGLINE_SELECTOR, "color") == f"var({TAGLINE_INK})"


def test_padiem_home_header_text_clears_aa_on_its_darkest_backdrop() -> None:
    page = source.resolve(HEADER_THEME, "var(--bg)")
    for name, darkest in HEADER_DARKEST_PAINTED.items():
        ink = source.resolve(HEADER_THEME, f"var({name})")
        worst = min(source.contrast(ink, surface) for surface in (page, darkest))
        assert worst >= TEXT_AA, (name, round(worst, 2))
        # 고치기 전 잉크는 같은 바탕에서 기준에 못 미쳤다 — 하한이 헐겁지 않다.
        before = source.resolve(HEADER_THEME, HEADER_INK_BEFORE[name])
        assert source.contrast(before, darkest) < TEXT_AA, name


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

OPEN_PROJECT_DIALOG = r"""() => {
  const dialog = document.getElementById('projectDialog');
  document.getElementById('projectNameInput').value = 'Patent review';
  document.getElementById('projectInstructionsInput').value = 'Summarise each ruling in five lines.';
  if (!dialog.open) dialog.showModal();
  return dialog.open;
}"""

SHOW_FORM_ERROR = r"""() => {
  const error = document.getElementById('projectFormError');
  error.textContent = 'Could not save the project.';
  error.hidden = false;
}"""

#: 수정 모드에서만 보이는 파일 영역을 앱과 같은 마크업으로 한 줄 채운다.
SHOW_FILES_PANEL = r"""() => {
  document.getElementById('projectFormError').hidden = true;
  document.getElementById('projectFilesPanel').hidden = false;
  const row = document.createElement('div');
  row.className = 'project-file-row';
  const copy = document.createElement('div');
  const strong = document.createElement('strong');
  strong.textContent = 'rulings.md';
  const small = document.createElement('small');
  small.textContent = 'text/markdown · 312';
  copy.append(strong, small);
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.textContent = 'Remove';
  row.append(copy, remove);
  document.getElementById('projectFilesList').replaceChildren(row);
}"""

#: selector, 기준(본문 4.5 / 큰 글자·아이콘 3)
PROJECT_DIALOG_TARGETS = (
    (".project-dialog-header p", TEXT_AA),
    ("#projectDialogTitle", LARGE_OR_ICON_AA),
    ("#projectDialogClose", LARGE_OR_ICON_AA),
    ("#projectNameInput", TEXT_AA),
    ("[data-project-instructions-label]", TEXT_AA),
    ("[data-project-instructions-optional]", TEXT_AA),
    ("#projectInstructionsInput", TEXT_AA),
    (".project-form-note", TEXT_AA),
    ("#projectDialogCancel", TEXT_AA),
    ("#projectSaveButton", TEXT_AA),
)
PROJECT_FILES_TARGETS = (
    (".project-files-heading small", TEXT_AA),
    (".project-file-add", TEXT_AA),
    ("#projectFilesList .project-file-row small", TEXT_AA),
    ("#projectFilesList .project-file-row button", TEXT_AA),
    (".project-files-note", TEXT_AA),
)
CONNECTORS_HEADER_TARGETS = (
    ("#connectorsView .standalone-view-kicker", TEXT_AA),
    ("#connectorsView .standalone-view-tagline", TEXT_AA),
)
#: 같은 kicker 규칙을 쓰는 다른 독립 화면(내비 단추 id, kicker).
OTHER_HEADER_PAGES = (
    ("automationNavButton", "#automationView .standalone-view-kicker"),
    ("calendarNavButton", ".calendar-view-kicker"),
    ("filesNavButton", "#libraryKicker"),
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
  if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
    // 글자는 내용 상자 안에 놓인다 — 테두리·안쪽 여백은 뺀다.
    box = [rect.left + px(style.borderLeftWidth) + px(style.paddingLeft),
           rect.top + px(style.borderTopWidth) + px(style.paddingTop),
           rect.right - px(style.borderRightWidth) - px(style.paddingRight),
           rect.bottom - px(style.borderBottomWidth) - px(style.paddingBottom)];
    if (el.tagName === 'TEXTAREA') {
      // 한 줄만 적어 넣는다 — 오른쪽 아래 크기 조절 손잡이는 글자 자리가 아니다.
      box[3] = Math.min(box[3], box[1] + px(style.lineHeight || style.fontSize) * 1.5);
    }
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


def _observe(observations, theme, width, measured, limits, label="") -> None:
    for selector, ratios in measured.items():
        assert ratios, (theme, width, selector, "not painted")
        observations.append((theme, width, selector + label, limits[selector], round(min(ratios), 2)))


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

                    # 1) 연결 화면의 공통 머리(kicker·설명 문구).
                    page.evaluate("document.getElementById('connectorsNavButton').click()")
                    page.wait_for_timeout(900)
                    limits = dict(CONNECTORS_HEADER_TARGETS)
                    _observe(observations, theme, width, _painted_contrast(page, tuple(limits)), limits)

                    # 2) 같은 kicker 규칙을 쓰는 다른 독립 화면 — 고친 테마에서만.
                    if theme == HEADER_THEME:
                        for nav, kicker in OTHER_HEADER_PAGES:
                            page.evaluate("(id) => document.getElementById(id).click()", nav)
                            page.wait_for_timeout(900)
                            _observe(observations, theme, width,
                                     _painted_contrast(page, (kicker,)), {kicker: TEXT_AA})

                    # 3) 프로젝트 창(새 프로젝트 상태), 그다음 저장 실패 문구.
                    assert page.evaluate(OPEN_PROJECT_DIALOG) is True
                    page.wait_for_timeout(500)
                    limits = dict(PROJECT_DIALOG_TARGETS)
                    _observe(observations, theme, width, _painted_contrast(page, tuple(limits)), limits)
                    page.evaluate(SHOW_FORM_ERROR)
                    page.wait_for_timeout(300)
                    _observe(observations, theme, width,
                             _painted_contrast(page, ("#projectFormError",)), {"#projectFormError": TEXT_AA})

                    # 4) 수정 모드의 파일 영역(추가 단추·파일 줄·삭제 단추) — 넓은 화면에서.
                    if width >= 1000:
                        page.evaluate(SHOW_FILES_PANEL)
                        page.wait_for_timeout(400)
                        limits = dict(PROJECT_FILES_TARGETS)
                        _observe(observations, theme, width, _painted_contrast(page, tuple(limits)), limits)
                    page.close()
        finally:
            browser.close()
    print(json.dumps(observations), flush=True)
    failing = [row for row in observations if row[4] < row[3]]
    assert not failing, failing
