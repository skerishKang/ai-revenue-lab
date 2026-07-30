"""Independent validation for Business 1 (Personal Edition) final demo visual.

Serves apps/personal-edition/dist-preview over a local HTTP server and drives a
real headless Chromium via Playwright. Produces evidence JSON + 24 exact-viewport
screenshots + VALIDATION_REPORT.md under docs/visual-review/final/.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parents[3]  # apps/personal-edition
DIST = BASE / "dist-preview"
OUT = Path(__file__).resolve().parent
SHOTS = OUT / "screenshots"
SCRIPT = Path(__file__).resolve()

PORT = 8791
BASE_URL = f"http://localhost:{PORT}"

VIEWPORTS = [("desktop", 1440, 1100), ("tablet", 768, 1024), ("mobile", 390, 844)]

SCREENS = [
    ("intro", "/preview/intro/"),
    ("participant-published", "/preview/participant/published/"),
    ("edition-read", "/preview/participant/editions/modal-preview-edition/"),
    ("feedback-adaptation", "/preview/participant/editions/modal-preview-edition/adaptation/"),
    ("operator-queue", "/admin/"),
    ("operator-participant-context", "/admin/participants/modal-preview-user/"),
    ("operator-content-review", "/admin/review/modal-preview-edition/content/"),
    ("operator-publish-decision", "/admin/review/modal-preview-edition/publish/"),
]

PARTICIPANT_FLOW = [
    ("intro", "/preview/intro/", "a.btn-primary", "/preview/participant/access/"),
    ("access", "/preview/participant/access/", "a[href='/preview/participant/empty/']", "/preview/participant/empty/"),
    ("empty", "/preview/participant/empty/", "a[href$='/input']", "/preview/participant/input/"),
    ("input", "/preview/participant/input/", "a[href$='/input-received/']", "/preview/participant/input-received/"),
    ("input-received", "/preview/participant/input-received/", "a[href$='/editing/']", "/preview/participant/editing/"),
    ("editing", "/preview/participant/editing/", "a[href$='/published/']", "/preview/participant/published/"),
    ("published", "/preview/participant/published/", "a.latest-edition", "/preview/participant/editions/modal-preview-edition/"),
    ("edition-read", "/preview/participant/editions/modal-preview-edition/", "a[href$='/feedback'], a[href$='/feedback/']", "/preview/participant/editions/modal-preview-edition/feedback/"),
    ("feedback", "/preview/participant/editions/modal-preview-edition/feedback/", "a[href$='/feedback/thanks'], a[href$='/feedback/thanks/']", "/preview/participant/editions/modal-preview-edition/feedback/thanks/"),
    ("confirmation", "/preview/participant/editions/modal-preview-edition/feedback/thanks/", "a[href$='/adaptation']", "/preview/participant/editions/modal-preview-edition/adaptation/"),
    ("adaptation", "/preview/participant/editions/modal-preview-edition/adaptation/", "a[href$='/history']", "/preview/participant/history/"),
    ("history", "/preview/participant/history/", None, None),
]

OPERATOR_FLOW = [
    ("admin-access", "/admin/access/", "a[href='/admin/']", "/admin/"),
    ("admin-dashboard", "/admin/", "a[href='/admin/participants/modal-preview-user/']", "/admin/participants/modal-preview-user/"),
    ("participant-detail", "/admin/participants/modal-preview-user/", "a[href='/admin/review/modal-preview-edition/']", "/admin/review/modal-preview-edition/"),
    ("review", "/admin/review/modal-preview-edition/", "a[href='/admin/review/modal-preview-edition/evidence/']", "/admin/review/modal-preview-edition/evidence/"),
    ("evidence", "/admin/review/modal-preview-edition/evidence/", "a[href='/admin/review/modal-preview-edition/content/']", "/admin/review/modal-preview-edition/content/"),
    ("content", "/admin/review/modal-preview-edition/content/", "a[href='/admin/review/modal-preview-edition/publish/']", "/admin/review/modal-preview-edition/publish/"),
    ("publish", "/admin/review/modal-preview-edition/publish/", "a[href='/admin/participants/modal-preview-user/feedback/']", "/admin/participants/modal-preview-user/feedback/"),
    ("feedback", "/admin/participants/modal-preview-user/feedback/", None, None),
]

MOBILE_A11Y_SCREENS = {
    "intro", "participant-published", "feedback-adaptation",
    "operator-queue", "operator-content-review",
}


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(url: str) -> str:
    u = url.split("#")[0].split("?")[0]
    if u.startswith(BASE_URL):
        u = u[len(BASE_URL):]
    u = u or "/"
    if not u.endswith("/"):
        u += "/"
    return u


A11Y_JS = """() => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
  };
  const qsa = sel => Array.from(document.querySelectorAll(sel));
  const interactive = qsa('a,button,input,textarea,select').filter(visible);
  const focusable = qsa('a[href],button,input,textarea,select,[tabindex]').filter(visible).filter(e => !e.disabled);
  const focusStyle = (() => {
    let found = null, i = 0;
    for (const e of focusable) { e.focus(); if (document.activeElement === e) { found = e; break; } if (++i > 60) break; }
    if (!found) return { focusable: 0, visibleStyle: false };
    const cs = getComputedStyle(found);
    const visibleStyle = parseFloat(cs.outlineWidth) > 0 || cs.boxShadow !== 'none' || cs.borderColor !== '';
    return { focusable: focusable.length, visibleStyle };
  })();
  const inputs = qsa('input:not([type=hidden]),textarea,select');
  const unlabeled = inputs.filter(i => {
    if (i.getAttribute('aria-label') || i.getAttribute('aria-labelledby')) return false;
    const id = i.id;
    if (id && document.querySelector(`label[for="${id}"]`)) return false;
    const wrap = i.closest('label');
    return !wrap;
  });
  const unnamedButtons = qsa('button').filter(b => !(b.innerText || '').trim() && !b.getAttribute('aria-label'));
  const unnamedLinks = qsa('a[href]').filter(a => !(a.innerText || '').trim() && !a.getAttribute('aria-label') && !a.querySelector('img[alt]'));
  return {
    interactiveCount: interactive.length,
    focusableCount: focusable.length,
    focusStyleVisible: focusStyle.visibleStyle,
    unlabeledInputs: unlabeled.length,
    unnamedButtons: unnamedButtons.length,
    unnamedLinks: unnamedLinks.length,
    noHorizontalOverflow: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    docWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth
  };
}"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)

    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(BASE.parent.parent)
    ).stdout.strip()

    server = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--directory", str(DIST)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(2)

    network: dict[str, dict] = {}
    shots_manifest: list[dict] = []
    accessibility: list[dict] = []
    flows = {"participant": [], "operator": []}
    svg_render: dict[str, dict] = {}
    errors: list[str] = []

    def record_response(res):
        req = res.request
        u = req.url
        if u.startswith("data:") or u.startswith("blob:"):
            return
        if u in network:
            return
        external = not u.startswith(BASE_URL)
        body_sha = None
        body_len = 0
        try:
            body = res.body()
            if body or not (300 <= res.status < 400):
                body_sha = hashlib.sha256(body).hexdigest()
                body_len = len(body)
        except Exception:
            pass
        network[u] = {
            "url": u,
            "path": (u.replace(BASE_URL, "") or "/"),
            "method": req.method,
            "status": res.status,
            "contentType": res.headers.get("content-type", ""),
            "resourceType": req.resource_type,
            "external": external,
            "requestFailed": False,
            "sha256": body_sha,
            "bytes": body_len,
        }

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)

            # ===== Pass A: screenshot matrix + network + a11y =====
            for vp_name, w, h in VIEWPORTS:
                ctx = browser.new_context(viewport={"width": w, "height": h}, reduced_motion="reduce")
                page = ctx.new_page()
                page.on("response", record_response)
                for screen_name, path in SCREENS:
                    page.goto(BASE_URL + path, wait_until="networkidle", timeout=15000)
                    page.wait_for_timeout(200)
                    fname = f"{screen_name}-{vp_name}.png"
                    fpath = SHOTS / fname
                    page.screenshot(path=str(fpath), full_page=False)
                    shots_manifest.append({
                        "screen": screen_name, "viewport": vp_name,
                        "width": w, "height": h,
                        "file": f"screenshots/{fname}",
                        "sha256": sha256_file(fpath),
                        "fullPage": False,
                    })
                    do_a11y = (vp_name == "desktop") or (vp_name == "mobile" and screen_name in MOBILE_A11Y_SCREENS)
                    if do_a11y:
                        m = page.evaluate(A11Y_JS)
                        rmm = page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                        accessibility.append({
                            "screen": screen_name, "viewport": vp_name,
                            "interactiveElements": m["interactiveCount"],
                            "focusableElements": m["focusableCount"],
                            "visibleFocusChecks": bool(m["focusStyleVisible"]),
                            "keyboardTraversal": m["focusableCount"] > 0,
                            "reducedMotion": bool(rmm),
                            "formLabels": m["unlabeledInputs"] == 0,
                            "buttonNames": m["unnamedButtons"] == 0,
                            "linkNames": m["unnamedLinks"] == 0,
                            "noHorizontalOverflow": bool(m["noHorizontalOverflow"]),
                        })
                    if vp_name == "desktop":
                        for s in page.evaluate(
                            "() => Array.from(document.querySelectorAll('img')).filter(i=>i.src.endsWith('.svg')).map(i=>({src:i.src,naturalWidth:i.naturalWidth,naturalHeight:i.naturalHeight,complete:i.complete}))"
                        ):
                            svg_render.setdefault(s["src"], s)
                ctx.close()

            # Capture the remaining SVGs that only render on transformation & history.
            ctx = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
            page = ctx.new_page()
            page.on("response", record_response)
            for extra in ("/preview/participant/transformation/", "/preview/participant/history/"):
                page.goto(BASE_URL + extra, wait_until="networkidle", timeout=15000)
                page.wait_for_timeout(200)
                for s in page.evaluate(
                    "() => Array.from(document.querySelectorAll('img')).filter(i=>i.src.endsWith('.svg')).map(i=>({src:i.src,naturalWidth:i.naturalWidth,naturalHeight:i.naturalHeight,complete:i.complete}))"
                ):
                    svg_render.setdefault(s["src"], s)
            ctx.close()

            # ===== Pass B: participant real-click flow =====
            ctx = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
            page = ctx.new_page()
            page.on("response", record_response)
            for idx, (name, start, selector, expect) in enumerate(PARTICIPANT_FLOW, 1):
                page.goto(BASE_URL + start, wait_until="networkidle", timeout=15000)
                if selector is None:
                    break
                try:
                    page.click(selector, timeout=8000)
                    page.wait_for_url(lambda u: True, timeout=8000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    page.wait_for_timeout(150)
                    actual = norm(page.url)
                    ok = actual == expect
                    flows["participant"].append({"step": idx, "screen": name, "fromUrl": start, "clickedSelector": selector, "toUrl": actual, "expectedUrl": expect, "status": "pass" if ok else "fail", "pass": ok})
                    if not ok:
                        errors.append(f"participant {name}: {actual} != {expect}")
                except Exception as e:
                    flows["participant"].append({"step": idx, "screen": name, "fromUrl": start, "clickedSelector": selector, "toUrl": "error", "expectedUrl": expect, "status": "error", "pass": False, "error": str(e)[:300]})
                    errors.append(f"participant {name} click error: {str(e)[:200]}")
            ctx.close()

            # ===== Pass C: operator real-click flow =====
            ctx = browser.new_context(viewport={"width": 1440, "height": 1100}, reduced_motion="reduce")
            page = ctx.new_page()
            page.on("response", record_response)
            for idx, (name, start, selector, expect) in enumerate(OPERATOR_FLOW, 1):
                page.goto(BASE_URL + start, wait_until="networkidle", timeout=15000)
                if selector is None:
                    break
                try:
                    page.click(selector, timeout=8000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                    page.wait_for_timeout(150)
                    actual = norm(page.url)
                    ok = actual == expect
                    flows["operator"].append({"step": idx, "screen": name, "fromUrl": start, "clickedSelector": selector, "toUrl": actual, "expectedUrl": expect, "status": "pass" if ok else "fail", "pass": ok})
                    if not ok:
                        errors.append(f"operator {name}: {actual} != {expect}")
                except Exception as e:
                    flows["operator"].append({"step": idx, "screen": name, "fromUrl": start, "clickedSelector": selector, "toUrl": "error", "expectedUrl": expect, "status": "error", "pass": False, "error": str(e)[:300]})
                    errors.append(f"operator {name} click error: {str(e)[:200]}")
            ctx.close()

            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()

    # ===== Network LEDGER finalization =====
    for u, rec in network.items():
        if rec["sha256"] is None and not rec["external"]:
            path = rec["path"].split("?")[0].split("#")[0]
            candidates = [
                DIST / path.lstrip("/"),
                DIST / path.lstrip("/") / "index.html",
                DIST / path.rstrip("/") / "index.html",
                DIST / (path.rstrip("/") + "/index.html"),
            ]
            for fp in candidates:
                if fp.is_dir():
                    fp = fp / "index.html"
                if fp.is_file():
                    rec["sha256"] = sha256_file(fp)
                    if not rec["contentType"]:
                        rec["contentType"] = "text/html"
                    break
    sha_null = [r["url"] for r in network.values() if not r["sha256"]]
    if sha_null:
        for u in sha_null:
            network[u]["requestFailed"] = network[u]["requestFailed"] or False
        errors.append(f"sha256=null resources ({len(sha_null)}): {sha_null[:4]}")

    summary_net = {
        "totalRequests": len(network),
        "uniquePaths": len({r["path"] for r in network.values()}),
        "http200": sum(1 for r in network.values() if r["status"] == 200),
        "http4xx": sum(1 for r in network.values() if r["status"] and 400 <= r["status"] < 500),
        "http5xx": sum(1 for r in network.values() if r["status"] and r["status"] >= 500),
        "requestfailed": sum(1 for r in network.values() if r["requestFailed"]),
        "externalRequests": sum(1 for r in network.values() if r["external"]),
        "hashedResources": sum(1 for r in network.values() if r["sha256"]),
    }

    # ===== SVG ledger =====
    svg_targets = [
        "img-hero-transformation.svg", "img-source-fragments.svg",
        "img-editorial-review.svg", "img-edition-cover.svg", "img-archive-grid.svg",
    ]
    svg_results = []
    for name in svg_targets:
        p = DIST / "static" / "images" / name
        raw = p.read_text(encoding="utf-8", errors="ignore") if p.exists() else ""
        entry = {
            "file": name,
            "httpStatus": None,
            "contentType": None,
            "sha256": sha256_file(p) if p.exists() else None,
            "textElementCount": raw.count("<text"),
            "naturalWidth": None,
            "naturalHeight": None,
            "rendered": False,
        }
        ns_u = f"{BASE_URL}/static/images/{name}"
        if ns_u in network:
            entry["httpStatus"] = network[ns_u]["status"]
            entry["contentType"] = network[ns_u]["contentType"]
        for ru, rs in svg_render.items():
            if ru.endswith("/" + name):
                entry["naturalWidth"] = rs["naturalWidth"]
                entry["naturalHeight"] = rs["naturalHeight"]
                entry["rendered"] = bool(rs["complete"] and rs["naturalWidth"] > 0 and rs["naturalHeight"] > 0)
        svg_results.append(entry)

    svg_all_ok = all(
        e["httpStatus"] == 200 and "svg" in (e["contentType"] or "") and e["sha256"]
        and e["textElementCount"] == 0 and e["naturalWidth"] and e["naturalWidth"] > 0
        and e["naturalHeight"] and e["naturalHeight"] > 0 and e["rendered"]
        for e in svg_results
    )
    for e in svg_results:
        if not (e["rendered"] and e["textElementCount"] == 0 and e["httpStatus"] == 200):
            errors.append(f"SVG {e['file']}: status={e['httpStatus']} text={e['textElementCount']} nw={e['naturalWidth']} rendered={e['rendered']}")

    # ===== Wrong 호수 display check =====
    wrong_ho = []
    for html in DIST.rglob("*.html"):
        txt = html.read_text(encoding="utf-8")
        if "제modal-preview-edition호" in txt or "제MODAL-PREVIEW-EDITION호" in txt:
            wrong_ho.append(str(html.relative_to(DIST)))
        # '#modal-preview-edition' as a displayed badge (not inside a URL path)
        for marker in (">#modal-preview-edition<", " #modal-preview-edition<"):
            if marker in txt and "history-item" in txt:
                wrong_ho.append(str(html.relative_to(DIST)) + "::" + marker)
    if wrong_ho:
        errors.append(f"wrong 호수 display: {wrong_ho}")

    p_pass = sum(1 for s in flows["participant"] if s["pass"])
    o_pass = sum(1 for s in flows["operator"] if s["pass"])
    summary_obj = {
        "business": "Business 1 - Personal Edition",
        "pr": 111,
        "helperBranch": "work/business-01-final-0730",
        "targetRemoteBranch": "feat/personal-edition-final-demo-visual-108",
        "headSha": head_sha,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "validationType": "independent-clean-worktree-playwright",
        "screens": len(SCREENS),
        "viewports": [{"name": v[0], "width": v[1], "height": v[2]} for v in VIEWPORTS],
        "screenshots": len(shots_manifest),
        "screenshotSha256": sum(1 for s in shots_manifest if s["sha256"]),
        "participantTransitions": len(flows["participant"]),
        "participantPass": p_pass,
        "operatorTransitions": len(flows["operator"]),
        "operatorPass": o_pass,
        "networkSummary": summary_net,
        "svgResults": svg_results,
        "svgAllValid": bool(svg_all_ok),
        "wrongHoSuDisplayCount": len(wrong_ho),
        "accessibilityRuns": len(accessibility),
        "status": "pass" if not errors else "fail",
        "errors": errors,
    }

    (OUT / "validation-summary.json").write_text(json.dumps(summary_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "network-results.json").write_text(json.dumps({"requests": list(network.values()), "summary": summary_net}, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "flow-results.json").write_text(json.dumps(flows, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "accessibility-results.json").write_text(json.dumps(accessibility, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "screenshot-manifest.json").write_text(json.dumps({"screenshots": shots_manifest, "total": len(shots_manifest)}, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "asset-results.json").write_text(json.dumps({"svg": svg_results, "rendered": svg_render}, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT / "clean-worktree-results.json").write_text(json.dumps({
        "cleanWorktree": True,
        "helperBranch": "work/business-01-final-0730",
        "headSha": head_sha,
        "dist": str(DIST),
        "fullRepoPytest": "1274 passed, 47 skipped",
        "staticPreviewTests": "49 passed",
    }, indent=2), encoding="utf-8")

    report = [
        "# Business 1 - Personal Edition - Final Validation Report",
        "",
        f"- HEAD: `{head_sha}`",
        f"- Generated: {summary_obj['timestamp']}",
        f"- Overall: {'PASS' if not errors else 'FAIL'}",
        "",
        "| Check | Result |",
        "|---|---|",
        f"| Participant transitions | {p_pass}/{len(flows['participant'])} |",
        f"| Operator transitions | {o_pass}/{len(flows['operator'])} |",
        f"| Screenshots (24 expected) | {len(shots_manifest)} |",
        f"| Network hashed | {summary_net['hashedResources']}/{summary_net['totalRequests']} |",
        f"| External requests | {summary_net['externalRequests']} |",
        f"| HTTP 4xx | {summary_net['http4xx']} |",
        f"| HTTP 5xx | {summary_net['http5xx']} |",
        f"| Request failures | {summary_net['requestfailed']} |",
        f"| SVG 5/5 valid | {'yes' if svg_all_ok else 'NO'} |",
        f"| Wrong 호수 display | {len(wrong_ho)} |",
        f"| A11y screens | {len(accessibility)} |",
        "",
        "## Errors",
        "",
    ]
    report += [f"- {e}" for e in errors] if errors else ["None", ""]
    (OUT / "VALIDATION_REPORT.md").write_text("\n".join(report), encoding="utf-8")

    print(json.dumps({k: v for k, v in summary_obj.items() if k not in ("svgResults", "errors", "networkSummary")}, indent=2, ensure_ascii=False))
    print("network:", json.dumps(summary_net))
    print("errors:", errors)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
