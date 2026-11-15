"""#7644 — 큐 기반 저장소도 토큰 확인을 활성 연결에서만 건너뛴다.

운영의 연결 저장소는 큐 기반(QueuePcAccountDataStore — D1PcPairingStore를
상속, 큐 DB의 실제 SQL 위에서 동작)이다. SQL 저장소만 고치고 큐 쪽 판정이
따라오는지 놓치면 안 되므로, 이 모듈은 같은 네 결과를 큐 쪽에서도 단언한다:

* 활성 행 → 토큰 확인 생략(200, 지금과 같음)
* 확인 대기 행 + 취소된 토큰 → 거절(502), 코드는 소비되지 않는다
* 해제됨 행 + 만료된 토큰 → 거절(502)
* 확인 대기·해제됨 행 + 유효한 토큰 → 진행(200)

큐의 실제 스키마(schema.apply)와 내부 RPC 경로(internal store handler)를 그대로
쓴다. RPC는 저장소 거절 이유를 숨기므로(502 queue_store_failed) 이유 문자열
단언은 SQL 저장소 시험(apps/padiem-chat/tests/test_7644_pairing_token_gate_link_state.py)이
담당하고, 여기서는 상태 코드와 행 상태 변화로 판정을 고정한다.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

QUEUE = Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from app.pc_device_pairing_store import derive_install_tag  # noqa: E402
from internal_store import (                                 # noqa: E402
    INTERNAL_STORE_PATH,
    QUEUE_SERVICE_SECRET_HEADER,
)
from schema import apply                                     # noqa: E402


def _load_queue_service():
    """Load apps/padiem-mesh-queue/service.py by path, never by bare name.

    A full pytest run may already hold a different top-level ``service`` module
    in ``sys.modules``; the unique name mirrors the loader the other mesh-queue
    checks use for schema.py and internal_store.py.
    """
    name = "mesh_queue_service_7644_token_gate"
    module = sys.modules.get(name)
    if module is not None:
        return module
    spec = spec_from_file_location(name, QUEUE / "service.py")
    module = module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


create_app = _load_queue_service().create_app

SECRET = "internal-store-service-secret-7644"
CHANNEL = "mesh-queue-channel-secret-7644-x"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node-ABC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]

OWNER = "usr_" + "a" * 32
NODE = "node//mesh-queue-pc-01"


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    """The header/body surface the queue's internal handler reads."""

    def __init__(self, state, wire):
        self.app = SimpleNamespace(state=state)
        body = b"{}" if wire is None else json.dumps(wire).encode("utf-8")
        self.headers = _Headers({"content-type": "application/json",
                                 "content-length": str(len(body)),
                                 QUEUE_SERVICE_SECRET_HEADER.lower(): SECRET})
        self._body = body

    async def body(self):
        return self._body


def _queue():
    """One queue database (real schema SQL) plus the real service app."""
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    app = create_app(connection=connection, channel_secret=CHANNEL, mode="mesh",
                     ownership_map=json.dumps(OWNERSHIP), service_secret=SECRET)
    return connection, app


def _handler(app):
    return next(route.endpoint for route in app.routes if route.path == INTERNAL_STORE_PATH)


def _call(app, wire):
    return asyncio.run(_handler(app)(_Request(app.state, wire)))


def _body(response):
    return json.loads(response.body.decode("utf-8"))


def _rpc(app, method, **arguments):
    return _body(_call(app, {"method": method, "arguments": arguments}))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _issue(connection, app) -> dict:
    issued = _rpc(app, "issue_code", user_id=OWNER, issued_at=_iso(_now()))
    assert issued["ok"] is True
    return issued["result"]


def _now() -> datetime:
    """한 시험 안의 모든 시각이 이 순간에 고정된다(현재 시각 한 번만 읽는다)."""
    return datetime.now(timezone.utc)


def _seed_link(connection, state: str) -> None:
    stamped = _iso(_now())
    connection.execute(
        "INSERT INTO pc_device_links "
        "(link_id, user_id, mesh_node_id, label, state, roots_json, "
        " pairing_code_id, created_at, updated_at, revoked_at) "
        "VALUES (?, ?, ?, NULL, ?, '[]', NULL, ?, ?, ?)",
        ("pclink_" + "2" * 32, OWNER, NODE, state, stamped, stamped,
         stamped if state == "revoked" else None),
    )


def _link_state(connection) -> str:
    return connection.execute(
        "SELECT state FROM pc_device_links WHERE user_id=? AND mesh_node_id=?",
        (OWNER, NODE),
    ).fetchone()[0]


def _code_state(connection, code_id: str) -> str:
    return connection.execute(
        "SELECT state FROM pc_pairing_codes WHERE code_id=?", (code_id,)
    ).fetchone()[0]


def _revoke_token(connection, code_id: str) -> None:
    connection.execute(
        "UPDATE pc_install_tokens SET revoked_at=? WHERE code_id=?",
        (_iso(_now()), code_id),
    )


def _expire_token(connection, code_id: str) -> None:
    # CHECK(expires_at > issued_at)를 지키도록 발행 시각도 함께 과거로 밀는다.
    connection.execute(
        "UPDATE pc_install_tokens SET issued_at=?, expires_at=? WHERE code_id=?",
        (_iso(_now() - timedelta(minutes=30)),
         _iso(_now() - timedelta(minutes=1)), code_id),
    )


