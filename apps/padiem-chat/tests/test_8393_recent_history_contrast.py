"""Recent conversation title contrast and mutually exclusive empty state (#8393)."""
import io
import json
import os
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
FETCH_STUB = r"""(() => {
  const original = window.fetch.bind(window);
  window.fetch = (input, init) => {
    const url = String(typeof input === "string" ? input : input.url || "");
    if (!url.includes("/api/")) return original(input, init);
    const auth = url.includes("/api/auth/status");
    const body = auth ? {
      ready: true, authenticated: false, user: null, session_state: "guest",
      shared_login_enabled: false, shared_session_present: false,
      status_reachable: true, history_ready: false, project_files_ready: false,
      model_requires_session: false
    } : {ok: false};
    return Promise.resolve(new Response(JSON.stringify(body), {
      status: auth ? 200 : 404, headers: {"content-type": "application/json"}
    }));
  };
})()"""


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


THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")
VIEWPORTS = ((1440, 950), (768, 900), (390, 844))
LOAD = r"""async (conversations) => {
  const d = document;
  const deps = {
    authState: {authenticated: true, history_ready: true}, authViewEpoch: 1,
    clawConversationIds: new Set(), historyList: d.querySelector('#historyList'),
    historySection: d.querySelector('#historySection'), historyEmpty: d.querySelector('#historyEmpty'),
    historyActionStatus: d.querySelector('#historyActionStatus'),
    uiT: key => key === "history-tool-request-group" ? "External tool requests" : key, sidebarActionIcon: () => d.createElement('span'),
    readClawRuns: async () => ({response: {ok: false}, data: null})
  };
  const previous = window.fetch;
  window.fetch = (input, init) => String(input) === '/api/conversations'
    ? Promise.resolve(new Response(JSON.stringify({conversations}), {status: 200}))
    : previous(input, init);
  try { await window.PadiemChatHistoryModule.create(deps).loadRecentConversations(); }
  finally { window.fetch = previous; }
  d.querySelector('.app-shell').classList.add('sidebar-open');
  deps.historySection.classList.remove('is-collapsed');
  return {rows: deps.historyList.querySelectorAll('.history-item').length,
          hidden: deps.historyEmpty.hidden, display: getComputedStyle(deps.historyEmpty).display};
}"""
NORMAL = {"id": "chat_fixture", "title": "Recent conversation fixture"}
TOOL = {"id": "chat_tool", "title": "\uc678\ubd80 AI \ub3c4\uad6c \uc694\uccad: fixture"}


def _rgb(value):
    return [float(x) for x in re.findall(r"[\d.]+", value)]


def _luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return sum(w * channel(c) for w, c in zip((.2126, .7152, .0722), rgb))


def _ratio(fg, bg):
    alpha = fg[3] if len(fg) == 4 else 1
    a, b = sorted((_luminance([f * alpha + b * (1 - alpha) for f, b in zip(fg, bg)]),
                   _luminance(bg)))
    return (b + .05) / (a + .05)


@pytest.mark.skipif(sync_playwright is None, reason="playwright not installed")
def test_recent_history_matrix(site):
    from PIL import Image
    report_dir = os.environ.get("HISTORY_CAPTURE_DIR")
    tag = os.environ.get("HISTORY_CAPTURE_TAG", "after")
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
                    state = page.evaluate(LOAD, [NORMAL])
                    assert state["rows"] == 1, state
                    title = page.locator("button.history-item")
                    title.scroll_into_view_if_needed()
                    page.evaluate("document.fonts.ready")
                    page.wait_for_timeout(300)
                    info = title.evaluate("""el => ({
                      theme: document.documentElement.dataset.theme,
                      fg: getComputedStyle(el).color,
                      fill: getComputedStyle(el).webkitTextFillColor,
                      bg: getComputedStyle(el.parentElement).backgroundColor,
                      sidebar: getComputedStyle(el.closest('.sidebar')).backgroundColor,
                      opacity: getComputedStyle(el).opacity,
                      token: getComputedStyle(el).getPropertyValue('--sidebar-text').trim()
                    })""")
                    assert info["theme"] == theme, info
                    label = title.text_content()
                    title.evaluate("el => {el.textContent = ''}")
                    img = Image.open(io.BytesIO(title.screenshot(animations="disabled"))).convert("RGB")
                    title.evaluate("(el, label) => {el.textContent = label}", label)
                    pixels = [img.getpixel((x, y)) for y in range(img.height//2-4, img.height//2+5)
                              for x in range(12, max(13, min(img.width-12, 130)))]
                    midpoint = img.getpixel((min(40, img.width-1), img.height//2))
                    minimum = min(_ratio(_rgb(info["fill"]), pix) for pix in pixels)
                    tool = page.evaluate(LOAD, [TOOL])
                    summary = page.locator(".history-tool-requests-summary")
                    summary.scroll_into_view_if_needed()
                    group_info = summary.evaluate("""el => ({
                      fg: getComputedStyle(el).color,
                      bg: getComputedStyle(el).backgroundColor,
                      arrow: getComputedStyle(el, '::before').color,
                      sidebar: getComputedStyle(el.closest('.sidebar')).backgroundColor
                    })""")
                    if report_dir and theme == "padiem-glass" and width in (1440, 390):
                        out = Path(report_dir)
                        out.mkdir(parents=True, exist_ok=True)
                        page.screenshot(path=str(out / f"{tag}-group-{width}.png"), animations="disabled")
                    summary_label = summary.text_content()
                    summary.evaluate("el => {el.textContent = ''}")
                    gimg = Image.open(io.BytesIO(summary.screenshot(animations="disabled"))).convert("RGB")
                    summary.evaluate("(el, label) => {el.textContent = label}", summary_label)
                    gpixels = [gimg.getpixel((x, y)) for y in range(gimg.height//2-4, gimg.height//2+5)
                               for x in range(25, min(gimg.width-12, 130))]
                    group_info["actual_bg"] = gimg.getpixel((40, gimg.height//2))
                    group_info["contrast"] = round(min(_ratio(_rgb(group_info["fg"]), pix)
                                                       for pix in gpixels), 3)
                    group_info["arrow_contrast"] = round(min(_ratio(_rgb(group_info["arrow"]), pix)
                                                             for pix in gpixels), 3)
                    empty = page.evaluate(LOAD, [])
                    invalid = page.evaluate(LOAD, [{"id": "bad"}])
                    mixed = page.evaluate(LOAD, [NORMAL, TOOL])
                    row = dict(theme=theme, width=width, **{k: v for k, v in info.items() if k != "theme"},
                               actual_bg=midpoint, contrast=round(minimum, 3), normal=state,
                               tool=tool, group=group_info, empty=empty, invalid=invalid, mixed=mixed)
                    observations.append(row)
                    print(json.dumps(row), flush=True)
                    page.close()
        finally:
            browser.close()
    for row in observations:
        assert row["contrast"] >= 4.5, row
        assert row["group"]["contrast"] >= 4.5, row
        assert row["group"]["arrow_contrast"] >= 3, row
        for key in ("normal", "tool", "mixed"):
            assert row[key]["rows"] > 0 and row[key]["hidden"] and row[key]["display"] == "none", row
        for key in ("empty", "invalid"):
            assert row[key]["rows"] == 0 and not row[key]["hidden"] and row[key]["display"] != "none", row
