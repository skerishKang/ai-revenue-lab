"""``LocalB14Binding``: the host stand-in for the B14 Service Binding.

Two defects made every host B14 call report "Service Binding is unavailable"
before a socket was opened, and a successful call unreadable after it:

* the request headers arrive as the local ``_Headers`` view, which has no
  ``keys()``, so ``dict(headers)`` raised inside ``fetch``;
* the binding transport reads responses through ``body.getReader()``, while the
  binding answered with raw bytes.

Both are asserted here at the seam, without a network.
"""

from __future__ import annotations

import json

import pytest

from app import local_runtime as rt

B14_URL = "https://b14.internal/api/pilot/v1/chat/completions"


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.content = payload
        self.status_code = 200
        self.headers = {"content-type": "application/json"}


class _FakeClient:
    def __init__(self, record: dict, payload: bytes) -> None:
        self._record = record
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def request(self, method, url, headers=None, content=None):
        self._record.update(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "content": content,
            }
        )
        return _FakeResponse(self._payload)


def _binding(monkeypatch, payload: bytes) -> tuple[rt.LocalB14Binding, dict]:
    record: dict = {}

    def fake_client(*args, **kwargs):
        return _FakeClient(record, payload)

    monkeypatch.setattr(rt.httpx, "AsyncClient", fake_client)
    return rt.LocalB14Binding("http://127.0.0.1:8789"), record


def _request() -> rt.LocalRequest:
    return rt.LocalRequest(
        B14_URL,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Padiem-B14-Proof": "a" * 64,
            "X-Padiem-B14-Time": "1700000000",
        },
        body=b'{"model":"host-model"}',
    )


async def test_fetch_forwards_the_local_headers_without_raising(monkeypatch) -> None:
    payload = json.dumps({"choices": []}).encode()
    binding, record = _binding(monkeypatch, payload)

    await binding.fetch(_request())

    assert record["method"] == "POST"
    assert record["url"] == "http://127.0.0.1:8789/api/pilot/v1/chat/completions"
    assert record["headers"]["content-type"] == "application/json"
    assert record["headers"]["x-padiem-b14-proof"] == "a" * 64
    assert record["headers"]["x-padiem-b14-time"] == "1700000000"
    assert record["content"] == b'{"model":"host-model"}'


async def test_the_answer_body_is_readable_the_way_the_binding_reads_it(monkeypatch) -> None:
    payload = json.dumps({"choices": [{"message": {"content": "합성 답변"}}]}).encode()
    binding, _record = _binding(monkeypatch, payload)

    response = await binding.fetch(_request())

    reader = response.body.getReader()
    first = await reader.read()
    assert first.done is False
    assert first.value == payload
    second = await reader.read()
    assert second.done is True
    assert second.value is None


def test_a_get_reader_body_stays_opaque_in_local_response() -> None:
    """``LocalResponse`` must not coerce a stream body into text."""

    stream = rt.LocalByteStream(b"payload")
    response = rt.LocalResponse(stream, status=200)

    assert response.body is stream
    assert response.status == 200


async def test_a_non_loopback_origin_is_refused() -> None:
    with pytest.raises(rt.LocalRuntimeError):
        rt.LocalB14Binding("http://b14.padiem.net:8789")
