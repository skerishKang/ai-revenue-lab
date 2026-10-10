"""Fast single-command model quick-add: offline; existing B14 validators only."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "b14_model_quick_add", ROOT / ".github/scripts/b14_model_quick_add.py"
)
assert SPEC is not None and SPEC.loader is not None
quick = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quick)
BASE = quick.checked_registry(quick.REGISTRY)


def candidate(**overrides):
    args = dict(provider="kira", upstream="future-smoke-test-model",
                name="Kira: Future Model", source="https://kiraai.vn/models/example/",
                checked_at="2026-10-10", capabilities=["chat", "coding"])
    args.update(overrides)
    return quick.make_candidate(BASE, **args)


class ModelQuickAddTests(unittest.TestCase):
    def test_current_json_is_valid_and_no_provider_calls(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = quick.main(["check", "--model-id", "kira/qwen3.8-flash-free"])
        self.assertEqual(code, 0)
        x = json.loads(out.getvalue())
        self.assertEqual(x["status"], "PASS")
        self.assertEqual(x["provider_api_posts"], 0)
        self.assertEqual(x["model_count"], 11)

    def test_preview_does_not_change_registry(self):
        before = quick.REGISTRY.read_bytes()
        out = io.StringIO()
        with redirect_stdout(out):
            code = quick.main([
                "add", "--provider", "kira", "--upstream", "future-smoke-test-model",
                "--name", "Kira: Future Model", "--source",
                "https://kiraai.vn/models/example/", "--checked-at", "2026-10-10"
            ])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["mode"], "DRY_RUN")
        self.assertEqual(report["expected_ci_lane"], "model_registration_only")
        self.assertEqual(report["provider_api_posts"], 0)
        self.assertEqual(before, quick.REGISTRY.read_bytes())

    def test_explicit_write_changes_only_one_json_append(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "b14_models.json"
            p.write_bytes(quick.REGISTRY.read_bytes())
            before = quick.checked_registry(p)
            with patch.object(quick, "REGISTRY", p):
                with redirect_stdout(io.StringIO()) as out:
                    code = quick.main([
                        "add", "--provider", "kira", "--upstream", "future-smoke-test-model",
                        "--name", "Kira: Future Model", "--source",
                        "https://kiraai.vn/models/example/", "--checked-at", "2026-10-10",
                        "--write",
                    ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["mode"], "JSON_APPENDED")
            after = quick.checked_registry(p)
            self.assertEqual(after["models"][:-1], before["models"])
            self.assertEqual(after["providers"], before["providers"])
            self.assertEqual(after["groups"], before["groups"])
            self.assertTrue(quick.exact_append_only(before, after))
            self.assertEqual(after["models"][-1]["id"], "kira/future-smoke-test-model")
            self.assertIsNone(after["models"][-1]["input_price_usd_per_1m"])

    def test_new_provider_requires_separate_credential_review(self):
        with self.assertRaisesRegex(quick.OnboardError, "NEW_PROVIDER_REQUIRES_ONE_TIME"):
            candidate(provider="unknown")

    def test_duplicate_disabled_and_bad_metadata_blocked(self):
        for kwargs in (
            {"upstream": "qwen3.8-flash-free"},
            {"source": "http://unsafe.example/"},
            {"source": "https://example.com@evil.invalid/"},
            {"checked_at": "someday"},
            {"capabilities": ["free", "chat"]},
            {"context_window": -1},
            {"input_price": -1.0},
            {"input_price": float("nan")},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(quick.OnboardError):
                candidate(**kwargs)

    def test_model_payload_never_changes_existing_entries(self):
        new = quick.prepare_append(BASE, candidate())
        self.assertEqual(len(new["models"]), len(BASE["models"])+1)
        self.assertEqual(new["models"][:-1], BASE["models"])
        self.assertTrue(quick.exact_append_only(BASE, new))
        quick.check_candidate_json(new, quick.REGISTRY)

    def test_missing_existing_model_fails_safe_without_network(self):
        with redirect_stdout(io.StringIO()) as out:
            code = quick.main(["check", "--model-id", "kira/not-onboarded-yet"])
        self.assertEqual(code, 2)
        report = json.loads(out.getvalue())
        self.assertEqual(report["reason"], "model_not_registered")
        self.assertEqual(report["provider_api_posts"], 0)


if __name__ == "__main__":
    unittest.main()
