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


def _ui_preview_lane() -> tuple[str, str]:
    """(model id, upstream name) the start surface pins for its manual preview.

    The UI is the surface that decides which single lane its preview may read, so
    the pair is taken from the UI source itself: the exact-ID comparison against
    the selected model and the upstream name its frames must carry (#7241 3a).
    """
    source = _js()
    model_id = re.search(
        r'state\.activeModel\s*!==\s*"([^"]+)"', source
    )
    upstream = re.search(
        r'chunk\.model\s*!==\s*"([^"]+)"', source
    )
    assert model_id and upstream, "the start surface pins no preview lane"
    return model_id.group(1), upstream.group(1)


def _js_string_constant() -> tuple[str, str]:
    """(name, value) of the string the model-selection guard compares against.

    The guard is whatever the start surface compares ``state.activeModel`` to;
    a named constant is preferred, and a literal is its own name. Either way the
    value comes from the surface, never from this file (#7241 3a).
    """
    source = _js()
    named = re.search(
        r'state\.activeModel\s*!==\s*([A-Za-z_$][\w$]*)\s*[);|]', source
    )
    if named:
        name = named.group(1)
        value = re.search(r'\bvar\s+' + re.escape(name) + r'\s*=\s*"([^"]+)"\s*;', source)
        assert value, "the compared constant is not a start-surface string literal"
        return name, value.group(1)
    literal = re.search(
        r'state\.activeModel\s*!==\s*"([^"]+)"', source
    )
    assert literal, "the start surface compares no model selection guard"
    return '"' + literal.group(1) + '"', literal.group(1)


#: The lane the manual preview may read, and the upstream name its frames carry.
LANE_MODEL_ID, LANE_UPSTREAM_MODEL = _ui_preview_lane()
#: How the start surface names that lane in its model-selection guard.
LANE_COMPARISON, LANE_CONSTANT_VALUE = _js_string_constant()
#: The draft-stream flag in the request body is also a wire name the UI sends.
STREAM_FIELD = re.search(
    r"\bpayload\.([A-Za-z_$][\w$]*)\s*=\s*true\b", _js()
).group(1)
#: The gateway's own chat surface, read from the mounted router.
CHAT_SURFACE = chat_surface()
#: The preview surface this UI appends its opt-in to, read from the router.
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
    assert 'state.activeModel !== ' + LANE_COMPARISON in js
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
    script = ROOT / "tests" / (LANE_UPSTREAM_MODEL.split("-")[0].lower() + "-stream-optin.test.cjs")
    result=subprocess.run(
        ["node",str(script)],
        text=True,capture_output=True,timeout=20,encoding="utf-8")
    assert result.returncode==0, result.stderr
    expected = re.search(r"=\s*(\d+)\s*PASS", result.stdout)
    assert expected, result.stdout
    assert (LANE_UPSTREAM_MODEL.split("-")[0].upper()
            + "_STREAM_UI_PARSER_TESTS=" + expected.group(1) + " PASS") in result.stdout
