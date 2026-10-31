"""#5573 PC pairing — one owner, their own PC, many-to-many, over real SQL.

Migration 072's two tables are applied to a real sqlite database and driven
through the real Starlette routes. The three behaviours the contract turns on are
pinned here and nowhere else matters as much:

* a pairing code is single use and short lived — a second claim and an expired
  claim are both refused, and neither creates a link;
* a link is `(user_id, mesh_node_id)`, so one PC shared by two accounts carries
  two independent root approvals, and revoking one pair leaves the other alone;
* nothing a PC claims becomes executable on the strength of the claim alone:
  without a server-side Mesh observation the link stays `pending_verification`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import sys

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.app_factory import create_app
from app.pc_device_pairing_routes import (
    PC_PAIRING_CLAIM_PATH,
    PC_PAIRING_PATH,
    PC_PAIRING_ROOTS_PATH,
    PC_PAIRING_ROOT_PATH,
)
from app.pc_device_pairing_store import (
    D1PcPairingStore,
    PcPairingError,
    derive_install_tag,
    drive_root,
    normalize_root_label,
    normalize_root_path,
)

sys.path.insert(0, str(Path(__file__).parent))

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "072_pc_device_pairing.sql"
MIGRATIONS = MIGRATION.parent
#: Both pairing migrations are one unapplied set: 073 ALTERs the table 072
#: creates, so "before the pairing migration" has to leave 073 out too or the
#: replay itself, not the code under test, is what fails.
PAIRING_MIGRATION_NUMBERS = {MIGRATION.name[:3], "073"}
OWNER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32
NODE = "node//mesh-pc-01"
OTHER_NODE = "node/meshdomain/mesh-pc-02"
SESSION_SECRET = "phase11-pc-pairing-session-secret-not-a-real-key-0000000000"
ORIGIN = "https://chat.example.test"


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
    """The prepare/bind/run/first surface the D1 stores use."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def prepare(self, query: str) -> D1Statement:
        return D1Statement(self.conn, query)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def database(*, with_072: bool = True) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if not with_072 and path.name[:3] in PAIRING_MIGRATION_NUMBERS:
            continue
        conn.executescript(path.read_text(encoding="utf-8"))
    return conn


def store(*, with_072: bool = True) -> D1PcPairingStore:
    return D1PcPairingStore(RealSQLiteD1(database(with_072=with_072)))


def app_with(store_value=None, *, verifier=None):
    app = create_app(Settings(
        runtime_mode="mock",
        session_secret=SESSION_SECRET,
        public_base_url=ORIGIN,
    ))
    app.state.pc_device_pairing_store = store_value
    if verifier is not None:
        app.state.pc_pairing_verifier = verifier
    return app


def client(app, *, user_id: str = OWNER):
    token = create_session_token(
        app.state.settings, user_id, now=int(_now().timestamp()),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        # Cookie-authenticated mutations are covered by the central #3476 origin
        # guard, and these routes are registered by app_factory, so they are
        # guarded: a browser client has to bring the reviewed Origin.
        headers={"Origin": ORIGIN},
        cookies={SESSION_COOKIE: token},
    )


def run(coro):
    import asyncio

    return asyncio.run(coro)


def observed_on_the_mesh(*, node_seen: bool = True):
    """Stand-in for PR-2's server-side Mesh observation of the claimed node."""
    async def verifier(*, mesh_node_id: str, code: str) -> bool:
        return node_seen
    return verifier


# -- the pairing code is a single-use possession proof -----------------------

def test_a_code_is_redeemed_once_and_the_second_claim_is_refused() -> None:
    async def journey():
        app = app_with(store())
        async with client(app) as session:
            issued = await session.post(PC_PAIRING_PATH, json={})
            assert issued.status_code == 201, issued.text
            code = issued.json()["pairing"]["code"]
            first = await session.post(
                PC_PAIRING_CLAIM_PATH, json={"code": code, "mesh_node_id": NODE},
            )
            assert first.status_code == 202, first.text
            second = await session.post(
                PC_PAIRING_CLAIM_PATH, json={"code": code, "mesh_node_id": NODE},
            )
            return first.json(), second.status_code, second.json()

    body, second_status, second_body = run(journey())
    assert body["link"]["mesh_node_id"] == NODE
    assert second_status == 403
    assert second_body["error"]["code"] == "pc_pairing_code_used"


