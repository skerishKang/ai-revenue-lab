"""B14 credential-slot status board: shape, authority, and key non-leakage.

The board reports metadata only. These tests pin two things that must not
regress: the slot -> Provider mapping comes from the same registry the gateway
dispatches with, and no key value (or any prefix longer than the sanctioned
four-character tail) reaches the response or a log record.

Every credential used here is synthetic and is set through the test process
environment or a temporary secret directory; nothing reads a real key.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path

from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.service_proof import (
    PROOF_HEADER,
    PROOF_TIME_HEADER,
    SERVICE_PROOF_BINDING,
    compute_service_proof,
)

PATH = "/api/pilot/v1/admin/credential-slots"
PROOF_SECRET = "unit-test-slot-board-proof-secret-0123456789"

AGNES = "sk-synthetic-agnes-0123456789-wxyz"
GOOGLE = "AIza-synthetic-google-abcdefghij-zsug"
INCEPTION = "sk-synthetic-inception-0123456789-mnop"
MODEL_SCOPE = "sk-synthetic-modelscope-0123456789-qrst"

EXPECTED_PROVIDERS = {
    "PADIEM_B14_CREDENTIAL_01": ["agnes-ai"],
    "PADIEM_B14_CREDENTIAL_02": ["atria"],
    "PADIEM_B14_CREDENTIAL_03": [],
    "PADIEM_B14_CREDENTIAL_04": ["experiential"],
    "PADIEM_B14_CREDENTIAL_05": ["google"],
    "PADIEM_B14_CREDENTIAL_06": ["inception"],
    "PADIEM_B14_CREDENTIAL_07": [],
    "PADIEM_B14_CREDENTIAL_08": [],
    "PADIEM_B14_CREDENTIAL_09": ["kira"],
    "PADIEM_B14_CREDENTIAL_10": ["modelscope"],
    "PADIEM_B14_CREDENTIAL_11": ["opencode-go"],
    "PADIEM_B14_CREDENTIAL_12": ["poolside"],
    "PADIEM_B14_CREDENTIAL_13": ["tokenharbor"],
    "PADIEM_B14_CREDENTIAL_14": ["zanslab"],
}


class FakeLedger:
    def __init__(self, *, last_success_at="2026-11-01T09:30:00+00:00", errors=None,
                 raises=False):
        self.last_success_at = last_success_at
        self.errors = errors if errors is not None else []
        self.raises = raises
        self.queries: list[tuple[list[str], str, int]] = []

    async def slot_activity(self, provider_ids, *, since, error_limit=10):
        self.queries.append((list(provider_ids), since, error_limit))
        if self.raises:
            raise RuntimeError("ledger driver detail that must not escape")
        if list(provider_ids) == ["agnes-ai"]:
            return {"last_success_at": self.last_success_at, "errors": self.errors}
        return {"last_success_at": None, "errors": []}


def _headers(secret=PROOF_SECRET, *, at=None):
    timestamp = str(int(time.time()) if at is None else int(at))
    return {
        PROOF_HEADER: compute_service_proof(secret, timestamp, b""),
        PROOF_TIME_HEADER: timestamp,
    }


def _seed(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv(SERVICE_PROOF_BINDING, PROOF_SECRET)
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_01", AGNES)
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_06", INCEPTION)
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_10", MODEL_SCOPE)
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    slot_file = secrets / "PADIEM_B14_CREDENTIAL_05"
    slot_file.write_text(GOOGLE, encoding="utf-8")
    if os.name == "posix":
        # The reader refuses a group/world-readable file; CI's umask otherwise
        # creates 0o644 and the slot correctly reports unresolved.
        os.chmod(slot_file, 0o600)
    monkeypatch.setenv("B14_SECRET_DIR", str(secrets))
    return secrets


def _client(store=None, *, local=False):
    if local:
        from app.local_runtime import create_local_app

        app = create_local_app()
    else:
        app = create_app()
    app.state.call_ledger_store = store
    return TestClient(app)


def test_slot_shape_comes_from_the_dispatch_registry(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    with _client(FakeLedger()) as client:
        response = client.get(PATH, headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert response.headers["cache-control"] == "no-store"
    slots = {row["slot"]: row for row in body["slots"]}
    assert [row["slot"] for row in body["slots"]] == list(EXPECTED_PROVIDERS)
    assert {slot: row["provider_ids"] for slot, row in slots.items()} == EXPECTED_PROVIDERS
    assert body["registry"] == "loaded"
    assert body["ledger"] == {"state": "bound", "error_window_hours": 168}

    agnes = slots["PADIEM_B14_CREDENTIAL_01"]
    assert agnes["configured"] is True
    assert agnes["state"] == "configured"
    assert agnes["length"] == len(AGNES)
    assert agnes["last4"] == AGNES[-4:]

    empty = slots["PADIEM_B14_CREDENTIAL_03"]
    assert empty["configured"] is False
    assert empty["state"] == "empty"
    assert empty["length"] is None
    assert empty["last4"] is None


def test_file_backed_slot_reports_file_mtime(monkeypatch, tmp_path):
    secrets = _seed(monkeypatch, tmp_path)
    stamp = time.time() - 3600
    os.utime(secrets / "PADIEM_B14_CREDENTIAL_05", (stamp, stamp))
    # The file leg is read by the COM2 adapter's request-scope reader, which is
    # the same reader the Provider lane uses on that host.
    monkeypatch.chdir(tmp_path)
    with _client(FakeLedger(), local=True) as client:
        response = client.get(PATH, headers=_headers())
    google = {row["slot"]: row for row in response.json()["slots"]}["PADIEM_B14_CREDENTIAL_05"]
    assert google["configured"] is True
    assert google["last4"] == "zsug"
    assert google["file_modified_source"] == "secret_file"
    assert google["file_modified_at"] is not None
    assert abs(datetime.fromisoformat(google["file_modified_at"]).timestamp() - stamp) < 1


def test_environment_file_mtime_is_reported_only_when_it_declares_the_slot(
    monkeypatch, tmp_path,
):
    _seed(monkeypatch, tmp_path)
    env_file = tmp_path / "b14.env"
    env_file.write_text(
        "B14_PROVIDER_MODE=live\n"
        "PADIEM_B14_CREDENTIAL_09=sk-synthetic-kira-0123456789-aaaa\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("B14_CREDENTIAL_ENV_FILE", str(env_file))
    stamp = time.time() - 7200
    os.utime(env_file, (stamp, stamp))
    with _client(FakeLedger()) as client:
        rows = {row["slot"]: row for row in client.get(PATH, headers=_headers()).json()["slots"]}
    assert rows["PADIEM_B14_CREDENTIAL_09"]["file_modified_source"] == "env_file"
    assert rows["PADIEM_B14_CREDENTIAL_09"]["file_modified_at"] is not None
    # A slot the environment file does not declare gets no mtime from it.
    assert rows["PADIEM_B14_CREDENTIAL_02"]["file_modified_source"] == "none"
    assert rows["PADIEM_B14_CREDENTIAL_02"]["file_modified_at"] is None


def test_ledger_activity_is_bounded_and_sanitized(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    ledger = FakeLedger(errors=[
        {"code": "provider_timeout", "count": 4},
        {"code": "upstream_rejected", "count": 2},
        {"code": "bad code with spaces", "count": 9},
        {"code": "x", "count": -1},
    ])
    with _client(ledger) as client:
        rows = {row["slot"]: row for row in client.get(PATH, headers=_headers()).json()["slots"]}
    agnes = rows["PADIEM_B14_CREDENTIAL_01"]
    assert agnes["last_success_at"] == "2026-11-01T09:30:00+00:00"
    assert agnes["recent_error_codes"] == [
        {"code": "provider_timeout", "count": 4},
        {"code": "upstream_rejected", "count": 2},
    ]
    assert ledger.queries and ledger.queries[0][0] == ["agnes-ai"]
    # Slots with no Provider never ask the ledger at all, so eleven slots query.
    assert len(ledger.queries) == 11


def test_unavailable_ledger_is_not_reported_as_zero(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    with _client(FakeLedger(raises=True)) as client:
        body = client.get(PATH, headers=_headers()).json()
    assert body["ledger"]["state"] == "unavailable"
    for row in body["slots"]:
        assert row["last_success_at"] is None
        assert row["recent_error_codes"] == []


def test_unconfigured_ledger_is_reported_truthfully(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    with _client(None) as client:
        body = client.get(PATH, headers=_headers()).json()
    assert body["ledger"]["state"] == "not_configured"
    assert all(row["recent_error_codes"] == [] for row in body["slots"])


def test_placeholder_value_is_not_configurable_and_exposes_no_tail(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_02", "sk-your-placeholder-key")
    with _client(FakeLedger()) as client:
        rows = {row["slot"]: row for row in client.get(PATH, headers=_headers()).json()["slots"]}
    atria = rows["PADIEM_B14_CREDENTIAL_02"]
    assert atria["configured"] is False
    assert atria["state"] == "placeholder"
    assert atria["length"] is None
    assert atria["last4"] is None


def test_anonymous_and_unproven_callers_are_refused(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    with _client(FakeLedger()) as client:
        anonymous = client.get(PATH)
        wrong = client.get(PATH, headers=_headers("a-different-proof-secret-0123456789"))
        stale = client.get(PATH, headers=_headers(at=time.time() - 3600))
    assert anonymous.status_code == 401
    assert anonymous.json()["error"]["code"] == "b14_service_proof_required"
    assert wrong.status_code == 401
    assert stale.status_code == 401


def test_missing_proof_secret_fails_closed(monkeypatch, tmp_path):
    _seed(monkeypatch, tmp_path)
    monkeypatch.delenv(SERVICE_PROOF_BINDING, raising=False)
    with _client(FakeLedger()) as client:
        response = client.get(PATH, headers=_headers())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "b14_service_proof_unconfigured"


def test_no_key_value_reaches_the_response_or_a_log_record(monkeypatch, tmp_path, caplog):
    _seed(monkeypatch, tmp_path)
    values = (AGNES, GOOGLE, INCEPTION, MODEL_SCOPE)
    caplog.set_level(logging.DEBUG)
    monkeypatch.chdir(tmp_path)
    with _client(FakeLedger(), local=True) as client:
        response = client.get(PATH, headers=_headers())
    body = response.text
    log_text = "\n".join(
        record.getMessage() for record in caplog.records
    )
    for value in values:
        assert value not in body
        assert value not in log_text
        # A prefix of the key is as sensitive as the key: only the sanctioned
        # four-character tail may ever be derived from it.
        assert value[:-4] not in body
        assert value[:8] not in body
        assert value[:8] not in log_text
    # The sanctioned tail and length are the only value-derived facts present.
    slots = {row["slot"]: row for row in response.json()["slots"]}
    assert AGNES[-4:] in body
    assert slots["PADIEM_B14_CREDENTIAL_01"]["length"] == len(AGNES)
    assert slots["PADIEM_B14_CREDENTIAL_05"]["length"] == len(GOOGLE)
