"""#6858/#6712 boundary: the Owner overlay's per-model reasoning block must load.

2026-11-05 comp2: the shipped validator still used an exact model-row key set,
so an overlay row carrying ``reasoning`` aborted at boot
(``model: unexpected/missing keys``) and the CTO's overrides file could not be
installed at all. These tests pin the relaxed-but-fail-closed contract:

- a base row plus ``reasoning`` validates and keeps every other key exact;
- a malformed reasoning block fails closed (normalize_policy);
- a row with an unrelated extra key is still rejected.
"""
from __future__ import annotations

import unittest

from app.pilot.model_registry_file import ModelRegistryError, validate_registry


def base_registry() -> dict:
    return {
        "schema_version": 1,
        "comment": "test",
        "providers": {
            "google": {
                "base_origin": "https://generativelanguage.googleapis.com/v1beta",
                "allowed_hosts": ["generativelanguage.googleapis.com"],
                "credential_source": "platform_secret",
                "credential_binding_name": "PADIEM_B14_CREDENTIAL_05",
                "enabled": True,
            },
        },
        "models": [
            {
                "id": "google/gemini-3.5-flash-lite",
                "provider_id": "google",
                "upstream_model": "gemini-3.5-flash-lite",
                "display_name": "Google: Gemini 3.5 Flash Lite",
                "provider_name": "Google AI Studio",
                "capabilities": ["chat"],
                "context_window": 1048576,
                "input_price_usd_per_1m": 0.3,
                "output_price_usd_per_1m": 2.5,
                "source": "google_ai_studio_official_catalog",
                "source_checked_at": "2026-10-08",
                "enabled": True,
            },
        ],
        "groups": {"plus": [], "pro": [], "max": []},
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
