"""#3977: no invented provenance/defaults for any registered serving model."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import pytest

from app.pilot.model_registry_file import read_registry
from app.pilot.model_native_parameters import _SUPPORTED, validate_native_parameters
from app.pilot.model_serving_evidence import registered_serving_evidence


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


def test_unknown_maker_variant_limits_are_not_fabricated():
    for item in registered_serving_evidence():
        assert item.provenance_status == "UNKNOWN"
        assert item.manufacturer is None
        assert item.variant_kind is None
        assert item.output_limit_status == "UNKNOWN"
        assert item.manufacturer_model_max_output is None
        assert item.serving_model_max_output is None


def test_native_options_are_only_exact_registered_documented_allowlists():
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


def test_evidence_is_immutable_and_has_no_secret_values():
    item = registered_serving_evidence()[0]
    with pytest.raises(FrozenInstanceError):
        item.serving_provider_id = "other"
    assert "API_KEY" not in repr(item)
    assert "Bearer" not in repr(item)
