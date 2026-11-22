"""#7962 — the download says when it dies, and the wait says when it has.

The install file is a ten-minute possession proof: a claim made with the code
it carries - or with that code's token - is refused once ``expires_at`` has
passed. Two facts were missing for the browser to act on that clock:

* a download never said which install it just handed over or when it stops
  being usable, so the modal could not show a countdown; and
* nothing on the wire named the code's own state, so a code that had expired
  looked the same as one still being waited on.

This file pins both over the real routes and real sqlite:

1. both download lanes stamp the server's own deadline (and the code id) on the
   response, and nothing that is a possession proof rides along with it;
2. the owner's polling answer names each dead state - pending, expired,
   cancelled, claimed - without ever reading the code or the token back out;
3. a dead install is replaced the way the 다시 받기 button does it: reissue the
   token, then download a fresh file whose header carries the new deadline.

The window itself is untouched: ``PAIRING_CODE_TTL_SECONDS`` stays 600.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).parent))

import _support.pc_device_pairing as pairing            # noqa: E402

from app.pc_device_pairing_routes import (               # noqa: E402
    PC_PAIRING_CLAIM_PATH,
    PC_PAIRING_INSTALL_EXE_PATH,
    PC_PAIRING_INSTALL_FILE_PATH,
    PC_PAIRING_PATH,
    PC_PAIRING_TOKEN_REISSUE_PATH,
    PC_PAIRING_TOKEN_REVOKE_PATH,
)
from app.pc_device_pairing_store import PAIRING_CODE_TTL_SECONDS  # noqa: E402

OWNER = pairing.OWNER
NODE = "node/meshdomain/mesh-expiry-01"
AGENT_URL = "https://mesh.example.padiem.net/meshagents?id=7&meshid=expiry0001"
RUN = pairing.run

#: The four states a code can be in from the owner's point of view, and the
#: three the token it stands for can be in.
CODE_STATES = {"pending", "expired", "cancelled", "claimed"}
TOKEN_STATES = {"active", "expired", "revoked"}


def configured(store_value):
    app = pairing.app_with(store_value)
    app.state.pc_pairing_install_url = AGENT_URL
    return app


def moment() -> datetime:
    return datetime.now(timezone.utc)


def instant(stamp: str) -> datetime:
    return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))


def url_token(url: str) -> str:
    return parse_qs(urlsplit(url).query)["padiem_install_token"][0]


# -- 1. the download names its install and its deadline ----------------------

def test_each_download_stamps_its_install_and_the_server_deadline() -> None:
    """One clock, told to the browser: the header *is* the row's own stamp."""

    async def journey():
        store_value = pairing.store()
        app = configured(store_value)
        async with pairing.client(app, user_id=OWNER) as session:
            script = await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={})
            program = await session.post(PC_PAIRING_INSTALL_EXE_PATH, json={})
            listed = (await session.get(PC_PAIRING_PATH)).json()["codes"]
        return store_value, script, program, listed

    store_value, script, program, listed = RUN(journey())
    rows = {code["code_id"]: code for code in listed}
    # #7962 keeps the ten-minute window: it is the number the UI now shows.
    assert PAIRING_CODE_TTL_SECONDS == 600

    handed_out = []
    for response in (script, program):
        assert response.status_code == 200, response.text
        code_id = response.headers["X-PC-Pairing-Code-Id"]
        deadline = response.headers["X-PC-Pairing-Expires-At"]
        assert code_id.startswith("pcpair_")
        assert code_id in rows, code_id
        # The header is the same stamp the polling answer repeats, so the
        # countdown and the refusal cannot drift apart.
        assert rows[code_id]["expires_at"] == deadline
        assert (instant(deadline) - instant(rows[code_id]["issued_at"])) \
            == timedelta(seconds=600)
        assert instant(deadline) > moment()
        assert rows[code_id]["state"] == "pending"
        handed_out.append(code_id)
    # Two downloads, two installs: neither lane reuses the other's code.
    assert len(set(handed_out)) == 2

    # A code id and a timestamp are not possession proofs, so nothing else may
    # be added to these responses' headers.
    for response in (script, program):
        named = {name for name in response.headers
                 if name.lower().startswith("x-pc-pairing")}
        assert named == {"x-pc-pairing-code-id", "x-pc-pairing-expires-at"}
    assert "pt_" not in json.dumps([dict(response.headers) for response in (script, program)])


# -- 2. the polling answer names the dead states -----------------------------

