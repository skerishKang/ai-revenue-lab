"""#5786: the councillor blog is a wrapper, not a second implementation.

The issue's completion bar is that the three councillor tools (축사·인사말,
SNS 홍보, 회의정리·활동집) stay owned by PADIEM: same screens, same styles,
same generation/save contract, same session. A wrapper can break that bar in
two quiet ways -- by copying markup/CSS "just for the landing page", or by
inventing its own login/save seam. Both are pinned here as structural
contracts, and the navigation adapter is executed for real against a DOM shim
so the deep link is proven to *click the existing controls* rather than to
re-render the util page somewhere else.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import os
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
WRAP = STATIC / "councillor"
INDEX_HTML = STATIC / "index.html"
UTIL_MENU_JS = STATIC / "util-menu.js"

# The util screens belong to util-menu.js / index.html. If any of these ids or
# classes shows up in the wrapper, the wrapper stopped reusing and started
# duplicating.
OWNED_BY_UTIL = (
    "utilNavButton", "utilView", "utilSpeechForm", "utilSpeechOutput",
    "utilSnsPanel", "utilMeetingPanel", "util-tab", "util-panel",
)
# New AI engines, logins, stores and download endpoints are forbidden in the
# wrapper: the existing /api/chat, /api/projects and /auth/* contracts own them.
FORBIDDEN_ENDPOINTS = ("/api/chat", "/api/projects", "/api/home", "/api/b66", "/auth/google")


@lru_cache(maxsize=None)
def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def wrapper_js() -> str:
    return read(WRAP / "councillor.js")


def adapter_js() -> str:
    return read(WRAP / "util-entry-adapter.js")


def brand() -> dict:
    return json.loads(read(WRAP / "brands" / "miraen.json"))


# --------------------------------------------------------------------------
# the wrapper reuses the existing look instead of re-declaring it
# --------------------------------------------------------------------------


def test_wrapper_loads_the_existing_theme_stack() -> None:
    html = read(WRAP / "councillor.html")
    # theme-init.js + the cinematic stylesheet chain are the same files Chat
    # loads, so a theme change upstream reaches this page without an edit here.
    for asset in ("../theme-init.js", "../padiem-cinematic-chat.css", "../padiem-themes.css"):
        assert asset in html, f"wrapper must reference {asset}"
    # Owner decision 2026-10-25: the page defaults to Light and offers Dark.
    # theme-init.js still owns the interpretation; the wrapper only supplies the
    # default when ?theme= is absent, and it must run first to do that.
    assert 'data-theme="light"' in html
    bootstrap = html.index("./councillor-theme-default.js")
    assert bootstrap < html.index("../theme-init.js"), (
        "the default must be in the URL before theme-init.js reads it")
    assert "../padiem-glass.css" not in html, "glass is the Chat default, not this page's"


def test_wrapper_declares_no_color_or_font_tokens() -> None:
    css = read(WRAP / "councillor.css")
    for token in ("--bg:", "--text:", "--font-display:", "--accent:", "--gold:", "--radius-md:"):
        assert token not in css, f"{token} must come from the Chat theme, not be re-declared"
    # The reading surfaces follow the theme: they must be painted from tokens so
    # Light and Dark both work without an edit here.
    assert css.count("var(--muted") >= 8 and css.count("var(--text") >= 6
    assert css.count("var(--line") >= 8 and css.count("var(--accent") >= 12
    assert css.count("var(--gold") >= 4, "the accent metal stays the theme's"
    assert css.count("var(--font-") >= 3, "face stacks must wrap the theme families, not replace them"
    assert css.count("var(--") > 60, "the palette must ride on the shared tokens"
    # Fixed colours are allowed only where content sits on video or on the one
    # dark band the owner approved (hero, topbar-over-hero, media section).
    offenders = []
    for block in re.finditer(r"([^{}]+)\{([^}]*)\}", css):
        selector, body = block.group(1), block.group(2)
        on_media = re.search(r"cine-(hero|media|veil|film|name|lead|eyebrow|actions|primary|secondary"
                             r"|facts|cue|grain|poster|video|feature|tile|links|link-row|link-title"
                             r"|link-kind|link-arrow|on-media)|cine-section-media"
                             r"|councillor-(topbar|brand|ghost)|:root", selector)
        if on_media:
            continue
        if "#f7f8fa" in body or "rgba(247, 248, 250" in body or "#04070d" in body:
            offenders.append(selector.strip().splitlines()[-1][:48])
    assert not offenders, f"fixed media colours leaked into themed rules: {offenders}"


def test_theme_switch_stays_on_the_existing_mechanism() -> None:
    """Owner decision: Light is the default and Dark is selectable, using the
    ?theme= state the Chat app already has -- not a second theme system."""
    js = _code_only(wrapper_js())
    assert 'THEMES = Object.freeze(["light", "dark"])' in js
    assert 'DEFAULT_THEME = "light"' in js
    # the toggle flips the attribute in place; nothing reloads the document
    assert "location.reload" not in js and "document.write" not in js
    assert 'setAttribute("data-theme", next)' in js
    assert "writeTheme(next)" in js
    bootstrap = _code_only(read(WRAP / "councillor-theme-default.js"))
    assert 'params.set("theme", "light")' in bootstrap
    assert "localStorage" not in bootstrap and "sessionStorage" not in bootstrap, (
        "theme preference stays in the URL, as the Chat privacy contract requires"
    )


def test_small_text_stays_readable_in_light() -> None:
    """Measured on the live page 2026-10-25: at 12-13px the theme's own
    --muted/#gold fell to 4.37 and 2.75:1 against the light canvas -- under
    WCAG AA. The fix derives stronger values from the same tokens instead of
    re-declaring them, so Dark keeps working untouched."""
    css = read(WRAP / "councillor.css")
    assert "--cine-muted-strong:" in css and "--cine-gold-strong:" in css
    assert "color-mix(in srgb, var(--muted)" in css
    assert "color-mix(in srgb, var(--gold)" in css
    for selector, token in (
        (".cine-fact dt", "--cine-muted-strong"),
        (".cine-source", "--cine-muted-strong"),
        (".cine-note-date", "--cine-muted-strong"),
        (".councillor-footer-line", "--cine-muted-strong"),
        (".cine-timeline-date", "--cine-gold-strong"),
    ):
        block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert block, selector
        assert f"var({token})" in block.group(1), f"{selector} still uses the raw token"


def test_topbar_controls_stay_tappable_and_focussable() -> None:
    css = read(WRAP / "councillor.css")
    blocks = re.findall(r"\.councillor-ghost\s*(?::not\([^)]*\))?\s*\{([^}]*)\}", css)
    assert blocks, "no .councillor-ghost rule found"
    assert any("min-height: 44px" in body for body in blocks), (
        "the topbar controls measured 33px tall, under the 44px touch target")
    assert ":focus-visible" in css, "keyboard focus must survive the theme switch"


def test_wrapper_keeps_its_own_layout_baseline() -> None:
    """The page does not load Chat's styles.css, so it must restate the layout
    baseline. Without border-box the hero's padding is added to min-height and
    the fact strip falls below the fold (measured 1101px in a 900px viewport)."""
    css = read(WRAP / "councillor.css")
    assert "box-sizing: border-box" in css
    assert ".councillor-body" in css.split("box-sizing: border-box")[0][-400:]


def test_wrapper_has_no_inline_script() -> None:
    # Production CSP is `script-src 'self'`; an inline script would be blocked
    # at the boundary the Chat app already relies on.
    html = read(WRAP / "councillor.html")
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html), "no inline script allowed"


def test_hero_copy_stays_in_one_column() -> None:
    """S4 caught a real layout defect: the hero was a flex ROW, so the
    placeholder disclosure (taken out of flow on desktop, back in flow on
    mobile) landed beside the action buttons and overlapped them at 390px."""
    css = read(WRAP / "councillor.css")
    hero = re.search(r"\.cine-hero\s*\{([^}]*)\}", css)
    assert hero and "flex-direction: column" in hero.group(1)
    note = re.search(r"\.cine-media-note\s*\{([^}]*)\}", css)
    assert note and "position: absolute" not in note.group(1), (
        "the disclosure must sit in the column, not float over the actions row")
    mobile = css[css.index("@media (max-width: 720px)"):]
    hero_mobile = re.search(r"\.cine-hero\s*\{([^}]*)\}", mobile)
    assert hero_mobile and "align-items" not in hero_mobile.group(1), (
        "a mobile align-items override would push the copy to the right edge")


# --------------------------------------------------------------------------
# 의원3종 stays owned by util-menu.js
# --------------------------------------------------------------------------


def test_wrapper_does_not_duplicate_the_util_screens() -> None:
    html = read(WRAP / "councillor.html")
    js = wrapper_js()
    for owned in OWNED_BY_UTIL:
        assert owned not in html, f"{owned} must not be re-created by the wrapper"
        assert owned not in js or owned == "utilNavButton", owned
    # the only util touch in the wrapper is the destination fragment
    assert js.count("#padiem-util") >= 1


def _code_only(source: str) -> str:
    """주석은 소유권 서술을 담고 있으므로 계약 검사에서는 본문만 본다."""
    # 순서가 의미 있다: 줄 주석 안의 brands/<id> 같은 텍스트가 /* 로 보이면
    # 블록 주석 제거가 본문까지 삼킨다. 그래서 줄 주석을 먼저 지운다.
    source = re.sub(r"(?m)^\s*//.*$", "", source)
    return re.sub(r"/\*.*?\*/", "", source, flags=re.S)


def test_wrapper_builds_no_second_ai_login_or_store() -> None:
    js = _code_only(wrapper_js())
    for endpoint in FORBIDDEN_ENDPOINTS:
        assert endpoint not in js, f"wrapper must not call {endpoint}"
    assert "../api/auth/status" in js
    assert re.search(r"fetch\(\s*STATUS_ENDPOINT", js), "session must come from the status read"
    # the whole network surface of the wrapper, enumerated
    literals = set(re.findall(r'"(\.\./[^"]*)"', js))
    assert literals == {"../api/auth/status", "../"}, literals
    assert "localStorage" not in js and "sessionStorage" not in js, (
        "presentation state stays in the URL, as the Chat privacy contract requires"
    )
    assert "createElement(\"form\")" not in js and "<form" not in read(WRAP / "councillor.html")
    assert _code_only(adapter_js()).count("fetch(") == 0, "the adapter must stay network-free"


def test_public_util_navigation_keeps_auth_on_server() -> None:
    js = wrapper_js()
    html = read(WRAP / "councillor.html")
    assert re.search(r'id="adminTools"[^>]*\\shidden', html)
    assert 'paintUtilLinks(null)' in js
    assert 'paintUtilLinks(user.name || user.display_name || user.email || null)' in js
    assert 'if (refs.adminTools) refs.adminTools.hidden = false' in js
    assert 'if (refs.adminGate) refs.adminGate.hidden = true' in js
    assert 'data.authenticated === true' in js
    assert 'paintAdminSignedOut' not in js
    assert 'const TOOLS = Object.freeze([' in js
    css = read(WRAP / "councillor.css")
    assert ".cine-admin-tools[hidden]" in css and ".cine-admin-gate[hidden]" in css


def test_public_copy_stays_visitor_facing() -> None:
    """Owner direction 2026-10-25: the prototype notice stays, the build
    diagnostics do not. Missing media, CSP, HTTP statuses and file names belong
    to this issue, not to a page a constituent reads."""
    data = json.dumps(brand(), ensure_ascii=False)
    # URL 값은 방문자가 읽는 문장이 아니다(미디어 주소의 확장자 등은 검사에서 제외).
    prose = re.sub(r"https?://[^\"]+", "", _code_only(wrapper_js()) + data)
    for diagnostic in ("미확보", "frame-src", "m3u8", "brands/miraen.json",
                       "404", "502", "CSP", "API 이슈"):
        assert diagnostic not in prose, f"visitor copy still says: {diagnostic}"
    # 실패 진단은 console.error 로 보내고, 화면에는 일반 안내만 남긴다.
    js = _code_only(wrapper_js())
    assert "표시할 자료를 불러오지 못했습니다." in js
    assert "console.error" in js
    assert "시제품" in prose
    assert "공식 웹사이트가 아닙니다" in brand()["prototypeNotice"]


def test_wrapper_links_only_to_the_existing_app_and_public_official_pages() -> None:
    js = wrapper_js()
    assert 'const CHAT_ROOT = "../"' in js
    for tool in ("speech", "sns", "meeting"):
        assert f'CHAT_ROOT + "#padiem-util/{tool}"' in js, tool
    data = brand()
    urls = [item.get("url", "") for item in data["media"]["tiles"] + data["media"]["links"]]
    urls += [c.get("url", "") for c in data["sns"]["channels"]]
    urls += [i.get("url", "") for i in data["activity"]["items"] if i.get("url")]
    assert urls, "brand must carry the researched sources"
    # 선례: 중앙선관위 공개 데이터는 443을 제공하지 않는다(2026-10-25 관측).
    # 공식 당선 근거 링크만 예외로, 호스트와 리소스 경로까지 못 박는다.
    OFFICIAL_HTTP_ALLOWLIST = ("http://data.nec.go.kr/resource/Cnddt_",)
    for url in urls:
        assert url.startswith("https://") or url.startswith(OFFICIAL_HTTP_ALLOWLIST), url
    # nothing is re-hosted from the assembly or the press: only page links.
    for url in urls:
        assert "/attach/" not in url, url
        assert not url.lower().endswith((".jpg", ".jpeg", ".png", ".mp4", ".webp", ".m3u8")), url


def test_media_state_is_declared_and_never_faked() -> None:
    """Two states, one contract: an unconfirmed brand must disclose the
    placeholder, and a confirmed brand must credit the source instead. Neither
    state may borrow the other's wording."""
    data = brand()
    hero = data["hero"]
    js = wrapper_js()
    assert hero["mediaKind"] in ("PLACEHOLDER", "CONFIRMED")
    assert "PLACEHOLDER_NOTE" in js and 'mediaKind === "CONFIRMED"' in js
    if hero["mediaKind"] == "CONFIRMED":
        assert hero["videoSources"] and hero["poster"], "confirmed state must carry real media"
        assert hero["credit"], "confirmed media must say where it came from"
    else:
        assert hero["videoSources"] == [] and hero["poster"] == ""
    # 승인된 자산도 저장소에 복사하지 않는다: 미디어 파일은 커밋 금지.
    assets = [f.name for f in WRAP.rglob("*")
              if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".m3u8"}]
    assert assets == [], f"media must stay on the R2 host, not be committed: {assets}"
    assert data["stage"] == "시제품" and "시제품" in data["prototypeNotice"]


