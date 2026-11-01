"""#5881 follow-on — the internal call is a door with a list of names on it.

The queue answers only the names it declared, only for a caller that proves the service
secret, and never repeats back what it was handed: an argument can name a customer's
path, and the store's own exception text is not ours to publish.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
import sqlite3
import sys
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.pc_device_pairing_store import D1PcPairingStore  # noqa: E402
from schema import apply  # noqa: E402
from internal_store import INTERNAL_STORE_PATH, QUEUE_SERVICE_SECRET_HEADER  # noqa: E402


def _load_queue_service():
    # Another suite may already have a top-level ``service`` module cached (the
    # broker owns one too), so this helper loads the queue's own file by path.
    spec = importlib.util.spec_from_file_location(
        "padiem_mesh_queue_service_under_test", QUEUE / "service.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


create_app = _load_queue_service().create_app

SECRET = "queue-channel-secret-value-261029"
SERVICE_SECRET = "queue-service-secret-value-261029"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node-ABC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state, wire, *, secret=SERVICE_SECRET):
        self.app = SimpleNamespace(state=state)
        body = b"{}" if wire is None else json.dumps(wire).encode("utf-8")
        self.headers = _Headers({"content-type": "application/json",
                                 "content-length": str(len(body))})
        if secret is not None:
            self.headers[QUEUE_SERVICE_SECRET_HEADER.lower()] = secret
        self._body = body

    async def body(self):
        return self._body


def _app(**kwargs):
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    kwargs.setdefault("service_secret", SERVICE_SECRET)
    return create_app(connection=connection, channel_secret=SECRET,
                      ownership_map=json.dumps(OWNERSHIP), mode="mesh", **kwargs)


def _handler(app):
    return next(route.endpoint for route in app.routes if route.path == INTERNAL_STORE_PATH)


def _call(app, wire, **kwargs):
    return asyncio.run(_handler(app)(_Request(app.state, wire, **kwargs)))


def _body(response):
    return json.loads(response.body.decode("utf-8"))


def test_an_undeclared_name_is_refused_before_anything_is_read():
    response = _call(_app(), {"method": "delete_everything", "arguments": {}})
    assert response.status_code == 400
    assert _body(response)["error"]["code"] == "queue_method_not_allowed"


def test_a_caller_without_the_service_secret_is_refused():
    app = _app()
    for secret in (None, "wrong-service-secret-value-0000"):
        response = _call(app, {"method": "list_links", "arguments": {"user_id": "u"}},
                         secret=secret)
        assert response.status_code == 403, secret
        assert _body(response)["error"]["code"] == "queue_channel_rejected"


def test_a_declared_name_runs_on_the_real_store_and_answers_with_its_result():
    app = _app()
    issued = _body(_call(app, {"method": "issue_code",
                               "arguments": {"user_id": "usr_" + "a" * 32,
                                             "issued_at": "2026-10-29T00:00:00.000Z"}}))
    assert issued["ok"] is True and issued["result"]["install_tag"]
    listed = _body(_call(app, {"method": "list_links", "arguments": {
        "user_id": "usr_" + "a" * 32}}))
    assert listed == {"ok": True, "result": []}


def test_a_store_failure_is_named_without_repeating_what_it_was_given():
    marker = "C:/Users/customer/private-file.txt"
    response = _call(_app(), {"method": "device_scope",
                              "arguments": {"device_id": marker, "unexpected": 1}})
    assert response.status_code == 502
    assert _body(response)["error"]["code"] == "queue_store_failed"
    assert marker not in response.body.decode("utf-8")


def test_the_door_is_not_even_open_without_a_service_secret_installed():
    app = _app(service_secret=None)
    assert not any(route.path == INTERNAL_STORE_PATH for route in app.routes)


def test_only_the_two_declared_keys_are_accepted():
    response = _call(_app(), {"method": "list_links", "arguments": {}, "extra": 1})
    assert response.status_code == 400
    assert _body(response)["error"]["code"] == "queue_invalid_body"


def test_pairing_store_is_reachable_through_the_same_object_the_executor_lane_uses():
    app = _app()
    assert isinstance(app.state.pc_device_pairing_store, D1PcPairingStore)
    links = asyncio.run(app.state.pc_device_pairing_store.list_links(
        user_id="usr_" + "a" * 32))
    assert links == []
