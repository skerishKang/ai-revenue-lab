"""#5634 first screen and the PC connection panel: one entry, one head line.

Two things changed on the first screen, and both of them are presentation:

  1. the first starter card is the computer connection entry, not the
     "easy explanation" prompt. Clicking it must open the SAME panel the
     composer PC status control opens, because there is one device directory
     reader and one device authority in the page,
  2. the greeting plus the four cards used to float in the middle of the
     first screen. They now sit in the top third of the space between the
     top of the content column and the fixed composer, so the top : bottom split
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
static tests below pin the shape of that contract through parsed attribute
maps, CSS rules and locale values (#8060 21차: no raw sheet text in this
module); the browser tests measure it.

No connector code, endpoint, migration, worker or production deploy is touched.
"""
from __future__ import annotations
import locale_bundle

import re

import pytest
from _support import claw_static
from _support.home_pc_card_panel_harness import (
    DIRECTORY,
    ConnectorHandler,
    index_button_subtree,
    static_url_fixture,
)
from _support.html_tags import tags_for_page
from css_rules import (
    declaration,
    find_rules_with_selector,
    rule_selector_list_contains,
    rules_for_sheet,
)

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

# The three windows of the verification list.
WINDOWS = ((1440, 900), (820, 1180), (390, 844))
# Only the windows wide enough for the 1 : 2 rule to apply (the phone keeps its
# own 16px start, because its block is taller than the screen).
RATIO_WINDOWS = ((1440, 900), (820, 1180))

# The locale sheet binds keys to selectors with inline pairs
# ["#selector", "key"]; the parsed set is what the binding checks assert on.
BINDING = re.compile(r'\["([^"]+)",\s*"([^"]+)"\]')


def _locale_bindings():
    return set(BINDING.findall(claw_static.locale_source()))


def _index_ids():
    return {attrs["id"] for _tag, attrs in tags_for_page("index.html")
            if attrs.get("id")}


@pytest.fixture(scope="session")
def static_url():
    yield from static_url_fixture()


def _intersects(first, second):
    return not (
        first["right"] <= second["left"]
        or first["left"] >= second["right"]
        or first["bottom"] <= second["top"]
        or first["top"] >= second["bottom"]
    )


# ---------------------------------------------------------------------------
# Static contracts: the shape of the change and the shape of the contract that
# must not move. Every sheet read lives in _support; the tests assert on
# parsed attribute maps, CSS declarations and locale values.
# ---------------------------------------------------------------------------


def test_the_first_card_is_the_computer_connection_entry():
    subtree = index_button_subtree("pcConnectStarter")
    button_attrs = subtree[0][1]
    assert button_attrs.get("class") == "starter"
    assert button_attrs.get("data-pc-connect-starter") == "true"
    # The card's headline carries the bound locale key, not inline copy.
    assert [attrs for _tag, attrs in subtree
            if attrs.get("data-locale-key") == "pc-connect-title"]
    # #5573 step 1: the status line on the card belongs to the connect flow's
    # own PC-list state, so the locale key for the old static copy is gone.
    assert not [attrs for _tag, attrs in subtree
                if attrs.get("data-locale-key") == "pc-connect-copy"]
    assert claw_static.locale_value("pc-connect-title", "ko") == "내 컴퓨터"
    # The card the first screen used to open with is gone for good.
    assert all(attrs.get("data-skill") != "explain"
               for _tag, attrs in tags_for_page("index.html"))
    assert "AI를 처음 쓰는 사람에게" not in claw_static.sheet("index.html")
    assert "쉽게 설명해줘" not in claw_static.sheet("index.html")


def test_the_card_opens_the_one_connect_flow():
    """#5573 step 1 (2026-10-29): the card no longer walks the owner into the
    device directory panel; it opens the ONE connect flow (modal, download,
    self-closing wait), like every other entry."""
    subtree = index_button_subtree("pcConnectStarter")
    button_attrs = subtree[0][1]
    assert button_attrs.get("type") == "button"
    assert button_attrs.get("aria-haspopup") == "dialog"
    assert button_attrs.get("aria-expanded") == "false"
    assert "aria-controls" not in button_attrs
    # The PC-list status line the connect flow paints lives on the card.
    assert any("data-pc-connect-state" in attrs for _tag, attrs in subtree)
    # The card is the first entry card, so it must come before the others.
    order = {attrs["id"]: position for position, (_tag, attrs)
             in enumerate(tags_for_page("index.html")) if attrs.get("id")}
    assert order["pcConnectStarter"] < order["documentStarterButton"]


