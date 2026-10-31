"""#5805: actual mobile Chat and Claw header scroll and motion contract."""
import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765").rstrip("/") + "/"

def measure(page):
    return page.evaluate("""() => {
      const bar = document.querySelector('.app-shell .main-panel > .topbar');
      const button = document.querySelector('#mobileMenu');
      const r = bar.getBoundingClientRect(), b = button.getBoundingClientRect();
      return {height: r.height, button: [b.x, b.y, b.width, b.height],
              collapsed: document.querySelector('.app-shell').hasAttribute('data-header-collapsed'),
              transition: getComputedStyle(bar).transitionDuration};
    }""")

def check(page, surface, reduced):
    page.goto(BASE, wait_until="load")
    page.wait_for_timeout(700)
    if surface == "claw":
        page.locator("#mobileMenu").click()
        page.locator("#clawNavButton").click()
        page.wait_for_selector('.app-shell[data-state="claw"]')
        page.wait_for_timeout(400)
    # Add inert content inside the actual visible primary scroll surface so the
    # short mock landing has enough overflow. No application state is changed.
    # The Claw landing uses the shared conversation scroll surface too.
    selector = ".conversation, .claw-workspace, .claw-inbox"
    scroller = page.locator(selector).locator("visible=true").first
    assert scroller.count(), f"{surface}: missing visible primary scroller"
    scroller.evaluate("""el => {
      const spacer = document.createElement('div');
      spacer.setAttribute('data-test-scroll-spacer', '');
      spacer.style.cssText = 'height: 2000px; flex: 0 0 2000px; pointer-events: none';
      el.appendChild(spacer);
      el.scrollTop = 0;
    }""")
    page.wait_for_timeout(400)
    top = measure(page)
    assert abs(top["height"] - 56) < 1 and not top["collapsed"], (surface, reduced, top)
    assert all(abs(a-b) < 1 for a,b in zip(top["button"][2:], [44,44])), top
    if reduced:
        assert all(float(x.strip().removesuffix("s")) == 0 for x in top["transition"].split(",")), top
    scroller.evaluate("el => el.scrollTop = 500")
    page.wait_for_function("document.querySelector('.app-shell').hasAttribute('data-header-collapsed')")
    page.wait_for_timeout(350)
    down = measure(page)
    assert abs(down["height"]) < 1 and down["collapsed"], (surface, reduced, down)
    assert all(abs(a-b) < 1 for a,b in zip(top["button"], down["button"])), (top, down)
    scroller.evaluate("el => el.scrollTop = 0")
    page.wait_for_function("!document.querySelector('.app-shell').hasAttribute('data-header-collapsed')")
    page.wait_for_timeout(350)
    restored = measure(page)
    assert abs(restored["height"] - 56) < 1 and not restored["collapsed"], (surface, reduced, restored)
    assert all(abs(a-b) < 1 for a,b in zip(top["button"], restored["button"])), (top, restored)
    print(f"5805 {surface} reduced_motion={reduced} PASS", flush=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    for reduced in (False, True):
        for surface in ("chat", "claw"):
            context = browser.new_context(viewport={"width": 390, "height": 844},
                                          reduced_motion="reduce" if reduced else "no-preference")
            page = context.new_page()
            check(page, surface, reduced)
            context.close()
    browser.close()
