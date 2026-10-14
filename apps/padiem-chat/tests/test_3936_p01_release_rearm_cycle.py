"""#3936: the release -> re-arm -> decide cycle must stay one-shot safe.

#4518 made a canonical retry-safe Engine rejection release the one-shot P01
decision reservation so the owner may decide again. The tests that shipped with
it cover the *first* release. What they do not cover is the rest of the state
machine the release opens up:

- a released reservation that is then **re-armed** by a second owner action,
- a re-armed reservation whose Engine result is **ambiguous** (must return to
  ``decision_unknown`` and stay armed, never a third dispatch),
- a re-armed reservation whose Engine result is **confirmed** (must reach
  ``confirmed`` with exactly two Engine calls),
- a duplicate reservation with **no** intervening release (the original one-shot
  guard: the INSERT primary key must fail closed),
- a stale/foreign re-arm attempt (must not consume the released reservation).

These are source-only assertions over synthetic fixtures. They prove the B62
state machine; they are not evidence of any production run.
"""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_p01_owner_decision import decide, ready, setup_pause
from test_3580_web_xlsx_sources import OWNER, request
from app.web_xlsx_p01_engine_client import CloudflareWebXlsxP01EngineClient

STATUS = "/api/claw/office/web-selections/{}/p01-status"
WORKSPACE = "owner:" + OWNER
# The exact canonical tool identity the Engine must echo back for a confirmation.
CANONICAL_TOOL = "tool:padiem:web-xlsx-confirm@1"


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = None
        self.value = body

    async def text(self):
        return self.value


class EngineBinding:
    """Private Engine Service Binding returning one fixed resume reply."""

    def __init__(self, status, result, *, raise_=False):
        self.status = status
        self.result = result
        self.raise_ = raise_
        self.calls = []

    async def fetch(self, js):
        self.calls.append(js)
        if self.raise_:
            raise RuntimeError("private Engine unavailable")
        return FakeResponse(self.status, json.dumps(self.result, ensure_ascii=False))


def real_client(binding):
    """The production client, so the real Engine envelope checks are exercised."""

    def make(url, *, method, headers, body):
        return SimpleNamespace(js_object={"request": len(binding.calls)})

    return CloudflareWebXlsxP01EngineClient(
        binding,
        caller_id="P01_ENGINE_B62",
        credential="secret-for-tests-only-not-real",
        request_factory=make,
    )


def retry_safe_binding():
    return EngineBinding(409, {"ok": False, "error": {"code": "invalid_decision"}})


def confirmed_envelope(continuation_ref, source_sha256):
    """The exact Engine confirmation shape the production client requires."""
    return {
        "ok": True,
        "tool": {
            "canonical_tool_id": CANONICAL_TOOL,
            "status": "completed",
            "continuation_ref": continuation_ref,
            "output": {
                "p01_intent_confirmed": True,
                "read_executed": False,
                "workcopy_created": False,
                "source_sha256": source_sha256,
            },
        },
    }


def request_row(db):
    return db.execute(
        "SELECT continuation_ref, source_sha256 FROM claw_web_xlsx_p01_requests"
    ).fetchone()


async def p01_status(app, settings, selection):
    return await request(
        app, settings, method="GET", owner=OWNER,
        path=STATUS.format(selection["selection_ref"]),
    )


def receipts(db):
    return list(db.execute("SELECT * FROM claw_web_xlsx_p01_decision_receipts"))


@pytest.mark.asyncio
async def test_released_then_rearmed_then_confirmed_reaches_confirmed():
    """A released reservation may be re-armed, and a confirmed Engine result wins."""
    app, settings, meta, r2, db, history, _ = ready()
    _original, selection = await setup_pause(app, settings)

    binding = retry_safe_binding()
    app.state.web_xlsx_p01_owner_decision_client = real_client(binding)

    first = await decide(app, settings, selection, decision="approve")
    assert first.status_code == 409, first.text
    assert first.json()["error"]["code"] == "owner_p01_decision_retryable", first.text
    released = receipts(db)
    assert len(released) == 1
    assert released[0]["released_at"] is not None
    created_at = released[0]["created_at"]

    # Second owner action: the Engine now verifies the approval.
    row = request_row(db)
    binding.status = 200
    binding.result = confirmed_envelope(row["continuation_ref"], row["source_sha256"])
    second = await decide(app, settings, selection, decision="approve")
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "confirmed"
    assert len(binding.calls) == 2, "exactly one new dispatch per owner action"

    after = receipts(db)
    assert len(after) == 1, "recovery must reuse the reservation, never mint a new one"
    assert after[0]["state"] == "confirmed"
    assert after[0]["released_at"] is None, "a consumed reservation is armed, not released"
    assert after[0]["created_at"] == created_at, "reservation identity must be preserved"

    state = await p01_status(app, settings, selection)
    assert state.status_code == 200, state.text
    assert state.json()["status"] == "confirmed"
    assert state.json()["owner_decision_enabled"] is False
    db.close()


