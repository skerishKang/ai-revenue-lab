"""#7297 PR 1 — Chat direct 경로 선행 동등성 게이트 시험.

제품 코드 변경 없이 지금 Chat direct 경로(`/api/orchestration`, `/api/chat/stream`,
`/api/chat`)에서 동작하는 그대로를 시험으로 고정한다:

1. `thought` 델타 중계:
   - `/api/orchestration` NDJSON 스트림(bridge 및 model-first)에서 `thought` 프레임이
     `delta`·`done`보다 먼저 전달되고 최종 저장 답변에는 섞이지 않는다.
   - `/api/chat/stream` SSE 스트림에서 `event: thought`가 `event: delta`·`event: done`보다
     먼저 전달되고 최종 저장 답변에는 섞이지 않는다.
2. `web_search` (`deep_research` · `explicit_search`):
   - `web_search: True` (`explicit_search`)가 `/api/orchestration`, `/api/chat/stream`,
     `/api/chat` 각각에서 그라운딩 검색 판단(`explicit_search=True`)으로 전달되고
     인용 근거(`evidence`)와 `tool.id == "web_search"` 표지를 반환한다.
   - `tool: "deep_research"` + `tool_input` 요청은 `/api/orchestration`에서 `409
     orchestration_not_applicable`로 폴백을 알리고, `/api/chat`에서 `deep_research`
     도구로 실행되어 근거와 함께 완료 응답을 반환한다.
3. `/api/chat` 폴백:
   - 첨부(`attachments`)나 명시 도구(`tool`)가 있는 요청은 `/api/orchestration`에서 `409`,
     `/api/chat/stream`에서 `422 streaming_unsupported`를 반환해 `/api/chat` JSON
     완료 경로로 폴백하며, `/api/chat`은 텍스트·문서 첨부·도구 요청을 모두 완료하고
     `conversations` 및 `claw_run_history`에 저장한다.
4. `Custom + 도구`:
   - `custom` 텍스트 단독 요청은 `/api/chat`·`/api/chat/stream`에서 직접 실행되고,
     `/api/orchestration`에서는 엔진 경유 비활성 시 `409 orchestration_not_applicable`로
     직행 경로 폴백을 알리며, 엔진 경유 활성 시 `user_credential_ref`와 함께 스트리밍된다.
   - `custom`과 명시 `tool`(`web_search`·`deep_research`) 또는 `attachments`의 결합은
     세 엔드포인트 모두에서 `422`(`PADIEM Custom은 현재 텍스트 대화만 지원합니다.`)로
     일관되게 거부된다.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.byok_client import CustomProviderClient
from app.byok_credentials import CUSTOM_PROVIDERS, D1CustomProviderCredentialStore
from app.config import Settings
from app.main import create_app
from app.orchestration_bridge import B62EngineOrchestrationBridge
from app.orchestration_routes import install_orchestration_routes

ORIGIN = "https://chat.example.test"
SESSION_SECRET = "parity-7297-session-secret-not-a-real-credential"
CUSTOM_KEY_SECRET = "parity-7297-custom-key-secret-not-a-real-credential"
CUSTOM_KEY = "sk-customer-owned-7297-key-AAAA1111"
OWNER = "usr_" + "a" * 32

_DEFAULT_CUSTOM_SPEC = next(iter(CUSTOM_PROVIDERS.values()))
CUSTOM_PROVIDER_SLOT = _DEFAULT_CUSTOM_SPEC.provider_id
CUSTOM_MODEL_SLOT = _DEFAULT_CUSTOM_SPEC.model_id
UPSTREAM_MODEL_SLOT = _DEFAULT_CUSTOM_SPEC.upstream_model(CUSTOM_MODEL_SLOT)


def _settings(*, runtime_mode: str = "mock", web_provider: str = "mock", byok_via_b14: bool = False) -> Settings:
    return Settings.from_values(
        runtime_mode=runtime_mode,
        b14_base_url="https://b14.example.test" if runtime_mode == "b14" else None,
        web_provider=web_provider,
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="7297-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        custom_key_secret=CUSTOM_KEY_SECRET,
        session_max_age_seconds=3600,
        byok_via_b14=byok_via_b14,
    )


def _build_app(
    cfg: Settings,
    *,
    history_store: Any,
    b14_client: Any = None,
    orchestration_bridge: B62EngineOrchestrationBridge | None = None,
    auto_grounding: Any = None,
    grounded_chat: Any = None,
    custom_credential_store: Any = None,
    custom_provider_client: Any = None,
    orchestration_stream_enabled: bool = False,
    orchestration_stream_users: frozenset[str] | None = None,
    model_first_enabled: bool = False,
) -> Any:
    app = create_app(
        cfg,
        history_store=history_store,
        custom_credential_store=custom_credential_store,
        custom_provider_client=custom_provider_client,
    )
    install_orchestration_routes(
        app,
        orchestration_bridge,
        stream_enabled=orchestration_stream_enabled,
        stream_users=orchestration_stream_users,
        model_first_enabled=model_first_enabled,
    )
    if b14_client is not None:
        app.state.b14_client = b14_client
    app.state.b14_catalog_source = None
    if auto_grounding is not None:
        app.state.auto_grounding = auto_grounding
    if grounded_chat is not None:
        app.state.grounded_chat = grounded_chat
    app.state.usage_gate_enforced = False
    return app


class _Statement:
    def __init__(self, conn: sqlite3.Connection, query: str) -> None:
        self.conn = conn
        self.query = query
        self.parameters: tuple[Any, ...] = ()

    def bind(self, *values: Any) -> _Statement:
        self.parameters = values
        return self

    async def run(self) -> None:
        self.conn.execute(self.query, self.parameters)
        self.conn.commit()

    async def first(self) -> dict[str, Any] | None:
        cursor = self.conn.execute(self.query, self.parameters)
        row = cursor.fetchone()
        self.conn.commit()
        return dict(row) if row else None

    async def all(self) -> list[dict[str, Any]]:
        cursor = self.conn.execute(self.query, self.parameters)
        rows = [dict(row) for row in cursor.fetchall()]
        self.conn.commit()
        return rows


class _SQLiteD1:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            f"CREATE TABLE users(id TEXT PRIMARY KEY); INSERT INTO users(id) VALUES('{OWNER}');"
        )
        migration = (
            Path(__file__).resolve().parents[1]
            / "migrations"
            / "053_chat_custom_provider_credentials.sql"
        )
        self.conn.executescript(migration.read_text(encoding="utf-8"))

    def prepare(self, query: str) -> _Statement:
        return _Statement(self.conn, query)


class _FakeCipher:
    def random_bytes(self, size: int) -> bytes:
        return b"x" * size

    async def encrypt(self, *, key: bytes, iv: bytes, plaintext: bytes, additional_data: bytes) -> bytes:
        tag = hashlib.sha256(key + iv + additional_data).digest()
        return tag + bytes(x ^ tag[i % len(tag)] for i, x in enumerate(plaintext))

    async def decrypt(self, *, key: bytes, iv: bytes, ciphertext: bytes, additional_data: bytes) -> bytes:
        tag = hashlib.sha256(key + iv + additional_data).digest()
        if ciphertext[:32] != tag:
            raise ValueError("AAD mismatch")
        return bytes(x ^ tag[i % len(tag)] for i, x in enumerate(ciphertext[32:]))


class _RecordingHistoryStore:
    def __init__(self) -> None:
        self.conversations: dict[str, dict[str, Any]] = {}
        self.runs: list[dict[str, Any]] = []
        self.staged_turns: dict[str, dict[str, Any]] = {}
        self.counter = 0

    async def get_user(self, user_id: str) -> Any:
        return {"id": user_id} if user_id == OWNER else None

    async def get_conversation(self, user_id: str, conversation_id: str, *, product_scope: str = "chat") -> dict[str, Any] | None:
        row = self.conversations.get(conversation_id)
        if not row or row["user_id"] != user_id:
            return None
        return dict(row)

    async def append_exchange(
        self,
        user_id: str,
        conversation_id: str | None,
        user_text: str,
        assistant_text: str,
        project_id: str | None = None,
        *,
        product_scope: str = "chat",
    ) -> str:
        if conversation_id is None:
            self.counter += 1
            conversation_id = "chat_" + f"{self.counter:032x}"
            self.conversations[conversation_id] = {
                "id": conversation_id,
                "user_id": user_id,
                "title": user_text[:80],
                "product_scope": product_scope,
                "project_id": project_id,
                "messages": [],
            }
        row = self.conversations[conversation_id]
        row["messages"].extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ])
        return conversation_id

    async def record_claw_run(self, **kwargs: Any) -> None:
        self.runs.append(dict(kwargs))

    async def begin_chat_stream_turn(
        self, *, user_id: str, run_id: str, workspace_id: str, user_text: str, conversation_id: str | None,
    ) -> str:
        if conversation_id is None:
            self.counter += 1
            conversation_id = "chat_" + f"{self.counter:032x}"
            self.conversations[conversation_id] = {
                "id": conversation_id,
                "user_id": user_id,
                "title": user_text[:80],
                "product_scope": "chat",
                "project_id": None,
                "messages": [{"role": "user", "content": user_text}],
            }
        self.staged_turns[run_id] = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "user_text": user_text,
            "workspace_id": workspace_id,
        }
        return conversation_id

    async def finish_chat_stream_turn(self, *, user_id: str, run_id: str, answer: str) -> str | None:
        staged = self.staged_turns.get(run_id)
        if not staged:
            return None
        cid = staged["conversation_id"]
        self.conversations[cid]["messages"].append({"role": "assistant", "content": answer})
        return cid

    async def update_claw_run_status(self, user_id: str, run_id: str, status: str) -> None:
        return None


class _RecordingOrchestrationBridge(B62EngineOrchestrationBridge):
    def __init__(self, *, thought: str = "단계별 생각", answer: str = "오케스트레이션 답변") -> None:
        super().__init__(client=object(), store=object())
        self.thought = thought
        self.answer = answer
        self.started_calls: list[dict[str, Any]] = []
        self.streamed_calls: list[dict[str, Any]] = []

    async def start(self, **kwargs: Any) -> Any:
        self.started_calls.append(dict(kwargs))
        return SimpleNamespace(
            orchestration={"events": [], "approval_pause": None, "continuation_ref": None, "answer": self.answer},
            answer=self.answer,
            decision_status="completed",
            user_text=kwargs.get("user_text"),
            conversation_id=kwargs.get("conversation_id") or ("chat_" + "1" * 32),
        )

    async def start_stream(self, **kwargs: Any):
        self.streamed_calls.append(dict(kwargs))
        if self.thought:
            yield {"thought_delta": {"delta": self.thought}}
        yield {"text_delta": {"delta": self.answer}}
        yield {
            "result": SimpleNamespace(
                orchestration={"events": [], "approval_pause": None, "continuation_ref": None, "answer": self.answer},
                answer=self.answer,
                decision_status="completed",
                user_text=kwargs.get("user_text"),
                conversation_id=kwargs.get("conversation_id") or ("chat_" + "2" * 32),
            )
        }


class _RecordingB14Client:
    def __init__(self, *, thought: str = "스트림 생각", answer: str = "직행 답변") -> None:
        self.thought = thought
        self.answer = answer
        self.complete_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        self.complete_calls.append({"messages": list(messages), **kwargs})
        return {"answer": self.answer}

    async def stream_text_auto(self, messages: list[dict[str, str]], **kwargs: Any):
        self.stream_calls.append({"messages": list(messages), **kwargs})
        if self.thought:
            yield SimpleNamespace(delta_thought=self.thought, delta_content=None, done=False, tool_call=None)
        yield SimpleNamespace(delta_thought=None, delta_content=self.answer, done=False, tool_call=None)
        yield SimpleNamespace(delta_thought=None, delta_content=None, done=True, tool_call=None)


class _RecordingAutoGrounding:
    def __init__(self, *, with_evidence: bool = True) -> None:
        self.with_evidence = with_evidence
        self.prepare_calls: list[dict[str, Any]] = []
        self.decide_calls: list[dict[str, Any]] = []

    def decide(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Any = None,
        util_scope: str | None = None,
        explicit_search: bool = False,
    ) -> Any:
        self.decide_calls.append({
            "messages": list(messages),
            "skill": getattr(skill, "id", None),
            "util_scope": util_scope,
            "explicit_search": explicit_search,
        })
        latest = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        return SimpleNamespace(
            requires_search=bool(explicit_search or self.with_evidence),
            query=latest[:80] if (explicit_search or self.with_evidence) else None,
            reason="explicit" if explicit_search else "auto",
        )

    async def prepare(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Any = None,
        additional_system_context: str | None = None,
        explicit_search: bool = False,
        util_scope: str | None = None,
    ) -> Any:
        self.prepare_calls.append({
            "messages": list(messages),
            "skill": getattr(skill, "id", None),
            "additional_system_context": additional_system_context,
            "explicit_search": explicit_search,
            "util_scope": util_scope,
        })
        if not (explicit_search or self.with_evidence):
            return SimpleNamespace(prepared=None, error=None)
        evidence = (
            SimpleNamespace(
                id="src-1",
                title="검색 출처 제목",
                url="https://example.com/source-1",
                snippet="검색 근거 본문 요약",
                retrieved_at="2026-11-10T00:00:00Z",
                provider="search-fixture",
                source_type="web",
            ),
        )
        prepared = SimpleNamespace(
            decision=SimpleNamespace(requires_search=True, query="검색어", reason="explicit"),
            context="[웹 검색 근거]\n검색 근거 본문 요약",
            evidence=evidence,
        )
        return SimpleNamespace(prepared=prepared, error=None)


class _RecordingGroundedChat:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        skill: Any,
        tool: Any,
        tool_input: str | None,
        additional_system_context: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({
            "messages": list(messages),
            "skill": getattr(skill, "id", None),
            "tool_id": getattr(tool, "id", None),
            "tool_input": tool_input,
            "additional_system_context": additional_system_context,
        })
        return {
            "answer": f"{tool.id} 완료 답변",
            "answer_status": "answered_with_evidence",
            "tool": {"id": tool.id, "title": tool.title},
            "evidence": [
                {
                    "id": "ev-1",
                    "title": "리서치 출처",
                    "url": "https://example.com/research",
                    "snippet": "리서치 요약",
                    "retrieved_at": "2026-11-10T00:00:00Z",
                    "provider": "search-fixture",
                    "source_type": "web",
                }
            ],
        }


def _parse_sse(raw_text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw_text.split("\n\n"):
        event_name = None
        data_obj = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event_name = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data_obj = json.loads(line[len("data: "):])
        if event_name is not None and data_obj is not None:
            events.append((event_name, data_obj))
    return events


def _parse_ndjson(raw_text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in raw_text.splitlines() if line.strip()]


async def _send(
    app: Any,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    settings_obj: Settings | None = None,
) -> httpx.Response:
    cfg = settings_obj or app.state.settings
    req_headers = {"Origin": ORIGIN}
    if headers:
        req_headers.update(headers)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
    ) as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(cfg, OWNER))
        return await client.request(method, path, json=json_body, headers=req_headers)


# ===========================================================================
# 1. Thought 델타 중계 게이트
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_thought_delta_relayed_on_orchestration_ndjson_and_chat_sse():
    store = _RecordingHistoryStore()
    bridge = _RecordingOrchestrationBridge(thought="오케스트레이션 추론 조각", answer="오케스트레이션 최종 답")
    b14 = _RecordingB14Client(thought="SSE 추론 조각", answer="SSE 최종 답")
    cfg = _settings()
    app = _build_app(
        cfg,
        history_store=store,
        b14_client=b14,
        orchestration_bridge=bridge,
        orchestration_stream_enabled=True,
        orchestration_stream_users=frozenset({OWNER}),
    )
    app.state.usage_gate_enforced = False

    # (A) /api/orchestration NDJSON 스트림: thought 프레임이 delta/done 전에 중계되고 저장 본문에는 섞이지 않음
    orch_resp = await _send(
        app,
        "POST",
        "/api/orchestration",
        json_body={"messages": [{"role": "user", "content": "추론 질문"}], "tier": "free"},
        headers={"Accept": "application/x-ndjson"},
    )
    assert orch_resp.status_code == 200, orch_resp.text
    assert "application/x-ndjson" in orch_resp.headers.get("content-type", "")
    frames = _parse_ndjson(orch_resp.text)
    assert [f["type"] for f in frames] == ["meta", "thought", "delta", "done"]
    assert frames[1] == {"type": "thought", "text": "오케스트레이션 추론 조각"}
    assert frames[2] == {"type": "delta", "text": "오케스트레이션 최종 답"}
    assert "오케스트레이션 추론 조각" not in json.dumps(frames[-1], ensure_ascii=False)

    # (B) /api/chat/stream SSE 폴백 스트림: event: thought가 event: delta 전에 중계됨
    sse_resp = await _send(
        app,
        "POST",
        "/api/chat/stream",
        json_body={"messages": [{"role": "user", "content": "폴백 추론 질문"}], "tier": "free"},
        headers={"Accept": "text/event-stream"},
    )
    assert sse_resp.status_code == 200, sse_resp.text
    events = _parse_sse(sse_resp.text)
    assert [name for name, _ in events] == ["meta", "thought", "delta", "done"]
    assert events[1][1] == {"text": "SSE 추론 조각"}
    assert events[2][1] == {"delta": "SSE 최종 답"}
    saved_cid = events[3][1]["conversation_id"]
    assert store.conversations[saved_cid]["messages"][-1]["content"] == "SSE 최종 답"


@pytest.mark.asyncio
async def test_gate_thought_delta_relayed_on_orchestration_model_first_ndjson():
    store = _RecordingHistoryStore()
    bridge = _RecordingOrchestrationBridge()
    b14 = _RecordingB14Client(thought="모델퍼스트 추론", answer="모델퍼스트 본문")
    cfg = _settings()
    app = _build_app(
        cfg,
        history_store=store,
        b14_client=b14,
        orchestration_bridge=bridge,
        orchestration_stream_enabled=True,
        orchestration_stream_users=frozenset({OWNER}),
        model_first_enabled=True,
    )
    app.state.usage_gate_enforced = False

    resp = await _send(
        app,
        "POST",
        "/api/orchestration",
        json_body={"messages": [{"role": "user", "content": "모델퍼스트 질문"}], "tier": "free"},
        headers={"Accept": "application/x-ndjson"},
    )
    assert resp.status_code == 200, resp.text
    frames = _parse_ndjson(resp.text)
    assert [f["type"] for f in frames] == ["meta", "thought", "delta", "done"]
    assert frames[1] == {"type": "thought", "text": "모델퍼스트 추론"}
    assert frames[2] == {"type": "delta", "text": "모델퍼스트 본문"}


# ===========================================================================
# 2. web_search (explicit_search · deep_research) 게이트
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_explicit_web_search_across_orchestration_stream_and_chat():
    store = _RecordingHistoryStore()
    bridge = _RecordingOrchestrationBridge(thought="", answer="검색 반영 답변")
    b14 = _RecordingB14Client(thought="", answer="스트림 검색 답변")
    grounding = _RecordingAutoGrounding(with_evidence=False)
    grounded_chat = _RecordingGroundedChat()
    cfg = _settings()
    app = _build_app(
        cfg,
        history_store=store,
        b14_client=b14,
        orchestration_bridge=bridge,
        auto_grounding=grounding,
        grounded_chat=grounded_chat,
        orchestration_stream_enabled=True,
        orchestration_stream_users=frozenset({OWNER}),
    )
    app.state.usage_gate_enforced = False

    # (A) /api/orchestration + web_search: True -> explicit_search=True 전달 + done에 근거 포함
    orch_resp = await _send(
        app,
        "POST",
        "/api/orchestration",
        json_body={
            "messages": [{"role": "user", "content": "오늘 발표된 정책 찾아줘"}],
            "tier": "free",
            "web_search": True,
        },
        headers={"Accept": "application/x-ndjson"},
    )
    assert orch_resp.status_code == 200, orch_resp.text
    assert grounding.prepare_calls[-1]["explicit_search"] is True
    done_frame = _parse_ndjson(orch_resp.text)[-1]
    assert done_frame["type"] == "done"
    assert done_frame["answer_status"] == "answered_with_evidence"
    assert done_frame["tool"] == {"id": "web_search", "title": "웹 검색"}
    assert done_frame["evidence"][0]["url"] == "https://example.com/source-1"

    # (B) /api/chat/stream + web_search: True -> explicit_search=True 전달 + SSE done에 근거 포함
    sse_resp = await _send(
        app,
        "POST",
        "/api/chat/stream",
        json_body={
            "messages": [{"role": "user", "content": "실시간 환율 검색해줘"}],
            "tier": "free",
            "web_search": True,
        },
        headers={"Accept": "text/event-stream"},
    )
    assert sse_resp.status_code == 200, sse_resp.text
    assert grounding.prepare_calls[-1]["explicit_search"] is True
    sse_done = dict(_parse_sse(sse_resp.text))["done"]
    assert sse_done["answer_status"] == "answered_with_evidence"
    assert sse_done["tool"] == {"id": "web_search", "title": "웹 검색"}
    assert sse_done["evidence"][0]["url"] == "https://example.com/source-1"

    # (C) /api/chat + web_search: True -> auto_grounding.decide(explicit_search=True) -> grounded_chat.complete
    chat_resp = await _send(
        app,
        "POST",
        "/api/chat",
        json_body={
            "messages": [{"role": "user", "content": "뉴스 검색 결과 알려줘"}],
            "tier": "free",
            "web_search": True,
        },
    )
    assert chat_resp.status_code == 200, chat_resp.text
    assert grounding.decide_calls[-1]["explicit_search"] is True
    assert grounded_chat.calls[-1]["tool_id"] == "web_search"
    chat_body = chat_resp.json()
    assert chat_body["answer"] == "web_search 완료 답변"
    assert chat_body["answer_status"] == "answered_with_evidence"
    assert chat_body["evidence"][0]["url"] == "https://example.com/research"


@pytest.mark.asyncio
async def test_gate_deep_research_falls_back_from_orchestration_to_api_chat():
    store = _RecordingHistoryStore()
    bridge = _RecordingOrchestrationBridge()
    b14 = _RecordingB14Client()
    grounded_chat = _RecordingGroundedChat()
    cfg = _settings(runtime_mode="b14", web_provider="mock")
    app = _build_app(
        cfg,
        history_store=store,
        b14_client=b14,
        orchestration_bridge=bridge,
        grounded_chat=grounded_chat,
    )
    app.state.usage_gate_enforced = False

    deep_payload = {
        "messages": [{"role": "user", "content": "반도체 공급망 심층 조사"}],
        "tier": "free",
        "tool": "deep_research",
        "tool_input": "반도체 공급망 동향",
    }

    # /api/orchestration은 tool 요청에 409 orchestration_not_applicable 반환
    orch_resp = await _send(app, "POST", "/api/orchestration", json_body=deep_payload, settings_obj=cfg)
    assert orch_resp.status_code == 409
    assert orch_resp.json()["error"]["code"] == "orchestration_not_applicable"

    # /api/chat/stream은 tool 요청에 422 streaming_unsupported 반환
    stream_resp = await _send(app, "POST", "/api/chat/stream", json_body=deep_payload, settings_obj=cfg)
    assert stream_resp.status_code == 422
    assert stream_resp.json()["error"]["code"] == "streaming_unsupported"

    # /api/chat은 deep_research 도구를 정상 실행하여 근거와 함께 200 반환
    chat_resp = await _send(app, "POST", "/api/chat", json_body=deep_payload, settings_obj=cfg)
    assert chat_resp.status_code == 200, chat_resp.text
    assert grounded_chat.calls[-1]["tool_id"] == "deep_research"
    assert grounded_chat.calls[-1]["tool_input"] == "반도체 공급망 동향"
    body = chat_resp.json()
    assert body["answer"] == "deep_research 완료 답변"
    assert body["tool"]["id"] == "deep_research"
    assert body["conversation_id"].startswith("chat_")


# ===========================================================================
# 3. /api/chat 폴백 게이트 (일반 텍스트 및 첨부 완료 경로)
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_api_chat_fallback_handles_attachments_and_projects_run_history():
    store = _RecordingHistoryStore()
    bridge = _RecordingOrchestrationBridge()
    b14 = _RecordingB14Client(thought="", answer="문서 기반 완료 답변")
    cfg = _settings()
    app = _build_app(
        cfg,
        history_store=store,
        b14_client=b14,
        orchestration_bridge=bridge,
    )
    app.state.usage_gate_enforced = False

    attachment_payload = {
        "messages": [{"role": "user", "content": "첨부 문서 요약해줘"}],
        "tier": "free",
        "attachments": [
            {
                "type": "document",
                "name": "notes.txt",
                "media_type": "text/plain",
                "text": "1분기 매출 보고서 초안 본문입니다.",
            }
        ],
    }

    # 1) /api/orchestration은 첨부가 있으면 409 orchestration_not_applicable 반환
    orch_resp = await _send(app, "POST", "/api/orchestration", json_body=attachment_payload)
    assert orch_resp.status_code == 409
    assert orch_resp.json()["error"]["code"] == "orchestration_not_applicable"

    # 2) /api/chat/stream은 첨부가 있으면 422 streaming_unsupported 반환
    stream_resp = await _send(app, "POST", "/api/chat/stream", json_body=attachment_payload)
    assert stream_resp.status_code == 422
    assert stream_resp.json()["error"]["code"] == "streaming_unsupported"

    # 3) /api/chat 폴백은 200으로 문서 컨텍스트를 포함해 답변하고 대화·실행 기록에 남김
    chat_resp = await _send(app, "POST", "/api/chat", json_body=attachment_payload)
    assert chat_resp.status_code == 200, chat_resp.text
    body = chat_resp.json()
    assert body["answer"] == "문서 기반 완료 답변"
    assert body["conversation_id"].startswith("chat_")
    assert body["attachments"] == [
        {
            "type": "document",
            "name": "notes.txt",
            "media_type": "text/plain",
            "byte_size": 48,
            "text_chars": 20,
        }
    ]
    assert "1분기 매출 보고서 초안 본문입니다." in (b14.complete_calls[-1].get("additional_system_context") or "")
    assert len(store.runs) == 1
    assert store.runs[0]["status"] == "completed"
    assert store.runs[0]["result_summary"] == "문서 기반 완료 답변"


# ===========================================================================
# 4. Custom + 도구 게이트
# ===========================================================================


@pytest.mark.asyncio
async def test_gate_custom_direct_and_custom_plus_tool_or_attachment_contract():
    d1 = _SQLiteD1()
    store = _RecordingHistoryStore()
    credential_store = D1CustomProviderCredentialStore(
        d1,
        key_secret=CUSTOM_KEY_SECRET,
        session_secret=SESSION_SECRET,
        cipher=_FakeCipher(),
    )
    await credential_store.save(user_id=OWNER, provider_id=CUSTOM_PROVIDER_SLOT, api_key=CUSTOM_KEY)

    provider_requests: list[httpx.Request] = []

    def _provider_handler(req: httpx.Request) -> httpx.Response:
        provider_requests.append(req)
        return httpx.Response(
            200,
            json={
                "model": UPSTREAM_MODEL_SLOT,
                "choices": [{"message": {"content": "내 키 직접 답변"}}],
            },
        )

    bridge = _RecordingOrchestrationBridge(thought="", answer="엔진 경유 내 키 답변")
    cfg_direct = _settings(byok_via_b14=False)
    app_direct = _build_app(
        cfg_direct,
        history_store=store,
        orchestration_bridge=bridge,
        custom_credential_store=credential_store,
        custom_provider_client=CustomProviderClient(transport=httpx.MockTransport(_provider_handler)),
    )

    custom_text_payload = {
        "messages": [{"role": "user", "content": "내 키로 질문합니다"}],
        "custom": {"provider": CUSTOM_PROVIDER_SLOT, "model": CUSTOM_MODEL_SLOT},
    }

    # (A) byok_via_b14=False일 때 /api/orchestration은 409 orchestration_not_applicable을 반환해
    #     브라우저가 /api/chat/stream 직행 경로로 폴백하게 한다.
    orch_direct = await _send(app_direct, "POST", "/api/orchestration", json_body=custom_text_payload)
    assert orch_direct.status_code == 409
    assert orch_direct.json()["error"]["code"] == "orchestration_not_applicable"

    # (B) /api/chat/stream과 /api/chat에서 Custom 텍스트 질문은 200으로 응답하고 기록에 투영된다.
    stream_direct = await _send(app_direct, "POST", "/api/chat/stream", json_body=custom_text_payload)
    assert stream_direct.status_code == 200, stream_direct.text
    sse = _parse_sse(stream_direct.text)
    assert [name for name, _ in sse] == ["delta", "done"]
    assert sse[0][1] == {"delta": "내 키 직접 답변"}

    chat_direct = await _send(app_direct, "POST", "/api/chat", json_body=custom_text_payload)
    assert chat_direct.status_code == 200, chat_direct.text
    assert chat_direct.json()["answer"] == "내 키 직접 답변"
    assert len(provider_requests) == 2

    # (C) Custom + 명시 도구(web_search / deep_research) 및 Custom + 첨부는
    #     /api/orchestration, /api/chat/stream, /api/chat 모두에서 422로 거부된다.
    for endpoint in ("/api/orchestration", "/api/chat/stream", "/api/chat"):
        with_tool = await _send(
            app_direct,
            "POST",
            endpoint,
            json_body={
                **custom_text_payload,
                "tool": "web_search",
                "tool_input": "환율",
            },
        )
        assert with_tool.status_code == 422, (endpoint, with_tool.text)
        assert with_tool.json()["error"]["message"] == "PADIEM Custom은 현재 텍스트 대화만 지원합니다."

        with_deep = await _send(
            app_direct,
            "POST",
            endpoint,
            json_body={
                **custom_text_payload,
                "tool": "deep_research",
                "tool_input": "심층 검색",
            },
        )
        assert with_deep.status_code == 422, (endpoint, with_deep.text)
        assert with_deep.json()["error"]["message"] == "PADIEM Custom은 현재 텍스트 대화만 지원합니다."

        with_attachment = await _send(
            app_direct,
            "POST",
            endpoint,
            json_body={
                **custom_text_payload,
                "attachments": [
                    {
                        "type": "document",
                        "name": "doc.txt",
                        "media_type": "text/plain",
                        "text": "문서 본문",
                    }
                ],
            },
        )
        assert with_attachment.status_code == 422, (endpoint, with_attachment.text)
        assert with_attachment.json()["error"]["message"] == "PADIEM Custom은 현재 텍스트 대화만 지원합니다."

    # (D) byok_via_b14=True일 때 /api/orchestration은 user_credential_ref를 해석해 SSE 스트림으로 중계한다.
    cfg_via_engine = _settings(byok_via_b14=True)
    app_via_engine = _build_app(
        cfg_via_engine,
        history_store=store,
        orchestration_bridge=bridge,
        custom_credential_store=credential_store,
        custom_provider_client=CustomProviderClient(transport=httpx.MockTransport(_provider_handler)),
    )

    orch_via = await _send(
        app_via_engine,
        "POST",
        "/api/orchestration",
        json_body=custom_text_payload,
        settings_obj=cfg_via_engine,
    )
    assert orch_via.status_code == 200, orch_via.text
    assert orch_via.headers.get("content-type", "").startswith("text/event-stream")
    assert len(bridge.streamed_calls) == 1
    assert bridge.streamed_calls[0]["byok_selection"] == {
        "provider": CUSTOM_PROVIDER_SLOT,
        "model": CUSTOM_MODEL_SLOT,
    }
    assert bridge.streamed_calls[0]["user_credential_ref"] is not None
