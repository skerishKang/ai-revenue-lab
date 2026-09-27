"""verify_browser.py — real-browser verification for the B67 static review surface.

Not a unit test. This drives a real Chromium at the three required viewports,
captures screenshots as evidence, and reports the checks the #3138 slice asks
for: layout overflow, the 3-column desktop workspace, the 390px single-column
conversation, the evidence panel vs drawer, the fail-closed state, keyboard
focus visibility, and 44px touch targets.

Run:  python reference/business-67-padiem-legal-v1/tests/verify_browser.py
The surface must already be served (any static server on the URL below).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8899/"
OUT = Path(__file__).resolve().parent.parent / "docs"

VIEWPORTS = {
    "desktop": (1440, 1000),
    "tablet": (768, 1024),
    "mobile": (390, 844),
}

# The nine reviewable states from #3138, minus H/I which are width-driven
# rather than switchable.
# (data-value, screenshot name, label) — these MUST match index.html exactly.
STATES = [
    ("home", "a-home", "새 조사"),
    ("unified", "b-unified", "통합"),
    ("official", "c-official", "공식"),
    ("drive", "d-drive", "Drive"),
    ("provenance", "e-provenance", "페이지"),
    ("fail-closed", "f-fail-closed", "근거 없음"),
    ("disconnected", "g-disconnected", "미연결"),
]

TOUCH_TARGETS = [
    ".claw-chip",
    ".ev-action",
    ".answer-action",
    ".evidence-trigger",
    ".recent-item",
    ".side-item",
    ".new-chat",
    ".corpus-doc",
    ".prov-locator",
    ".send-button",
    ".tool-button",
    ".evidence-close",
    ".mobile-menu",
]

results: dict[str, object] = {"viewports": {}, "states": {}, "checks": {}}
failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  FAIL  {msg}")


def ok(msg: str) -> None:
    print(f"  ok    {msg}")


def overflow(page) -> dict:
    return page.evaluate(
        """() => ({
            scrollW: document.documentElement.scrollWidth,
            clientW: document.documentElement.clientWidth,
            bodyScrollW: document.body.scrollWidth,
            bodyClientW: document.body.clientWidth,
        })"""
    )


def check_no_overflow(page, label: str) -> None:
    o = overflow(page)
    if o["scrollW"] > o["clientW"] + 1:
        fail(f"{label}: horizontal overflow {o['scrollW']} > {o['clientW']}")
    else:
        ok(f"{label}: no horizontal overflow ({o['clientW']}px)")


def check_touch_targets(page, label: str) -> None:
    small = page.evaluate(
        """(selectors) => {
            const bad = [];
            for (const sel of selectors) {
                for (const node of document.querySelectorAll(sel)) {
                    if (node.offsetParent === null && node.getClientRects().length === 0) continue;
                    const r = node.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    if (r.height < 44 || r.width < 44) {
                        bad.push({sel, w: Math.round(r.width), h: Math.round(r.height),
                                  text: (node.textContent || '').trim().slice(0, 24)});
                    }
                }
            }
            return bad;
        }""",
        TOUCH_TARGETS,
    )
    if small:
        for item in small:
            fail(f"{label}: touch target {item['sel']} is {item['w']}x{item['h']} < 44px ({item['text']!r})")
    else:
        ok(f"{label}: all touch targets >= 44px")


def check_focus_visible(page, label: str, stops: int = 30) -> None:
    """Tab through the surface with real keystrokes and confirm each focused
    control actually paints an outline.

    Programmatic .focus() is NOT used: it does not set :focus-visible in
    Chromium unless a keyboard interaction preceded it, which made an earlier
    version of this check report false negatives on every control.
    """
    page.evaluate("() => document.body.focus()")
    page.keyboard.press("Home")
    page.click("#skipLinkOrBody", force=True) if page.locator("#skipLinkOrBody").count() else None

    missing: list[str] = []
    visited = 0
    for _ in range(stops):
        page.keyboard.press("Tab")
        info = page.evaluate(
            """() => {
                const n = document.activeElement;
                if (!n || n === document.body) return null;
                // An element may paint its own ring, or delegate it to a
                // :focus-within ancestor (the composer textarea does exactly
                // this). Accept either, as long as a ring is actually visible.
                let has = false;
                for (let cur = n, i = 0; cur && i < 4; cur = cur.parentElement, i++) {
                    const cs = getComputedStyle(cur);
                    const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
                    const shadow = cs.boxShadow && cs.boxShadow !== 'none';
                    if (outline || shadow) { has = true; break; }
                }
                return {
                    has,
                    name: (n.id || n.className || n.tagName).toString().slice(0, 40),
                };
            }"""
        )
        if info is None:
            continue
        visited += 1
        if not info["has"]:
            missing.append(info["name"])

    if visited == 0:
        fail(f"{label}: keyboard traversal reached no focusable element")
    elif missing:
        fail(f"{label}: {len(missing)}/{visited} tab stops lack a visible focus ring: {missing[:5]}")
    else:
        ok(f"{label}: all {visited} keyboard tab stops show a visible focus ring")


def check_live_region(label: str, page) -> None:
    n = page.evaluate(
        """() => document.querySelectorAll('[aria-live="polite"]').length"""
    )
    if n != 1:
        fail(f"{label}: expected exactly 1 aria-live=polite region, found {n}")
    else:
        ok(f"{label}: exactly one polite live region")


def check_evidence_panel_vs_drawer(page, width: int, label: str) -> None:
    panel_visible = page.evaluate(
        """() => { const p = document.getElementById('evidencePanel');
                   return p ? getComputedStyle(p).display !== 'none' : false; }"""
    )
    drawer_offscreen = page.evaluate(
        """() => { const d = document.getElementById('evidenceDrawer');
                   return d ? d.getBoundingClientRect().top >= window.innerHeight - 1 : null; }"""
    )
    if width <= 920:
        if panel_visible:
            fail(f"{label}: desktop evidence panel is still rendered at {width}px")
        else:
            ok(f"{label}: desktop panel removed at {width}px (drawer serves it)")
        if drawer_offscreen is False:
            fail(f"{label}: evidence drawer is on-screen while closed")
    else:
        if not panel_visible:
            fail(f"{label}: desktop evidence panel missing at {width}px")
        else:
            ok(f"{label}: desktop evidence panel rendered at {width}px")


def check_keyboard_drawer(page, label: str) -> None:
    """Open the evidence sheet with the keyboard only, then confirm focus moved
    inside it, Escape closes it, and focus returns to the trigger."""
    page.click("#evidenceTrigger")
    page.wait_for_timeout(300)
    inside = page.evaluate(
        """() => document.getElementById('evidenceDrawer').contains(document.activeElement)"""
    )
    if not inside:
        fail(f"{label}: focus did not move into the evidence drawer")
    else:
        ok(f"{label}: focus moves into the drawer on open")

    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    after = page.evaluate(
        """() => ({
            open: document.getElementById('evidenceDrawer').dataset.open,
            inert: document.getElementById('evidenceDrawer').inert,
            focusBack: document.activeElement && document.activeElement.id,
        })"""
    )
    if after["open"] != "false":
        fail(f"{label}: Escape did not close the drawer")
    elif not after["inert"]:
        fail(f"{label}: drawer is not inert after close (it would trap focus)")
    elif after["focusBack"] != "evidenceTrigger":
        fail(f"{label}: focus returned to {after['focusBack']!r}, expected evidenceTrigger")
    else:
        ok(f"{label}: Escape closes drawer, inert applied, focus restored to trigger")


def check_authority_split(page) -> None:
    got = page.evaluate(
        """() => Array.from(document.querySelectorAll('#evidenceList .ev')).map(ev => ({
               n: ev.dataset.evidenceN,
               auth: ev.dataset.authority,
               badge: (ev.querySelector('.auth-badge') || {}).textContent,
               rail: getComputedStyle(ev).borderLeftColor,
               style: getComputedStyle(ev).borderLeftStyle,
           }))"""
    )
    classes = {row["badge"]: row for row in got}
    if "1차자료" not in classes:
        fail("no 1차자료 (official primary authority) card rendered")
    if "2차자료" not in classes:
        fail("no 2차자료 (secondary) card rendered")
    if "당사자 문서" not in classes:
        fail("no 당사자 문서 (party document) card rendered")
    unhooked = [row["n"] for row in got if not row.get("auth")]
    if unhooked:
        fail(f"evidence card(s) {unhooked} carry no data-authority, so the rail cannot be styled")
    p, s = classes.get("1차자료"), classes.get("2차자료")
    if p and s and p["rail"] == s["rail"] and p["style"] == s["style"]:
        fail("primary and secondary authority render identically (no visual distinction)")
    else:
        ok("primary vs secondary authority are visually distinct (rail style + colour + label)")
    ok(f"authority badges rendered: {sorted(classes)}")


def check_provenance_unverified(page) -> None:
    got = page.evaluate(
        """() => Array.from(document.querySelectorAll('#evidenceList .prov-locator'))
                 .map(n => n.dataset.verified)"""
    )
    if not got:
        fail("no page/section locator rendered in the evidence panel")
    elif any(v != "false" for v in got):
        fail(f"a page locator claims to be verified: {got}")
    else:
        ok(f"all {len(got)} page locators are marked unverified (page numbers are not model-generated)")


def check_fail_closed(page) -> None:
    text = page.evaluate(
        """() => document.getElementById('conversation').textContent"""
    )
    if "검증 가능한 근거를 찾지 못했습니다" not in text:
        fail("fail-closed state does not show the required message")
    else:
        ok("fail-closed state shows '검증 가능한 근거를 찾지 못했습니다'")
    for label in ("검색 범위 바꾸기", "내 Drive 확인"):
        if label not in text:
            fail(f"fail-closed state missing recovery action: {label}")
    ok("fail-closed state offers both recovery actions")
    cards = page.evaluate("""() => document.querySelectorAll('#evidenceList .ev').length""")
    if cards != 0:
        fail(f"fail-closed state still shows {cards} evidence cards")
    else:
        ok("fail-closed state shows zero evidence cards (no confident answer without evidence)")


def check_no_legacy_hwp_claim(page) -> None:
    text = page.evaluate("""() => document.body.textContent""")
    if "HWP/HWPX 지원" in text or "HWP · HWPX 지원" in text:
        fail("UI claims HWP/HWPX support")
    if "HWP" not in text:
        fail("HWP is not mentioned at all; the unsupported state must be visible")
    ok("legacy HWP is shown as unsupported, not as supported")


def check_demo_labelling(page) -> None:
    labels = page.evaluate(
        """() => ({
            demoLabels: document.querySelectorAll('.demo-label').length,
            corpusState: (document.querySelector('.corpus-state') || {}).textContent,
            docNote: (document.querySelector('.corpus-empty') || {}).textContent,
        })"""
    )
    if labels["demoLabels"] < 1:
        fail("no DEMO / demo-label marker present")
    else:
        ok(f"DEMO labelling present ({labels['demoLabels']} markers)")
    if labels.get("corpusState") and "DEMO" not in labels["corpusState"]:
        fail(f"Drive connection state is not marked DEMO: {labels['corpusState']!r}")
    else:
        ok(f"Drive state labelled: {labels.get('corpusState')!r}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"Verifying {URL}\n")

    with sync_playwright() as p:
        # The host has a system proxy that swallows loopback traffic, which made
        # Chromium hang on 127.0.0.1 while curl succeeded. Bypass it explicitly.
        browser = p.chromium.launch(args=["--no-proxy-server"])
        for name, (w, h) in VIEWPORTS.items():
            print(f"[{name}] {w}x{h}")
            ctx = browser.new_context(viewport={"width": w, "height": h},
                                      device_scale_factor=1)
            page = ctx.new_page()
            errors: list[str] = []
            page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}")
                    if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

            page.goto(URL, wait_until="domcontentloaded")
            # The desktop evidence panel is display:none at <=920px, so waiting
            # for ITS cards to be visible would time out on tablet/mobile. The
            # conversation renders at every width and is populated last.
            page.wait_for_function(
                "() => document.getElementById('conversation').children.length > 0",
                timeout=15000,
            )
            page.wait_for_timeout(250)

            check_no_overflow(page, name)
            check_touch_targets(page, name)
            check_focus_visible(page, name)
            check_live_region(name, page)
            check_evidence_panel_vs_drawer(page, w, name)
            check_authority_split(page)
            check_provenance_unverified(page)
            check_no_legacy_hwp_claim(page)
            check_demo_labelling(page)
            if w <= 920:
                check_keyboard_drawer(page, name)
                check_mobile_citation_opens_drawer(page)
                if w == 390:
                    check_mobile_sidebar_trap_cleanup(page)
                    page.set_viewport_size({"width": w, "height": h})
                    page.wait_for_timeout(300)
            else:
                check_desktop_sidebar_interactive(page)
                check_desktop_evidence_uses_panel(page)
                check_drive_disconnected_truth(page)
                check_state_scope_single_authority(page)
                check_matter_consistency(page)
                check_composer_submit_paths(page)
                check_web_scope_selectable(page)
                check_web_scope_survives_reload(page)
                check_scope_grounded_results(page)
                check_authority_ordering(page)
                check_disconnected_truth_all_scopes(page)

            page.screenshot(path=str(OUT / f"{name}-B-unified.png"), full_page=False)

            if errors:
                for e in errors:
                    fail(f"{name}: {e}")
            else:
                ok(f"{name}: no console errors")

            results["viewports"][name] = {"width": w, "height": h, "consoleErrors": errors}
            ctx.close()

        # ── State sweep at desktop width ────────────────────────────────
        print("\n[states] 1440x1000")
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_function(
            "() => document.getElementById('conversation').children.length > 0",
            timeout=15000,
        )
        page.wait_for_timeout(300)

        for state_id, shot, label in STATES:
            chip = page.locator(f'#stateChips .claw-chip[data-value="{state_id}"]')
            if chip.count() != 1:
                fail(f"state {state_id}: expected exactly 1 chip in #stateChips, found {chip.count()}")
                continue
            chip.click()
            page.wait_for_timeout(250)
            text = page.evaluate("""() => document.getElementById('conversation').textContent""")
            cards = page.evaluate("""() => document.querySelectorAll('#evidenceList .ev').length""")
            if not text.strip():
                fail(f"state {state_id} rendered an empty conversation")
            page.screenshot(path=str(OUT / f"state-{shot}.png"), full_page=False)
            results["states"][state_id] = {
                "label": label, "evidenceCards": cards, "textLen": len(text.strip())
            }
            ok(f"state {state_id} ({label}): {cards} evidence card(s), {len(text.strip())} chars")

        # Fail-closed gets extra assertions after the sweep.
        page.locator('#stateChips .claw-chip[data-value="fail-closed"]').click()
        page.wait_for_timeout(200)
        check_fail_closed(page)
        page.screenshot(path=str(OUT / "state-f-fail-closed-detail.png"), full_page=False)

        ctx.close()
        browser.close()

    results["failures"] = failures
    (OUT / "browser-verification.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL BROWSER CHECKS PASSED")
    print(f"Screenshots + JSON report: {OUT}")
    return 0


# ── CENTRAL review regressions (#3161) ──────────────────────────────────────
# Each of these corresponds to a real defect found in review, not to a
# hypothetical. They are interaction-level on purpose: an `inert` element is
# skipped by the tab order, so a Tab-count check cannot detect a control that
# is visible but unusable. Every one of these clicks the control for real.


def check_desktop_sidebar_interactive(page) -> None:
    """BLOCKER 1: the desktop sidebar was permanently `inert`.

    `syncSidebar` derived `open` from `mobile && ...`, so on desktop
    `sidebar.inert = !open` was always true — a visible, permanently dead
    control column. Assert the real interaction, not the tab order.
    """
    inert = page.evaluate(
        """() => ({
            sidebar: document.getElementById('sidebar').inert,
            main: document.getElementById('mainPanel').inert,
        })"""
    )
    if inert["sidebar"]:
        fail(f"desktop sidebar is inert ({inert}) — visible but unusable")
    else:
        ok("desktop sidebar is not inert")

    # Prove it by actually clicking a control inside it.
    before = page.evaluate("""() => document.getElementById('topbarTitle').textContent""")
    try:
        page.click("#matterList .recent-item:nth-child(2)", timeout=3000)
    except Exception as e:
        fail(f"desktop matter button is not clickable: {type(e).__name__}")
        return
    after = page.evaluate(
        """() => ({
            title: document.getElementById('topbarTitle').textContent,
            current: document.querySelector('#matterList .recent-item[aria-current="true"]')?.dataset.matter,
        })"""
    )
    if after["title"] == before:
        fail(f"desktop matter click did not change the surface title (still {before!r})")
    else:
        ok(f"desktop matter click works and updates the title ({after['title']!r})")

    # New research button.
    try:
        page.click("#newResearch", timeout=3000)
        page.wait_for_timeout(200)
        if page.evaluate("""() => document.getElementById('appShell').dataset.view""") != "home":
            fail("desktop #newResearch click did not switch to the home view")
        else:
            ok("desktop #newResearch click works")
    except Exception as e:
        fail(f"desktop #newResearch is not clickable: {type(e).__name__}")

    # Corpus document button.
    page.click('#stateChips .claw-chip[data-value="drive"]')
    page.wait_for_timeout(250)
    try:
        page.click("#corpus .corpus-doc", timeout=3000)
        page.wait_for_timeout(150)
        note = page.evaluate("""() => document.getElementById('runtimeNote').textContent""")
        if "샘플 문서" not in note and "hwp" not in note:
            fail(f"desktop corpus click produced no response (note={note!r})")
        else:
            ok("desktop corpus document click works")
    except Exception as e:
        fail(f"desktop corpus document button is not clickable: {type(e).__name__}")


def check_desktop_evidence_uses_panel(page) -> None:
    """BLOCKER 2: a citation click opened the mobile sheet on desktop too."""
    page.click('#stateChips .claw-chip[data-value="unified"]')
    page.wait_for_timeout(250)
    page.click("#conversation .cite")
    page.wait_for_timeout(300)
    after = page.evaluate(
        """() => {
            const d = document.getElementById('evidenceDrawer');
            const active = document.querySelector('#evidenceList .ev[data-active="true"]');
            return {
                drawerOpen: d.dataset.open,
                drawerInert: d.inert,
                drawerOnScreen: d.getBoundingClientRect().top < window.innerHeight - 1,
                activeN: active ? active.dataset.evidenceN : null,
                triggerHidden: document.getElementById('evidenceTriggerRow').hidden,
            };
        }"""
    )
    if after["drawerOpen"] != "false":
        fail(f"desktop citation opened the mobile sheet (data-open={after['drawerOpen']})")
    elif not after["drawerInert"]:
        fail("desktop sheet is not inert while closed")
    elif after["drawerOnScreen"]:
        fail("desktop sheet is on screen while closed")
    elif not after["activeN"]:
        fail("desktop citation did not highlight a right-panel evidence card")
    else:
        ok(f"desktop citation highlights right-panel card [n={after['activeN']}], sheet stays closed")
    if not after["triggerHidden"]:
        fail("the mobile-only evidence trigger is still shown on desktop")
    else:
        ok("mobile-only evidence trigger is hidden on desktop")


def check_mobile_citation_opens_drawer(page) -> None:
    """BLOCKER 2, mobile half: the same click must open the sheet here."""
    page.click("#conversation .cite")
    page.wait_for_timeout(350)
    inside = page.evaluate(
        """() => ({
            open: document.getElementById('evidenceDrawer').dataset.open,
            focusInside: document.getElementById('evidenceDrawer').contains(document.activeElement),
            activeN: document.querySelector('#drawerList .ev[data-active="true"]')?.dataset.evidenceN,
            caller: document.activeElement ? document.activeElement.className : '',
        })"""
    )
    if inside["open"] != "true":
        fail(f"mobile citation did not open the sheet (data-open={inside['open']})")
    elif not inside["focusInside"]:
        fail("mobile sheet opened but focus did not move into it")
    else:
        ok(f"mobile citation opens the sheet, focus inside, card [n={inside['activeN']}] active")

    page.keyboard.press("Escape")
    page.wait_for_timeout(350)
    back = page.evaluate(
        """() => ({
            open: document.getElementById('evidenceDrawer').dataset.open,
            inert: document.getElementById('evidenceDrawer').inert,
            focusClass: document.activeElement ? document.activeElement.className : '',
        })"""
    )
    if back["open"] != "false" or not back["inert"]:
        fail(f"mobile Escape did not close/inert the sheet: {back}")
    elif "cite" not in back["focusClass"]:
        fail(f"focus returned to {back['focusClass']!r}, expected the citation caller")
    else:
        ok("mobile Escape closes the sheet and returns focus to the citation")


def check_drive_disconnected_truth(page) -> None:
    """BLOCKER 3: Drive evidence reappeared while the UI said "disconnected".

    That is the worst possible state for this product — a citation pointing at
    a document the interface claims it cannot see.
    """
    page.click('#stateChips .claw-chip[data-value="disconnected"]')
    page.wait_for_timeout(300)
    disconnected = page.evaluate(
        """() => ({
            connected: window.B67DemoApp.store.get().driveConnected,
            corpusLabel: (document.querySelector('.corpus-state')||{}).textContent,
        })"""
    )
    if disconnected["connected"]:
        fail("disconnected state did not clear driveConnected")

    for target in ("drive", "unified", "provenance"):
        page.click(f'#stateChips .claw-chip[data-value="{target}"]')
        page.wait_for_timeout(250)
        probe = page.evaluate(
            """() => {
                const s = window.B67DemoApp.store.get();
                return {
                    connected: s.driveConnected,
                    driveEvidence: s.evidence.filter(e => e.source_type === 'drive').length,
                    citedNumbers: Array.from(document.querySelectorAll('#conversation .cite'))
                        .map(c => parseInt(c.dataset.cite, 10)),
                    citedInDrive: Array.from(document.querySelectorAll('#conversation .cite'))
                        .some(c => {
                            const n = parseInt(c.dataset.cite, 10);
                            const rec = (window.B67Demo ? null : null);
                            return false;
                        }),
                    cardNums: Array.from(document.querySelectorAll('#evidenceList .ev'))
                        .map(e => parseInt(e.dataset.evidenceN, 10)),
                    answerRendered: !!document.querySelector('#conversation .assistant-content'),
                };
            }"""
        )
        if probe["driveEvidence"] > 0:
            fail(f"'{target}' shows {probe['driveEvidence']} Drive evidence record(s) while disconnected")
        # A citation may only point at a record that is actually in the panel.
        # When it cannot, the surface must fail closed rather than render it.
        stray = [n for n in probe["citedNumbers"] if n not in probe["cardNums"]]
        if stray:
            if probe["answerRendered"]:
                fail(f"'{target}' renders an answer citing [n] {stray} that are not in the panel")
        elif not probe["answerRendered"] and probe["cardNums"]:
            fail(f"'{target}' fails closed although every citation resolves")
    ok("no Drive evidence is produced by any state while Drive is disconnected")
    ok("no citation points at a record missing from the evidence panel")

    # The connection-required state must be explicit, not silently empty.
    page.click('#stateChips .claw-chip[data-value="drive"]')
    page.wait_for_timeout(250)
    text = page.evaluate("""() => document.getElementById('conversation').textContent""")
    if "Drive 자료에 접근할 수 없습니다" not in text:
        fail("Drive-scoped query while disconnected does not explain the blocker")
    else:
        ok("Drive-scoped query while disconnected shows a connection-required state")

    # Reconnect restores truth, explicitly.
    page.click("#corpus .recent-item")
    page.wait_for_timeout(300)
    reconnected = page.evaluate(
        """() => ({
            connected: window.B67DemoApp.store.get().driveConnected,
            driveEvidence: window.B67DemoApp.store.get().evidence.filter(e => e.source_type === 'drive').length,
        })"""
    )
    if not reconnected["connected"] or reconnected["driveEvidence"] == 0:
        fail(f"explicit DEMO connect did not restore Drive evidence: {reconnected}")
    else:
        ok(f"explicit DEMO connect restores Drive evidence ({reconnected['driveEvidence']} records)")


def check_state_scope_single_authority(page) -> None:
    """BLOCKER 4: title, scope chip, and evidence could disagree.

    `state` is now the only routing authority; the scope chip and the title are
    derived from it.
    """
    def probe(expected_state, expected_scope_label):
        got = page.evaluate(
            """() => {
                const pressed = document.querySelector('#conversation .claw-chip[aria-pressed="true"]');
                return {
                    state: window.B67DemoApp.store.get().state,
                    scopeForState: window.B67DemoApp.scopeForState(window.B67DemoApp.store.get().state),
                    title: document.getElementById('topbarTitle').textContent,
                    scopeChip: pressed
                        ? (pressed.querySelector('span:not(.chip-icon)') || pressed).textContent.trim()
                        : null,
                    types: Array.from(new Set(
                        Array.from(document.querySelectorAll('#evidenceList .ev'))
                            .map(e => e.dataset.sourceType)
                    )),
                };
            }"""
        )
        return got

    for st, label, want_type in (
        ("official", "공식 법률자료", "official"),
        ("drive", "내 Drive", "drive"),
        ("unified", "통합", None),
    ):
        page.click(f'#stateChips .claw-chip[data-value="{st}"]')
        page.wait_for_timeout(250)
        got = probe(st, label)
        if got["scopeForState"] != st:
            fail(f"'{st}': scopeForState returned {got['scopeForState']!r}")
        if label not in got["title"]:
            fail(f"'{st}': title {got['title']!r} does not name the scope {label!r}")
        if got["scopeChip"] != label:
            fail(f"'{st}': scope chip is {got['scopeChip']!r}, expected {label!r}")
        if want_type and got["types"] != [want_type]:
            fail(f"'{st}': evidence types are {got['types']}, expected only [{want_type!r}]")
        if not want_type and any(t not in ("official", "drive", "web") for t in got["types"]):
            fail(f"'{st}': unexpected evidence types {got['types']}")
    ok("title, scope chip, and evidence all derive from one state authority")

    # Reload must restore the same triple.
    page.click('#stateChips .claw-chip[data-value="official"]')
    page.wait_for_timeout(250)
    before_matter = page.evaluate("""() => window.B67DemoApp.store.get().matter""")
    before = page.evaluate(
        """() => {
            const chip = document.querySelector('#conversation .claw-chip[aria-pressed="true"]');
            return {
                state: window.B67DemoApp.store.get().state,
                scopeChip: chip ? (chip.querySelector('span:not(.chip-icon)') || chip).textContent.trim() : null,
                title: document.getElementById('topbarTitle').textContent,
            };
        }"""
    )
    page.reload()
    page.wait_for_function(
        "() => document.getElementById('conversation').children.length > 0", timeout=15000)
    page.wait_for_timeout(400)
    after_restore = page.evaluate(
        """() => {
            const chip = document.querySelector('#conversation .claw-chip[aria-pressed="true"]');
            return {
                state: window.B67DemoApp.store.get().state,
                scopeChip: chip ? (chip.querySelector('span:not(.chip-icon)') || chip).textContent.trim() : null,
                title: document.getElementById('topbarTitle').textContent,
            };
        }"""
    )
    if before["state"] != after_restore["state"] or before["scopeChip"] != after_restore["scopeChip"]:
        fail(f"restore changed the routing triple: {before} -> {after_restore}")
    elif not after_restore["title"].startswith(after_restore["scopeChip"]):
        fail(f"restored title {after_restore['title']!r} does not lead with the scope chip label")
    else:
        ok(f"reload/restore reproduces state + scope chip + title scope ({after_restore['state']})")
    matter_now = page.evaluate("""() => window.B67DemoApp.store.get().matter""")
    if matter_now == before_matter:
        fail("matter selection is not reset to a defined default on reload")
    else:
        ok("matter returns to its default on reload (documented: matter is not persisted)")


def check_composer_submit_paths(page) -> None:
    """Composer hardening: form submit is the canonical path, so pointer-send
    cannot navigate the page and Enter-send goes through the same function."""
    start_url = page.url
    page.fill("#composerInput", "포인터 전송 확인")
    page.wait_for_timeout(100)
    page.click("#sendButton")
    page.wait_for_timeout(400)
    after_pointer = page.evaluate(
        """() => ({
            url: location.href,
            value: document.getElementById('composerInput').value,
            state: window.B67DemoApp.store.get().state,
        })"""
    )
    if after_pointer["url"] != start_url:
        fail(f"pointer send navigated the page: {start_url} -> {after_pointer['url']}")
    else:
        ok("pointer send does not navigate")
    if after_pointer["value"] != "":
        fail(f"pointer send did not clear the composer ({after_pointer['value']!r})")
    else:
        ok("pointer send clears the composer")

    page.fill("#composerInput", "엔터 전송 확인")
    page.wait_for_timeout(100)
    page.press("#composerInput", "Enter")
    page.wait_for_timeout(400)
    after_enter = page.evaluate(
        """() => ({url: location.href, value: document.getElementById('composerInput').value})"""
    )
    if after_enter["url"] != start_url:
        fail("Enter send navigated the page")
    else:
        ok("Enter send does not navigate")
    if after_enter["value"] != "":
        fail("Enter send did not clear the composer")
    else:
        ok("Enter send clears the composer")

    page.fill("#composerInput", "줄바꿈 유지")
    page.wait_for_timeout(100)
    page.press("#composerInput", "Shift+Enter")
    page.wait_for_timeout(300)
    shifted = page.evaluate(
        """() => ({
            url: location.href,
            value: document.getElementById('composerInput').value,
            hasNewline: document.getElementById('composerInput').value.indexOf(String.fromCharCode(10)) !== -1,
        })"""
    )
    if shifted["url"] != start_url:
        fail("Shift+Enter navigated the page")
    elif not shifted["hasNewline"]:
        fail("Shift+Enter did not insert a newline (it submitted instead)")
    else:
        ok("Shift+Enter inserts a newline without sending")

    # Empty input must not submit.
    page.fill("#composerInput", "")
    page.wait_for_timeout(150)
    disabled = page.evaluate("""() => document.getElementById('sendButton').disabled""")
    if not disabled:
        fail("send button is enabled with an empty composer")
    else:
        ok("send button is disabled with an empty composer")


def check_matter_consistency(page) -> None:
    """ADD-1: the selected matter must be reflected across the surface, and the
    shared sample corpus must be disclosed rather than implied."""
    page.click('#stateChips .claw-chip[data-value="unified"]')
    page.wait_for_timeout(250)
    titles = set()
    for i in (1, 2, 3):
        page.click(f"#matterList .recent-item:nth-child({i})")
        page.wait_for_timeout(250)
        titles.add(page.evaluate("""() => document.getElementById('topbarTitle').textContent"""))
    if len(titles) != 3:
        fail(f"selecting a matter does not change the title (saw {len(titles)} distinct titles)")
    else:
        ok(f"matter selection updates the title consistently ({len(titles)} distinct)")

    corpus = page.evaluate("""() => document.getElementById('corpus').textContent""")
    if "동일한 샘플 자료" not in corpus:
        fail("the corpus does not disclose that all matters share the sample data")
    else:
        ok("corpus discloses that the sample data is shared across matters")

# ── CENTRAL round-2 regressions (#3161) ─────────────────────────────────────

def _sidebar_probe(page):
    return page.evaluate(
        """() => ({
            open: document.getElementById('appShell').classList.contains('sidebar-open'),
            sidebarInert: document.getElementById('sidebar').inert,
            mainInert: document.getElementById('mainPanel').inert,
            trapActive: window.B67DemoApp.sidebarTrap().isActive(),
            focus: document.activeElement ? (document.activeElement.id || document.activeElement.className) : '',
        })"""
    )


def _check_sidebar_close_path(page, label, close_fn) -> None:
    """Every close path must release the trap, not just the CSS class.

    A drawer that looks closed while its focus trap is still live keeps a
    document-level keydown listener installed, which silently swallows the
    next Tab/Escape. The class state alone cannot detect this.
    """
    page.click("#mobileMenu")
    page.wait_for_timeout(300)
    opened = _sidebar_probe(page)
    if not opened["open"] or opened["sidebarInert"] or not opened["mainInert"]:
        fail(f"{label}: sidebar did not open correctly ({opened})")
        return
    if not opened["trapActive"]:
        fail(f"{label}: sidebar opened but the focus trap is not active ({opened})")
    else:
        ok(f"{label}: open -> sidebar interactive, main inert, trap active")

    close_fn()
    page.wait_for_timeout(350)
    closed = _sidebar_probe(page)
    if closed["open"]:
        page.evaluate("() => window.B67DemoApp.closeSidebar()")
        page.wait_for_timeout(200)
        fail(f"{label}: sidebar class was not removed")
    elif not closed["sidebarInert"]:
        fail(f"{label}: closed sidebar is not inert (off-canvas content stays reachable)")
    elif closed["mainInert"]:
        fail(f"{label}: main panel is still inert after close")
    elif closed["trapActive"]:
        fail(f"{label}: focus trap is STILL ACTIVE after close - a hidden trap remains")
    elif closed["focus"] != "mobileMenu":
        fail(f"{label}: focus returned to {closed['focus']!r}, expected mobileMenu")
    else:
        ok(f"{label}: close -> class off, sidebar inert, main live, trap released, focus on #mobileMenu")


def check_mobile_sidebar_trap_cleanup(page) -> None:
    """BLOCKER A: all three close paths must fully release the trap."""
    # Reset before each path so one failure cannot cascade into the next.
    def reset():
        page.evaluate("() => window.B67DemoApp.closeSidebar()")
        page.wait_for_timeout(200)

    _check_sidebar_close_path(page, "escape", lambda: page.keyboard.press("Escape"))
    reset()
    _check_sidebar_close_path(page, "close-button", lambda: page.click("#sidebarClose"))
    reset()
    # The scrim spans the viewport but the open drawer (z-index 20) covers its
    # left portion, so click the exposed strip on the right. Clicking the
    # element's centre would land on the drawer and test nothing.
    _check_sidebar_close_path(
        page, "scrim",
        lambda: page.click("#sidebarScrim", position={"x": 360, "y": 420}, force=True))

    # The trap must not linger after a breakpoint collapse either.
    page.click("#mobileMenu")
    page.wait_for_timeout(300)
    if not _sidebar_probe(page)["trapActive"]:
        fail("breakpoint: sidebar did not open before the resize")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.wait_for_timeout(400)
    after = _sidebar_probe(page)
    if after["trapActive"]:
        fail("breakpoint collapse to desktop left the sidebar trap active")
    else:
        ok("breakpoint collapse to desktop releases the trap")


def check_web_scope_selectable(page) -> None:
    """BLOCKER B: the 웹 chip looked real and collapsed to 통합 on click."""
    chips = page.evaluate(
        """() => Array.from(document.querySelectorAll('#conversation .claw-chip'))
                 .map(c => c.getAttribute('data-value'))"""
    )
    if "web" not in chips:
        fail(f"the source scope row has no web chip (found {chips})")
        return
    page.click('#conversation .claw-chip[data-value="web"]')
    page.wait_for_timeout(300)
    got = page.evaluate(
        """() => {
            const c = document.querySelector('#conversation .claw-chip[aria-pressed="true"]');
            return {
                state: window.B67DemoApp.store.get().state,
                scopeForState: window.B67DemoApp.scopeForState(window.B67DemoApp.store.get().state),
                chip: c ? (c.querySelector('span:not(.chip-icon)') || c).textContent.trim() : null,
                title: document.getElementById('topbarTitle').textContent,
                types: Array.from(new Set(
                    Array.from(document.querySelectorAll('#evidenceList .ev'))
                        .map(e => e.dataset.sourceType))),
                badge: (document.querySelector('#evidenceList .auth-badge') || {}).textContent,
            };
        }"""
    )
    if got["state"] != "web":
        fail(f"clicking 웹 set state to {got['state']!r}, not 'web'")
    elif got["scopeForState"] != "web":
        fail(f"scopeForState('web') returned {got['scopeForState']!r}")
    elif got["chip"] != "웹":
        fail(f"the web scope chip is not selected (chip={got['chip']!r})")
    elif not got["title"].startswith("웹"):
        fail(f"title is {got['title']!r}, does not begin with 웹")
    elif got["types"] != ["web"]:
        fail(f"web scope shows evidence types {got['types']}, expected only ['web']")
    else:
        ok("웹 is selectable: state, scope chip, title, and web-only evidence")

    if got["badge"] != "2차자료":
        fail(f"web evidence is not labelled secondary (badge={got['badge']!r})")
    else:
        ok("web evidence is labelled 2차자료")


def check_web_scope_survives_reload(page) -> None:
    """A scope the user chose must still be there after a refresh.

    persist() stored "web" happily while restore() validated against the top-bar
    demo strip, which has no `web` entry — so every reload silently dropped the
    scope back to 통합. The reload is the real user action, so it is checked as
    one, not simulated.
    """
    page.evaluate("() => window.B67DemoApp.applyState({state: 'web'})")
    page.wait_for_timeout(250)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(400)
    got = page.evaluate(
        """() => {
            const c = document.querySelector('#conversation .claw-chip[aria-pressed="true"]');
            const cites = Array.from(document.querySelectorAll('#conversation .cite'))
                            .map(x => parseInt(x.dataset.cite, 10));
            const cards = Array.from(document.querySelectorAll('#evidenceList .ev'))
                            .map(e => parseInt(e.dataset.evidenceN, 10));
            return {
                state: window.B67DemoApp.store.get().state,
                chip: c ? (c.querySelector('span:not(.chip-icon)') || c).textContent.trim() : null,
                title: document.getElementById('topbarTitle').textContent,
                answered: !!document.querySelector('#conversation .assistant-content'),
                failClosed: document.getElementById('conversation').textContent
                    .includes('검증 가능한 근거를 찾지 못했습니다'),
                unresolved: cites.filter(n => !cards.includes(n)),
            };
        }"""
    )
    if got["state"] != "web":
        fail(f"web scope was lost on reload: state={got['state']!r}")
    elif got["chip"] != "웹":
        fail(f"web chip is not selected after reload: {got['chip']!r}")
    elif not got["title"].startswith("웹"):
        fail(f"title after reload is {got['title']!r}, does not begin with 웹")
    elif not got["answered"] or got["failClosed"]:
        fail("reloaded web scope did not render its own grounded answer")
    elif got["unresolved"]:
        fail(f"reloaded web scope cites {got['unresolved']} with no evidence card")
    else:
        ok("web scope survives a real reload: chip, title and grounded answer intact")

    # And the restored value must be the state space, not the demo strip.
    persistable = page.evaluate("() => window.B67DemoApp.PERSISTABLE_STATES")
    if "web" not in persistable:
        fail(f"web is not in the persistable state space: {persistable}")
    else:
        ok(f"persistable state space includes the web scope: {persistable}")


def check_scope_grounded_results(page) -> None:
    """BLOCKER C: official/drive/web must render a real grounded answer.

    A text-length check cannot tell a grounded answer from the fail-closed
    card. This asserts the actual structure: an assistant answer exists, a
    citation button exists, every cited number exists in the evidence cards,
    and the generic fail-closed title is absent.
    """
    expected = {
        "unified": {1, 2, 3, 4, 5},
        "official": {4},
        "drive": {1, 2, 3},
        "web": {5},
    }
    for scope, want_cites in expected.items():
        page.evaluate(f"() => window.B67DemoApp.applyState({{state: '{scope}'}})")
        page.wait_for_timeout(300)
        got = page.evaluate(
            """() => ({
                answered: !!document.querySelector('#conversation .assistant-content'),
                hasPrompt: !!document.querySelector('#conversation .message-bubble'),
                cites: Array.from(document.querySelectorAll('#conversation .cite'))
                            .map(c => parseInt(c.dataset.cite, 10)),
                cards: Array.from(document.querySelectorAll('#evidenceList .ev'))
                            .map(e => parseInt(e.dataset.evidenceN, 10)),
                failClosedTitle: document.getElementById('conversation').textContent
                    .includes('검증 가능한 근거를 찾지 못했습니다'),
            })"""
        )
        if not got["answered"]:
            fail(f"{scope}: no grounded answer was rendered")
            continue
        if not got["hasPrompt"]:
            fail(f"{scope}: grounded answer rendered without the user turn")
        if got["failClosedTitle"]:
            fail(f"{scope}: fell into generic fail-closed although records are present")
        unresolved = sorted(set(got["cites"]) - set(got["cards"]))
        if unresolved:
            fail(f"{scope}: cites {unresolved} which are not in the evidence surface")
        if set(got["cites"]) != want_cites:
            fail(f"{scope}: citations {sorted(set(got['cites']))} != expected {sorted(want_cites)}")
        else:
            ok(f"{scope}: grounded answer, citations {sorted(want_cites)} all resolve")

    # The web answer must carry its own limit in the body, not only in a badge.
    page.evaluate("() => window.B67DemoApp.applyState({state: 'web'})")
    page.wait_for_timeout(250)
    web_text = page.evaluate("""() => document.getElementById('conversation').textContent""")
    for phrase in ("2차자료", "참고자료"):
        if phrase not in web_text:
            fail(f"web answer body does not carry the secondary-source limit ({phrase!r} missing)")
    if "단독 사용하지 마십시오" not in web_text:
        fail("web answer does not warn against single-source legal reliance")
    else:
        ok("web answer states its secondary-source limit in the answer body")


def check_authority_ordering(page) -> None:
    """AUTHORITY_RANK must actually order the panel, not just be documented."""
    page.evaluate("() => window.B67DemoApp.applyState({state: 'unified'})")
    page.wait_for_timeout(300)
    order = page.evaluate(
        """() => Array.from(document.querySelectorAll('#evidenceList .ev'))
                  .map(e => e.dataset.authority)"""
    )
    rank = {"primary": 0, "party": 1, "internal": 2, "secondary": 3}
    ranks = [rank[a] for a in order]
    if ranks != sorted(ranks):
        fail(f"evidence panel is not in authority order: {order}")
    else:
        ok(f"evidence panel is ordered by authority: {order}")

    # Display order changes; identity does not.
    nums = page.evaluate(
        """() => Array.from(document.querySelectorAll('#evidenceList .ev-num'))
                  .map(n => n.textContent)"""
    )
    if sorted(nums) != ["[1]", "[2]", "[3]", "[4]", "[5]"]:
        fail(f"reordering changed the visible evidence identities: {nums}")
    else:
        ok("reordering is display-only; [1]..[5] identities are unchanged")


def check_disconnected_truth_all_scopes(page) -> None:
    """The Drive-disconnected fix must survive the new web state."""
    page.evaluate("() => window.B67DemoApp.applyState({state: 'disconnected'})")
    page.wait_for_timeout(300)
    for scope in ("drive", "unified", "web", "official"):
        page.evaluate(f"() => window.B67DemoApp.applyState({{state: '{scope}'}})")
        page.wait_for_timeout(250)
        got = page.evaluate(
            """() => {
                const s = window.B67DemoApp.store.get();
                return {
                    connected: s.driveConnected,
                    driveRecords: s.evidence.filter(e => e.source_type === 'drive').length,
                    cites: Array.from(document.querySelectorAll('#conversation .cite'))
                        .map(c => parseInt(c.dataset.cite, 10)),
                    cards: Array.from(document.querySelectorAll('#evidenceList .ev'))
                        .map(e => parseInt(e.dataset.evidenceN, 10)),
                };
            }"""
        )
        if got["driveRecords"] > 0:
            fail(f"disconnected + '{scope}' still serves {got['driveRecords']} Drive record(s)")
        stray = sorted(set(got["cites"]) - set(got["cards"]))
        if stray:
            fail(f"disconnected + '{scope}' cites {stray} absent from the panel")
    ok("no scope serves Drive evidence while Drive is disconnected")
    ok("no scope renders a citation absent from its evidence surface while disconnected")

    # Drive scope must be an explicit connection-required state, not a blank.
    page.evaluate("() => window.B67DemoApp.applyState({state: 'drive'})")
    page.wait_for_timeout(250)
    text = page.evaluate("""() => document.getElementById('conversation').textContent""")
    if "Drive 자료에 접근할 수 없습니다" not in text:
        fail("Drive scope while disconnected does not show the connection-required state")
    else:
        ok("Drive scope while disconnected shows the connection-required state")

if __name__ == "__main__":
    sys.exit(main())
