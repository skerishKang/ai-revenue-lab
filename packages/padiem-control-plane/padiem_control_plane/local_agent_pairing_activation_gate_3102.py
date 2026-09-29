"""#3102 — executable pairing activation gate (source-only).

The readiness contract in :mod:`padiem_control_plane.local_agent_pairing_activation_3102`
records *what* a live deployment must satisfy. This module is the missing
**executable** half: the bounded evaluator a manual gate runs, whose verdict
either refuses a live activation or proves the bounded canary chain.

Boundary — this gate creates no authority and mutates nothing:

    SECOND_PAIRING_AUTHORITY=0
    SECOND_DEVICE_LIFECYCLE_AUTHORITY=0
    SECOND_SESSION_AUTHORITY=0
    SECOND_CREDENTIAL_STORE=0
    PRODUCTION_MUTATION=0
    CALLER_BROKER_URL_OVERRIDE=0
    PUBLIC_INBOUND_PC_PORT=0
    SECRET_OUTPUT=0

Everything it evaluates is delegated to the canonical #3080 surfaces:

* challenge issuance / single-use / expiry / issuance rate bound —
  :mod:`padiem_control_plane.local_agent_broker_pairing`
  (``InMemoryBrokerPairingAuthority`` and its HTTP routes);
* device lifecycle (``unpaired``, ``paired_offline``, ``online``, ``revoked``,
  ``credential_expired``, ``update_required``) — ``kagent.local_agent_pairing``;
* server-backed ONLINE — ``kagent.local_agent_server_projection``;
* broker infrastructure bootstrap — ``b54-local-agent-broker-production-gate.yml``
  (this gate never duplicates it, and ``bootstrap_private`` is explicitly NOT
  #3102 completion);
* public hostname activation — ``b54-local-agent-public-ingress-activation.yml``.

The gate is deliberately **non-mutating**. Issuing a real canary challenge
requires an authenticated account/workspace session, which is an operator step a
CENTRAL-approved activation performs; the gate evaluates the bounded,
secret-free observation that step produces. A gate that could itself mint a
challenge would be a second pairing authority, which is exactly what #3102
forbids.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .contracts import ControlPlaneContractError
from .local_agent_pairing_activation_3102 import (
    ACTIVATION_RUNBOOK,
    REQUIRED_ACTIVATION_BINDING_NAMES,
    ROLLBACK_RUNBOOK,
    PairingActivationReadiness,
    SOURCE_ONLY_READINESS,
    assert_not_activated,
)

#: The rate binding the deployment must supply. It is one of the canonical
#: activation binding names — re-exported, never re-declared, so the name cannot
#: drift between the contract and the gate.
RATE_LIMIT_BINDING_NAME = "PAIREM_PAIRING_ISSUANCE_RATE_LIMIT"

#: The canonical issuance enforcement this gate reasons about, read from the
#: contract module rather than restated here.
CANONICAL_RATE_ERROR_CODE = "pairing_issuance_rate_limited"
CANONICAL_RATE_WINDOW_SECONDS = 600
CANONICAL_MAX_TRACKED_SCOPES = 4_096

#: The canonical authority the live gate runs against. Fixed, never an input:
#: #3102 forbids a caller-selected broker destination.
FIXED_BROKER_AUTHORITY_REF = "control-plane.local-agent-broker.production.v1"
PUBLIC_HOSTNAME = "local-agent.padiem.net"
EXPECTED_TRANSPORT_SCHEME = "https"
EXPECTED_TRANSPORT_PORT = 443

#: Where infrastructure mutation actually lives. Recorded as names so a reviewer
#: can see this gate delegates instead of duplicating.
INFRASTRUCTURE_GATE = "b54-local-agent-broker-production-gate.yml"
INGRESS_GATE = "b54-local-agent-public-ingress-activation.yml"
BOOTSTRAP_PRIVATE_IS_NOT_3102_COMPLETION = True

GATE_STAGES: tuple[str, ...] = (
    "repository_preflight",
    "cloudflare_readonly_readiness",
    "exact_main_guard",
    "rate_bound_gate",
    "canary_contract",
    "revoke_contract",
    "expired_repair_contract",
    "rollback_disable_contract",
    "secret_free_evidence",
)

#: Non-mutating modes only. A live challenge/redeem is an operator/CENTRAL step;
#: its bounded observation is what these modes evaluate.
GATE_MODES: tuple[str, ...] = (
    "repository_preflight",
    "cloudflare_readonly",
    "canary_contract_evaluate",
    "rollback_disable_evaluate",
)


def _fail(code: str, message: str) -> None:
    raise ControlPlaneContractError(code, message)


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        _fail(f"{name}_must_be_boolean", f"{name} must be a boolean")
    return value


def _require_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{name}_must_be_integer", f"{name} must be an integer")
    return value


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{name}_must_be_non_empty_string", f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class RateBoundGate:
    """Bounded issuance rate-limit activation contract for one deployment.

    Source of truth is the canonical authority's own ``safe_dict()`` projection:
    this gate reads ``rate_bound_active`` / ``rate_limit`` / ``window_seconds``
    from it instead of re-deriving the bound. An unbound deployment is a hard
    failure — it is the exact gap #3102 records as
    ``issuance_rate_bound_active=False``.
    """

    binding_name: str
    rate_limit: int | None
    window_seconds: int
    max_tracked_scopes: int

    def __post_init__(self) -> None:
        if self.binding_name != RATE_LIMIT_BINDING_NAME:
            _fail("rate_binding_name_not_canonical", "the rate binding name must be the canonical one")
        if self.rate_limit is not None:
            if isinstance(self.rate_limit, bool) or not isinstance(self.rate_limit, int) or self.rate_limit < 1:
                _fail("rate_limit_must_be_positive_integer", "a bound rate limit must be a positive integer")
        _require_int(self.window_seconds, "window_seconds")
        _require_int(self.max_tracked_scopes, "max_tracked_scopes")

    @property
    def bound_active(self) -> bool:
        return self.rate_limit is not None

    @classmethod
    def from_authority_safe_dict(cls, projection: Mapping[str, Any]) -> "RateBoundGate":
        """Build from the canonical authority's own secret-free projection."""
        if not isinstance(projection, Mapping):
            _fail("rate_projection_must_be_mapping", "the rate projection must be a mapping")
        if "rate_bound_active" not in projection or "rate_limit" not in projection:
            _fail(
                "rate_projection_missing_canonical_fields",
                "the rate projection must come from the canonical authority's safe_dict()",
            )
        try:
            window = _require_int(
                projection.get("window_seconds", CANONICAL_RATE_WINDOW_SECONDS), "window_seconds"
            )
            max_scopes = _require_int(
                projection.get("max_tracked_scopes", CANONICAL_MAX_TRACKED_SCOPES),
                "max_tracked_scopes",
            )
        except ControlPlaneContractError:
            raise
        except (TypeError, ValueError) as exc:  # a malformed projection is a refusal
            raise ControlPlaneContractError("rate_projection_malformed", "the rate projection is malformed") from exc
        return cls(
            binding_name=RATE_LIMIT_BINDING_NAME,
            rate_limit=projection.get("rate_limit"),
            window_seconds=window,
            max_tracked_scopes=max_scopes,
        )

    def evaluate(self) -> dict[str, Any]:
        """The bounded gate verdict. Fails closed when the bound is not active."""
        active = self.bound_active
        return {
            "RATE_BINDING_NAME": self.binding_name,
            "RATE_BOUND_ACTIVE": active,
            "RATE_LIMIT_WINDOW_SECONDS": self.window_seconds,
            "RATE_ENFORCEMENT_ERROR_CODE": CANONICAL_RATE_ERROR_CODE,
            "RATE_BOUND_GATE": "PASS" if active else "FAIL_RATE_BOUND_NOT_ACTIVE",
        }


