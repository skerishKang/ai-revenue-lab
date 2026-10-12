"""#3936: a retry-safe Engine rejection must release the P01 one-shot reservation.

The canonical continuation lane (``kagent.p01_approval_continuation``) defines
``RETRY_SAFE_RESUME_CODES`` -- the Engine rejected this submission *without*
consuming the stored continuation, so the owner may decide again. The B62 web
P01 lane reserved the one-shot decision receipt BEFORE the Engine call and never
released it, so such a rejection left the receipt at ``dispatching`` forever:
public status ``decision_unknown``, and no second owner decision could ever be
recorded. This contradicts the canonical retry policy and #3935's
``RETRY_IS_PERMITTED_ONLY_IF_SAFE``.

These tests pin the required recovery: retry-safe release only, never automatic
re-execution, never an approval bypass. An ambiguous transport result must still
stay armed (see ``test_3580_web_xlsx_p01_owner_decision``).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_3580_web_xlsx_p01_owner_decision import decide, ready, setup_pause
from test_3580_web_xlsx_sources import OWNER, request
from app.web_xlsx_p01_engine_client import CloudflareWebXlsxP01EngineClient

STATUS = "/api/claw/office/web-selections/{}/p01-status"


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = None
        self.value = body

    async def text(self):
        return self.value


class EngineBinding:
    """Minimal private Engine Service Binding returning one fixed resume reply."""

    def __init__(self, status, result):
        self.status = status
        self.result = result
        self.calls = []

    async def fetch(self, js):
        self.calls.append(js)
        return FakeResponse(self.status, json.dumps(self.result, ensure_ascii=False))


def real_client(binding):
    """The production ``CloudflareWebXlsxP01EngineClient`` over a fake binding."""

    def make(url, *, method, headers, body):
        return SimpleNamespace(js_object={"request": len(binding.calls)})

    return CloudflareWebXlsxP01EngineClient(
        binding,
        caller_id="P01_ENGINE_B62",
        credential="secret-for-tests-only-not-real",
        request_factory=make,
    )


async def p01_status(app, settings, selection):
    return await request(
        app, settings, method="GET", owner=OWNER,
        path=STATUS.format(selection["selection_ref"]),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [
    "invalid_decision",
    "continuation_identity_mismatch",
    "invalid_verified_decision",
])
async def test_retry_safe_engine_rejection_releases_one_shot_reservation(code):
    app, settings, meta, r2, db, history, _ = ready()
    _original, selection = await setup_pause(app, settings)
    binding = EngineBinding(409, {"ok": False, "error": {"code": code}})
    app.state.web_xlsx_p01_owner_decision_client = real_client(binding)

    first = await decide(app, settings, selection, decision="approve")
    assert first.status_code == 409, first.text
    assert first.json()["error"]["code"] == "owner_p01_decision_retryable", first.text
    assert len(binding.calls) == 1
    # The Engine proved the continuation was NOT consumed, so the owner may
    # decide again: the one-shot reservation must be released, not left armed.
    receipt = db.execute(
        "SELECT state, released_at FROM claw_web_xlsx_p01_decision_receipts"
    ).fetchone()
    assert receipt["state"] == "dispatching"
    assert receipt["released_at"] is not None
    state = await p01_status(app, settings, selection)
    assert state.status_code == 200, state.text
    assert state.json()["status"] == "waiting_p01", state.text
    assert state.json()["owner_decision_enabled"] is True

    # A fresh owner action (never an automatic replay) reaches the Engine again.
    second = await decide(app, settings, selection, decision="approve")
    assert len(binding.calls) == 2
    assert second.status_code == 409, second.text
    db.close()


@pytest.mark.asyncio
async def test_ambiguous_engine_transport_result_stays_armed():
    """A genuinely unknown resume outcome must NOT be retried or released."""
    app, settings, meta, r2, db, history, _ = ready()
    _original, selection = await setup_pause(app, settings)

    class DownBinding:
        def __init__(self):
            self.calls = []

        async def fetch(self, js):
            self.calls.append(js)
            raise RuntimeError("private Engine unavailable")

    binding = DownBinding()
    app.state.web_xlsx_p01_owner_decision_client = real_client(binding)

    first = await decide(app, settings, selection, decision="approve")
    assert first.status_code == 503, first.text
    assert db.execute(
        "SELECT state FROM claw_web_xlsx_p01_decision_receipts"
    ).fetchone()["state"] == "dispatching"
    state = await p01_status(app, settings, selection)
    assert state.json()["status"] == "decision_unknown", state.text
    assert state.json()["owner_decision_enabled"] is False
    second = await decide(app, settings, selection, decision="approve")
    assert second.status_code in (409, 503)
    assert len(binding.calls) == 1
    db.close()


@pytest.mark.asyncio
async def test_retry_safe_rejection_never_creates_second_receipt_or_grant():
    """Recovery must reuse the same reservation identity, not mint a new grant."""
    app, settings, meta, r2, db, history, _ = ready()
    _original, selection = await setup_pause(app, settings)
    binding = EngineBinding(409, {"ok": False, "error": {"code": "invalid_decision"}})
    app.state.web_xlsx_p01_owner_decision_client = real_client(binding)

    await decide(app, settings, selection, decision="deny")
    rows = list(db.execute("SELECT * FROM claw_web_xlsx_p01_decision_receipts"))
    assert len(rows) == 1
    assert rows[0]["outcome"] == "deny"
    assert rows[0]["released_at"] is not None
    # No workcopy / processing grant may exist after a rejected decision.
    state = await p01_status(app, settings, selection)
    assert state.json()["workcopy_created"] is False
    assert state.json()["processing_started"] is False
    db.close()
