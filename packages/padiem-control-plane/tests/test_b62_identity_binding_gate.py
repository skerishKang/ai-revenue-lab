from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / ".github" / "workflows" / "b62-control-plane-identity-binding-gate.yml"


def test_binding_gate_is_exact_main_and_explicitly_mutating():
    source = GATE.read_text(encoding="utf-8")

    assert "B62 Control Plane Identity Binding Gate" in source
    assert "repository_preflight" in source
    assert "cloudflare_readonly" in source
    assert "activate_identity_binding" in source
    assert "rollback_identity_binding" in source
    assert "ACTIVATE_B62_CONTROL_PLANE_IDENTITY_SERVICE_BINDING" in source
    assert "ROLLBACK_B62_CONTROL_PLANE_IDENTITY_SERVICE_BINDING" in source
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in source
    assert "environment: production" in source


def test_binding_gate_inherits_existing_bindings_instead_of_reconstructing_them():
    source = GATE.read_text(encoding="utf-8")

    assert '"type": "inherit"' in source
    assert '"version_id": "latest"' in source
    assert '"version_id": active_version' not in source
    assert '"name": binding_name' in source
    assert '"type": "service"' in source
    assert '"service": identity_worker' in source
    assert "SECRET_BINDING_VALUE_READ_OR_REWRITTEN=NO" in source
    assert "Existing Worker bindings changed during identity binding patch" in source


def test_binding_gate_observes_binding_shape_and_allows_inherit_or_concrete_readback():
    source = GATE.read_text(encoding="utf-8")

    assert "B62_BINDINGS_SHAPE_OBSERVATION" in source
    assert 'has_version_id: has("version_id")' in source
    assert "neither inherit/latest nor identical to pre-patch state" in source
    assert "neither inherit/latest nor identical to pre-rollback state" in source
    assert "before_by_name" in source
    assert "expected_by_name" in source
    assert "PAYLOAD_INHERIT_VERSION_ID_LATEST=YES" in source


def test_binding_gate_requires_latest_active_version_and_preserves_source_and_public_topology():
    source = GATE.read_text(encoding="utf-8")

    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in source
    assert "resources.script.etag" in source
    assert "SOURCE_ETAG_UNCHANGED=PASS" in source
    assert "EXISTING_BINDINGS_UNCHANGED=PASS" in source
    assert "PUBLIC_TOPOLOGY_UNCHANGED=PASS" in source
    assert "WORKER_SOURCE_REDEPLOY=NO" in source
    assert "LOCAL_AGENT_INGRESS_CHANGED=NO" in source


def test_binding_gate_readback_retries_latest_version_propagation():
    source = GATE.read_text(encoding="utf-8")

    assert "LATEST_VERSION_PROPAGATION_RETRY=OK" in source
    assert '"${latest}" = "${active}"' in source
    assert ".result.items[0].id // empty" in source
    assert source.count("for _ in $(seq 1 4); do") == 2


def test_binding_gate_keeps_default_b62_config_unmodified():
    source = GATE.read_text(encoding="utf-8")
    config_name = "wrang" + "ler.toml"
    default_config = (ROOT / "apps" / "padiem-chat" / config_name).read_text(encoding="utf-8")

    assert "IDENTITY_AUTHORITY_SERVICE" not in default_config
    assert "DEFAULT_B62_CONFIG_MUTATION=NO" in source
    assert "/workers/scripts/${B62_WORKER}/settings" in source
    assert "-X PATCH" in source


def test_binding_gate_rollback_removes_only_identity_binding():
    source = GATE.read_text(encoding="utf-8")

    assert "Expected exactly one identity binding before rollback" in source
    assert "Rollback modified an existing non-identity binding" in source
    assert "IDENTITY_SERVICE_BINDING_REMOVED=PASS" in source
    assert "PUBLIC_TOPOLOGY_UNCHANGED=PASS" in source
