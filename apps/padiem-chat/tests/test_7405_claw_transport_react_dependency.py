"""#7405: the web transport's Claw sender is not unused.

The static app no longer calls requestClawGeneral itself, but the React clone
imports static/chat-transport.js and calls it. Removing the function broke the
B62 React clone CI, so this contract keeps the cross-app dependency explicit.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
REACT_SRC = Path(__file__).resolve().parents[2] / "padiem-chat-react" / "src"


def test_static_app_has_no_caller_outside_the_shared_transport():
    for path in STATIC.rglob("*.js"):
        if path.name == "chat-transport.js":
            continue
        assert "requestClawGeneral" not in path.read_text(encoding="utf-8"), path


def test_static_transport_keeps_the_react_clone_claw_sender():
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    assert "async function requestClawGeneral(payload, signal)" in transport
    assert "    requestClawGeneral," in transport
    start = transport.index("async function requestClawGeneral(payload, signal)")
    end = transport.index("\n  async function requestStreaming(", start)
    claw = transport[start:end]
    assert 'fetch("/api/claw/general"' in claw
    assert 'fetch("/api/chat/stream"' not in claw


def test_react_clone_imports_and_calls_the_static_claw_sender():
    react_transport = (REACT_SRC / "lib" / "chat-transport.ts").read_text(encoding="utf-8")
    react_claw = (REACT_SRC / "api" / "clawApi.ts").read_text(encoding="utf-8")
    assert 'import "../../../../apps/padiem-chat/static/chat-transport.js";' in react_transport
    assert "requestClawGeneral(payload: unknown, signal?: AbortSignal): Promise<Response>;" in react_transport
    assert "chatTransport.requestClawGeneral(payload, request.signal)" in react_claw
