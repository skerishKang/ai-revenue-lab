"""#5573 PR-4b: the handoff turns a code into the tag and the one installer link.

Whoever holds the code is the PC it was issued for, so this surface takes no
session and gives out no identity: the derived tag (which the wrapper stamps into
the agent name) and the single Windows installer URL the deployment declared. The
link never comes from the request, and an unconfigured deployment says so.
"""
from __future__ import annotations
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing          # noqa: E402

from app.pc_device_pairing_routes import (             # noqa: E402
    PC_PAIRING_HANDOFF_PATH,
    install_url_from_config,
)
from app.pc_device_pairing_store import derive_install_tag  # noqa: E402

AGENT_URL = "https://mesh.example.padiem.net/agents/meshwing-64.exe"
run = pairing.run


def app_configured(*, url=AGENT_URL, store_value=None):
    app = pairing.app_with(pairing.store() if store_value is None else store_value)
    app.state.pc_pairing_install_url = url
    return app


def _handoff(app, code):
    async def once():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=pairing.ORIGIN,
        ) as anonymous:
            return await anonymous.post(PC_PAIRING_HANDOFF_PATH, json={"code": code})
    response = run(once())
    return response.status_code, response.json()


# -- the config is the only source of the link -------------------------------

def test_only_a_plain_https_installer_url_is_handed_out():
    assert install_url_from_config(AGENT_URL) == AGENT_URL
    for unusable in ("", None, "http://mesh.example/agents/x.exe",
                     "https://user@mesh.example/x", "https:///x",
                     "https://mesh.example/agents/x exe", "ftp://mesh.example/x"):
        assert install_url_from_config(unusable) is None, unusable


def test_an_unconfigured_deployment_says_it_is_not_ready(monkeypatch):
    app = pairing.app_with(pairing.store())          # no install URL at all

    async def once():
        issued = await app.state.pc_device_pairing_store.issue_code(
            user_id=pairing.OWNER, issued_at=pairing._now(),
        )
        return issued["code"]

    code = run(once())
    status, body = _handoff(app, code)
    assert status == 503 and body["error"]["code"] == "pc_pairing_not_ready"


def test_the_request_cannot_name_the_installer_it_gets():
    app = app_configured()

    async def once():
        issued = await app.state.pc_device_pairing_store.issue_code(
            user_id=pairing.OWNER, issued_at=pairing._now(),
        )
        return issued["code"]

    code = run(once())

    async def smuggling():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=pairing.ORIGIN,
        ) as anonymous:
            return await anonymous.post(
                PC_PAIRING_HANDOFF_PATH,
                json={"code": code, "agent_url": "https://attacker.example/malware.exe"},
            )
    response = run(smuggling())
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "pc_pairing_body_invalid"


# -- a handoff never consumes the proof -------------------------------------

def test_a_valid_code_returns_its_derived_tag_and_leaves_the_code_unspent():
    store = pairing.store()
    app = app_configured(store_value=store)
    issued = run(store.issue_code(user_id=pairing.OWNER, issued_at=pairing._now()))

    status, body = _handoff(app, issued["code"])
    assert status == 200, body
    assert body["handoff"]["install_tag"] == derive_install_tag(issued["code"])
    assert body["handoff"]["agent_url"] == AGENT_URL
    assert issued["code"] not in body["handoff"]["install_tag"]

    # The code is still pending and still claimable: a download that fails
    # mid-way must not have burned the only ten-minute proof the PC holds.
    row = store.db.conn.execute(
        "SELECT state FROM pc_pairing_codes WHERE code_id=?", (issued["code_id"],),
    ).fetchone()
    assert row["state"] == "pending"
    link = run(store.redeem_code(
        code=issued["code"], mesh_node_id=pairing.NODE, label=None,
        now=pairing._now(), verified=True,
    ))
    assert link["state"] == "active"


def test_a_used_or_expired_code_is_refused_the_same_way_as_a_claim():
    store = pairing.store()
    app = app_configured(store_value=store)
    issued = run(store.issue_code(user_id=pairing.OWNER, issued_at=pairing._now()))
    run(store.redeem_code(
        code=issued["code"], mesh_node_id=pairing.NODE, label=None,
        now=pairing._now(), verified=True,
    ))
    assert _handoff(app, issued["code"])[1]["error"]["code"] == "pc_pairing_code_used"

    stale = run(store.issue_code(
        user_id=pairing.OWNER,
        issued_at=pairing._now() - __import__("datetime").timedelta(minutes=11),
    ))
    assert _handoff(app, stale["code"])[1]["error"]["code"] == "pc_pairing_code_expired"
    assert _handoff(app, "NOSUCHCODE1234")[1]["error"]["code"] == "pc_pairing_code_unknown"


def test_the_handoff_needs_no_session_and_stores_no_plaintext():
    store = pairing.store()
    app = app_configured(store_value=store)
    issued = run(store.issue_code(user_id=pairing.OWNER, issued_at=pairing._now()))

    status, _ = _handoff(app, issued["code"])
    assert status == 200
    rows = store.db.conn.execute("SELECT * FROM pc_pairing_codes").fetchall()
    stored = " ".join(str(value) for row in rows for value in tuple(row))
    assert issued["code"] not in stored
