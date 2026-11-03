"""#261104 pairing re-report storm — the tag a paired PC keeps naming.

Production (COM2, 2026-11-04): every presence beat re-observes the pairing tag
each paired PC still carries in its install name, and every repeat raised
``PcPairingError("pairing code used")`` - about 800 refused lines an hour for
links that are perfectly fine. Two properties pin the fix:

* a node re-reporting the tag it already claimed ends quietly - ``None`` at
  the store, no exception and no refusal line in the presence lane - while a
  different node naming that spent tag is still refused, and expiry and
  install-token refusals are untouched;
* the refusal lines that remain carry a bounded reason (the fixed
  ``PcPairingError`` phrase, never another exception's message) and only the
  node's last six characters, once per hour per (node, reason), with the
  window's repeats counted and summarized as ``refused_suppressed count=N``.
"""
from __future__ import annotations
from datetime import timedelta
from pathlib import Path
import logging
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import test_5573_pc_device_pairing as pairing            # noqa: E402
import test_5015_pc_read_dispatch as lane                # noqa: E402
import test_5553_mesh_online_projection_261024 as projection  # noqa: E402
import test_5553_mesh_only_presence as presence_lane     # noqa: E402

from app import oracle_mesh_read_return_routes as routes  # noqa: E402
from app.mesh_device_presence_store import D1MeshDevicePresenceStore  # noqa: E402
from app.pc_device_pairing_store import (                # noqa: E402
    PAIRING_CODE_TTL_SECONDS,
    PcPairingError,
)

RUN = pairing.run

BEAT_NODE = projection.NODE_ID


def _issued(store):
    """One real code with the wrapper-shaped agent name its install stamps."""
    issued = RUN(store.issue_code(
        user_id=lane.OWNER, issued_at=pairing._now(),
    ))
    name = f"{issued['install_tag']} {issued['install_token']} [C D] beta-pc"
    return issued, name


# -- A: the store ends a node's own re-report quietly ------------------------

def test_a_node_rereporting_its_own_claimed_tag_ends_quietly() -> None:
    store = pairing.store()
    issued, name = _issued(store)

    link = RUN(store.complete_claim_from_observation(
        agent_name=name, mesh_node_id=pairing.NODE, now=pairing._now(),
    ))
    assert link["state"] == "active"

    assert RUN(store.complete_claim_from_observation(
        agent_name=name, mesh_node_id=pairing.NODE, now=pairing._now(),
    )) is None
    links = RUN(store.links_for_owner(user_id=lane.OWNER))
    assert [row["link_id"] for row in links] == [link["link_id"]]


def test_a_different_node_reusing_a_spent_tag_is_still_refused() -> None:
    store = pairing.store()
    issued, name = _issued(store)

    RUN(store.complete_claim_from_observation(
        agent_name=name, mesh_node_id=pairing.NODE, now=pairing._now(),
    ))
    with pytest.raises(PcPairingError) as again:
        RUN(store.complete_claim_from_observation(
            agent_name=name, mesh_node_id=pairing.OTHER_NODE, now=pairing._now(),
        ))
    assert str(again.value) == "pairing code used"
    # The refusal consumes nothing and the original link stays the only one.
    assert RUN(store.complete_claim_from_observation(
        agent_name=name, mesh_node_id=pairing.NODE, now=pairing._now(),
    )) is None
    assert len(RUN(store.links_for_owner(user_id=lane.OWNER))) == 1


def test_a_pending_code_still_claims_and_expiry_still_refuses() -> None:
    store = pairing.store()
    issued, name = _issued(store)

    link = RUN(store.complete_claim_from_observation(
        agent_name=name, mesh_node_id=pairing.NODE, now=pairing._now(),
    ))
    assert link["state"] == "active" and link["mesh_node_id"] == pairing.NODE

    stale_store = pairing.store()
    stale_issued, stale_name = _issued(stale_store)
    later = pairing._now() + timedelta(seconds=PAIRING_CODE_TTL_SECONDS + 1)
    with pytest.raises(PcPairingError) as expired:
        RUN(stale_store.complete_claim_from_observation(
            agent_name=stale_name, mesh_node_id=pairing.NODE, now=later,
        ))
    assert str(expired.value) == "pairing code expired"
    assert RUN(stale_store.links_for_owner(user_id=lane.OWNER)) == []
    assert stale_issued["code_id"] != issued["code_id"]