def test_an_expired_code_is_refused_and_creates_no_link() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now() - timedelta(minutes=11))
        with pytest.raises(PcPairingError) as refused:
            await pairing.redeem_code(
                code=issued["code"], mesh_node_id=NODE, label=None, now=_now(),
            )
        links = await pairing.list_links(user_id=OWNER)
        row = pairing.db.conn.execute(
            "SELECT state FROM pc_pairing_codes WHERE code_id=?", (issued["code_id"],),
        ).fetchone()
        return refused.value, links, row["state"]

    error, links, state = run(journey())
    assert str(error) == "pairing code expired"
    assert links == []
    # The expired code is moved out of `pending`, so it cannot be redeemed twice
    # by racing a clock read against the expiry column.
    assert state == "cancelled"


def test_the_plaintext_code_never_reaches_the_database() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        rows = pairing.db.conn.execute(
            "SELECT code_sha256, tag_sha256 FROM pc_pairing_codes"
        ).fetchall()
        return issued, rows[0]

    issued, row = run(journey())
    assert issued["code"] not in (row["code_sha256"] + row["tag_sha256"])
    assert row["code_sha256"] != issued["code"]
    assert row["tag_sha256"] != issued["install_tag"]
    # The tag the installer stamps into the MeshCentral agent name is a pure
    # function of the code, so the PC needs nothing beyond the code (R2, R3).
    assert derive_install_tag(issued["code"]) == issued["install_tag"]


# -- a claim without a Mesh observation is not executable --------------------

def test_a_claim_without_a_directory_observation_stays_pending() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(),
        )
        executable = await pairing.link_for(user_id=OWNER, mesh_node_id=NODE)
        return link["state"], executable

    state, executable = run(journey())
    assert state == "pending_verification"
    assert executable is None


def test_a_verified_claim_is_immediately_usable_and_reclaims_idempotently() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label="집 PC", now=_now(), verified=True,
        )
        executable = await pairing.link_for(user_id=OWNER, mesh_node_id=NODE)
        return link["state"], link["label"], executable["mesh_node_id"]

    state, label, node = run(journey())
    assert state == "active"
    assert label == "집 PC"
    assert node == NODE


# -- the link, not the account or the PC, carries the folder grant ----------

