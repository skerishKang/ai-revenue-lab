"""#3977: official exact provider facts without invented serving/model defaults."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import pytest

from app.pilot.model_registry_file import read_registry
from app.pilot.model_native_parameters import _SUPPORTED, validate_native_parameters
from app.pilot import model_serving_evidence as evidence_api
from app.pilot.model_serving_evidence import registered_serving_evidence


GOOGLE_OFFICIAL = {
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite",
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it",
}
GEMINI_LITE = {
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite",
}


def test_all_canonical_11_have_exact_provider_upstream_and_origin():
    data = read_registry()
    evidence = registered_serving_evidence()
    assert len(evidence) == len(data["models"]) == 11
    assert len(set(x.model_id for x in evidence)) == len(evidence)
    for record, model in zip(evidence, data["models"]):
        assert (
            record.model_id, record.serving_provider_id, record.upstream_model
        ) == (model["id"], model["provider_id"], model["upstream_model"])
        assert record.serving_origin == data["providers"][model["provider_id"]]["base_origin"]
        assert record.registry_source == model["source"]
        assert record.registry_checked_at == model["source_checked_at"]


def test_first_party_google_exact_ids_have_their_official_evidence_source():
    indexed = {record.model_id: record for record in registered_serving_evidence()}
    assert {key for key, item in indexed.items() if item.manufacturer} == GOOGLE_OFFICIAL
    for model_id in GOOGLE_OFFICIAL:
        record = indexed[model_id]
        assert record.provenance_status == "DOCUMENTED"
        assert record.manufacturer == "Google"
        assert record.variant_kind == "official_first_party_api_code"
        assert record.official_source_url.startswith("https://ai.google.dev/")
        assert record.serving_origin == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_only_two_google_flash_lite_cards_have_documented_65536_output():
    indexed = {record.model_id: record for record in registered_serving_evidence()}
    for model_id in GEMINI_LITE:
        item = indexed[model_id]
        assert item.manufacturer_model_max_output == 65536
        assert item.manufacturer_output_limit_status == "DOCUMENTED"
        assert item.official_source_url.endswith(model_id.removeprefix("google/"))
        # Manufacturer max is never silently the serving or request cap.
        assert item.serving_model_max_output is None
        assert item.output_limit_status == "UNKNOWN"
    for model_id in set(indexed) - GEMINI_LITE:
        item = indexed[model_id]
        assert item.manufacturer_model_max_output is None
        assert item.manufacturer_output_limit_status == "UNKNOWN"


def test_seven_non_google_models_and_unverified_serving_caps_stay_unknown():
    remaining = [item for item in registered_serving_evidence()
                 if item.model_id not in GOOGLE_OFFICIAL]
    assert len(remaining) == 7
    for item in remaining:
        assert item.provenance_status == "UNKNOWN"
        assert item.manufacturer is None
        assert item.variant_kind is None
        assert item.official_source_url is None
    for item in registered_serving_evidence():
        assert item.output_limit_status == "UNKNOWN"
        assert item.serving_model_max_output is None


def test_spoofed_google_origin_disables_all_first_party_provenance(monkeypatch):
    data = deepcopy(read_registry())
    data["providers"]["google"]["base_origin"] = "https://thirdparty.example.test/v1"
    monkeypatch.setattr(evidence_api, "read_registry", lambda: data)
    result = registered_serving_evidence()
    for item in result:
        if item.model_id in GOOGLE_OFFICIAL:
            assert item.provenance_status == "UNKNOWN"
            assert item.manufacturer_model_max_output is None
            assert item.official_source_url is None


def test_spoofed_upstream_alias_does_not_inherit_original_card(monkeypatch):
    data = deepcopy(read_registry())
    data["models"][2]["upstream_model"] = "gemini-3.1-flash-lite-provider-variant"
    monkeypatch.setattr(evidence_api, "read_registry", lambda: data)
    result = registered_serving_evidence()
    item = next(x for x in result if x.model_id == "google/gemini-3.1-flash-lite")
    assert item.provenance_status == "UNKNOWN"
    assert item.manufacturer_model_max_output is None
    assert item.official_source_url is None


def test_native_options_remain_only_exact_registered_documented_allowlists():
    evidence = registered_serving_evidence()
    assert {x.model_id for x in evidence if x.native_override_fields} == set(_SUPPORTED)
    assert len(_SUPPORTED) == 4
    for entry in evidence:
        if entry.model_id in _SUPPORTED:
            assert set(entry.native_override_fields) == set(_SUPPORTED[entry.model_id])
            assert entry.native_override_status == "DOCUMENTED"
        else:
            assert entry.native_override_fields == ()
            assert entry.native_override_status == "UNKNOWN"
            with pytest.raises(ValueError):
                validate_native_parameters(entry.model_id, {"reasoning_effort": "high"})


def test_evidence_is_immutable_and_never_exposes_secrets():
    item = registered_serving_evidence()[0]
    with pytest.raises(FrozenInstanceError):
        item.serving_provider_id = "other"
    assert "API_KEY" not in repr(item)
    assert "Bearer" not in repr(item)
