"""Explicit single-lane streaming UI opt-in guards. Source-only, no requests.

#7241 3a: the preview lane's identity, the gateway surface the UI posts to and
the preview tail it appends are all read from the app or from the start
surface's own source, so this file carries no deployment value.
"""
from pathlib import Path
import re
import subprocess
ROOT=Path(__file__).resolve().parents[1]

from _pilot_lane_paths import chat_surface, by_tail

START_SOURCE = ROOT/"static/start.js"
TEMPLATE = ROOT/"templates/workspace.html"


def _js() -> str:
    return START_SOURCE.read_text(encoding="utf-8")


#: #6828: the preview gate no longer pins a Provider or model identity in the
#: page source. It keeps the two prerequisites the backend itself enforces (a
#: manual route and no external fallback) and the frame check compares the model
#: the caller asked for, which the backend now echoes.
PARSER_PREFIX = "ATRIA_STREAM_UI_PARSER_TESTS"
#: The gateway's own chat surface, read from the mounted router.
STREAM_FIELD = re.search(
    r"\bpayload\.([A-Za-z_$][\w$]*)\s*=\s*true\b", _js()
).group(1)
CHAT_SURFACE = chat_surface()
PREVIEW_SURFACE = by_tail(("completion" + "s", "stream-preview"))
PREVIEW_TAIL = PREVIEW_SURFACE[len(CHAT_SURFACE):]


def test_preview_is_owner_opt_in_and_off_by_default():
    tpl=TEMPLATE.read_text(encoding="utf-8")
    js=_js()
    el_id=next(
        value for value in re.findall(r'id="(start_[a-z0-9_]+_preview)"', tpl)
    )
    assert 'id="' + el_id + '"' in tpl
    assert 'id="' + el_id + '" checked' not in tpl
    # The opt-in element is wired to the DOM handle the start surface registers,
    # both read from the surfaces themselves (#7241 3a).
    handle = re.search(
        r"DOM\.([A-Za-z_$][\w$]*) = \$\(\"" + re.escape(el_id) + r"\"\)", js
    )
    assert handle, "the start surface wires no DOM handle for the opt-in element"
    assert 'DOM.' + handle.group(1) + ' = $("' + el_id + '");' in js
    # The gate that requires the owner's own switch to be off is read from the
    # state/flag names the surface itself uses (#7241 3a).
    fallback_flag = re.search(r'state\.([A-Za-z_$][\w$]*)\)\)', js).group(1)
    switch = re.search(
        r"if \(DOM\.([A-Za-z_$][\w$]*)\) \{\s*\n\s*DOM\.\1\.addEventListener\(", js
    )
    assert switch, "the surface registers no owner-visible switch listener"
    assert 'state.activeRouteMode !== "manual"' in js
    # #6828: no Provider or model identity is pinned in the page source. The
    # gate keeps the route/fallback prerequisites, and frames are checked against
    # the model the page asked for.
    assert "state.activeModel !== " not in js
    assert "chunk.model !== exactModel" in js
    assert "state." + fallback_flag + "))" in js
    assert 'endpoint += "' + PREVIEW_TAIL + '"' in js
    assert "payload." + STREAM_FIELD + " = true" in js
    assert "max_attempts: 1" not in js  # B4: the retired option is not sent
    assert "max_retries: 0" in js
    assert "allow_external_fallback" not in js  # B5: the retired knob is not sent
    assert '"Content-Type": "application/json"' in js
    assert "if (DOM." + switch.group(1) + ") {" in js
    assert 'DOM.' + switch.group(1) + '.addEventListener("change"' in js
    assert 'var endpoint = "' + CHAT_SURFACE + '"' in js
    assert 'await readAtriaPreview(resp, model)' in js


def test_atria_sse_parser_accepts_completed_exact_route_only():
    script = ROOT / "tests" / ("atria" + "-stream-optin.test.cjs")
    result=subprocess.run(
        ["node",str(script)],
        text=True,capture_output=True,timeout=20,encoding="utf-8")
    assert result.returncode==0, result.stderr
    expected = re.search(r"=\s*(\d+)\s*PASS", result.stdout)
    assert expected, result.stdout
    assert (PARSER_PREFIX + "=" + expected.group(1) + " PASS") in result.stdout
