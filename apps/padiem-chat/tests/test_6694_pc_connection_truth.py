"""#6694 — the PC list tells the truth about which computer is connected.

Three defects measured on 2026-11-02 in Chat's "내 컴퓨터" surface:

(A) the list and its status chip said "연결됨" from the pairing record's
    `state`, which stays `active` forever - a PC whose Mesh agent was removed
    still read as connected. The list now carries MeshCentral's own node
    connectivity (`online`, `last_seen_at`) from the existing server-recorded
    presence receipt, and the surfaces say 오프라인 when the agent is not
    connected.
(B) the machine's own name was cut to the 15-character NetBIOS form
    (`PADIEM-COMMAND-` instead of `PADIEM-COMMAND-CENTER`) because both install
    lanes read `Environment.MachineName` / `$env:COMPUTERNAME`. They now report
    the whole DNS host name, so a link is named with the computer's full name.
(C) a re-installed agent arrives under a new Mesh node id and left the old
    `pc_device_links` row alive beside the new one: one computer, two lines.
    A fresh claim now marks the owner's older link for the same Windows
    computer name as `replaced` - never deleted.
"""
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.app_factory import create_app
from app.config import Settings
from app.mesh_device_presence_store import D1MeshDevicePresenceStore
from app.pc_device_pairing_routes import PC_PAIRING_PATH, render_install_script
from app.pc_device_pairing_store import (
    D1PcPairingStore,
    label_machine_key,
    machine_key,
    pc_name_from_agent_name,
)