def test_a_later_observed_claim_promotes_the_same_pair_and_adds_no_permission() -> None:
    async def journey():
        pairing = store()
        first = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        pending = await pairing.redeem_code(
            code=first["code"], mesh_node_id=NODE, label="작업 PC", now=_now(),
        )
        # Nothing may be approved on a pair nothing has observed yet.
        with pytest.raises(PcPairingError) as refused:
            await pairing.approve_root(
                user_id=OWNER, link_id=pending["link_id"], path="C:/Users/me/a", now=_now(),
            )
        second = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        promoted = await pairing.redeem_code(
            code=second["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        return str(refused.value), promoted["link_id"], pending["link_id"], \
            promoted["state"], promoted["label"], promoted["roots"]

    reason, promoted_id, pending_id, state, label, roots = run(journey())
    assert reason == "link not active"
    # The same pair, not a second row, and no folder came along for the ride.
    assert promoted_id == pending_id
    assert state == "active"
    assert label == "작업 PC"
    assert roots == []


def test_roots_are_approved_per_link_and_a_revoked_pair_keeps_the_other_alive() -> None:
    async def journey():
        pairing = store()
        mine = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        theirs = await pairing.issue_code(user_id=OTHER, issued_at=_now())
        # Same physical PC, two accounts: two links (R1).
        first = await pairing.redeem_code(
            code=mine["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        second = await pairing.redeem_code(
            code=theirs["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        approved = await pairing.approve_root(
            user_id=OWNER, link_id=first["link_id"], path="C:/Users/me/견적", now=_now(),
        )
        await pairing.approve_root(
            user_id=OTHER, link_id=second["link_id"], path="C:/Users/other/경리", now=_now(),
        )
        revoked = await pairing.revoke_link(
            user_id=OWNER, link_id=first["link_id"], now=_now(),
        )
        return {
            "approved": approved,
            "revoked": revoked,
            "mine_after": await pairing.link_for(user_id=OWNER, mesh_node_id=NODE),
            "theirs_after": await pairing.link_for(user_id=OTHER, mesh_node_id=NODE),
            "first_row": await pairing._read_link(OWNER, first["link_id"]),
        }

    out = run(journey())
    assert out["approved"]["path"] == "C:/Users/me/견적"
    assert out["revoked"] is True
    # R5: the deleted pair's authority is gone …
    assert out["mine_after"] is None
    assert out["first_row"]["roots"] == []
    assert out["first_row"]["state"] == "revoked"
    # … and the other account's link and folder on the same machine are untouched.
    assert [root["path"] for root in out["theirs_after"]["roots"]] == ["C:/Users/other/경리"]


def test_a_traversing_relative_or_wildcard_path_is_still_refused() -> None:
    assert normalize_root_path("C:/Users/me/견적") == "C:/Users/me/견적"
    assert normalize_root_path("C:\\Users\\me\\\t견적") is None
    for rejected in ("C:/Users/../Windows", "상대경로", "C:/a*b", "   ", "C:/Users/me/x:y"):
        assert normalize_root_path(rejected) is None, rejected


def test_a_whole_drive_is_an_approvable_root() -> None:
    """#5573 Owner decision: a linked PC works over its drives by default.

    The shape is accepted in every spelling the PC or an owner types, and the
    other guards - traversal, wildcards, control characters, relative text -
    are unchanged, so widening the default scope did not widen the grammar.
    """
    for accepted, expected in (
        ("C:", "C:"), ("c:", "C:"), ("C:/", "C:"), ("C:\\", "C:"),
        ("D:\\", "D:"), ("Z:/", "Z:"),
    ):
        assert normalize_root_path(accepted) == expected, accepted

    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        approved = await pairing.approve_root(
            user_id=OWNER, link_id=link["link_id"], path="C:\\", now=_now(),
        )
        async with client(app_with(pairing)) as session:
            listed = await session.get(PC_PAIRING_PATH)
        return approved, listed.json()

    approved, listed = run(journey())
    assert approved["path"] == "C:" and approved["label"] == "C:"
    assert [root["path"] for root in listed["links"][0]["roots"]] == ["C:"]


def test_a_claiming_pc_seeds_its_own_fixed_drives_and_the_scope_is_said() -> None:
    """The PC names the drives it has; the server grants them and says so.

    A PC that could not answer the query is reported (`lookup_failed`), because a
    silently empty link reads as "this machine has no drives" - which is a lie
    about a PC nobody asked.
    """
    assert drive_root("c:\\") == "C:" and drive_root("C:/Users/me") is None

    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        claimed = await pairing.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(),
            verified=True, drives=["C:", "D:"],
        )
        quiet = await pairing.issue_code(user_id=OTHER, issued_at=_now())
        bare = await pairing.redeem_code(
            code=quiet["code"], mesh_node_id=OTHER_NODE, label=None, now=_now(),
            verified=True, drives=[],
        )
        adopted = await pairing.adopt_link(
            user_id=OTHER, mesh_node_id=NODE, root_paths=["C:/Users/other/경리"],
            now=_now(), drives=["E:"],
        )
        async with client(app_with(pairing)) as session:
            code = await session.post(PC_PAIRING_PATH, json={})
            body = (await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": code.json()["pairing"]["code"],
                "mesh_node_id": "node//mesh-pc-09",
                "drives": ["C:\\"],
            })).json()
            oversized = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": code.json()["pairing"]["code"],
                "mesh_node_id": "node//mesh-pc-10",
                "drives": ["C:/Users/me"],
            })
        return claimed, bare, adopted, body, oversized

    claimed, bare, adopted, body, oversized = run(journey())
    assert [root["path"] for root in claimed["roots"]] == ["C:", "D:"]
    assert [root["label"] for root in claimed["roots"]] == ["C:", "D:"]
    assert bare["roots"] == []
    assert [root["path"] for root in adopted["roots"]] == ["C:/Users/other/경리", "E:"]
    assert body["drives_status"] == "seeded"
    # A PC may report drives, not folders: the claim channel cannot name a folder.
    assert oversized.status_code == 400, oversized.text


