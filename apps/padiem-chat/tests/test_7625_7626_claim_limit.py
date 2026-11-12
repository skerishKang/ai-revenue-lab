"""#7625/#7626: the claim failure limit follows the network, not the named PC.

A claim names a node id the caller chose, so counting failures against that id
let anyone lock a PC's owner out by naming their PC; #7614 already makes the
named id activate nothing, so the limit is the network's own code-guessing
budget (#7625). The meter itself must answer too: an unreadable counter refuses
the claim with 503 instead of reading as "not locked" (#7626), and a counter
that cannot be written still lets the original refusal go out while logging why
the failure was not counted.

Every store here is the real SQLite database with the real migrations applied,
and the ten-minute window is injected through the route's own clock.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.pc_device_pairing_routes import PC_PAIRING_CLAIM_PATH

from test_5573_pc_device_pairing import NODE, ORIGIN, OTHER_NODE, OWNER
from test_7563_pc_claim_proof import _issue, _online, app_with, run, store

ATTACKER_SOURCE = {"cf-connecting-ip": "203.0.113.9"}
OWNER_SOURCE = {"cf-connecting-ip": "198.51.100.7"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _claim_raw(app, *, code, node, headers) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=ORIGIN,
        headers={"Origin": ORIGIN, **(headers or {})},
    ) as anonymous:
        return await anonymous.post(
            PC_PAIRING_CLAIM_PATH, json={"code": code, "mesh_node_id": node},
        )


def test_a_source_lock_does_not_follow_a_node_id_another_source_named(monkeypatch) -> None:
    """Ten wrong claims that name a PC lock the NAMING source, not the PC.

    Before #7625 the named node id was counted too, so this exact sequence
    locked the PC's owner out of their own code.
    """

    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app)
        failures = [
            await _claim_raw(
                app, code="WRONGCODE234", node=NODE, headers=ATTACKER_SOURCE,
            )
            for _ in range(10)
        ]
        # The PC owner's own source, the same named PC, the right code.
        ok = await _claim_raw(
            app, code=issued["code"], node=NODE, headers=OWNER_SOURCE,
        )
        return [row.status_code for row in failures], ok.status_code

    failures, ok_status = run(journey())
    assert failures == [403] * 10
    assert ok_status == 202


def test_one_source_still_hits_the_limit_when_it_changes_the_node_id(monkeypatch) -> None:
    """The network counter is what limits code guessing, unchanged (#7625)."""

    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app)
        clock = {"now": datetime.now(timezone.utc).replace(microsecond=0)}
        monkeypatch.setattr(
            __import__("app.pc_device_pairing_routes", fromlist=["_now"]),
            "_now", lambda: clock["now"],
        )
        failures = [
            await _claim_raw(
                app, code="WRONGCODE234",
                node="node//mesh-pc-%02d" % index, headers=ATTACKER_SOURCE,
            )
            for index in range(10)
        ]
        locked = await _claim_raw(
            app, code=issued["code"], node="node//mesh-pc-99",
            headers=ATTACKER_SOURCE,
        )
        clock["now"] = clock["now"] + timedelta(seconds=601)
        fresh = await _issue(app)
        unlocked = await _claim_raw(
            app, code=fresh["code"], node="node//mesh-pc-99",
            headers={"cf-connecting-ip": "198.51.100.8"},
        )
        return [row.status_code for row in failures], locked.status_code, unlocked.status_code

    failures, locked, unlocked = run(journey())
    assert failures == [403] * 10
    assert locked == 429
    assert unlocked == 202


def test_an_unreadable_meter_refuses_with_503_and_never_checks_the_code(monkeypatch) -> None:
    """#7626: a meter that cannot be read is not an unlocked meter."""

    async def journey():
        pairing = store()
        app = app_with(pairing, verifier=_online())
        issued = await _issue(app)
        checked = []

        original = pairing.redeem_code

        async def spy_redeem(**values):
            checked.append(values)
            return await original(**values)

        async def broken(**values):
            raise RuntimeError("meter unreadable")

        import app.pc_device_pairing_routes as pairing_routes

        monkeypatch.setattr(pairing_routes, "_now", _now)
        monkeypatch.setattr(pairing, "claim_failure_counts", broken)
        monkeypatch.setattr(pairing, "redeem_code", spy_redeem)
        response = await _claim_raw(
            app, code=issued["code"], node=NODE, headers=ATTACKER_SOURCE,
        )
        return response, checked

    response, checked = run(journey())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "pc_pairing_claim_unavailable"
    assert checked == [], "the code check never ran past an unreadable meter"


def test_an_unwritable_meter_keeps_the_refusal_and_logs_why(monkeypatch, caplog) -> None:
    """#7626: the refused claim still refuses; the unwritten count is logged."""

    async def journey():
        import app.pc_device_pairing_routes as pairing_routes

        pairing = store()
        app = app_with(pairing, verifier=_online())
        await _issue(app)
        async def broken(**values):
            raise RuntimeError("meter unwritable")

        # The route's logger stops propagating once the host binds it a handler;
        # the test reads the line through the root instead.
        monkeypatch.setattr(pairing_routes._LOGGER, "propagate", True)
        monkeypatch.setattr(pairing, "record_claim_failure", broken)
        return await _claim_raw(
            app, code="WRONGCODE234", node=NODE, headers=ATTACKER_SOURCE,
        )

    with caplog.at_level(logging.WARNING):
        response = run(journey())
    assert response.status_code == 403
    lines = [
        record.getMessage() for record in caplog.records
        if "pc_pairing_claim_failure_record" in record.getMessage()
    ]
    assert lines, "the unwritten failure count is logged with its reason code"
    joined = "\n".join(lines)
    assert "unwritten" in joined
    # No request address and no code value ever land in the trace.
    assert "203.0.113.9" not in joined
    assert "WRONGCODE234" not in joined
