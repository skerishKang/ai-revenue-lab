"""#5634 first screen and the PC connection panel: one entry, one head line.

Two things changed on the first screen, and both of them are presentation:

  1. the first starter card is the computer connection entry, not the
     "easy explanation" prompt. Clicking it must open the SAME panel the
     composer PC status control opens, because there is one device directory
     reader and one device authority in the page,
  2. the greeting plus the four cards used to float in the middle of the
     first screen. They now sit in the top third of the space between the top
     of the content column and the fixed composer, so the top : bottom split
     of the first screen is about 1 : 2,

and the panel itself got smaller:

  3. the panel head is one line -- title, its short refresh action and the
     close button on the right -- instead of a title block above a separate
     action row,
  4. the server-owned device ID is a detail value below the device name,
     truncated on screen and readable in full through its title attribute.

The #5325 / #5617 panel contract is what keeps the panel usable: it stays
above the composer, it never covers the message input, it closes with its own
button and with Escape, the underlying composer controls stay clickable while
it is open, and the 44px / .8rem touch floor of its actions is untouched. The
static tests below pin the shape of that contract; the browser tests measure
it.

No connector code, endpoint, migration, worker or production deploy is touched.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

# The static contract tests below must run everywhere (the required CI lane
# installs no browser), so Playwright is optional here and only the real
# browser checks are skipped when it is absent.
try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"

INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOCALE_JS = (STATIC / "locale.js").read_text(encoding="utf-8")
CLAW_JS = (STATIC / "claw-device-manager.js").read_text(encoding="utf-8")
CLAW_STATUS_JS = (STATIC / "claw-composer-connection-status.js").read_text(encoding="utf-8")
CLAW_CSS = (STATIC / "claw-device-manager.css").read_text(encoding="utf-8")
FIRST_USE_CSS = (STATIC / "padiem-first-use.css").read_text(encoding="utf-8")

# The three windows of the verification list.
WINDOWS = ((1440, 900), (820, 1180), (390, 844))
# Only the windows wide enough for the 1 : 2 rule to apply (the phone keeps its
# own 16px start, because its block is taller than the screen).
RATIO_WINDOWS = ((1440, 900), (820, 1180))

# The deployment capability of the running service, so the web-search control
# really arrives and can be clicked while the panel is open.
HEALTH = {
    "web_tools_ready": True,
    "deep_research_ready": False,
    "auth_configured": True,
    "history_store_bound": True,
    "projects_code_ready": True,
    "projects_code_store_bound": True,
    "saved_outputs_code_ready": True,
    "saved_output_store_bound": True,
}

# Twelve confirmed devices: enough that the panel's own scroll has to work, and
# a mix of online / offline rows so both state chips render.
DIRECTORY = {
    "ok": True,
    "available": True,
    "ownerScoped": True,
    "selectedDeviceId": None,
    "devices": [
        {
            "deviceId": "owner-node-%02d-%s" % (index, "b" * 40),
            "deviceName": "내 데스크톱" if index == 0 else "외부 노드 %02d" % index,
            "platform": "Windows 11",
            "state": "CONNECTED" if index % 4 in (0, 3) else "OFFLINE",
            "usable": index % 4 in (0, 3),
            "executable": index % 4 in (0, 3),
            "selectable": index % 4 in (0, 3),
        }
        for index in range(12)
    ],
}

CONNECT_ENDPOINT = "/api/claw/local-access/devices"
SELECT_ENDPOINT = "/api/claw/local-access/devices/select"


class ConnectorHandler(http.server.SimpleHTTPRequestHandler):
    """The static app plus the two endpoints the panel really calls."""

    directory_reads = 0
    selection_posts = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json(HEALTH)
        if self.path.startswith(CONNECT_ENDPOINT):
            ConnectorHandler.directory_reads += 1
            return self._json(DIRECTORY)
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith(SELECT_ENDPOINT):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            body = json.loads(raw or "{}")
            ConnectorHandler.selection_posts.append(body)
            return self._json(
                {"ok": True, "selectedDeviceId": body.get("device_id")}
            )
        self.send_response(404)
        self.end_headers()


@pytest.fixture(scope="session")
def static_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), ConnectorHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/index.html?theme=padiem-glass" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


def _intersects(first, second):
    return not (
        first["right"] <= second["left"]
        or first["left"] >= second["right"]
        or first["bottom"] <= second["top"]
        or first["top"] >= second["bottom"]
    )


def _button_with_id(html, element_id):
    marker = 'id="%s"' % element_id
    start = html.index(marker)
    return html[html.rindex("<button", 0, start): html.index("</button>", start)]


# ---------------------------------------------------------------------------
# Static contracts: the shape of the change and the shape of the contract that
# must not move.
# ---------------------------------------------------------------------------


def test_the_first_card_is_the_computer_connection_entry():
    card = _button_with_id(INDEX, "pcConnectStarter")
    assert 'class="starter"' in card
    assert 'data-pc-connect-starter="true"' in card
    assert 'data-locale-key="pc-connect-title"' in card
    assert 'data-locale-key="pc-connect-copy"' in card
    assert "컴퓨터 연결" in card
    # The card the first screen used to open with is gone for good.
    assert 'data-skill="explain"' not in INDEX
    assert "AI를 처음 쓰는 사람에게" not in INDEX
    assert "쉽게 설명해줘" not in INDEX


def test_the_card_points_at_the_same_panel_as_the_composer_control():
    card = _button_with_id(INDEX, "pcConnectStarter")
    assert 'type="button"' in card
    assert 'aria-controls="clawDeviceManagerPanel"' in card
    assert 'aria-expanded="false"' in card
    assert 'aria-haspopup="dialog"' in card
    # The card is the first entry card, so it must come before the others.
    assert INDEX.index('id="pcConnectStarter"') < INDEX.index('id="documentStarterButton"')


def test_the_starter_grid_keeps_four_cards_without_a_duplicate_prompt():
    assert 'id="documentStarterButton"' in INDEX
    assert 'id="writingStarterButton"' in INDEX
    assert 'id="webSearchStarterButton"' in INDEX
    assert 'data-skill="explain"' not in INDEX


def test_the_locale_covers_the_new_card_in_both_languages():
    assert '"pc-connect-title": "컴퓨터 연결", "pc-connect-copy": "컴퓨터 연결 패널 열기"' in LOCALE_JS
    assert '"pc-connect-title": "Connect computer", "pc-connect-copy": "Open the connection panel"' in LOCALE_JS
    assert '["#pcConnectStarter strong", "pc-connect-title"]' in LOCALE_JS
    assert '["#pcConnectStarter small", "pc-connect-copy"]' in LOCALE_JS
    # The card is a real control now: nothing may bind the first starter slot
    # as a prompt again.
    assert ".starter:nth-child(1)" not in LOCALE_JS


def test_the_card_reuses_the_existing_panel_open_path():
    assert 'getElementById("pcConnectStarter")' in CLAW_STATUS_JS
    assert "starterCard.addEventListener(\"click\", openExistingPanel)" in CLAW_STATUS_JS
    # Both visible entries into the panel report the same expanded state.
    assert 'card.setAttribute("aria-controls", PANEL_ID)' in CLAW_STATUS_JS
    assert 'card.setAttribute("aria-expanded"' in CLAW_STATUS_JS
    # An opening click on the card must not immediately close the panel it
    # opened, so the card is excluded from the outside-click guard.
    assert 'target.closest("#composerPcStatus, #pcConnectStarter")' in CLAW_JS
    assert "root.append(toggle, panel)" in CLAW_JS


def test_the_panel_head_is_one_line_with_its_touch_floor_intact():
    assert ".claw-device-manager-head {" in CLAW_CSS
    # Refresh sits next to the title, close keeps the right edge of the row.
    assert ".claw-device-manager-head .claw-device-manager-refresh { order: 1; }" in CLAW_CSS
    assert (
        ".claw-device-manager-head .claw-device-manager-close { order: 3; margin-left: auto; }"
        in CLAW_CSS
    )
    assert ".claw-device-manager-refresh { flex: 0 0 auto;" in CLAW_CSS
    # The old stacked head and its separate action row are gone.
    assert "flex-direction: row-reverse;" not in CLAW_CSS
    assert ".claw-device-manager-actions" not in CLAW_CSS
    # The shared action floor that #4139 pinned must not move.
    assert (
        ".claw-device-manager-close,\n"
        ".claw-device-manager-refresh,\n"
        ".claw-device-manager-select {" in CLAW_CSS
    )
    assert "font-size: .8rem;" in CLAW_CSS
    assert "min-height: 44px;" in CLAW_CSS


def test_the_panel_stays_above_the_composer_and_scrolls_its_own_content():
    assert "bottom: 22px;" in CLAW_CSS
    assert "max-height: min(330px, 46vh);" in CLAW_CSS
    assert "overflow-y: auto;" in CLAW_CSS
    # The frame stays click-through and only its form controls take the
    # pointer, so the content behind the panel keeps working. That is the
    # #5014 contract: granting the pointer to the panel's own head covers the
    # cards that sit under it.
    assert "pointer-events: none;" in CLAW_CSS
    assert (
        ".claw-device-manager-panel button,\n"
        ".claw-device-manager-panel a,\n"
        ".claw-device-manager-panel input,\n"
        ".claw-device-manager-panel select,\n"
        ".claw-device-manager-panel textarea,\n"
        ".claw-device-manager-panel label {\n"
        "  pointer-events: auto;\n"
        "}\n"
        ".claw-device-manager-head {" in CLAW_CSS
    )


def test_the_device_id_is_a_detail_value_not_a_row_header():
    assert 'element("small", "claw-device-manager-id", device.deviceId)' in CLAW_JS
    assert "id.title = device.deviceId;" in CLAW_JS
    assert "name.title = device.deviceName || device.deviceId;" in CLAW_JS
    assert (
        'if (device.deviceId && device.deviceId !== (device.deviceName || "")) {' in CLAW_JS
    )
    assert ".claw-device-manager-id {" in CLAW_CSS
    assert "max-width: 112px;" in CLAW_CSS
    assert "text-overflow: ellipsis;" in CLAW_CSS
    assert "white-space: nowrap;" in CLAW_CSS


def test_the_first_screen_split_is_one_to_two():
    """The 1 : 2 first-screen split is one shared origin, not one per product.

    #5561: this contract used to require two constants -- 747px for Chat and
    836px for Claw, because the Claw hero block measures 89px more. Dividing a
    per-product number by three moved the shared row, so the Claw brand line sat
    ~30px below the Chat one on the same screen. One token now holds the
    expression; a taller product block changes the space under the hero only.
    """
    assert "@media (min-width: 641px)" in FIRST_USE_CSS
    assert "var(--padiem-first-screen-inset" in FIRST_USE_CSS
    assert "calc((100dvh - 836px) / 3)" not in FIRST_USE_CSS
    frame = (STATIC / "shared-six-panel-frame.css").read_text(encoding="utf-8")
    assert "max(12px, calc((100dvh - 747px) / 3))" in frame
    # The composer keeps its own first-use treatment.
    assert '.app-shell[data-state="home"] .composer' in FIRST_USE_CSS


# ---------------------------------------------------------------------------
# Browser contracts.
# ---------------------------------------------------------------------------

# Everything is measured in ONE page call, so every box below comes from the
# same frame. Reading the boxes one at a time races the layout, which is still
# settling while the panel opens.
MEASURE = """() => {
    const box = el => {
        if (!el) return null;
        const b = el.getBoundingClientRect();
        return {top: b.top, left: b.left, right: b.right, bottom: b.bottom, height: b.height, width: b.width};
    };
    const inside = (scope, selector) => (scope ? scope.querySelector(selector) : null);
    const panel = document.getElementById('clawDeviceManagerPanel');
    const card = document.getElementById('pcConnectStarter');
    const composer = document.querySelector('.composer');
    const web = document.getElementById('webSearchButton');
    return {
        card: box(card),
        cardExpanded: card ? card.getAttribute('aria-expanded') : null,
        panelOpen: !!panel && !panel.hidden,
        panel: box(panel),
        head: inside(panel, '.claw-device-manager-head') && box(inside(panel, '.claw-device-manager-head')),
        title: inside(panel, '#clawDeviceManagerTitle') && box(inside(panel, '#clawDeviceManagerTitle')),
        refresh: inside(panel, '.claw-device-manager-refresh') && box(inside(panel, '.claw-device-manager-refresh')),
        close: inside(panel, '.claw-device-manager-close') && box(inside(panel, '.claw-device-manager-close')),
        composer: box(composer),
        composerWrap: box(document.querySelector('.composer-wrap')),
        input: box(document.querySelector('.composer textarea') || document.querySelector('.composer input')),
        web: box(web),
        webHidden: web ? web.hidden : null,
        webPressed: web ? web.getAttribute('aria-pressed') : null,
        cardLabels: Array.from(document.querySelectorAll('.starter-grid > *')).map(el => ({
            visible: el.getBoundingClientRect().height > 2,
            strong: (el.querySelector('strong') || {}).textContent || null,
        })),
        rows: document.querySelectorAll('#clawDeviceManagerList .claw-device-manager-item').length,
        status: (document.getElementById('clawDeviceManagerStatus') || {}).textContent,
        overflowY: panel ? getComputedStyle(panel).overflowY : null,
        scrollable: panel ? panel.scrollHeight > panel.clientHeight : null,
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
    };
}"""

SETTLE = """() => new Promise(resolve => {
    const read = () => {
        const panel = document.getElementById('clawDeviceManagerPanel');
        const wrap = document.querySelector('.composer-wrap');
        if (!panel || !wrap) return 'missing';
        const a = panel.getBoundingClientRect();
        const b = wrap.getBoundingClientRect();
        return [a.top, a.left, a.right, a.bottom, b.top, b.left].join(',');
    };
    let last = null;
    let same = 0;
    let frames = 0;
    const step = () => {
        const now = read();
        same = now === last ? same + 1 : 0;
        last = now;
        frames += 1;
        if (same >= 3 || frames > 90) return resolve(true);
        requestAnimationFrame(step);
    };
    step();
})"""


def _measure(page):
    page.wait_for_function(SETTLE)
    return page.evaluate(MEASURE)


def _open_panel(page):
    page.click("#pcConnectStarter")
    page.wait_for_function("() => !document.getElementById('clawDeviceManagerPanel').hidden")


def _ready(page):
    page.wait_for_function(
        "() => !!document.getElementById('pcConnectStarter') && "
        "!!document.getElementById('clawDeviceManagerPanel')"
    )


@pytest.mark.parametrize("window", WINDOWS)
@requires_browser
def test_the_first_card_opens_the_panel_at_each_size(static_url, window):
    width, height = window
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(static_url)
            _ready(page)

            before = _measure(page)
            labels = [item["strong"] for item in before["cardLabels"] if item["visible"]]
            assert "컴퓨터 연결" in labels
            assert "쉽게 설명해줘" not in labels
            assert len(labels) == 4
            assert before["card"]["height"] > 2
            assert before["panelOpen"] is False
            assert before["cardExpanded"] == "false"
            assert before["scrollWidth"] == before["clientWidth"]

            _open_panel(page)
            after = _measure(page)
            panel, head = after["panel"], after["head"]
            title, refresh, close = after["title"], after["refresh"], after["close"]
            composer, composer_wrap = after["composer"], after["composerWrap"]

            assert after["panelOpen"] is True
            assert after["cardExpanded"] == "true"
            assert panel["height"] > 2 and head["height"] > 2
            assert title["width"] > 2 and refresh["width"] > 2 and close["width"] > 2
            title_center = title["top"] + title["height"] / 2
            # One head line: the title, its short refresh action and the close
            # button share a single row.
            assert head["height"] < 60
            assert abs(refresh["top"] + refresh["height"] / 2 - title_center) < 3
            assert abs(close["top"] + close["height"] / 2 - title_center) < 3
            assert 0 <= refresh["left"] - title["right"] <= 40
            assert close["left"] > refresh["right"]
            assert abs(close["right"] - head["right"]) < 1
            # The panel ends above the composer box, inside its width, and never
            # over the message input.
            assert panel["bottom"] <= composer["top"] - 8
            assert panel["left"] >= composer["left"] - 2
            assert panel["right"] <= composer["right"] + 2
            assert panel["top"] <= composer_wrap["top"]
            assert not _intersects(panel, after["input"])
            assert after["scrollWidth"] == after["clientWidth"]
            assert panel["bottom"] <= height + 1
        finally:
            browser.close()


@pytest.mark.parametrize("window", WINDOWS)
@requires_browser
def test_the_panel_closes_and_the_composer_controls_stay_clickable(static_url, window):
    width, height = window
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(static_url)
            _ready(page)

            _open_panel(page)
            opened = _measure(page)
            assert opened["panelOpen"] is True
            assert opened["cardExpanded"] == "true"

            # The second visible entry into the same panel is the composer PC
            # status control; clicking it toggles the panel the card opened.
            page.click("#composerPcStatus")
            page.wait_for_function("() => document.getElementById('clawDeviceManagerPanel').hidden")
            toggled = _measure(page)
            assert toggled["panelOpen"] is False
            assert toggled["cardExpanded"] == "false"

            # Its own close button.
            _open_panel(page)
            page.click("#clawDeviceManagerPanel .claw-device-manager-close")
            page.wait_for_function("() => document.getElementById('clawDeviceManagerPanel').hidden")
            assert _measure(page)["panelOpen"] is False

            # Escape.
            _open_panel(page)
            page.keyboard.press("Escape")
            page.wait_for_function("() => document.getElementById('clawDeviceManagerPanel').hidden")
            assert _measure(page)["panelOpen"] is False

            # A click outside the panel.
            _open_panel(page)
            page.click("#emptyState h1")
            page.wait_for_function("() => document.getElementById('clawDeviceManagerPanel').hidden")
            assert _measure(page)["panelOpen"] is False

            # The composer controls below the panel stay uncovered and clickable.
            _open_panel(page)
            below = _measure(page)
            assert below["webHidden"] is False
            assert below["web"]["height"] > 2
            assert not _intersects(below["web"], below["panel"])
            uncovered = page.eval_on_selector(
                "#webSearchButton",
                """el => {
                    const b = el.getBoundingClientRect();
                    const top = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
                    return !top || top === el || el.contains(top);
                }""",
            )
            assert uncovered is True
            page.click("#webSearchButton")
            clicked = _measure(page)
            # The click reached the composer control: the panel did not swallow
            # it. (The panel may dismiss on the outside click, as a popover
            # should, but it never eats the click.)
            assert below["webPressed"] != "true"
            assert clicked["webPressed"] == "true"
            assert clicked["scrollWidth"] == clicked["clientWidth"]
        finally:
            browser.close()


@pytest.mark.parametrize("window", RATIO_WINDOWS)
@requires_browser
def test_the_first_screen_top_bottom_split_is_about_one_to_two(static_url, window):
    width, height = window
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(static_url)
            _ready(page)
            page.wait_for_function(SETTLE)
            columns = page.evaluate(
                """() => {
                    const column = document.querySelector('.conversation').getBoundingClientRect();
                    const group = document.getElementById('emptyState').getBoundingClientRect();
                    const composer = document.querySelector('.composer-wrap').getBoundingClientRect();
                    return {columnTop: column.top, groupTop: group.top, groupBottom: group.bottom, composerTop: composer.top};
                }"""
            )
            top_gap = columns["groupTop"] - columns["columnTop"]
            bottom_gap = columns["composerTop"] - columns["groupBottom"]
            assert top_gap > 0
            assert bottom_gap > 0
            assert 0.4 <= top_gap / bottom_gap <= 0.6
        finally:
            browser.close()


@requires_browser
def test_the_device_rows_lead_with_the_name_and_the_id_stays_readable(static_url):
    ConnectorHandler.directory_reads = 0
    ConnectorHandler.selection_posts = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(static_url)
            _ready(page)

            _open_panel(page)
            page.wait_for_function(
                "() => document.querySelectorAll('#clawDeviceManagerList .claw-device-manager-item').length >= 12"
            )

            rows = page.eval_on_selector_all(
                "#clawDeviceManagerList .claw-device-manager-item",
                """els => els.map(el => {
                    const detail = el.querySelector('.claw-device-manager-id');
                    return {
                        name: (el.querySelector('strong') || {}).textContent || null,
                        idText: detail ? detail.textContent : null,
                        idTitle: detail ? detail.title : null,
                        order: Array.from(el.querySelector('.claw-device-manager-detail').children).map(
                            c => c.className || c.tagName
                        ),
                        state: (el.querySelector('.claw-device-manager-state') || {}).textContent || null,
                        choose: (el.querySelector('.claw-device-manager-select') || {}).textContent || null,
                        chooseEnabled: (el.querySelector('.claw-device-manager-select') || {}).disabled !== true
                    };
                })""",
            )
            assert len(rows) == 12
            assert rows[0]["name"] == "내 데스크톱"
            assert rows[0]["state"] == "온라인 · 작업 승인 필요"
            assert rows[1]["state"] == "오프라인"
            assert rows[0]["choose"] == "작업 대상 후보로 선택"
            assert rows[0]["chooseEnabled"] is True
            # The device name leads the row; the ID follows below it.
            assert rows[0]["order"][0] == "STRONG"
            assert "claw-device-manager-id" in rows[0]["order"][1:]
            # The long server ID is shown truncated and readable in full.
            assert rows[0]["idText"] == rows[0]["idTitle"]
            assert len(rows[0]["idText"]) > 40
            assert page.eval_on_selector(
                "#clawDeviceManagerList .claw-device-manager-item .claw-device-manager-id",
                "el => getComputedStyle(el).textOverflow === 'ellipsis' && "
                "el.getBoundingClientRect().width > 0 && el.scrollWidth >= el.clientWidth",
            )

            # Refresh asks the server for the directory again.
            reads_before = ConnectorHandler.directory_reads
            page.click("#clawDeviceManagerPanel .claw-device-manager-refresh")
            page.wait_for_function(
                "() => document.querySelector('#clawDeviceManagerStatus').textContent.includes('선택하세요')"
            )
            assert ConnectorHandler.directory_reads == reads_before + 1

            # Selecting a device still saves the server-owned preference.
            page.click("#clawDeviceManagerList .claw-device-manager-select")
            page.wait_for_function(
                "() => document.querySelector('#clawDeviceManagerStatus').textContent.includes('선택됨')"
            )
            assert ConnectorHandler.selection_posts == [{"device_id": "owner-node-00-%s" % ("b" * 40)}]
            pressed = page.eval_on_selector(
                "#clawDeviceManagerList .claw-device-manager-select",
                "el => el.getAttribute('aria-pressed')",
            )
            assert pressed == "true"

            # The panel scrolls its own content instead of pushing the composer.
            settled = _measure(page)
            assert settled["overflowY"] == "auto"
            assert settled["scrollable"] is True
            assert settled["scrollWidth"] == settled["clientWidth"]
        finally:
            browser.close()
