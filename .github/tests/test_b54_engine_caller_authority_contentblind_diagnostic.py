from __future__ import annotations

import contextlib
import io
import importlib.util
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b54-engine-caller-authority-readonly-gate.yml"
HELPER = ROOT / ".github/scripts/b54_engine_caller_authority_contentblind_diagnostic.py"

BASE_ENV = "PADIEM_ENGINE_CALLER_REGISTRY_V1"
OVERLAY_ENV = "PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY"

CRED_B61 = "cred-sentinel-" + "b" * 40
CRED_UNRELATED = "cred-sentinel-" + "u" * 40
CRED_OVERLAY = "cred-sentinel-" + "o" * 40
CRED_B54_IN_BASE = "cred-sentinel-" + "x" * 40
UNRELATED_CALLER_ID = "caller-sentinel-unrelated"
UNRELATED_APP_ID = "app-sentinel-allowed"
B61_APP_ID = "app-sentinel-b61"

# The full credential/app-id/unrelated-caller surface of every fixture. None
# of these strings may ever appear in diagnostic output.
SENTINELS = (
    CRED_B61,
    CRED_UNRELATED,
    CRED_OVERLAY,
    CRED_B54_IN_BASE,
    UNRELATED_CALLER_ID,
    UNRELATED_APP_ID,
    B61_APP_ID,
)

APPROVED_LINE = re.compile(
    r"^(BASE_PARSE=(OK|INVALID)|OVERLAY_PARSE=(OK|INVALID)"
    r"|BASE_CONTAINS_B54_KAGENT=(YES|NO)|DUPLICATE_CALLER_ID=(YES|NO)"
    r"|BASE_CALLER_COUNT=([0-9]|[1-5][0-9]|6[0-4])|OVERLAY_CALLER_ID_MATCH=(YES|NO)"
    r"|B54_ENGINE_AUTHORITY_CONTENTBLIND=PASS|SECRET_VALUE_OUTPUT=0"
    r"|RAW_REGISTRY_JSON_OUTPUT=0|CLOUDFLARE_MUTATION=0|PRODUCTION_MUTATION=0)$"
)