def test_the_starter_grid_keeps_four_cards_without_a_duplicate_prompt():
    ids = _index_ids()
    assert "documentStarterButton" in ids
    assert "writingStarterButton" in ids
    assert "webSearchStarterButton" not in ids
    assert all(attrs.get("data-skill") != "explain"
               for _tag, attrs in tags_for_page("index.html"))

def test_the_locale_covers_the_new_card_in_both_languages():
    assert claw_static.locale_value("pc-connect-title", "ko") == "내 컴퓨터"
    assert claw_static.locale_value("pc-connect-title", "en") == "My computer"
    bindings = _locale_bindings()
    assert ("#pcConnectStarter strong", "pc-connect-title") in bindings
    # #5573 step 1: the card's status line is the connect flow's own PC-list
    # state, so the locale sheet no longer owns (or clobbers) it.
    known = set(locale_bundle.keys("ko")) | set(locale_bundle.keys("en")) | {
        key for _selector, key in bindings}
    assert "pc-connect-copy" not in known
    assert not [selector for selector, _key in bindings
                if selector.startswith("#pcConnectStarter small")]
    # The card is a real control now: nothing may bind the first starter slot
    # as a prompt again.
    assert not [selector for selector, _key in bindings
                if selector.startswith(".starter:nth-child(1)")]


def test_the_entries_route_through_the_one_connect_flow():
    """#5573 step 1: the composer control and the first-screen card both go
    through the one connect flow; the directory panel keeps its own path."""
    assert claw_static.js_statement(
        "pc-connect-flow.js", 'STARTER_ID = "pcConnectStarter"')
    assert claw_static.js_statement("pc-connect-flow.js", "function wireStarter")
    assert 'getElementById("pcConnectStarter")' not in claw_static.sheet(
        "claw-composer-connection-status.js")
    # The composer control connects through the flow: popover when a PC is
    # connected, the modal otherwise; the panel path is only the fallback.
    assert "PadiemPcConnectFlow" in claw_static.sheet("claw-composer-connection-status.js")
    assert claw_static.js_statement(
        "claw-composer-connection-status.js", "flow.togglePopover(button)")
    # An opening click on the card must not immediately close the panel it
    # opened, so the card is excluded from the outside-click guard. The
    # guidance surface joins the exclusion: it reads the panel's own rendered
    # states, so its clicks keep the directory open (#4139 summary contract).
    guards = re.findall(r'target\.closest\("([^"]*)"\)',
                        claw_static.sheet("claw-device-manager.js"))
    assert len(guards) == 1
    assert {part.strip() for part in guards[0].split(",")} == {
        "#composerPcStatus", "#pcConnectStarter", "#clawDeviceGuidance"}
    assert claw_static.js_statement("claw-device-manager.js", "root.append(toggle, panel)")


def test_the_panel_head_is_one_line_with_its_touch_floor_intact():
    rules = rules_for_sheet("claw-device-manager.css")
    assert find_rules_with_selector(rules, ".claw-device-manager-head")
    # Refresh sits next to the title, close keeps the right edge of the row.
    assert claw_static.css_declaration(
        "claw-device-manager.css",
        ".claw-device-manager-head .claw-device-manager-refresh", "order") == ["1"]
    assert claw_static.css_declaration(
        "claw-device-manager.css",
        ".claw-device-manager-head .claw-device-manager-close", "order") == ["3"]
    assert claw_static.css_declaration(
        "claw-device-manager.css",
        ".claw-device-manager-head .claw-device-manager-close", "margin-left") == ["auto"]
    flex = [value for value in claw_static.css_declaration(
        "claw-device-manager.css", ".claw-device-manager-refresh", "flex")
        if value is not None]
    assert flex == ["0 0 auto"]
    # The old stacked head and its separate action row are gone.
    assert all((declaration(rule, "flex-direction") or "") != "row-reverse"
               for rule in rules)
    assert not [rule for rule in rules
                if any("claw-device-manager-actions" in selector
                       for selector in rule.selectors)]
    # The shared action floor that #4139 pinned must not move.
    floor = [rule for rule in rules if rule_selector_list_contains(
        rule, ".claw-device-manager-close",
        ".claw-device-manager-refresh", ".claw-device-manager-select")]
    assert len(floor) == 1
    assert declaration(floor[0], "font-size") == ".8rem"
    assert declaration(floor[0], "min-height") == "44px"


