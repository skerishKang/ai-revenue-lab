from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.b14_client import ChatRuntimeError
from app.config import Settings
from app.main import create_app
from app.poolside_ux_test import (
    POOL_SIDE_CHAT_URL,
    POOL_SIDE_MODEL,
    PoolsideUXTestClient,
    is_version_preview_host,
)
from app.public_chat import public_chat_result


class FakeSecretBinding:
    def __init__(self, value: str = "unit-test-credential", *, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls = 0

    async def get(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


@pytest.mark.asyncio
async def test_completion_uses_fixed_poolside_origin_model_and_server_authorization() -> None:
    secret = FakeSecretBinding()
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        body = json.loads(request.content.decode("utf-8"))
        seen["body"] = body
        return httpx.Response(
            200,
            json={"id": "test-response", "choices": [{"message": {"content": "실제 형태의 테스트 답변입니다."}}]},
        )

    client = PoolsideUXTestClient(secret, transport=httpx.MockTransport(handler))
    result = await client.complete([{"role": "user", "content": "짧게 답해 주세요."}])

    assert seen["url"] == POOL_SIDE_CHAT_URL
    assert seen["authorization"] == "Bearer unit-test-credential"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body["model"] == POOL_SIDE_MODEL
    assert body["stream"] is False
    assert body["messages"][-1] == {"role": "user", "content": "짧게 답해 주세요."}
    assert result["answer"] == "실제 형태의 테스트 답변입니다."
    assert result["runtime"] == "test_poolside"
    assert secret.calls == 1
    assert "unit-test-credential" not in repr(client)


@pytest.mark.asyncio
async def test_public_chat_document_path_keeps_reference_context_but_strips_route_identity() -> None:
    secret = FakeSecretBinding()
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        captured["messages"] = body["messages"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "문서의 핵심은 테스트 계획입니다."}}]})

    direct = PoolsideUXTestClient(secret, transport=httpx.MockTransport(handler))
    app = create_app(settings=Settings.from_values(runtime_mode="mock", live_enabled="false"))
    app.state.b14_client = direct
    app.state.usage_gate_enforced = False

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://preview.test") as browser:
        response = await browser.post(
            "/api/chat",
            json={
                "messages": [{"role": "user", "content": "첨부 문서 핵심을 알려주세요."}],
                "attachments": [
                    {
                        "type": "document",
                        "name": "ux-test.txt",
                        "media_type": "text/plain",
                        "text": "이 문서의 핵심은 실제 대화 UX 테스트 계획입니다.",
                    }
                ],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "문서의 핵심은 테스트 계획입니다."
    assert payload["runtime"] == "test_poolside"
    assert "route" not in payload
    assert "request_id" not in payload
    assert "model" not in json.dumps(payload, ensure_ascii=False).lower()
    assert "provider" not in json.dumps(payload, ensure_ascii=False).lower()
    assert payload["attachments"][0]["name"] == "ux-test.txt"

    provider_messages = captured["messages"]
    assert isinstance(provider_messages, list)
    system_text = "\n".join(
        item["content"] for item in provider_messages if isinstance(item, dict) and item.get("role") == "system"
    )
    assert "신뢰되지 않은 참고 데이터" in system_text
    assert "실제 대화 UX 테스트 계획" in system_text
    assert "비밀/API 키 요청" in system_text


@pytest.mark.asyncio
async def test_progressive_stream_yields_multiple_visible_deltas_then_done() -> None:
    secret = FakeSecretBinding()
    sse = (
        'data: {"choices":[{"delta":{"content":"첫"}}]}\n\n'
        ': keepalive\n\n'
        'data: {"choices":[{"delta":{"content":" 번째"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":" 답변"}}]}\n\n'
        'data: [DONE]\n\n'
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == POOL_SIDE_MODEL
        assert body["stream"] is True
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))

    client = PoolsideUXTestClient(secret, transport=httpx.MockTransport(handler))
    events = [event async for event in client.stream_text_auto([{"role": "user", "content": "스트리밍 테스트"}])]

    assert [event.delta_content for event in events if event.delta_content] == ["첫", " 번째", " 답변"]
    assert events[-1].done is True
    assert secret.calls == 1


@pytest.mark.asyncio
async def test_stream_finishes_on_finish_reason_without_done_marker() -> None:
    secret = FakeSecretBinding()
    sse = (
        'data: {"choices":[{"delta":{"content":"완료"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
    )

    client = PoolsideUXTestClient(
        secret,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))
        ),
    )
    events = [event async for event in client.stream_text_auto([{"role": "user", "content": "finish reason 테스트"}])]

    assert [event.delta_content for event in events if event.delta_content] == ["완료"]
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_incomplete_stream_fails_closed_without_done_event() -> None:
    secret = FakeSecretBinding()
    sse = 'data: {"choices":[{"delta":{"content":"중간 답변"}}]}\n\n'
    client = PoolsideUXTestClient(
        secret,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))
        ),
    )

    events = []
    with pytest.raises(ChatRuntimeError) as caught:
        async for event in client.stream_text_auto([{"role": "user", "content": "EOF 테스트"}]):
            events.append(event)

    assert caught.value.code == "incomplete_upstream_stream"
    assert all(not event.done for event in events)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_browser_stream_exposes_incomplete_upstream_as_sse_error() -> None:
    sse = 'data: {"choices":[{"delta":{"content":"브라우저에 보일 일부 답변"}}]}\n\n'
    direct = PoolsideUXTestClient(
        FakeSecretBinding(),
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode("utf-8"))
        ),
    )
    app = create_app(settings=Settings.from_values(runtime_mode="mock", live_enabled="false"))
    app.state.b14_client = direct
    app.state.usage_gate_enforced = False

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://preview.test") as browser:
        response = await browser.post(
            "/api/chat/stream",
            json={"messages": [{"role": "user", "content": "브라우저 스트림 테스트"}]},
        )

    assert response.status_code == 200
    assert response.text.count("event: delta") == 1
    assert response.text.count("event: error") == 1
    assert '"code":"incomplete_upstream_stream"' in response.text
    assert "event: done" not in response.text


