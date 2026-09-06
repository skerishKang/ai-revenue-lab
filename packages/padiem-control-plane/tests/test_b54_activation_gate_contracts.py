from __future__ import annotations

from pathlib import Path


_WORKFLOW = (
    Path(__file__).parents[3]
    / ".github"
    / "workflows"
    / "b54-local-agent-public-ingress-activation.yml"
)


def _source() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_activation_gate_is_manual_only_for_production_mutation() -> None:
    source = _source()
    assert "workflow_dispatch:" in source
    assert "push:" not in source
    assert "preflight_only" in source
    assert "activate_public_ingress" in source
    assert "rollback_remove_custom_domain" in source
    assert 'environment: production' in source
    assert "ACTIVATE_B54_LOCAL_AGENT_PUBLIC_INGRESS_LOCAL_AGENT_PADIEM_NET" in source
    assert "ROLLBACK_B54_LOCAL_AGENT_PUBLIC_INGRESS_REMOVE_CUSTOM_DOMAIN" in source
    assert "inputs.mode == 'activate_public_ingress'" in source
    assert "inputs.mode == 'rollback_remove_custom_domain'" in source


def test_activation_gate_requires_exact_target_hostname() -> None:
    source = _source()
    assert "target_hostname:" in source
    assert 'test "${TARGET_HOSTNAME}" = "local-agent.padiem.net"' in source
    assert 'test "${TARGET_HOSTNAME}" = "${PUBLIC_HOSTNAME}"' in source
    assert "HOSTNAME_VALIDATION=PASS" in source


def test_activation_gate_requires_exact_main_sha_input_and_verification() -> None:
    source = _source()
    assert "exact_main_sha:" in source
    assert "TARGET_SHA: ${{ inputs.exact_main_sha }}" in source
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in source
    assert "EXACT_MAIN=PASS" in source
    assert "PREMUTATION_EXACT_MAIN=PASS" in source
    assert "ROLLBACK_EXACT_MAIN=PASS" in source


def test_activation_gate_pins_current_post_remediation_versions() -> None:
    source = _source()
    assert "b5b5e0f1-96de-4521-8242-86466b4b1803" in source
    assert "c2217fb5-3a63-4fd5-90d9-431bd94c4a97" in source
    assert "8de403cd-b6c9-4280-a673-1e3fa4bea203" not in source
    assert "7bf165c0-f320-4bb4-8410-1d516fa4960a" not in source
    assert "DEPLOYED_VERSION_PIN=PASS" in source


def test_activation_gate_preflight_validates_hostname_routes_and_dns_authority() -> None:
    source = _source()
    assert "PRIVATE_STATE_WORKER_PUBLIC=NO" in source
    assert "EDGE_ONLY_PUBLIC_CANDIDATE=YES" in source
    assert "CLOSED_DEVICE_ROUTES=PASS" in source
    assert "EDGE_SERVICE_BINDING=PASS" in source
    assert "ROUTE_VALIDATION=PASS" in source
    assert "DNS_AUTHORITY_MUTATION=NO" in source
    assert "CLOUDFLARE_READONLY=PASS" in source
    assert "CANDIDATE_CUSTOM_DOMAIN=PRESENT_EDGE" in source
    assert "CANDIDATE_CUSTOM_DOMAIN=ABSENT" in source
    assert "Refusing ambiguous Custom Domain state." in source


def test_activation_gate_rechecks_versions_and_boundary_before_mutation() -> None:
    source = _source()
    authorization = source.index("Require explicit owner activation authorization and exact main")
    precheck = source.index("Fail-closed recheck immediately before mutation")
    attach = source.index("Attach exact Custom Domain to existing edge Worker if absent")
    already_active = source.index("Confirm existing Custom Domain stays attached to edge Worker")
    readback = source.index("Read back exact public boundary and run bounded unauthenticated HTTPS smoke")
    assert authorization < precheck < attach < already_active < readback
    assert "IMMEDIATE_PREMUTATION_BASELINE=PASS" in source
    assert "CUSTOM_DOMAIN_ATTACH=SUCCESS" in source
    assert "CUSTOM_DOMAIN_ALREADY_ACTIVE=YES" in source
    assert "CUSTOM_DOMAIN_MUTATION=NONE" in source
    assert "WORKER_REDEPLOY=NO" in source
    assert "DURABLE_OBJECT_MUTATION=NO" in source


def test_activation_gate_runs_405_404_401_public_acceptance() -> None:
    source = _source()
    assert "GET_SESSION_405 405 GET /session '' local_agent_http_post_required" in source
    assert "UNKNOWN_POST_404 404 POST /not-a-device-route '{}' local_agent_http_route_not_found" in source
    assert "UNAUTH_SESSION_401 401 POST /session '{}' local_agent_http_auth_required" in source
    assert "PUBLIC_CUSTOM_DOMAIN_READBACK=PASS" in source
    assert "PUBLIC_405_404_401_SMOKE=PASS" in source
    assert "WINDOWS_LIVE_CANARY=NO" in source
    assert "USER_ROLLOUT=NO" in source
    assert "PRODUCTION_READY=NO" in source


def test_activation_gate_rollback_preserves_durable_state_and_versions() -> None:
    source = _source()
    assert "CUSTOM_DOMAIN_DETACH=SUCCESS" in source
    assert "STATE_WORKER_DELETED=NO" in source
    assert "EDGE_WORKER_DELETED=NO" in source
    assert "DURABLE_OBJECT_DELETED=NO" in source
    assert "DURABLE_OBJECT_STORAGE_MIGRATION=NO" in source
    assert "VERSIONS_PRESERVED=PASS" in source
    rollback = source.index("Detach only the exact Custom Domain")
    readback = source.index("CUSTOM_DOMAIN_DETACH=SUCCESS")
    assert rollback < readback
    assert "/workers/domains/${DOMAIN_ID}" in source


def test_activation_gate_never_deletes_workers_or_durable_storage() -> None:
    source = _source()
    assert source.count("-X DELETE") == 1
    delete_pos = source.index("-X DELETE")
    assert source.index("/workers/domains/${DOMAIN_ID}") > delete_pos
    assert "dns_records" not in source
    assert "/storage" not in source
    assert "/migrations" not in source
    assert "workers/scripts" not in source[delete_pos:delete_pos + 400]
    assert "delete_durable_object" not in source.lower()