def test_the_panel_stays_above_the_composer_and_scrolls_its_own_content():
    rules = rules_for_sheet("claw-device-manager.css")
    # The base composition, outside the phone media overrides that only rescale
    # the same panel. The layout rule and the anchored rule share the selector;
    # exactly one of them carries the composer anchor and its bounds.
    anchored = [rule for rule in find_rules_with_selector(rules, ".claw-device-manager-panel")
                if rule.media is None and declaration(rule, "bottom") is not None]
    assert len(anchored) == 1
    assert declaration(anchored[0], "bottom") == "22px"
    assert declaration(anchored[0], "max-height") == "min(330px, 46vh)"
    assert declaration(anchored[0], "overflow-y") == "auto"
    # The frame stays click-through and only its form controls take the
    # pointer, so the content behind the panel keeps working. That is the
    # #5014 contract: granting the pointer to the panel's own head covers the
    # cards that sit under it.
    assert declaration(anchored[0], "pointer-events") == "none"
    controls = [rule for rule in rules if rule_selector_list_contains(
        rule,
        ".claw-device-manager-panel button",
        ".claw-device-manager-panel a",
        ".claw-device-manager-panel input",
        ".claw-device-manager-panel select",
        ".claw-device-manager-panel textarea",
        ".claw-device-manager-panel label",
    )]
    assert len(controls) == 1
    assert declaration(controls[0], "pointer-events") == "auto"


def test_the_device_id_is_a_detail_value_not_a_row_header():
    assert claw_static.js_statement(
        "claw-device-manager.js", 'element("small", "claw-device-manager-id", device.deviceId)')
    assert claw_static.js_statement("claw-device-manager.js", "id.title = device.deviceId;")
    assert claw_static.js_statement(
        "claw-device-manager.js", "name.title = device.deviceName || device.deviceId;")
    assert claw_static.js_statement(
        "claw-device-manager.js",
        'if (device.deviceId && device.deviceId !== (device.deviceName || "")) {')
    rules = rules_for_sheet("claw-device-manager.css")
    id_rule = find_rules_with_selector(rules, ".claw-device-manager-id")
    assert len(id_rule) == 1
    assert declaration(id_rule[0], "max-width") == "112px"
    assert declaration(id_rule[0], "text-overflow") == "ellipsis"
    assert declaration(id_rule[0], "white-space") == "nowrap"


def test_the_first_screen_split_is_one_to_two():
    """The 1 : 2 first-screen split is one shared origin, not one per product.

    #5561: this contract used to require two constants -- 747px for Chat and
    836px for Claw, because the Claw hero block measures 89px more. Dividing a
    per-product number by three moved the shared row, so the Claw brand line sat
    ~30px below the Chat one on the same screen. One token now holds the
    expression; a taller product block changes the space under the hero only.
    """
    # Phase 2 moved the consumer rule itself to the shared frame and keyed it on
    # the layout variant, so a new page inherits the composition by declaring the
    # variant instead of adding a sheet. This file now documents the decision.
    frame_rules = rules_for_sheet("shared-six-panel-frame.css")
    assert [rule for rule in frame_rules
            if declaration(rule, "--padiem-first-screen-inset")
            == "max(12px, calc((100dvh - 620px) / 3))"]
    # 11-03 audit: the greeting stopped breaking into three lines, so the Chat
    # block this origin was composed around measured 330px instead of 476px at
    # 1440x900. The constant moved with the measured block; the expression and
    # the single-token rule are unchanged.
    assert any(rule.media == "(min-width: 641px)"
               and declaration(rule, "padding-top")
               == "var(--padiem-first-screen-inset)"
               for rule in frame_rules)
    assert any("var(--padiem-first-screen-inset)" in value
               for rule in frame_rules for value in rule.declarations.values())
    assert any(selector.startswith('.app-shell[data-layout-variant="conversation"]')
               for rule in frame_rules for selector in rule.selectors)
    first_use = rules_for_sheet("padiem-first-use.css")
    assert all("var(--padiem-first-screen-inset"
               not in (declaration(rule, "padding-top") or "")
               for rule in first_use)
    assert all("calc((100dvh - 836px) / 3)" not in value
               for rule in first_use for value in rule.declarations.values())
    # The composer keeps its own first-use treatment.
    assert find_rules_with_selector(first_use, '.app-shell[data-state="home"] .composer')


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
    const attachment = document.getElementById('attachmentButton');
    const tier = document.querySelector('.composer-tier-trigger');
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
        attachment: box(attachment),
        tier: box(tier),
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
    # #5573 step 1: the panel's first-screen entries no longer open it; the
    # tests drive the panel through its own toggle directly.
    page.evaluate("document.getElementById('clawDeviceManagerToggle').click()")
    page.wait_for_function("() => !document.getElementById('clawDeviceManagerPanel').hidden")


