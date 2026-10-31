"""#5895: the ops read-only status readout must not be able to write anything.

The contract is static: it parses the workflow and scans every command body. It
asserts that

  * the live readout runs only behind an explicit workflow_dispatch plus the
    GET_OPS_READONLY_STATUS marker, and a pull_request run executes the static
    contract job alone;
  * no step body carries a mutating command, HTTP method or transfer flag;
  * the only Cloudflare URL is the GET on a Worker deployments record, and the
    only credentials are the two existing read-only Secret names, checked for
    presence and never echoed;
  * served-version selection stays on the canonical resolver instead of a
    re-derived inline traffic path;
  * every job prints PRODUCTION_MUTATION=0.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ops-readonly-status.yml"

READONLY_MARKER = "GET_OPS_READONLY_STATUS"
LIVE_JOB = "ops-status"
CONTRACT_JOB = "source-contract"
ALLOWED_SECRETS = {"secrets.CLOUDFLARE_API_TOKEN", "secrets.CLOUDFLARE_ACCOUNT_ID"}

# Written as concatenations so this file never contains a runnable mutating
# command itself, and the injected body below is a doctored copy used only to
# prove the scanner rejects it.
FORBIDDEN_COMMAND_PATTERNS = (
    r"(?:npx\s+)?wrangler\s+\w*(?:deploy|secret|d1|pages|kv|routes|r2|tail|versions\s+upload)",
    r"pywrangler" + r"\s+deploy",
    r"workflow_" + r"deploy",
    r"actions/github" + r"-script",
    r"cloudflare" + r"_deployment",
    r"\bgit\s+push\b",
    r"\bgh\s+api\b",
    r"\b(?:terraform|kubectl)\s+apply\b",
    r"\-\-migrate",
)
FORBIDDEN_HTTP_METHODS = r"\b(?:POS" + r"T|PU" + r"T|PAT" + r"CH|DELET" + r"E)\b"
FORBIDDEN_TRANSFER_FLAGS = (
    r"(?:^|\s)\-X[\s=]",
    r"(?:^|\s)\-\-request[\s=]",
    r"(?:^|\s)\-d[\s=]",
    r"\-\-data",
    r"(?:^|\s)\-F[\s=]",
    r"\-\-form",
    r"(?:^|\s)\-T[\s=]",
    r"\-\-upload" + r"\-file",
)
ECHO_PRONE_TOKENS = ("echo", "printf")
TOKEN_VARS = ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _document() -> dict[str, Any]:
    return yaml.safe_load(_text())


def _triggers(document: dict[str, Any]) -> dict[str, Any]:
    # PyYAML resolves the plain scalar `on` to the boolean True.
    return document.get(True) or document.get("on") or {}


def _jobs(document: dict[str, Any]) -> dict[str, Any]:
    return document["jobs"]


def _steps(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for job in _jobs(document).values() for step in job.get("steps", [])]


def _run_bodies(document: dict[str, Any]) -> list[str]:
    return [str(step.get("run", "")) for step in _steps(document) if step.get("run")]


def find_write_commands(bodies: list[str]) -> list[str]:
    """Return every mutating command, HTTP method or transfer flag in ``bodies``."""
    offenders: list[str] = []
    for body in bodies:
        for pattern in FORBIDDEN_COMMAND_PATTERNS:
            offenders += re.findall(pattern, body)
        for pattern in FORBIDDEN_TRANSFER_FLAGS:
            offenders += re.findall(pattern, body, re.MULTILINE)
        offenders += re.findall(FORBIDDEN_HTTP_METHODS, body)
    return [offender for offender in offenders if offender]


def cloudflare_urls(body_text: str) -> list[str]:
    return re.findall(r"https://api\.cloudflare\.com/[^\s\"'\\]+", body_text)


def test_workflow_triggers_never_run_the_readout_automatically() -> None:
    triggers = _triggers(_document())
    assert set(triggers) <= {"workflow_dispatch", "pull_request"}
    dispatch = triggers["workflow_dispatch"]
    assert {"target_sha", "confirmation"} <= set(dispatch["inputs"])
    assert dispatch["inputs"]["target_sha"]["required"] is True
    assert dispatch["inputs"]["confirmation"]["required"] is True


def test_live_readout_requires_dispatch_and_the_get_only_marker() -> None:
    jobs = _jobs(_document())
    assert jobs[LIVE_JOB]["needs"] == CONTRACT_JOB
    condition = jobs[LIVE_JOB]["if"]
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert f"github.event.inputs.confirmation == '{READONLY_MARKER}'" in condition
    assert "always()" not in condition and "failure()" not in condition


def test_only_the_readout_job_holds_production_credentials() -> None:
    jobs = _jobs(_document())
    assert jobs[LIVE_JOB]["environment"] == "production"
    assert "env" not in jobs[CONTRACT_JOB]
    assert "secrets." not in yaml.dump(jobs[CONTRACT_JOB])
    readout_env = jobs[LIVE_JOB]["env"]
    assert set(readout_env) == {
        "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "TARGET_SHA"
    }
    assert "CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}" in _text()
    assert "CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}" in _text()


def test_workflow_requests_read_only_permissions() -> None:
    document = _document()
    assert document["permissions"] == {"contents": "read"}
    for job in _jobs(document).values():
        assert "permissions" not in job


def test_no_step_body_carries_a_write_command() -> None:
    assert find_write_commands(_run_bodies(_document())) == []


def test_injecting_a_write_command_fails_the_same_checker() -> None:
    tampered = list(_run_bodies(_document()))
    tampered[-1] += "\n" + "wrangler " + "deploy\n"
    assert find_write_commands(tampered) != []
    method_only = ['curl -sS --request "' + "POS" + 'T" https://api.cloudflare.com/x']
    assert find_write_commands(method_only) != []
    transfer_flag = ["curl -sS --upload" + "-file body.txt https://api.cloudflare.com/x"]
    assert find_write_commands(transfer_flag) != []


def test_the_only_cloudflare_url_is_a_deployments_record_get() -> None:
    urls = cloudflare_urls(_text())
    assert urls, "the readout must actually call Cloudflare"
    assert all(url.endswith("/deployments") for url in urls), urls
    assert len(urls) == 1


def test_served_version_selection_stays_on_the_canonical_resolver() -> None:
    body_text = _text()
    assert "from cloudflare_served_version import" in body_text
    assert "resolve_served_version_id(payload)" in body_text
    assert "ServedVersionResolutionError" in body_text
    assert ".result.deployments[0].versions[0].percentage == 100" not in body_text
    assert "(.result.deployments[0].versions | length) == 1" not in body_text


def test_three_lanes_and_two_public_hosts_are_reported() -> None:
    env = _document()["env"]
    assert env["CHAT_WORKER"] == "padiem-chat"
    assert env["ENGINE_WORKER"] == "padiem-ai-engine"
    assert env["B14_WORKER"] == "ai-revenue-korean-ai-platform"
    assert env["CHAT_HEALTH_URL"] == "https://chat.padiem.net/health"
    assert env["FILES_HEALTH_URL"] == "https://files.padiem.net/health"
    assert "for lane in chat engine b14; do" in _text()


def test_public_health_probe_reports_a_code_and_never_a_request_body() -> None:
    body_text = _text()
    assert "OPS_HEALTH_CHAT_CODE=" in body_text
    assert "OPS_HEALTH_FILES_CODE=" in body_text
    assert "UNREACHABLE" in body_text
    assert "-o /dev/null -w '%{http_code}'" in body_text


def test_results_reach_stdout_and_the_step_summary() -> None:
    body_text = _text()
    for marker in ("OPS_SERVED_CHAT", "OPS_SERVED_ENGINE", "OPS_SERVED_B14"):
        assert f'"{marker}"' in body_text, marker
    assert '_VERSION={served}"' in body_text
    assert '_DEPLOYED_AT={deployed_at}"' in body_text
    assert "=BLOCKED" in body_text and "_REASON={exc.reason}" in body_text
    assert 'summary.open("a", encoding="utf-8")' in body_text
    assert "${GITHUB_STEP_SUMMARY}" in body_text


def test_credential_values_are_only_checked_for_presence_and_never_echoed() -> None:
    assert {
        match for match in re.findall(r"secrets\.[A-Z0-9_]+", _text())
    } == ALLOWED_SECRETS
    assert "vars." not in _text()
    for body in _run_bodies(_document()):
        for line in body.splitlines():
            if any(name in line for name in TOKEN_VARS):
                assert not any(token in line for token in ECHO_PRONE_TOKENS), line


def test_every_job_prints_the_no_mutation_marker() -> None:
    bodies = _run_bodies(_document())
    assert len(bodies) >= 2
    for job in _jobs(_document()).values():
        job_bodies = [str(step.get("run", "")) for step in job.get("steps", [])]
        assert any("PRODUCTION_MUTATION=0" in body for body in job_bodies), job
    assert "B14_DEPLOY=0" in "\n".join(bodies)
    assert "D1_MUTATION=0" in "\n".join(bodies)
    assert "LIVE_PROVIDER_POST_COUNT=0" in "\n".join(bodies)