def test_one_accounts_drive_grant_stays_on_its_own_link() -> None:
    """Two accounts on one machine, and the drive belongs to exactly one of them."""
    async def journey():
        pairing = store()
        first = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        mine = await pairing.redeem_code(
            code=first["code"], mesh_node_id=NODE, label=None, now=_now(),
            verified=True, drives=["C:"],
        )
        second = await pairing.issue_code(user_id=OTHER, issued_at=_now())
        theirs = await pairing.redeem_code(
            code=second["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        rows = await pairing.links_for_owner(user_id=OTHER)
        revoked = await pairing.revoke_root(
            user_id=OTHER, link_id=theirs["link_id"],
            root_ref=mine["roots"][0]["root_ref"], now=_now(),
        )
        still_mine = await pairing.links_for_owner(user_id=OWNER)
        return theirs, rows, revoked, still_mine

    theirs, rows, revoked, still_mine = run(journey())
    assert theirs["roots"] == []
    assert [root["path"] for root in rows[0]["roots"]] == []
    assert revoked is False
    assert [root["path"] for root in still_mine[0]["roots"]] == ["C:"]


def test_a_root_removal_leaves_the_link_and_its_other_roots_usable() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        first = await pairing.approve_root(
            user_id=OWNER, link_id=link["link_id"], path="C:/Users/me/a", now=_now(),
        )
        await pairing.approve_root(
            user_id=OWNER, link_id=link["link_id"], path="C:/Users/me/b", now=_now(),
        )
        revoked = await pairing.revoke_root(
            user_id=OWNER, link_id=link["link_id"], root_ref=first["root_ref"], now=_now(),
        )
        live = await pairing.link_for(user_id=OWNER, mesh_node_id=NODE)
        return revoked, [root["path"] for root in live["roots"] if root["state"] == "active"]

    revoked, paths = run(journey())
    assert revoked is True
    assert paths == ["C:/Users/me/b"]


# -- the HTTP surface refuses when it has no store or no session -------------

def test_routes_refuse_without_a_store_and_require_a_session() -> None:
    async def journey():
        app = app_with(None)
        async with client(app) as session:
            issued = await session.post(PC_PAIRING_PATH, json={})
        anonymous = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app_with(store())),
            base_url=ORIGIN,
        )
        async with anonymous:
            unauthenticated = await anonymous.get(PC_PAIRING_PATH)
            bad_body = await anonymous.post(PC_PAIRING_CLAIM_PATH, json={"code": "X"})
        return issued.status_code, unauthenticated.status_code, bad_body.status_code

    issued, unauthenticated, bad_body = run(journey())
    assert issued == 503
    assert unauthenticated == 401
    assert bad_body == 400