def test_a_revoked_install_token_is_still_refused() -> None:
    store = pairing.store()
    issued, name = _issued(store)

    RUN(store.revoke_install_token(
        user_id=lane.OWNER, code_id=issued["code_id"], now=pairing._now(),
    ))
    with pytest.raises(PcPairingError) as revoked:
        RUN(store.complete_claim_from_observation(
            agent_name=name, mesh_node_id=pairing.NODE, now=pairing._now(),
        ))
    assert str(revoked.value) == "install token revoked"
    assert RUN(store.links_for_owner(user_id=lane.OWNER)) == []


# -- B: the presence lane summarizes what it refuses --------------------------

class _RefusingPairing:
    """A pairing store that raises for every tagged beat, like a spent-tag fleet."""

    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls: list[str] = []

    async def complete_claim_from_observation(
        self, *, agent_name, mesh_node_id, now,
    ):
        self.calls.append(str(mesh_node_id))
        raise self.exc


def _beat_state(pairing_store, *, clock=None):
    state = projection._poll_state(D1MeshDevicePresenceStore(presence_lane.D1()))
    state.pc_device_pairing_store = pairing_store
    if clock is not None:
        state.pairing_refusal_log = routes._PairingRefusalLog(now_func=lambda: clock[0])
    return state


def _tagged_beat(agent_name: str = "pd-deadbeef [C D]") -> dict:
    return {"presence": [{"device_id": BEAT_NODE, "connected": True, "agent_name": agent_name}]}


def test_a_beat_for_an_already_paired_node_logs_nothing(caplog) -> None:
    store = pairing.store()
    issued, name = _issued(store)
    RUN(store.complete_claim_from_observation(
        agent_name=name, mesh_node_id=BEAT_NODE, now=pairing._now(),
    ))

    state = _beat_state(store)
    with caplog.at_level(logging.INFO):
        code, body = projection._poll(state, _tagged_beat(name))
    assert code == 200 and body == {"ok": True, "dispatch": None}
    assert "pairing_claim=refused" not in caplog.text
    assert "pairing_claim=completed" not in caplog.text
    # The beat still leaves its presence receipt; the claim adds nothing.
    row = RUN(state.mesh_device_presence_store.load(BEAT_NODE))
    assert row is not None and row["connected"] is True


def test_repeated_refusals_warn_once_per_hour_and_are_summarized(caplog) -> None:
    clock = [0.0]
    fake = _RefusingPairing(PcPairingError("pairing code used"))
    state = _beat_state(fake, clock=clock)
    beat = _tagged_beat()

    with caplog.at_level(logging.INFO):
        for _ in range(5):
            code, _body = projection._poll(state, beat)
            assert code == 200
        clock[0] += routes._PairingRefusalLog._WINDOW_SECONDS + 1
        code, _body = projection._poll(state, beat)
        assert code == 200
    suppressed = [r for r in caplog.records if "refused_suppressed" in r.getMessage()]
    assert len(suppressed) == 1 and suppressed[0].levelno == logging.INFO
    assert "count=4" in suppressed[0].getMessage()
    refused = [r for r in caplog.records
               if r.levelno == logging.WARNING and "pairing_claim=refused" in r.getMessage()]
    assert len(refused) == 2  # the window's opener and the new window's opener


def test_an_unexpected_failure_logs_only_the_exception_type(caplog) -> None:
    fake = _RefusingPairing(RuntimeError(f"secret {BEAT_NODE} path C:/x"))
    state = _beat_state(fake)

    with caplog.at_level(logging.INFO):
        code, _body = projection._poll(state, _tagged_beat())
    assert code == 200
    assert "reason=RuntimeError" in caplog.text
    assert "secret" not in caplog.text
    assert "C:/x" not in caplog.text
