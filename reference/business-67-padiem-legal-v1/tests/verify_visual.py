"""verify_visual.py — geometry and contrast audit for the B67 review surface.

Layout bugs (clipped text, overlap, content trapped behind the fixed composer)
and contrast failures are measurable, so this checks them numerically rather
than by eye. It complements verify_browser.py, which checks behaviour.

Run:  python reference/business-67-padiem-legal-v1/tests/verify_visual.py
"""

from __future__ import annotations

import sys
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8899/"

failures: list[str] = []
notes: list[str] = []


def fail(m): failures.append(m); print(f"  FAIL  {m}")
def ok(m): print(f"  ok    {m}")
def note(m): notes.append(m); print(f"  note  {m}")


# ── Injected into the page: geometry probes ────────────────────────────────
GEOMETRY_JS = r"""
() => {
  const vis = (n) => {
    const cs = getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = n.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };

  // 1. Clipped text: the element's content is wider/taller than its box and it
  //    does not scroll.
  const clipped = [];
  const sel = 'p, span, strong, small, dt, dd, h1, h2, button, a, code, em';
  for (const n of document.querySelectorAll(sel)) {
    if (!vis(n)) continue;
    // .sr-only is clipped BY DESIGN (the visually-hidden utility), and the
    // brand / avatar marks carry an intentional overflow:hidden blur, so
    // their scrollWidth always exceeds clientWidth. Neither is a layout bug.
    if (n.closest('.sr-only, .brand-mark, .assistant-avatar')) continue;
    if (n.classList.contains('sr-only')) continue;
    const cs = getComputedStyle(n);
    // Only a scrollable box can actually hide its own text. An
    // overflow:hidden box that never scrolls clips by design.
    if (!/auto|scroll/.test(cs.overflowX) && !/auto|scroll/.test(cs.overflowY)) continue;
    const overflowsX = n.scrollWidth - n.clientWidth > 1;
    const overflowsY = n.scrollHeight - n.clientHeight > 1;
    if (!overflowsX && !overflowsY) continue;
    if (cs.textOverflow === 'ellipsis') continue;
    const t = (n.textContent || '').trim().slice(0, 30);
    if (!t) continue;
    clipped.push({ t, tag: n.tagName, cls: (n.className||'').toString().slice(0,40),
                   x: n.scrollWidth - n.clientWidth, y: n.scrollHeight - n.clientHeight });
  }

  // 2. Content hidden behind the fixed composer.
  const composer = document.querySelector('.composer-wrap');
  const cw = composer ? composer.getBoundingClientRect() : null;
  const buried = [];
  if (cw) {
    // An element momentarily behind a FIXED composer is only a bug if the
    // scroll container cannot bring it clear. Check the scroll range, not
    // the instantaneous rect.
    const conv = document.getElementById('conversation');
    const scrollable = conv.scrollHeight - conv.clientHeight;
    if (scrollable <= 1) {
      // Nothing scrolls, so nothing can be trapped. Check the last child sits
      // clear of the composer directly.
      const last = conv.lastElementChild;
      if (last) {
        const lr = last.getBoundingClientRect();
        if (lr.bottom > cw.top + 2) {
          buried.push({ t: 'last conversation item ends at ' + Math.round(lr.bottom) +
                             ', composer starts at ' + Math.round(cw.top),
                        cls: 'composer-overlap' });
        }
      }
    } else {
      // Scrolling: the padding reserve must at least cover the composer.
      const padBottom = parseFloat(getComputedStyle(conv).paddingBottom) || 0;
      if (padBottom + 4 < cw.height) {
        buried.push({ t: 'conversation padding-bottom ' + padBottom + 'px < composer ' + cw.height + 'px',
                      cls: 'scroll-clearance' });
      }
    }
    // A fixed region genuinely covering another fixed region IS a bug.
    const panel = document.getElementById('evidencePanel');
    if (panel && getComputedStyle(panel).display !== 'none') {
      const pr = panel.getBoundingClientRect();
      if (cw.left < pr.right - 2 && cw.right > pr.left + 2 && cw.top < pr.bottom) {
        buried.push({ t: 'fixed composer overlaps the evidence panel', cls: 'composer/panel' });
      }
    }
  }

  // 3. Column balance at desktop.
  const rect = (s) => { const e=document.querySelector(s); if(!e) return null;
                        const r=e.getBoundingClientRect(); return r.width>0?Math.round(r.width):0; };

  // 4. Elements escaping the viewport horizontally.
  const escaping = [];
  for (const n of document.querySelectorAll('#conversation *, #evidenceList *, .sidebar *')) {
    if (!vis(n)) continue;
    if (n.closest('.sidebar')) continue; // intentionally off-canvas when closed
    const r = n.getBoundingClientRect();
    if (r.right > window.innerWidth + 1) {
      escaping.push({ t:(n.textContent||'').trim().slice(0,25), cls:(n.className||'').toString().slice(0,40),
                      right: Math.round(r.right), vw: window.innerWidth });
    }
  }

  return {
    clipped: clipped.slice(0, 10),
    buried: buried.slice(0, 10),
    escaping: escaping.slice(0, 10),
    cols: { sidebar: rect('.sidebar'), conversation: rect('.conversation'),
            evidence: rect('.evidence-panel') },
    vw: window.innerWidth,
    vh: window.innerHeight,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
  };
}
"""