def test_claim_requires_the_closed_body_and_a_canonical_node_identity() -> None:
    async def journey():
        app = app_with(store())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
        ) as anonymous:
            bare = await anonymous.post(
                PC_PAIRING_CLAIM_PATH, json={"code": "ABCDEF234567", "mesh_node_id": "foo/bar"},
            )
            extra = await anonymous.post(
                PC_PAIRING_CLAIM_PATH,
                json={"code": "ABCDEF234567", "mesh_node_id": NODE, "user_id": OWNER},
            )
            return bare.status_code, bare.json()["error"]["code"], extra.status_code

    bare_status, bare_code, extra_status = run(journey())
    # An identity neither canonical form describes is refused before the code is
    # looked up, so a malformed one tells a caller nothing about whether a code
    # exists. Both real forms are accepted: `node/<domain>/<node>` and the
    # `id@domain` spelling meshctrl reports (Owner decision on #5573).
    assert bare_status == 400 and bare_code == "pc_pairing_node_invalid"
    # A request may never name the account it is pairing into.
    assert extra_status == 400


def test_a_foreign_account_cannot_revoke_or_approve_another_links_pair() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        refused = await pairing.revoke_link(user_id=OTHER, link_id=link["link_id"], now=_now())
        still = await pairing.link_for(user_id=OWNER, mesh_node_id=NODE)
        return refused, still["link_id"] == link["link_id"]

    refused, intact = run(journey())
    assert refused is False
    assert intact is True


def test_revoke_and_root_paths_drive_the_same_authority_over_http() -> None:
    async def journey():
        app = app_with(store(), verifier=observed_on_the_mesh())
        async with client(app) as session:
            issued = await session.post(PC_PAIRING_PATH, json={})
            code = issued.json()["pairing"]["code"]
            claimed = await session.post(
                PC_PAIRING_CLAIM_PATH, json={"code": code, "mesh_node_id": OTHER_NODE},
            )
            link_id = claimed.json()["link"]["link_id"]
            approved = await session.post(
                PC_PAIRING_ROOTS_PATH.format(link_id=link_id), json={"path": "C:/Users/me/경리"},
            )
            listed = await session.get(PC_PAIRING_PATH)
            dropped = await session.delete(
                PC_PAIRING_ROOT_PATH.format(link_id=link_id, root_ref=approved.json()["root"]["root_ref"]),
            )
            after = await session.get(PC_PAIRING_PATH)
            revoked = await session.delete(f"{PC_PAIRING_PATH}/{link_id}")
            gone = await session.get(PC_PAIRING_PATH)
            return {
                "claimed": claimed.status_code,
                "approved": approved.status_code,
                "listed": listed.json()["links"],
                "dropped": dropped.status_code,
                "after": after.json()["links"],
                "revoked": revoked.status_code,
                "gone": gone.json()["links"],
            }

    out = run(journey())
    # A node the server has observed pairs active; the state decides, not the claim.
    assert out["claimed"] == 201
    assert out["approved"] == 201
    assert [root["path"] for root in out["listed"][0]["roots"]] == ["C:/Users/me/경리"]
    assert out["dropped"] == 200
    assert out["after"][0]["roots"] == []
    assert out["revoked"] == 200
    # A revoked link leaves the owner's list; it is not hidden and re-enabled.
    assert out["gone"] == []


