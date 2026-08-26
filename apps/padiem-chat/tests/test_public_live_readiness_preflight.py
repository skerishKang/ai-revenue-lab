from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / ".github/scripts/b62_cloudflare_live_readiness.py"
    module_name = "b62_cloudflare_live_readiness_contract"
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _settings(bindings):
    return {"success": True, "result": {"bindings": bindings}}


def _base_bindings(*, runtime="mock", live="false"):
    return [
        {"name": "PADIEM_CHAT_RUNTIME_MODE", "type": "plain_text", "text": runtime},
        {"name": "PADIEM_CHAT_LIVE_ENABLED", "type": "plain_text", "text": live},
        {
            "name": "PADIEM_CHAT_B14_BASE_URL",
            "type": "plain_text",
            "text": "https://b14.example.test",
        },
        {
            "name": "PADIEM_CHAT_DB",
            "type": "d1",
            "database_id": "must-not-be-emitted",
        },
        {
            "name": "PADIEM_CHAT_QUOTA_SALT",
            "type": "secret_text",
            "text": "must-never-be-copied",
        },
        {
            "name": "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT",
            "type": "plain_text",
            "text": "4",
        },
        {
            "name": "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT",
            "type": "plain_text",
            "text": "20",
        },
        {
            "name": "PADIEM_CHAT_USER_BURST_LIMIT",
            "type": "plain_text",
            "text": "8",
        },
        {
            "name": "PADIEM_CHAT_USER_DAILY_LIMIT",
            "type": "plain_text",
            "text": "100",
        },
        {
            "name": "PADIEM_CHAT_GLOBAL_DAILY_LIMIT",
            "type": "plain_text",
            "text": "1000",
        },
    ]


def _b14(*, live=True, has_key=True):
    return {
        "status": "ok",
        "business14": {
            "provider_mode": "live" if live else "mock",
            "has_key": has_key,
        },
    }


def _schema_payload(*, include_table=True, include_index=True, columns=None):
    if columns is None:
        columns = [
            "subject_type",
            "subject_key",
            "bucket_type",
            "bucket_start",
            "request_count",
            "updated_at",
        ]
    objects = []
    if include_table:
        objects.append({"type": "table", "name": "live_usage_buckets"})
    if include_index:
        objects.append({"type": "index", "name": "idx_live_usage_buckets_updated_at"})
    return {
        "success": True,
        "result": [
            {"success": True, "results": objects},
            {
                "success": True,
                "results": [
                    {"cid": idx, "name": name, "type": "TEXT"}
                    for idx, name in enumerate(columns)
                ],
            },
        ],
    }


def _ready_evaluate(module, bindings=None, *, runtime="mock", live="false"):
    if bindings is None:
        bindings = _base_bindings(runtime=runtime, live=live)
    return module.evaluate(
        _settings(bindings),
        200,
        _b14(),
        quota_schema_ready=True,
        quota_schema_status="ready",
    )


def test_binding_inventory_never_copies_secret_or_unknown_plaintext():
    module = _load_module()
    payload = _settings(
        _base_bindings()
        + [
            {
                "name": "SOME_OTHER_SECRET",
                "type": "secret_text",
                "text": "secret-sentinel",
            },
            {
                "name": "ACCIDENTAL_PLAINTEXT_SECRET",
                "type": "plain_text",
                "text": "plain-sentinel",
            },
        ]
    )

    types, safe_text = module.binding_inventory(payload)

    assert types["PADIEM_CHAT_QUOTA_SALT"] == "secret_text"
    assert "PADIEM_CHAT_QUOTA_SALT" not in safe_text
    assert "PADIEM_CHAT_DB" not in safe_text
    assert "SOME_OTHER_SECRET" not in safe_text
    assert "ACCIDENTAL_PLAINTEXT_SECRET" not in safe_text
    assert "secret-sentinel" not in repr(safe_text)
    assert "plain-sentinel" not in repr(safe_text)
    assert "must-not-be-emitted" not in repr(safe_text)


