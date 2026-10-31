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
    for code in ("401", "403", "404", "429", "500", "502", "503", "599"):
        refuse((code, "{}", "200", HEALTH, "200", HEALTH), f"METADATA_HTTP_{code}")


def test_a_control_plane_that_never_answered_is_named_apart_from_an_http_error():
    for code in ("000", ""):
        refuse((code, "", "200", HEALTH, "200", HEALTH), "METADATA_NO_RESPONSE")


def test_disabled_malformed_and_failed_metadata_never_accepted():
    refuse(("200", DISABLED, "200", HEALTH, "200", HEALTH), "SUBDOMAIN_DISABLED_EXPLICIT")
    refuse(("200", '{"success":false,"result":{"enabled":true}}', "200", HEALTH, "200", HEALTH),
           "METADATA_SUCCESS_NOT_TRUE")
    refuse(("200", "not json", "200", HEALTH, "200", HEALTH), "METADATA_NOT_JSON")
    refuse(("200", '{"success":true,"result":"charliekant"}', "200", HEALTH, "200", HEALTH),
           "SUBDOMAIN_RESULT_NOT_OBJECT")


def test_an_absent_enabled_flag_is_an_anomaly_and_never_a_pass():
    """The live per-Worker /subdomain response carries `enabled`, so a response
    without it is not a success to be excused."""

    refuse(("200", '{"success":true,"result":{"previews_enabled":true}}',
            "200", HEALTH, "200", HEALTH), "SUBDOMAIN_FLAG_ABSENT")


def test_both_health_responses_must_match_exact_app_and_runtime():
    mismatched = [
        ("200", "{}"), ("200", "invalid json"),
        ("200", json.dumps({"status":"ok","app":"fake","runtime":"b14"})),
        ("200", json.dumps({"status":"ok","app":"padiem-chat","runtime":"mock"})),
    ]
    for offset, plane in ((2, "WORKERS_DEV"), (4, "CUSTOM_DOMAIN")):
        for status, content in mismatched:
            args = ["504", "timeout", "200", HEALTH, "200", HEALTH]
            args[offset:offset + 2] = [status, content]
            refuse(tuple(args), f"HEALTH_{plane}_ENVELOPE_MISMATCH")
        for status, content in (("503", HEALTH), ("429", HEALTH), ("500", HEALTH)):
            args = ["504", "timeout", "200", HEALTH, "200", HEALTH]
            args[offset:offset + 2] = [status, content]
            refuse(tuple(args), f"HEALTH_{plane}_HTTP_{status}")
        for status in ("000", ""):
            args = ["504", "timeout", "200", HEALTH, "200", HEALTH]
            args[offset:offset + 2] = [status, ""]
            refuse(tuple(args), f"HEALTH_{plane}_NO_RESPONSE")


def test_workers_dev_failure_is_not_masked_by_a_healthy_custom_domain():
    refuse(("200", METADATA, "503", HEALTH, "200", HEALTH),
           "HEALTH_WORKERS_DEV_HTTP_503")
    refuse(("200", METADATA, "200", HEALTH, "503", HEALTH),
           "HEALTH_CUSTOM_DOMAIN_HTTP_503")


def test_the_504_fallback_still_requires_both_live_origins():
    assert gate.prove("504", "gateway timeout", "200", HEALTH, "200", HEALTH) == "DATAPLANE_504_FALLBACK"
    refuse(("504", "gateway timeout", "503", HEALTH, "200", HEALTH),
           "HEALTH_WORKERS_DEV_HTTP_503")