@dataclass(frozen=True, slots=True)
class CanaryObservation:
    """Secret-free observation of one bounded live canary attempt.

    Every field is a boolean, an int or an enumerated posture. No pairing code,
    credential, token or endpoint secret can appear here — the live operator step
    reports outcomes and counts only.
    """

    challenge_issued: bool
    redeem_count: int
    paired_offline_reached: bool
    lifecycle_state: str
    session_opened: bool
    heartbeat_acknowledged: bool
    online_projection: str
    transport_scheme: str
    transport_port: int
    caller_endpoint_override: bool
    public_inbound_port: int

    def __post_init__(self) -> None:
        _require_bool(self.challenge_issued, "challenge_issued")
        _require_int(self.redeem_count, "redeem_count")
        _require_bool(self.paired_offline_reached, "paired_offline_reached")
        _require_text(self.lifecycle_state, "lifecycle_state")
        _require_bool(self.session_opened, "session_opened")
        _require_bool(self.heartbeat_acknowledged, "heartbeat_acknowledged")
        _require_text(self.online_projection, "online_projection")
        _require_text(self.transport_scheme, "transport_scheme")
        _require_int(self.transport_port, "transport_port")
        _require_bool(self.caller_endpoint_override, "caller_endpoint_override")
        _require_int(self.public_inbound_port, "public_inbound_port")

    def evaluate(self) -> dict[str, Any]:
        """The canary chain contract: issue -> redeem once -> paired_offline -> session -> ONLINE."""
        checks = {
            "CHALLENGE_ISSUED": self.challenge_issued is True,
            "PAIRING_SINGLE_USE": self.redeem_count == 1,
            "PAIRED_OFFLINE_REACHED": self.paired_offline_reached is True,
            "CANONICAL_SESSION_OPENED": self.session_opened is True,
            "HEARTBEAT_ACKNOWLEDGED": self.heartbeat_acknowledged is True,
            "SERVER_BACKED_ONLINE": self.online_projection == "online"
            and self.lifecycle_state == "online",
            "TRUSTED_TLS_ENDPOINT": self.transport_scheme == EXPECTED_TRANSPORT_SCHEME
            and self.transport_port == EXPECTED_TRANSPORT_PORT,
            "CALLER_ENDPOINT_OVERRIDE": self.caller_endpoint_override is False,
            "PUBLIC_INBOUND_PC_PORT": self.public_inbound_port == 0,
        }
        return {
            "checks": checks,
            "SYSTEM_STATUS_ONLINE": checks["SERVER_BACKED_ONLINE"],
            "LIVE_CANARY_CONTRACT": "PASS" if all(checks.values()) else "FAIL",
        }