def test_the_polling_answer_names_each_dead_code_without_revealing_it() -> None:
    """Every state the wait must act on, and no secret in the answer."""

    async def journey():
        store_value = pairing.store()
        app = configured(store_value)
        expired = await store_value.issue_code(
            user_id=OWNER, issued_at=moment() - timedelta(minutes=11))
        cancelled = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        claimed = await store_value.issue_code(user_id=OWNER, issued_at=moment())
        async with pairing.client(app, user_id=OWNER) as session:
            pending = await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={})
            await session.post(
                PC_PAIRING_TOKEN_REVOKE_PATH.format(code_id=cancelled["code_id"]))
            claimed_link = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": claimed["code"], "mesh_node_id": NODE,
                "install_token": claimed["install_token"],
            })
            listed = (await session.get(PC_PAIRING_PATH)).json()
        return (store_value, expired, cancelled, claimed, pending, claimed_link,
                listed)

    (store_value, expired, cancelled, claimed, pending, claimed_link,
     listed) = RUN(journey())
    assert claimed_link.status_code in (201, 202), claimed_link.text
    rows = {code["code_id"]: code for code in listed["codes"]}
    pending_id = pending.headers["X-PC-Pairing-Code-Id"]

    assert rows[pending_id]["state"] == "pending"
    assert rows[expired["code_id"]]["state"] == "expired"
    assert rows[cancelled["code_id"]]["state"] == "cancelled"
    assert rows[claimed["code_id"]]["state"] == "claimed"
    assert {code["code_id"]: code["install_token_state"]
            for code in listed["codes"]} == {
        pending_id: "active",
        expired["code_id"]: "expired",
        cancelled["code_id"]: "revoked",
        claimed["code_id"]: "active",
    }
    # A closed vocabulary, and each row is a state plus a clock - never the code
    # or the token it stands for, which the browser must not be able to read.
    for code in listed["codes"]:
        assert set(code) == {"code_id", "state", "install_token_state",
                             "issued_at", "expires_at"}
        assert code["state"] in CODE_STATES
        assert code["install_token_state"] in TOKEN_STATES
        assert instant(code["expires_at"]) > instant(code["issued_at"])
    body = json.dumps(listed)
    for secret in (expired["code"], cancelled["code"], claimed["code"],
                   expired["install_token"], cancelled["install_token"],
                   claimed["install_token"]):
        assert secret not in body


# -- 3. 다시 받기: a dead install is replaced, never revived -----------------

def test_a_dead_install_is_replaced_by_a_fresh_file_with_a_new_deadline() -> None:
    async def journey():
        store_value = pairing.store()
        app = configured(store_value)
        dead = await store_value.issue_code(
            user_id=OWNER, issued_at=moment() - timedelta(minutes=11))
        async with pairing.client(app, user_id=OWNER) as session:
            refused = await session.post(PC_PAIRING_CLAIM_PATH, json={
                "code": dead["code"], "mesh_node_id": NODE,
                "install_token": dead["install_token"],
            })
            reissued = await session.post(
                PC_PAIRING_TOKEN_REISSUE_PATH.format(code_id=dead["code_id"]))
            fresh = reissued.json()["pairing"]
            rebuilt = await session.post(PC_PAIRING_INSTALL_FILE_PATH, json={
                "code": fresh["code"], "install_token": url_token(fresh["install_url"]),
            })
            listed = (await session.get(PC_PAIRING_PATH)).json()["codes"]
        return store_value, dead, refused, reissued, fresh, rebuilt, listed

    (store_value, dead, refused, reissued, fresh, rebuilt,
     listed) = RUN(journey())
    # The refusal the expired screen is shown for, said by the server itself.
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "pc_pairing_code_expired"

    # And the fresh file the button offers: a new code, a new deadline.
    assert reissued.status_code == 201, reissued.text
    assert fresh["code_id"] != dead["code_id"]
    assert instant(fresh["expires_at"]) - moment() > timedelta(minutes=9)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.headers["X-PC-Pairing-Code-Id"] == fresh["code_id"]
    assert rebuilt.headers["X-PC-Pairing-Expires-At"] == fresh["expires_at"]

    rows = {code["code_id"]: code for code in listed}
    # The retired install is dead on both clocks; the replacement is one wait.
    assert rows[dead["code_id"]]["install_token_state"] == "revoked"
    assert rows[fresh["code_id"]]["state"] == "pending"
    assert rows[fresh["code_id"]]["install_token_state"] == "active"
