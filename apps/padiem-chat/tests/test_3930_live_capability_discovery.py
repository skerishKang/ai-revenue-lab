"""#3930 capability discovery: server-owned and zero-dispatch."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from pathlib import Path

from app.claw_general_routes import CLAW_LIVE_REQUEST_HEADER
from test_b54_claw_general_p01_routing import _client, _make_adapter

ROOT=Path(__file__).resolve().parents[1]
CAP="/api/claw/general/capabilities"
SUBJECT = "sub_" + "9" * 32



def _adapter(subject=True, stream=True):
    a=_make_adapter(subject_lane=subject)
    a._runner=SimpleNamespace(run_stream=(lambda *_args, **_kwargs: None)) if stream else None
    return a


@contextmanager
def _canary_client(adapter):
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new=AsyncMock(return_value=SimpleNamespace(auth_session=SimpleNamespace(subject=SimpleNamespace(subject_id=SUBJECT))))):
        with _client(adapter) as client:
            yield client

def test_capability_disabled_and_no_dispatch_or_quota():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        denied=client.get(CAP)
    assert denied.status_code==200
    assert denied.json()=={"live_events_available":False}
    assert "no-store" in denied.headers["cache-control"]
    adapter.execute.assert_not_awaited()


def test_capability_requires_signed_in_user_even_if_server_enabled():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        client.cookies.clear()
        denied=client.get(CAP)
    assert denied.json()=={"live_events_available":False}
    adapter.execute.assert_not_awaited()


def test_capability_requires_real_stream_runner():
    adapter=_adapter(stream=False)
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        denied=client.get(CAP)
    assert denied.json()=={"live_events_available":False}
    adapter.execute.assert_not_awaited()


def test_capability_follows_current_server_flag():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        allowed=client.get(CAP)
        client.app.state.claw_live_sse_enabled=False
        denied=client.get(CAP)
    assert allowed.json()=={"live_events_available":True}
    assert denied.json()=={"live_events_available":False}
    adapter.execute.assert_not_awaited()


def test_canonical_subject_requires_real_current_session():
    adapter=_adapter(subject=True)
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=True
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", new=AsyncMock(return_value=None)):
            denied=client.get(CAP)
        with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", new=AsyncMock(return_value=SimpleNamespace(auth_session=SimpleNamespace(subject=SimpleNamespace(subject_id=SUBJECT))))):
            allowed=client.get(CAP)
    assert denied.json()=={"live_events_available":False}
    assert allowed.json()=={"live_events_available":True}
    adapter.execute.assert_not_awaited()


def test_server_flag_never_treats_browser_header_as_capability_authority():
    adapter=_adapter()
    with _canary_client(adapter) as client:
        client.app.state.claw_live_sse_enabled=False
        resp=client.get(CAP, headers={CLAW_LIVE_REQUEST_HEADER:"p01-events-v1"})
    assert resp.json()=={"live_events_available":False}


def test_web_transport_no_longer_ships_the_direct_claw_general_probe():
    transport=(ROOT/"static"/"chat-transport.js").read_text(encoding="utf-8")
    # #7405: generic Claw turns use the shared streaming lane
    # (payload.product="claw"), so the static web app has no direct caller.
    assert "requestClawGeneral" not in transport
    assert CAP not in transport
    assert 'fetch("/api/claw/general"' not in transport
    # The server-owned route and readiness probe stay for native/React/front-worker clients.
    factory=(ROOT/"app"/"app_factory.py").read_text(encoding="utf-8")
    assert '"/api/claw/general"' in factory
    assert CAP in factory
    routes=(ROOT/"app"/"claw_general_routes.py").read_text(encoding="utf-8")
    assert "async def claw_general_capabilities(" in routes
