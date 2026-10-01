from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b62_b66_quote_url_activation.py"
WORKFLOW = ROOT / ".github/workflows/b62-b66-quote-url-activation-gate.yml"
TARGET = "PADIEM_CHAT_B66_QUOTE_BASE_URL"


def _load():
    spec = importlib.util.spec_from_file_location("b62_b66_quote_url_activation", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _binding(name, kind, **extra):
    return {"name": name, "type": kind, **extra}


def _settings(bindings):
    return {"success": True, "result": {"bindings": bindings}}


def _baseline():
    return [
        _binding("ASSETS", "assets"),
        _binding("PADIEM_CHAT_DB", "d1", id="11111111-1111-1111-1111-111111111111"),
        _binding("PADIEM_CHAT_RUNTIME_MODE", "plain_text", text="production"),
        _binding("LEGACY_SECRET", "secret_text"),
    ]


def test_expected_origin_is_https_root_and_normalized() -> None:
    helper = _load()
    assert helper.normalize_expected_origin("https://quote.example.test/") == "https://quote.example.test"
    for bad in (
        "http://quote.example.test",
        "https://quote.example.test/path",
        "https://quote.example.test?x=1",
        "https://user:pw@quote.example.test",
        "quote.example.test",
    ):
        try:
            helper.normalize_expected_origin(bad)
        except helper.ActivationError:
            continue
        raise AssertionError(f"expected refusal for {bad}")


def test_classify_missing_exact_drift_wrong_type_invalid() -> None:
    helper = _load()
    expected = "https://quote.example.test"
    assert helper.classify(_settings(_baseline()), expected)[0] == "missing"
    assert helper.classify(
        _settings(_baseline() + [_binding(TARGET, "plain_text", text=expected)]), expected
    )[0] == "exact"
    assert helper.classify(
        _settings(_baseline() + [_binding(TARGET, "plain_text", text="https://other.example.test")]), expected
    )[0] == "drift"
    assert helper.classify(
        _settings(_baseline() + [_binding(TARGET, "secret_text")]), expected
    )[0] == "wrong_type"
    assert helper.classify(
        _settings(_baseline() + [_binding(TARGET, "plain_text", text="https://quote.example.test/path")]), expected
    )[0] == "invalid"


def test_plan_adds_only_missing_target_and_inherits_everything_else() -> None:
    helper = _load()
    plan = helper.build_plan(_settings(_baseline()), "https://quote.example.test/", "f" * 40)
    assert plan["no_op"] is False
    payload = plan["payload"]
    assert payload is not None
    inherited = {
        b["name"] for b in payload["bindings"]
        if b["type"] == "inherit" and b["version_id"] == "latest"
    }
    assert inherited == {b["name"] for b in _baseline()}
    target = [b for b in payload["bindings"] if b["name"] == TARGET]
    assert target == [{"name": TARGET, "type": "plain_text", "text": "https://quote.example.test"}]
    assert "LEGACY_SECRET" in json.dumps(payload)
    assert "secret_text" not in json.dumps(payload)


def test_plan_exact_is_noop_and_refuses_drift_or_wrong_type() -> None:
    helper = _load()
    expected = "https://quote.example.test"
    exact = _settings(_baseline() + [_binding(TARGET, "plain_text", text=expected)])
    assert helper.build_plan(exact, expected, "a" * 40)["no_op"] is True
    for bad in (
        _settings(_baseline() + [_binding(TARGET, "plain_text", text="https://other.example.test")]),
        _settings(_baseline() + [_binding(TARGET, "secret_text")]),
    ):
        try:
            helper.build_plan(bad, expected, "a" * 40)
        except helper.ActivationError:
            continue
        raise AssertionError("expected fail-closed activation plan")


def test_verify_readback_requires_target_and_preserves_unrelated_bindings() -> None:
    helper = _load()
    expected = "https://quote.example.test"
    before = _settings(_baseline())
    after = _settings(_baseline() + [_binding(TARGET, "plain_text", text=expected)])
    helper.verify_readback(before, after, expected)

    broken = _settings([
        b for b in _baseline() if b["name"] != "PADIEM_CHAT_DB"
    ] + [_binding(TARGET, "plain_text", text=expected)])
    try:
        helper.verify_readback(before, broken, expected)
    except helper.ActivationError:
        pass
    else:
        raise AssertionError("unrelated binding removal must fail")


def test_workflow_is_exact_main_bounded_and_no_code_deploy() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert "expected_origin:" in workflow
    assert "ACTIVATE_B62_B66_QUOTE_URL_FROM_EXACT_MAIN" in workflow
    assert "environment: production" in workflow
    assert "b62-b66-quote-url-premutation-settings" in workflow
    assert "PREMUTATION_SERVED_VERSION_RECORDED=YES" in workflow
    assert "B62_B66_QUOTE_URL_POST_READBACK=PASS" in workflow
    assert "UNRELATED_BINDINGS_PRESERVED=PASS" in workflow
    assert "SECRET_VALUES_READ=0" in workflow
    assert "WORKER_CODE_DEPLOY=0" in workflow
    assert "github.event_name == 'workflow_dispatch' && inputs.mode == 'activate_b66_quote_url'" in workflow
    assert "PATCH" in workflow and "/workers/scripts/${B62_WORKER}/settings" in workflow
    for forbidden in ("wrangler deploy", "pywrangler deploy", "d1 migrations apply"):
        assert forbidden not in workflow


if __name__ == "__main__":
    test_expected_origin_is_https_root_and_normalized()
    test_classify_missing_exact_drift_wrong_type_invalid()
    test_plan_adds_only_missing_target_and_inherits_everything_else()
    test_plan_exact_is_noop_and_refuses_drift_or_wrong_type()
    test_verify_readback_requires_target_and_preserves_unrelated_bindings()
    test_workflow_is_exact_main_bounded_and_no_code_deploy()
    print("B62_B66_QUOTE_URL_ACTIVATION_TESTS=PASS")
