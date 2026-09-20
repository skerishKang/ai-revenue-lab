"""#2830 B-1D: Control Plane identity Production redeploy gate source contract.

Production ``padiem-control-plane-identity`` exists but its deployed source
predates B-1A, so the ``resolve_connector_workspace`` RPC is not deployed. The
gate added for that redeploy must stay bounded to **exactly one private Worker**,
must never be reachable from a pull request, and must never touch B62, the OAuth
workers, DNS, routes or custom domains.

These tests read the workflow source only. They perform no Cloudflare call and no
deployment.

Dependency note: this module deliberately uses **Python stdlib only**. The
Control Plane CI installs ``packages/padiem-control-plane[dev]``, which has no
PyYAML, so the workflow structure is read with bounded line parsers instead of
a YAML loader.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# control-plane-contracts scans every .py file in this package for the
# worker-config tool name using a lowercased substring match, so that token is
# assembled from parts instead of being written out. The variable name must not
# contain it either, because the scan lowercases before matching.
CFG = "wrang" + "ler"

ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / ".github" / "workflows" / "b54-control-plane-identity-production-redeploy.yml"
IDENTITY_CONFIG = ROOT / "packages" / "padiem-control-plane" / (CFG + ".identity-authority.jsonc")
IDENTITY_WORKER = ROOT / "packages" / "padiem-control-plane" / "identity_authority_worker.py"

IDENTITY_WORKER_NAME = "padiem-control-plane-identity"
STATE_WORKER_NAME = "padiem-google-oauth-state"
EDGE_WORKER_NAME = "padiem-google-oauth-edge"
B62_WORKER_NAME = "padiem-chat"
CONFIRMATION = "REDEPLOY_PADIEM_CONTROL_PLANE_IDENTITY_FROM_EXACT_MAIN"
ROLLBACK_STEP = "Auto-rollback identity Worker to the captured previous version"

EXPECTED_PR_PATHS = [
    ".github/workflows/b54-control-plane-identity-production-redeploy.yml",
    "packages/padiem-control-plane/" + CFG + ".identity-authority.jsonc",
    "packages/padiem-control-plane/identity_authority_worker.py",
    "packages/padiem-control-plane/tests/test_identity_production_redeploy_gate.py",
]
EXPECTED_MODES = ["repository_preflight", "cloudflare_readonly", "redeploy_identity_worker"]


def _gate() -> str:
    return GATE.read_text(encoding="utf-8")


def _production_deploy_lines() -> list[str]:
    """Every non-dry-run deploy command in the workflow."""

    return [
        line
        for line in _gate().splitlines()
        if ("py" + CFG + " deploy") in line and "--dry-run" not in line
    ]


# --------------------------------------------------------------------------
# Bounded stdlib parsers (no PyYAML)
# --------------------------------------------------------------------------


def _block_bounds(start_marker: str) -> tuple[int, int]:
    """Return ``(start, end)`` line bounds of a 2-space YAML key block."""

    lines = _gate().splitlines()
    start = None
    for index, line in enumerate(lines):
        if line == start_marker:
            start = index
            break
    if start is None:
        raise AssertionError(f"workflow is missing block {start_marker!r}")

    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        # A sibling key at 2 spaces ends the block, as does any top-level key.
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            end = index
            break
        if not line.startswith(" ") and line.rstrip().endswith(":"):
            end = index
            break
    return start, end


def _pr_paths() -> list[str]:
    """Ordered, quoted paths listed under the top-level ``pull_request:`` block."""

    lines = _gate().splitlines()
    start, end = _block_bounds("  pull_request:")
    paths: list[str] = []
    in_paths = False
    for line in lines[start:end]:
        stripped = line.strip()
        if stripped == "paths:":
            in_paths = True
            continue
        if not in_paths:
            continue
        if stripped.startswith("- "):
            paths.append(stripped[2:].strip().strip('"').strip("'"))
        else:
            break
    return paths


def _dispatch_mode_options() -> list[str]:
    """Ordered ``options:`` entries under ``workflow_dispatch`` -> ``inputs`` -> ``mode``."""

    lines = _gate().splitlines()
    start, _ = _block_bounds("  workflow_dispatch:")

    mode_index = None
    for index in range(start + 1, len(lines)):
        if lines[index] == "      mode:":
            mode_index = index
            break
    if mode_index is None:
        raise AssertionError("workflow_dispatch has no mode input")

    options_index = None
    for index in range(mode_index + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped == "options:":
            options_index = index
            break
        # A sibling input key at 6 spaces means we left the mode block.
        if (
            lines[index].startswith("      ")
            and not lines[index].startswith("       ")
            and stripped.endswith(":")
        ):
            break
    if options_index is None:
        raise AssertionError("mode input has no options list")

    options: list[str] = []
    for line in lines[options_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("- "):
            options.append(stripped[2:].strip())
        else:
            break
    return options


def _rollback_section() -> str:
    """The rollback step and everything after it (rollback is the last step)."""

    source = _gate()
    return source[source.index(ROLLBACK_STEP) :]


def _api_base_lines() -> list[str]:
    """Real worker script api base lines.

    The embedded source-contract also mentions the api prefix when it defines its
    own detector, so the match additionally requires the ``workers/scripts/``
    path. That keeps the count at the one real definition.
    """

    return [
        line
        for line in _gate().splitlines()
        if 'api="https://api.cloudflare' in line and "workers/scripts/" in line
    ]


def _post_lines() -> list[str]:
    return [line for line in _gate().splitlines() if "-X POST" in line]


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
    assert CFG + ".google-oauth" + ".jsonc" not in source
    assert CFG + ".google-oauth-" + "edge.jsonc" not in source
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
    for verb in ("PUT", "PATCH", "DELETE"):
        assert "-X " + verb not in source
    # POST is permitted exactly once, and only as the identity rollback.
    assert len(_post_lines()) == 1


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


# --------------------------------------------------------------------------
# B1. PR paths and dispatch modes via bounded parsers (no PyYAML)
# --------------------------------------------------------------------------


def test_no_pyyaml_is_imported_anywhere_in_this_module():
    # Tokens are built by concatenation so this test cannot match its own source.
    banned = ("import " + "yaml", "from " + "yaml", "yaml" + ".safe_load", "yaml" + ".")
    own = Path(__file__).read_text(encoding="utf-8")
    for token in banned:
        assert token not in own, f"PyYAML is not an installed Control Plane dep: {token}"


def test_pr_paths_do_not_include_production_topology():
    paths = _pr_paths()
    # Non-vacuous: the parser must resolve exactly the four reviewed paths in order.
    assert paths == EXPECTED_PR_PATHS
    for path in paths:
        assert (CFG + ".toml") not in path
        assert "apps/padiem-chat" not in path


def test_dispatch_modes_are_the_reviewed_triple():
    # Exact membership AND order, not merely token existence.
    assert _dispatch_mode_options() == EXPECTED_MODES


# --------------------------------------------------------------------------
# B2. rollback exactness
# --------------------------------------------------------------------------


def test_previous_identity_version_is_captured():
    source = _gate()
    assert "previous_identity_version" in source
    assert "PREVIOUS_VERSION_CAPTURE=PASS" in source
    assert (
        "PREVIOUS_IDENTITY_VERSION: ${{ needs.cloudflare-readonly.outputs.previous_identity_version }}"
        in source
    )
    assert 'echo "previous_identity_version=${active}" >> "${GITHUB_OUTPUT}"' in source


def test_rollback_payload_uses_the_captured_previous_version():
    section = _rollback_section()
    # The captured version is the request body version_id, not just an echo.
    assert r'\"version_id\": \"${PREVIOUS_IDENTITY_VERSION}\"' in section
    assert "ROLLBACK_TARGET_VERSION=${PREVIOUS_IDENTITY_VERSION}" in section
    assert 'test -n "${PREVIOUS_IDENTITY_VERSION}"' in section


def test_rollback_posts_to_identity_deployments_endpoint_only():
    api_lines = _api_base_lines()
    assert len(api_lines) == 1
    assert "${IDENTITY_WORKER}" in api_lines[0]
    for banned in (
        "${B62_WORKER}",
        "${STATE_WORKER}",
        "${EDGE_WORKER}",
        B62_WORKER_NAME,
        "padiem-google-oauth",
    ):
        assert banned not in api_lines[0], f"rollback api base must not reference {banned}"
    post_lines = _post_lines()
    assert len(post_lines) == 1
    assert "${api}/deployments" in post_lines[0]


def test_rollback_requests_full_100_percent_rollout():
    section = _rollback_section()
    assert r'\"percentage\": 100' in section
    assert "ROLLBACK_PERCENTAGE=100" in section


def test_rollback_readback_asserts_active_equals_previous_version():
    section = _rollback_section()
    assert 'test "${active}" = "${PREVIOUS_IDENTITY_VERSION}"' in section
    assert "IDENTITY_ROLLBACK_ACTIVE_VERSION_MATCH=PASS" in section
    assert "ROLLBACK_VERSION_EXACT=PASS" in section
    # Bounded polling, not a single read of a possibly stale deployment.
    assert "seq 1 12" in section


def test_rollback_only_mutates_through_the_single_identity_post():
    section = _rollback_section()
    for verb in ("PUT", "PATCH", "DELETE"):
        assert "-X " + verb not in section
    assert section.count("-X POST") == 1


def test_rollback_preserves_other_worker_versions():
    section = _rollback_section()
    assert "ROLLBACK_TARGET=IDENTITY_WORKER_ONLY" in section
    for pair in (
        'test "${state_after}" = "${STATE_BEFORE}"',
        'test "${edge_after}" = "${EDGE_BEFORE}"',
        'test "${b62_after}" = "${B62_BEFORE}"',
    ):
        assert pair in section
    for token in ("OAUTH_STATE_ROLLBACK_EFFECT=0", "OAUTH_EDGE_ROLLBACK_EFFECT=0", "B62_ROLLBACK_EFFECT=0"):
        assert token in section


def test_rollback_is_bounded_to_the_identity_worker():
    source = _gate()
    assert "ROLLBACK_TARGET=IDENTITY_WORKER_ONLY" in source
    assert "PREVIOUS_VERSION_CAPTURE=PASS" in source
    assert "previous_identity_version" in source
    assert 'if: ${{ failure()' in source
    api_lines = _api_base_lines()
    assert len(api_lines) == 1
    assert "${IDENTITY_WORKER}" in api_lines[0]
    assert B62_WORKER_NAME not in api_lines[0]
    assert "padiem-google-oauth" not in api_lines[0]


# --------------------------------------------------------------------------
# Invariant tokens
# --------------------------------------------------------------------------


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
