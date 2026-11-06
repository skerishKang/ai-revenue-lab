"""Owner model-console writes on B14: overlay, probe gate, key file hygiene.

The base registry stays the shipped catalog; the Owner writes an overlay next to
it. These tests pin the four promises the screen depends on: the overlay is what
the next read (and the next boot) sees, a model can only be registered after a
probe receipt for that exact row, retirement removes the model from the effective
catalog while remaining reversible, and a credential write touches only its own
governed slot file while never returning, logging or auditing the value.

Every credential here is synthetic and lives in a temporary directory.
"""

from __future__ import annotations

import json
import os
import stat
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import model_admin_ops as ops
from app.pilot.model_registry_file import read_overlay, read_registry, write_overlay
from app.pilot.service_proof import PROOF_HEADER, PROOF_TIME_HEADER, compute_service_proof

PREFIX = "/api/pilot"
REGISTRY = PREFIX + ops.REGISTRY_PATH
PROBE = PREFIX + ops.PROBE_PATH
MODEL_APPLY = PREFIX + ops.MODEL_APPLY_PATH
MODEL_RETIRE = PREFIX + ops.MODEL_RETIRE_PATH
PROVIDER_APPLY = PREFIX + ops.PROVIDER_APPLY_PATH
CREDENTIAL_WRITE = PREFIX + ops.CREDENTIAL_WRITE_PATH
AUDIT = PREFIX + ops.AUDIT_PATH

PROOF_SECRET = "unit-test-model-admin-proof-secret-0123456789"
SYNTHETIC_VALUE = "sk-synthetic-owner-value-0123456789-wxyz"
EXISTING_LINE_VALUE = "sk-synthetic-previous-0123456789-abcd"

PROVIDER = {
    "provider_id": "example",
    "base_origin": "https://api.example.com",
    "allowed_hosts": ["api.example.com"],
    "credential_source": "platform_secret",
    "credential_binding_name": "PADIEM_B14_CREDENTIAL_07",
    "enabled": True,
}

MODEL = {
    "id": "example/chat-1",
    "provider_id": "example",
    "upstream_model": "chat-1",
    "display_name": "Example Chat 1",
    "provider_name": "Example",
    "capabilities": ["chat"],
    "context_window": 8192,
    "input_price_usd_per_1m": 0.5,
    "output_price_usd_per_1m": 1.5,
    "source": "https://example.com/pricing",
    "source_checked_at": "2026-11-03T00:00:00Z",
    "enabled": True,
}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    base = tmp_path / "b14_models.json"
    base.write_bytes(
        (Path(ops.__file__).parent / "b14_models.json").read_bytes()
    )
    overlay = tmp_path / "b14_models.overrides.json"
    monkeypatch.setenv("B14_REGISTRY_PATH", str(base))
    monkeypatch.setenv("B14_REGISTRY_OVERLAY_PATH", str(overlay))
    return base


@pytest.fixture
def client(registry, monkeypatch, tmp_path):
    monkeypatch.setenv("PADIEM_B14_SERVICE_PROOF_SECRET", PROOF_SECRET)
    monkeypatch.delenv("B14_CREDENTIAL_ENV_FILE", raising=False)
    monkeypatch.delenv("B14_SECRET_DIR", raising=False)
    monkeypatch.delenv("PADIEM_B14_CREDENTIAL_07", raising=False)
    # A write also mirrors the value into os.environ for the running process.
    # Absent keys are recorded via setenv so teardown really removes them and
    # the next test (which asserts on slot truth) sees the real environment.
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_05", "")
    monkeypatch.setenv("PADIEM_B14_CREDENTIAL_06", "")
    ops._RECEIPTS.clear()
    app = create_app()
    installed: list[dict] = []
    monkeypatch.setattr(ops, "_install", lambda effective: installed.append(effective))
    app.state.model_admin_installed = installed
    return TestClient(app)


def _proof(secret, raw: bytes, *, at=None):
    timestamp = str(int(time.time()) if at is None else int(at))
    return {
        PROOF_HEADER: compute_service_proof(secret, timestamp, raw),
        PROOF_TIME_HEADER: timestamp,
    }


def post(client, path, payload, *, secret=PROOF_SECRET, proof=True):
    raw = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json"}
    if proof:
        headers.update(_proof(secret, raw))
    return client.post(path, content=raw, headers=headers)


def get(client, path, *, secret=PROOF_SECRET):
    return client.get(path, headers=_proof(secret, b""))


def _receipt(model_row, provider_row=None):
    return {
        "expires": time.time() + 600,
        "fingerprint": ops._fingerprint(model_row),
        "model_id": model_row["id"],
        "provider_fingerprint": ops._fingerprint(provider_row) if provider_row else None,
    }


# --- caller proof ------------------------------------------------------------

