from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.bounded_request_body import RequestBodyTooLarge, read_bounded_request_body


class FakeRequest:
    def __init__(self, chunks: list[bytes], *, content_length: str | None = None) -> None:
        self._chunks = list(chunks)
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = content_length
        self.stream_calls = 0
        self.yield_count = 0
        self.url = SimpleNamespace(path="/api/chat")

    def stream(self):
        self.stream_calls += 1

        async def _iter():
            for chunk in self._chunks:
                self.yield_count += 1
                yield chunk

        return _iter()


def test_exact_limit_accepts_multiple_chunks() -> None:
    request = FakeRequest([b"ab", b"cd"])
    body = asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert body == b"abcd"
    assert request.stream_calls == 1
    assert request.yield_count == 2


def test_chunked_oversize_stops_before_later_chunks() -> None:
    request = FakeRequest([b"1234", b"5", b"never-read"])

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert request.stream_calls == 1
    assert request.yield_count == 2


def test_declared_oversize_rejects_before_stream_is_opened() -> None:
    request = FakeRequest([b"never-read"], content_length="5")

    with pytest.raises(RequestBodyTooLarge):
        asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert request.stream_calls == 0
    assert request.yield_count == 0


def test_missing_or_malformed_length_uses_incremental_counter() -> None:
    request = FakeRequest([b"12", b"34"], content_length="not-a-number")
    body = asyncio.run(read_bounded_request_body(request, max_bytes=4))

    assert body == b"1234"
    assert request.stream_calls == 1
    assert request.yield_count == 2


def test_core_public_routes_never_fall_back_to_full_request_body_materialization() -> None:
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    for name in ("auth_routes.py", "chat_routes.py", "claw_routes.py", "orchestration_routes.py"):
        source = (app_dir / name).read_text(encoding="utf-8")
        assert "await request.body()" not in source, name
        assert "read_bounded_request_body" in source, name


def _error_code(response) -> str:
    return json.loads(response.body.decode("utf-8"))["error"]["code"]


def test_chat_routes_do_not_refuse_a_body_for_its_size() -> None:
    # #4379: the browser request carries no PADIEM byte total, so a chunked
    # body past the former 6MB budget is read instead of being refused.
    from app import chat_routes

    assert chat_routes.MAX_BROWSER_BODY_BYTES is None
    for handler in (chat_routes.api_chat, chat_routes.api_chat_stream):
        request = FakeRequest(
            [
                b"x" * 6_000_000,
                b"y",
                b"never-read",
            ]
        )
        response = asyncio.run(handler(request))

        assert response.status_code != 413
        # The body was read to the end instead of being cut at a byte budget.
        assert request.yield_count == 3


def test_the_reader_stays_incremental_without_a_padiem_total() -> None:
    # #4379: a route may declare no PADIEM byte total. The reader still
    # streams the body chunk by chunk.
    request = FakeRequest([b"ab", b"cd", b"ef"])
    body = asyncio.run(read_bounded_request_body(request, max_bytes=None))

    assert body == b"abcdef"
    assert request.stream_calls == 1
    assert request.yield_count == 3


def test_orchestration_reader_rejects_chunked_oversize_with_existing_vocab() -> None:
    from app import orchestration_routes
    from app.orchestration_bridge import B62OrchestrationError

    request = FakeRequest(
        [
            b"x" * orchestration_routes.MAX_ORCHESTRATION_BROWSER_BODY_BYTES,
            b"y",
            b"never-read",
        ]
    )

    with pytest.raises(B62OrchestrationError) as caught:
        asyncio.run(orchestration_routes._json_body(request))

    assert caught.value.code == "request_too_large"
    assert caught.value.status_code == 413
    assert request.yield_count == 2


def test_claw_public_routes_reject_chunked_oversize_before_later_chunks() -> None:
    from app import claw_routes

    for handler in (
        claw_routes.claw_manual_intake_preview,
        claw_routes.claw_manual_intake_execute,
        claw_routes.claw_manual_intake_quote_compare,
    ):
        request = FakeRequest(
            [
                b"x" * claw_routes.MAX_MANUAL_INTAKE_BODY_BYTES,
                b"y",
                b"never-read",
            ]
        )
        request.headers["content-type"] = "application/json"
        response = asyncio.run(handler(request))

        assert response.status_code == 413
        assert _error_code(response) == "request_too_large"
        assert request.yield_count == 2


def test_claw_approval_route_uses_same_bounded_reader(monkeypatch) -> None:
    from app import claw_routes

    monkeypatch.setattr(claw_routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(claw_routes, "current_user_id", lambda request: "user_test")

    request = FakeRequest(
        [
            b"x" * claw_routes.MAX_APPROVAL_DECISION_BODY_BYTES,
            b"y",
            b"never-read",
        ]
    )
    request.headers["content-type"] = "application/json"
    response = asyncio.run(claw_routes.claw_approval_decision(request))

    assert response.status_code == 413
    assert _error_code(response) == "request_too_large"
    assert request.yield_count == 2


def test_password_auth_reader_rejects_chunked_oversize_before_later_chunks() -> None:
    from app import auth_routes

    request = FakeRequest(
        [
            b"x" * auth_routes._PASSWORD_BODY_LIMIT,
            b"y",
            b"never-read",
        ]
    )
    request.headers["content-type"] = "application/json"

    parsed = asyncio.run(auth_routes._json_body(request))

    assert parsed is None
    assert request.yield_count == 2