@pytest.mark.asyncio
async def test_provider_http_error_is_bounded_and_does_not_echo_credential() -> None:
    secret_value = "unit-test-credential-never-echo"
    secret = FakeSecretBinding(secret_value)

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"upstream accidentally echoed {secret_value}")

    client = PoolsideUXTestClient(secret, transport=httpx.MockTransport(handler))
    with pytest.raises(ChatRuntimeError) as caught:
        await client.complete([{"role": "user", "content": "테스트"}])

    assert caught.value.code == "test_provider_auth_failed"
    assert secret_value not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_secret_binding_failure_is_fail_closed_without_exception_chain() -> None:
    marker = "binding-internal-sensitive-marker"
    secret = FakeSecretBinding(error=RuntimeError(marker))
    client = PoolsideUXTestClient(secret, transport=httpx.MockTransport(lambda _request: httpx.Response(500)))

    with pytest.raises(ChatRuntimeError) as caught:
        await client.complete([{"role": "user", "content": "테스트"}])

    assert caught.value.code == "test_provider_credential_unavailable"
    assert marker not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.asyncio
async def test_malformed_or_empty_completion_fails_closed() -> None:
    secret = FakeSecretBinding()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    client = PoolsideUXTestClient(secret, transport=httpx.MockTransport(handler))
    with pytest.raises(ChatRuntimeError) as caught:
        await client.complete([{"role": "user", "content": "테스트"}])

    assert caught.value.code == "malformed_upstream"


def test_version_preview_host_guard_rejects_canonical_production() -> None:
    assert is_version_preview_host("9abc1234-padiem-chat.charliekant.workers.dev") is True
    assert is_version_preview_host("ux1091-padiem-chat.charliekant.workers.dev") is True
    assert is_version_preview_host("padiem-chat.charliekant.workers.dev") is False
    assert is_version_preview_host("evil.example") is False
    assert is_version_preview_host(None) is False


def test_public_projection_drops_internal_provider_and_model_metadata() -> None:
    result = public_chat_result(
        {
            "answer": "안녕하세요.",
            "runtime": "test_poolside",
            "request_id": "internal",
            "route": {"provider": "Poolside", "model": POOL_SIDE_MODEL, "mode": "test-direct"},
            "skill": {"id": "auto", "title": "자동 추천"},
        }
    )

    assert result == {
        "answer": "안녕하세요.",
        "runtime": "test_poolside",
        "skill": {"id": "auto", "title": "자동 추천"},
    }


def test_ux_test_wrangler_config_is_version_preview_only_and_uses_secrets_store() -> None:
    root = Path(__file__).resolve().parents[1]
    test_config = (root / "wrangler.ux-test.toml").read_text(encoding="utf-8")
    production_config = (root / "wrangler.toml").read_text(encoding="utf-8")

    assert 'name = "padiem-chat"' in test_config
    assert 'main = "worker_ux_test.py"' in test_config
    assert "preview_urls = true" in test_config
    assert "[[secrets_store_secrets]]" in test_config
    assert 'binding = "PADIEM_POOLSIDE_API_KEY"' in test_config
    assert 'secret_name = "PADIEM_POOLSIDE_API_KEY"' in test_config
    assert "f0b09ca04a7b43248154c773704a5616" in test_config
    assert "worker_ux_test.py" not in production_config
    assert "secrets_store_secrets" not in production_config
