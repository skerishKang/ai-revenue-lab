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
    # theme-init.js + the glass/cinematic stylesheets are the same files Chat
    # loads, so a theme change upstream reaches this page without an edit here.
    for asset in ("../theme-init.js", "../padiem-glass.css", "../padiem-cinematic-chat.css"):
        assert asset in html, f"wrapper must reference {asset}"


def test_wrapper_declares_no_color_or_font_tokens() -> None:
    css = read(WRAP / "councillor.css")
    for token in ("--bg:", "--text:", "--font-display:", "--accent:", "--gold:", "--radius-md:"):
        assert token not in css, f"{token} must come from the Chat theme, not be re-declared"
    # The reading surfaces (cards, facts, bio, admin panels) must be painted
    # from the theme. Only the decorative hero scrim may carry its own literal
    # gradient, because that layer is the placeholder material itself.
    # Every reading surface must be painted from the theme's glass tokens.
    assert css.count("var(--glass-card-surface") >= 5, "cards must use the glass surface token"
    assert css.count("var(--card-border") >= 4, "card borders must use the theme border token"
    assert css.count("var(--muted") >= 4 and css.count("var(--text") >= 1
    assert css.count("var(--font-") >= 4, "typography must come from the theme stack"
    assert css.count("var(--") > 30, "the palette must ride on the shared tokens"


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
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", source)


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


def test_admin_surface_is_fail_closed() -> None:
    js = wrapper_js()
    html = read(WRAP / "councillor.html")
    # The panels start hidden in the document, so a signed-out visitor never
    # sees the admin surface even before the status read resolves.
    assert re.search(r'id="adminTools"[^>]*\shidden', html), "admin tools must ship hidden"
    assert re.search(r'id="adminGate"[^>]*\shidden', html), "admin gate must ship hidden"
    start = js[js.index("async function start()"):]
    # the painted path closes the admin surface before the session read runs,
    # so the tools can only ever appear after an authenticated response.
    assert start.rindex('paintAdminSignedOut("guest")') < start.rindex("void readSession()")
    assert "data.authenticated === true" in js
    assert 'paintAdminSignedOut("unavailable")' in js, "a failed status read must stay closed"
    css = read(WRAP / "councillor.css")
    # display:grid on the panel beats the UA [hidden] rule; without this line a
    # signed-out visitor keeps the admin panel in layout (observed in S4).
    assert ".cine-admin-tools[hidden]" in css and ".cine-admin-gate[hidden]" in css


def test_public_copy_stays_visitor_facing() -> None:
    """Owner direction 2026-10-25: the prototype notice stays, the build
    diagnostics do not. Missing media, CSP, HTTP statuses and file names belong
    to this issue, not to a page a constituent reads."""
    rendered = _code_only(wrapper_js()) + json.dumps(brand(), ensure_ascii=False)
    for diagnostic in ("미확보", "frame-src", "mp4", "m3u8", "brands/miraen.json",
                       "404", "502", "CSP ", "API 이슈"):
        assert diagnostic not in rendered, f"visitor copy still says: {diagnostic}"
    assert "시제품" in rendered
    assert "공식 웹사이트가 아닙니다" in brand()["prototypeNotice"]


def test_wrapper_links_only_to_the_existing_app_and_public_official_pages() -> None:
    js = wrapper_js()
    assert 'const CHAT_ROOT = "../"' in js
    for tool in ("speech", "sns", "meeting"):
        assert f'CHAT_ROOT + "#padiem-util/{tool}"' in js, tool
    data = brand()
    urls = [item.get("url", "") for item in data["media"]["items"]]
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


def test_placeholder_media_is_declared_and_not_faked() -> None:
    data = brand()
    hero = data["hero"]
    assert hero["mediaKind"] == "PLACEHOLDER"
    assert hero["videoSources"] == [] and hero["poster"] == ""
    assert data["stage"] == "시제품"
    assert "시제품" in data["prototypeNotice"]
    js = wrapper_js()
    # the disclosure is rendered from mediaKind, so a confirmed asset cannot
    # silently inherit the placeholder wording -- or the other way round.
    assert 'CONFIRMED' in js and "시제품" in js
    assets = [p.name for p in WRAP.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".webm", ".m3u8"}]
    assert assets == [], f"unlicensed media must not be committed: {assets}"


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
