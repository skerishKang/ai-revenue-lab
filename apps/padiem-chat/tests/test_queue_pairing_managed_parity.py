"""관리 PC 표식이 프록시 경로에서 실제로 동작한다(#7109 후속 500 해소).

운영 실측(2026-11-08 13:10): POST /api/pc/devices/{link_id}/managed → 500 —
queue_store_proxy.py:365의 허용 목록과 mesh-queue internal_store.py:74의
스토어 서버 허용 목록에 #7147/#7153의 세 메서드가 없었다. 시험은 D1 store를
직접 써서 프록시 경로를 지나지 않았다.

이 계약은 세 조각이 하나임을 고정한다:
- PcPairingStore Protocol의 모든 공개 메서드가 프록시 허용 목록에 등록
- 같은 이름이 스토어 서버 허용 목록(mesh-queue internal_store)에도 등록
- set_managed의 now(datetime)가 경계에서 ISO로 오가는 직렬화
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
QUEUE = ROOT / "apps" / "padiem-mesh-queue"
CHAT = ROOT / "apps" / "padiem-chat"

sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.pc_device_pairing_store import PcPairingStore  # noqa: E402
from app.queue_store_proxy import (  # noqa: E402
    QUEUE_PAIRING_METHODS,
    QueueBackedPairingStore,
    QueueStoreClient,
)


def _store_server_methods() -> frozenset:
    spec = importlib.util.spec_from_file_location(
        "mq_internal_store", QUEUE / "internal_store.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PAIRING_METHODS


def test_every_protocol_method_is_registered_on_both_sides():
    """Protocol의 모든 공개 메서드가 프록시·스토어 서버 양쪽 허용 목록에 있다."""
    protocol_methods = {
        name for name, value in vars(PcPairingStore).items()
        if callable(value) and not name.startswith("_")
    }
    assert protocol_methods <= QUEUE_PAIRING_METHODS, (
        "the Protocol gained a method the queue proxy does not route"
    )
    assert protocol_methods <= _store_server_methods(), (
        "the Protocol gained a method the store server does not route"
    )


def _db():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    schema_spec = importlib.util.spec_from_file_location(
        "mq_schema", QUEUE / "schema.py")
    schema = importlib.util.module_from_spec(schema_spec)
    schema_spec.loader.exec_module(schema)
    schema.apply(connection)
    return connection


def _queue_service():
    """Load apps/padiem-mesh-queue/service.py by path, never by bare name.

    A full pytest run already holds a different top-level ``service`` module in
    ``sys.modules`` (apps/padiem-broker/service.py is imported the same way by
    test_broker_loopback_v2_roundtrip_261031, and the chat suite has its own
    ``service`` historical entry points). ``import service`` then returned the
    wrong module and these two tests died with AttributeError: module 'service'
    has no attribute 'create_app'. The unique name mirrors the loader the other
    mesh-queue parity checks use for schema.py and internal_store.py.
    """
    name = "mesh_queue_service_managed_parity"
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(name, QUEUE / "service.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _queue_app(database):
    return _queue_service().create_app(
        connection=database, channel_secret=SECRET, mode="mesh",
        ownership_map=json.dumps([{"account_ref": "acct-1", "device_id": "device-1",
                                   "node_ref": "node//NEWPC", "root_ref": "C:",
                                   "path_relative": "p.txt", "file_path": "C:/p.txt",
                                   "command_exec": True}]),
        service_secret=SECRET)


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _FakeRequest:
    """The header/body surface the queue's internal handler reads."""

    def __init__(self, headers, payload):
        body = json.dumps(payload).encode("utf-8")
        merged = {str(k).lower(): v for k, v in (headers or {}).items()}
        merged.setdefault("content-type", "application/json")
        merged.setdefault("content-length", str(len(body)))
        self.headers = _Headers(merged)
        self._body = body
        self.app = SimpleNamespace(state=None)

    async def body(self):
        return self._body


class _FakeResponse:
    """The stream surface the queue client reads: status + aiter_bytes."""

    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    async def aiter_bytes(self):
        yield self._body


def _client(queue_app):
    handler = next(route.endpoint for route in queue_app.routes
                   if getattr(route, "path", "") == "/internal/store")

    class _Bridge:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def stream(self, method, url, json=None, headers=None):
            assert method == "POST"

            class Context:
                async def __aenter__(self):
                    response = await handler(_FakeRequest(headers, json))
                    if response.status_code != 200:
                        print("SERVER refusal:", response.status_code,
                              response.body.decode("utf-8", "replace")[:200])
                    return _FakeResponse(response.status_code, response.body)

                async def __aexit__(self, *exc):
                    return False
            return Context()
    return QueueStoreClient(origin="https://queue.padiem.net", service_secret=SECRET,
                            client_factory=lambda **kw: _Bridge(**kw))


USER = "usr_" + "a" * 32
NODE = "node//NEWPC"
SECRET = "queue-service-secret-value-261029"


async def _managed_flow(pairing):
    issued = await pairing.issue_code(user_id=USER, issued_at=NOW)
    await pairing.complete_claim_from_observation(
        agent_name="%s [C D] CGI-9" % issued["install_tag"],
        mesh_node_id=NODE, now=NOW)
    links = await pairing.list_links(user_id=USER)
    link_id = links[0]["link_id"]
    marked = await pairing.set_managed(link_id=link_id, by_user_id=USER,
                                       managed=True, now=NOW)
    state = await pairing.managed_state(link_id=link_id)
    gate = await pairing.is_managed_link(user_id=USER, mesh_node_id=NODE)
    inventory = await pairing.list_active_device_ids()
    return {"marked": marked["managed"], "state": state["managed"], "gate": gate,
            "inventory": inventory}


from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = datetime.now(timezone.utc)


def test_the_managed_mark_round_trips_through_the_proxy_path(tmp_path):
    """set_managed → managed_state → is_managed_link 왕복이 프록시 경로에서 성공."""
    database = _db()
    queue_app = _queue_app(database)
    pairing = QueueBackedPairingStore(_client(queue_app))
    result = asyncio.run(_managed_flow(pairing))
    assert result == {"marked": True, "state": True, "gate": True,
                      "inventory": [NODE]}


def test_the_system_gate_accepts_a_managed_link_through_the_proxy(tmp_path, monkeypatch):
    """mcp_gateway_execution의 SYSTEM 판정이 프록시 경로로 true를 받는다."""
    from app import mcp_gateway_execution
    from app.platform_admin_authority import PlatformAdminAuthority

    class _Roles:
        async def role_for(self, user_id):
            return "ADMIN"

    database = _db()
    queue_app = _queue_app(database)
    pairing = QueueBackedPairingStore(_client(queue_app))
    asyncio.run(_managed_flow(pairing))

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        platform_admin_authority=PlatformAdminAuthority(
            role_store=_Roles(), legacy_model_admin=None, legacy_b66_admin=None),
        pc_device_pairing_store=pairing,
    )))

    async def drive():
        return await mcp_gateway_execution._pc_system_mode_allowed(
            request, uid=USER, device_id=NODE)

    assert asyncio.run(drive()) is True
