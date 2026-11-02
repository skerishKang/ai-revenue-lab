"""tools/b14/add_model.py: adapter probe + one registry row, offline and live-wire.

Every stage runs through the real adapter with a MockTransport, so the tool's
PASS never proves more than the adapter contract (answer, Korean, streaming,
latency, error mapping) and the row it emits is the canonical registry row.
No network, no credential value, no registry mutation outside tmp_path.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
REGISTRY = APP_ROOT / "app" / "pilot" / "b14_models.json"

_SPEC = importlib.util.spec_from_file_location("b14_add_model_tool", REPO_ROOT / "tools" / "b14" / "add_model.py")
assert _SPEC is not None and _SPEC.loader is not None
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)

ATRIA_BINDING = "PADIEM_B14_CREDENTIAL_02"
OFFLINE_ARGS = [
    "--provider", "atria",
    "--model-id", "atria/atria-probe-model",
    "--name", "Atria: Probe Model",
    "--source", "https://atria-asi.ai/models/probe",
    "--checked-at", "2026-11-02",
    "--offline",
]


def _run(argv):
    code = tool.main(argv)
    return code


def test_offline_probe_passes_and_emits_one_append_only_row(capsys):
    before = json.loads(REGISTRY.read_text(encoding="utf-8"))
    code = _run([*OFFLINE_ARGS, "--probe-only"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS"
    assert report["network"] == "mock_transport"
    assert report["provider_api_posts"] == 2
    checks = report["checks"]
    assert checks["response"] and checks["korean"] and checks["streaming"]
    assert checks["stream_done"] and checks["model_echo"]
    assert checks["error_codes"] == {
        "401": "upstream_auth_failed",
        "403": "upstream_auth_failed",
        "429": "upstream_rate_limited",
        "500": "upstream_server_error",
    }
    assert report["sample"] == "통과"
    assert report["latency_ms"]["completed"] >= 0
    assert report.get("registration") is None
    assert json.loads(REGISTRY.read_text(encoding="utf-8")) == before


def test_offline_row_is_exactly_the_canonical_candidate(capsys):
    before = json.loads(REGISTRY.read_text(encoding="utf-8"))
    code = _run(OFFLINE_ARGS)
    assert code == 0
    row = json.loads(capsys.readouterr().out)["registration"]["row"]
    assert row["id"] == "atria/atria-probe-model"
    assert row["provider_id"] == "atria"
    assert row["upstream_model"] == "atria-probe-model"
    assert row["provider_name"] == "Atria"
    assert row["capabilities"] == ["chat"]
    assert row["input_price_usd_per_1m"] is None
    assert row["enabled"] is True
    assert json.loads(REGISTRY.read_text(encoding="utf-8")) == before


def test_write_appends_one_row_to_a_copied_registry(monkeypatch, tmp_path, capsys):
    copied = tmp_path / "b14_models.json"
    copied.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tool, "REGISTRY", copied)
    code = _run([*OFFLINE_ARGS, "--write"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["registration"]["mode"] == "JSON_APPENDED"
    after = json.loads(copied.read_text(encoding="utf-8"))
    assert after["providers"] == json.loads(REGISTRY.read_text(encoding="utf-8"))["providers"]
    assert after["models"][:-1] == json.loads(REGISTRY.read_text(encoding="utf-8"))["models"]
    assert after["models"][-1]["id"] == "atria/atria-probe-model"
    assert after["groups"] == json.loads(REGISTRY.read_text(encoding="utf-8"))["groups"]


def test_offline_probe_needs_no_real_key_and_sends_bearer_shape(capsys, monkeypatch):
    monkeypatch.delenv(ATRIA_BINDING, raising=False)
    code = _run([*OFFLINE_ARGS, "--probe-only"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["auth_header_shape"] is True
    assert "authorization" in report["request_headers"]


def test_new_provider_probe_and_row_require_explicit_provider_metadata(capsys):
    argv = [
        "--provider", "probe-new",
        "--model-id", "probe-new/probe-model",
        "--name", "Probe New: Model",
        "--source", "https://probe-new.example/models/probe",
        "--checked-at", "2026-11-02",
        "--offline",
        "--create-provider",
        "--provider-name", "Probe New",
        "--base-url", "https://api.probe-new.example/v1",
        "--credential-binding", "PADIEM_B14_CREDENTIAL_15",
        "--extra-header", "X-Vendor-Api-Version: 2026-11-02",
        "--probe-only",
    ]
    code = _run(argv)
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS"
    assert report["checks"]["korean"] is True

    import app.pilot.platform_secrets as secrets

    assert secrets.get_platform_provider("probe-new") is None


def test_new_provider_row_with_extra_headers_is_registered_validated(monkeypatch, tmp_path, capsys):
    copied = tmp_path / "b14_models.json"
    copied.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tool, "REGISTRY", copied)
    argv = [
        "--provider", "probe-new",
        "--model-id", "probe-new/probe-model",
        "--name", "Probe New: Model",
        "--source", "https://probe-new.example/models/probe",
        "--checked-at", "2026-11-02",
        "--offline",
        "--create-provider",
        "--provider-name", "Probe New",
        "--base-url", "https://api.probe-new.example/v1",
        "--credential-binding", "PADIEM_B14_CREDENTIAL_15",
        "--extra-header", "X-Vendor-Api-Version: 2026-11-02",
        "--write",
    ]
    code = _run(argv)
    assert code == 0
    after = json.loads(copied.read_text(encoding="utf-8"))
    row = after["providers"]["probe-new"]
    assert row["base_origin"] == "https://api.probe-new.example/v1"
    assert row["credential_binding_name"] == "PADIEM_B14_CREDENTIAL_15"
    assert row["extra_headers"] == {"X-Vendor-Api-Version": "2026-11-02"}
    assert after["models"][-1]["id"] == "probe-new/probe-model"


def test_retired_identity_is_refused_before_any_probe(capsys):
    argv = [
        "--provider", "experiential",
        "--model-id", "experiential/gpt-5.6-luna",
        "--name", "Retired",
        "--source", "https://example.invalid/x",
        "--offline",
        "--probe-only",
    ]
    code = _run(argv)
    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED"


def test_model_id_must_belong_to_the_provider(capsys):
    code = _run([
        "--provider", "atria",
        "--model-id", "kira/wrong-prefix",
        "--offline",
        "--probe-only",
    ])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "model_id_must_start_with_provider_id"


def test_duplicate_model_id_is_refused_and_registry_untouched(monkeypatch, tmp_path, capsys):
    copied = tmp_path / "b14_models.json"
    copied.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tool, "REGISTRY", copied)
    before = copied.read_text(encoding="utf-8")
    argv = [
        "--provider", "inception",
        "--model-id", "inception/mercury-2.5",
        "--name", "Dup",
        "--source", "https://example.invalid/x",
        "--offline",
        "--write",
    ]
    code = _run(argv)
    assert code == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "model_id_already_registered"
    assert copied.read_text(encoding="utf-8") == before
