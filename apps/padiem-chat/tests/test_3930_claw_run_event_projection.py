"""#3930 canonical P01 UI status projection: exact event vocabulary, no fake phases."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
MODULE = STATIC / "claw-run-event-projection.js"
APP = STATIC / "app.js"
INDEX = STATIC / "index.html"


def _probe(js: str) -> dict:
    source = MODULE.read_text(encoding="utf-8")
    program = (
        "global.window = globalThis;\n"
        + source
        + "\nconst P = globalThis.PadiemClawRunEventProjection;\n"
        + js
    )
    result = subprocess.run(
        ["node", "-e", program], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return json.loads(result.stdout.strip())


def test_source_loads_only_in_existing_chat_shell_before_app() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert html.count('<script src="./claw-run-event-projection.js"></script>') == 1
    assert html.index("claw-run-event-projection.js") < html.index('<script src="./app.js">')
    source = APP.read_text(encoding="utf-8")
    assert 'frame.event === "p01_event"' in source
    assert 'canonicalEventProjection.consume(envelope)' in source
    assert 'const canonicalEventProjection = clawGeneralRequest ?' in source


def test_actual_core_envelope_order_and_terminal_guard() -> None:
    result = _probe("""
const p=P.create();
const base={run_id:"run.1",trace_id:"trace.1",app_id:"claw",timestamp_iso:"2026-10-09T13:00:00Z",message:"SECRET_TOKEN",metadata:{password:"never-render"}};
const mk=(sequence,kind)=>({...base,event_id:"event."+sequence,sequence,kind});
console.log(JSON.stringify({
 one:p.consume(mk(1,"run_started")),
 two:p.consume(mk(2,"tool_started")),
 three:p.consume(mk(3,"tool_completed")),
 four:p.consume(mk(4,"run_completed")),
 after:p.consume(mk(5,"tool_started")),
 snap:p.snapshot(),
 ko:P.label("tool_started","ko"), en:P.label("tool_started","en"),
 unknown:P.label("memory_read","ko")
}));
""")
    assert [result[k]["accepted"] for k in ("one", "two", "three", "four")] == [True] * 4
    assert result["four"]["terminal"] is True
    assert result["after"]["reason"] == "already_terminal"
    assert result["snap"] == {"runId": "run.1", "traceId": "trace.1", "appId": "claw", "sequence": 4, "terminal": True}
    assert result["ko"] == "도구가 실행 중입니다"
    assert result["en"] == "Tool running"
    assert result["unknown"] is None
    assert "SECRET_TOKEN" not in json.dumps(result)
    assert "never-render" not in json.dumps(result)


def test_missing_start_replay_gap_and_foreign_run_are_rejected() -> None:
    result = _probe("""
const p=P.create();
const mk=(seq,kind,run="run.1")=>({event_id:"e."+seq,run_id:run,trace_id:"tr.1",app_id:"claw",kind,sequence:seq,timestamp_iso:"t"});
const early=p.consume(mk(2,"tool_started"));
const start=p.consume(mk(1,"run_started"));
const replay=p.consume(mk(1,"run_started"));
const gap=p.consume(mk(3,"tool_started"));
const foreign=p.consume(mk(2,"tool_started","run.other"));
const valid=p.consume(mk(2,"tool_started"));
console.log(JSON.stringify({early,start,replay,gap,foreign,valid,snap:p.snapshot()}));
""")
    assert result["early"]["reason"] == "missing_start"
    assert result["replay"]["reason"] == "replayed_or_stale"
    assert result["gap"]["reason"] == "sequence_gap"
    assert result["foreign"]["reason"] == "foreign_run"
    assert result["start"]["accepted"] and result["valid"]["accepted"]
    assert result["snap"]["sequence"] == 2


def test_no_server_event_never_generates_a_status() -> None:
    result = _probe("""
const p=P.create();
const empty=p.snapshot();
const invalid=p.consume({kind:"tool_started",sequence:1});
const after=p.snapshot();
console.log(JSON.stringify({empty,invalid,after,keys:Object.keys(P).sort()}));
""")
    assert result["empty"] == result["after"]
    assert result["after"]["sequence"] == 0
    assert result["invalid"]["accepted"] is False
    assert result["keys"] == ["create", "label"]
    source = MODULE.read_text(encoding="utf-8")
    for forbidden in ("fetch(", "setTimeout(", "setInterval(", "innerHTML", "localStorage", "sessionStorage", "indexedDB", "new WebSocket", "EventSource"):
        assert forbidden not in source
