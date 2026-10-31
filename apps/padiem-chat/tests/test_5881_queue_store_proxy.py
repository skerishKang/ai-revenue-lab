"""#5881 follow-on: the queue proxy switches, refuses, and forwards only what it may.

No network. The transport is a recording mock, and what is proved is the shape of the
one call, the fail-closed switch, and the two lists that must not drift: the names this
Worker may ask for and the names the queue is willing to answer.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
from typing import Any

import pytest

from app import queue_store_proxy as proxy

QUEUE_MODULE = (pathlib.Path(__file__).resolve().parents[3]
                / "apps" / "padiem-mesh-queue" / "internal_store.py")
SECRET = "queue-service-secret-value-261029"
ORIGIN = "https://queue.padiem.net"
MARKER = "C:/Users/customer/private-file.txt"


class _Response:
    """Exactly the response surface consumed from Workers: no json/aread."""
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    async def aiter_bytes(self):
        # Split inside multibyte UTF-8 as a real fetch may do.
        for index in range(0, len(self._raw), 2):
            yield self._raw[index:index + 2]


class _Call:
    """Workers-shaped recording client: stream(), never post()."""

    def __init__(self, handler):
        self.handler = handler
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, json=None, headers=None):
        self.sent.append({"method": method, "url": url, "json": json, "headers": dict(headers or {})})
        outer = self
        class Context:
            async def __aenter__(self):
                return outer.handler(dict(outer.sent[-1]))
            async def __aexit__(self, *exc):
                outer.closed = True
                return False
        return Context()


def _client(handler):
    """A client whose only network part is the recording stand-in above."""

    recorder = _Call(handler)
    return proxy.QueueStoreClient(origin=ORIGIN, service_secret=SECRET,
                                  client_factory=recorder), recorder


def _queue_module():
    spec = importlib.util.spec_from_file_location("queue_internal_store", QUEUE_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_switch_is_fail_closed_to_the_path_that_runs_today():
    for value in (None, "", "  ", "D1", "postgres", "com2x", 7):
        assert proxy.queue_backend(value) == proxy.QUEUE_BACKEND_D1
    for value in ("com2", "COM2", " com2 "):
        assert proxy.queue_backend(value) == proxy.QUEUE_BACKEND_COM2


def test_no_client_is_built_without_the_switch_or_without_material():
    class Env:
        PC_QUEUE_BACKEND = "d1"

    assert proxy.build_queue_client(Env()) is None

    class HalfSwitched(Env):
        PC_QUEUE_BACKEND = "com2"

    with pytest.raises(proxy.QueueUnavailable):
        proxy.build_queue_client(HalfSwitched())

    class Switched(HalfSwitched):
        PC_QUEUE_ORIGIN = ORIGIN
        PC_QUEUE_SERVICE_SECRET = SECRET

    assert isinstance(proxy.build_queue_client(Switched()), proxy.QueueStoreClient)


def test_loopback_http_is_opt_in_and_narrow():
    """The 8830 staging queue is plain http on loopback; https stays the default."""

    with pytest.raises(proxy.QueueUnavailable):
        proxy.QueueStoreClient(origin="http://127.0.0.1:8830", service_secret=SECRET)

    client = proxy.QueueStoreClient(
        origin="http://127.0.0.1:8830/", service_secret=SECRET,
        allow_loopback_http=True,
    )
    assert client._origin == "http://127.0.0.1:8830"
    assert proxy.QueueStoreClient(
        origin="http://localhost:8830", service_secret=SECRET,
        allow_loopback_http=True,
    )._origin == "http://localhost:8830"

    for bad in (
        "http://example.com:8830",
        "http://127.0.0.1",
        "http://127.0.0.1:8830/path",
        "http://user@127.0.0.1:8830",
        "https://127.0.0.1:8830",
        "http://[::1]:8830",
        "http://127.0.0.1:8830?x=1",
    ):
        with pytest.raises(proxy.QueueUnavailable):
            proxy.QueueStoreClient(origin=bad, service_secret=SECRET,
                                   allow_loopback_http=True)


def test_build_queue_client_reads_the_loopback_flag_strictly():
    class Env:
        PC_QUEUE_BACKEND = "com2"
        PC_QUEUE_ORIGIN = "http://127.0.0.1:8830"
        PC_QUEUE_SERVICE_SECRET = SECRET

    with pytest.raises(proxy.QueueUnavailable):
        proxy.build_queue_client(Env())

    Env.PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP = "0"
    with pytest.raises(proxy.QueueUnavailable):
        proxy.build_queue_client(Env())

    Env.PADIEM_CHAT_QUEUE_ALLOW_LOOPBACK_HTTP = "true"
    assert isinstance(proxy.build_queue_client(Env()), proxy.QueueStoreClient)


def test_the_call_sends_the_declared_name_and_proves_the_service_secret():
    seen: dict[str, Any] = {}

    client, recorder = _client(lambda sent: _Response(200, {"ok": True, "result": []}))
    assert asyncio.run(client.call("list_links", user_id="usr_1")) == []
    sent = recorder.sent[0]
    seen["path"] = __import__("urllib.parse", fromlist=["x"]).urlparse(sent["url"]).path
    seen["secret"] = sent["headers"][proxy.QUEUE_SERVICE_SECRET_HEADER]
    seen["body"] = sent["json"]
    assert seen["path"] == proxy.INTERNAL_STORE_PATH
    assert seen["secret"] == SECRET
    assert seen["body"] == {"method": "list_links", "arguments": {"user_id": "usr_1"}}


def test_every_queue_call_carries_the_declared_user_agent():
    """The Cloudflare edge answers the Pyodide runtime's default
    `Python-urllib/3.12` UA with 403 error 1010 before the queue is reached, so
    each call must name itself with the explicit UA."""

    client, recorder = _client(lambda sent: _Response(200, {"ok": True, "result": []}))
    asyncio.run(client.call("list_links", user_id="usr_1"))
    agent = recorder.sent[0]["headers"]["User-Agent"]
    assert agent == proxy.QUEUE_USER_AGENT
    assert agent != "Python-urllib/3.12"
    assert "urllib" not in agent.lower()


def test_an_unusable_answer_is_named_without_repeating_what_was_sent():
    def handler(request):
        return _Response(502, {"ok": False,
                               "error": {"code": "queue_store_failed"}})

    client, _ = _client(handler)
    with pytest.raises(proxy.QueueUnavailable) as caught:
        asyncio.run(client.call("device_scope", device_id=MARKER))
    assert MARKER not in str(caught.value)
    assert MARKER not in repr(caught.value)


@pytest.mark.parametrize("answer", [
    {"ok": True},  # no result to hand back
    {"ok": False, "result": []},  # a refusal the client must not read as a value
    {"result": []},  # no answer at all
    "not an object",  # the queue answered with something else
])
def test_a_malformed_answer_never_becomes_a_quiet_empty_result(answer):
    def handler(request):
        return _Response(200, answer)

    client, _ = _client(handler)
    with pytest.raises(proxy.QueueUnavailable):
        asyncio.run(client.call("list_links", user_id="usr_1"))


def test_history_store_moves_only_the_dispatch_names_and_keeps_the_conversation_local():
    called: list[str] = []

    def handler(request):
        called.append(request["json"]["method"])
        return _Response(200, {"ok": True, "result": {"dispatch_id": "dsp_1"}})

    class Inner:
        async def get_user(self, *, user_id):
            return {"id": user_id, "from": "d1"}

        async def store_oracle_mesh_original(self, **arguments):
            return "r2"

    client, _ = _client(handler)
    store = proxy.QueueForwardingHistoryStore(Inner(), client)
    moved = asyncio.run(store.oldest_pending_oracle_mesh_dispatch())
    assert moved == {"dispatch_id": "dsp_1"}
    assert asyncio.run(store.get_user(user_id="usr_1"))["from"] == "d1"
    # The over-budget original lives in private R2: it is not the queue's to answer.
    assert asyncio.run(store.store_oracle_mesh_original(dispatch_id="dsp_1")) == "r2"
    assert called == ["oldest_pending_oracle_mesh_dispatch"]


def test_an_undeclared_store_name_cannot_reach_the_transport():
    def handler(request):
        raise AssertionError("the transport must not be touched")

    client, _ = _client(handler)
    pairing = proxy.QueueBackedPairingStore(client)
    with pytest.raises(AttributeError):
        pairing.drop_table()
    assert callable(pairing.list_links)


def test_the_two_allowlists_are_one_list():
    """A name this Worker can ask for must be a name the queue is willing to answer."""

    queue = _queue_module()
    assert proxy.QUEUE_DISPATCH_METHODS == queue.DISPATCH_METHODS
    assert proxy.QUEUE_PAIRING_METHODS == queue.PAIRING_METHODS
    assert proxy.QUEUE_PRESENCE_METHODS == queue.PRESENCE_METHODS
    # Nothing the conversation or private storage owns is on either list.
    for forbidden in ("store_oracle_mesh_command_result", "store_oracle_mesh_original",
                      "store_oracle_mesh_original_bytes", "read_oracle_mesh_original",
                      "append_local_task_result", "get_claw_run"):
        assert forbidden not in proxy.QUEUE_DISPATCH_METHODS, forbidden


@pytest.mark.parametrize('result', [None, [], {'name': '한글🙂', 'count': 2}])
def test_workers_shaped_response_parses_without_httpx_only_helpers(result):
    response = _Response(200, {'ok': True, 'result': result})
    assert not hasattr(response, 'json') and not hasattr(response, 'aread')
    client, recorder = _client(lambda sent: response)
    assert not hasattr(recorder, 'post')
    assert asyncio.run(client.call('list_links')) == result
    assert recorder.sent[0]['method'] == 'POST' and recorder.closed


def test_actual_httpx_streaming_response_is_supported():
    import httpx
    seen = []
    async def handler(request):
        seen.append(request.method)
        assert json.loads(request.content)['method'] == 'list_links'
        return httpx.Response(200, json={'ok': True, 'result': {'name': '한글🙂'}})
    transport = httpx.MockTransport(handler)
    client = proxy.QueueStoreClient(origin=ORIGIN, service_secret=SECRET,
        client_factory=lambda **options: httpx.AsyncClient(transport=transport, **options))
    assert asyncio.run(client.call('list_links')) == {'name': '한글🙂'}
    assert seen == ['POST']


def test_actual_workers_compat_client_and_response_interface(monkeypatch):
    from test_httpx_compat_workers_timeout import _load_workers_shim
    shim = _load_workers_shim(None)
    assert not hasattr(shim.AsyncClient, 'post') and not hasattr(shim.Response, 'json')
    monkeypatch.setattr(proxy, 'httpx', shim)
    closed, seen = [], []
    class Stream(shim.AsyncByteStream):
        async def __aiter__(self):
            raw = json.dumps({'ok': True, 'result': '한글🙂'}, ensure_ascii=False).encode()
            for byte in raw:
                yield bytes([byte])
        async def aclose(self):
            closed.append(True)
    class Transport(shim.AsyncBaseTransport):
        async def handle_async_request(self, request):
            seen.append(request.method)
            return shim.Response(200, stream=Stream())
    client = proxy.QueueStoreClient(origin=ORIGIN, service_secret=SECRET,
        client_factory=lambda **options: shim.AsyncClient(transport=Transport(), **options))
    assert asyncio.run(client.call('list_links')) == '한글🙂'
    assert seen == ['POST'] and closed == [True]


@pytest.mark.parametrize('failure,stage,status,reason', [
    ('transport', 'request', 0, 'transport_error'),
    ('http', 'status', 403, 'http_status'),
    ('body', 'body_read', 200, 'transport_error'),
    ('json', 'json_decode', 200, 'invalid_json'),
    ('envelope', 'envelope', 200, 'invalid_envelope'),
])
def test_diagnostics_distinguish_failure_stage_without_values(caplog, failure, stage, status, reason):
    import logging
    class Response(_Response):
        async def aiter_bytes(self):
            if failure == 'body':
                raise proxy.httpx.ReadError(MARKER + SECRET)
            async for chunk in super().aiter_bytes():
                yield chunk
    response = Response(403 if failure == 'http' else 200,
                        {'ok': False, 'error': MARKER} if failure == 'envelope' else {'ok': True, 'result': MARKER})
    if failure == 'json':
        response._raw = (MARKER + SECRET).encode()
    def handler(sent):
        if failure == 'transport':
            raise proxy.httpx.ConnectError(MARKER + SECRET)
        return response
    client, recorder = _client(handler)
    with caplog.at_level(logging.INFO, logger=proxy.__name__), pytest.raises(proxy.QueueUnavailable) as caught:
        asyncio.run(client.call('list_links', user_id=MARKER))
    lines = [record.getMessage() for record in caplog.records if record.name == proxy.__name__]
    assert len(lines) == 1
    assert f'method=list_links stage={stage} status={status} outcome=error reason={reason} elapsed_ms=' in lines[0]
    for forbidden in (MARKER, SECRET, ORIGIN, proxy.QUEUE_SERVICE_SECRET_HEADER):
        assert forbidden not in lines[0] and forbidden not in str(caught.value)
    if failure != 'transport':
        assert recorder.closed


def test_success_log_does_not_echo_an_unknown_method_or_result(caplog):
    import logging
    client, _ = _client(lambda sent: _Response(200, {'ok': True, 'result': MARKER}))
    with caplog.at_level(logging.INFO, logger=proxy.__name__):
        assert asyncio.run(client.call('customer_private_method', user_id=MARKER)) == MARKER
    line = caplog.records[-1].getMessage()
    assert 'method=other stage=complete status=200 outcome=ok reason=ok elapsed_ms=' in line
    for forbidden in ('customer_private_method', MARKER, SECRET, ORIGIN):
        assert forbidden not in line


@pytest.mark.parametrize("status,raw,expected", [
    (200, b'{"ok":true,"result":[1]}', [1]),
    (403, b'{"ok":false,"error":{}}', None),
    (200, b'not-json', None),
])
def test_workers_forced_load_transport_handles_status_and_body(monkeypatch, status, raw, expected):
    from test_httpx_compat_workers_timeout import _load_workers_shim
    shim = _load_workers_shim(None)
    monkeypatch.setattr(proxy, "httpx", shim)
    class Stream(shim.AsyncByteStream):
        async def __aiter__(self):
            yield raw
    class Transport(shim.AsyncBaseTransport):
        async def handle_async_request(self, request):
            assert request.method == "POST"
            return shim.Response(status, stream=Stream())
    client = proxy.QueueStoreClient(origin=ORIGIN, service_secret=SECRET,
        client_factory=lambda **options: shim.AsyncClient(transport=Transport(), **options))
    if status == 200 and expected is not None:
        assert asyncio.run(client.call("list_links")) == expected
    else:
        with pytest.raises(proxy.QueueUnavailable):
            asyncio.run(client.call("list_links"))


def test_unexpected_attribute_error_is_safe_and_classified(caplog):
    import logging
    class Broken:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def stream(self, *args, **kwargs): raise AttributeError(MARKER + SECRET)
    client = proxy.QueueStoreClient(origin=ORIGIN, service_secret=SECRET, client_factory=lambda **kw: Broken())
    with caplog.at_level(logging.WARNING, logger=proxy.__name__), pytest.raises(proxy.QueueUnavailable) as caught:
        asyncio.run(client.call("list_links"))
    assert "reason=unexpected_AttributeError" in caplog.text
    assert MARKER not in caplog.text and SECRET not in caplog.text
    assert MARKER not in str(caught.value) and SECRET not in str(caught.value)
