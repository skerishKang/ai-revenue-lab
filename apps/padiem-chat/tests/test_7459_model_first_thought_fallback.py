"""#7459 6-(1): 생각이 이미 스트리밍된 뒤 모델 단계에서 실패·빈 응답으로 끝나면 생각을 접고 다음 후보 모델로 1회 폴백한다."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request

import app.central_model_route_runtime as route_runtime
from app import orchestration_routes as routes
from app.b14_client import ChatRuntimeError, ChatStreamEvent
from app.central_model_final_dispatch_guard import FinalDispatchDenied
from app.model_policy import current_request_route_model, current_request_tier_id
from padiem_control_plane.product_tier_routes import (
    ProductCredentialMode,
    ProductRouteStatus,
    ProductTierRoute,
)


PRIMARY_MODEL = "google/primary-max-7459"
FALLBACK_MODEL = "openrouter/fallback-max-7459"


class _PlanStream:
    def __init__(self, items):
        self._items = list(items)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._items:
            raise StopAsyncIteration
        item = self._items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def aclose(self):
        self.closed = True


class _SequentialB14:
    def __init__(self, streams):
        self._streams = list(streams)
        self.calls = []

    def stream_text_auto(
        self,
        messages,
        *,
        skill=None,
        additional_system_context=None,
        tools=(),
        tool_choice=None,
    ):
        self.calls.append(
            {
                "tier": current_request_tier_id(),
                "route_model": current_request_route_model(),
                "tools": tuple(tools),
            }
        )
        return _PlanStream(self._streams.pop(0))


class _Store:
    def __init__(self):
        self.saved = []

    async def append_exchange(self, user_id, conversation_id, user_text, answer, **kwargs):
        self.saved.append((user_text, answer))
        return "chat_7459_saved"


def _make_request(payload, *, stream: bool, b14):
    headers = [(b"content-type", b"application/json")]
    if stream:
        headers.append((b"accept", b"application/x-ndjson"))
    req = Request({"type": "http", "method": "POST", "path": "/api/orchestration", "headers": headers})
    req.scope["app"] = SimpleNamespace(
        state=SimpleNamespace(
            orchestration_bridge=SimpleNamespace(ready=True),
            orchestration_stream_enabled=stream,
            model_first_enabled=True,
            history_store=_Store(),
            usage_gate_enforced=False,
            usage_gate=None,
            b14_client=b14,
            auto_grounding=None,
            central_model_policy_store="policy-store",
            b14_catalog_source="catalog-source",
            settings=SimpleNamespace(runtime_mode="b14"),
        )
    )
    req._body = json.dumps(payload).encode("utf-8")
    return req


def _run_request(req):
    async def _go():
        res = await routes.api_orchestration(req)
        if hasattr(res, "body_iterator"):
            body = b""
            async for chunk in res.body_iterator:
                body += chunk.encode() if isinstance(chunk, str) else chunk
            return SimpleNamespace(status_code=res.status_code, body=body, media_type=res.media_type)
        return res

    return asyncio.run(_go())


def _setup_tier_and_auth(monkeypatch, *, fallback_id=FALLBACK_MODEL):
    import app.chat_pc_drive as drive
    import app.pc_work_context as pc_ctx

    monkeypatch.setattr(routes, "_bridge", lambda r: SimpleNamespace(ready=True))
    monkeypatch.setattr(routes, "auth_ready", lambda r: True)
    monkeypatch.setattr(routes, "current_user_id", lambda r: "usr_" + "c" * 32)

    async def _no_denial(request, uid, tier):
        return None

    async def _no_pc_stream_ctx(request, *, uid, requested_device_id=None, user_text=None):
        return None

    async def _no_pc_text(request, *, owner_id):
        return None

    monkeypatch.setattr(routes, "selected_grade_denial", _no_denial)
    monkeypatch.setattr(drive, "resolve_chat_pc_stream_context", _no_pc_stream_ctx)
    monkeypatch.setattr(pc_ctx, "build_pc_work_context_text", _no_pc_text)

    monkeypatch.setattr(
        route_runtime,
        "effective_active_route_for",
        lambda label: ProductTierRoute(
            route_id="max.test.v1",
            status=ProductRouteStatus.EXECUTABLE,
            model_family="google",
            provider_id="google",
            model_id=PRIMARY_MODEL,
            upstream_model="gemini-test",
            credential_mode=ProductCredentialMode.PLATFORM_SECRET_BINDING,
            credential_binding="GOOGLE_KEY",
            evidence="test",
        ),
    )
    monkeypatch.setattr(
        route_runtime,
        "tier_fallback_rosters",
        lambda: {"max": (PRIMARY_MODEL, fallback_id)} if fallback_id else {"max": (PRIMARY_MODEL,)},
    )


def test_7459_ndjson_retries_next_candidate_once_when_stream_fails_after_thought(monkeypatch):
    _setup_tier_and_auth(monkeypatch)
    guarded_models = []

    async def _fake_guard(request, model_id, store, catalog):
        guarded_models.append(model_id)
        return None

    monkeypatch.setattr(routes, "create_guard_from_request", _fake_guard)

    b14 = _SequentialB14(
        [
            [
                ChatStreamEvent(delta_thought="1차 후보가 생각 중입니다."),
                ChatRuntimeError(502, "provider_server_error", "상류 오류"),
            ],
            [
                ChatStreamEvent(delta_thought="2차 후보가 확인했습니다."),
                ChatStreamEvent(delta_content="정상 답변입니다."),
                ChatStreamEvent(done=True),
            ],
        ]
    )
    req = _make_request(
        {"messages": [{"role": "user", "content": "지금 연결됨?"}], "tier": "max", "stream": 1},
        stream=True,
        b14=b14,
    )
    res = _run_request(req)
    frames = [json.loads(raw) for raw in res.body.splitlines() if raw.strip()]

    assert [f["type"] for f in frames] == [
        "meta",
        "thought",
        "thought_reset",
        "thought",
        "delta",
        "done",
    ]
    assert frames[1]["text"] == "1차 후보가 생각 중입니다."
    assert frames[3]["text"] == "2차 후보가 확인했습니다."
    assert frames[4]["text"] == "정상 답변입니다."
    assert [c["route_model"] for c in b14.calls] == [PRIMARY_MODEL, FALLBACK_MODEL]
    assert guarded_models == [PRIMARY_MODEL, FALLBACK_MODEL]
    assert req.app.state.history_store.saved == [("지금 연결됨?", "정상 답변입니다.")]


def test_7459_ndjson_and_json_retry_when_primary_ends_empty_after_thought(monkeypatch):
    _setup_tier_and_auth(monkeypatch)
    monkeypatch.setattr(routes, "create_guard_from_request", lambda *a, **kw: asyncio.sleep(0))

    # NDJSON: 생각만 내보내고 빈 답변으로 종료된 경우
    b14_stream = _SequentialB14(
        [
            [ChatStreamEvent(delta_thought="생각만 하고 종료"), ChatStreamEvent(done=True)],
            [ChatStreamEvent(delta_content="폴백 답변"), ChatStreamEvent(done=True)],
        ]
    )
    stream_res = _run_request(
        _make_request(
            {"messages": [{"role": "user", "content": "질문"}], "tier": "max", "stream": 1},
            stream=True,
            b14=b14_stream,
        )
    )
    frames = [json.loads(raw) for raw in stream_res.body.splitlines() if raw.strip()]
    assert [f["type"] for f in frames] == ["meta", "thought", "thought_reset", "delta", "done"]
    assert frames[3]["text"] == "폴백 답변"

    # JSON: 생각만 내보내고 실패한 경우
    b14_json = _SequentialB14(
        [
            [
                ChatStreamEvent(delta_thought="생각 중"),
                ChatRuntimeError(502, "upstream_execution_failed", "실패"),
            ],
            [ChatStreamEvent(delta_content="JSON 폴백 답변"), ChatStreamEvent(done=True)],
        ]
    )
    json_res = _run_request(
        _make_request(
            {"messages": [{"role": "user", "content": "질문"}], "tier": "max"},
            stream=False,
            b14=b14_json,
        )
    )
    assert json_res.status_code == 200
    assert json.loads(json_res.body)["answer"] == "JSON 폴백 답변"


def test_7459_never_retries_after_answer_delta_or_on_dispatch_guard_denial(monkeypatch):
    _setup_tier_and_auth(monkeypatch)
    monkeypatch.setattr(routes, "create_guard_from_request", lambda *a, **kw: asyncio.sleep(0))

    # 1) 이미 답변 본문(delta)이 일부 스트리밍된 뒤 실패하면 중복 출력을 막기 위해 재시도하지 않는다.
    b14_partial = _SequentialB14(
        [
            [
                ChatStreamEvent(delta_content="부분 답변"),
                ChatRuntimeError(502, "provider_server_error", "중단"),
            ],
            [ChatStreamEvent(delta_content="절대 호출되면 안 됨"), ChatStreamEvent(done=True)],
        ]
    )
    partial_res = _run_request(
        _make_request(
            {"messages": [{"role": "user", "content": "질문"}], "tier": "max", "stream": 1},
            stream=True,
            b14=b14_partial,
        )
    )
    partial_frames = [json.loads(raw) for raw in partial_res.body.splitlines() if raw.strip()]
    assert [f["type"] for f in partial_frames] == ["meta", "delta", "error"]
    assert len(b14_partial.calls) == 1

    # 2) FinalDispatchDenied는 권한/정책 거부이므로 폴백 후보로 우회하지 않는다.
    b14_denied = _SequentialB14(
        [
            [FinalDispatchDenied("policy_revision_changed")],
            [ChatStreamEvent(delta_content="절대 호출되면 안 됨"), ChatStreamEvent(done=True)],
        ]
    )
    denied_res = _run_request(
        _make_request(
            {"messages": [{"role": "user", "content": "질문"}], "tier": "max", "stream": 1},
            stream=True,
            b14=b14_denied,
        )
    )
    denied_frames = [json.loads(raw) for raw in denied_res.body.splitlines() if raw.strip()]
    assert [f["type"] for f in denied_frames] == ["meta", "error"]
    assert len(b14_denied.calls) == 1
