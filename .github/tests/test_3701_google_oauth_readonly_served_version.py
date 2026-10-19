"""#3701: Google OAuth automatic audit reuses canonical served-version CLI."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "b54-google-oauth-readonly-main-audit.yml"
CLI = ROOT / ".github" / "scripts" / "cloudflare_served_version_cli.py"


def test_readonly_audit_uses_canonical_cli_at_both_served_version_sites() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    audit = text.split("\n  cloudflare-readonly:", 1)[1]
    assert audit.count("cloudflare_served_version_cli.py resolve-active") == 2
    assert ".result.deployments[0].versions[0].percentage == 100" not in audit
    assert "(.result.deployments[0].versions | length) == 1" not in audit
    assert CLI.is_file()


def test_private_worker_state_output_is_not_contaminated_by_cli_stdout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    inspect = text.split("inspect_worker() {", 1)[1].split("identity_state=", 1)[0]
    assert 'if [ "${code}" = "404" ]' in inspect
    assert 'printf \'%s\\n\' "absent"' in inspect
    assert 'resolve-active --deployments "${deployments}" >/dev/null' in inspect
    assert 'printf \'%s\\n\' "present_private"' in inspect
    assert inspect.index('if [ "${code}" = "404" ]') < inspect.index("resolve-active")


def test_b62_latest_equals_active_contract_is_preserved() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'b62_active="$(python3 .github/scripts/cloudflare_served_version_cli.py resolve-active --deployments "${b62_deployments}")"' in text
    assert 'b62_latest="$(jq -r \'.result.items[0].id\' "${b62_versions}")"' in text
    assert 'test "${b62_active}" = "${b62_latest}"' in text
    assert "B62_LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in text


def test_cli_change_retriggers_pull_and_push_audits() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    pull_paths = text.split("pull_request:", 1)[1].split("push:", 1)[0]
    push_paths = text.split("push:", 1)[1].split("permissions:", 1)[0]
    assert ".github/scripts/cloudflare_served_version_cli.py" in pull_paths
    assert ".github/scripts/cloudflare_served_version_cli.py" in push_paths
