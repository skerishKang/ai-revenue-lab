"""Contract tests for the #2509 standalone read-only quota snapshot gate.

Proves, without touching Cloudflare, that:
  1. only the five quota variables can ever be printed as values;
  2. a secret_text value is never printed (wrong type -> fail closed);
  3. an unknown plain_text binding is never printed;
  4. account/database identifiers and the full settings body are never printed;
  5. the gate workflow carries no deploy/mutation command;
  6. the exact-main guard is mandatory and the snapshot job is dispatch-only;
  7. missing / wrong-type / non-integer / out-of-range all fail closed;
  8. a complete valid snapshot passes with a closed vocabulary.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
WORKFLOW = ROOT / ".github" / "workflows" / "b62-chat-quota-snapshot-readonly.yml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass(slots=True) can resolve the module dict.
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


snap = _load("b62_quota_snapshot", SCRIPTS / "b62_quota_snapshot_readonly.py")
readiness = _load("b62_live_readiness", SCRIPTS / "b62_cloudflare_live_readiness.py")

QUOTA_KEYS = (
    "PADIEM_CHAT_ANONYMOUS_BURST_LIMIT",
    "PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT",
    "PADIEM_CHAT_USER_BURST_LIMIT",
    "PADIEM_CHAT_USER_DAILY_LIMIT",
    "PADIEM_CHAT_GLOBAL_DAILY_LIMIT",
)

SECRET_VALUE = "super-secret-salt-should-never-appear"
UNKNOWN_VALUE = "unknown-plaintext-should-never-appear"
DATABASE_ID = "deadbeef-dead-beef-dead-beefdeadbeef"
ACCOUNT_ID = "9be14bb7b8974e65d0afba647ab16932"


def _valid_text() -> dict[str, str]:
    return dict(zip(QUOTA_KEYS, ["4", "20", "8", "100", "1000"]))


def _valid_types_and_text() -> tuple[dict[str, str], dict[str, str]]:
    types = {key: "plain_text" for key in QUOTA_KEYS}
    return types, _valid_text()


def _settings_payload() -> dict:
    bindings = [{"name": key, "type": "plain_text", "text": value} for key, value in _valid_text().items()]
    bindings.append({"name": "PADIEM_CHAT_QUOTA_SALT", "type": "secret_text", "text": SECRET_VALUE})
    bindings.append({"name": "SOME_UNKNOWN_FLAG", "type": "plain_text", "text": UNKNOWN_VALUE})
    bindings.append({"name": "PADIEM_CHAT_DB", "type": "d1", "database_id": DATABASE_ID})
    return {"success": True, "result": {"bindings": bindings, "account_id": ACCOUNT_ID}}


# --------------------------------------------------------------------------
# 1. quota 5개만 value 출력 가능
# --------------------------------------------------------------------------
def test_only_five_quota_keys_are_snapshot_surface() -> None:
    assert snap.QUOTA_SNAPSHOT_KEYS == QUOTA_KEYS
    assert len(snap.QUOTA_SNAPSHOT_KEYS) == 5


def test_valid_snapshot_emits_exactly_five_value_lines() -> None:
    types, text = _valid_types_and_text()
    ok, reason, values = snap.evaluate_quota_snapshot(types, text)
    assert ok is True and reason == "" and len(values) == 5
    lines = snap.render_snapshot(ok, reason, values)
    value_lines = [line for line in lines if re.fullmatch(r"QUOTA_SNAPSHOT_PADIEM_CHAT_\w+=\d+", line)]
    assert len(value_lines) == 5
    assert "QUOTA_SNAPSHOT_COMPLETE=PASS" in lines


# --------------------------------------------------------------------------
# 2. secret_text는 value 출력 불가
# --------------------------------------------------------------------------
def test_secret_text_quota_key_fails_closed_without_value() -> None:
    types, text = _valid_types_and_text()
    types["PADIEM_CHAT_USER_DAILY_LIMIT"] = "secret_text"
    ok, reason, values = snap.evaluate_quota_snapshot(types, text)
    assert ok is False and reason == "WRONG_TYPE" and values == {}
    joined = "\n".join(snap.render_snapshot(ok, reason, values))
    assert "QUOTA_SNAPSHOT_PADIEM_CHAT_USER_DAILY_LIMIT" not in joined
    assert SECRET_VALUE not in joined


# --------------------------------------------------------------------------
# 3. unknown plain_text도 출력 불가
# --------------------------------------------------------------------------
def test_unknown_plain_text_never_printed() -> None:
    types, text = _valid_types_and_text()
    types["SOME_UNKNOWN_FLAG"] = "plain_text"
    text["SOME_UNKNOWN_FLAG"] = UNKNOWN_VALUE
    ok, reason, values = snap.evaluate_quota_snapshot(types, text)
    assert ok is True  # unknown key is simply not part of the surface
    joined = "\n".join(snap.render_snapshot(ok, reason, values))
    assert UNKNOWN_VALUE not in joined
    assert "SOME_UNKNOWN_FLAG" not in joined


# --------------------------------------------------------------------------
# 4. account/database identifier / full JSON 출력 불가 (end-to-end via parser)
# --------------------------------------------------------------------------
def test_reused_parser_drops_secret_unknown_and_identifiers() -> None:
    types, safe_text = readiness.binding_inventory(_settings_payload())
    assert types["PADIEM_CHAT_QUOTA_SALT"] == "secret_text"
    assert "PADIEM_CHAT_QUOTA_SALT" not in safe_text  # secret text never copied
    assert "SOME_UNKNOWN_FLAG" not in safe_text  # non-allowlisted plaintext ignored
    assert "PADIEM_CHAT_DB" not in safe_text  # identifiers never in safe text
    assert all(key in safe_text for key in QUOTA_KEYS)


def test_end_to_end_snapshot_output_is_safe() -> None:
    types, safe_text = readiness.binding_inventory(_settings_payload())
    ok, reason, values = snap.evaluate_quota_snapshot(types, safe_text)
    lines = snap.render_snapshot(ok, reason, values)
    joined = "\n".join(lines)
    assert ok is True and "QUOTA_SNAPSHOT_COMPLETE=PASS" in joined
    for forbidden in (SECRET_VALUE, UNKNOWN_VALUE, DATABASE_ID, ACCOUNT_ID, "database_id", "bindings"):
        assert forbidden not in joined


def test_output_lines_match_closed_vocabulary() -> None:
    allowed = re.compile(
        r"^(QUOTA_SNAPSHOT_PADIEM_CHAT_\w+=\d+"
        r"|QUOTA_SNAPSHOT_COMPLETE=(PASS|FAIL)"
        r"|QUOTA_SNAPSHOT_FAILURE=(READ_FAILED|MISSING|WRONG_TYPE|NON_INTEGER|RANGE_VIOLATION))$"
    )
    types, text = _valid_types_and_text()
    for args in ((True, "", dict(zip(QUOTA_KEYS, [4, 20, 8, 100, 1000]))), (False, "MISSING", {})):
        for line in snap.render_snapshot(*args):
            assert allowed.fullmatch(line), f"non-closed-vocabulary line: {line}"


# --------------------------------------------------------------------------
# 7. missing / non-integer / wrong-type / range -> FAIL
# --------------------------------------------------------------------------
def test_missing_key_fails_closed() -> None:
    types, text = _valid_types_and_text()
    del types["PADIEM_CHAT_GLOBAL_DAILY_LIMIT"]
    ok, reason, values = snap.evaluate_quota_snapshot(types, text)
    assert (ok, reason, values) == (False, "MISSING", {})


def test_non_integer_fails_closed() -> None:
    types, text = _valid_types_and_text()
    text["PADIEM_CHAT_USER_BURST_LIMIT"] = "eight"
    ok, reason, _ = snap.evaluate_quota_snapshot(types, text)
    assert (ok, reason) == (False, "NON_INTEGER")


def test_range_violation_fails_closed() -> None:
    for bad in ("0", "-5", "1000001"):
        types, text = _valid_types_and_text()
        text["PADIEM_CHAT_ANONYMOUS_DAILY_LIMIT"] = bad
        ok, reason, _ = snap.evaluate_quota_snapshot(types, text)
        assert (ok, reason) == (False, "RANGE_VIOLATION"), bad


def test_global_daily_range_boundary_uses_its_own_maximum() -> None:
    types, text = _valid_types_and_text()
    text["PADIEM_CHAT_GLOBAL_DAILY_LIMIT"] = "10000000"  # == maximum, allowed
    assert snap.evaluate_quota_snapshot(types, text)[0] is True
    text["PADIEM_CHAT_GLOBAL_DAILY_LIMIT"] = "10000001"  # > maximum
    assert snap.evaluate_quota_snapshot(types, text)[0] is False


# --------------------------------------------------------------------------
# 5 + 6. workflow contract: no mutation, exact-main guard, dispatch-only job
# --------------------------------------------------------------------------
def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict:
    data = yaml.safe_load(_workflow_text())
    trigger = data.get("on", data.get(True))
    return {"triggers": trigger, "jobs": data["jobs"], "permissions": data["permissions"]}


def test_workflow_parses_and_declares_target_sha_input() -> None:
    wf = _workflow()
    assert "workflow_dispatch" in wf["triggers"]
    assert wf["triggers"]["workflow_dispatch"]["inputs"]["target_sha"]["required"] is True


def test_snapshot_job_is_dispatch_only() -> None:
    job = _workflow()["jobs"]["quota-snapshot"]
    assert job["if"] == "github.event_name == 'workflow_dispatch'"


def test_exact_main_guard_is_mandatory() -> None:
    text = _workflow_text()
    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.inputs.target_sha }}"' in text
    assert 'test "$(git rev-parse origin/main)" = "${{ github.event.inputs.target_sha }}"' in text
    assert "EXACT_MAIN_SNAPSHOT=PASS" in text
    assert "git fetch" in text


def test_workflow_has_no_deploy_or_mutation_command() -> None:
    text = _workflow_text()
    for forbidden in (
        "pywrangler",
        "wrangler",
        "curl",
        "-X ",
        "PUT",
        "PATCH",
        "DELETE",
        "secret put",
        "d1 execute",
        "d1 migrate",
        "migrations apply",
    ):
        assert forbidden not in text, f"forbidden mutation token in workflow: {forbidden}"


def test_snapshot_script_is_get_only_and_reuses_parser() -> None:
    text = (SCRIPTS / "b62_quota_snapshot_readonly.py").read_text(encoding="utf-8")
    assert "post_json" not in text  # no mutation request path
    assert "wrangler" not in text and "pywrangler" not in text
    assert "binding_inventory" in text  # reuses the proven parser, no duplicate
    assert "from b62_cloudflare_live_readiness import" in text


def test_workflow_permissions_are_read_only() -> None:
    assert _workflow()["permissions"] == {"contents": "read"}
