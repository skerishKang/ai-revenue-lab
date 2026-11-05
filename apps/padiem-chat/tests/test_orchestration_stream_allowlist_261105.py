"""#6899 Chat 스트리밍 허용 목록: 전역 스위치·로그인 사용자·게스트 경계."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from app import orchestration_routes as routes
from app.orchestration_stream import (
    STREAM_USERS_ENV,
    orchestration_stream_users,
    stream_on_for,
)


USER = "user_allowlisted"
OTHER = "user_other"
GUEST = None


class _Bridge:
    ready = True

    def __init__(self):
        self.started = []
        self.streamed = []

    async def start(self, **kwargs):
        self.started.append(kwargs)
        return SimpleNamespace(
            answer="엔진 답변",
            orchestration={"events": [], "answer": "엔진 답변"},
            decision_status=None,
            conversation_id="chat_engine",
            user_text=kwargs.get("user_text"),
        )

    async def start_stream(self, **kwargs):
        self.streamed.append(kwargs)
        yield {
            "result": SimpleNamespace(
                answer="스트림 답변",
                orchestration={"events": [], "answer": "스트림 답변"},
                decision_status=None,
                conversation_id="chat_stream",
                user_text=kwargs.get("user_text"),
            )
        }


def _request(
    *,
    uid: str | None,
    stream_enabled: bool,
    stream_users=frozenset(),
    accept: str | None = None,
):
    headers = [(b"content-type", b"application/json")]
    if accept is not None:
        headers.append((b"accept", accept.encode("ascii")))
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/orchestration",
            "headers": headers,
        }
    )
    request.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=_Bridge(),
            orchestration_stream_enabled=stream_enabled,
            orchestration_stream_users=frozenset(stream_users),
            model_first_enabled=False,
            history_store=None,
            usage_gate_enforced=False,
            settings=SimpleNamespace(runtime_mode="mock"),
        )
    )
    request._body = json.dumps(
        {"messages": [{"role": "user", "content": "안녕"}], "tier": "free"}
    ).encode("utf-8")
    return request


def _install(monkeypatch, uid):
    import app.chat_pc_drive as drive

    monkeypatch.setattr(routes, "_bridge", lambda request: request.app.state.orchestration_bridge)
    monkeypatch.setattr(routes, "auth_ready", lambda request: uid is not None)
    monkeypatch.setattr(routes, "current_user_id", lambda request: uid)

    async def _no_pc_context(request, *, uid, requested_device_id=None, user_text=None):
        return None

    monkeypatch.setattr(drive, "resolve_chat_pc_stream_context", _no_pc_context)


def _call(request):
    async def run():
        response = await routes.api_orchestration(request)
        if hasattr(response, "body_iterator"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk.encode() if isinstance(chunk, str) else chunk
            return SimpleNamespace(
                status_code=response.status_code,
                body=body,
                media_type=response.media_type,
            )
        return response

    return asyncio.run(run())


def _ndjson_frames(body: bytes):
    return [json.loads(line) for line in body.decode("utf-8").splitlines() if line]


def test_allowlist_parsing_is_trimmed_deduplicated_and_never_fails():
    assert orchestration_stream_users({STREAM_USERS_ENV: " a , b ,,a , "}) == frozenset({"a", "b"})
    assert orchestration_stream_users({STREAM_USERS_ENV: ""}) == frozenset()
    assert orchestration_stream_users({STREAM_USERS_ENV: "   "}) == frozenset()
    assert orchestration_stream_users({}) == frozenset()
    assert orchestration_stream_users({STREAM_USERS_ENV: ["a", "b"]}) == frozenset()
    assert orchestration_stream_users({STREAM_USERS_ENV: 1}) == frozenset()
    assert orchestration_stream_users({STREAM_USERS_ENV: None}) == frozenset()


def test_stream_decision_matrix():
    users = frozenset({USER})
    assert stream_on_for(True, frozenset(), USER, False) is True
    assert stream_on_for(True, frozenset(), GUEST, True) is True
    assert stream_on_for(False, users, USER, False) is True
    assert stream_on_for(False, users, OTHER, False) is False
    assert stream_on_for(False, users, GUEST, True) is False
    assert stream_on_for(False, users, "  " + USER + "  ", False) is True
    assert stream_on_for(False, frozenset(), USER, False) is False


def test_install_defaults_to_an_empty_allowlist():
    from starlette.applications import Starlette

    app = Starlette()
    routes.install_orchestration_routes(app, None)
    assert app.state.orchestration_stream_enabled is False
    assert app.state.orchestration_stream_users == frozenset()

    routes.install_orchestration_routes(
        app, None, stream_enabled=True, stream_users=frozenset({USER}),
    )
    assert app.state.orchestration_stream_enabled is True
    assert app.state.orchestration_stream_users == frozenset({USER})


def test_both_entrypoints_read_the_allowlist_once_at_startup():
    root = Path(__file__).resolve().parents[1]
    host = (root / "app" / "local_cpython.py").read_text(encoding="utf-8")
    worker = (root / "worker.py").read_text(encoding="utf-8")
    assert "stream_users=orchestration_stream_users(os.environ)" in host
    assert "stream_users=orchestration_stream_users(self.env)" in worker


def test_switch_off_without_allowlist_keeps_the_existing_json_response(monkeypatch):
    _install(monkeypatch, USER)
    response = _call(
        _request(
            uid=USER,
            stream_enabled=False,
            stream_users=frozenset(),
            accept="application/x-ndjson",
        )
    )

    assert response.status_code == 200
    assert response.media_type == "application/json"
    body = json.loads(response.body)
    assert body["answer"] == "엔진 답변"
    assert "type" not in body


def test_allowlisted_logged_in_user_streams(monkeypatch):
    _install(monkeypatch, USER)
    response = _call(
        _request(
            uid=USER,
            stream_enabled=False,
            stream_users=frozenset({USER}),
            accept="application/x-ndjson",
        )
    )

    assert response.status_code == 200
    assert response.media_type == "application/x-ndjson"
    frames = _ndjson_frames(response.body)
    assert frames[0] == {"type": "meta", "stream": True}
    assert frames[-1]["type"] == "done"


def test_logged_in_user_outside_the_allowlist_keeps_the_existing_json_response(monkeypatch):
    _install(monkeypatch, OTHER)
    response = _call(
        _request(
            uid=OTHER,
            stream_enabled=False,
            stream_users=frozenset({USER}),
            accept="application/x-ndjson",
        )
    )

    assert response.status_code == 200
    assert response.media_type == "application/json"
    assert json.loads(response.body)["answer"] == "엔진 답변"


def test_guest_is_not_enabled_by_the_allowlist(monkeypatch):
    _install(monkeypatch, GUEST)
    request = _request(
        uid=GUEST,
        stream_enabled=False,
        stream_users=frozenset({USER}),
        accept="application/x-ndjson",
    )
    response = _call(request)

    assert response.status_code == 401
    assert getattr(request.app.state.orchestration_bridge, "streamed") == []


def test_global_switch_streams_every_logged_in_user(monkeypatch):
    _install(monkeypatch, OTHER)
    response = _call(
        _request(
            uid=OTHER,
            stream_enabled=True,
            stream_users=frozenset(),
            accept="application/x-ndjson",
        )
    )

    assert response.status_code == 200
    assert response.media_type == "application/x-ndjson"
    assert _ndjson_frames(response.body)[-1]["type"] == "done"