def test_media_urls_stay_on_the_allowed_host() -> None:
    js = wrapper_js()
    assert 'MEDIA_HOSTS = Object.freeze(["media.padiem.net"])' in js, (
        "brand files are hand-edited, so <video>/<img> sources stay allowlisted")
    hero = brand()["hero"]
    feature = brand()["feature"]
    for url in list(hero["videoSources"]) + [hero["poster"]] + list(feature["sources"]):
        assert url.startswith("https://media.padiem.net/councillor/miraen/"), url
    assert "new URL(value)" in js and 'parsed.protocol !== "https:"' in js


def test_dated_media_is_labelled_so_it_cannot_read_as_current() -> None:
    """Owner note 2026-10-25: the 2025 introduction interview must not pass as a
    present-day statement of office."""
    feature = brand()["feature"]
    assert "2025" in feature["kind"] and "2025" in feature["title"]
    assert "촬영" in feature["note"] and "현재 직위" in feature["note"]
    assert "2026년 6월 3일" in brand()["profile"][3]["value"], "current office must be stated separately"


def test_admin_entry_is_not_a_public_landing_card() -> None:
    """Owner note 2026-10-25: the councillor tools move off the visitor page into
    a management path, so the admin block must live in the footer only."""
    html = read(WRAP / "councillor.html")
    main = html[html.index("<main"):html.index("</main>")]
    footer = html[html.index("<footer"):]
    assert "adminTools" not in main and "adminGate" not in main
    assert 'id="adminTools"' in footer and 'id="adminGate"' in footer