CLOSED_FIELDS = (
    "BASE_PARSE",
    "OVERLAY_PARSE",
    "BASE_CONTAINS_B54_KAGENT",
    "DUPLICATE_CALLER_ID",
    "BASE_CALLER_COUNT",
    "OVERLAY_CALLER_ID_MATCH",
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "b54_engine_caller_authority_contentblind_diagnostic", HELPER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _caller(caller_id: str, credential: str, app_id: str) -> dict[str, object]:
    return {
        "caller_id": caller_id,
        "credential": credential,
        "allowed_app_ids": [app_id],
    }


def _base(callers: list[dict[str, object]]) -> str:
    return json.dumps({"version": 1, "callers": callers})


def _overlay(caller: dict[str, object]) -> str:
    return json.dumps({"version": 1, "caller": caller})


def _valid_base() -> str:
    return _base(
        [
            _caller("storymemory-b61", CRED_B61, B61_APP_ID),
            _caller(UNRELATED_CALLER_ID, CRED_UNRELATED, UNRELATED_APP_ID),
        ]
    )


def _valid_overlay() -> str:
    return _overlay(_caller("b54-kagent", CRED_OVERLAY, "b54-padiem-claw"))


def _run(helper, base: str | None = None, overlay: str | None = None):
    saved = {name: os.environ.pop(name, None) for name in (BASE_ENV, OVERLAY_ENV)}
    try:
        if base is not None:
            os.environ[BASE_ENV] = base
        if overlay is not None:
            os.environ[OVERLAY_ENV] = overlay
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = helper.main([])
    finally:
        for name in (BASE_ENV, OVERLAY_ENV):
            os.environ.pop(name, None)
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value
    return code, stdout.getvalue() + stderr.getvalue()


def _fields(output: str) -> dict[str, str]:
    return dict(
        line.split("=", 1) for line in output.splitlines() if "=" in line
    )


def test_fixture_1_valid_base_valid_nonduplicate_overlay() -> None:
    helper = _load_helper()
    code, output = _run(helper, _valid_base(), _valid_overlay())
    assert code == 0
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "OK"
    assert fields["OVERLAY_PARSE"] == "OK"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "NO"
    assert fields["DUPLICATE_CALLER_ID"] == "NO"
    assert fields["BASE_CALLER_COUNT"] == "2"
    assert fields["OVERLAY_CALLER_ID_MATCH"] == "YES"


def test_fixture_2_malformed_base() -> None:
    helper = _load_helper()
    code, output = _run(helper, "{not-json", _valid_overlay())
    assert code == 0
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "INVALID"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "NO"
    assert fields["BASE_CALLER_COUNT"] == "0"
    assert fields["DUPLICATE_CALLER_ID"] == "NO"


def test_fixture_2b_malformed_base_still_detects_duplicate_structurally() -> None:
    # A base that fails strict validation (over capacity) must not hide a
    # positive b54-kagent duplicate finding.
    helper = _load_helper()
    callers = [_caller(f"caller-{index:03d}", CRED_B61, B61_APP_ID) for index in range(65)]
    callers.append(_caller("b54-kagent", CRED_B54_IN_BASE, "b54-padiem-claw"))
    code, output = _run(helper, _base(callers), _valid_overlay())
    assert code == 0
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "INVALID"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "YES"
    assert fields["DUPLICATE_CALLER_ID"] == "YES"
    assert fields["BASE_CALLER_COUNT"] == "64"


def test_fixture_3_malformed_overlay() -> None:
    helper = _load_helper()
    broken = json.dumps({"version": 2, "caller": _caller("b54-kagent", CRED_OVERLAY, "b54-padiem-claw")})
    code, output = _run(helper, _valid_base(), broken)
    assert code == 0
    fields = _fields(output)
    assert fields["OVERLAY_PARSE"] == "INVALID"
    assert fields["OVERLAY_CALLER_ID_MATCH"] == "YES"  # id is structurally present
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "NO"


def test_fixture_4_base_contains_b54_kagent_duplicate() -> None:
    helper = _load_helper()
    duplicate_base = _base(
        [
            _caller("storymemory-b61", CRED_B61, B61_APP_ID),
            _caller("b54-kagent", CRED_B54_IN_BASE, "b54-padiem-claw"),
        ]
    )
    code, output = _run(helper, duplicate_base, _valid_overlay())
    assert code == 0
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "OK"
    assert fields["OVERLAY_PARSE"] == "OK"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "YES"
    assert fields["DUPLICATE_CALLER_ID"] == "YES"
    assert fields["BASE_CALLER_COUNT"] == "2"
    assert fields["OVERLAY_CALLER_ID_MATCH"] == "YES"


def test_fixture_5_valid_base_without_b54_kagent() -> None:
    helper = _load_helper()
    single = _base([_caller("storymemory-b61", CRED_B61, B61_APP_ID)])
    code, output = _run(helper, single, _valid_overlay())
    assert code == 0
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "OK"
    assert fields["BASE_CONTAINS_B54_KAGENT"] == "NO"
    assert fields["DUPLICATE_CALLER_ID"] == "NO"


def test_fixture_6_bounded_caller_count() -> None:
    helper = _load_helper()
    at_cap = _base(
        [_caller(f"caller-{index:03d}", CRED_B61, B61_APP_ID) for index in range(64)]
    )
    code, output = _run(helper, at_cap, _valid_overlay())
    assert code == 0
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "OK"
    assert fields["BASE_CALLER_COUNT"] == "64"
    over_cap = _base(
        [_caller(f"caller-{index:03d}", CRED_B61, B61_APP_ID) for index in range(65)]
    )
    _, output = _run(helper, over_cap, _valid_overlay())
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "INVALID"
    assert int(fields["BASE_CALLER_COUNT"]) <= 64


def test_fixture_7_secret_content_never_emitted() -> None:
    helper = _load_helper()
    scenarios = (
        (_valid_base(), _valid_overlay()),
        ("{not-json", _valid_overlay()),
        (_valid_base(), json.dumps({"version": 2, "caller": {}})),
        (None, _valid_overlay()),
        (_valid_base(), None),
    )
    for base, overlay in scenarios:
        _, output = _run(helper, base, overlay)
        for sentinel in SENTINELS:
            assert sentinel not in output, f"secret content leaked: {sentinel!r}"
        assert CRED_OVERLAY not in output


def test_fixture_8_raw_json_never_emitted() -> None:
    helper = _load_helper()
    code, output = _run(helper, _valid_base(), _valid_overlay())
    assert code == 0
    assert _valid_base() not in output
    assert _valid_overlay() not in output
    for fragment in ("callers", "allowed_app_ids", "credential", "version", "{", "}"):
        assert fragment not in output, f"raw JSON fragment leaked: {fragment!r}"


def test_fixture_9_output_contract_closed_to_approved_fields() -> None:
    helper = _load_helper()
    code, output = _run(helper, _valid_base(), _valid_overlay())
    assert code == 0
    lines = output.splitlines()
    assert len(lines) == 11
    for line in lines:
        assert APPROVED_LINE.fullmatch(line), f"unapproved output line: {line!r}"
    keys = [line.split("=", 1)[0] for line in lines]
    for field in CLOSED_FIELDS:
        assert keys.count(field) == 1
    assert keys[:6] == list(CLOSED_FIELDS)


def test_blank_and_absent_inputs_fail_closed() -> None:
    helper = _load_helper()
    code, output = _run(helper, "   ", _valid_overlay())
    assert code == 0
    fields = _fields(output)
    assert fields["BASE_PARSE"] == "INVALID"
    code, output = _run(helper)
    assert code == 2
    assert "B54_ENGINE_AUTHORITY_CONTENTBLIND=FAIL" in output
    assert "=" not in output.split("B54_ENGINE_AUTHORITY_CONTENTBLIND=FAIL")[0]


def test_diagnostic_reuses_production_parsers() -> None:
    helper = _load_helper()
    assert helper.parse_caller_registry_v1.__module__ == "app.identity_enforcement"
    assert helper.parse_caller_registry_v1_overlay.__module__ == "app.identity_enforcement"
    assert (
        helper._authority_diagnostic.classify_authority_payloads.__module__
        == "app.authority_diagnostic"
    )
    assert helper.EXPECTED_OVERLAY_CALLER_ID == "b54-kagent"
    assert helper._authority_diagnostic.AUTHORITY_DIAGNOSTIC_PATH == (
        "/internal/v1/diagnostics/caller-authority"
    )


def test_runtime_module_gates_the_diagnostic_fail_closed() -> None:
    helper = _load_helper()
    module = helper._authority_diagnostic

    class _Env:
        PADIEM_ENGINE_AUTHORITY_DIAGNOSTIC_TOKEN = "d" * 48
        PADIEM_ENGINE_CALLER_REGISTRY_V1 = _valid_base()
        PADIEM_ENGINE_CALLER_REGISTRY_V1_OVERLAY = _valid_overlay()

    class _Headers(dict):
        def get(self, key, default=None):  # case-insensitive like Workers Headers
            for name, value in self.items():
                if name.lower() == key.lower():
                    return value
            return default

    env = _Env()
    headers = _Headers({module.DIAGNOSTIC_TOKEN_HEADER: "d" * 48})

    status, body = module.diagnostic_response(env, "POST", headers)
    assert status == 405 and body["ok"] is False

    status, body = module.diagnostic_response(object(), "GET", headers)
    assert status == 503
    assert body["error"]["code"] == "authority_diagnostic_unavailable"

    status, body = module.diagnostic_response(env, "GET", _Headers())
    assert status == 401 and body["error"]["code"] == "authority_diagnostic_unauthorized"

    wrong = _Headers({module.DIAGNOSTIC_TOKEN_HEADER: "a" * 48})
    status, body = module.diagnostic_response(env, "GET", wrong)
    assert status == 401

    oversized = _Headers({module.DIAGNOSTIC_TOKEN_HEADER: "a" * 900})
    status, body = module.diagnostic_response(env, "GET", oversized)
    assert status == 401

    status, body = module.diagnostic_response(env, "GET", headers)
    assert status == 200
    assert tuple(sorted(body)) == tuple(sorted(module.OUTPUT_KEYS))
    assert body["BASE_PARSE"] == "OK"
    assert body["OVERLAY_CALLER_ID_MATCH"] == "YES"
    rendered = json.dumps(body)
    for sentinel in SENTINELS:
        assert sentinel not in rendered


def test_workflow_wiring_is_dispatch_only_and_closed() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "content_blind_diagnostic" in workflow
    assert (
        "github.event_name == 'workflow_dispatch' && inputs.mode == 'content_blind_diagnostic'"
        in workflow
    )
    # The diagnostic runs inside the Engine runtime; the workflow only makes
    # one token-gated GET and never reads or transports registry values.
    assert "https://engine.padiem.net/internal/v1/diagnostics/caller-authority" in workflow
    assert "x-padiem-engine-authority-diagnostic-token" in workflow
    assert "AUTHORITY_DIAGNOSTIC_TOKEN: ${{ secrets.B54_ENGINE_AUTHORITY_DIAGNOSTIC_TOKEN }}" in workflow
    assert "(keys | sort) ==" in workflow
    assert 'test "$(printf \'%s\\n\' "${evidence}" | wc -l)" -eq 6' in workflow
    assert "RUNTIME_DIAGNOSTIC_STATUS=200" in workflow
    assert "CONTENTBLIND_RUNTIME=FAIL_CLOSED" in workflow
    assert "CONTENTBLIND_OUTPUT_CONTRACT=FAIL" in workflow
    assert "upload-artifact" not in workflow
    assert ".result.text" not in workflow
    assert "read_secret_text" not in workflow
    assert "/secrets" not in workflow


if __name__ == "__main__":
    test_fixture_1_valid_base_valid_nonduplicate_overlay()
    test_fixture_2_malformed_base()
    test_fixture_2b_malformed_base_still_detects_duplicate_structurally()
    test_fixture_3_malformed_overlay()
    test_fixture_4_base_contains_b54_kagent_duplicate()
    test_fixture_5_valid_base_without_b54_kagent()
    test_fixture_6_bounded_caller_count()
    test_fixture_7_secret_content_never_emitted()
    test_fixture_8_raw_json_never_emitted()
    test_fixture_9_output_contract_closed_to_approved_fields()
    test_blank_and_absent_inputs_fail_closed()
    test_diagnostic_reuses_production_parsers()
    test_runtime_module_gates_the_diagnostic_fail_closed()
    test_workflow_wiring_is_dispatch_only_and_closed()
    print("B54_ENGINE_CALLER_AUTHORITY_CONTENTBLIND_DIAGNOSTIC_TESTS=PASS")
