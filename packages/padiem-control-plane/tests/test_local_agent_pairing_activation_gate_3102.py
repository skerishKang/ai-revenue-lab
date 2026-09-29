"""#3102 — executable pairing activation gate contracts.

Two halves, mirroring the repository's gate-test style:

* the manual gate workflow is asserted as *source text*, because its job is to
  be the thing a reviewer can see cannot mutate Production;
* the evaluator is exercised directly, because fail-closed behaviour is what
  makes a bounded canary claim meaningful.

No network, no Cloudflare call, no server, no dispatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_pairing_activation_3102 import (
    SOURCE_ONLY_READINESS,
    PairingActivationReadiness,
    assert_not_activated,
)
from padiem_control_plane.local_agent_pairing_activation_gate_3102 import (
    CANONICAL_RATE_ERROR_CODE,
    CanaryObservation,
    FIXED_BROKER_AUTHORITY_REF,
    GATE_MODES,
    GATE_STAGES,
    PUBLIC_HOSTNAME,
    RATE_LIMIT_BINDING_NAME,
    RateBoundGate,
    RevokeRepairObservation,
    RollbackDisableObservation,
    _main,
    assert_secret_free_gate_projection,
    evaluate_activation_gate,
)

_REPO_ROOT = Path(__file__).parents[3]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "b54-local-agent-pairing-activation-gate.yml"

_SHA = "5ad64e98113004d314d53549b6ffe4951f7173f1"


def _source() -> str:
    return _WORKFLOW.read_text(encoding="utf-8")


def _good_rate() -> RateBoundGate:
    return RateBoundGate(RATE_LIMIT_BINDING_NAME, 5, 600, 4_096)


def _good_canary(**overrides) -> CanaryObservation:
    values = {
        "challenge_issued": True,
        "redeem_count": 1,
        "paired_offline_reached": True,
        "lifecycle_state": "online",
        "session_opened": True,
        "heartbeat_acknowledged": True,
        "online_projection": "online",
        "transport_scheme": "https",
        "transport_port": 443,
        "caller_endpoint_override": False,
        "public_inbound_port": 0,
    }
    values.update(overrides)
    return CanaryObservation(**values)


def _good_repair(**overrides) -> RevokeRepairObservation:
    values = {
        "revoked_state_reached": True,
        "credential_refused_after_revoke": True,
        "expired_state_reached": True,
        "repair_via_canonical_flow": True,
        "second_repair_redeem_count": 0,
    }
    values.update(overrides)
    return RevokeRepairObservation(**values)


def _good_rollback(**overrides) -> RollbackDisableObservation:
    values = {
        "disable_flag_cleared": True,
        "issuance_refuses_new_scopes": True,
        "online_projection_not_forged": True,
        "durable_pairing_state_preserved": True,
        "issued_credentials_preserved": True,
    }
    values.update(overrides)
    return RollbackDisableObservation(**values)


# ---------------------------------------------------------------------------
# Workflow source contracts
# ---------------------------------------------------------------------------


def test_gate_is_manual_only_and_offers_only_non_mutating_modes() -> None:
    source = _source()
    assert "workflow_dispatch:" in source
    assert "push:" not in source
    for mode in GATE_MODES:
        assert f"- {mode}" in source
    assert "permissions:\n  contents: read" in source
    # No mutating mode is offered on this gate at all: bootstrap stays with the
    # broker gate, and the custom-domain step stays with the ingress gate.
    assert "- bootstrap_private" not in source
    assert "mode == 'bootstrap_private'" not in source
    assert "- activate_public_ingress" not in source
    assert "mode == 'activate_public_ingress'" not in source
    assert "BOOTSTRAP_PRIVATE_IS_NOT_3102_COMPLETION=YES" in source


def test_gate_requires_exact_main_sha_and_guards_it() -> None:
    source = _source()
    assert "exact_main_sha:" in source
    assert "TARGET_SHA: ${{ inputs.exact_main_sha }}" in source
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in source
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in source
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in source
    assert "EXACT_MAIN=PASS" in source


def test_gate_self_enforces_that_it_cannot_mutate_production() -> None:
    source = _source()
    for forbidden in ("wrangler deploy", "wrangler d1", "wrangler secret", "pages deploy"):
        assert forbidden in source  # the guard list itself
    assert "FORBIDDEN_MUTATION_COMMAND" in source
    assert "PRODUCTION_MUTATION=0" in source
    assert "BOOTSTRAP_PRIVATE_IS_NOT_3102_COMPLETION=YES" in source
    # The guard must trip when a mutating command is actually present.
    assert 'if grep -q "${forbidden}"' in source


def test_gate_delegates_infrastructure_instead_of_duplicating_it() -> None:
    source = _source()
    assert "DELEGATED_TO=b54-local-agent-broker-production-gate.yml" in source
    assert "b54-local-agent-public-ingress-activation.yml" in source
    # Read-only readiness may list deployed workers, but never deploy them.
    assert "workers/scripts" in source
    assert "wrangler deploy" in source  # only inside the forbidden-command guard


def test_gate_pins_the_fixed_authority_and_rate_binding() -> None:
    source = _source()
    assert f"AUTHORITY_REF: {FIXED_BROKER_AUTHORITY_REF}" in source
    assert f"PUBLIC_HOSTNAME: {PUBLIC_HOSTNAME}" in source
    assert f"RATE_BINDING: {RATE_LIMIT_BINDING_NAME}" in source
    assert CANONICAL_RATE_ERROR_CODE in source
    # No caller-supplied broker destination is accepted anywhere.
    assert "broker_url" not in source
    assert "target_hostname" not in source


def test_gate_evaluates_the_canonical_sources_and_the_executable_evaluator() -> None:
    source = _source()
    assert "local_agent_broker_pairing.py" in source
    assert "local_agent_pairing_activation_3102.py" in source
    assert "local_agent_pairing_activation_gate_3102.py" in source
    assert "--mode repository_preflight" in source
    assert "--observation" in source
    assert "OBSERVATION_DECODED=YES" in source
    assert "SECRET_FREE_EVIDENCE=PASS" in source
    assert "RATE_BOUND_GATE=" in source
    assert "LIVE_CANARY_CONTRACT=" in source
    assert "ROLLBACK_DISABLE=" in source


def test_gate_stages_cover_every_required_step() -> None:
    assert set(GATE_STAGES) == {
        "repository_preflight",
        "cloudflare_readonly_readiness",
        "exact_main_guard",
        "rate_bound_gate",
        "canary_contract",
        "revoke_contract",
        "expired_repair_contract",
        "rollback_disable_contract",
        "secret_free_evidence",
    }


# ---------------------------------------------------------------------------
# Rate-bound gate
# ---------------------------------------------------------------------------


def test_unbound_rate_fails_closed() -> None:
    verdict = RateBoundGate(RATE_LIMIT_BINDING_NAME, None, 600, 4_096).evaluate()
    assert verdict["RATE_BOUND_ACTIVE"] is False
    assert verdict["RATE_BOUND_GATE"] == "FAIL_RATE_BOUND_NOT_ACTIVE"


def test_bound_rate_passes() -> None:
    verdict = _good_rate().evaluate()
    assert verdict["RATE_BOUND_ACTIVE"] is True
    assert verdict["RATE_BOUND_GATE"] == "PASS"
    assert verdict["RATE_ENFORCEMENT_ERROR_CODE"] == CANONICAL_RATE_ERROR_CODE


def test_rate_projection_must_come_from_the_canonical_authority() -> None:
    gate = RateBoundGate.from_authority_safe_dict(
        {"rate_limit": 3, "rate_bound_active": True, "window_seconds": 600, "max_tracked_scopes": 4096}
    )
    assert gate.evaluate()["RATE_BOUND_GATE"] == "PASS"
    with pytest.raises(ControlPlaneContractError):
        RateBoundGate.from_authority_safe_dict({"rate_limit": 3})
    with pytest.raises(ControlPlaneContractError):
        RateBoundGate.from_authority_safe_dict("not-a-mapping")
    with pytest.raises(ControlPlaneContractError):
        RateBoundGate("SOME_OTHER_BINDING", 3, 600, 4_096)
    with pytest.raises(ControlPlaneContractError):
        RateBoundGate(RATE_LIMIT_BINDING_NAME, 0, 600, 4_096)


# ---------------------------------------------------------------------------
# Canary contract
# ---------------------------------------------------------------------------


def test_canary_contract_passes_only_for_the_full_chain() -> None:
    verdict = _good_canary().evaluate()
    assert verdict["LIVE_CANARY_CONTRACT"] == "PASS"
    assert all(verdict["checks"].values())
    assert verdict["SYSTEM_STATUS_ONLINE"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"challenge_issued": False},
        {"redeem_count": 0},
        {"redeem_count": 2},
        {"paired_offline_reached": False},
        {"lifecycle_state": "paired_offline"},
        {"session_opened": False},
        {"heartbeat_acknowledged": False},
        {"online_projection": "paired_offline"},
        {"transport_scheme": "http"},
        {"transport_port": 8080},
        {"caller_endpoint_override": True},
        {"public_inbound_port": 1},
    ],
)
def test_canary_contract_fails_closed_on_any_single_violation(overrides) -> None:
    verdict = _good_canary(**overrides).evaluate()
    assert verdict["LIVE_CANARY_CONTRACT"] == "FAIL"
    assert not all(verdict["checks"].values())


# ---------------------------------------------------------------------------
# Revoke / repair and rollback / disable
# ---------------------------------------------------------------------------


def test_revoke_and_repair_contract() -> None:
    assert _good_repair().evaluate()["REVOKE_REPAIR_CONTRACT"] == "PASS"


@pytest.mark.parametrize(
    "overrides",
    [
        {"revoked_state_reached": False},
        {"credential_refused_after_revoke": False},
        {"expired_state_reached": False},
        {"repair_via_canonical_flow": False},
        {"second_repair_redeem_count": 1},
    ],
)
def test_revoke_repair_fails_closed(overrides) -> None:
    assert _good_repair(**overrides).evaluate()["REVOKE_REPAIR_CONTRACT"] == "FAIL"


def test_rollback_is_a_disable_never_a_delete() -> None:
    assert _good_rollback().evaluate()["ROLLBACK_DISABLE"] == "PASS"


@pytest.mark.parametrize(
    "overrides",
    [
        {"disable_flag_cleared": False},
        {"issuance_refuses_new_scopes": False},
        {"online_projection_not_forged": False},
        {"durable_pairing_state_preserved": False},
        {"issued_credentials_preserved": False},
    ],
)
def test_rollback_disable_fails_closed(overrides) -> None:
    assert _good_rollback(**overrides).evaluate()["ROLLBACK_DISABLE"] == "FAIL"


# ---------------------------------------------------------------------------
# Projection contracts
# ---------------------------------------------------------------------------


def test_preflight_projection_is_secret_free_and_claims_no_authority() -> None:
    projection = evaluate_activation_gate(exact_main_sha=_SHA, gate_mode="repository_preflight")
    assert projection["gate_verdict"] == "SOURCE_READY_PREFLIGHT_PASS"
    assert projection["second_pairing_authority"] == 0
    assert projection["second_device_lifecycle_authority"] == 0
    assert projection["second_session_authority"] == 0
    assert projection["production_mutation"] is False
    assert projection["caller_broker_url_override"] is False
    assert projection["public_inbound_pc_port"] == 0
    assert projection["secret_output"] is False
    assert projection["binding_values_present"] is False
    assert projection["bootstrap_private_is_3102_completion"] is False
    assert_secret_free_gate_projection(projection)


def test_canary_mode_refuses_while_the_rate_bound_is_inactive() -> None:
    projection = evaluate_activation_gate(
        exact_main_sha=_SHA,
        gate_mode="canary_contract_evaluate",
        canary=_good_canary(),
    )
    # A satisfied canary with an unbounded issuance surface is not an activation.
    assert projection["gate_verdict"] == "FAIL_RATE_BOUND_NOT_ACTIVE"


def test_canary_mode_passes_only_with_bound_rate_and_full_chain() -> None:
    projection = evaluate_activation_gate(
        exact_main_sha=_SHA,
        gate_mode="canary_contract_evaluate",
        rate=_good_rate(),
        canary=_good_canary(),
    )
    assert projection["gate_verdict"] == "PASS"


def test_unsupported_mode_and_bad_sha_are_refused() -> None:
    with pytest.raises(ControlPlaneContractError):
        evaluate_activation_gate(exact_main_sha=_SHA, gate_mode="activate_everything")
    with pytest.raises(ControlPlaneContractError):
        evaluate_activation_gate(exact_main_sha="main", gate_mode="repository_preflight")


def test_projection_rejects_an_unexpected_field() -> None:
    projection = evaluate_activation_gate(exact_main_sha=_SHA, gate_mode="repository_preflight")
    projection["pairing_code"] = "deadbeef"
    with pytest.raises(ControlPlaneContractError):
        assert_secret_free_gate_projection(projection)


def test_gate_cannot_claim_a_live_activation() -> None:
    # The activation contract's own guard stays the single assertion of this
    # rule, and the gate refuses any readiness that claims an activation.
    assert_not_activated(SOURCE_ONLY_READINESS)
    with pytest.raises(ControlPlaneContractError):
        evaluate_activation_gate(
            exact_main_sha=_SHA,
            gate_mode="repository_preflight",
            readiness=PairingActivationReadiness(
                source_ready=True,
                production_activated=True,
                trusted_tls_required=True,
                outbound_only_desktop=True,
                public_inbound_port=False,
                upnp_required=False,
                caller_endpoint_override=False,
                challenge_ttl_bounded=True,
                challenge_single_use=True,
                issuance_rate_bound_active=True,
                revoke_path_available=True,
                rotate_path_available=True,
                server_backed_online_only=True,
                canonical_authorities_reused=True,
            ),
        )


# ---------------------------------------------------------------------------
# Bounded CLI (the executable path the manual gate workflow invokes)
# ---------------------------------------------------------------------------


def _good_observation() -> dict:
    return {
        "rate": {"rate_limit": 5, "rate_bound_active": True, "window_seconds": 600, "max_tracked_scopes": 4096},
        "canary": {
            "challenge_issued": True,
            "redeem_count": 1,
            "paired_offline_reached": True,
            "lifecycle_state": "online",
            "session_opened": True,
            "heartbeat_acknowledged": True,
            "online_projection": "online",
            "transport_scheme": "https",
            "transport_port": 443,
            "caller_endpoint_override": False,
            "public_inbound_port": 0,
        },
        "revoke_repair": {
            "revoked_state_reached": True,
            "credential_refused_after_revoke": True,
            "expired_state_reached": True,
            "repair_via_canonical_flow": True,
            "second_repair_redeem_count": 0,
        },
    }


def test_cli_full_chain_passes_and_tolerates_a_bom_prefixed_file(tmp_path) -> None:
    import json

    observation = tmp_path / "canary.json"
    # utf-8-sig writes a BOM on purpose: an operator-produced file may carry one.
    observation.write_text(json.dumps(_good_observation()), encoding="utf-8-sig")
    assert _main(
        ["--mode", "canary_contract_evaluate", "--exact-main-sha", _SHA, "--observation", str(observation)]
    ) == 0


def test_cli_fails_closed_when_the_rate_bound_is_inactive(tmp_path) -> None:
    import json

    payload = _good_observation()
    payload["rate"] = {"rate_limit": None, "rate_bound_active": False, "window_seconds": 600, "max_tracked_scopes": 4096}
    observation = tmp_path / "unbound.json"
    observation.write_text(json.dumps(payload), encoding="utf-8")
    assert _main(
        ["--mode", "canary_contract_evaluate", "--exact-main-sha", _SHA, "--observation", str(observation)]
    ) == 3


def test_cli_refusals_are_bounded_and_leave_no_traceback(tmp_path) -> None:
    malformed = tmp_path / "malformed.json"
    malformed.write_text("not json at all", encoding="utf-8")
    with pytest.raises(SystemExit) as malformed_exit:
        _main(["--mode", "repository_preflight", "--exact-main-sha", _SHA, "--observation", str(malformed)])
    assert "Traceback" not in str(malformed_exit.value.code)
    with pytest.raises(SystemExit) as mode_exit:
        _main(["--mode", "activate_everything", "--exact-main-sha", _SHA])
    assert str(mode_exit.value.code) == "gate_refused:unsupported_gate_mode"
    with pytest.raises(SystemExit) as arg_exit:
        _main(["--mode", "repository_preflight", "--exact-main-sha", _SHA, "--unknown", "x"])
    assert str(arg_exit.value.code) == "unsupported_argument"


def test_cli_preflight_reports_the_unbound_rate_without_failing(tmp_path) -> None:
    import json

    payload = _good_observation()
    del payload["rate"]
    observation = tmp_path / "norate.json"
    observation.write_text(json.dumps(payload), encoding="utf-8")
    # Preflight is a source check: it reports the posture instead of tripping.
    assert _main(
        ["--mode", "repository_preflight", "--exact-main-sha", _SHA, "--observation", str(observation)]
    ) == 0