sys.path.insert(0, str(Path(__file__).parent))

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
OLD_NODE = "node/meshdomain/old-node-AAAA"
NEW_NODE = "node/meshdomain/new-node-BBBB"
SESSION_SECRET = "phase11-pc-6694-session-secret-not-a-real-key-000000000000"
ORIGIN = "https://chat.example.test"
FULL_NAME = "PADIEM-COMMAND-CENTER"
NETBIOS_NAME = "PADIEM-COMMAND-"


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    for path in sorted(MIGRATIONS.glob("*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    return conn


def pairing_store(conn: sqlite3.Connection) -> D1PcPairingStore:
    return D1PcPairingStore(RealSQLiteD1(conn))


def run(coro):
    return asyncio.run(coro)


def app_with(pairing, presence=None):
    app = create_app(Settings(
        runtime_mode="mock",
        session_secret=SESSION_SECRET,
        public_base_url=ORIGIN,
    ))
    app.state.pc_device_pairing_store = pairing
    app.state.mesh_device_presence_store = presence
    return app


def client(app, *, user_id: str = OWNER):
    token = create_session_token(
        app.state.settings, user_id, now=int(_now().timestamp()),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN},
        cookies={SESSION_COOKIE: token},
    )


# -- the sameness criterion: one Windows computer name ----------------------

def test_the_netbios_fold_is_what_makes_two_names_one_computer() -> None:
    # The measured pair from 2026-11-02: the whole DNS name and the 15-character
    # form Windows keeps. Both name the same physical machine.
    assert machine_key(FULL_NAME) == machine_key(NETBIOS_NAME) == "PADIEM-COMMAND-"
    assert machine_key("padiem-command-center") == machine_key(NETBIOS_NAME)
    # Different machines stay different.
    assert machine_key("DESKTOP-7Q41B2X") != machine_key(NETBIOS_NAME)
    # An owner's alias is not a computer name and decides nothing.
    for alias in ("집 PC", "office laptop", "", None, "  ", "집-PC-작업용"):
        assert machine_key(alias) is None, alias
    # A label carries the machine name first, then the owner's alias.
    assert label_machine_key(FULL_NAME + " · 컴1") == "PADIEM-COMMAND-"
    assert label_machine_key("컴1") is None


def test_the_observed_machine_name_is_kept_whole() -> None:
    # #6694 (B): the full Windows name must survive the decoration removal. The
    # 15-character form is what the old lanes produced, and it is still read as
    # the name it is - it is just no longer what a fresh install produces.
    assert pc_name_from_agent_name(
        "pd-30780019 [C D E G] " + FULL_NAME) == FULL_NAME
    assert pc_name_from_agent_name("pd-30780019 " + NETBIOS_NAME) == NETBIOS_NAME


# -- (C) a new link for the same computer replaces the older record ---------

def _old_link(pairing, *, label: str, node: str = OLD_NODE, owner: str = OWNER):
    issued = run(pairing.issue_code(user_id=owner, issued_at=_now()))
    return run(pairing.redeem_code(
        code=issued["code"], mesh_node_id=node, label=label, now=_now(),
        verified=True, drives=["C:"],
    ))


def _new_observation_claim(pairing, *, agent_name: str, node: str = NEW_NODE):
    issued = run(pairing.issue_code(user_id=OWNER, issued_at=_now()))
    return run(pairing.complete_claim_from_observation(
        agent_name="%s [C D] %s" % (issued["install_tag"], agent_name),
        mesh_node_id=node, now=_now(),
    ))


def test_a_reinstall_under_a_new_node_id_leaves_one_line() -> None:
    conn = database()
    pairing = pairing_store(conn)
    old = _old_link(pairing, label=FULL_NAME + " · 컴1")
    new = _new_observation_claim(pairing, agent_name=FULL_NAME)

    links = run(pairing.list_links(user_id=OWNER))
    by_id = {link["link_id"]: link for link in links}
    assert len(links) == 2  # the record is kept, not deleted
    assert by_id[old["link_id"]]["state"] == "replaced"
    assert by_id[old["link_id"]]["superseded_at"]
    assert by_id[new["link_id"]]["state"] == "active"
    assert by_id[new["link_id"]]["label"] == FULL_NAME
    # The replaced record grants nothing: every authority read answers with the
    # one live link only.
    assert [row["link_id"] for row in run(pairing.links_for_owner(user_id=OWNER))] \
        == [new["link_id"]]
    assert run(pairing.link_for(user_id=OWNER, mesh_node_id=OLD_NODE)) is None
    assert run(pairing.device_scope(device_id=OLD_NODE)) is None


def test_the_truncated_old_name_is_also_recognised_as_the_same_computer() -> None:
    # The measured ghost was registered as the 15-character name; a fresh
    # install now reports the whole name. They are one computer.
    conn = database()
    pairing = pairing_store(conn)
    old = _old_link(pairing, label=NETBIOS_NAME)
    new = _new_observation_claim(pairing, agent_name=FULL_NAME)
    links = {link["link_id"]: link for link in run(pairing.list_links(user_id=OWNER))}
    assert links[old["link_id"]]["state"] == "replaced"
    assert links[new["link_id"]]["state"] == "active"


def test_another_accounts_link_on_the_same_computer_is_untouched() -> None:
    conn = database()
    pairing = pairing_store(conn)
    theirs = _old_link(pairing, label=FULL_NAME + " · 회사", owner=OTHER)
    await_ = _new_observation_claim(pairing, agent_name=FULL_NAME)
    assert await_["state"] == "active"
    still_theirs = run(pairing.list_links(user_id=OTHER))
    assert [row["link_id"] for row in still_theirs] == [theirs["link_id"]]
    assert still_theirs[0]["state"] == "active"
    assert run(pairing.link_for(user_id=OTHER, mesh_node_id=OLD_NODE)) is not None


def test_an_alias_only_label_never_decides_two_pcs_are_one() -> None:
    conn = database()
    pairing = pairing_store(conn)
    old = _old_link(pairing, label="집 작업용 PC")
    new = _new_observation_claim(pairing, agent_name=FULL_NAME)
    links = {link["link_id"]: link for link in run(pairing.list_links(user_id=OWNER))}
    # Nothing proved they are the same machine, so both stay live records.
    assert links[old["link_id"]]["state"] == "active"
    assert links[new["link_id"]]["state"] == "active"


def test_a_revoke_then_reclaim_of_the_same_node_is_live_again() -> None:
    conn = database()
    pairing = pairing_store(conn)
    old = _old_link(pairing, label=FULL_NAME)
    _new_observation_claim(pairing, agent_name=FULL_NAME)
    # Re-pairing the old node after the newer link was revoked must not carry a
    # stale supersede stamp into a live row.
    issued = run(pairing.issue_code(user_id=OWNER, issued_at=_now()))
    refreshed = run(pairing.redeem_code(
        code=issued["code"], mesh_node_id=OLD_NODE, label=FULL_NAME, now=_now(),
        verified=True,
    ))
    assert refreshed["link_id"] == old["link_id"]
    assert refreshed["state"] == "active"
    assert refreshed["superseded_at"] is None
    links = {link["link_id"]: link for link in run(pairing.list_links(user_id=OWNER))}
    assert links[old["link_id"]]["state"] == "active"


# -- (A) the list carries the node's real connectivity ---------------------

class FakePresence:
    def __init__(self, rows: dict[str, dict | None]) -> None:
        self.rows = rows
        self.reads: list[str] = []

    async def load(self, device_id: str):
        self.reads.append(device_id)
        return self.rows.get(device_id)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _receipt(*, device_id: str, connected: bool, received_at: datetime,
             last_connected_at: datetime | None = None):
    return {
        "device_id": device_id,
        "connected": connected,
        "received_at": _stamp(received_at),
        "last_connected_at": _stamp(last_connected_at) if last_connected_at else None,
        "credential_generation": None,
        "source": "mesh",
    }


def _listed(pairing, presence):
    async def journey():
        app = app_with(pairing, presence)
        async with client(app) as session:
            response = await session.get(PC_PAIRING_PATH)
            assert response.status_code == 200, response.text
            return response.json()

    return run(journey())


def test_the_list_says_offline_when_the_agent_is_not_connected() -> None:
    """The measured (A) defect: an active record with no agent behind it."""
    conn = database()
    pairing = pairing_store(conn)
    link = _old_link(pairing, label=FULL_NAME)
    last_online = _now() - timedelta(minutes=40)
    presence = FakePresence({OLD_NODE: {
        **_receipt(device_id=OLD_NODE, connected=False, received_at=_now(),
                   last_connected_at=last_online),
    }})
    body = _listed(pairing, presence)
    row = next(item for item in body["links"] if item["link_id"] == link["link_id"])
    assert row["state"] == "active"          # the pairing record is intact
    assert row["online"] is False            # but the agent is not connected
    assert row["last_seen_at"] == presence.rows[OLD_NODE]["last_connected_at"]


def test_the_list_says_online_only_inside_the_presence_staleness_bound() -> None:
    conn = database()
    pairing = pairing_store(conn)
    link = _old_link(pairing, label=FULL_NAME)

    fresh = _listed(pairing, FakePresence({
        OLD_NODE: _receipt(device_id=OLD_NODE, connected=True, received_at=_now()),
    }))
    assert next(r for r in fresh["links"] if r["link_id"] == link["link_id"])["online"] is True

    stale_stamp = _now() - timedelta(seconds=181)
    stale = _listed(pairing, FakePresence({
        OLD_NODE: _receipt(device_id=OLD_NODE, connected=True, received_at=stale_stamp,
                           last_connected_at=stale_stamp),
    }))
    row = next(r for r in stale["links"] if r["link_id"] == link["link_id"])
    assert row["online"] is False
    assert row["last_seen_at"]


def test_a_pc_nothing_has_observed_is_never_listed_as_online() -> None:
    conn = database()
    pairing = pairing_store(conn)
    link = _old_link(pairing, label=FULL_NAME)
    body = _listed(pairing, FakePresence({}))
    row = next(r for r in body["links"] if r["link_id"] == link["link_id"])
    assert row["online"] is False
    assert row["last_seen_at"] is None


def test_a_working_store_failure_is_not_read_as_connected() -> None:
    class Broken:
        async def load(self, device_id: str):
            raise RuntimeError("driver fault, never to be echoed")

    conn = database()
    pairing = pairing_store(conn)
    link = _old_link(pairing, label=FULL_NAME)
    body = _listed(pairing, Broken())
    row = next(r for r in body["links"] if r["link_id"] == link["link_id"])
    assert row["online"] is False
    assert "driver fault" not in str(body)


def test_the_presence_store_keeps_the_moment_it_was_last_connected() -> None:
    conn = database()
    store = D1MeshDevicePresenceStore(RealSQLiteD1(conn))
    online_at = _now() - timedelta(minutes=5)
    assert run(store.upsert(
        device_id=NEW_NODE, connected=True, received_at=online_at,
        credential_generation=None, source="mesh",
    )) is True
    assert run(store.upsert(
        device_id=NEW_NODE, connected=False, received_at=_now(),
        credential_generation=None, source="mesh",
    )) is True
    stored = run(store.load(NEW_NODE))
    assert stored["connected"] is False
    # The disconnect beat did not overwrite when the node was last connected.
    assert stored["last_connected_at"] == online_at.astimezone(timezone.utc) \
        .isoformat().replace("+00:00", "Z")


# -- (B) the install lanes report the whole computer name ------------------

def test_the_install_file_reports_the_dns_host_name_not_the_netbios_form() -> None:
    script = render_install_script(
        install_tag="pd-1234abcd", agent_url="https://mesh.example.net/meshagents",
    )
    assert script is not None
    # Dns.GetHostName() answers the whole DNS name; COMPUTERNAME is the
    # 15-character NetBIOS form and stays only as the fallback.
    assert "[System.Net.Dns]::GetHostName()" in script
    # #6775 이후: 기본 조각은 태그 하나(토큰·드라이브는 조건부로 뒤에 붙고)
    # 마지막 조각이 기기 이름 — DNS 이름이 먼저 온다는 규칙은 그대로다.
    assert "$reported = $PairingTag" in script
    assert '$reported = $reported + " " + $machine' in script
    assert '$reported = $reported + " " + $env:COMPUTERNAME' not in script
    assert '$reported = $PairingTag + " [" + ($letters -join " ") + "] " + $env:COMPUTERNAME' \
        not in script


def test_both_pc_install_lanes_report_the_whole_name() -> None:
    root = Path(__file__).resolve().parents[3]
    wrapper = (root / "scripts/pc_pairing/install-padiem-pc.ps1").read_text(encoding="utf-8-sig")
    assert "[System.Net.Dns]::GetHostName()" in wrapper
    # The NetBIOS form is only ever the fallback, never the first answer.
    assert "try { [System.Net.Dns]::GetHostName() } catch { $env:COMPUTERNAME }" in wrapper
    assert wrapper.count("$machine = $env:COMPUTERNAME") == 1
    assert "if (-not $machine) { $machine = $env:COMPUTERNAME }" in wrapper

    program = (root / "scripts/pc_pairing/connect-exe/PadiemPcConnect.cs").read_text(
        encoding="utf-8")
    assert "Dns.GetHostName()" in program
    # The agent name is built from the whole name, not the truncated property.
    assert "AgentName(tag, FixedDriveLetters(), FullMachineName())" in program
    assert "AgentName(tag, FixedDriveLetters(), Environment.MachineName)" not in program
    # A full 21-character computer name fits the name grammar.
    assert "{1,128}" in program