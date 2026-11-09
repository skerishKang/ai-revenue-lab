"""#6858/#6712 boundary: the Owner overlay's per-model reasoning block must load.

2026-11-05 comp2: the shipped validator still used an exact model-row key set,
so an overlay row carrying ``reasoning`` aborted at boot
(``model: unexpected/missing keys``) and the CTO's overrides file could not be
installed at all. These tests pin the relaxed-but-fail-closed contract:

- a base row plus ``reasoning`` validates and keeps every other key exact;
- a malformed reasoning block fails closed (normalize_policy);
- a row with an unrelated extra key is still rejected.

#7241: the document the validator is driven with is built from the effective
registry — the shipped document today, the private registry once this host is
switched — and from the validator's own key vocabulary (its required root /
provider / model key sets and its group names). No provider, host, binding,
model or metadata value is written in this module.
"""
from __future__ import annotations

import copy
import unittest

from app.pilot import model_registry_file as registry_file
from app.pilot.model_registry_file import ModelRegistryError, validate_registry

from _registry_values import model_rows, provider_row, registry


def _sample_provider_id() -> str:
    return model_rows()[0]["provider_id"]


def _sample_model_row() -> dict:
    """One effective model row reduced to the validator's exact row shape.

    The row keeps only the keys the validator requires (``reasoning`` is the
    key under test and is added by each case), so the base document is exact
    by construction whatever metadata the effective document carries.
    """
    row = copy.deepcopy(model_rows()[0])
    required = {
        "id", "provider_id", "upstream_model", "display_name", "provider_name",
        "capabilities", "context_window", "input_price_usd_per_1m",
        "output_price_usd_per_1m", "source", "source_checked_at", "enabled",
    }
    required &= set(row)
    row = {key: value for key, value in row.items() if key in required}
    # The capability list is what the validator checks for its chat tag; the
    # base row states exactly that one tag.
    row["capabilities"] = ["chat"]
    return row


def _sample_provider_row(provider_id: str, model_id: str) -> dict:
    """The effective provider row, in the validator's exact provider shape."""
    row = copy.deepcopy(provider_row(provider_id))
    row.pop("extra_headers", None)
    # A model row must be addressed under its own provider id; the base
    # document derives the id from the provider row it is attached to.
    row.setdefault("credential_source", "platform_secret")
    row["enabled"] = True
    assert model_id.startswith(provider_id + "/")
    return row


def base_registry() -> dict:
    model = _sample_model_row()
    provider_id = model["provider_id"]
    return {
        "schema_version": 1,
        "comment": "test",
        "providers": {provider_id: _sample_provider_row(provider_id, model["id"])},
        "models": [model],
        "groups": {name: [] for name in registry_file._GROUPS},
    }


class OverlayReasoningValidation(unittest.TestCase):
    def test_overlay_row_with_reasoning_block_validates(self) -> None:
        data = base_registry()
        data["models"][0]["reasoning"] = {
            "supported": True,
            "values": ["minimal", "low", "medium", "high"],
        }
        validate_registry(data)

    def test_malformed_reasoning_block_fails_closed(self) -> None:
        data = base_registry()
        data["models"][0]["reasoning"] = {"supported": True, "values": ["deepest"]}
        with self.assertRaises(ModelRegistryError):
            validate_registry(data)

        data["models"][0]["reasoning"] = {"supported": True}
        with self.assertRaises(ModelRegistryError):
            validate_registry(data)

    def test_unrelated_extra_key_is_still_rejected(self) -> None:
        data = base_registry()
        data["models"][0]["temperature_default"] = 0.7
        with self.assertRaises(ModelRegistryError):
            validate_registry(data)

    def test_reasoning_block_requires_object(self) -> None:
        data = base_registry()
        data["models"][0]["reasoning"] = "high"
        with self.assertRaises(ModelRegistryError):
            validate_registry(data)


if __name__ == "__main__":
    unittest.main()