def _observed_name(tag: str, token: str | None = None) -> str:
    parts = ["PADIEM", tag]
    if token is not None:
        parts.append(token)
    parts.append("beta-notebook")
    return " ".join(parts)


def _redeem(app, issued, *, install_token=None):
    return _call(app, {"method": "redeem_code", "arguments": {
        "code": issued["code"], "mesh_node_id": NODE, "label": None,
        "now": _iso(_now()), "verified": True, "install_token": install_token,
    }})


def _observe(app, issued, *, token=None):
    name = _observed_name(derive_install_tag(issued["code"]), token)
    return _call(app, {"method": "complete_claim_from_observation", "arguments": {
        "agent_name": name, "mesh_node_id": NODE, "now": _iso(_now()),
    }})


# -- 1. 활성 행은 지금과 같이 토큰 확인을 건너뛴다 ------------------------------

def test_queue_redeem_on_an_active_link_still_skips_the_token_check():
    connection, app = _queue()
    _seed_link(connection, "active")
    issued = _issue(connection, app)
    _revoke_token(connection, issued["code_id"])

    response = _redeem(app, issued, install_token=issued["install_token"])
    assert response.status_code == 200
    assert _body(response)["result"]["state"] == "active"
    assert _code_state(connection, issued["code_id"]) == "claimed"


def test_queue_observation_on_an_active_link_still_skips_the_token_check():
    connection, app = _queue()
    _seed_link(connection, "active")
    issued = _issue(connection, app)
    _revoke_token(connection, issued["code_id"])

    response = _observe(app, issued)
    assert response.status_code == 200
    assert _body(response)["result"]["state"] == "active"
    assert _code_state(connection, issued["code_id"]) == "claimed"


# -- 2. 확인 대기 행 + 취소된 토큰 → 거절 --------------------------------------

def test_queue_redeem_on_a_pending_link_with_a_revoked_token_is_refused():
    connection, app = _queue()
    _seed_link(connection, "pending_verification")
    issued = _issue(connection, app)
    _revoke_token(connection, issued["code_id"])

    response = _redeem(app, issued)
    assert response.status_code == 502
    assert _body(response)["error"]["code"] == "queue_store_failed"
    assert _code_state(connection, issued["code_id"]) == "pending"
    assert _link_state(connection) == "pending_verification"


def test_queue_observation_on_a_pending_link_with_a_revoked_token_is_refused():
    connection, app = _queue()
    _seed_link(connection, "pending_verification")
    issued = _issue(connection, app)
    _revoke_token(connection, issued["code_id"])

    response = _observe(app, issued)
    assert response.status_code == 502
    assert _code_state(connection, issued["code_id"]) == "pending"
    assert _link_state(connection) == "pending_verification"


# -- 3. 해제됨 행 + 만료된 토큰 → 거절 ----------------------------------------

def test_queue_redeem_on_a_revoked_link_with_an_expired_token_is_refused():
    connection, app = _queue()
    _seed_link(connection, "revoked")
    issued = _issue(connection, app)
    _expire_token(connection, issued["code_id"])

    response = _redeem(app, issued)
    assert response.status_code == 502
    assert _code_state(connection, issued["code_id"]) == "pending"
    assert _link_state(connection) == "revoked"


def test_queue_observation_on_a_revoked_link_with_an_expired_token_is_refused():
    connection, app = _queue()
    _seed_link(connection, "revoked")
    issued = _issue(connection, app)
    _expire_token(connection, issued["code_id"])

    response = _observe(app, issued)
    assert response.status_code == 502
    assert _code_state(connection, issued["code_id"]) == "pending"
    assert _link_state(connection) == "revoked"


# -- 4. 확인 대기·해제됨 행 + 유효한 토큰 → 진행 -------------------------------

def test_queue_redeem_on_a_pending_link_with_a_valid_token_proceeds():
    connection, app = _queue()
    _seed_link(connection, "pending_verification")
    issued = _issue(connection, app)

    response = _redeem(app, issued, install_token=issued["install_token"])
    assert response.status_code == 200
    assert _body(response)["result"]["state"] == "active"
    assert _code_state(connection, issued["code_id"]) == "claimed"


def test_queue_redeem_on_a_revoked_link_with_a_valid_token_proceeds():
    connection, app = _queue()
    _seed_link(connection, "revoked")
    issued = _issue(connection, app)

    response = _redeem(app, issued, install_token=issued["install_token"])
    assert response.status_code == 200
    result = _body(response)["result"]
    assert result["state"] == "active"
    # 해제 후 재연결은 새 부여다: 폴더·드라이브는 돌아오지 않는다.
    assert result["roots"] == []
    assert _code_state(connection, issued["code_id"]) == "claimed"


def test_queue_observation_on_a_pending_link_with_a_valid_token_proceeds():
    connection, app = _queue()
    _seed_link(connection, "pending_verification")
    issued = _issue(connection, app)

    response = _observe(app, issued, token=issued["install_token"])
    assert response.status_code == 200
    assert _body(response)["result"]["state"] == "active"
    assert _code_state(connection, issued["code_id"]) == "claimed"


def test_queue_observation_on_a_revoked_link_with_a_valid_token_proceeds():
    connection, app = _queue()
    _seed_link(connection, "revoked")
    issued = _issue(connection, app)

    response = _observe(app, issued, token=issued["install_token"])
    assert response.status_code == 200
    result = _body(response)["result"]
    assert result["state"] == "active"
    assert result["roots"] == []
    assert _code_state(connection, issued["code_id"]) == "claimed"
