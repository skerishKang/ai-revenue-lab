"""#6065 S5: the live readback must not be able to lie in the ways it usually does.

These tests drive `readback()` itself with synthetic responses — not its source text —
because a check that only greps the tool passes even when the guard is disabled.

  * an empty or truncated response must never read as a match: two empty bodies hash
    equal, so a failed fetch would otherwise report success;
  * Cloudflare injects one Web Analytics `<script>` into the served HTML (measured
    2026-10-29: 366-byte tag on its own line, so 367 bytes including that newline, and
    the *only* difference against the source), so the raw HTML hash can never equal the
    source hash. The injection is removed before hashing and its size is reported;
    because the source already ends that line with its own newline, a pattern that eats
    leading whitespace as well lands one byte short of the source forever.
  * the skip link is parked at left:-9999px until focused, so counting it as an
    overflow offender or a touch target would make a clean page fail the gate forever.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
import subprocess
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
TOOL = REPO_ROOT / "tools" / "council_s5_live_verify.py"

spec = importlib.util.spec_from_file_location("council_s5_live_verify", TOOL)
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

BEACON = b'<script type="module" src="https://static.cloudflareinsights.com/beacon.min.js/vabc123"></script>'


def inject_beacon(html: bytes) -> bytes:
    """Reproduce the live injection byte-for-byte: the tag lands on its own line,
    so what Cloudflare adds is the tag *plus the newline that follows it*."""
    return html.replace(b"</body>", BEACON + b"\n</body>", 1)


def serve(monkeypatch_map):
    """Replace the tool's fetch with canned responses, run readback(), restore."""
    real_get = tool.get
    tool.get = lambda url: monkeypatch_map[next(k for k in monkeypatch_map if k in url)]
    try:
        return tool.readback()
    finally:
        tool.get = real_get


def _source(name: str) -> bytes:
    path = {a: s for a, s in tool.ASSETS}[name]
    return subprocess.run(["git", "show", f"{tool.source_ref()}:{path}"], capture_output=True,
                          cwd=REPO_ROOT, check=True).stdout


def test_a_correct_deploy_reads_match_even_with_the_injected_beacon():
    html = _source("index.html")
    assert BEACON.decode() not in html.decode("utf-8", "ignore")
    served_html = inject_beacon(html)
    assert len(served_html) - len(html) == len(BEACON) + 1, "the injection owns its own newline"
    rows = serve({"index.html": (200, served_html),
                  "static/council-app.css": (200, _source("static/council-app.css")),
                  "static/council-app.js": (200, _source("static/council-app.js"))})
    by = {r["asset"]: r for r in rows}
    assert by["index.html"]["verdict"] == "MATCH", by["index.html"]
    assert by["index.html"]["cf_injected_bytes"] == len(BEACON) + 1, \
        "the injection size must be reported exactly, not hidden and not over-counted"
    assert all(r["verdict"] == "MATCH" for r in rows), rows


def test_the_beacon_pattern_never_eats_the_source_newline_before_the_tag():
    # the live source ends `</script>\n</body>`; if the pattern swallowed that leading
    # newline too, a byte-perfect deploy would report a 1-byte shortfall forever.
    assert tool.BEACON.pattern.startswith(rb"<script"), "no leading \\s* — the tag only"
    html = _source("index.html")
    assert tool.BEACON.sub(b"", inject_beacon(html)) == html
    # and a page with no injection at all is left completely untouched
    assert tool.BEACON.sub(b"", html) == html


def test_an_empty_response_can_never_report_match():
    rows = serve({"index.html": (200, b""),
                  "static/council-app.css": (200, b""),
                  "static/council-app.js": (200, b"")})
    assert all(r["verdict"] == "FAIL-EMPTY" for r in rows), rows
    # two empty bodies hash equal: the hash alone would have said MATCH
    assert hashlib.sha256(b"").hexdigest() == hashlib.sha256(b"").hexdigest()


def test_a_truncated_response_is_drift_not_a_near_match():
    css = _source("static/council-app.css")
    rows = serve({"index.html": (200, _source("index.html")),
                  "static/council-app.css": (200, css[: len(css) - 400]),
                  "static/council-app.js": (200, _source("static/council-app.js"))})
    by = {r["asset"]: r for r in rows}
    assert by["static/council-app.css"]["verdict"] == "DRIFT", by["static/council-app.css"]
    assert not by["static/council-app.css"]["length_equal"]


def test_an_older_stage_is_reported_as_drift_not_silence():
    # what the site actually served on 2026-10-29: the S0 CSS while main carries S0..S4
    old = _source("static/council-app.css").replace(b"clamp(14px, 1.8vw, 20px)", b"16px")
    rows = serve({"index.html": (200, _source("index.html")),
                  "static/council-app.css": (200, old),
                  "static/council-app.js": (200, _source("static/council-app.js"))})
    assert {r["verdict"] for r in rows} == {"MATCH", "DRIFT"}, rows


def test_the_parked_skip_link_is_excluded_in_both_detectors_and_nowhere_else():
    marks = tool.MARKERS
    guard = "if (el.classList.contains('council-skip') && parked(el)) continue;"
    assert marks.count(guard) == 2, "one guard in the overflow detector, one in the touch detector"
    assert marks.count("const parked = (el) =>") == 1
    assert re.search(r"b\.right <= 0 \|\| b\.left >= innerWidth", marks), \
        "parked must mean off-screen in either direction, not just left:-9999px"
    # the exclusion is conditional: a focused skip link must still be measured
    assert "council-skip:focus" not in marks, "the JS must not special-case the focused state away"


def test_the_attribution_names_a_commit_only_when_all_three_assets_match():
    ref = tool.source_ref()
    head = subprocess.run(["git", "rev-parse", ref], capture_output=True, cwd=REPO_ROOT,
                          text=True, check=True).stdout.strip()
    blobs = {served: tool.git_blob(_source(served)) for served, _ in tool.ASSETS}
    assert tool.serving_commit(blobs) == head, "the newest commit matching main's own bytes is main"
    stale = dict(blobs)
    stale["index.html"] = tool.git_blob(b"<html>an older page</html>\n")
    assert tool.serving_commit(stale) is None, \
        "one mismatching asset must yield UNATTRIBUTED, never the closest guess"


def test_the_marker_harness_waits_on_the_settled_panel_not_a_fixed_sleep():
    """Harness contract, checked as text because Playwright is not a CI dependency.

    The shipped markup keeps `#councilAuthPanel` hidden until `/api/auth/status`
    resolves, so a fixed sleep measures whatever state the sleep happened to land on:
    it reported a hidden sign-in panel at 390 on a page that was fine.
    """
    body = TOOL.read_text(encoding="utf-8").split("def browser(")[1]
    settle = re.search(r"hasAttribute\(\s*['\"]hidden['\"]\s*\)", body)
    assert settle, "must wait on the panel's own settled state, not on time"
    sleep = re.search(r"wait_for_timeout\((\d+)\)", body)
    assert sleep, "the harness lost its settle buffer"
    assert settle.start() < sleep.start(), "the wait must precede the sleep, or the sleep is the sync point"
    assert int(sleep.group(1)) <= 500, "a long sleep is the race we just removed"
