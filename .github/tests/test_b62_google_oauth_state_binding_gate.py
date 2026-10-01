"""Source-contract regressions for the B67 Google OAuth state binding gate.

These tests are network-free. They validate only the checked-in workflow and
must never perform Cloudflare, OAuth, D1, provider, or Production mutations.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / ".github" / "workflows" / "b62-google-oauth-state-binding-gate.yml"


def source() -> str:
    return GATE.read_text(encoding="utf-8")


def test_gate_targets_exact_reviewed_binding_and_worker() -> None:
    text = source()
    assert "GOOGLE_OAUTH_BINDING: GOOGLE_OAUTH_STATE_SERVICE" in text
    assert "OAUTH_STATE_WORKER: padiem-google-oauth-state" in text
    assert 'service: "padiem-google-oauth-state"' in text
    assert 'GOOGLE_OAUTH_SERVICE_BINDING_NAME = "GOOGLE_OAUTH_STATE_SERVICE"' in text


def test_repository_config_remains_non_authoritative_for_live_binding() -> None:
    text = source()
    assert 'assert "GOOGLE_OAUTH_STATE_SERVICE" not in config' in text
    assert "DEFAULT_B62_CONFIG_MUTATION=NO" in text


def test_dispatch_modes_are_closed_and_mutation_is_explicit() -> None:
    text = source()
    for mode in (
        "repository_preflight",
        "cloudflare_readonly",
        "activate_google_oauth_state_binding",
        "rollback_google_oauth_state_binding",
    ):
        assert f"- {mode}" in text
    assert "ACTIVATE_B62_GOOGLE_OAUTH_STATE_SERVICE_BINDING" in text
    assert "ROLLBACK_B62_GOOGLE_OAUTH_STATE_SERVICE_BINDING" in text
    assert "environment: production" in text


def test_exact_main_is_rechecked_before_mutation() -> None:
    text = source()
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in text
    assert 'git fetch --no-tags --depth=1 origin main' in text
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in text


def test_only_settings_patch_is_mutation_transport() -> None:
    text = source()
    assert text.count("curl -sS -X PATCH") == 2
    assert "/workers/scripts/${B62_WORKER}/settings" in text
    assert "pywrangler deploy" not in text
    assert "wrangler deploy" not in text


def test_activation_adds_exactly_one_service_binding() -> None:
    text = source()
    assert '{"name": binding_name, "type": "service", "service": service}' in text
    assert "GOOGLE_OAUTH_STATE_SERVICE_BINDING_ADDED=PASS" in text


def test_rollback_removes_only_the_reviewed_binding() -> None:
    text = source()
    assert "GOOGLE_OAUTH_STATE_SERVICE_BINDING_REMOVED=PASS" in text
    assert '"bindings": [' in text
    assert '{"name": name, "type": "inherit", "version_id": "latest"}' in text


def test_existing_binding_and_source_exactness_are_pinned() -> None:
    text = source()
    assert "EXISTING_BINDINGS_UNCHANGED=PASS" in text
    assert "SOURCE_ETAG_UNCHANGED=PASS" in text
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in text
    assert "PUBLIC_TOPOLOGY_UNCHANGED=PASS" in text


def test_target_oauth_worker_must_remain_private() -> None:
    text = source()
    assert "OAUTH_STATE_WORKER_PRIVATE=PASS" in text
    assert ".result.enabled == false and .result.previews_enabled == false" in text


def test_secret_values_are_never_read_or_rewritten() -> None:
    text = source()
    assert "SECRET_BINDING_VALUE_READ_OR_REWRITTEN=NO" in text
    assert "ROLLBACK_SECRET_BINDING_VALUE_READ_OR_REWRITTEN=NO" in text


def test_source_contract_pins_private_workspace_truth_rpc() -> None:
    text = source()
    assert "async def workspace_connector_state" in text
    assert "WORKSPACE_CONNECTOR_STATE_RPC = True" in text
    assert "WORKSPACE_CONNECTOR_STATE_PUBLIC_ROUTE = False" in text
    assert "PUBLIC_FETCH = False" in text


def test_gate_has_no_provider_or_product_data_mutation_path() -> None:
    text = source()
    forbidden = (
        "/api/connectors/google/connect",
        "/api/connectors/google/callback",
        "/d1/database/",
        "workspace_create",
        "token_lease",
        "A6_RUNNER",
    )
    for token in forbidden:
        assert token not in text
