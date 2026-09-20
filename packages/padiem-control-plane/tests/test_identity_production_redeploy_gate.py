"""#2830 B-1D: Control Plane identity Production redeploy gate source contract.

Production ``padiem-control-plane-identity`` exists but its deployed source
predates B-1A, so the ``resolve_connector_workspace`` RPC is not deployed. The
gate added for that redeploy must stay bounded to **exactly one private Worker**,
must never be reachable from a pull request, and must never touch B62, the OAuth
workers, DNS, routes or custom domains.

These tests read the workflow source only. They perform no Cloudflare call and no
deployment.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / ".github" / "workflows" / "b54-control-plane-identity-production-redeploy.yml"
IDENTITY_CONFIG = ROOT / "packages" / "padiem-control-plane" / "wrangler.identity-authority.jsonc"
IDENTITY_WORKER = ROOT / "packages" / "padiem-control-plane" / "identity_authority_worker.py"

IDENTITY_WORKER_NAME = "padiem-control-plane-identity"
STATE_WORKER_NAME = "padiem-google-oauth-state"
EDGE_WORKER_NAME = "padiem-google-oauth-edge"
B62_WORKER_NAME = "padiem-chat"
CONFIRMATION = "REDEPLOY_PADIEM_CONTROL_PLANE_IDENTITY_FROM_EXACT_MAIN"


def _gate() -> str:
    return GATE.read_text(encoding="utf-8")


def _production_deploy_lines() -> list[str]:
    """Every non-dry-run deploy command in the workflow."""

    return [
        line
        for line in _gate().splitlines()
        if "pywrangler deploy" in line and "--dry-run" not in line
    ]


# --------------------------------------------------------------------------
# 1. exact-main required
# --------------------------------------------------------------------------


def test_exact_main_is_required_before_mutation():
    source = _gate()
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in source
    assert 'test "${GITHUB_SHA}" = "${TARGET_SHA}"' in source
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in source
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in source
    assert "EXACT_CURRENT_MAIN=PASS" in source


# --------------------------------------------------------------------------
# 17. current-main recheck immediately before mutation
# --------------------------------------------------------------------------


def test_current_main_is_rechecked_immediately_before_mutation():
    source = _gate()
    # Unique echo token that exists ONLY in the immediate recheck step, so the
    # test fails if that recheck is removed (non-vacuous).
    assert "EXACT_MAIN_IMMEDIATE_RECHECK_PASSED=PASS" in source
    # The recheck has to happen after checkout/setup and before the deploy step.
    assert source.index("EXACT_MAIN_IMMEDIATE_RECHECK_PASSED=PASS") < source.index(
        "Redeploy only Control Plane identity Worker"
    )


# --------------------------------------------------------------------------
# 2-3. explicit confirmation and the production environment
# --------------------------------------------------------------------------


def test_explicit_confirmation_phrase_is_required():
    source = _gate()
    assert CONFIRMATION in source
    assert 'test "${CONFIRMATION}" = "' + CONFIRMATION + '"' in source


def test_mutation_runs_in_the_production_environment():
    source = _gate()
    assert "environment: production" in source
    redeploy_job = source[source.index("redeploy-identity-worker:") :]
    assert "environment: production" in redeploy_job


# --------------------------------------------------------------------------
# 4-5. exactly one deploy command, targeting the identity Worker only
# --------------------------------------------------------------------------


def test_exactly_one_production_deploy_command_exists():
    lines = _production_deploy_lines()
    assert len(lines) == 1, f"expected one deploy command, got {len(lines)}: {lines}"


def test_the_single_deploy_command_targets_identity_only():
    deploy_line = _production_deploy_lines()[0]
    assert "resolve_connector_workspace" in deploy_line
    assert B62_WORKER_NAME not in deploy_line
    assert "padiem-google-oauth" not in deploy_line
    # The config it deploys is the identity authority config.
    assert "IDENTITY_WORKER_REDEPLOY=1" in _gate()


def test_other_worker_configs_are_never_deployed():
    source = _gate()
    assert "wrangler.google-oauth" + ".jsonc" not in source
    assert "wrangler.google-oauth-" + "edge.jsonc" not in source
    assert IDENTITY_WORKER_NAME in source


# --------------------------------------------------------------------------
# 6-8. no other Worker is redeployed
# --------------------------------------------------------------------------


def test_oauth_state_worker_redeploy_is_zero():
    source = _gate()
    assert "OAUTH_STATE_WORKER_REDEPLOY=0" in source
    assert 'test "${STATE_AFTER}" = "${STATE_BEFORE}"' in source


def test_oauth_edge_worker_redeploy_is_zero():
    source = _gate()
    assert "OAUTH_EDGE_WORKER_REDEPLOY=0" in source
    assert 'test "${EDGE_AFTER}" = "${EDGE_BEFORE}"' in source


def test_b62_worker_redeploy_is_zero():
    source = _gate()
    assert "B62_MUTATION=0" in source
    assert "B62_WORKER_REDEPLOY=0" in source
    assert 'test "${B62_AFTER}" = "${B62_BEFORE}"' in source
    assert "B62_BINDING_MUTATION=0" in source


def test_identity_version_must_actually_change():
    source = _gate()
    assert 'test "${IDENTITY_AFTER}" != "${IDENTITY_BEFORE}"' in source
    assert "IDENTITY_ACTIVE_VERSION_CHANGED=PASS" in source
    assert "ACTIVE_EQUALS_LATEST=PASS" in source


# --------------------------------------------------------------------------
# 9-11. public topology preservation
# --------------------------------------------------------------------------


def test_no_public_route_mutation():
    source = _gate()
    assert "/workers/" + "routes" not in source
    for verb in ("POST", "PUT", "PATCH", "DELETE"):
        assert "-X " + verb not in source


def test_no_dns_or_custom_domain_mutation():
    source = _gate()
    assert "DNS_MUTATION=0" in source
    assert "CUSTOM_DOMAIN_MUTATION=0" in source
    assert "PUBLIC_TOPOLOGY_MUTATION=0" in source
    assert "LOCAL_AGENT_INGRESS_CHANGED=NO" in source
    assert "D1_MUTATION=0" in source


def test_identity_private_ingress_is_reasserted_after_deploy():
    source = _gate()
    assert "IDENTITY_PUBLIC_INGRESS_UNCHANGED=PASS" in source
    assert "PUBLIC_CUSTOM_DOMAIN=NO" in source
    # workers.dev and preview URLs must stay disabled on the identity Worker.
    assert ".result.enabled == false and .result.previews_enabled == false" in source


# --------------------------------------------------------------------------
# 12. secret boundary
# --------------------------------------------------------------------------


def test_no_secret_value_is_printed_or_read_back():
    source = _gate()
    assert "SECRET_VALUES_OUTPUT=0" in source
    assert "SECRET_VALUES_READBACK=0" in source
    # Secrets are written to a 0600 file and consumed by path, never echoed.
    assert '> "${secret_file}"' in source
    assert 'chmod 600 "${secret_file}"' in source
    assert 'trap \'rm -f "${secret_file}"' in source
    for leaked in ("${{ secrets.CONTROL_PLANE_IDENTITY_LOOKUP_KEY }}", "${{ secrets.GOOGLE_CONNECT_TICKET_KEY }}"):
        assert ("echo " + leaked) not in source


def test_secret_names_are_pinned_to_the_canonical_identity_set():
    source = _gate()
    assert "CONTROL_PLANE_IDENTITY_LOOKUP_KEY" in source
    assert "GOOGLE_CONNECT_TICKET_KEY" in source
    # Only name/type presence is verified during readback.
    assert 'any(.name == "CONTROL_PLANE_IDENTITY_LOOKUP_KEY")' in source
    assert 'any(.name == "GOOGLE_CONNECT_TICKET_KEY")' in source


# --------------------------------------------------------------------------
# 13. resolve_connector_workspace required
# --------------------------------------------------------------------------


def test_resolve_connector_workspace_is_required_in_source():
    source = _gate()
    assert "resolve_connector_workspace" in source
    worker = IDENTITY_WORKER.read_text(encoding="utf-8")
    assert "resolve_connector_workspace" in worker
    assert "RESOLVE_CONNECTOR_WORKSPACE_SOURCE_REQUIRED=PASS" in source
    assert "RESOLVE_CONNECTOR_WORKSPACE_DEPLOY_EVIDENCE=" in source


def test_identity_config_keeps_private_ingress_and_required_secrets():
    import json
    import re

    config = json.loads(re.sub(r"//.*", "", IDENTITY_CONFIG.read_text(encoding="utf-8")))
    assert config["name"] == IDENTITY_WORKER_NAME
    assert config["workers_dev"] is False
    assert config["preview_urls"] is False
    assert set(config["secrets"]["required"]) == {
        "CONTROL_PLANE_IDENTITY_LOOKUP_KEY",
        "GOOGLE_CONNECT_TICKET_KEY",
    }
    for key in ("routes", "custom_domain", "custom_domains"):
        assert key not in config


# --------------------------------------------------------------------------
# 14-15. dry-run on PR, mutation unavailable on PR
# --------------------------------------------------------------------------


def test_pr_runs_a_dry_run_only():
    source = _gate()
    assert "--dry-run" in source
    assert "IDENTITY_WORKER_PACKAGE_DRY_RUN=PASS" in source
    assert "PRODUCTION_MUTATION=0" in source


def test_mutation_is_unavailable_on_pull_request():
    source = _gate()
    redeploy_job = source[source.index("redeploy-identity-worker:") :]
    guard = redeploy_job[: redeploy_job.index("steps:")]
    assert "github.event_name == 'workflow_dispatch'" in guard
    assert "inputs.mode == 'redeploy_identity_worker'" in guard


def test_pr_paths_do_not_include_production_topology():
    import yaml

    document = yaml.safe_load(_gate())
    paths = document[True]["pull_request"]["paths"]
    for path in paths:
        assert "wrangler.toml" not in path
        assert "apps/padiem-chat" not in path


# --------------------------------------------------------------------------
# 16. rollback bounded to the identity Worker
# --------------------------------------------------------------------------


def test_rollback_is_bounded_to_the_identity_worker():
    source = _gate()
    assert "ROLLBACK_TARGET=IDENTITY_WORKER_ONLY" in source
    assert "PREVIOUS_VERSION_CAPTURE=PASS" in source
    assert "previous_identity_version" in source
    rollback_lines = [line for line in source.splitlines() if "wrangler@4 rollback" in line]
    assert len(rollback_lines) == 1
    assert IDENTITY_WORKER_NAME in rollback_lines[0]
    assert B62_WORKER_NAME not in rollback_lines[0]
    assert "padiem-google-oauth" not in rollback_lines[0]
    assert 'if: ${{ failure()' in source


# --------------------------------------------------------------------------
# Mode contract
# --------------------------------------------------------------------------


def test_dispatch_modes_are_the_reviewed_triple():
    import yaml

    document = yaml.safe_load(_gate())
    options = document[True]["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert options == ["repository_preflight", "cloudflare_readonly", "redeploy_identity_worker"]


@pytest.mark.parametrize(
    "token",
    [
        "IDENTITY_WORKER_REDEPLOY=1",
        "OAUTH_STATE_WORKER_REDEPLOY=0",
        "OAUTH_EDGE_WORKER_REDEPLOY=0",
        "B62_MUTATION=0",
        "PUBLIC_TOPOLOGY_MUTATION=0",
        "CUSTOM_DOMAIN_MUTATION=0",
        "DNS_MUTATION=0",
        "D1_MUTATION=0",
        "B62_BINDING_MUTATION=0",
        "LOCAL_AGENT_INGRESS_CHANGED=NO",
        "SECRET_VALUES_OUTPUT=0",
        "SECRET_VALUES_READBACK=0",
    ],
)
def test_invariant_tokens_are_emitted(token: str):
    assert token in _gate()