# WCAG relative-luminance contrast, composited over the real painted background.
CONTRAST_JS = r"""
() => {
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  // Proper source-over compositing: the result stays translucent unless a
  // layer is opaque. Forcing a:1 made a 7%-opacity tint look like an opaque
  // light surface, which produced wildly wrong contrast readings.
  const over = (fg, bg) => {
    const a = fg.a + bg.a * (1 - fg.a);
    if (a === 0) return { r: 0, g: 0, b: 0, a: 0 };
    return {
      r: (fg.r*fg.a + bg.r*bg.a*(1-fg.a)) / a,
      g: (fg.g*fg.a + bg.g*bg.a*(1-fg.a)) / a,
      b: (fg.b*fg.a + bg.b*bg.a*(1-fg.a)) / a,
      a: a,
    };
  };
  const lum = (c) => {
    const f = (v) => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
    return 0.2126*f(c.r) + 0.7152*f(c.g) + 0.0722*f(c.b);
  };
  const ratio = (a, b) => { const l1=lum(a), l2=lum(b);
    return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05); };

  const effBg = (n) => {
    let el = n, acc = null;
    while (el && el !== document.documentElement) {
      const cs = getComputedStyle(el);
      const c = parse(cs.backgroundColor);
      if (c && c.a > 0) {
        acc = acc ? over(acc, c) : c;
        if (acc.a >= 0.999) return acc;
      }
      el = el.parentElement;
    }
    const root = parse(getComputedStyle(document.body).backgroundColor) || {r:0,g:0,b:0,a:1};
    return acc ? over(acc, root) : root;
  };

  const results = [];
  const targets = [
    ['.assistant-content', 'answer body'],
    ['.ev-title', 'evidence title'],
    ['.ev-doc', 'evidence doc name'],
    ['.ev-meta dd', 'evidence meta value'],
    ['.ev-meta dt', 'evidence meta label'],
    ['.ev-quote', 'evidence quote'],
    ['.ev-empty-body', 'empty/fail-closed body'],
    ['.ev-empty-title', 'empty/fail-closed title'],
    ['.prov-row dd', 'provenance value'],
    ['.prov-row dt', 'provenance label'],
    ['.prov-locator', 'page locator'],
    ['.auth-badge', 'authority badge'],
    ['.src-chip', 'source chip'],
    ['.starter small', 'starter caption'],
    ['.scope-note', 'scope note'],
    ['.composer-note', 'composer note'],
    ['.sidebar-footer > span:not(.preview-dot)', 'sidebar footer'],
    ['.fmt-row', 'format matrix row'],
    ['.recent-section h2', 'sidebar section heading'],
    ['.corpus-doc-name', 'corpus doc name'],
    ['.ev-foot', 'evidence footnote'],
    ['.evidence-foot', 'evidence panel footnote'],
  ];
  for (const [sel, name] of targets) {
    const n = document.querySelector(sel);
    if (!n) continue;
    const cs = getComputedStyle(n);
    const fg = parse(cs.color);
    if (!fg) continue;
    const bg = effBg(n);
    const f = fg.a < 1 ? over(fg, bg) : fg;
    results.push({ name, sel, ratio: Math.round(ratio(f, bg) * 100) / 100,
                   size: parseFloat(cs.fontSize), weight: cs.fontWeight, color: cs.color });
  }
  return results;
}
"""