def test_every_refusal_prints_one_cause_line_and_no_response_content() -> None:
    """The whole point of the cause code is a stopped release that says why.

    CI runs this file directly (`python .github/tests/...`), so it uses
    tempfile rather than a pytest fixture.
    """

    import re
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)

        def run(metadata_body: str, workers_body: str = HEALTH, custom_body: str = HEALTH,
                metadata_status: str = "200") -> tuple[int, str]:
            paths = {}
            for name, content in (("m", metadata_body), ("w", workers_body), ("c", custom_body)):
                paths[name] = root / f"{name}.json"
                paths[name].write_text(content, encoding="utf-8")
            done = subprocess.run([
                sys.executable, str(HELPER),
                "--metadata-status", metadata_status, "--metadata-body", str(paths["m"]),
                "--workers-status", "200", "--workers-body", str(paths["w"]),
                "--custom-status", "200", "--custom-body", str(paths["c"]),
            ], capture_output=True, text=True, check=False)
            return done.returncode, done.stdout

        rc, out = run(METADATA)
        assert rc == 0 and "B62_PUBLIC_ORIGIN_PROOF=PASS" in out

        rc, out = run(DISABLED)
        assert rc == 1 and "B62_PUBLIC_ORIGIN_PROOF=BLOCKED" in out
        assert "B62_PUBLIC_ORIGIN_PROOF_CAUSE=SUBDOMAIN_DISABLED_EXPLICIT" in out

        rc, out = run(json.dumps({"success": True, "result": {"previews_enabled": True}}))
        assert rc == 1 and "B62_PUBLIC_ORIGIN_PROOF_CAUSE=SUBDOMAIN_FLAG_ABSENT" in out

        rc, out = run("not json at all")
        assert rc == 1 and "B62_PUBLIC_ORIGIN_PROOF_CAUSE=METADATA_NOT_JSON" in out

        rc, out = run("{}", metadata_status="403")
        assert rc == 1 and "B62_PUBLIC_ORIGIN_PROOF_CAUSE=METADATA_HTTP_403" in out

        rc, out = run(METADATA, workers_body="{}")
        assert rc == 1 and "B62_PUBLIC_ORIGIN_PROOF_CAUSE=HEALTH_WORKERS_DEV_ENVELOPE_MISMATCH" in out

        # A cause line is a condition code: upper-case identifier characters only,
        # so it can never echo a URL, a body or a credential.
        causes = []
        for body in (DISABLED, json.dumps({"success": True, "result": {}}), "not json at all"):
            rc, out = run(body)
            causes.append([ln for ln in out.splitlines() if "CAUSE=" in ln][0])
        rc, out = run(METADATA, workers_body="{}")
        causes.append([ln for ln in out.splitlines() if "CAUSE=" in ln][0])
        for line in causes:
            value = line.split("=", 1)[1]
            assert re.fullmatch(r"[A-Z0-9_]+", value), value
            assert "chat.padiem.net" not in value and "http" not in value.lower()

        # An unreadable input file names the plane it could not read.
        missing = root / "absent.json"
        done = subprocess.run([
            sys.executable, str(HELPER),
            "--metadata-status", "200", "--metadata-body", str(root / "m.json"),
            "--workers-status", "200", "--workers-body", str(missing),
            "--custom-status", "200", "--custom-body", str(root / "c.json"),
        ], capture_output=True, text=True, check=False)
        assert done.returncode == 1
        assert "B62_PUBLIC_ORIGIN_PROOF_CAUSE=GUARD_INPUT_UNREADABLE_WORKERS_DEV" in done.stdout


def test_workflow_preserves_source_contract_and_rollback():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("python .github/scripts/b62_public_origin_504_guard.py") == 2
    assert text.count("https://${B62_WORKER}.charliekant.workers.dev/health") == 2
    assert "B62_PUBLIC_ORIGIN=CHAT_PADIEM_NET" in text
    assert "B62_PUBLIC_ORIGIN_STILL_ENABLED=PASS" in text
    assert "BINDINGS_MATCH_REPOSITORY_PLAN=PASS" in text
    assert "Auto-rollback to recorded version on any failed step" in text


if __name__ == "__main__":
    for name, fn in list(globals().copy().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + "=PASS")
