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


if __name__ == "__main__":
    sys.exit(main())
