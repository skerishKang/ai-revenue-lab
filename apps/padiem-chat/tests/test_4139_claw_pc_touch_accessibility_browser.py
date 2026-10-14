"""#4541 — the Claw "My computers" directory and the how-to-connect guidance must
offer a real >=44x44 CSS px hit area.

At `main bbc75b46` a Chromium probe measured all six interactive controls of
`claw-device-manager.css` / `claw-device-guidance.css` at **40.0px tall** in every
one of 18 combinations (390/768/1280 x padiem-glass/light/dark x ko/en). Widths were
already 49.6-362px, so the defect is the height floor only, and the disabled device
row shared it (40.0px). The component's keyboard behaviour was already correct, so
this stays a presentation-only change.

The static guards below bind the *floor*, not the arithmetic that happens to produce
it: they fail if `min-height` drops below 44px, if someone "fixes" the target by
inflating the glyph or re-gates the floor behind one theme, and if this change leaks
selectors outside the two view styles. The Chromium pass then measures the shipped
render path (real JS, only the future devices GET mocked), so a validator with a
browser gets the box proof rather than a declaration count.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

# The full B62 core runners do not install Playwright; skip the live-browser half
# there instead of aborting collection.
sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
MANAGER_CSS = STATIC / "claw-device-manager.css"
GUIDANCE_CSS = STATIC / "claw-device-guidance.css"
ENDPOINT = "/api/claw/local-access/devices"
FLOOR = 44.0

# Directory: the toggle rule and the shared close/refresh/select rule.
TOGGLE_RULE = r"\.claw-device-manager-toggle\s*\{"
ACTION_RULE = r"\.claw-device-manager-close,\s*\.claw-device-manager-refresh,\s*\.claw-device-manager-select\s*\{"
GUIDANCE_TOGGLE_RULE = r"\.claw-device-guidance-toggle\s*\{"
GUIDANCE_CLOSE_RULE = r"\.claw-device-guidance-close\s*\{"

# Font sizes present at main. The floor must come from box height, never from bigger
# text: these controls carry the same glyphs and information density as before.
BASELINE_FONT_SIZES = {
    TOGGLE_RULE: ".82rem",
    ACTION_RULE: ".8rem",
    GUIDANCE_TOGGLE_RULE: ".82rem",
    GUIDANCE_CLOSE_RULE: ".8rem",
}


def _css(path: Path) -> str:
    """CSS with comments stripped, so prose cannot satisfy a declaration guard."""
    return re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)


def _rule(css: str, header: str) -> str:
    match = re.search(header, css)
    assert match is not None, f"rule not found: {header}"
    open_brace = css.index("{", match.start())
    return css[open_brace + 1 : css.index("}", open_brace)]


def _declared_values(body: str, property_name: str) -> list[str]:
    """Every declaration of `property_name` in the rule, in source order.

    CSS lets a later declaration inside the same block override an earlier one, so
    a guard that reads only the first value would accept `min-height: 44px`
    followed by `min-height: 40px`, or a text-size "fix" appended underneath.
    """
    return [value.strip() for value in
            re.findall(rf"(?<![\w-]){re.escape(property_name)}\s*:\s*([^;\n]+)", body)]


def _single_declared(body: str, property_name: str) -> str:
    values = _declared_values(body, property_name)
    assert values, f"rule lost its {property_name}"
    assert set(values) == {values[0]}, (
        f"{property_name} is declared more than once with different values: {values}")
    return values[0]


# --- the floor, pinned statically so every runner enforces it -----------------


@pytest.mark.parametrize("header", [TOGGLE_RULE, ACTION_RULE])
def test_directory_controls_meet_the_44px_floor(header: str) -> None:
    body = _rule(_css(MANAGER_CSS), header)
    assert _single_declared(body, "min-height") == "44px", f"{header} must floor at 44px"


@pytest.mark.parametrize("header", [GUIDANCE_TOGGLE_RULE, GUIDANCE_CLOSE_RULE])
def test_guidance_controls_meet_the_44px_floor(header: str) -> None:
    body = _rule(_css(GUIDANCE_CSS), header)
    assert _single_declared(body, "min-height") == "44px", f"{header} must floor at 44px"


def test_no_40px_floor_survives_in_either_view_style() -> None:
    for path in (MANAGER_CSS, GUIDANCE_CSS):
        assert "min-height: 40px" not in _css(path), f"{path.name} still floors a control at 40px"


@pytest.mark.parametrize("header,font_size", sorted(BASELINE_FONT_SIZES.items()))
def test_floor_was_not_bought_with_bigger_text(header: str, font_size: str) -> None:
    """A larger glyph is not a bigger target for a screen-reader or low-vision user."""
    body = _rule(_css(MANAGER_CSS) + _css(GUIDANCE_CSS), header)
    assert _single_declared(body, "font-size") == font_size, (
        f"{header} changed font-size; raise min-height instead of the text")


def test_floor_is_theme_independent() -> None:
    """The 44px rules must not be re-gated behind one data-theme block."""
    for path, headers in ((MANAGER_CSS, (TOGGLE_RULE, ACTION_RULE)),
                          (GUIDANCE_CSS, (GUIDANCE_TOGGLE_RULE, GUIDANCE_CLOSE_RULE))):
        css = _css(path)
        for header in headers:
            start = re.search(header, css).start()
            prefix = css[:start]
            open_brace = css.index("{", start)
            # Anything before the rule must not have left an unclosed @media/theme gate.
            assert prefix.count("{") == prefix.count("}"), (
                f"{header} sits inside a conditional block; the floor must apply everywhere")
            assert not re.search(r"\[data-theme[^\]]*\]\s*$", prefix[-200:]), (
                f"{header} floor must not be scoped to a single theme")


def test_change_stays_inside_the_two_view_styles() -> None:
    """No class selector in these files may reach outside its own component namespace."""
    for path, prefix in ((MANAGER_CSS, "claw-device-manager"), (GUIDANCE_CSS, "claw-device-guidance")):
        css = _css(path)
        classes = set(re.findall(r"\.([A-Za-z][\w-]*)", css))
        foreign = sorted(name for name in classes if not name.startswith(prefix))
        assert not foreign, f"{path.name} styles a foreign class: {foreign}"


# --- live Chromium measurement of the shipped render path --------------------


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


def _directory_fixture() -> str:
    return json.dumps({
        "ok": True, "available": True, "ownerScoped": True,
        "devices": [
            {"deviceId": "home", "deviceName": "집 컴퓨터", "platform": "Windows",
             "state": "CONNECTED", "usable": True},
            # The disabled row must keep the same floor as the enabled ones.
            {"deviceId": "laptop", "deviceName": "노트북", "platform": "Windows",
             "state": "OFFLINE", "usable": False},
            {"deviceId": "office", "deviceName": "사무실 PC", "platform": "Windows",
             "state": "CONNECTED", "usable": True},
        ],
    }, ensure_ascii=False)


def _open_surfaces(browser, server, width, theme, locale):
    page = browser.new_page(viewport={"width": width, "height": 850})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#clawDeviceManagerToggle").wait_for(state="attached")
    # Presentation state only; app.js owns session and navigation gates.
    page.evaluate("""() => {
      document.querySelector('.app-shell').setAttribute('data-state', 'claw');
      document.getElementById('clawWorkspace').hidden = false;
    }""")
    page.locator("#clawDeviceManagerToggle").wait_for(state="visible", timeout=10000)
    body = _directory_fixture()
    page.route("**" + ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json", body=body))
    page.locator("#clawDeviceManagerToggle").click()
    page.locator("#clawDeviceManagerList li").first.wait_for()
    page.evaluate("(t) => document.documentElement.setAttribute('data-theme', t)", theme)
    page.evaluate("""(loc) => {
      const btn = document.querySelector(`[data-locale-value="${loc}"]`)
        || document.querySelector(`[data-locale-value="${loc.toUpperCase()}"]`);
      if (btn) btn.click();
    }""", locale)
    page.evaluate("() => document.querySelector('#clawDeviceGuidanceToggle').click()")
    page.locator("#clawDeviceGuidancePanel").wait_for(state="visible")
    return page, errors


BOXES_JS = """() => {
  const families = [
    ['manager-toggle', '#clawDeviceManagerToggle'],
    ['manager-close', '.claw-device-manager-close'],
    ['manager-refresh', '.claw-device-manager-refresh'],
    ['manager-select', '.claw-device-manager-select'],
    ['guidance-toggle', '.claw-device-guidance-toggle'],
    ['guidance-close', '.claw-device-guidance-close'],
  ];
  const out = [];
  const seen = new Set();
  for (const [label, selector] of families) {
    for (const el of document.querySelectorAll(selector)) {
      if (seen.has(el)) continue;
      seen.add(el);
      el.scrollIntoView({block: 'center', inline: 'nearest'});
      const r = el.getBoundingClientRect();
      const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      let intercepted = false;
      if (!top) intercepted = true;
      else if (!(el === top || el.contains(top) || top.contains(el))) intercepted = true;
      out.push({label, w: r.width, h: r.height, disabled: el.disabled === true, intercepted});
    }
  }
  return out;
}"""


@pytest.mark.parametrize("width", [390, 768, 1280])
@pytest.mark.parametrize("theme", ["padiem-glass", "dark"])
def test_measured_hit_areas_are_at_least_44px(browser, server, width, theme) -> None:
    page, errors = _open_surfaces(browser, server, width, theme, "ko")
    boxes = page.evaluate(BOXES_JS)
    assert {b["label"] for b in boxes} == {
        "manager-toggle", "manager-close", "manager-refresh", "manager-select",
        "guidance-toggle", "guidance-close",
    }, "a measured control disappeared"
    assert len([b for b in boxes if b["label"] == "manager-select"]) == 3, (
        "the disabled device row must be measured too, not skipped")
    too_small = [(b["label"], round(b["w"], 1), round(b["h"], 1), b["disabled"])
                 for b in boxes if b["w"] < FLOOR or b["h"] < FLOOR]
    assert not too_small, f"hit area below {FLOOR}px: {too_small}"
    covered = [b["label"] for b in boxes if b["intercepted"]]
    assert not covered, f"another element covers the centre of: {covered}"
    if width == 390:
        assert page.evaluate("() => document.documentElement.scrollWidth") <= page.evaluate(
            "() => document.documentElement.clientWidth"), "390px must not scroll sideways"
    assert not errors, errors
    page.close()


def test_keyboard_access_and_locale_copy(browser, server) -> None:
    page, errors = _open_surfaces(browser, server, 390, "padiem-glass", "en")
    toggle, panel = "#clawDeviceManagerToggle", "#clawDeviceManagerPanel"
    page.evaluate("(s) => document.querySelector(s).focus()", toggle)
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    assert page.locator(panel).is_hidden(), "Enter on the focused toggle must close the directory"
    page.keyboard.press("Enter")
    page.locator(".claw-device-manager-close").wait_for(state="visible")
    assert page.evaluate("(s) => document.querySelector(s).getAttribute('aria-expanded')",
                         toggle) == "true"

    reached = []
    for _ in range(8):
        page.keyboard.press("Tab")
        reached.append(page.evaluate(
            "() => String(document.activeElement.id || document.activeElement.className)"))
    for control in ("claw-device-manager-close", "claw-device-manager-refresh", "claw-device-manager-select"):
        assert any(control in step for step in reached), f"Tab never reaches {control}: {reached}"
    ring = page.evaluate(
        """() => { const cs = getComputedStyle(document.activeElement);
             return [cs.outlineStyle, parseFloat(cs.outlineWidth)]; }""")
    assert ring[0] != "none" and ring[1] >= 2, f"keyboard focus ring missing: {ring}"

    page.evaluate("() => document.querySelector('.claw-device-manager-refresh').focus()")
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.locator(panel).is_hidden(), "Escape must close the directory"
    assert page.evaluate("(s) => document.activeElement === document.querySelector(s)",
                         toggle), "closing must return focus to the toggle"

    guidance_toggle, guidance = "#clawDeviceGuidanceToggle", "#clawDeviceGuidancePanel"
    assert page.locator(guidance).is_visible(), "guidance opens from _open_surfaces"
    page.evaluate("(s) => document.querySelector(s).focus()", guidance_toggle)
    page.keyboard.press("Enter")
    page.wait_for_timeout(250)
    assert page.locator(guidance).is_hidden(), "Enter must close the guidance panel"
    page.keyboard.press("Enter")
    page.locator(".claw-device-guidance-close").wait_for(state="visible")
    page.evaluate("() => document.querySelector('.claw-device-guidance-close').focus()")
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    assert page.locator(guidance).is_hidden(), "Escape must close the guidance panel"
    assert page.evaluate("(s) => document.activeElement === document.querySelector(s)",
                         guidance_toggle), "closing guidance must return focus to its toggle"
    assert not errors, errors
    page.close()
