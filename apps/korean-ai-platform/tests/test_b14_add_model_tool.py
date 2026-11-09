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

from _registry_values import (  # noqa: E402
    adapter_modules,
    model_ids,
    registry,
    requires_owner_document,
)


def _provider_with_a_model() -> str:
    """An existing Provider row the document already serves at least one model on.

    A probe of an existing Provider needs that Provider's display name, which
    the registry publishes under its models, so the Provider is selected by the
    structural fact that it has one instead of being named (#7241 3a).
    """
    document = registry()
    served = {row["provider_id"] for row in document["models"]}
    for provider_id in sorted(document["providers"]):
        if provider_id in served and provider_id in adapter_modules():
            return provider_id
    return ""


def _unserved_provider() -> str:
    """An existing Provider row that serves no model yet.

    A first-model probe on an existing Provider needs precisely that shape, so
    the Provider is selected by the structural fact instead of by name.
    """
    served = {row["provider_id"] for row in registry()["models"]}
    for provider_id in sorted(registry()["providers"]):
        if provider_id not in served:
            return provider_id
    raise AssertionError("every Provider in the document already serves a model")


def _available_model_id() -> str:
    """A registered model id, read from the document rather than written here."""
    return sorted(model_ids())[0]


def _provider_display_name(provider_id: str) -> str:
    """The display name the document publishes for this Provider's models."""
    names = {
        row["provider_name"] for row in registry()["models"]
        if row["provider_id"] == provider_id
    }
    assert len(names) == 1, "the Provider's display name is ambiguous"
    return names.pop()


def _binding_of(provider_id: str) -> str:
    """The credential binding NAME the Provider's own adapter constant declares."""
    module = adapter_modules().get(provider_id)
    if module is None:
        return ""
    return next(
        value for name, value in vars(module).items()
        if name.endswith("CREDENTIAL_BINDING") and isinstance(value, str) and value
    )


EXISTING_PROVIDER = _provider_with_a_model()
#: The Provider's own adapter constant, when the document installs an adapter for
#: it. The placeholder fixture installs none, which is when the pin skips.
EXISTING_BINDING = _binding_of(EXISTING_PROVIDER) if EXISTING_PROVIDER else ""
#: Whether the document serves a Provider the tool's probe can drive.
SELECTED = bool(EXISTING_PROVIDER)
#: A synthetic probe identity under the existing Provider. Its tail is a test
#: name, not a deployment value: the registry carries no such row.
PROBE_TAIL = "probe-model"
PROBE_SOURCE = "https://probe.invalid/models/probe"


#: The offline argv for the existing-Provider probe. The Provider and its
#: binding slot come from the document; the model tail is a synthetic name the
#: registry does not carry („a probe identity”, not a deployment value).
OFFLINE_ARGS = [
    "--provider", EXISTING_PROVIDER,
    "--model-id", f"{EXISTING_PROVIDER}/{PROBE_TAIL}",
    "--name", "Probe: Model",
    "--source", PROBE_SOURCE,
    "--checked-at", "2026-11-02",
    "--offline",
]

#: A brand-new Provider this tool must create explicitly. Nothing in the
#: deployment declares it, so the whole argv stays a test-only fixture.
NEW_PROVIDER = "probe-new"
NEW_PROVIDER_ARGS = [
    "--provider", NEW_PROVIDER,
    "--model-id", f"{NEW_PROVIDER}/{PROBE_TAIL}",
    "--name", "Probe New: Model",
    "--source", PROBE_SOURCE,
    "--checked-at", "2026-11-02",
    "--offline",
    "--create-provider",
    "--provider-name", "Probe New",
    "--base-url", "https://api.probe-new.invalid/v1",
    "--credential-binding", "PADIEM_PROBE_NEW_BINDING",
    "--extra-header", "X-Vendor-Api-Version: 2026-11-02",
]


def _run(argv):
    code = tool.main(argv)
    return code


@requires_owner_document
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


