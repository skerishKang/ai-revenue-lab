"""B14 credential-slot status board: shape, authority, and key non-leakage.

The board reports metadata only. These tests pin two things that must not
regress: the slot -> Provider mapping comes from the same registry the gateway
dispatches with, and no key value (or any prefix longer than the sanctioned
four-character tail) reaches the response or a log record.

Every credential used here is synthetic and is set through the test process
environment or a temporary secret directory; nothing reads a real key.

#7241: the slot -> Provider mapping and every binding name are read from the
effective registry, so this suite carries no deployment value of its own.
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

from _registry_values import registry

PATH = "/api/pilot/v1/admin/credential-slots"
PROOF_SECRET = "unit-test-slot-board-proof-secret-0123456789"

def _slot_bindings() -> tuple[str, ...]:
    """The stable slot names the deployment declares, from the board itself."""
    from app.pilot.credential_slots_admin import SLOT_BINDINGS

    return tuple(SLOT_BINDINGS)


def expected_providers() -> dict[str, list[str]]:
    """Slot -> Provider ids, derived exactly the way the board derives them."""
    from app.pilot.credential_slots_admin import _providers_by_slot

    expected, state = _providers_by_slot()
    assert state == "loaded"
    return expected


def slot_of(provider_id: str) -> str:
    """The binding name the registry declares for a Provider."""
    return registry()["providers"][provider_id]["credential_binding_name"]


def binding_owner(binding: str) -> str | None:
    """The Provider a slot carries, or None when no Provider declares it."""
    carried = EXPECTED_PROVIDERS.get(binding) or []
    return carried[0] if carried else None


# Pinned by the deployment's own slot list, not by a hand-kept copy: the board
# lists every declared slot, including one no Provider carries.
SLOTS = _slot_bindings()
EXPECTED_PROVIDERS = expected_providers()
assert tuple(EXPECTED_PROVIDERS) == SLOTS

# The roles this suite exercises are chosen from the registry shape, never from
# a declared name: three Provider-bearing slots hold a configured value (one of
# them through the file leg), one slot holds no Provider at all, one slot is
# declared only by the environment file, and one keeps the placeholder check.
_CARRIED = [slot for slot, ids in EXPECTED_PROVIDERS.items() if ids]
EMPTY_SLOT = next(slot for slot, ids in EXPECTED_PROVIDERS.items() if not ids)
_KEY_SLOTS = _CARRIED[:3]
# One role's value lives in the secret file rather than in the environment.
_FILE_SLOT = _KEY_SLOTS[1]
_ENV_SLOT = _CARRIED[3]
_PLACEHOLDER_SLOT = _CARRIED[4]

# Synthetic values, one per role, so no real key shape is reproduced here.
KEY_VALUES = [
    f"sk-synthetic-role-{index}-0123456789-wxyz" for index in range(len(_KEY_SLOTS))
]
KEY_BY_SLOT = dict(zip(_KEY_SLOTS, KEY_VALUES))
ENV_SLOT_VALUE = "sk-synthetic-envfile-0123456789-lmnop"
PLACEHOLDER_VALUE = "sk-your-placeholder-key"

# The environment-file leg declares its own slot and value.
ENV_FILE_LINE = f"{_ENV_SLOT}={ENV_SLOT_VALUE}"
# The board reports only the sanctioned four-character tail of a value.
TAIL_LENGTH = 4


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
        if list(provider_ids) == EXPECTED_PROVIDERS[_KEY_SLOTS[0]]:
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
    for slot in _KEY_SLOTS:
        if slot == _FILE_SLOT:
            continue
        monkeypatch.setenv(slot, KEY_BY_SLOT[slot])
    secrets = tmp_path / "secrets"
    secrets.mkdir(mode=0o700)
    slot_file = secrets / _FILE_SLOT
    slot_file.write_text(KEY_BY_SLOT[_FILE_SLOT], encoding="utf-8")
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

    filled = slots[_KEY_SLOTS[0]]
    assert filled["configured"] is True
    assert filled["state"] == "configured"
    assert filled["provider_ids"] == EXPECTED_PROVIDERS[_KEY_SLOTS[0]]
    assert filled["length"] == len(KEY_BY_SLOT[_KEY_SLOTS[0]])
    assert filled["last4"] == KEY_BY_SLOT[_KEY_SLOTS[0]][-TAIL_LENGTH:]

    empty = slots[EMPTY_SLOT]
    assert empty["configured"] is False
    assert empty["state"] == "empty"
    assert empty["length"] is None
    assert empty["last4"] is None


def test_file_backed_slot_reports_file_mtime(monkeypatch, tmp_path):
    secrets = _seed(monkeypatch, tmp_path)
    stamp = time.time() - 3600
    os.utime(secrets / _FILE_SLOT, (stamp, stamp))
    # The file leg is read by the COM2 adapter's request-scope reader, which is
    # the same reader the Provider lane uses on that host.
    monkeypatch.chdir(tmp_path)
    with _client(FakeLedger(), local=True) as client:
        response = client.get(PATH, headers=_headers())
    from_file = {row["slot"]: row for row in response.json()["slots"]}[_FILE_SLOT]
    assert from_file["configured"] is True
    assert from_file["provider_ids"] == EXPECTED_PROVIDERS[_FILE_SLOT]
    assert from_file["last4"] == KEY_BY_SLOT[_FILE_SLOT][-TAIL_LENGTH:]
    assert from_file["file_modified_source"] == "secret_file"
    assert from_file["file_modified_at"] is not None
    assert abs(
        datetime.fromisoformat(from_file["file_modified_at"]).timestamp() - stamp
    ) < 1


def test_environment_file_mtime_is_reported_only_when_it_declares_the_slot(
    monkeypatch, tmp_path,
):
    _seed(monkeypatch, tmp_path)
    env_file = tmp_path / "b14.env"
    env_file.write_text(
        "B14_PROVIDER_MODE=live\n" + f"{ENV_FILE_LINE}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("B14_CREDENTIAL_ENV_FILE", str(env_file))
    stamp = time.time() - 7200
    os.utime(env_file, (stamp, stamp))
    with _client(FakeLedger()) as client:
        rows = {row["slot"]: row for row in client.get(PATH, headers=_headers()).json()["slots"]}
    assert rows[_ENV_SLOT]["file_modified_source"] == "env_file"
    assert rows[_ENV_SLOT]["file_modified_at"] is not None
    # A slot the environment file does not declare gets no mtime from it.
    assert rows[_PLACEHOLDER_SLOT]["file_modified_source"] == "none"
    assert rows[_PLACEHOLDER_SLOT]["file_modified_at"] is None


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
    filled = rows[_KEY_SLOTS[0]]
    assert filled["last_success_at"] == "2026-11-01T09:30:00+00:00"
    assert filled["recent_error_codes"] == [
        {"code": "provider_timeout", "count": 4},
        {"code": "upstream_rejected", "count": 2},
    ]
    assert ledger.queries and ledger.queries[0][0] == EXPECTED_PROVIDERS[_KEY_SLOTS[0]]
    # Slots with no Provider never ask the ledger at all, so only Provider-bearing
    # slots query the ledger.
    assert len(ledger.queries) == sum(1 for ids in EXPECTED_PROVIDERS.values() if ids)


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
    monkeypatch.setenv(_PLACEHOLDER_SLOT, PLACEHOLDER_VALUE)
    with _client(FakeLedger()) as client:
        rows = {row["slot"]: row for row in client.get(PATH, headers=_headers()).json()["slots"]}
    placeholder = rows[_PLACEHOLDER_SLOT]
    assert placeholder["configured"] is False
    assert placeholder["provider_ids"] == EXPECTED_PROVIDERS[_PLACEHOLDER_SLOT]
    assert placeholder["state"] == "placeholder"
    assert placeholder["length"] is None
    assert placeholder["last4"] is None


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
    values = tuple(KEY_BY_SLOT[slot] for slot in _KEY_SLOTS)
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
        assert value[:-TAIL_LENGTH] not in body
        assert value[:8] not in body
        assert value[:8] not in log_text
    # The sanctioned tail and length are the only value-derived facts present.
    slots = {row["slot"]: row for row in response.json()["slots"]}
    assert KEY_BY_SLOT[_KEY_SLOTS[0]][-TAIL_LENGTH:] in body
    for index, slot in enumerate(_KEY_SLOTS):
        assert slots[slot]["length"] == len(KEY_VALUES[index])