def test_an_unknown_or_foreign_pairing_code_id_is_not_redeemable_by_another_owner() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        # The same PC presenting a second account's code can only ever create that
        # account's own link: the code decides the owner, nothing else can.
        theirs = await pairing.issue_code(user_id=OTHER, issued_at=_now())
        second = await pairing.redeem_code(
            code=theirs["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        return link["link_id"], second["link_id"], await pairing.list_links(user_id=OWNER), \
            await pairing.list_links(user_id=OTHER)

    mine, theirs, mine_links, their_links = run(journey())
    assert mine != theirs
    assert [row["mesh_node_id"] for row in mine_links] == [NODE]
    assert [row["mesh_node_id"] for row in their_links] == [NODE]


# -- before the Owner applies 072, the surface reads as "not ready" ----------

def test_every_pairing_route_answers_503_not_ready_until_072_is_applied() -> None:
    """The live case between the Chat deploy and the migration.

    The Worker composes this store against whatever D1 binding exists, so on a
    database where 072 has not been applied every call fails inside the driver.
    That has to be a bounded 503, never an unhandled exception (HTTP 500) and
    never an answer that looks like an empty but valid directory.
    """
    async def journey():
        app = app_with(store(with_072=False))
        async with client(app) as session:
            issued = await session.post(PC_PAIRING_PATH, json={})
            listed = await session.get(PC_PAIRING_PATH)
            claimed = await session.post(
                PC_PAIRING_CLAIM_PATH, json={"code": "ABCDEF234567", "mesh_node_id": NODE},
            )
            revoked = await session.delete(PC_PAIRING_PATH + "/pclink_" + "0" * 32)
            roots = await session.post(
                PC_PAIRING_ROOTS_PATH.format(link_id="pclink_" + "0" * 32),
                json={"path": "C:/Users/me/a"},
            )
            return [
                (response.status_code, response.json()["error"]["code"])
                for response in (issued, listed, claimed, revoked, roots)
            ]

    outcomes = run(journey())
    assert [code for _, code in outcomes] == ["pc_pairing_not_ready"] * 5
    assert [status for status, _ in outcomes] == [503] * 5


def test_an_unexplained_store_fault_is_still_a_refusal_and_not_a_500() -> None:
    async def journey():
        class Broken:
            async def list_links(self, **values):
                raise RuntimeError("driver fault, never to be echoed")

            async def list_codes(self, **values):
                return []

        app = app_with(Broken())
        async with client(app) as session:
            listed = await session.get(PC_PAIRING_PATH)
        return listed.status_code, listed.json()["error"]["code"], listed.text

    status, code, body = run(journey())
    assert status == 503 and code == "pc_pairing_unavailable"
    assert "driver fault" not in body


# -- each approved folder carries the name the owner gave it ----------------

def test_one_folder_is_named_by_itself_and_two_cannot_share_a_name() -> None:
    async def journey():
        pairing_store = store()
        issued = await pairing_store.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing_store.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        first = await pairing_store.approve_root(
            user_id=OWNER, link_id=link["link_id"], path="C:/Users/me/견적", now=_now(),
        )
        refused = None
        try:
            await pairing_store.approve_root(
                user_id=OWNER, link_id=link["link_id"], path="C:/Users/other/견적",
                now=_now(),
            )
        except PcPairingError as exc:
            refused = str(exc)
        renamed = await pairing_store.approve_root(
            user_id=OWNER, link_id=link["link_id"], path="C:/Users/other/견적",
            label="본사 견적", now=_now(),
        )
        return first["label"], refused, renamed["label"], [
            root["path"] for root in (await pairing_store.link_for(
                user_id=OWNER, mesh_node_id=NODE,
            ))["roots"]
        ]

    default_label, refused, given, paths = run(journey())
    # The folder's own name is the label the model gets, so an owner who never
    # named a folder still gets a usable one.
    assert default_label == "견적"
    assert refused == "root label exists"
    assert given == "본사 견적"
    assert paths == ["C:/Users/me/견적", "C:/Users/other/견적"]


def test_a_root_label_that_cannot_survive_being_named_back_is_refused() -> None:
    for rejected in ("견적/2026", "a\\b", "..", ".", "  ", "x" * 65, "견\t적"):
        assert normalize_root_label(rejected) is None, rejected
    assert normalize_root_label("  견적  ") == "견적"
    assert normalize_root_label("본사 견적") == "본사 견적"

    async def journey():
        pairing_store = store()
        issued = await pairing_store.issue_code(user_id=OWNER, issued_at=_now())
        link = await pairing_store.redeem_code(
            code=issued["code"], mesh_node_id=NODE, label=None, now=_now(), verified=True,
        )
        with pytest.raises(PcPairingError) as refused:
            await pairing_store.approve_root(
                user_id=OWNER, link_id=link["link_id"], path="C:/Users/me/a",
                label="a/b", now=_now(),
            )
        return str(refused.value)

    assert run(journey()) == "root label invalid"