@pytest.mark.asyncio
async def test_released_then_rearmed_then_ambiguous_returns_to_decision_unknown():
    """After a re-arm, an ambiguous result must re-close the retry door."""
    app, settings, meta, r2, db, history, _ = ready()
    _original, selection = await setup_pause(app, settings)

    binding = retry_safe_binding()
    app.state.web_xlsx_p01_owner_decision_client = real_client(binding)

    first = await decide(app, settings, selection, decision="approve")
    assert first.status_code == 409
    assert first.json()["error"]["code"] == "owner_p01_decision_retryable"
    assert (await p01_status(app, settings, selection)).json()["status"] == "waiting_p01"

    # Second owner action, now ambiguous: the receipt is re-armed and re-closed.
    binding.raise_ = True
    second = await decide(app, settings, selection, decision="approve")
    assert second.status_code == 503, second.text
    assert second.json()["error"]["code"] == "owner_p01_decision_dispatch_unknown"

    armed = receipts(db)
    assert len(armed) == 1
    assert armed[0]["state"] == "dispatching"
    assert armed[0]["released_at"] is None, "an ambiguous result must stay armed"

    state = await p01_status(app, settings, selection)
    assert state.status_code == 200, state.text
    assert state.json()["status"] == "decision_unknown", state.text
    assert state.json()["owner_decision_enabled"] is False

    # The released-and-rearmed retry door is now closed again: no third dispatch.
    third = await decide(app, settings, selection, decision="approve")
    assert third.status_code in (409, 503), third.text
    assert len(binding.calls) == 2, "an armed reservation must never auto-replay"
    assert (await p01_status(app, settings, selection)).json()["status"] == "decision_unknown"
    db.close()


@pytest.mark.asyncio
async def test_duplicate_reservation_without_release_fails_closed():
    """The original one-shot guard: no release, no second reservation."""
    app, settings, meta, r2, db, history, _ = ready()
    _original, selection = await setup_pause(app, settings)
    store = app.state.web_xlsx_p01_owner_decision_store
    waiting = await store.load_waiting(
        owner_id=OWNER, workspace_id=WORKSPACE,
        selection_ref=selection["selection_ref"],
    )
    assert waiting is not None
    await store.reserve(waiting=waiting, outcome="deny")
    assert len(receipts(db)) == 1
    with pytest.raises(sqlite3.IntegrityError):
        await store.reserve(waiting=waiting, outcome="deny")
    assert len(receipts(db)) == 1, "a duplicate reservation must not add a row"
    db.close()


@pytest.mark.asyncio
async def test_rearm_requires_the_exact_released_row_for_this_pause():
    """A stale or foreign 'waiting' scope must never re-arm another receipt."""
    app, settings, meta, r2, db, history, _ = ready()
    _original, selection = await setup_pause(app, settings)
    binding = retry_safe_binding()
    app.state.web_xlsx_p01_owner_decision_client = real_client(binding)
    assert (await decide(app, settings, selection, decision="approve")).status_code == 409

    store = app.state.web_xlsx_p01_owner_decision_store
    waiting = await store.load_waiting(
        owner_id=OWNER, workspace_id=WORKSPACE,
        selection_ref=selection["selection_ref"],
    )
    # Different pause identity: the re-arm UPDATE must match nothing, and the
    # fallback INSERT must fail closed on the existing primary key.
    stale = {**waiting, "pause_id": "pause:" + "a" * 32}
    with pytest.raises(sqlite3.IntegrityError):
        await store.reserve(waiting=stale, outcome="approve")
    rows = receipts(db)
    assert len(rows) == 1
    assert rows[0]["released_at"] is not None, (
        "a foreign re-arm attempt must not consume the released reservation"
    )
    db.close()
