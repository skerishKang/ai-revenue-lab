"""#6695 PR-2 — presence·장치 목록은 로그인한 계정의 소유 장치만 다룬다.

격리 설계(비공개 운영 기록(거버넌스 폴더, 같은 상대 경로), PC_MESH_TENANT_ISOLATION_20261102.md)의
PR-2 계약을 고정한다:

(A) presence 영수증이 기록되는 순간 소유 계정 목록을 함께 저장한다 — 디렉터리가
    답한 account_refs(legacy 맵 행이면 단일 ref)가 행 자체에 남아, 이후 조회가
    읽기 시점의 규율만으로 소유를 다시 유추하지 않는다.
(B) 노드 전역 조회(`drive_roots_for_node`)는 소유자 검증 없이는 답하지 않는다 —
    계정을 대신해 부르는 호출자는 반드시 자기 id를 넘기고, 같은 기기를 다른
    소유자가 링크했어도 그 드라이브 배치는 건너오지 않는다.
(C) 어떤 계정의 장치 존재·이름·온라인 여부도 다른 계정의 응답·로그에 나오지
    않는다 — 페어링 목록과 장치 디렉터리가 소유 링크로만 좁혀지는 것을 응답과
    로그 양쪽에서 단언한다. 채택(adopt)은 관리자 검증이 장치 읽기보다 먼저다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import claw_device_directory_routes as directory_routes
from app.mesh_device_presence_store import (
    D1MeshDevicePresenceStore,
    MeshDevicePresenceStoreError,
)
from app.pc_device_pairing_routes import PC_PAIRING_ADOPT_PATH, PC_PAIRING_PATH
from app.pc_device_pairing_store import D1PcPairingStore

import test_5553_mesh_online_projection_261024 as existing

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
NODE_OWNERS = "node/meshdomain/owner-pc-AAAA"
NODE_OTHERS = "node/meshdomain/other-pc-BBBB"
SESSION_SECRET = "phase11-pc-6695-pr2-session-secret-not-a-real-key-0000"
ORIGIN = "https://chat.example.test"
NOW = datetime.now(timezone.utc)


class D1Statement:
    def __init__(self, conn: sqlite3.Connection, query: str) -> None:
        self.conn = conn
        self.query = query
        self.args: tuple = ()

    def bind(self, *args):
        self.args = args
        return self

    async def run(self):
        cursor = self.conn.execute(self.query, self.args)
        return {"results": [dict(row) for row in cursor.fetchall()]}

    async def first(self):
        row = self.conn.execute(self.query, self.args).fetchone()
        return dict(row) if row is not None else None


class RealSQLiteD1:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def prepare(self, query: str) -> D1Statement:
        return D1Statement(self.conn, query)


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    return conn


def run(coro):
    return asyncio.run(coro)


def pairing_store(conn: sqlite3.Connection) -> D1PcPairingStore:
    return D1PcPairingStore(RealSQLiteD1(conn))


def presence_store(conn: sqlite3.Connection) -> D1MeshDevicePresenceStore:
    return D1MeshDevicePresenceStore(RealSQLiteD1(conn))


def _link(conn: sqlite3.Connection, *, user_id: str, node: str, drive: str) -> None:
    run(pairing_store(conn).adopt_link(
        user_id=user_id, mesh_node_id=node, root_paths=[], now=NOW, drives=[drive],
    ))


# -- (A) the presence receipt is owner-attributed at record time -------------

def test_the_row_round_trips_the_owner_accounts() -> None:
    store = presence_store(database())
    assert run(store.upsert(
        device_id="pc@mesh+1", connected=True, received_at=NOW,
        credential_generation=None, source="mesh", account_refs=[OWNER, OTHER],
    )) is True
    row = run(store.load("pc@mesh+1"))
    assert row["account_refs"] == [OWNER, OTHER]
    # A beat without an owner list keeps the pre-PR-2 row shape exactly.
    assert run(store.upsert(
        device_id="pc@mesh+2", connected=False, received_at=NOW,
        credential_generation=None, source="mesh",
    )) is True
    assert run(store.load("pc@mesh+2"))["account_refs"] is None


@pytest.mark.parametrize("bad", [
    [], ["", OWNER], [OWNER] * 9, [OWNER, 7], [None], ["x" * 321],
])
def test_malformed_owner_lists_refuse_instead_of_partial_writes(bad) -> None:
    store = presence_store(database())
    with pytest.raises(MeshDevicePresenceStoreError):
        run(store.upsert(
            device_id="pc@mesh+1", connected=True, received_at=NOW,
            credential_generation=None, source="mesh", account_refs=bad,
        ))
    assert run(store.load("pc@mesh+1")) is None


def test_a_poll_beat_records_the_map_rows_single_owner() -> None:
    store = presence_store(database())
    state = existing._poll_state(store)
    state.mesh_presence_generation_resolver = None
    code, body = existing._poll(state, {"presence": [
        {"device_id": existing.NODE_ID, "connected": True},
    ]})
    assert code == 200 and body == {"ok": True, "dispatch": None}
    row = run(store.load(existing.DEVICE_ID))
    assert row["account_refs"] == ["acct_5553"]


def test_a_poll_beat_records_every_account_the_directory_answers() -> None:
    store = presence_store(database())

    class _DirectoryPairing:
        async def device_scope(self, *, device_id: str):
            # The real directory answers with the canonical device identity.
            return {"device_id": existing.DEVICE_ID, "account_refs": [OWNER, OTHER]}

    state = existing._poll_state(store)
    state.mesh_presence_generation_resolver = None
    state.pc_device_pairing_store = _DirectoryPairing()
    code, _ = existing._poll(state, {"presence": [
        {"device_id": existing.NODE_ID, "connected": True},
    ]})
    assert code == 200
    row = run(store.load(existing.DEVICE_ID))
    assert row["account_refs"] == [OWNER, OTHER]


# -- (B) the node-global drive lookup answers owner-scoped when asked --------

def test_drive_roots_for_node_stays_global_only_for_the_admin_call() -> None:
    conn = database()
    _link(conn, user_id=OWNER, node=NODE_OWNERS, drive="C:\\")
    _link(conn, user_id=OTHER, node=NODE_OWNERS, drive="D:\\")
    store = pairing_store(conn)
    # The admin adopt path reads the machine's drives from every link.
    assert run(store.drive_roots_for_node(mesh_node_id=NODE_OWNERS)) == ["C:", "D:"]
    # A caller for one account never learns the other owner's drive layout.
    assert run(store.drive_roots_for_node(
        mesh_node_id=NODE_OWNERS, owner_user_id=OWNER)) == ["C:"]
    assert run(store.drive_roots_for_node(
        mesh_node_id=NODE_OWNERS, owner_user_id=OTHER)) == ["D:"]
    # An owner with no link on this machine reads nothing, not the machine.
    stranger = "usr_" + "c" * 32
    assert run(store.drive_roots_for_node(
        mesh_node_id=NODE_OWNERS, owner_user_id=stranger)) == []


# -- (C) another account's device never appears in a response or a log -------

def _app_with(conn: sqlite3.Connection):
    from app.app_factory import create_app
    from app.config import Settings

    app = create_app(Settings(
        runtime_mode="mock",
        session_secret=SESSION_SECRET,
        public_base_url=ORIGIN,
    ))
    app.state.pc_device_pairing_store = pairing_store(conn)
    app.state.mesh_device_presence_store = presence_store(conn)
    return app


def _client(app, *, user_id: str):
    from app.auth import SESSION_COOKIE, create_session_token

    token = create_session_token(
        app.state.settings, user_id, now=int(NOW.timestamp()),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
        cookies={SESSION_COOKIE: token},
    )


def test_the_pairing_list_shows_only_the_callers_own_devices(caplog) -> None:
    conn = database()
    _link(conn, user_id=OWNER, node=NODE_OWNERS, drive="C:\\")
    _link(conn, user_id=OTHER, node=NODE_OTHERS, drive="C:\\")
    # The other account's PC is connected right now — its liveness is exactly
    # what must not leak into this account's list.
    run(presence_store(conn).upsert(
        device_id=NODE_OTHERS, connected=True, received_at=NOW,
        credential_generation=None, source="mesh", account_refs=[OTHER],
    ))
    app = _app_with(conn)
    with caplog.at_level(logging.DEBUG):
        response = asyncio.run(_client(app, user_id=OWNER).get(PC_PAIRING_PATH))
    assert response.status_code == 200
    links = response.json()["links"]
    assert [link["mesh_node_id"] for link in links] == [NODE_OWNERS]
    assert all(link.get("label") != "다른자료" for link in links)
    assert NODE_OTHERS not in caplog.text
    assert "다른자료" not in caplog.text


def test_the_device_directory_never_names_another_accounts_device(caplog) -> None:
    conn = database()
    _link(conn, user_id=OWNER, node=NODE_OWNERS, drive="C:\\")
    _link(conn, user_id=OTHER, node=NODE_OTHERS, drive="C:\\")
    presence = presence_store(conn)
    # The other account's PC is online by the same receipt the owner's list
    # reads; the directory must still not show it to this account.
    run(presence.upsert(
        device_id=NODE_OTHERS, connected=True, received_at=NOW,
        credential_generation=None, source="mesh", account_refs=[OTHER],
    ))
    app = _app_with(conn)
    request = SimpleNamespace(app=app)
    with caplog.at_level(logging.DEBUG):
        response = asyncio.run(directory_routes._read_device_directory(
            request, uid=OWNER, workspace_id="owner:" + OWNER,
        ))
    body = json.loads(response.body)
    assert body["ok"] is True
    devices = body.get("devices", [])
    ids = [row["deviceId"] for row in devices]
    assert NODE_OWNERS in ids, ids
    assert NODE_OTHERS not in ids, ids
    assert all(row.get("deviceId") != NODE_OTHERS for row in devices)
    assert NODE_OTHERS not in caplog.text
    assert "다른자료" not in caplog.text


def test_an_adopt_refusal_reads_no_device_store_at_all() -> None:
    conn = database()
    _link(conn, user_id=OTHER, node=NODE_OTHERS, drive="C:\\")
    app = _app_with(conn)
    store = app.state.pc_device_pairing_store
    presence = app.state.mesh_device_presence_store
    pairing_reads = {"roots": 0}
    presence_reads = {"load": 0}

    original_roots = store.drive_roots_for_node

    async def counting_roots(**arguments):
        pairing_reads["roots"] += 1
        return await original_roots(**arguments)

    original_load = presence.load

    async def counting_load(**arguments):
        presence_reads["load"] += 1
        return await original_load(**arguments)

    store.drive_roots_for_node = counting_roots
    presence.load = counting_load
    response = asyncio.run(_client(app, user_id=OWNER).post(
        PC_PAIRING_ADOPT_PATH, json={"device_id": NODE_OTHERS},
    ))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "pc_pairing_not_admin"
    # The guard runs before anything is read: a refused caller learns nothing
    # about which devices exist — not even that the device id answers.
    assert pairing_reads == {"roots": 0}
    assert presence_reads == {"load": 0}
