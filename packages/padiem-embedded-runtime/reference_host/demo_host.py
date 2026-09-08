"""Repository-local reference host for IP-SIDECAR (S2 demo, non-production).

Drives one deterministic journey — mount, open, context projection, notice,
close, disable — using only fixture data and an injected Engine port
(normally :class:`DeterministicFakeEnginePort`). Performs no I/O, no
network, and never touches real products.
"""

from __future__ import annotations

from typing import Mapping

from padiem_embedded_runtime.bootstrap import parse_bootstrap_config
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
