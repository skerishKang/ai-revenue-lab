"""#3930 B62 origin 504 GET-only fallback negative controls."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b62_public_origin_504_guard.py"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
spec = importlib.util.spec_from_file_location("origin_504", HELPER)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

HEALTH = json.dumps({"status": "ok", "app": "padiem-chat", "runtime": "b14"})
METADATA = json.dumps({"success": True, "result": {"enabled": True}})
DISABLED = json.dumps({"success": True, "result": {"enabled": False}})


def refuse(args, expected):
    try:
        gate.prove(*args)
    except gate.OriginProofError as exc:
        assert str(exc) == expected
    else:
        raise AssertionError("invalid public-origin proof unexpectedly accepted")


def test_successful_cloudflare_metadata_still_required():
    assert gate.prove("200", METADATA, "200", HEALTH, "200", HEALTH) == "CONTROL_AND_DATA_PLANE"


def test_only_504_may_use_two_independent_live_origins():
    assert gate.prove("504", "gateway timeout", "200", HEALTH, "200", HEALTH) == "DATAPLANE_504_FALLBACK"


def test_other_http_errors_are_never_accepted():
    for code in ("000", "401", "403", "404", "429", "500", "502", "503", "599"):
        refuse((code, "{}", "200", HEALTH, "200", HEALTH), "METADATA_HTTP_NOT_ACCEPTED")


def test_disabled_malformed_and_failed_metadata_never_accepted():
    refuse(("200", DISABLED, "200", HEALTH, "200", HEALTH), "SUBDOMAIN_NOT_ENABLED")
    refuse(("200", '{"success":false,"result":{"enabled":true}}', "200", HEALTH, "200", HEALTH),
           "SUBDOMAIN_NOT_ENABLED")
    refuse(("200", "not json", "200", HEALTH, "200", HEALTH), "METADATA_NOT_JSON")


def test_both_health_responses_must_match_exact_app_and_runtime():
    invalid = [
        ("503", HEALTH), ("200", "{}"), ("200", "invalid json"),
        ("200", json.dumps({"status":"ok","app":"fake","runtime":"b14"})),
        ("200", json.dumps({"status":"ok","app":"padiem-chat","runtime":"mock"})),
    ]
    for offset in (2, 4):
        for status, content in invalid:
            args = ["504", "timeout", "200", HEALTH, "200", HEALTH]
            args[offset:offset + 2] = [status, content]
            refuse(tuple(args), "PUBLIC_HEALTH_NOT_PROVEN")


def test_workflow_preserves_source_contract_and_rollback():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("python .github/scripts/b62_public_origin_504_guard.py") == 2
    assert text.count("https://${B62_WORKER}.charliekant.workers.dev/health") == 2
    assert "B62_PUBLIC_ORIGIN=CHAT_PADIEM_NET" in text
    assert "B62_PUBLIC_ORIGIN_STILL_ENABLED=PASS" in text
    assert "FULL_SECRET_SET_EQUALITY=PASS" in text
    assert "Auto-rollback to recorded version on any failed step" in text


if __name__ == "__main__":
    for name, fn in list(globals().copy().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + "=PASS")
