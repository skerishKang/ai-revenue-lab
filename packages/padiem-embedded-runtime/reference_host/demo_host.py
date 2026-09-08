"""Repository-local reference host for IP-SIDECAR (S2 demo, non-production).

Drives one deterministic journey — mount, open, context projection, notice,
close, disable — using only fixture data and an injected Engine port
(normally :class:`DeterministicFakeEnginePort`). Performs no I/O, no
network, and never touches real products.
"""

from __future__ import annotations

from typing import Mapping

from padiem_embedded_runtime.bootstrap import parse_bootstrap_config
from padiem_embedded_runtime.bridge import intake_host_payload
from padiem_embedded_runtime.engine_port import DeterministicFakeEnginePort, EnginePort
from padiem_embedded_runtime.errors import SidecarContractError
from padiem_embedded_runtime.events import project_event
from padiem_embedded_runtime.host_context import envelop_host_context
from padiem_embedded_runtime.lifecycle import EmbeddedShell


def run_demo(fixture: Mapping[str, object], port: EnginePort | None = None) -> dict[str, object]:
    """Execute the deterministic reference journey and return a JSON-safe report."""
    if not isinstance(fixture, Mapping):
        raise SidecarContractError("demo fixture must be a mapping")

    bootstrap_raw = fixture.get("bootstrap")
    context_raw = fixture.get("host_context")
    notice_text = fixture.get("notice_text", "")
    canned = fixture.get("fake_engine", {})
    if not isinstance(bootstrap_raw, Mapping) or not isinstance(context_raw, Mapping):
        raise SidecarContractError("demo fixture needs bootstrap and host_context mappings")
    if not isinstance(notice_text, str) or not isinstance(canned, Mapping):
        raise SidecarContractError("demo fixture has invalid notice_text or fake_engine")

    steps: list[dict[str, object]] = []
    active_port: EnginePort = port if port is not None else DeterministicFakeEnginePort(canned)

    config = parse_bootstrap_config(bootstrap_raw)
    steps.append({"step": "mount", "state": "closed", "host_id": config.host_id})

    shell = EmbeddedShell(config)
    steps.append({"step": "open", "state": shell.open()})
    steps.append({"step": "opened", "state": shell.opened()})

    envelope = envelop_host_context(config.host_id, context_raw)
    steps.append(
        {
            "step": "context_received",
            "event": project_event(
                "context.received",
                config.host_id,
                1,
                "Host context accepted as untrusted",
                {"field_count": str(len(envelope.fields))},
            ).to_public_dict(),
            "dropped_reserved_count": len(envelope.dropped_reserved),
        }
    )

    engine_reply = active_port.invoke_capability(
        "notice.render", {"host_id": config.host_id, "field_count": len(envelope.fields)}
    )
    steps.append(
        {
            "step": "notice_posted",
            "event": project_event(
                "notice.posted", config.host_id, 2, notice_text, {"engine_ok": str(engine_reply.get("ok", False))}
            ).to_public_dict(),
        }
    )

    steps.append({"step": "close", "state": shell.close()})
    steps.append({"step": "closed_event", "state": shell.closed_event()})

    disabled = shell.disable("demo complete")
    steps.append({"step": "disable", "state": disabled.state, "ok": disabled.ok})

    guarded = shell.guard_open_interaction()
    steps.append(
        {
            "step": "open_while_disabled",
            "refused": guarded is not None and not guarded.ok,
            "fallback": guarded.fallback if guarded else None,
        }
    )

    return {
        "host_id": config.host_id,
        "final_state": shell.state,
        "host_primary_journey": "unbroken",
        "steps": steps,
    }


def run_bridge_journey(fixture: Mapping[str, object]) -> dict[str, object]:
    """Drive the S3 host-context bridge over four deterministic paths.

    Uses only fixture data and the injected/absent Engine port (never real
    transport). Each path builds a fresh shell and returns the public-safe
    bridge outcome plus the resulting shell state, proving normal,
    incompatible-version, malformed-context, and disabled handling without
    ever breaking the host primary journey.
    """
    if not isinstance(fixture, Mapping):
        raise SidecarContractError("bridge fixture must be a mapping")
    bootstrap_raw = fixture.get("bootstrap")
    context_valid = fixture.get("context_valid")
    context_malformed = fixture.get("context_malformed")
    incompatible = fixture.get("incompatible_contract_version")
    if not isinstance(bootstrap_raw, Mapping):
        raise SidecarContractError("bridge fixture needs a bootstrap mapping")
    if not isinstance(context_valid, Mapping) or not isinstance(context_malformed, Mapping):
        raise SidecarContractError("bridge fixture needs valid and malformed context mappings")
    if not isinstance(incompatible, str):
        raise SidecarContractError("bridge fixture needs an incompatible_contract_version")

    def fresh_shell() -> EmbeddedShell:
        stripped = {k: v for k, v in bootstrap_raw.items() if k != "contract_version"}
        return EmbeddedShell(parse_bootstrap_config(stripped))

    paths: dict[str, object] = {}

    normal_shell = fresh_shell()
    normal = intake_host_payload(dict(bootstrap_raw), context_valid, normal_shell)
    paths["normal"] = {
        "status": normal.status,
        "accepted": normal.accepted,
        "shell_state": normal_shell.state,
        "dropped_reserved_count": normal.diagnostics.dropped_reserved_count,
    }

    incompatible_shell = fresh_shell()
    bad_version = dict(bootstrap_raw)
    bad_version["contract_version"] = incompatible
    incompatible_outcome = intake_host_payload(bad_version, context_valid, incompatible_shell)
    paths["incompatible"] = {
        "status": incompatible_outcome.status,
        "reason_code": incompatible_outcome.diagnostics.reason_code,
        "accepted": incompatible_outcome.accepted,
        "shell_state": incompatible_shell.state,
    }

    malformed_shell = fresh_shell()
    malformed_outcome = intake_host_payload(
        dict(bootstrap_raw), context_malformed, malformed_shell
    )
    paths["malformed"] = {
        "status": malformed_outcome.status,
        "reason_code": malformed_outcome.diagnostics.reason_code,
        "accepted": malformed_outcome.accepted,
        "shell_state": malformed_shell.state,
    }

    disabled_shell = fresh_shell()
    disabled_shell.disable("pre-disabled")
    disabled_outcome = intake_host_payload(dict(bootstrap_raw), context_valid, disabled_shell)
    paths["disabled"] = {
        "status": disabled_outcome.status,
        "shell_state": disabled_shell.state,
        "host_primary_journey": "unbroken",
    }

    return {"paths": paths, "host_primary_journey": "unbroken"}