def test_every_route_requires_the_caller_proof(client):
    for path, payload in (
        (REGISTRY, None), (PROBE, {"model": MODEL}),
        (MODEL_APPLY, {"model": MODEL}), (MODEL_RETIRE, {"model_id": MODEL["id"]}),
        (PROVIDER_APPLY, {"provider": PROVIDER}), (CREDENTIAL_WRITE, {}),
        (AUDIT, None),
    ):
        response = (
            client.get(path) if payload is None
            else post(client, path, payload, proof=False)
        )
        assert response.status_code == 401, path
        assert response.json()["error"]["code"] == "b14_service_proof_required"


def test_unconfigured_proof_secret_fails_closed(client, monkeypatch):
    monkeypatch.delenv("PADIEM_B14_SERVICE_PROOF_SECRET")
    response = get(client, REGISTRY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "b14_service_proof_unconfigured"


# --- registry read -----------------------------------------------------------

def test_registry_read_reports_the_effective_catalog(client):
    response = get(client, REGISTRY)
    assert response.status_code == 200
    body = response.json()
    registry = read_registry()
    assert body["ok"] is True
    assert len(body["providers"]) == len(registry["providers"])
    assert len(body["models"]) == len(registry["models"])
    assert len(body["slot_usage"]) == 14
    assert body["overlay"]["present"] is False
    assert SYNTHETIC_VALUE not in response.text


# --- provider ----------------------------------------------------------------

def test_provider_apply_writes_the_overlay_and_returns_counts(client):
    response = post(client, PROVIDER_APPLY, {"provider": PROVIDER})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["provider_id"] == "example"
    assert body["provider_count"] == len(read_registry()["providers"])
    assert body["overlay"]["present"] is True
    assert read_overlay()["providers"]["example"]["base_origin"] == "https://api.example.com"
    assert "example" in read_registry()["providers"]
    assert client.app.state.model_admin_installed[-1]["providers"]["example"]


def test_provider_apply_refuses_a_binding_outside_the_governed_slots(client):
    row = {**PROVIDER, "credential_binding_name": "PADIEM_B14_CREDENTIAL_99"}
    response = post(client, PROVIDER_APPLY, {"provider": row})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_binding_not_a_governed_slot"
    assert not read_overlay()


def test_provider_apply_refuses_an_unknown_field(client):
    row = {**PROVIDER, "api_key": SYNTHETIC_VALUE}
    response = post(client, PROVIDER_APPLY, {"provider": row})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_unknown_field"
    assert SYNTHETIC_VALUE not in response.text
    assert not read_overlay()


def test_provider_apply_refuses_a_full_slot(client):
    from app.pilot.model_registry_file import write_overlay

    filler = {
        f"filler{index}": {
            "base_origin": f"https://filler{index}.example.com",
            "allowed_hosts": [f"filler{index}.example.com"],
            "credential_source": "platform_secret",
            "credential_binding_name": "PADIEM_B14_CREDENTIAL_14",
            "enabled": False,
        }
        for index in range(8)
    }
    write_overlay({"providers": filler})
    payload = {"provider": {**PROVIDER, "credential_binding_name": "PADIEM_B14_CREDENTIAL_14"}}
    response = post(client, PROVIDER_APPLY, payload)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credential_slot_full"


def test_provider_apply_maps_a_registry_rejection(client, monkeypatch):
    def _reject(update, path=None):
        raise read_registry_error()

    from app.pilot.model_registry_file import ModelRegistryError

    read_registry_error = ModelRegistryError
    monkeypatch.setattr(ops._registry(), "write_overlay", _reject)
    response = post(client, PROVIDER_APPLY, {"provider": PROVIDER})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_invalid"


# --- model registration needs a receipt for that exact row -------------------

def test_model_apply_refuses_without_a_probe_receipt(client):
    response = post(client, MODEL_APPLY, {"model": MODEL, "provider": PROVIDER})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_probe_required"
    assert not read_overlay()


def test_model_apply_refuses_a_receipt_for_a_different_row(client):
    other = {**MODEL, "context_window": 4096}
    ops._RECEIPTS["tkn"] = _receipt(other, PROVIDER)
    response = post(client, MODEL_APPLY, {
        "model": MODEL, "provider": PROVIDER, "probe_id": "tkn",
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_probe_stale"
    assert not read_overlay()


def test_model_apply_with_a_matching_receipt_registers_the_model(client):
    cleaned, reason = ops._clean_model(MODEL)
    assert cleaned is not None, reason
    provider = {k: v for k, v in PROVIDER.items() if k != "provider_id"}
    ops._RECEIPTS["tkn"] = _receipt(cleaned, provider)
    response = post(client, MODEL_APPLY, {
        "model": MODEL, "provider": PROVIDER, "probe_id": "tkn",
    })
    assert response.status_code == 200, response.text
    assert response.json()["model"]["id"] == MODEL["id"]
    effective = read_registry()
    assert MODEL["id"] in {row["id"] for row in effective["models"]}
    assert "example" in effective["providers"]
    assert ops._RECEIPTS == {}


def test_model_apply_keeps_an_existing_reasoning_block(client):
    provider = {k: v for k, v in PROVIDER.items() if k != "provider_id"}
    reasoning = {
        "supported": True,
        "values": ["minimal", "low", "medium", "high"],
    }
    write_overlay({
        "providers": {"example": provider},
        "models": [{**MODEL, "reasoning": reasoning}],
    })
    assert read_overlay()["models"][0]["reasoning"] == reasoning

    cleaned, reason = ops._clean_model(MODEL)
    assert cleaned is not None, reason
    ops._RECEIPTS["tkn"] = _receipt(cleaned)

    response = post(client, MODEL_APPLY, {"model": MODEL, "probe_id": "tkn"})
    assert response.status_code == 200, response.text

    overlay_row = next(row for row in read_overlay()["models"] if row["id"] == MODEL["id"])
    assert overlay_row["reasoning"] == reasoning
    effective_row = next(row for row in read_registry()["models"] if row["id"] == MODEL["id"])
    assert effective_row["reasoning"] == reasoning


def test_model_apply_does_not_invent_a_reasoning_block(client):
    provider = {k: v for k, v in PROVIDER.items() if k != "provider_id"}
    write_overlay({"providers": {"example": provider}, "models": [MODEL]})
    assert "reasoning" not in read_overlay()["models"][0]

    cleaned, reason = ops._clean_model(MODEL)
    assert cleaned is not None, reason
    ops._RECEIPTS["tkn"] = _receipt(cleaned)

    response = post(client, MODEL_APPLY, {"model": MODEL, "probe_id": "tkn"})
    assert response.status_code == 200, response.text

    overlay_row = next(row for row in read_overlay()["models"] if row["id"] == MODEL["id"])
    assert "reasoning" not in overlay_row
    effective_row = next(row for row in read_registry()["models"] if row["id"] == MODEL["id"])
    assert "reasoning" not in effective_row


def test_model_apply_refuses_a_retired_identity(client):
    cleaned, reason = ops._clean_model(MODEL)
    assert cleaned is not None, reason
    provider = {k: v for k, v in PROVIDER.items() if k != "provider_id"}
    ops._RECEIPTS["tkn"] = _receipt(cleaned, provider)
    assert post(client, MODEL_APPLY, {
        "model": MODEL, "provider": PROVIDER, "probe_id": "tkn",
    }).status_code == 200

    retired = post(client, MODEL_RETIRE, {"model_id": MODEL["id"], "retire": True})
    assert retired.status_code == 200, retired.text

    ops._RECEIPTS["tkn2"] = _receipt(cleaned, provider)
    response = post(client, MODEL_APPLY, {
        "model": MODEL, "provider": PROVIDER, "probe_id": "tkn2",
    })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_is_retired"


# --- retirement is reversible ------------------------------------------------

def test_retire_then_restore_round_trips_the_effective_catalog(client):
    retired_id = read_registry()["models"][0]["id"]

    retired = post(client, MODEL_RETIRE, {"model_id": retired_id, "retire": True})
    assert retired.status_code == 200, retired.text
    effective = read_registry()
    assert retired_id not in {row["id"] for row in effective["models"]}
    assert retired_id in effective["retired_models"]
    assert retired_id not in (read_overlay().get("models") or [])
    assert all(retired_id not in ids for ids in effective["groups"].values())

    restored = post(client, MODEL_RETIRE, {"model_id": retired_id, "retire": False})
    assert restored.status_code == 200, restored.text
    effective = read_registry()
    assert retired_id in {row["id"] for row in effective["models"]}
    assert retired_id not in (effective.get("retired_models") or [])


def test_retire_an_unknown_model_is_not_reported_as_success(client):
    response = post(client, MODEL_RETIRE, {"model_id": "example/nope"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_registered"


def test_restore_a_model_that_is_not_retired_is_a_conflict(client):
    response = post(client, MODEL_RETIRE, {"model_id": "example/nope", "retire": False})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_not_retired"


# --- credential slot write ---------------------------------------------------

def test_credential_write_refuses_a_slot_outside_the_assignment(client, tmp_path):
    monkeypatch_env = os.environ.get("B14_CREDENTIAL_ENV_FILE")
    os.environ["B14_CREDENTIAL_ENV_FILE"] = str(tmp_path / "b14.env")
    try:
        response = post(client, CREDENTIAL_WRITE, {"slot_number": 15, "value": SYNTHETIC_VALUE})
    finally:
        if monkeypatch_env is None:
            os.environ.pop("B14_CREDENTIAL_ENV_FILE", None)
        else:
            os.environ["B14_CREDENTIAL_ENV_FILE"] = monkeypatch_env
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "slot_not_governed"


def test_credential_write_refuses_a_placeholder_value(client, tmp_path, monkeypatch):
    monkeypatch.setenv("B14_CREDENTIAL_ENV_FILE", str(tmp_path / "b14.env"))
    response = post(client, CREDENTIAL_WRITE, {"slot_number": 5, "value": "sk-your-key-here"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "credential_value_placeholder"


def test_credential_write_refuses_when_the_store_manages_the_slot(client, tmp_path, monkeypatch):
    from app.pilot import worker_env

    slot_binding = "PADIEM_B14_CREDENTIAL_05"
    env_file = tmp_path / "b14.env"
    monkeypatch.setenv("B14_CREDENTIAL_ENV_FILE", str(env_file))

    def _status(name):
        return "resolved" if name == slot_binding else ""

    def _scoped(name):
        return "s" * 40 if name == slot_binding else None

    monkeypatch.setattr(worker_env, "secret_status", _status)
    monkeypatch.setattr(worker_env, "scoped_secret", _scoped)

    response = post(client, CREDENTIAL_WRITE, {"slot_number": 5, "value": SYNTHETIC_VALUE})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "credential_write_store_managed"
    assert not env_file.exists()


def test_credential_write_needs_a_configured_target(client):
    response = post(client, CREDENTIAL_WRITE, {"slot_number": 5, "value": SYNTHETIC_VALUE})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "credential_write_unconfigured"


def test_env_file_write_preserves_other_lines_backs_up_and_never_echoes(
    client, tmp_path, monkeypatch,
):
    env_file = tmp_path / "b14.env"
    env_file.write_text(
        "OTHER_SETTING=keep-me\nPADIEM_B14_CREDENTIAL_05=" + EXISTING_LINE_VALUE + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("B14_CREDENTIAL_ENV_FILE", str(env_file))

    response = post(client, CREDENTIAL_WRITE, {"slot_number": 5, "value": SYNTHETIC_VALUE})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["slot"] == "PADIEM_B14_CREDENTIAL_05"
    assert body["length"] == len(SYNTHETIC_VALUE)
    assert body["last4"] == SYNTHETIC_VALUE[-4:]
    assert body["target"] == "env_file"
    assert body["backup_kept"] is True
    assert SYNTHETIC_VALUE not in response.text

    text = env_file.read_text(encoding="utf-8")
    assert "OTHER_SETTING=keep-me" in text
    assert "PADIEM_B14_CREDENTIAL_05=" + SYNTHETIC_VALUE in text
    assert EXISTING_LINE_VALUE not in text
    assert os.environ["PADIEM_B14_CREDENTIAL_05"] == SYNTHETIC_VALUE

    backups = list(tmp_path.glob("b14.env.bak.*"))
    assert len(backups) == 1
    assert EXISTING_LINE_VALUE in backups[0].read_text(encoding="utf-8")
    if os.name == "posix":
        assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
        assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_secret_file_write_targets_one_slot_file(client, tmp_path, monkeypatch):
    secrets = tmp_path / "secrets"
    secrets.mkdir()
    monkeypatch.setenv("B14_SECRET_DIR", str(secrets))

    response = post(client, CREDENTIAL_WRITE, {"slot_number": 6, "value": SYNTHETIC_VALUE})
    assert response.status_code == 200, response.text
    assert response.json()["target"] == "secret_file"
    written = secrets / "PADIEM_B14_CREDENTIAL_06"
    assert written.read_text(encoding="utf-8").strip() == SYNTHETIC_VALUE
    assert [p.name for p in secrets.iterdir() if p.name.startswith("PADIEM_")] == [
        "PADIEM_B14_CREDENTIAL_06"
    ]


def test_the_value_never_reaches_the_audit_log(client, tmp_path, monkeypatch):
    env_file = tmp_path / "b14.env"
    monkeypatch.setenv("B14_CREDENTIAL_ENV_FILE", str(env_file))
    assert post(client, CREDENTIAL_WRITE, {"slot_number": 5, "value": SYNTHETIC_VALUE}).status_code == 200

    audit = get(client, AUDIT)
    assert audit.status_code == 200
    entries = audit.json()["entries"]
    assert any(entry["action"] == "credential_write" for entry in entries)
    record = next(e for e in entries if e["action"] == "credential_write")
    assert record["last4"] == SYNTHETIC_VALUE[-4:]
    assert SYNTHETIC_VALUE not in json.dumps(entries)

    audit_file = Path(os.environ["B14_REGISTRY_OVERLAY_PATH"]).with_name("model_admin_audit.jsonl")
    assert SYNTHETIC_VALUE not in audit_file.read_text(encoding="utf-8")