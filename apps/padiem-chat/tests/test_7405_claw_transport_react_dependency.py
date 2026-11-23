"""#7405: the web transport's Claw sender is not unused.

The static app no longer calls requestClawGeneral itself, but the React clone
imports static/chat-transport.js and calls it. Removing the function broke the
B62 React clone CI, so this contract keeps the cross-app dependency explicit.
"""

# #8060: shipped reads live in _support; assertions stay here.
from _support.transport_source import app_js, pc_recovery_js, read, react_claw_ts, react_transport_ts, streaming_module_js, transport_js

from pathlib import Path

from _support import claw_route_identity_source as sheets

STATIC = Path(__file__).resolve().parents[1] / "static"
REACT_SRC = Path(__file__).resolve().parents[2] / "padiem-chat-react" / "src"


def test_static_app_has_no_caller_outside_the_shared_transport():
    for path in sheets.js_paths():
        if path.name == "chat-transport.js":
            continue
<<<<<<< HEAD
        assert "requestClawGeneral" not in sheets.source(path), path


def test_static_transport_keeps_the_react_clone_claw_sender():
    transport = sheets.sheet("chat-transport.js")
=======
        assert "requestClawGeneral" not in read(path), path


def test_static_transport_keeps_the_react_clone_claw_sender():
    transport = transport_js()
>>>>>>> origin/main
    assert "async function requestClawGeneral(payload, signal)" in transport
    assert "    requestClawGeneral," in transport
    start = transport.index("async function requestClawGeneral(payload, signal)")
    end = transport.index("\n  async function requestStreaming(", start)
    claw = transport[start:end]
    assert 'fetch("/api/claw/general"' in claw
    assert 'fetch("/api/chat/stream"' not in claw


def test_react_clone_imports_and_calls_the_static_claw_sender():
<<<<<<< HEAD
    react_transport = sheets.repo_source("padiem-chat-react/src/lib/chat-transport.ts")
    react_claw = sheets.repo_source("padiem-chat-react/src/api/clawApi.ts")
=======
    react_transport = react_transport_ts()
    react_claw = react_claw_ts()
>>>>>>> origin/main
    assert 'import "../../../../apps/padiem-chat/static/chat-transport.js";' in react_transport
    assert "requestClawGeneral(payload: unknown, signal?: AbortSignal): Promise<Response>;" in react_transport
    assert "chatTransport.requestClawGeneral(payload, request.signal)" in react_claw
