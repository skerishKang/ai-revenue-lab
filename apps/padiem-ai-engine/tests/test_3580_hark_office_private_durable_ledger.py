"""Private #3580 Engine verified receipt -> exact owner/Broker durable one-shot relay."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

# Preserve sibling test fixture import under both root and per-app pytest runs.
sys.path.insert(0, str(Path(__file__).parent))

import pytest

from app.hark_office_p01_durable_ledger import (
    PrivateDurableOfficeReadLedger, TrustedOfficeReadCommandBinding,
)
from test_3580_hark_office_p01_binding import _actual_approved_office_resume, _args


def binding(**overrides):
    args = _args(listing=False)
    values = dict(
        owner_id="owner_3580_a", workspace_id="workspace_3580",
        session_id="session_3580", run_id=args["run_id"],
        device_id=args["device_id"], root_ref=args["root_ref"],
        request_fingerprint=args["request_fingerprint"],
        binding_ref="bound_device_3580", command_id="cmd_3580",
        tool_request_ref="tool_req_3580", request_id="request_3580",
        revision_ref="revision_3580", command_fingerprint="a" * 64,
        sequence=1,
    )
    values.update(overrides)
    return TrustedOfficeReadCommandBinding(**values)


@pytest.mark.asyncio
async def test_engine_real_verified_read_persisted_redeemed_once_after_restart(tmp_path):
    database = tmp_path / "private-office.db"
    exact = binding()
    ledger = PrivateDurableOfficeReadLedger(
        database_path=database, trusted_binding_resolver=lambda receipt: exact,
    )
    result, engine, store, replay, _ = await _actual_approved_office_resume(
        listing=False, sink=ledger,
    )
    assert result.status_code == 200, result.body
    assert "first_party_verified_session" not in str(result.body)
    assert "command_fingerprint" not in str(result.body)
    assert database.exists()
    reopened = PrivateDurableOfficeReadLedger(
        database_path=database, trusted_binding_resolver=lambda receipt: exact,
    )
    assert reopened.redeem_for_trusted_command(replace(exact, session_id="other_session")) is None
    assert reopened.redeem_for_trusted_command(replace(exact, command_id="other_cmd")) is None
    assert reopened.redeem_for_trusted_command(replace(exact, device_id="other_dev")) is None
    assert reopened.redeem_for_trusted_command(replace(exact, owner_id="other_owner")) is None
    assert reopened.redeem_for_trusted_command(replace(exact, workspace_id="other_workspace")) is None
    assert reopened.redeem_for_trusted_command(replace(exact, run_id="other_run")) is None
    assert reopened.redeem_for_trusted_command(replace(exact, sequence=2)) is None
    approved = reopened.redeem_for_trusted_command(exact)
    assert approved is not None
    assert approved.binding == exact
    assert approved.receipt.request_fingerprint == exact.request_fingerprint
    assert approved.receipt.verified_decision.outcome.value == "approved"
    assert reopened.redeem_for_trusted_command(exact) is None
    assert ledger.redeem_for_trusted_command(exact) is None
    duplicate = await engine.resume_payload(replay)
    assert duplicate.status_code != 200


@pytest.mark.asyncio
async def test_no_prior_authenticated_command_binding_fails_engine_closed(tmp_path):
    db = tmp_path / "private-office.db"
    ledger = PrivateDurableOfficeReadLedger(
        database_path=db, trusted_binding_resolver=lambda receipt: None,
    )
    outcome, engine, store, replay, _ = await _actual_approved_office_resume(
        listing=False, sink=ledger,
    )
    assert outcome.status_code == 503
    assert outcome.body["error"]["code"] == "office_approval_receipt_unavailable"
    assert ledger.redeem_for_trusted_command(binding()) is None
    assert (await engine.resume_payload(replay)).status_code != 200


@pytest.mark.asyncio
async def test_foreign_command_cannot_bless_verified_engine_receipt(tmp_path):
    exact = binding(device_id="foreign_device")
    ledger = PrivateDurableOfficeReadLedger(
        database_path=tmp_path / "private-office.db",
        trusted_binding_resolver=lambda receipt: exact,
    )
    outcome, *_ = await _actual_approved_office_resume(listing=False, sink=ledger)
    assert outcome.status_code == 503
    assert ledger.redeem_for_trusted_command(exact) is None


@pytest.mark.asyncio
async def test_list_only_never_produces_read_receipt(tmp_path):
    exact = binding()
    ledger = PrivateDurableOfficeReadLedger(
        database_path=tmp_path / "private-office.db",
        trusted_binding_resolver=lambda receipt: exact,
    )
    result, *_ = await _actual_approved_office_resume(listing=True, sink=ledger)
    assert result.status_code == 200
    assert ledger.redeem_for_trusted_command(exact) is None


@pytest.mark.asyncio
async def test_expired_one_shot_evidence_unavailable_without_dispatch(tmp_path):
    now = datetime.now(timezone.utc)
    clock = [now]
    exact = binding()
    ledger = PrivateDurableOfficeReadLedger(
        database_path=tmp_path / "private-office.db",
        trusted_binding_resolver=lambda receipt: exact,
        clock=lambda: clock[0],
    )
    result, *_ = await _actual_approved_office_resume(listing=False, sink=ledger)
    assert result.status_code == 200
    clock[0] = now + timedelta(minutes=6)
    assert ledger.redeem_for_trusted_command(exact) is None


def test_reject_public_or_incomplete_command_binding(tmp_path):
    with pytest.raises(ValueError):
        binding(sequence=True)
    with pytest.raises(ValueError):
        binding(owner_id="../owner")
    with pytest.raises(ValueError):
        binding(command_fingerprint="not_sha")
    with pytest.raises(ValueError):
        PrivateDurableOfficeReadLedger(
            database_path=tmp_path / "private-office.db",
            trusted_binding_resolver=None,
        )
    # The ledger does NOT have a browser endpoint, file-reading port or local grant.
    from app.hark_office_p01_durable_ledger import (
        PRIVATE_LEDGER_MINTS_DEVICE_GRANT, PRIVATE_LEDGER_HAS_PUBLIC_HTTP_ROUTE,
    )
    assert PRIVATE_LEDGER_MINTS_DEVICE_GRANT is False
    assert PRIVATE_LEDGER_HAS_PUBLIC_HTTP_ROUTE is False


@pytest.mark.asyncio
async def test_parallel_redeem_is_globally_one_shot_across_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    exact = binding()
    path = tmp_path / "private-office.db"
    ledger = PrivateDurableOfficeReadLedger(
        database_path=path, trusted_binding_resolver=lambda receipt: exact,
    )
    result, *_ = await _actual_approved_office_resume(listing=False, sink=ledger)
    assert result.status_code == 200

    def redeem(_):
        other = PrivateDurableOfficeReadLedger(
            database_path=path, trusted_binding_resolver=lambda receipt: exact,
        )
        return other.redeem_for_trusted_command(exact)

    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(redeem, range(4)))
    assert sum(value is not None for value in values) == 1


@pytest.mark.asyncio
async def test_modified_stored_invocation_fails_closed_without_consuming(tmp_path):
    import json
    import sqlite3
    exact = binding()
    path = tmp_path / "private-office.db"
    ledger = PrivateDurableOfficeReadLedger(
        database_path=path, trusted_binding_resolver=lambda receipt: exact,
    )
    result, *_ = await _actual_approved_office_resume(listing=False, sink=ledger)
    assert result.status_code == 200
    with sqlite3.connect(path) as db:
        encoded = db.execute(
            "SELECT receipt_json FROM office_read_receipt_v1 WHERE request_fingerprint=?",
            (exact.request_fingerprint,),
        ).fetchone()[0]
        payload = json.loads(encoded)
        payload["exact_tool_arguments"] = [
            [name, "other.xlsx" if name == "path_relative" else value]
            for name, value in payload["exact_tool_arguments"]
        ]
        db.execute(
            "UPDATE office_read_receipt_v1 SET receipt_json=? WHERE request_fingerprint=?",
            (json.dumps(payload), exact.request_fingerprint),
        )
    with pytest.raises(ValueError):
        ledger.redeem_for_trusted_command(exact)
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT consumed_at FROM office_read_receipt_v1 WHERE request_fingerprint=?",
            (exact.request_fingerprint,),
        ).fetchone()[0] is None