def test_d1_binding_alone_is_not_enough_for_ready_to_arm():
    module = _load_module()
    readiness = module.evaluate(_settings(_base_bindings()), 200, _b14())

    assert readiness.d1_bound is True
    assert readiness.quota_schema_ready is False
    assert readiness.prerequisites_ready is False


def test_current_mock_shape_is_safe_hold_even_when_all_prerequisites_exist():
    module = _load_module()
    readiness = _ready_evaluate(module)

    assert readiness.prerequisites_ready is True
    assert readiness.public_live_active is False
    assert readiness.safe_hold is True


def test_live_active_requires_b14_runtime_and_explicit_live_arm():
    module = _load_module()
    readiness = _ready_evaluate(module, runtime="b14", live="true")

    assert readiness.prerequisites_ready is True
    assert readiness.public_live_active is True
    assert readiness.safe_hold is False


def test_b14_not_live_or_keyless_keeps_readiness_on_hold():
    module = _load_module()

    mock_b14 = module.evaluate(
        _settings(_base_bindings()),
        200,
        _b14(live=False, has_key=True),
        quota_schema_ready=True,
        quota_schema_status="ready",
    )
    keyless_b14 = module.evaluate(
        _settings(_base_bindings()),
        200,
        _b14(live=True, has_key=False),
        quota_schema_ready=True,
        quota_schema_status="ready",
    )

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

    readiness = module.evaluate(
        _settings(bindings),
        200,
        _b14(),
        quota_schema_ready=True,
        quota_schema_status="ready",
    )

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
    no_base = [
        item
        for item in _base_bindings()
        if item.get("name") != "PADIEM_CHAT_B14_BASE_URL"
    ]

    assert (
        module.evaluate(
            _settings(no_d1),
            200,
            _b14(),
            quota_schema_ready=True,
            quota_schema_status="ready",
        ).prerequisites_ready
        is False
    )
    assert (
        module.evaluate(
            _settings(no_base),
            200,
            _b14(),
            quota_schema_ready=True,
            quota_schema_status="ready",
        ).prerequisites_ready
        is False
    )


def test_complete_quota_schema_is_ready():
    module = _load_module()
    ready, status = module.evaluate_quota_schema_response(200, _schema_payload())

    assert ready is True
    assert status == "ready"


@pytest.mark.parametrize(
    "payload",
    [
        _schema_payload(include_table=False),
        _schema_payload(include_index=False),
        _schema_payload(
            columns=[
                "subject_type",
                "subject_key",
                "bucket_type",
                "bucket_start",
                "request_count",
            ]
        ),
    ],
)
def test_missing_table_index_or_required_column_is_hold(payload):
    module = _load_module()
    ready, status = module.evaluate_quota_schema_response(200, payload)

    assert ready is False
    assert status == "missing"


def test_d1_read_permission_unavailable_is_bounded_hold():
    module = _load_module()

    for http_status in (401, 403):
        ready, status = module.evaluate_quota_schema_response(
            http_status,
            {"success": False, "errors": [{"message": "not emitted"}]},
        )
        assert ready is False
        assert status == "permission_unavailable"

        readiness = module.evaluate(
            _settings(_base_bindings()),
            200,
            _b14(),
            quota_schema_ready=ready,
            quota_schema_status=status,
        )
        assert readiness.prerequisites_ready is False


def test_malformed_successful_d1_schema_response_fails_audit_closed():
    module = _load_module()

    with pytest.raises(RuntimeError):
        module.evaluate_quota_schema_response(200, {"success": True, "result": []})


def test_database_identifier_and_secret_values_are_never_emitted(capsys):
    module = _load_module()
    payload = _settings(_base_bindings())

    assert module.d1_database_id(payload) == "must-not-be-emitted"
    readiness = _ready_evaluate(module)
    module.emit(readiness)
    output = capsys.readouterr().out

    assert "must-not-be-emitted" not in output
    assert "must-never-be-copied" not in output
    assert "READY_TO_ARM" in output
    assert "QUOTA_SCHEMA_READY=true" in output
    assert "D1_SCHEMA_AUDIT=ready" in output