@requires_owner_document
def test_offline_row_is_exactly_the_canonical_candidate(capsys):
    before = json.loads(REGISTRY.read_text(encoding="utf-8"))
    code = _run(OFFLINE_ARGS)
    assert code == 0
    row = json.loads(capsys.readouterr().out)["registration"]["row"]
    assert row["id"] == f"{EXISTING_PROVIDER}/{PROBE_TAIL}"
    assert row["provider_id"] == EXISTING_PROVIDER
    assert row["upstream_model"] == PROBE_TAIL
    assert row["provider_name"] == _provider_display_name(EXISTING_PROVIDER)
    assert row["capabilities"] == ["chat"]
    assert row["input_price_usd_per_1m"] is None
    assert row["enabled"] is True
    assert json.loads(REGISTRY.read_text(encoding="utf-8")) == before


@requires_owner_document
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
    assert after["models"][-1]["id"] == f"{EXISTING_PROVIDER}/{PROBE_TAIL}"
    assert after["groups"] == json.loads(REGISTRY.read_text(encoding="utf-8"))["groups"]


@requires_owner_document
def test_offline_probe_needs_no_real_key_and_sends_bearer_shape(capsys, monkeypatch):
    monkeypatch.delenv(EXISTING_BINDING, raising=False)
    code = _run([*OFFLINE_ARGS, "--probe-only"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["auth_header_shape"] is True
    assert "authorization" in report["request_headers"]


def test_new_provider_probe_and_row_require_explicit_provider_metadata(capsys):
    code = _run([*NEW_PROVIDER_ARGS, "--probe-only"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "PASS"
    assert report["checks"]["korean"] is True

    import app.pilot.platform_secrets as secrets

    assert secrets.get_platform_provider(NEW_PROVIDER) is None


@requires_owner_document
def test_new_provider_row_with_extra_headers_is_registered_validated(monkeypatch, tmp_path, capsys):
    copied = tmp_path / "b14_models.json"
    copied.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tool, "REGISTRY", copied)
    code = _run([*NEW_PROVIDER_ARGS, "--write"])
    assert code == 0
    after = json.loads(copied.read_text(encoding="utf-8"))
    row = after["providers"][NEW_PROVIDER]
    assert row["base_origin"] == "https://api.probe-new.invalid/v1"
    assert row["credential_binding_name"] == "PADIEM_PROBE_NEW_BINDING"
    assert row["extra_headers"] == {"X-Vendor-Api-Version": "2026-11-02"}
    assert after["models"][-1]["id"] == f"{NEW_PROVIDER}/{PROBE_TAIL}"


@requires_owner_document
def test_retired_identity_is_refused_before_any_probe(capsys):
    # The retired roster is the document's own: no retired identity is written
    # here, and a host that reads another document skips the pin (#7241 3a).
    retired = _retired_identities()
    assert retired, "the effective document retires no identity"
    provider_id, model_id = retired[0]
    argv = [
        "--provider", provider_id,
        "--model-id", model_id,
        "--name", "Retired",
        "--source", PROBE_SOURCE,
        "--offline",
        "--probe-only",
    ]
    code = _run(argv)
    assert code == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "model_id_is_retired"


def _retired_identities() -> list[tuple[str, str]]:
    """(provider id, model id) for every retired identity in the document."""
    from app.pilot.model_registry_file import retired_model_ids

    return [
        (model_id.split("/", 1)[0], model_id)
        for model_id in sorted(retired_model_ids())
    ]


@requires_owner_document
def test_model_id_must_belong_to_the_provider(capsys):
    # A different, live Provider supplies the mismatched prefix.
    foreign_provider = next(
        provider_id for provider_id in sorted(registry()["providers"])
        if provider_id != EXISTING_PROVIDER
    )
    code = _run([
        "--provider", EXISTING_PROVIDER,
        "--model-id", f"{foreign_provider}/{PROBE_TAIL}",
        "--offline",
        "--probe-only",
    ])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "model_id_must_start_with_provider_id"


@requires_owner_document
def test_duplicate_model_id_is_refused_and_registry_untouched(monkeypatch, tmp_path, capsys):
    copied = tmp_path / "b14_models.json"
    copied.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tool, "REGISTRY", copied)
    before = copied.read_text(encoding="utf-8")
    duplicate = _available_model_id()
    argv = [
        "--provider", duplicate.split("/", 1)[0],
        "--model-id", duplicate,
        "--name", "Dup",
        "--source", PROBE_SOURCE,
        "--offline",
        "--write",
    ]
    code = _run(argv)
    assert code == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "model_id_already_registered"
    assert copied.read_text(encoding="utf-8") == before