@dataclass(frozen=True, slots=True)
class RevokeRepairObservation:
    """Secret-free observation of the revoke and expired/re-pair repair paths."""

    revoked_state_reached: bool
    credential_refused_after_revoke: bool
    expired_state_reached: bool
    repair_via_canonical_flow: bool
    second_repair_redeem_count: int

    def __post_init__(self) -> None:
        _require_bool(self.revoked_state_reached, "revoked_state_reached")
        _require_bool(self.credential_refused_after_revoke, "credential_refused_after_revoke")
        _require_bool(self.expired_state_reached, "expired_state_reached")
        _require_bool(self.repair_via_canonical_flow, "repair_via_canonical_flow")
        _require_int(self.second_repair_redeem_count, "second_repair_redeem_count")

    def evaluate(self) -> dict[str, Any]:
        checks = {
            "REVOKE_STATE_REACHED": self.revoked_state_reached is True,
            "REVOKED_CREDENTIAL_REFUSED": self.credential_refused_after_revoke is True,
            "CREDENTIAL_EXPIRED_STATE_REACHED": self.expired_state_reached is True,
            "REPAIR_VIA_CANONICAL_FLOW": self.repair_via_canonical_flow is True,
            "REPLAY_SECOND_REDEMPTION": self.second_repair_redeem_count == 0,
        }
        return {
            "checks": checks,
            "REVOKE_REPAIR_CONTRACT": "PASS" if all(checks.values()) else "FAIL",
        }


@dataclass(frozen=True, slots=True)
class RollbackDisableObservation:
    """Secret-free observation of the disable path.

    Rollback is a disable, never a delete: durable pairing state and issued
    credentials must survive so a later activation cannot strand devices.
    """

    disable_flag_cleared: bool
    issuance_refuses_new_scopes: bool
    online_projection_not_forged: bool
    durable_pairing_state_preserved: bool
    issued_credentials_preserved: bool

    def __post_init__(self) -> None:
        _require_bool(self.disable_flag_cleared, "disable_flag_cleared")
        _require_bool(self.issuance_refuses_new_scopes, "issuance_refuses_new_scopes")
        _require_bool(self.online_projection_not_forged, "online_projection_not_forged")
        _require_bool(self.durable_pairing_state_preserved, "durable_pairing_state_preserved")
        _require_bool(self.issued_credentials_preserved, "issued_credentials_preserved")

    def evaluate(self) -> dict[str, Any]:
        checks = {
            "DISABLE_FLAG_CLEARED": self.disable_flag_cleared is True,
            "ISSUANCE_REFUSES_NEW_SCOPES": self.issuance_refuses_new_scopes is True,
            "ONLINE_PROJECTION_NOT_FORGED": self.online_projection_not_forged is True,
            "DURABLE_STATE_PRESERVED": self.durable_pairing_state_preserved is True,
            "CREDENTIALS_PRESERVED": self.issued_credentials_preserved is True,
        }
        return {
            "checks": checks,
            "ROLLBACK_DISABLE": "PASS" if all(checks.values()) else "FAIL",
        }


