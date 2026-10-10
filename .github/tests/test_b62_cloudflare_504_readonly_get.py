"""Read-only, bounded Cloudflare 504 retry source safety checks (#3930)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github/scripts/b62_cloudflare_504_readonly_get.sh"
WORKFLOW = ROOT / ".github/workflows/b62-production-code-deploy-gate.yml"


def test_504_only_two_attempts_and_never_post():
    text = HELPER.read_text(encoding="utf-8")
    assert 'for attempt in 1 2; do' in text
    assert 'if [ "${code}" != "504" ]; then' in text
    assert 'if [ "${code}" = "200" ]; then' in text
    assert "BLOCKED_REPEATED_504" in text
    assert 'sleep 2' in text
    assert " -X POST" not in text
    assert "SECRET_VALUES" not in text
    assert 'Authorization: Bearer ${CLOUDFLARE_API_TOKEN}' in text


def test_allowed_endpoint_path_is_b62_worker_only():
    text = HELPER.read_text(encoding="utf-8")
    assert 'accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts/${B62_WORKER}' in text
    for suffix in ('/settings', '/deployments', '/subdomain', '/versions'):
        assert suffix in text
    assert "UNAUTHORIZED_PATH" in text
    assert 'https://example.com' not in text


def test_deploy_gate_only_wraps_readonly_get_and_preserves_mutation_controls():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("bash .github/scripts/b62_cloudflare_504_readonly_get.sh") >= 10
    assert 'CONFIRM' in text or 'DEPLOY_B62_PRODUCTION_CODE_FROM_EXACT_MAIN' in text
    assert 'B62_PRODUCTION_CODE_DEPLOY=SUCCESS' in text
    assert 'FULL_SECRET_SET_EQUALITY=PASS' in text
    assert 'Auto-rollback to recorded version on any failed step' in text
    assert 'set -euo pipefail' in HELPER.read_text(encoding="utf-8")


if __name__ == "__main__":
    for name, fn in list(globals().copy().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(name + "=PASS")
