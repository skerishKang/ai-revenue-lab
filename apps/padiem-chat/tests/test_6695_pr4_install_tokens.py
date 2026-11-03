"""#6695 PR-4 — the install URL carries the account, not just the pairing code.

Migration 093 adds one row per issued code: `pc_install_tokens`, which holds a
SHA-256 of a `pt_`-prefixed token and nothing else. What the contract turns on:

* the URL an account is handed names that account (its own token is appended to
  the deployment's MeshCentral link, which stays intact), so two accounts never
  receive the same install;
* the token never leaves the server in plaintext except inside the file it is
  meant for, and the database keeps only its hash;
* a new pairing presents the token from the channel it used - the claim body or
  the observed agent name - and a foreign, revoked or expired token is refused
  with its own reason;
* the owner can cancel or replace exactly one install, and a PC linked before
  this table existed keeps pairing and keeps its link.

Everything runs against real sqlite with the real migrations and the real
Starlette routes, because the properties that matter are database properties.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing            # noqa: E402

from app import queue_store_proxy as proxy               # noqa: E402
from app.pc_device_pairing_routes import (               # noqa: E402
    PC_PAIRING_CLAIM_PATH,
    PC_PAIRING_INSTALL_EXE_PATH,
    PC_PAIRING_INSTALL_FILE_PATH,
    PC_PAIRING_PATH,
    PC_PAIRING_TOKEN_REISSUE_PATH,
    PC_PAIRING_TOKEN_REVOKE_PATH,
    render_install_script,
)
from app.pc_device_pairing_store import (                # noqa: E402
    INSTALL_TOKEN_HEX_CHARS,
    INSTALL_TOKEN_PREFIX,
    PAIRING_CODE_ALPHABET,
    PAIRING_CODE_CHARS,
    PcPairingError,
    derive_install_tag,
    install_token_from_agent_name,
    pc_name_from_agent_name,
    tag_from_agent_name,
)

REPO = Path(__file__).resolve().parents[3]
STATIC = Path(__file__).resolve().parents[1] / "static"
QUEUE_MODULE = REPO / "apps" / "padiem-mesh-queue" / "internal_store.py"
SCHEMA_MODULE = REPO / "apps" / "padiem-mesh-queue" / "schema.py"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "093_pc_install_tokens.sql"

OWNER = pairing.OWNER
OTHER = pairing.OTHER
NODE = "node/meshdomain/mesh-token-01"
OTHER_NODE = "node/meshdomain/mesh-token-02"
AGENT_URL = "https://mesh.example.padiem.net/meshagents?id=4&meshid=c9yfFkUpi38"
RUN = pairing.run

TOKEN_SHAPE = re.compile(r"^" + re.escape(INSTALL_TOKEN_PREFIX)
                         + r"[0-9a-f]{%d}$" % INSTALL_TOKEN_HEX_CHARS)
#: A pairing code is 12 characters of the unambiguous alphabet (no I or O), so
#: an ordinary word like COMPUTERNAME is not mistaken for one.
CODE_SHAPE = re.compile(
    r"\b[" + re.escape(PAIRING_CODE_ALPHABET) + "]{" + str(PAIRING_CODE_CHARS) + r"}\b"
)


def configured(store_value):
    app = pairing.app_with(store_value)
    app.state.pc_pairing_install_url = AGENT_URL
    return app


def moment() -> datetime:
    return datetime.now(timezone.utc)


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def url_token(url: str) -> str:
    return parse_qs(urlsplit(url).query)["padiem_install_token"][0]


def token_rows(store_value):
    return store_value.db.conn.execute(
        "SELECT token_id, token_sha256, code_id, user_id, expires_at, revoked_at "
        "FROM pc_install_tokens"
    ).fetchall()


# -- 1. the URL names the account -------------------------------------------

def test_each_account_receives_its_own_account_specific_install_url() -> None:
    async def journey():
        shared = pairing.store()
        app = configured(shared)
        async with pairing.client(app, user_id=OWNER) as session:
            mine = await session.post(PC_PAIRING_PATH, json={})
        async with pairing.client(app, user_id=OTHER) as session:
            theirs = await session.post(PC_PAIRING_PATH, json={})
        return shared, mine.json()["pairing"], theirs.json()["pairing"]

    shared, mine, theirs = RUN(journey())
    for issued, owner in ((mine, OWNER), (theirs, OTHER)):
        assert issued["install_url"].startswith(AGENT_URL + "&"), issued["install_url"]
        # The deployment's own arguments survive untouched …
        query = parse_qs(urlsplit(issued["install_url"]).query)
        assert query["id"] == ["4"]
        assert query["meshid"] == ["c9yfFkUpi38"]
        # … and the token is its own argument, not a reuse of theirs.
        token = url_token(issued["install_url"])
        assert TOKEN_SHAPE.fullmatch(token), token
        row = shared.db.conn.execute(
            "SELECT token_sha256, user_id, code_id FROM pc_install_tokens WHERE code_id=?",
            (issued["code_id"],),
        ).fetchone()
        assert row["user_id"] == owner
        assert row["token_sha256"] == hashlib.sha256(token.encode("utf-8")).hexdigest()

    assert url_token(mine["install_url"]) != url_token(theirs["install_url"])
    # Exactly one install per issuance, bound to its own code.
    assert shared.db.conn.execute("SELECT COUNT(*) FROM pc_install_tokens").fetchone()[0] == 2


def test_the_token_is_stored_only_as_a_hash_and_the_list_never_reads_it_back() -> None:
    async def journey():
        store_value = pairing.store()
        issued = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        listed = await store_value.list_codes(user_id=OWNER, now=moment())
        return store_value, issued, listed

    store_value, issued, listed = RUN(journey())
    token = issued["install_token"]
    assert TOKEN_SHAPE.fullmatch(token), token
    row = token_rows(store_value)[0]
    assert row["token_sha256"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert row["user_id"] == OWNER and row["code_id"] == issued["code_id"]
    # The plaintext value is in no column of the row, and the owner-facing list
    # answers "does this install still stand" without ever carrying it.
    assert token not in json.dumps(dict(row), ensure_ascii=False)
    assert listed[0]["install_token_state"] == "active"
    assert "install_token" not in listed[0]
    assert token not in json.dumps(listed, ensure_ascii=False)


# -- 2. a new pairing is held to the token it presents ----------------------

def test_another_accounts_token_cannot_claim_this_code_and_creates_no_link() -> None:
    async def journey():
        store_value = pairing.store()
        mine = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        theirs = await store_value.issue_code(user_id=OTHER, issued_at=moment())
        with pytest.raises(PcPairingError) as refused:
            await store_value.redeem_code(
                code=mine["code"], mesh_node_id=NODE, label=None, now=moment(),
                install_token=theirs["install_token"],
            )
        app = configured(store_value)
        async with pairing.client(app, user_id=OWNER) as session:
            over_http = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": mine["code"], "mesh_node_id": NODE,
                "install_token": theirs["install_token"],
            })
        return store_value, str(refused.value), over_http, mine, theirs

    store_value, reason, over_http, mine, theirs = RUN(journey())
    assert reason == "install token invalid"
    assert over_http.status_code == 403, over_http.text
    assert over_http.json()["error"]["code"] == "pc_pairing_token_invalid"
    assert over_http.json()["error"]["message"]
    assert theirs["install_token"] not in over_http.text
    assert store_value.db.conn.execute(
        "SELECT COUNT(*) FROM pc_device_links"
    ).fetchone()[0] == 0


def test_a_revoked_install_is_refused_and_the_already_linked_pc_is_untouched() -> None:
    async def journey():
        store_value = pairing.store()
        app = configured(store_value)
        async with pairing.client(app, user_id=OWNER) as session:
            first = await session.post(PC_PAIRING_PATH, json={})
            first_code = first.json()["pairing"]["code"]
            first_token = url_token(first.json()["pairing"]["install_url"])
            linked = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": first_code, "mesh_node_id": NODE, "install_token": first_token,
            })
            second = await session.post(PC_PAIRING_PATH, json={})
            second_pairing = second.json()["pairing"]
            second_token = url_token(second_pairing["install_url"])
            revoked = await session.post(
                PC_PAIRING_TOKEN_REVOKE_PATH.format(code_id=second_pairing["code_id"]),
            )
            without_token = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": second_pairing["code"], "mesh_node_id": OTHER_NODE,
            })
            with_token = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": second_pairing["code"], "mesh_node_id": OTHER_NODE,
                "install_token": second_token,
            })
            listed = await session.get(PC_PAIRING_PATH)
            still = await store_value.list_links(user_id=OWNER)
            return linked, revoked, without_token, with_token, listed.json(), still

    linked, revoked, without_token, with_token, listed, still = RUN(journey())
    assert linked.status_code in (201, 202), linked.text
    assert revoked.status_code == 200 and revoked.json()["ok"] is True
    assert revoked.json()["install"]["code_state"] == "cancelled"
    for refused in (without_token, with_token):
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "pc_pairing_token_revoked"
    # The PC that paired before the cancellation keeps its link and its state.
    assert [row["mesh_node_id"] for row in still] == [NODE]
    assert [link["mesh_node_id"] for link in listed["links"]] == [NODE]
    states = {code["code_id"]: code["install_token_state"] for code in listed["codes"]}
    assert set(states.values()) == {"active", "revoked"}


def test_an_expired_install_is_reported_expired_and_can_no_longer_pair() -> None:
    """The token lives exactly as long as its code, so one clock expires both.

    The owner's list says the install no longer stands, and the claim is refused
    on the code's own expiry - the token gate is never asked to guess about a
    code that is already dead.
    """

    async def journey():
        store_value = pairing.store()
        issued = await store_value.issue_code(
            user_id=OWNER, issued_at=moment() - timedelta(minutes=11),
        )
        listed = await store_value.list_codes(user_id=OWNER, now=moment())
        with pytest.raises(PcPairingError) as refused:
            await store_value.redeem_code(
                code=issued["code"], mesh_node_id=NODE, label=None, now=moment(),
                install_token=issued["install_token"],
            )
        return listed, str(refused.value)

    listed, refused = RUN(journey())
    assert listed[0]["state"] == "expired"
    assert listed[0]["install_token_state"] == "expired"
    assert refused == "pairing code expired"


def test_a_claim_without_a_token_pairs_the_way_it_always_did() -> None:
    """Existing installs are not invalidated by the table arriving.

    Two shapes are covered: a code minted before 093 has no token row at all,
    and a code minted with a token is still claimable by a channel that never
    carried one, as long as the token it is bound to still stands.
    """
    code = "ABCDEFGHJKLM"
    tag = derive_install_tag(code)

    async def journey():
        store_value = pairing.store()
        now = moment()
        store_value.db.conn.execute(
            "INSERT INTO pc_pairing_codes "
            "(code_id, code_sha256, tag_sha256, user_id, state, mesh_node_id, "
            " issued_at, expires_at, claimed_at) "
            "VALUES (?, ?, ?, ?, 'pending', NULL, ?, ?, NULL)",
            (
                "pcpair_" + "1" * 32,
                hashlib.sha256(code.encode("utf-8")).hexdigest(),
                hashlib.sha256(tag.encode("utf-8")).hexdigest(),
                OWNER, stamp(now - timedelta(seconds=1)),
                stamp(now + timedelta(minutes=5)),
            ),
        )
        legacy = await store_value.redeem_code(
            code=code, mesh_node_id=NODE, label=None, now=now,
        )
        issued = await store_value.issue_code(user_id=OWNER, issued_at=now)
        bound = await store_value.redeem_code(
            code=issued["code"], mesh_node_id=OTHER_NODE, label=None, now=now,
        )
        third = await store_value.issue_code(user_id=OWNER, issued_at=now)
        with pytest.raises(PcPairingError) as malformed:
            await store_value.redeem_code(
                code=third["code"], mesh_node_id="node/meshdomain/mesh-token-03",
                label=None, now=now, install_token=INSTALL_TOKEN_PREFIX + "zz",
            )
        return legacy, bound, str(malformed.value), store_value

    legacy, bound, malformed, store_value = RUN(journey())
    assert legacy["mesh_node_id"] == NODE
    assert bound["mesh_node_id"] == OTHER_NODE
    assert malformed == "install token invalid"
    # No token row was invented for the legacy code that never had one.
    assert store_value.db.conn.execute(
        "SELECT COUNT(*) FROM pc_install_tokens WHERE code_id=?", ("pcpair_" + "1" * 32,),
    ).fetchone()[0] == 0


# -- 3. cancel and replace exactly one install ------------------------------

def test_reissue_retires_the_old_pair_and_hands_out_exactly_one_new_install() -> None:
    async def journey():
        store_value = pairing.store()
        app = configured(store_value)
        async with pairing.client(app, user_id=OWNER) as session:
            issued = (await session.post(PC_PAIRING_PATH, json={})).json()["pairing"]
            old_token = url_token(issued["install_url"])
            reissued = await session.post(
                PC_PAIRING_TOKEN_REISSUE_PATH.format(code_id=issued["code_id"]),
            )
            new_pairing = reissued.json()["pairing"]
            new_token = url_token(new_pairing["install_url"])
            old_claim = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": issued["code"], "mesh_node_id": NODE, "install_token": old_token,
            })
            new_claim = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": new_pairing["code"], "mesh_node_id": NODE,
                "install_token": new_token,
            })
            listed = (await session.get(PC_PAIRING_PATH)).json()["codes"]
        return reissued, issued, new_pairing, old_token, new_token, old_claim, \
            new_claim, listed

    reissued, issued, new_pairing, old_token, new_token, old_claim, new_claim, listed = \
        RUN(journey())
    assert reissued.status_code == 201, reissued.text
    assert new_pairing["code_id"] != issued["code_id"]
    assert new_pairing["code"] != issued["code"]
    assert TOKEN_SHAPE.fullmatch(new_token) and new_token != old_token
    assert old_claim.status_code == 403
    assert old_claim.json()["error"]["code"] == "pc_pairing_token_revoked"
    assert new_claim.status_code in (201, 202), new_claim.text
    states = {code["code_id"]: code["install_token_state"] for code in listed}
    assert states[issued["code_id"]] == "revoked"
    assert states[new_pairing["code_id"]] == "active"


def test_cancel_and_reissue_are_owner_scoped_closed_and_bounded() -> None:
    async def journey():
        store_value = pairing.store()
        issued = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        app = configured(store_value)
        async with pairing.client(app, user_id=OTHER) as session:
            foreign_revoke = await session.post(
                PC_PAIRING_TOKEN_REVOKE_PATH.format(code_id=issued["code_id"]),
            )
            foreign_reissue = await session.post(
                PC_PAIRING_TOKEN_REISSUE_PATH.format(code_id=issued["code_id"]),
            )
        async with pairing.client(app, user_id=OWNER) as session:
            unknown = await session.post(
                PC_PAIRING_TOKEN_REVOKE_PATH.format(code_id="pcpair_" + "0" * 32),
            )
            invalid = await session.post(
                PC_PAIRING_TOKEN_REISSUE_PATH.format(code_id="not-a-code-id"),
            )
        anonymous = pairing.client(pairing.app_with(None), user_id=OWNER)
        async with anonymous as session:
            no_store = await session.post(
                PC_PAIRING_TOKEN_REVOKE_PATH.format(code_id=issued["code_id"]),
            )
        no_session_app = configured(pairing.store())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=no_session_app), base_url=pairing.ORIGIN,
        ) as session:
            no_session = await session.post(
                PC_PAIRING_TOKEN_REVOKE_PATH.format(code_id=issued["code_id"]),
            )
        return foreign_revoke, foreign_reissue, unknown, invalid, no_store, no_session

    foreign_revoke, foreign_reissue, unknown, invalid, no_store, no_session = RUN(journey())
    for refused in (foreign_revoke, foreign_reissue):
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "pc_pairing_link_forbidden"
    for refused in (unknown, invalid):
        assert refused.status_code == 403, refused.text
        assert refused.json()["error"]["code"] == "pc_pairing_code_unknown"
    assert no_store.status_code == 503
    assert no_session.status_code == 401


# -- 4. the download names its install and carries its token ---------------

def test_the_script_download_names_its_install_and_embeds_the_token() -> None:
    async def journey():
        store_value = pairing.store()
        app = configured(store_value)
        # A store-issued install keeps its plaintext code in the test's hand, which
        # is what the reissue lane's second download names; the route's own
        # download is exercised beside it.
        issued = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        async with pairing.client(app, user_id=OWNER) as session:
            fresh = await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={})
            fresh_code_id = fresh.headers.get("X-PC-Pairing-Code-Id")
            rebuilt = await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={
                "code": issued["code"], "install_token": issued["install_token"],
            })
            unnamed = await session.post(
                PC_PAIRING_INSTALL_FILE_PATH, json={"code": issued["code"]},
            )
            bad_token = await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={
                "code": issued["code"], "install_token": "pt_zz",
            })
            extra = await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={
                "code": issued["code"], "extra": True,
            })
            listed = (await session.get(PC_PAIRING_PATH)).json()["codes"]
        return (store_value, issued, fresh, fresh_code_id, rebuilt, unnamed,
                bad_token, extra, listed)

    (store_value, issued, fresh, fresh_code_id, rebuilt, unnamed, bad_token,
     extra, listed) = RUN(journey())
    assert fresh.status_code == 200, fresh.text
    # The browser learns which install it downloaded; the token rides in no header.
    assert fresh_code_id and fresh_code_id.startswith("pcpair_")
    assert fresh_code_id != issued["code_id"]
    assert issued["install_token"] not in json.dumps(dict(fresh.headers))
    token = re.search(
        r"\$PadiemInstallToken = '(pt_[0-9a-f]{32})'", fresh.text,
    ).group(1)
    assert TOKEN_SHAPE.fullmatch(token)
    assert "padiem_install_token=" + token in fresh.text
    row = store_value.db.conn.execute(
        "SELECT token_sha256 FROM pc_install_tokens WHERE code_id=?", (fresh_code_id,),
    ).fetchone()
    assert row["token_sha256"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert CODE_SHAPE.search(fresh.text) is None
    assert store_value.db.conn.execute("SELECT COUNT(*) FROM pc_pairing_codes").fetchone()[0] == 2
    states = {code["code_id"]: code["install_token_state"] for code in listed}
    assert states[fresh_code_id] == "active"

    # Naming a code re-renders that install; it never mints a second one.
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.headers["X-PC-Pairing-Code-Id"] == issued["code_id"]
    assert "$PadiemInstallToken = '" + issued["install_token"] + "'" in rebuilt.text
    assert store_value.db.conn.execute("SELECT COUNT(*) FROM pc_pairing_codes").fetchone()[0] == 2

    # A code named without its token renders the pre-093 shape for that same code.
    assert unnamed.status_code == 200, unnamed.text
    assert unnamed.headers["X-PC-Pairing-Code-Id"] == issued["code_id"]
    assert "$PadiemInstallToken = ''" in unnamed.text
    assert store_value.db.conn.execute("SELECT COUNT(*) FROM pc_pairing_codes").fetchone()[0] == 2

    assert bad_token.status_code == 400 and extra.status_code == 400


def test_the_program_download_puts_the_token_in_its_download_url() -> None:
    """The reviewed program cannot stamp a name, so the URL carries the token."""

    async def journey():
        store_value = pairing.store()
        app = configured(store_value)
        async with pairing.client(app, user_id=OWNER) as session:
            response = await session.post(PC_PAIRING_INSTALL_EXE_PATH, json={})
        return store_value, response

    store_value, response = RUN(journey())
    assert response.status_code == 200, response.text
    code_id = response.headers.get("X-PC-Pairing-Code-Id")
    assert code_id and code_id.startswith("pcpair_")
    # The trailer names the deployment's link with this install's token appended.
    tail = response.content.decode("latin-1")
    url = re.search(r"PADIEMURL:(\S+)\r\n", tail).group(1)
    assert url.startswith(AGENT_URL + "&padiem_install_token=")
    token = url_token(url)
    assert TOKEN_SHAPE.fullmatch(token)
    row = store_value.db.conn.execute(
        "SELECT token_sha256 FROM pc_install_tokens WHERE code_id=?", (code_id,),
    ).fetchone()
    assert row["token_sha256"] == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert re.search(r"PADIEMTAG:pd-[0-9a-f]{8}\r\n", tail)
    # The token is in the file it belongs to, never in a response header.
    assert token not in json.dumps(dict(response.headers))


# -- 5. the observed agent name carries the same token ----------------------

def test_the_observed_name_is_held_to_the_same_token_binding() -> None:
    async def journey():
        store_value = pairing.store()
        issued = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        theirs = await store_value.issue_code(user_id=OTHER, issued_at=moment())
        linked = await store_value.complete_claim_from_observation(
            agent_name=f"{issued['install_tag']} {issued['install_token']} [C] PADIEM-PC",
            mesh_node_id=NODE, now=moment(),
        )
        # A second, still-pending install of this account, so the foreign token
        # is what the gate refuses rather than a code that is already spent.
        fresh = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        return store_value, issued, theirs, fresh, linked

    store_value, issued, theirs, fresh, linked = RUN(journey())
    assert linked["state"] == "active"
    assert [root["path"] for root in linked["roots"]] == ["C:"]

    async def refused():
        with pytest.raises(PcPairingError) as exc:
            await store_value.complete_claim_from_observation(
                agent_name=f"{fresh['install_tag']} {theirs['install_token']} PADIEM-PC",
                mesh_node_id=OTHER_NODE, now=moment(),
            )
        return str(exc.value)

    # The tag alone would have matched; the foreign token is what refuses it.
    assert RUN(refused()) == "install token invalid"


def test_the_install_file_and_the_name_reader_agree_on_the_token() -> None:
    token = INSTALL_TOKEN_PREFIX + "a" * INSTALL_TOKEN_HEX_CHARS
    script = render_install_script(
        install_tag="pd-1234abcd", agent_url=AGENT_URL, install_token=token,
    )
    assert script is not None
    assert "$PadiemInstallToken = '" + token + "'" in script
    assert 'if ($PadiemInstallToken) { $reported = $reported + " " + $PadiemInstallToken }' in script
    # Without a token the reported name is exactly the pre-093 one.
    plain = render_install_script(install_tag="pd-1234abcd", agent_url=AGENT_URL)
    assert plain is not None and "$PadiemInstallToken = ''" in plain
    assert render_install_script(
        install_tag="pd-1234abcd", agent_url=AGENT_URL, install_token="pt_zz",
    ) is None

    name = f"pd-1234abcd {token} [C D] PADIEM-PC"
    assert install_token_from_agent_name(name) == token
    assert tag_from_agent_name(name) == "pd-1234abcd"
    assert pc_name_from_agent_name(name) == "PADIEM-PC"
    assert install_token_from_agent_name("pd-1234abcd PADIEM-PC") is None
    assert install_token_from_agent_name(f"pd-1234abcd {token} {token} PADIEM-PC") is None
    assert install_token_from_agent_name(f"x{token}x") is None


# -- 6. migration 093 is idempotent and the queue ledger covers it ----------

def test_migration_093_is_idempotent_and_only_hash_shaped() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(sql)
    conn.executescript(sql)
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(pc_install_tokens)")]
    assert columns == [
        "token_id", "token_sha256", "code_id", "user_id",
        "issued_at", "expires_at", "revoked_at",
    ]
    now = moment()
    values = (
        "pctok_" + "1" * 32, "a" * 64, "pcpair_" + "1" * 32, OWNER,
        stamp(now), stamp(now + timedelta(minutes=10)),
    )
    conn.execute(
        "INSERT INTO pc_install_tokens "
        "(token_id, token_sha256, code_id, user_id, issued_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)", values,
    )
    for duplicate in (
        ("pctok_" + "2" * 32, "a" * 64, "pcpair_" + "2" * 32),
        ("pctok_" + "3" * 32, "b" * 64, "pcpair_" + "1" * 32),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO pc_install_tokens "
                "(token_id, token_sha256, code_id, user_id, issued_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (duplicate[0], duplicate[1], duplicate[2], OWNER,
                 stamp(now), stamp(now + timedelta(minutes=10))),
            )


def test_the_queue_schema_ledger_applies_093_and_the_proxy_may_ask_for_it(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location("queue_schema", SCHEMA_MODULE)
    assert spec is not None and spec.loader is not None
    schema = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(schema)

    assert "093_pc_install_tokens.sql" in schema.QUEUE_MIGRATIONS
    assert "pc_install_tokens" in schema.QUEUE_TABLES
    assert tuple(schema.REQUIRED_COLUMNS["pc_install_tokens"]) == (
        "token_id", "token_sha256", "code_id", "user_id", "expires_at", "revoked_at",
    )
    from app.d1_sqlite import connect

    connection = connect(str(tmp_path / "queue.sqlite3"))
    schema.apply(connection)
    schema.apply(connection)                      # a restart replays no DDL
    columns = [row[1] for row in connection.execute("PRAGMA table_info(pc_install_tokens)")]
    assert "token_sha256" in columns and "revoked_at" in columns
    applied = [row[0] for row in connection.execute("SELECT name FROM queue_schema_applied")]
    assert "093_pc_install_tokens.sql" in applied

    # Both allowlists answer the two new methods, or the COM2 lane would 404
    # an owner's cancel/replace at the seam.
    spec = importlib.util.spec_from_file_location("queue_internal_store", QUEUE_MODULE)
    assert spec is not None and spec.loader is not None
    internal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(internal)
    for name in ("revoke_install_token", "reissue_install_token"):
        assert name in proxy.QUEUE_PAIRING_METHODS, name
        assert name in internal.PAIRING_METHODS, name


# -- 7. the screen says it in both languages, and never renders the token ---

def test_the_install_controls_and_strings_are_wired_for_both_languages() -> None:
    card = (STATIC / "pc-pairing-card.js").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    for key in (
        "pc-pairing-install-cancel", "pc-pairing-install-reprepare",
        "pc-pairing-install-cancelled", "pc-pairing-install-reprepared",
    ):
        assert locale.count(f'"{key}"') == 2, key      # ko and en
        assert f'"{key}"' in card, key
    # The shared strings are read through locale.js, with the local copy as
    # fallback for a page that loads the card alone.
    assert "window.__padiemLocale" in card
    assert 'cancelInstallButton.addEventListener("click"' in card
    assert 'reprepareInstallButton.addEventListener("click"' in card
    assert "/token/revoke" in card and "/token/reissue" in card
    # The full token is never put on the screen: the card holds a code id and
    # reads the token out of the server's URL only to re-download the file.
    assert "activeInstall.token" not in card
    assert not re.search(r"textContent\s*=\s*[^;\n]*install_token", card)