def _ready(page):
    page.wait_for_function(
        "() => !!document.getElementById('pcConnectStarter') && "
        "!!document.getElementById('clawDeviceManagerPanel')"
    )


@pytest.mark.parametrize("window", WINDOWS)
@requires_browser
def test_the_first_card_opens_the_modal_and_the_panel_keeps_its_shape(static_url, window):
    width, height = window
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(static_url)
            _ready(page)

            before = _measure(page)
            labels = [item["strong"] for item in before["cardLabels"] if item["visible"]]
            assert "내 컴퓨터" in labels
            assert "쉽게 설명해줘" not in labels
            assert len(labels) == 4
            assert before["card"]["height"] > 2
            assert before["panelOpen"] is False
            assert before["cardExpanded"] == "false"
            assert before["scrollWidth"] == before["clientWidth"]

            # #5573 step 1: the first card opens the ONE connect flow — the
            # modal — and Escape closes it; the panel keeps its own toggle path.
            page.click("#pcConnectStarter")
            page.wait_for_function(
                "() => !!document.querySelector('.pc-connect-backdrop') && "
                "!document.querySelector('.pc-connect-backdrop').hidden"
            )
            page.keyboard.press("Escape")
            page.wait_for_function("() => document.querySelector('.pc-connect-backdrop').hidden")

            _open_panel(page)
            after = _measure(page)
            panel, head = after["panel"], after["head"]
            title, refresh, close = after["title"], after["refresh"], after["close"]
            composer, composer_wrap = after["composer"], after["composerWrap"]

            assert after["panelOpen"] is True
            assert after["cardExpanded"] == "false"
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
            assert opened["cardExpanded"] == "false"

            # #5573 step 1: the composer PC control no longer toggles the
            # panel. The directory fixture here reports connected devices, so
            # the control opens the PC-list popover; Escape closes it while
            # the panel stays as it was. The panel open above started the
            # directory read; wait for its snapshot to reach the control
            # before clicking, so the popover path is deterministic.
            page.wait_for_function(
                "() => document.getElementById('composerPcStatus').dataset.state === 'connected'"
            )
            page.click("#composerPcStatus")
            page.wait_for_function(
                "() => !!document.querySelector('.pc-connect-popover') && "
                "!document.querySelector('.pc-connect-popover').hidden"
            )
            page.keyboard.press("Escape")
            page.wait_for_function("() => document.querySelector('.pc-connect-popover').hidden")

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

            # The remaining attachment and model controls stay uncovered by the panel.
            below = _measure(page)
            assert below["attachment"]["height"] >= 44
            assert below["tier"]["height"] > 2
            assert not _intersects(below["tier"], below["panel"])
            page.evaluate("""() => {
                window.__tierClickReached = false;
                document.addEventListener('click', event => {
                    if (event.target.closest('.composer-tier-trigger')) window.__tierClickReached = true;
                }, {once: true, capture: true});
            }""")
            page.click(".composer-tier-trigger")
            assert page.evaluate("() => window.__tierClickReached") is True
            clicked = _measure(page)
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
            assert rows[0]["state"] == "온라인 · 바로 작업"
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
            assert ConnectorHandler.selection_posts == [
                {"device_id": DIRECTORY["devices"][0]["deviceId"]}]
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
