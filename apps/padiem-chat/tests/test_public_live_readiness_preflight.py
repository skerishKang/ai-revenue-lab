from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / ".github/scripts/b62_cloudflare_live_readiness.py"
    spec = importlib.util.spec_from_file_location("b62_cloudflare_live_readiness_contract", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(bindings):
    return {"success": True, "result": {"bindings": bindings}}


def _base_bindings(*, runtime="mock", live="false"):
    return [
        {"name": "PADIEM_CHAT_RUNTIME_MODE", "type": "plain_text", "text": runtime},
        {"name": "PADIEM_CHAT_LIVE_ENABLED", "type": "plain_text", "text": live},
        {"name": "PADIEM_CHAT_B14_BASE_URL", "type": "plain_text", "text": "https://b14.example.test"},
        {"name": "PADIEM_CHAT_DB", "type": "d1", "database_id": "must-not-be-emitted"},
        {"name": "PADIEM_CHAT_QUOTA_SALT", "type": "secret_text", "text": "must-never-be-copied"},
        {"name": "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT", "type": "plain_text", "text": "4"},
        {"name": "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT", "type": "plain_text", "text": "20"},
        {"name": "PADIEM_CHAT_USER_BURST_LIMIT", "type": "plain_text", "text": "8"},
        {"name": "PADIEM_CHAT_USER_DAILY_LIMIT", "type": "plain_text", "text": "100"},
        {"name": "PADIEM_CHAT_GLOBAL_DAILY_LIMIT", "type": "plain_text", "text": "1000"},
    ]


def _b14(*, live=True, has_key=True):
    return {
        "status": "ok",
        "business14": {
            "provider_mode": "live" if live else "mock",
            "has_key": has_key,
        },
    }


def test_binding_inventory_never_copies_secret_or_unknown_plaintext():
    module = _load_module()
    payload = _settings(
        _base_bindings()
        + [
            {"name": "SOME_OTHER_SECRET", "type": "secret_text", "text": "secret-sentinel"},
            {"name": "ACCIDENTAL_PLAINTEXT_SECRET", "type": "plain_text", "text": "plain-sentinel"},
        ]
    )

    types, safe_text = module.binding_inventory(payload)

    assert types["PADIEM_CHAT_QUOTA_SALT"] == "secret_text"
    assert "PADIEM_CHAT_QUOTA_SALT" not in safe_text
    assert "SOME_OTHER_SECRET" not in safe_text
    assert "ACCIDENTAL_PLAINTEXT_SECRET" not in safe_text
    assert "secret-sentinel" not in repr(safe_text)
    assert "plain-sentinel" not in repr(safe_text)


def test_current_mock_shape_is_safe_hold_even_when_other_prerequisites_exist():
    module = _load_module()
    readiness = module.evaluate(_settings(_base_bindings()), 200, _b14())

    assert readiness.prerequisites_ready is True
    assert readiness.public_live_active is False
    assert readiness.safe_hold is True


def test_live_active_requires_b14_runtime_and_explicit_live_arm():
    module = _load_module()
    readiness = module.evaluate(
        _settings(_base_bindings(runtime="b14", live="true")),
        200,
        _b14(),
    )

    assert readiness.prerequisites_ready is True
    assert readiness.public_live_active is True
    assert readiness.safe_hold is False


def test_b14_not_live_or_keyless_keeps_readiness_on_hold():
    module = _load_module()

    mock_b14 = module.evaluate(_settings(_base_bindings()), 200, _b14(live=False, has_key=True))
    keyless_b14 = module.evaluate(_settings(_base_bindings()), 200, _b14(live=True, has_key=False))

    assert mock_b14.prerequisites_ready is False
    assert keyless_b14.prerequisites_ready is False


def test_quota_salt_must_be_secret_text_binding():
    module = _load_module()
    bindings = _base_bindings()
    bindings = [
        {**item, "type": "plain_text", "text": "not-a-secret-binding"}
        if item.get("name") == "PADIEM_CHAT_QUOTA_SALT"
        else item
        for item in bindings
    ]

    readiness = module.evaluate(_settings(bindings), 200, _b14())

    assert readiness.quota_salt_secret_bound is False
    assert readiness.prerequisites_ready is False


def test_every_quota_limit_must_be_explicit_positive_finite_integer():
    module = _load_module()
    assert module.finite_limits_configured({name: "1" for name in module.QUOTA_LIMITS}) is True

    for name, maximum in module.QUOTA_LIMITS.items():
        complete = {key: "1" for key in module.QUOTA_LIMITS}

        missing = dict(complete)
        missing.pop(name)
        assert module.finite_limits_configured(missing) is False

        zero = dict(complete)
        zero[name] = "0"
        assert module.finite_limits_configured(zero) is False

        too_high = dict(complete)
        too_high[name] = str(maximum + 1)
        assert module.finite_limits_configured(too_high) is False

        invalid = dict(complete)
        invalid[name] = "unlimited"
        assert module.finite_limits_configured(invalid) is False


def test_missing_d1_or_b14_base_keeps_readiness_on_hold():
    module = _load_module()

    no_d1 = [item for item in _base_bindings() if item.get("name") != "PADIEM_CHAT_DB"]
    no_base = [item for item in _base_bindings() if item.get("name") != "PADIEM_CHAT_B14_BASE_URL"]

    assert module.evaluate(_settings(no_d1), 200, _b14()).prerequisites_ready is False
    assert module.evaluate(_settings(no_base), 200, _b14()).prerequisites_ready is False