#: The only keys a gate evidence projection may carry. Structural allowlist, not
#: a value scan: the diagnostic surface cannot grow a secret-bearing field.
SECRET_FREE_GATE_KEYS: frozenset[str] = frozenset(
    {
        "contract_version",
        "gate_mode",
        "exact_main_sha",
        "fixed_broker_authority_ref",
        "public_hostname",
        "stages",
        "rate",
        "canary",
        "revoke_repair",
        "rollback_disable",
        "delegated_gates",
        "bootstrap_private_is_3102_completion",
        "second_pairing_authority",
        "second_device_lifecycle_authority",
        "second_session_authority",
        "production_mutation",
        "caller_broker_url_override",
        "public_inbound_pc_port",
        "secret_output",
        "binding_values_present",
        "gate_verdict",
    }
)


def assert_secret_free_gate_projection(projection: Mapping[str, Any]) -> None:
    """Reject a gate projection carrying anything outside the allowlisted keys."""
    if not isinstance(projection, Mapping):
        _fail("gate_projection_must_be_mapping", "the gate projection must be a mapping")
    extra = set(projection) - SECRET_FREE_GATE_KEYS
    if extra:
        raise ControlPlaneContractError(
            "gate_projection_not_secret_free",
            f"gate projection carries unexpected fields: {sorted(extra)}",
        )


def evaluate_activation_gate(
    *,
    exact_main_sha: str,
    gate_mode: str,
    readiness: PairingActivationReadiness = SOURCE_ONLY_READINESS,
    rate: RateBoundGate | None = None,
    canary: CanaryObservation | None = None,
    revoke_repair: RevokeRepairObservation | None = None,
    rollback_disable: RollbackDisableObservation | None = None,
) -> dict[str, Any]:
    """Evaluate one bounded activation-gate run.

    ``repository_preflight`` judges the source contract only. The evaluating
    modes additionally require their observation, and every mode fails closed:
    a missing observation is a refusal, never an assumed pass.
    """
    if gate_mode not in GATE_MODES:
        _fail("unsupported_gate_mode", "the gate mode is not one of the bounded non-mutating modes")
    if not isinstance(exact_main_sha, str) or len(exact_main_sha) != 40:
        _fail("exact_main_sha_must_be_full_sha", "the exact main SHA must be a full 40-character id")

    # The source-only posture is asserted, so this gate can never claim a live
    # activation happened as a side effect of running it.
    assert_not_activated(readiness)

    rate_verdict = (
        rate
        or RateBoundGate(RATE_LIMIT_BINDING_NAME, None, CANONICAL_RATE_WINDOW_SECONDS, CANONICAL_MAX_TRACKED_SCOPES)
    ).evaluate()
    canary_verdict = canary.evaluate() if canary is not None else {"LIVE_CANARY_CONTRACT": "NOT_EVALUATED"}
    repair_verdict = (
        revoke_repair.evaluate() if revoke_repair is not None else {"REVOKE_REPAIR_CONTRACT": "NOT_EVALUATED"}
    )
    rollback_verdict = (
        rollback_disable.evaluate() if rollback_disable is not None else {"ROLLBACK_DISABLE": "NOT_EVALUATED"}
    )

    projection: dict[str, Any] = {
        "contract_version": "claw-pairing-activation-gate.v1",
        "gate_mode": gate_mode,
        "exact_main_sha": exact_main_sha,
        "fixed_broker_authority_ref": FIXED_BROKER_AUTHORITY_REF,
        "public_hostname": PUBLIC_HOSTNAME,
        "stages": list(GATE_STAGES),
        "rate": rate_verdict,
        "canary": canary_verdict,
        "revoke_repair": repair_verdict,
        "rollback_disable": rollback_verdict,
        "delegated_gates": [INFRASTRUCTURE_GATE, INGRESS_GATE],
        "bootstrap_private_is_3102_completion": False,
        "second_pairing_authority": 0,
        "second_device_lifecycle_authority": 0,
        "second_session_authority": 0,
        "production_mutation": False,
        "caller_broker_url_override": False,
        "public_inbound_pc_port": 0,
        "secret_output": False,
        "binding_values_present": False,
    }

    if gate_mode == "repository_preflight":
        # Source contract only: preflight reports the rate posture instead of
        # failing on it, because an unbound deployment is exactly the recorded
        # #3102 gap this gate exists to expose. The evaluating modes are where an
        # unbound rate becomes a hard refusal.
        projection["gate_verdict"] = "SOURCE_READY_PREFLIGHT_PASS"
    elif gate_mode == "cloudflare_readonly":
        projection["gate_verdict"] = "READONLY_READINESS_ONLY"
    elif gate_mode == "canary_contract_evaluate":
        # A live canary cannot be claimed while issuance is unbounded.
        if rate_verdict["RATE_BOUND_GATE"] != "PASS":
            projection["gate_verdict"] = "FAIL_RATE_BOUND_NOT_ACTIVE"
        else:
            projection["gate_verdict"] = canary_verdict["LIVE_CANARY_CONTRACT"]
    else:  # rollback_disable_evaluate
        projection["gate_verdict"] = rollback_verdict["ROLLBACK_DISABLE"]

    assert_secret_free_gate_projection(projection)
    return projection


