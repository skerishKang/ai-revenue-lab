"""Cloudflare Pages watch-path repair contract: no deploy API used."""
from __future__ import annotations
from copy import deepcopy
from unittest import TestCase, main
from unittest.mock import patch
import provision_padiem_phone_pages as mod


class WatchPathContract(TestCase):
    def setUp(self):
        self.project = mod.project_body()

    def test_new_project_uses_documented_single_wildcard(self):
        self.assertEqual(self.project["source"]["config"]["path_includes"],
                         ["apps/padiem-phone/public-demo/*"])

    def test_existing_correct_project_requires_no_mutation(self):
        with patch.object(mod, "api_request") as call:
            result = mod.repair_deprecated_watch_path("account", "secret", self.project)
            self.assertEqual(result, self.project)
            call.assert_not_called()

    def test_repair_changes_only_source_watch_path(self):
        old = deepcopy(self.project)
        old["source"]["config"]["path_includes"] = [mod.ROOT + "/**"]
        calls = []
        def fake_api(account, token, method, suffix, payload=None):
            calls.append((method, suffix, payload))
            if method == "PATCH":
                return 200, {"success": True, "result": deepcopy(self.project)}
            if method == "GET":
                return 200, {"success": True, "result": deepcopy(self.project)}
            raise AssertionError("unexpected API method")
        with patch.object(mod, "api_request", side_effect=fake_api):
            result = mod.repair_deprecated_watch_path("account", "secret", old)
        self.assertEqual([m for m, _, _ in calls], ["PATCH", "GET"])
        self.assertEqual(calls[0][2], {"source": {"type": "github",
                                                 "config": {"path_includes": [mod.ROOT + "/*"]}}})
        self.assertEqual(result["source"]["config"]["path_includes"], [mod.ROOT + "/*"])

    def test_unknown_existing_watch_path_never_mutated(self):
        old = deepcopy(self.project)
        old["source"]["config"]["path_includes"] = ["*"]
        with patch.object(mod, "api_request") as call, self.assertRaises(RuntimeError):
            mod.repair_deprecated_watch_path("account", "secret", old)
        call.assert_not_called()

    def test_repair_must_read_back_exact_path(self):
        old = deepcopy(self.project)
        old["source"]["config"]["path_includes"] = [mod.ROOT + "/**"]
        with patch.object(mod, "api_request", side_effect=[
            (200, {"success": True}),
            (200, {"success": True, "result": old}),
        ]), self.assertRaisesRegex(RuntimeError, "readback_mismatch"):
            mod.repair_deprecated_watch_path("account", "secret", old)


if __name__ == "__main__":
    main()
