from __future__ import annotations

from pathlib import Path


_WORKFLOW = (
    Path(__file__).parents[3]
    / ".github"
    / "workflows"
    / "b54-local-agent-ingress-remediation-redeploy.yml"
)


def _source() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def test_gate_is_manual_only_for_production_mutation() -> None:
    source = _source()
    assert "workflow_dispatch:" in source
    assert "push:" not in source
    assert "redeploy_fetch_transport" in source
    assert 'environment: production' in source
    assert "REDEPLOY_PADIEM_LOCAL_AGENT_FETCH_TRANSPORT_STATE_THEN_EDGE" in source
    assert "github.event_name == 'workflow_dispatch'" in source
    assert "inputs.mode == 'redeploy_fetch_transport'" in source


def test_gate_pins_exact_pre_fix_production_versions_and_topology() -> None:
    source = _source()
    assert "8de403cd-b6c9-4280-a673-1e3fa4bea203" in source
    assert "7bf165c0-f320-4bb4-8410-1d516fa4960a" in source
    assert "local-agent.padiem.net" in source
    assert "padiem-local-agent-broker-state" in source
    assert "padiem-local-agent-broker-edge" in source
    assert "PINNED_PRE_FIX_VERSIONS=PASS" in source
    assert "PUBLIC_CUSTOM_DOMAIN_PRESERVED=PASS" in source
    assert "EDGE_SERVICE_BINDING=PASS" in source
    assert "PREMUTATION_EXACT_MAIN=PASS" in source
    assert "IMMEDIATE_PREMUTATION_BASELINE=PASS" in source


def test_gate_orders_state_before_edge_and_rechecks_main_between_mutations() -> None:
    source = _source()
    state_deploy = source.index("Redeploy corrected state Worker first")
    state_readback = source.index("Read back new private state version before edge mutation")
    second_main_check = source.index("Reconfirm exact main before second mutation")
    edge_deploy = source.index("Redeploy corrected edge Worker second")
    final_readback = source.index("Read back exact public/private topology after both redeploys")
    smoke = source.index("Run bounded public 405 404 401 acceptance smoke")
    assert state_deploy < state_readback < second_main_check < edge_deploy < final_readback < smoke
    assert "STATE_FIRST_REDEPLOY=SUCCESS" in source
    assert "EDGE_SECOND_REDEPLOY=SUCCESS" in source
    assert "STATE_PRIVATE_READBACK_AFTER_REDEPLOY=PASS" in source
    assert "EDGE_PRIVATE_READBACK_AFTER_REDEPLOY=PASS" in source


def test_gate_packages_both_workers_before_any_production_mutation() -> None:
    source = _source()
    deploy_tool = "py" + "wrang" + "ler deploy"
    assert "Dry-run package both exact Python Workers" in source
    assert source.count(deploy_tool) == 4
    assert source.count("--dry-run") == 2
    assert "WORKER_PACKAGING_PREFLIGHT=PASS" in source
    assert source.index("WORKER_PACKAGING_PREFLIGHT=PASS") < source.index("Redeploy corrected state Worker first")


def test_gate_requires_exact_405_404_401_public_acceptance() -> None:
    source = _source()
    assert "GET_SESSION_405 405 GET /session '' local_agent_http_post_required" in source
    assert "UNKNOWN_POST_404 404 POST /not-a-device-route '{}' local_agent_http_route_not_found" in source
    assert "UNAUTH_SESSION_401 401 POST /session '{}' local_agent_http_auth_required" in source
    assert "PUBLIC_405_404_401_SMOKE=PASS" in source
    assert "WINDOWS_LIVE_CANARY=NO" in source
    assert "USER_ROLLOUT=NO" in source
    assert "PRODUCTION_READY=NO" in source


def test_gate_never_mutates_domain_dns_routes_or_deletes_durable_state() -> None:
    source = _source()
    assert "CUSTOM_DOMAIN_MUTATION=NO" in source
    assert "DNS_MUTATION=NO" in source
    assert "WORKER_ROUTE_MUTATION=NO" in source
    assert "CUSTOM_DOMAIN_DELETE=NO" in source
    assert "DURABLE_OBJECT_DELETE=NO" in source
    assert "DURABLE_OBJECT_STORAGE_MIGRATION=NO" in source
    assert "AUTO_WORKER_ROLLBACK=NO" in source
    assert "-X DELETE" not in source
    assert "/dns_records" not in source


def test_source_contract_requires_fetch_transport_without_new_authority() -> None:
    source = _source()
    assert 'EDGE_TO_STATE_DEVICE_TRANSPORT = "service_binding_fetch"' in source
    assert "LOCAL_AGENT_BROKER_SERVICE.fetch(" in source
    assert "CANONICAL_DEVICE_HTTP_SERVICE_REUSED = True" in source
    assert "SECOND_DEVICE_AUTHORITY = False" in source
    assert "ADMIN_RPC_HTTP_EXPOSED = False" in source
    assert "REMEDIATION_SOURCE_CONTRACT=PASS" in source