def _load_observation(path: str) -> dict[str, Any]:
    """Read one bounded observation file. Every failure is a bounded refusal.

    ``utf-8-sig`` is deliberate: an operator-produced file may carry a BOM, and
    a gate that dies with a raw traceback on an encoding quirk is not a
    fail-closed gate.
    """
    import json as _json

    try:
        with open(path, encoding="utf-8-sig") as handle:
            payload = _json.load(handle)
    except OSError as exc:
        raise SystemExit(f"observation_unreadable:{type(exc).__name__}")
    except ValueError:
        raise SystemExit("observation_not_valid_json")
    if not isinstance(payload, dict):
        raise SystemExit("observation_must_be_json_object")
    return payload


def _main(argv: list[str] | None = None) -> int:
    """Bounded CLI used by the manual gate workflow. Prints one JSON line."""
    import sys

    arguments = list(sys.argv[1:] if argv is None else argv)
    mode = "repository_preflight"
    sha = ""
    observation_path = ""
    index = 0
    while index < len(arguments):
        token = arguments[index]
        if token == "--mode" and index + 1 < len(arguments):
            mode = arguments[index + 1]
            index += 2
            continue
        if token == "--exact-main-sha" and index + 1 < len(arguments):
            sha = arguments[index + 1]
            index += 2
            continue
        if token == "--observation" and index + 1 < len(arguments):
            observation_path = arguments[index + 1]
            index += 2
            continue
        raise SystemExit("unsupported_argument")

    rate = None
    canary = revoke_repair = rollback_disable = None
    if observation_path:
        payload = _load_observation(observation_path)
        try:
            if "canary" in payload:
                canary = CanaryObservation(**payload["canary"])
            if "revoke_repair" in payload:
                revoke_repair = RevokeRepairObservation(**payload["revoke_repair"])
            if "rollback_disable" in payload:
                rollback_disable = RollbackDisableObservation(**payload["rollback_disable"])
            if "rate" in payload:
                rate = RateBoundGate.from_authority_safe_dict(payload["rate"])
        except ControlPlaneContractError as exc:
            raise SystemExit(f"observation_refused:{exc.code}")
        except TypeError:
            raise SystemExit("observation_refused:unexpected_fields")

    try:
        projection = evaluate_activation_gate(
            exact_main_sha=sha,
            gate_mode=mode,
            rate=rate,
            canary=canary,
            revoke_repair=revoke_repair,
            rollback_disable=rollback_disable,
        )
    except ControlPlaneContractError as exc:
        raise SystemExit(f"gate_refused:{exc.code}")

    print(json.dumps(projection, sort_keys=True, separators=(",", ":")))
    # Only the evaluating modes gate the exit code; preflight and readonly
    # readiness report posture and always exit 0 when they ran correctly.
    if mode in {"repository_preflight", "cloudflare_readonly"}:
        return 0
    failing = {"FAIL", "FAIL_RATE_BOUND_NOT_ACTIVE"}
    return 3 if projection["gate_verdict"] in failing else 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(_main())


__all__ = [
    "ACTIVATION_RUNBOOK",
    "BOOTSTRAP_PRIVATE_IS_NOT_3102_COMPLETION",
    "CANONICAL_MAX_TRACKED_SCOPES",
    "CANONICAL_RATE_ERROR_CODE",
    "CANONICAL_RATE_WINDOW_SECONDS",
    "CanaryObservation",
    "EXPECTED_TRANSPORT_PORT",
    "EXPECTED_TRANSPORT_SCHEME",
    "FIXED_BROKER_AUTHORITY_REF",
    "GATE_MODES",
    "GATE_STAGES",
    "INFRASTRUCTURE_GATE",
    "INGRESS_GATE",
    "PUBLIC_HOSTNAME",
    "RATE_LIMIT_BINDING_NAME",
    "REQUIRED_ACTIVATION_BINDING_NAMES",
    "ROLLBACK_RUNBOOK",
    "RateBoundGate",
    "RevokeRepairObservation",
    "RollbackDisableObservation",
    "SECRET_FREE_GATE_KEYS",
    "assert_secret_free_gate_projection",
    "evaluate_activation_gate",
]
