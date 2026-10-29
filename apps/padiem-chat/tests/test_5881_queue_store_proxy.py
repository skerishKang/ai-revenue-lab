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
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Call:
    """The transport the proxy module is tested through: it records, it answers."""

    def __init__(self, handler):
        self.handler = handler
        self.sent: list[dict[str, Any]] = []

    def __call__(self, *args, **kwargs):  # httpx.AsyncClient(...)
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.sent.append({"url": url, "json": json, "headers": dict(headers or {})})
        return self.handler(dict(self.sent[-1]))


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


def test_the_call_sends_the_declared_name_and_proves_the_service_secret():
    seen: dict[str, Any] = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["secret"] = request.headers.get(proxy.QUEUE_SERVICE_SECRET_HEADER)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": []})

    client, recorder = _client(lambda sent: _Response(200, {"ok": True, "result": []}))
    assert asyncio.run(client.call("list_links", user_id="usr_1")) == []
    sent = recorder.sent[0]
    seen["path"] = __import__("urllib.parse", fromlist=["x"]).urlparse(sent["url"]).path
    seen["secret"] = sent["headers"][proxy.QUEUE_SERVICE_SECRET_HEADER]
    seen["body"] = sent["json"]
    assert seen["path"] == proxy.INTERNAL_STORE_PATH
    assert seen["secret"] == SECRET
    assert seen["body"] == {"method": "list_links", "arguments": {"user_id": "usr_1"}}


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
