from __future__ import annotations

from app.config import Settings
from app.main import create_app


def test_streaming_route_is_separate_from_completed_chat_contract():
    app = create_app(Settings(runtime_mode="mock"))
    routes = {
        getattr(route, "path", None): route
        for route in app.routes
        if getattr(route, "path", None)
    }

    assert "/api/chat" in routes
    assert "/api/chat/stream" in routes
    assert routes["/api/chat"] is not routes["/api/chat/stream"]
    assert routes["/api/chat"].methods == {"POST"}
    assert routes["/api/chat/stream"].methods == {"POST"}
