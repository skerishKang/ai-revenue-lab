"""B62 rollback contract: Cloudflare deployments POST MUST use strategy+versions.

Regression for 2026-10-10 failed 400 auto-rollback after Production 503.
No Cloudflare access, no secrets, and no deployments occur in this suite.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_cloudflare_rollback_deployment_request.py"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"
VERSION = "7d735075-fcfd-4260-bc6a-3561f35f5d65"

spec = importlib.util.spec_from_file_location("b62_rollback_payload", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_body_matches_cloudflare_create_deployment_schema():
    assert module.make_payload(VERSION) == {
        "strategy": "percentage",
        "versions": [{"version_id": VERSION, "percentage": 100}],
    }
    assert len(module.make_payload(VERSION)["versions"]) == 1
    assert sum(v["percentage"] for v in module.make_payload(VERSION)["versions"]) == 100


def test_invalid_uuid_and_injection_fail_closed():
    for invalid in (
        "", "not-a-uuid", "../../etc/passwd", "7d735075-fcfd-4260-bc6a-3561f35f5d65\"}",
        VERSION.upper(), "1234", None, 1234,
    ):
        try:
            module.make_payload(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid rollback version accepted")


def test_exact_file_is_created_without_secrets_or_overwrite():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "rollback.json"
        args = [sys.executable, str(SCRIPT), "--version-id", VERSION, "--output", str(out)]
        first = subprocess.run(args, capture_output=True, text=True, check=False)
        assert first.returncode == 0, first.stderr
        assert "B62_ROLLBACK_REQUEST=VALIDATED" in first.stdout
        assert VERSION not in first.stdout
        assert json.loads(out.read_text(encoding="utf-8")) == module.make_payload(VERSION)
        second = subprocess.run(args, capture_output=True, text=True, check=False)
        assert second.returncode != 0
        assert "B62_ROLLBACK_REQUEST=BLOCKED" in second.stdout
        assert json.loads(out.read_text(encoding="utf-8")) == module.make_payload(VERSION)


def test_invalid_uuid_never_creates_body():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "rollback.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--version-id", "invalid", "--output", str(out)],
            capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0
        assert not out.exists()


def test_both_automatic_and_manual_rollback_use_correct_body():
    text = WORKFLOW.read_text(encoding="utf-8")
    for name, filename in (
        ("Auto-rollback to recorded version on any failed step", "b62-auto-rollback-request.json"),
        ("Roll out recorded version", "b62-manual-rollback-request.json"),
    ):
        start = text.index("      - name: " + name)
        end = text.find("\n      - name: ", start + 10)
        body = text[start:] if end == -1 else text[start:end]
        assert filename in body
        assert "python3 .github/scripts/b62_cloudflare_rollback_deployment_request.py" in body
        assert '--version-id "${PREVIOUS_VERSION_ID}" --output "${rollback_request}"' in body
        assert '-d "@${rollback_request}"' in body
        assert '-X POST "${api}/deployments"' in body
        assert '{"version_id"' not in body
        assert body.index("rollback_deployment_request.py") < body.index('-X POST "${api}/deployments"')


def test_legacy_fail_closed_and_secret_guards_are_unchanged():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "ROLLBACK_NOT_REQUIRED_ACTIVE_VERSION_UNCHANGED" in text
    assert "ROLLBACK_POST_ATTEMPTED=NO" in text
    assert "ROLLBACK_POST_ATTEMPTED=YES" in text
    assert "ROLLBACK_EFFECT=EXECUTED" in text
    assert "FULL_SECRET_SET_EQUALITY=PASS" in text
    assert "DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN" in text
    assert "ROLLBACK_B62_PRODUCTION_CODE_TO_RECORDED_VERSION" in text
    assert "B62_PRODUCTION_SMOKE=PASS" in text
    assert "environment: production" in text
    assert "- name: Prove Cloudflare rollback deployment request shape" in text


if __name__ == "__main__":
    for name, fn in list(globals().copy().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + "=PASS")
