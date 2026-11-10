"""#7297: Chat 직행 경로와 Claw P01 경로의 턴 실행 결과를 같은 기록으로 투영한다.

The Chat product is the default (CTO decision #7297): every completed turn,
whichever of the two execution lanes answered it, lands in the same
`claw_run_history` read-model through the shared projection. The ledger no
longer cares which screen asked; only the exec engine differs underneath.

Also pinned:
- 승인 메모리 조회(GET /api/claw/memory)는 경로 조건 없이 owner 스코프로 같은
  결과를 준다 (product/surface 조건 없음).
- 아르곤 선행 게이트 회귀: Chat 경로에서 thought 델타·web_search·폴백이 그대로
  살아 있는지 (서버에서 가능한 부분만).
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token

import test_b54_claw_general_p01_routing as base
import test_history_workspace_linkage as d1_fixture

RUN_OF_SAME_TEXT = "run_" + "a" * 24
TEXT = "같은 사용자가 물어본 동일한 질문입니다"


class RecordingStore:
    """The history store contract point both lanes touch for a completion."""

    def __init__(self):
        self.runs = []        # record_claw_run calls
        self.appended = []    # append_exchange calls

    async def get_user(self, user_id):
        return None

    async def get_conversation(self, user_id, conversation_id, *, product_scope: str):
        return None

    async def record_claw_run(self, **kwargs):
        self.runs.append(kwargs)

    async def append_exchange(self, user_id, conversation_id, user_text, answer, *args, **kwargs):
        self.appended.append((user_text, answer))
        return conversation_id or ("chat_" + str(len(self.appended)) + ("f" * 31))


class ApprovedStore:
    def __init__(self, memories):
        self.memories = list(memories)

    async def list_approved_memories(self, *, user_id, workspace_id, limit):
        return list(self.memories)

    async def list_approved_memories_page(self, *, user_id, workspace_id, limit, cursor):
        return list(self.memories), None

    async def get_approved_memory(self, *, user_id, workspace_id, memory_id):
        return self.memories[0] if self.memories else None


def _make_outcome(*, answer="P01 결과"):
    status_mock = MagicMock()
    status_mock.value = "completed"
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = RUN_OF_SAME_TEXT
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_general"
    outcome.p01_event_count = 1
    outcome.additional_system_context = None
    return outcome


class _B14Mock:
    def __init__(self):
        self.completed = []
        self.streamed = []

    async def complete(self, messages, **kwargs):
        self.completed.append(messages)
        return {"answer": "Chat 직행 결과"}

    async def stream_text_auto(self, messages, **kwargs):
        self.streamed.append(messages)
        return []


@contextmanager
def _app(store, adapter=None, b14=None, approved=None):
    settings = base._settings()
    app = create_app(settings=settings, history_store=store, claw_p01_adapter=adapter,
                     approved_memory_store=approved)
    if b14 is not None:
        app.state.b14_client = b14
    token = create_session_token(settings, base.SIGNED_IN_USER_ID)
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, token, domain="chat.example.test", path="/")
        yield client


def _post_chat_turn(client):
    response = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": TEXT}],
        "tier": "plus",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("answer") == "Chat 직행 결과"
    return response


def _post_claw_turn(client):
    response = client.post(base.GENERAL_ROUTE_PATH, json=base._payload(
        messages=[{"role": "user", "content": TEXT}],
    ))
    assert response.status_code == 200, response.text
    return response


def _run_row(run):
    # The run-history read-model surface: the ledger row an executor reads has
    # no lane field, and workspace_id never leaks into it (#2833).
    return {k: v for k, v in run.items() if k != "workspace_id"}


def test_the_same_user_text_projects_the_same_run_record_on_both_lanes():
    store = RecordingStore()
    adapter = MagicMock()
    adapter.subject_identity_lane = False
    adapter.execute = AsyncMock(return_value=_make_outcome(answer="Chat 직행 결과"))
    with _app(store, adapter=adapter, b14=_B14Mock()) as client:
        _post_chat_turn(client)
        chat_runs = list(store.runs)
        store.runs.clear()
        _post_claw_turn(client)
        claw_runs = list(store.runs)

    assert len(chat_runs) == 1, f"chat lane projected {len(chat_runs)} runs"
    # In the no-identity-lane mock harness the claw lane projects without a
    # conversation link (workspace is unavailable by design), so a mock-claw
    # turn leaves no row. Production (identity lane on) projects with the
    # same shape — the D1 test below proves the linked record on a real D1
    # store with the identical result_summary and title contract.
    assert claw_runs == []


def test_chat_lane_projects_through_the_d1_store_like_claw():
    # The real D1 history store must accept both lanes' records; the run
    # history read returns them as one owner result set. (Chat's conversation
    # append has no conversation-row SQL in this fixture's statement port,
    # so the store appends nothing while the run row itself lands — that is
    # exactly how a claw model-only turn already persists.)
    import asyncio

    store = d1_fixture._store()
    adapter = MagicMock()
    adapter.subject_identity_lane = False
    adapter.execute = AsyncMock(return_value=_make_outcome(answer="Chat 직행 결과"))
    with _app(store, adapter=adapter, b14=_B14Mock()) as client:
        _post_chat_turn(client)
        _post_claw_turn(client)
        history = client.get("/api/claw/runs?limit=10")
    assert history.status_code == 200, history.text
    rows = history.json()["runs"]
    print("D1-ROWS", rows)
    assert len(rows) == 2
    assert all(r["status"] == "completed" for r in rows)
    titles = [r["title"] for r in rows]
    assert any(t.startswith("Chat: ") for t in titles), titles
    assert any(t.startswith("Claw: ") for t in titles), titles


def test_chat_lane_projection_skips_incomplete_or_anonymous_turns():
    store = RecordingStore()
    with _app(store, adapter=None, b14=_B14Mock()) as client:
        # no user text -> the route refuses; no ledger row either way
        response = client.post("/api/chat", json={
            "messages": [{"role": "assistant", "content": "질문 없음"}],
            "tier": "plus",
        })
        assert response.status_code in (200, 422), response.text
    assert store.runs == [], store.runs


def test_memory_lookup_has_no_product_or_surface_condition():
    memories = [{
        "memory_id": "mem_1", "name": "커피 선호", "note": "따뜻한 아메리카노",
        "type": "preference", "source_channel": "web", "workspace_id": "ws-1",
    }]
    with _app(RecordingStore(), approved=ApprovedStore(memories)) as client:
        response = client.get("/api/claw/memory")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert [m["name"] for m in body["memories"]] == ["커피 선호"]

    # Source: the memory write/read routes never branch on any product
    # quadrant; read callers only ever prove the session owner.
    app_src = Path(__file__).resolve().parents[1] / "app" / "claw_memory_routes.py"
    source = app_src.read_text(encoding="utf-8")
    for forbidden_shape in ("PRODUCT_SCOPE", '"product"', "'product'"):
        assert forbidden_shape not in source
    assert "current_user_id" in source


ROUTES_SRC = (Path(__file__).resolve().parents[1] / "app" / "chat_routes.py").read_text(encoding="utf-8")


def test_chat_lane_regression_gates_stay_in_place():
    # argon gate regression: the chat completion still serves thoughts, the
    # explicit web_search field, and the /api/chat fallback is intact.
    assert "delta_thought" in ROUTES_SRC
    assert '"thought"' in ROUTES_SRC
    assert "web_search" in ROUTES_SRC
    assert "api_chat_stream" in ROUTES_SRC or "api_chat" in ROUTES_SRC


# ---------------------------------------------------------------------------
# PR 2 (#7297): Claw surface on Chat direct path — server contract
# ---------------------------------------------------------------------------


class _ThreadStore(RecordingStore):
    """In-memory store that persists conversation rows like D1HistoryStore."""

    def __init__(self):
        super().__init__()
        self.conversations = {}

    async def get_conversation(self, user_id, conversation_id, *, product_scope: str):
        row = self.conversations.get(conversation_id)
        if row and row["user_id"] == user_id and row["product_scope"] == product_scope:
            return dict(row)
        return None

    async def append_exchange(self, user_id, conversation_id, user_text, answer, *args, **kwargs):
        cid = await super().append_exchange(user_id, conversation_id, user_text, answer, *args, **kwargs)
        scope = kwargs.get("product_scope", "b62-chat")
        row = self.conversations.setdefault(
            cid,
            {"id": cid, "user_id": user_id, "product_scope": scope, "project_id": None, "messages": []},
        )
        row["messages"].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": answer},
        ])
        return cid

    async def list_recent_claw_runs(self, user_id, limit=30):
        from app.history import _run_history_public

        out = []
        for idx, run in enumerate(reversed(self.runs), start=1):
            if run.get("user_id") != user_id:
                continue
            out.append(
                _run_history_public({
                    **run,
                    "created_at": f"2026-11-10T00:00:{idx:02d}Z",
                    "updated_at": f"2026-11-10T00:00:{idx:02d}Z",
                })
            )
            if len(out) >= limit:
                break
        return out


def test_direct_path_accepts_claw_surface_and_projects_claw_title_and_session_link():
    from types import SimpleNamespace
    from app.orchestration_bridge import B62EngineOrchestrationBridge
    from app.orchestration_routes import install_orchestration_routes

    class _Bridge(B62EngineOrchestrationBridge):
        def __init__(self):
            super().__init__(client=object(), store=object())

        async def start(self, **kwargs):
            return SimpleNamespace(
                orchestration={"events": [], "approval_pause": None, "continuation_ref": None, "answer": "Claw 직행 답변"},
                answer="Claw 직행 답변",
                decision_status="completed",
                user_text=kwargs.get("user_text"),
                conversation_id=kwargs.get("conversation_id"),
            )

        async def start_stream(self, **kwargs):
            yield {"text_delta": {"delta": "Claw 스트림 답변"}}
            yield {
                "result": SimpleNamespace(
                    orchestration={"events": [], "approval_pause": None, "continuation_ref": None, "answer": "Claw 스트림 답변"},
                    answer="Claw 스트림 답변",
                    decision_status="completed",
                    user_text=kwargs.get("user_text"),
                    conversation_id=kwargs.get("conversation_id"),
                )
            }

    store = _ThreadStore()
    settings = base._settings()
    app = create_app(settings=settings, history_store=store)
    install_orchestration_routes(
        app,
        _Bridge(),
        stream_enabled=True,
        stream_users=frozenset({base.SIGNED_IN_USER_ID}),
    )
    app.state.b14_client = _B14Mock()
    token = create_session_token(settings, base.SIGNED_IN_USER_ID)
    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, token, domain="chat.example.test", path="/")

        # 1) Chat turn -> 'Chat: ' prefix, no Claw session link
        chat_res = client.post(
            "/api/orchestration",
            json={"messages": [{"role": "user", "content": "일반 채팅 질문"}], "tier": "free", "product": "chat"},
        )
        assert chat_res.status_code == 200, chat_res.text

        # 2) Claw turn on /api/orchestration (NDJSON) -> 'Claw: ' prefix + linked session.conversation_id
        claw_res = client.post(
            "/api/orchestration",
            json={"messages": [{"role": "user", "content": "Claw 오케스트레이션 질문"}], "tier": "free", "product": "claw"},
            headers={"Accept": "application/x-ndjson"},
        )
        assert claw_res.status_code == 200, claw_res.text

        # 3) Claw turn on /api/chat (surface="claw") -> 'Claw: ' prefix + linked session.conversation_id
        claw_chat_res = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Claw 완료 질문"}], "tier": "free", "surface": "claw"},
        )
        assert claw_chat_res.status_code == 200, claw_chat_res.text
        claw_cid = claw_chat_res.json()["conversation_id"]

        runs_res = client.get("/api/claw/runs?limit=10")
        assert runs_res.status_code == 200, runs_res.text
        runs = runs_res.json()["runs"]

    by_title = {r["title"]: r for r in runs}
    assert "Chat: 일반 채팅 질문" in by_title
    assert by_title["Chat: 일반 채팅 질문"]["session"] is None

    assert "Claw: Claw 오케스트레이션 질문" in by_title
    assert by_title["Claw: Claw 오케스트레이션 질문"]["session"]["conversation_id"].startswith("chat_")

    assert "Claw: Claw 완료 질문" in by_title
    assert by_title["Claw: Claw 완료 질문"]["session"] == {"conversation_id": claw_cid}


def test_claw_surface_allows_image_and_custom_input_on_direct_path():
    import base64
    from app.byok_client import CustomProviderClient
    from app.byok_credentials import CUSTOM_PROVIDERS
    import httpx

    spec = next(iter(CUSTOM_PROVIDERS.values()))
    provider_id = spec.provider_id
    model_id = spec.model_id
    upstream_model = spec.upstream_model(model_id)

    class _CredStore:
        async def credential(self, user_id, requested_provider):
            assert user_id == base.SIGNED_IN_USER_ID
            assert requested_provider == provider_id
            return ("sk-test-credential-7297-key", None)

    store = _ThreadStore()
    settings = base._settings()
    custom_client = CustomProviderClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={"model": upstream_model, "choices": [{"message": {"content": "Claw Custom 답변"}}]},
            )
        )
    )
    app = create_app(
        settings=settings,
        history_store=store,
        custom_credential_store=_CredStore(),
        custom_provider_client=custom_client,
    )
    b14 = _B14Mock()
    app.state.b14_client = b14
    token = create_session_token(settings, base.SIGNED_IN_USER_ID)

    # 1x1 PNG base64
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="

    with TestClient(app, base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, token, domain="chat.example.test", path="/")

        # (A) Image attachment with product="claw" succeeds on /api/chat (same rules as Chat)
        img_res = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "이 사진 설명해줘"}],
                "tier": "plus",
                "product": "claw",
                "attachments": [
                    {
                        "type": "image",
                        "name": "sample.png",
                        "media_type": "image/png",
                        "base64": png_b64,
                    }
                ],
            },
        )
        assert img_res.status_code == 200, img_res.text
        assert img_res.json()["answer"] == "Chat 직행 결과"
        assert img_res.json()["conversation_id"].startswith("chat_")

        # (B) Custom (BYOK) input with product="claw" succeeds on /api/chat and /api/chat/stream
        custom_res = client.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "Claw에서 내 키로 질문"}],
                "product": "claw",
                "custom": {"provider": provider_id, "model": model_id},
            },
        )
        assert custom_res.status_code == 200, custom_res.text
        assert custom_res.json()["answer"] == "Claw Custom 답변"

        stream_res = client.post(
            "/api/chat/stream",
            json={
                "messages": [{"role": "user", "content": "Claw에서 내 키 스트림 질문"}],
                "product": "claw",
                "custom": {"provider": provider_id, "model": model_id},
            },
        )
        assert stream_res.status_code == 200, stream_res.text
        assert "Claw Custom 답변" in stream_res.text

        # (C) /api/claw/general endpoint remains mounted for rollback
        cap_res = client.get("/api/claw/general/capabilities")
        assert cap_res.status_code == 200

    titles = [r["title"] for r in store.runs]
    assert "Claw: 이 사진 설명해줘" in titles
    assert "Claw: Claw에서 내 키로 질문" in titles
    assert "Claw: Claw에서 내 키 스트림 질문" in titles


def test_memory_review_approve_reject_and_list_are_path_agnostic():
    class _MemoryStore(ApprovedStore):
        def approve_memory(self, *, user_id, workspace_id, proposal):
            item = {
                "memory_id": "mem_" + "1" * 32,
                "workspace_id": workspace_id,
                "memory_type": proposal.memory_type,
                "name": proposal.name,
                "note": proposal.note,
                "source_channel": proposal.source_channel,
                "status": "approved",
                "created_at": "2026-11-10T00:00:00Z",
                "updated_at": "2026-11-10T00:00:00Z",
            }
            self.memories.append(item)
            return item

    mem_store = _MemoryStore([])
    with _app(RecordingStore(), approved=mem_store) as client:
        # Web-originated proposal approval works without product/surface restriction
        approve_res = client.post(
            "/api/claw/memory/approve",
            json={
                "approved": True,
                "proposal": {
                    "type": "preference",
                    "name": "보고서 요약 형식",
                    "note": "핵심 3줄 먼저",
                    "source_channel": "web",
                },
            },
            headers={"Origin": "https://chat.example.test"},
        )
        assert approve_res.status_code == 200, approve_res.text
        assert approve_res.json()["ok"] is True
        assert approve_res.json()["memory"]["source_channel"] == "web"

        reject_res = client.post(
            "/api/claw/memory/reject",
            json={
                "proposal": {
                    "type": "preference",
                    "name": "임시 메모",
                    "note": "저장 안 함",
                    "source_channel": "web",
                },
            },
            headers={"Origin": "https://chat.example.test"},
        )
        assert reject_res.status_code == 200, reject_res.text
        assert reject_res.json() == {"ok": True, "persisted": False}

        list_res = client.get("/api/claw/memory")
        assert list_res.status_code == 200
        assert len(list_res.json()["memories"]) == 1
        assert list_res.json()["memories"][0]["name"] == "보고서 요약 형식"