def audit(page, label: str, is_mobile: bool) -> None:
    g = page.evaluate(GEOMETRY_JS)

    if g["clipped"]:
        for c in g["clipped"]:
            fail(f"{label}: clipped text in {c['tag']}.{c['cls']} "
                 f"(+{c['x']}px x, +{c['y']}px y): {c['t']!r}")
    else:
        ok(f"{label}: no clipped text")

    if g["buried"]:
        for b in g["buried"]:
            fail(f"{label}: content hidden behind the fixed composer: {b['t']!r} (.{b['cls']})")
    else:
        ok(f"{label}: no content trapped behind the fixed composer")

    if g["escaping"]:
        for e in g["escaping"]:
            fail(f"{label}: element escapes the viewport (right={e['right']} vw={e['vw']}): {e['t']!r}")
    else:
        ok(f"{label}: nothing escapes the viewport")

    if g["scrollW"] > g["clientW"] + 1:
        fail(f"{label}: horizontal scroll {g['scrollW']} > {g['clientW']}")
    else:
        ok(f"{label}: no horizontal scroll")

    if is_mobile:
        if g["cols"]["evidence"]:
            fail(f"{label}: evidence panel still laid out at mobile width")
        else:
            ok(f"{label}: evidence panel removed (single column, not squeezed)")
        ok(f"{label}: conversation column is {g['cols']['conversation']}px of {g['vw']}px")
    else:
        c = g["cols"]
        if not (c["sidebar"] and c["conversation"] and c["evidence"]):
            fail(f"{label}: expected a 3-column desktop layout, got {c}")
        else:
            smallest = min(c["sidebar"], c["conversation"], c["evidence"])
            total = sum(c.values())
            if smallest < 200:
                fail(f"{label}: a column is starved: {c}")
            elif total > g["vw"] + 2:
                fail(f"{label}: columns total {total}px, wider than the {g['vw']}px viewport: {c}")
            else:
                ok(f"{label}: 3 balanced columns "
                   f"(sidebar {c['sidebar']} / conversation {c['conversation']} / evidence {c['evidence']})")

    for r in page.evaluate(CONTRAST_JS):
        large = r["size"] >= 24 or (r["size"] >= 18.66 and int(r["weight"]) >= 700)
        floor = 3.0 if large else 4.5
        if r["ratio"] < floor:
            fail(f"{label}: contrast {r['ratio']}:1 < {floor}:1 for {r['name']} "
                 f"({r['size']}px/{r['weight']}, {r['color']})")
        elif r["ratio"] < floor + 0.6:
            note(f"{label}: contrast {r['ratio']}:1 is only just above {floor}:1 for {r['name']}")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-proxy-server"])

        for name, (w, h) in {"desktop": (1440, 1000), "tablet": (768, 1024),
                              "mobile": (390, 844)}.items():
            print(f"\n[{name}] {w}x{h}")
            ctx = browser.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            page.goto(URL, wait_until="commit")
            page.wait_for_function(
                "() => document.getElementById('conversation').children.length > 0", timeout=15000)
            page.wait_for_timeout(400)
            audit(page, name, w <= 920)
            ctx.close()

        # Fail-closed tone check — the most important screen in the product.
        print("\n[fail-closed tone]")
        ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = ctx.new_page()
        page.goto(URL, wait_until="commit")
        page.wait_for_function(
            "() => document.getElementById('conversation').children.length > 0", timeout=15000)
        page.click('#stateChips .claw-chip[data-value="fail-closed"]')
        page.wait_for_timeout(400)

        tone = page.evaluate(
            """() => {
                const card = document.querySelector('#conversation .ev-empty');
                if (!card) return null;
                const cs = getComputedStyle(card);
                const body = card.querySelector('.ev-empty-body');
                return {
                    border: cs.borderColor, borderStyle: cs.borderStyle,
                    bg: cs.backgroundColor,
                    bodyColor: body ? getComputedStyle(body).color : null,
                    title: (card.querySelector('.ev-empty-title')||{}).textContent,
                    actions: Array.from(card.querySelectorAll('.ev-action')).map(b => b.textContent.trim()),
                };
            }"""
        )
        if tone is None:
            fail("fail-closed: no fail-closed card rendered")
        else:
            # Calm, not alarming: must NOT use the danger palette.
            if "255, 157, 157" in tone["border"] or "220, 62, 62" in tone["border"]:
                fail(f"fail-closed renders with an alarm/danger border: {tone['border']}")
            else:
                ok(f"fail-closed uses a calm border, not an alarm colour ({tone['border']})")
            if tone["actions"] != ["검색 범위 바꾸기", "내 Drive 확인"]:
                fail(f"fail-closed actions unexpected: {tone['actions']}")
            else:
                ok(f"fail-closed offers both recovery actions: {tone['actions']}")
        ctx.close()
        browser.close()

    print("\n" + "=" * 60)
    for n in notes:
        print("  note  " + n)
    if failures:
        print(f"\nFAILED — {len(failures)} issue(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL VISUAL/GEOMETRY/CONTRAST CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
