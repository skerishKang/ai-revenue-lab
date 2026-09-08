"""Focused contract tests: bootstrap/config boundary (S2)."""

import unittest

from padiem_embedded_runtime import SidecarContractError, parse_bootstrap_config


def valid_raw(**overrides):
    raw = {
        "host_id": "demo-host-01",
        "shell_version": "0.1.0",
        "locale": "ko",
        "features": ["context-panel"],
        "host_name": "S2 reference host",
    }
    raw.update(overrides)
    return raw


class BootstrapContractTests(unittest.TestCase):
    def test_valid_bootstrap_parses_and_serializes(self):
        config = parse_bootstrap_config(valid_raw())
        public = config.to_public_dict()
        self.assertEqual(public["host_id"], "demo-host-01")
        self.assertEqual(public["features"], ["context-panel"])
        import json

        json.dumps(public)

    def test_rejects_secret_like_values(self):
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(host_name="my api_key vault"))
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(host_id="bearer-abc"))

    def test_rejects_bad_shapes(self):
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(host_id="has space!"))
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(shell_version="1.0"))
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(locale="fr"))
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(features=["context-panel", "context-panel"]))
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(features=["admin-panel"]))
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config({"host_id": "x"})

    def test_rejects_unknown_fields(self):
        with self.assertRaises(SidecarContractError):
            parse_bootstrap_config(valid_raw(client_secret="nope"))


if __name__ == "__main__":
    unittest.main()
