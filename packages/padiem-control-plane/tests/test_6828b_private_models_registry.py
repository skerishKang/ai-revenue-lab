"""#6828 2단계 ② — the private registry file, its validation and its fail-closed load.

These are contract tests: no network, no provider dispatch, no real provider
host, model identity or credential value. The public repository carries the
FORMAT only, so every fixture here is a placeholder.

What is pinned:

(a) a valid document loads, with the four product grades and their rosters;
(b) a missing file answers an EMPTY registry (0 models) and never falls back to
    a value that once shipped in the repository;
(c) an invalid document keeps the caller's last good snapshot, is reported with
    a reason code, and readiness stays refused;
(d) the reason never carries a path, a provider origin or a model identity;
(e) the validator refuses plain-http origins, pasted credential values, tier
    rosters naming models that do not exist, and a model outside its provider;
(f) the host path comes from the environment, the override wins, and the
    default is the design location;
(g) a file other users can read is refused before it is parsed (POSIX);
(h) the checked-in example and schema carry placeholders only.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

import pytest

from padiem_control_plane.models_registry import (
    DEFAULT_REGISTRY_PATH,
    FORMAT_VERSION,
    PrivateRegistryUnavailable,
    REGISTRY_OVERRIDE_ENV,
    REGISTRY_PATH_ENV,
    empty_registry,
    is_credential_binding_name,
    load_private_registry,
    load_snapshot,
    readiness,
    registry_path,
    registry_source,
    validate_document,
)

FIXTURE = Path(__file__).parent / "fixtures" / "models_private_fixture.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_REGISTRY = REPO_ROOT / "docs" / "registry"


def fixture_document() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def private_file(tmp_path: Path, document: dict | None = None, *, mode: int = 0o600) -> Path:
    """Write a document where the loader will read it, with the host's mode."""
    target = tmp_path / "models-private.json"
    payload = fixture_document() if document is None else document
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(target, mode)
    return target


def code_of(document: dict) -> str:
    with pytest.raises(PrivateRegistryUnavailable) as caught:
        validate_document(document)
    return caught.value.code


# --- (a) a valid document -----------------------------------------------------


def test_the_documented_document_loads_with_every_grade(tmp_path):
    registry = load_private_registry(private_file(tmp_path))

    assert registry.version == FORMAT_VERSION
    assert registry.ready is True
    assert registry.providers["example-provider"]["credential_binding"] == "PADIEM_B14_CREDENTIAL_99"
    assert {row["id"] for row in registry.models} == {
        "example-provider/example-model-1", "example-provider/example-model-2"}
    assert set(registry.tiers) == {"free", "plus", "pro", "max"}
    assert registry.tiers["free"]["primary"] == "example-provider/example-model-1"
    assert registry.tiers["free"]["fallback"] == ("example-provider/example-model-2",)


def test_the_admin_lane_is_optional_but_valid_when_present(tmp_path):
    document = fixture_document()
    document["tiers"]["admin"] = {
        "primary": "example-provider/example-model-2", "fallback": []}
    registry = load_private_registry(private_file(tmp_path, document))
    assert set(registry.tiers) == {"free", "plus", "pro", "max", "admin"}


# --- (b) a missing file is an empty registry, not a repository fallback -------


def test_a_missing_file_answers_an_empty_registry(tmp_path):
    load = load_snapshot(tmp_path / "absent.json")

    assert load.loaded is False
    assert load.code == "registry_file_missing"
    assert load.registry.models == ()
    assert load.ready is False
    assert readiness(load) == {"ok": False, "models": 0, "reason": "registry_file_missing"}


def test_the_empty_registry_is_never_ready():
    empty = empty_registry()
    assert empty.models == ()
    assert empty.providers == {}
    assert empty.ready is False


# --- (c) an invalid document keeps the last good snapshot --------------------


def test_an_invalid_document_keeps_the_last_good_snapshot(tmp_path):
    good = load_private_registry(private_file(tmp_path))
    document = fixture_document()
    document["version"] = "padiem.models.private.v2"
    broken = private_file(tmp_path, document)

    load = load_snapshot(broken, previous=good)

    assert load.loaded is False
    assert load.code == "registry_version_unsupported"
    assert load.registry is good
    assert load.ready is False
    assert readiness(load)["ok"] is False


def test_an_empty_document_is_refused_rather_than_reported_ready(tmp_path):
    load = load_snapshot(private_file(tmp_path, {"version": FORMAT_VERSION}))
    assert load.code == "registry_providers"
    assert load.ready is False


# --- (d) the reason is value-free --------------------------------------------


def test_the_reason_carries_no_path_no_origin_and_no_model(tmp_path, caplog):
    document = fixture_document()
    document["providers"]["example-provider"]["base_origin"] = "http://api.example.invalid/v1"
    target = private_file(tmp_path, document)

    with caplog.at_level(logging.WARNING, logger="padiem.models_registry"):
        load = load_snapshot(target)

    assert load.code == "registry_provider_origin"
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "registry_provider_origin" in message
    assert target.name in message
    assert str(tmp_path) not in message
    assert "api.example.invalid" not in message
    with pytest.raises(PrivateRegistryUnavailable) as caught:
        validate_document(document)
    assert str(caught.value) == "registry_provider_origin"