# --------------------------------------------------------------------------
# the navigation seam
# --------------------------------------------------------------------------


def test_adapter_is_registered_after_util_menu() -> None:
    html = read(INDEX_HTML)
    menu = html.index("./util-menu.js")
    adapter = html.index("./councillor/util-entry-adapter.js")
    assert menu < adapter, "adapter must run after util-menu.js attaches its handlers"
    assert html.count("./councillor/util-entry-adapter.js") == 1


def test_util_menu_ownership_is_untouched() -> None:
    # The wrapper lane must not fork the util implementation it depends on.
    source = read(UTIL_MENU_JS)
    assert "5786" not in source, "util-menu.js must not be edited for the wrapper"
    assert "showUtil" in source and "utilNavButton" in source


HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");

const adapterPath = process.argv[2];

function makeNode(tag, attrs) {
  return {
    tagName: String(tag || "").toUpperCase(),
    id: (attrs && attrs.id) || "",
    className: (attrs && attrs.className) || "",
    attributes: Object.assign({}, attrs || {}),
    clicks: 0,
    hidden: false,
    click() { this.clicks += 1; },
    getAttribute(name) {
      if (name === "data-util") return this.attributes["data-util"] || null;
      return this.attributes[name] === undefined ? null : this.attributes[name];
    },
  };
}

