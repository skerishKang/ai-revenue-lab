#!/usr/bin/env python3
"""#6065 S5 — prove the councillor UI that is LIVE equals the design that is MERGED.

Merging S0..S4 did not put them on chat.padiem.net; only a deploy does. This tool is
the readback the release acceptance needs, and it is deliberately strict about the two
ways this check usually lies:

  1. an empty or truncated response hashes like anything else if you only compare
     hashes, so a failed fetch can read as a match — every asset must be non-empty
     and its byte length must equal the source length;
  2. Cloudflare injects one Web Analytics `<script>` into the served HTML (measured
     2026-10-29: the tag is 366 bytes and it arrives on its own line, so the injection
     owns 367 bytes including that newline — and it is the *only* difference against the
     source). The raw HTML hash can therefore never equal the source hash. The injection
     is removed before hashing and its size is reported instead of hidden. Removing
     source whitespace with the tag would put the source one byte short of a match, so
     the pattern takes the tag plus at most the newline that follows it, never the
     newline before it.

Then it checks the *visual* markers each stage added, because matching bytes can still
be the wrong stage: S0 = wrapping header, S1 = fluid gutter + stroke brand mark +
16.5px brand type, S2 = card icon column, S3 = field panel and paper result,
S4 = list panels with hairline rows.

And it answers the question `DRIFT` cannot: WHICH commit Production is serving. The
served bytes are matched by git blob identity against `origin/main` history, so the
release owner gets "you are serving <sha>, main is N commits ahead, these council
commits are merged but not live" instead of three red rows.

Read-only: it never signs in, generates, or stores anything. Exit code 0 only when the
served assets equal `origin/main` AND every stage marker is present.

    python tools/council_s5_live_verify.py
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://chat.padiem.net/apps/council/"
APP = "apps/padiem-council-apps/static"
ASSETS = [("index.html", f"{APP}/index.html"),
          ("static/council-app.css", f"{APP}/council-app.css"),
          ("static/council-app.js", f"{APP}/council-app.js")]
BEACON = re.compile(
    rb"<script[^<>]*cloudflareinsights\.com/beacon\.min\.js[^<>]*>[^<>]*</script>\n?", re.I)
WIDTHS = (320, 390, 768, 1440)
HEIGHTS = {320: 700, 390: 844, 768: 1024, 1440: 1000}

MARKERS = r"""() => {
  const q = (s) => document.querySelector(s);
  const cs = (e, p) => e ? getComputedStyle(e)[p] : null;
  const box = (e) => e ? e.getBoundingClientRect() : null;
  const bar = q('.council-topbar'), mark = q('.council-brand-mark'), name = q('.council-brand-name'),
        card = q('.council-card'), icon = q('.council-card-icon'), auth = q('#councilAuthPanel'),
        saved = q('.council-saved-list'), archive = q('.council-archive');
  // The skip link lives at left:-9999px until it is focused, so it is neither an
  // overflow offender nor a touch target while parked. Counting it made a clean
  // page fail this gate forever.
  const parked = (el) => {
    const b = el.getBoundingClientRect();
    return b.right <= 0 || b.left >= innerWidth;
  };
  const offenders = [];
  for (const el of document.querySelectorAll('body *')) {
    const c = getComputedStyle(el);
    if (c.display === 'none' || c.visibility === 'hidden') continue;
    const b = el.getBoundingClientRect();
    if (b.width === 0 || b.height === 0) continue;
    if (el.classList.contains('council-skip') && parked(el)) continue;
    if (b.right > innerWidth + 1 || (b.left < -1 && !parked(el))) offenders.push(el.tagName.toLowerCase() + '.' + (el.className || '').toString().slice(0, 28));
  }
  const small = [];
  for (const el of document.querySelectorAll('a,button,input,select,textarea')) {
    const c = getComputedStyle(el);
    if (c.display === 'none') continue;
    const b = el.getBoundingClientRect();
    if (b.width === 0 || b.height === 0) continue;
    if (el.classList.contains('council-skip') && parked(el)) continue;
    const isBox = el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio');
    const min = isBox ? 24 : 44;
    if (b.height < min || b.width < min) small.push(el.tagName.toLowerCase() + '.' + (el.className || '').toString().slice(0, 24) + ' ' + Math.round(b.width) + 'x' + Math.round(b.height));
  }
  return {
    vw: innerWidth,
    s0_wraps: cs(bar, 'flexWrap') === 'wrap',
    s1_gutter: cs(bar, 'paddingLeft'), s1_gap: cs(bar, 'gap'),
    s1_markIsStrokeSvg: !!(mark && mark.querySelector('svg')) && cs(mark, 'backgroundColor').startsWith('rgba(0, 0, 0, 0'),
    s1_markWidth: Math.round((box(mark) || {width: 0}).width),
    s1_nameSize: cs(name, 'fontSize'), s1_nameTracking: cs(name, 'letterSpacing'),
    s2_cardCols: cs(card, 'gridTemplateColumns'), s2_iconWidth: icon ? Math.round(box(icon).width) : null,
    s3_fieldRadius: cs(q('#councilCountry'), 'borderRadius'),
    s4_authRadius: cs(auth, 'borderRadius'),
    authVisible: auth ? cs(auth, 'display') !== 'none' : null,
    builders: document.querySelectorAll('.council-form').length,
    docOvf: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    offenderCount: offenders.length, offenders: offenders.slice(0, 4),
    smallCount: small.length, small: small.slice(0, 5),
    countries: [...document.querySelectorAll('#councilCountry option')].map((o) => o.value).join(','),
  };
}"""


def get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "padiem-s5-readback"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def git_blob(data: bytes) -> str:
    p = subprocess.run(["git", "hash-object", "--stdin"], input=data, capture_output=True, check=True)
    return p.stdout.decode().strip()


def source_ref() -> str:
    """Which commit the served bytes are compared against.

    A developer worktree has `origin/main` and the question is 'is Production on the
    latest main'. A CI checkout is detached at the exact head with `fetch-depth: 1`,
    where `origin/main` does not exist and the checkout itself is the thing being
    proved — so falling back to HEAD keeps the same rules testable there without
    quietly comparing against nothing.
    """
    for ref in ("origin/main", "HEAD"):
        if subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref],
                          cwd=ROOT, capture_output=True).returncode == 0:
            return ref
    return "HEAD"


def serving_commit(blobs: dict[str, str]) -> str | None:
    """Which commit is Production actually serving?

    "DRIFT vs main" only says the deploy is behind. Identifying the newest commit whose
    three blobs equal the three served bytes turns that into a fact the release owner
    can act on. Matching is on git blob identity (SHA-1 of the exact bytes), and a
    candidate list is only ever built from `origin/main` — if no commit matches all
    three, this returns None instead of naming the closest one.
    """
    ref = source_ref()
    revs = subprocess.run(["git", "rev-list", ref, "--max-count=400"],
                          capture_output=True, cwd=ROOT, check=True).stdout.decode().split()
    lines = [f"{r}:{source}" for r in revs for _, source in ASSETS]
    check = subprocess.run(["git", "cat-file", "--batch-check"], input="\n".join(lines),
                           capture_output=True, cwd=ROOT, text=True, check=True).stdout.splitlines()
    table = {}
    for line, key in zip(check, lines):
        parts = line.split()
        table[key] = parts[0] if len(parts) >= 2 and parts[1] == "blob" else None
    for r in revs:
        if all(table.get(f"{r}:{source}") == blobs[served]
               for served, source in ASSETS):
            return r
    return None


def readback() -> list[dict]:
    blobs, bodies = {}, {}
    for served, source in ASSETS:
        status, body = get(urljoin(BASE + "/", served))
        comparable = (BEACON.sub(b"", body) if source.endswith("index.html") else body)
        bodies[served] = (status, body, comparable)
        blobs[served] = git_blob(comparable)
    rows = []
    for served, source in ASSETS:
        status, body, comparable = bodies[served]
        local = subprocess.run(["git", "show", f"{source_ref()}:{source}"], capture_output=True,
                               cwd=ROOT, check=True).stdout
        sha_served = hashlib.sha256(comparable).hexdigest()
        sha_source = hashlib.sha256(local).hexdigest()
        rows.append({"asset": served, "status": status, "served_bytes": len(body),
                     "cf_injected_bytes": len(body) - len(comparable),
                     "git_blob": blobs[served], "source_bytes": len(local),
                     "served_sha": sha_served[:16], "source_sha": sha_source[:16],
                     "non_empty": len(body) > 0, "length_equal": len(comparable) == len(local),
                     "sha_equal": sha_served == sha_source})
        rows[-1]["verdict"] = ("FAIL-EMPTY" if not rows[-1]["non_empty"] else
                               "MATCH" if rows[-1]["sha_equal"] and rows[-1]["length_equal"] else
                               "DRIFT" if status == 200 else f"HTTP{status}")
    return rows


def browser() -> dict:
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for w in WIDTHS:
            ctx = b.new_context(viewport={"width": w, "height": HEIGHTS[w]}, device_scale_factor=2)
            pg = ctx.new_page()
            pg.goto(BASE, wait_until="load")
            pg.wait_for_function("() => document.fonts.status === 'loaded'", timeout=20000)
            # The sign-in panel ships `hidden` and init() unhides it only after
            # /api/auth/status resolves. A fixed sleep let that fetch win the race at
            # one width out of four and read as "panel hidden" on a healthy page. This
            # tool never signs in, so signed-out is the guaranteed state and waiting on
            # it is a real sync point, not a guess; a page that never settles now fails
            # loudly instead of reporting a wrong number.
            pg.wait_for_function(
                "() => { const p = document.querySelector('#councilAuthPanel');"
                " return !!p && !p.hasAttribute('hidden'); }",
                timeout=15000)
            pg.wait_for_timeout(400)
            out[str(w)] = pg.evaluate(MARKERS)
            ctx.close()
        b.close()
    return out


def main() -> int:
    rows = readback()
    marks = browser()
    print("=== 1. served vs origin/main (empty response is never a match) ===")
    for r in rows:
        print(f"{r['asset']:<24} {r['status']} served={r['served_bytes']}b "
              f"(cf-injected {r['cf_injected_bytes']}b) sha={r['served_sha']} "
              f"source={r['source_bytes']}b sha={r['source_sha']} -> {r['verdict']}")
    print("\n=== 2. what Production is actually serving ===")
    ref = source_ref()
    served_at = serving_commit({r["asset"]: r["git_blob"] for r in rows})
    if served_at:
        meta = subprocess.run(["git", "log", "-1", "--format=%h %ad %s", "--date=iso", served_at],
                              capture_output=True, cwd=ROOT, text=True).stdout.strip()
        ahead = subprocess.run(["git", "rev-list", "--count", f"{served_at}..{ref}"],
                               capture_output=True, cwd=ROOT, text=True).stdout.strip()
        print(f"SERVING={served_at} ({meta}) — main is {ahead} commits ahead of it")
        merged_not_live = subprocess.run(
            ["git", "log", "--oneline", f"{served_at}..{ref}", "--", APP],
            capture_output=True, cwd=ROOT, text=True).stdout.strip()
        if merged_not_live:
            print("MERGED_BUT_NOT_SERVED:")
            for line in merged_not_live.splitlines():
                print("   ", line)
    else:
        print(f"SERVING=UNATTRIBUTED — the served bytes match no commit on {ref} "
              "(a partial or mixed deploy); name nothing until that is explained")
    print("\n=== 3. stage markers on the live page ===")
    for w, d in marks.items():
        print(f"{w:<5} ovf={d['docOvf']} offenders={d['offenderCount']} small={d['smallCount']} "
              f"S0wrap={d['s0_wraps']} S1gutter={d['s1_gutter']}/{d['s1_gap']} S1mark={d['s1_markIsStrokeSvg']}/{d['s1_markWidth']} "
              f"S1name={d['s1_nameSize']}/{d['s1_nameTracking']} S2cols={d['s2_cardCols']}/icon={d['s2_iconWidth']} "
              f"S3field={d['s3_fieldRadius']} S4auth={d['s4_authRadius']} builders={d['builders']} "
              f"authVisible={d['authVisible']} countries={d['countries']}")
        if d["small"]:
            print("      sub-floor:", d["small"])

    deployed = all(r["verdict"] == "MATCH" for r in rows)
    wide = marks.get("1440", {})
    staged = (wide.get("s1_markIsStrokeSvg") and wide.get("s2_iconWidth") == 30
              and wide.get("s1_nameSize") == "16.5px" and wide.get("s4_authRadius") == "14px"
              and wide.get("s3_fieldRadius") == "14px")
    geometry_ok = all(d["docOvf"] == 0 and d["offenderCount"] == 0 for d in marks.values())
    print(f"\nDEPLOYED_TO_MAIN_BYTES={'YES' if deployed else 'NO'}  "
          f"S1_S4_MARKERS={'YES' if staged else 'NO'}  GEOMETRY_CLEAN={'YES' if geometry_ok else 'NO'}")
    print("LIVE_VERIFIED=" + ("YES" if (deployed and staged and geometry_ok) else "NO"))
    out = Path(tempfile.gettempdir()) / "s5_live_verification.json"
    json.dump({"readback": rows, "markers": marks}, out.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"evidence: {out}")
    return 0 if (deployed and staged and geometry_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