# --- (e) what the validator refuses ------------------------------------------


def test_a_plain_http_origin_is_refused():
    document = fixture_document()
    document["providers"]["example-provider"]["base_origin"] = "http://api.example.invalid/v1"
    assert code_of(document) == "registry_provider_origin"


def test_a_pasted_credential_value_is_refused():
    document = fixture_document()
    document["providers"]["example-provider"]["credential_binding"] = (
        "sk-live-0000000000000000000000000000000000000000")
    assert code_of(document) == "registry_provider_credential_binding"
    assert is_credential_binding_name("PADIEM_B14_CREDENTIAL_07") is True
    assert is_credential_binding_name("PADIEM_B14_CREDENTIAL_7") is False
    assert is_credential_binding_name("sk-live-abc") is False


def test_a_tier_may_only_name_models_that_exist():
    document = fixture_document()
    document["tiers"]["pro"]["fallback"] = ["example-provider/missing-model"]
    assert code_of(document) == "registry_tier_unknown_model"


def test_a_tier_primary_may_not_repeat_inside_its_roster():
    document = fixture_document()
    document["tiers"]["plus"]["fallback"] = ["example-provider/example-model-2"]
    assert code_of(document) == "registry_tier_primary_in_fallback"


def test_free_plus_pro_max_are_required():
    document = fixture_document()
    del document["tiers"]["max"]
    assert code_of(document) == "registry_tier_names"


def test_a_model_must_belong_to_the_provider_it_names():
    document = fixture_document()
    document["models"][0]["id"] = "other-provider/example-model-1"
    assert code_of(document) == "registry_model_provider_mismatch"


def test_an_unknown_capability_is_refused():
    document = fixture_document()
    document["models"][0]["capabilities"] = ["chat", "telepathy"]
    assert code_of(document) == "registry_model_capabilities"


def test_the_registry_may_not_carry_a_second_credential_field():
    document = fixture_document()
    document["providers"]["example-provider"]["credential_value"] = "x"
    assert code_of(document) == "registry_provider_keys"


# --- (f) where the file comes from -------------------------------------------


def test_the_default_path_is_the_design_location(monkeypatch):
    monkeypatch.delenv(REGISTRY_PATH_ENV, raising=False)
    monkeypatch.delenv(REGISTRY_OVERRIDE_ENV, raising=False)
    assert registry_path() == Path(DEFAULT_REGISTRY_PATH)
    assert registry_source() == "default"


def test_the_override_wins_over_the_configured_path(monkeypatch, tmp_path):
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(tmp_path / "configured.json"))
    monkeypatch.setenv(REGISTRY_OVERRIDE_ENV, str(tmp_path / "override.json"))
    assert registry_path() == tmp_path / "override.json"
    assert registry_source() == "override"

    monkeypatch.delenv(REGISTRY_OVERRIDE_ENV)
    assert registry_path() == tmp_path / "configured.json"
    assert registry_source() == "configured"


def test_the_configured_path_is_what_the_loader_reads(monkeypatch, tmp_path):
    target = private_file(tmp_path)
    monkeypatch.setenv(REGISTRY_PATH_ENV, str(target))
    assert load_snapshot().loaded is True


# --- (g) the 0640 rule --------------------------------------------------------


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes; the deployment is Linux")
def test_a_registry_other_users_can_read_is_refused(tmp_path):
    target = private_file(tmp_path, mode=0o644)
    load = load_snapshot(target)
    assert load.code == "registry_permissions_too_open"
    assert load.ready is False


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes; the deployment is Linux")
def test_the_deployment_mode_is_accepted(tmp_path):
    assert load_snapshot(private_file(tmp_path, mode=0o640)).loaded is True


# --- (h) the public repository carries placeholders only ---------------------


def test_the_checked_in_example_and_schema_carry_placeholders_only():
    example_text = (DOCS_REGISTRY / "models.example.json").read_text(encoding="utf-8")
    schema_text = (DOCS_REGISTRY / "models.schema.json").read_text(encoding="utf-8")
    example = json.loads(example_text)

    assert example["version"] == FORMAT_VERSION
    for entry in example["providers"].values():
        assert entry["base_origin"].endswith(".invalid/v1")
        assert all(host.endswith(".invalid") for host in entry["allowed_hosts"])
        assert entry["credential_binding"] == "PADIEM_B14_CREDENTIAL_99"
    for row in example["models"]:
        assert row["provider_id"] == "example-provider"
    assert validate_document(example).ready is True
    assert "padiem.models.private.v1" in schema_text
    assert "PADIEM_B14_CREDENTIAL_99" not in schema_text


def test_the_fixture_is_the_same_placeholder_document():
    example = json.loads((DOCS_REGISTRY / "models.example.json").read_text(encoding="utf-8"))
    assert fixture_document()["providers"] == example["providers"]
    assert fixture_document()["models"] == example["models"]


def test_the_private_file_is_not_part_of_this_repository():
    for directory in (DOCS_REGISTRY, FIXTURE.parent):
        for path in directory.iterdir():
            assert path.name != "models-private.json"
    assert not (REPO_ROOT / DEFAULT_REGISTRY_PATH.lstrip("/")).exists()