function run(hash) {
  const nav = makeNode("button", { id: "utilNavButton" });
  const tabs = ["speech", "sns", "meeting", "pdfmd"].map((tool) =>
    makeNode("button", { className: "util-tab", "data-util": tool }));
  const byId = { utilNavButton: nav };
  const listeners = {};
  const sandbox = {
    document: {
      readyState: "complete",
      getElementById: (id) => byId[id] || null,
      querySelector: (sel) => {
        const m = /data-util="([^"]+)"/.exec(sel);
        if (!m) return null;
        return tabs.find((t) => t.attributes["data-util"] === m[1]) || null;
      },
      addEventListener: () => {},
    },
    window: {
      location: { hash },
      addEventListener: (name, fn) => { listeners[name] = fn; },
    },
  };
  vm.runInNewContext(fs.readFileSync(adapterPath, "utf8"), sandbox, { filename: adapterPath });
  void listeners;
  return {
    nav: nav.clicks,
    active: tabs.filter((t) => t.clicks > 0).map((t) => t.attributes["data-util"]),
  };
}

const out = {};
out.deepSns = run("#padiem-util/sns");
out.deepMeeting = run("#padiem-util/meeting");
out.bareRoute = run("#padiem-util");
out.unknownTool = run("#padiem-util/../../etc");
out.otherRoute = run("#padiem-claw");
out.noHash = run("");
process.stdout.write(JSON.stringify(out));
"""


def test_adapter_clicks_the_existing_controls() -> None:
    node = shutil.which("node")
    assert node, "node runtime is required for the adapter harness"
    harness = ROOT / "tests" / "_5786_adapter_harness.js"
    harness.write_text(HARNESS, encoding="utf-8")
    try:
        proc = subprocess.run(
            [node, str(harness), str(WRAP / "util-entry-adapter.js")],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        out = json.loads(proc.stdout)
    finally:
        harness.unlink(missing_ok=True)

    # the fragment becomes a click on the real sidebar button and the real tab
    assert out["deepSns"] == {"nav": 1, "active": ["sns"]}
    assert out["deepMeeting"]["active"] == ["meeting"]
    assert out["bareRoute"]["nav"] == 1
    assert out["bareRoute"]["active"] == [], "bare route must not force a tab"
    # anything else is refused without touching the screens: no selector is
    # built from an unknown fragment, and other routes are left alone.
    assert out["unknownTool"]["active"] == []
    assert out["otherRoute"]["nav"] == 0 and out["otherRoute"]["active"] == []
    assert out["noHash"]["nav"] == 0
