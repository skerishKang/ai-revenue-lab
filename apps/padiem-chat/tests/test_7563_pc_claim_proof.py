"""#7563: a claim proves the PC by observation, not by the caller's own word.

The typed-code claim used to accept a `mesh_node_id` the caller chose and the
server only asked whether that node was online, so account B's code plus
account A's online PC became an active link for B. These tests pin the
replacement contract:

* a claim always lands in `pending_verification`, whatever the request says;
* the executor's observation of the install tag promotes it — once, and only
  inside the code's ten minutes;
* the drives come from that observation, never from the claim body.

Every store here is the real SQLite database with the real migrations applied.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.pc_device_pairing_routes import (
    PC_PAIRING_CLAIM_PATH,
    PC_PAIRING_PATH,
)
from app.pc_device_pairing_store import PcPairingError

from test_5573_pc_device_pairing import (
    NODE,
    ORIGIN,
    OTHER,
    OTHER_NODE,
    OWNER,
    app_with,
    client,
    run,
    store,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _online() -> object:
    """The old claim proof: the node is online, and nothing else is asked."""

    async def verifier(*, mesh_node_id: str, code: str) -> bool:
        return True

    return verifier


async def _issue(app, *, user_id: str = OWNER) -> dict:
    async with client(app, user_id=user_id) as session:
        response = await session.post(PC_PAIRING_PATH, json={})
        assert response.status_code == 201, response.text
        return response.json()["pairing"]


async def _claim(app, *, code: str, node: str, headers=None, extra=None):
    payload = {"code": code, "mesh_node_id": node}
    if extra:
        payload.update(extra)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN, **(headers or {})},
    ) as anonymous:
        return await anonymous.post(PC_PAIRING_CLAIM_PATH, json=payload)


def test_a_claim_naming_another_accounts_online_pc_creates_no_active_link() -> None:
    """Account B's code + account A's online node must not become B's PC."""

    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app, user_id=OTHER)
        claimed = await _claim(app, code=issued["code"], node=NODE)
        return (
            claimed.status_code,
            claimed.json()["link"]["state"],
            await pairing.link_for(user_id=OTHER, mesh_node_id=NODE),
            await pairing.link_for(user_id=OWNER, mesh_node_id=NODE),
        )

    status, state, other_link, owner_link = run(journey())
    assert status == 202
    assert state == "pending_verification"
    assert other_link is None
    assert owner_link is None


def test_claim_then_observation_promotes_once_and_grants_observed_drives() -> None:
    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app)
        claimed = await _claim(
            app, code=issued["code"], node=NODE, extra={"drives": ["C:"]},
        )
        before = await pairing.link_for(user_id=OWNER, mesh_node_id=NODE)
        name = f"{issued['install_tag']} [D E] WORKSTATION-1"
        first = await pairing.complete_claim_from_observation(
            agent_name=name, mesh_node_id=NODE, now=_now(),
        )
        second = await pairing.complete_claim_from_observation(
            agent_name=name, mesh_node_id=NODE, now=_now(),
        )
        after = await pairing.link_for(user_id=OWNER, mesh_node_id=NODE)
        return claimed, before, first, second, after

    claimed, before, first, second, after = run(journey())
    assert claimed.status_code == 202
    assert before is None
    assert first is not None and first["state"] == "active"
    assert second is None
    assert after is not None
    # The body said C:; only what the executor observed is granted.
    assert [root["path"] for root in after["roots"]] == ["D:", "E:"]


def test_the_claim_body_never_grants_drives_or_activation() -> None:
    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app)
        claimed = await _claim(
            app, code=issued["code"], node=NODE,
            extra={"drives": ["C:", "D:"], "label": "내 PC"},
        )
        body = claimed.json()
        listed = await pairing.list_links(user_id=OWNER)
        return claimed.status_code, body, listed

    status, body, listed = run(journey())
    assert status == 202
    assert body["link"]["state"] == "pending_verification"
    assert body["link"]["roots"] == []
    assert body["drives_status"] == "not_applied"
    assert [row["roots"] for row in listed] == [[]]


def test_an_observation_after_the_code_expired_promotes_nothing() -> None:
    async def journey():
        pairing = store()
        issued = await pairing.issue_code(
            user_id=OWNER, issued_at=_now() - timedelta(minutes=11),
        )
        with pytest.raises(PcPairingError) as refused:
            await pairing.complete_claim_from_observation(
                agent_name=f"{issued['install_tag']} [C] WORKSTATION-2",
                mesh_node_id=NODE,
                now=_now(),
            )
        return str(refused.value), await pairing.link_for(
            user_id=OWNER, mesh_node_id=NODE,
        )

    error, link = run(journey())
    assert error == "pairing code expired"
    assert link is None


def test_two_simultaneous_observations_promote_exactly_once() -> None:
    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app)
        await _claim(app, code=issued["code"], node=NODE)
        name = f"{issued['install_tag']} [C] WORKSTATION-3"
        both = await asyncio.gather(
            pairing.complete_claim_from_observation(
                agent_name=name, mesh_node_id=NODE, now=_now(),
            ),
            pairing.complete_claim_from_observation(
                agent_name=name, mesh_node_id=NODE, now=_now(),
            ),
        )
        return both, await pairing.link_for(user_id=OWNER, mesh_node_id=NODE)

    both, link = run(journey())
    assert sum(1 for row in both if row and row.get("_promoted")) == 1
    assert link is not None and link["state"] == "active"


def test_observation_promotes_only_the_code_owners_pending_link() -> None:
    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        mine = await _issue(app, user_id=OWNER)
        theirs = await _issue(app, user_id=OTHER)
        await _claim(app, code=mine["code"], node=NODE)
        await _claim(app, code=theirs["code"], node=NODE)
        await pairing.complete_claim_from_observation(
            agent_name=f"{mine['install_tag']} [C] WORKSTATION-4",
            mesh_node_id=NODE,
            now=_now(),
        )
        return (
            await pairing.link_for(user_id=OWNER, mesh_node_id=NODE),
            await pairing.link_for(user_id=OTHER, mesh_node_id=NODE),
        )

    mine, theirs = run(journey())
    assert mine is not None and mine["state"] == "active"
    assert theirs is None


def test_ten_failed_claims_lock_the_node_and_the_source(monkeypatch) -> None:
    from app import pc_device_pairing_routes as pairing_routes

    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app)
        clock = {"now": datetime.now(timezone.utc).replace(microsecond=0)}
        monkeypatch.setattr(pairing_routes, "_now", lambda: clock["now"])
        source = {"cf-connecting-ip": "203.0.113.9"}
        failures = [
            await _claim(app, code="WRONGCODE234", node=NODE, headers=source)
            for _ in range(10)
        ]
        # The right code, the same node: the window is already spent.
        locked = await _claim(app, code=issued["code"], node=NODE, headers=source)
        # A success elsewhere does not clear the source key either.
        other_node = await _claim(
            app, code=issued["code"], node=OTHER_NODE, headers=source,
        )
        clock["now"] = clock["now"] + timedelta(seconds=601)
        fresh = await _issue(app)
        unlocked = await _claim(
            app, code=fresh["code"], node=OTHER_NODE,
            headers={"cf-connecting-ip": "198.51.100.7"},
        )
        return [row.status_code for row in failures], locked, other_node, unlocked

    failures, locked, other_node, unlocked = run(journey())
    assert failures == [403] * 10
    assert locked.status_code == 429
    assert 1 <= int(locked.headers.get("retry-after")) <= 600
    assert locked.json()["error"]["code"] == "pc_pairing_claim_throttled"
    assert other_node.status_code == 429
    assert unlocked.status_code == 202
