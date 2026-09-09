"""Repository-local reference host for IP-SIDECAR (S2-S7 demos, non-production).

Drives deterministic journeys — mount, open, context projection, notice,
close, disable, bridge intake, citation presentation, attachment input
presentation, approval presentation, and streaming lifecycle/error/retry
presentation — using only fixture data and an injected Engine port (normally
:class:`DeterministicFakeEnginePort`).
Performs no I/O, no network, and never touches real products.
"""

from __future__ import annotations

from typing import Mapping

from padiem_embedded_runtime.approval_presentation import (
    present_approval_proposals,
    present_approval_state,
    present_confirmation_intent,
    present_public_reference,
)
from padiem_embedded_runtime.attachment_input import (
    present_attachment_ref,
    present_selections,
    present_upload_lifecycle,
)
from padiem_embedded_runtime.bootstrap import parse_bootstrap_config
from padiem_embedded_runtime.bridge import intake_host_payload
from padiem_embedded_runtime.engine_port import DeterministicFakeEnginePort, EnginePort
from padiem_embedded_runtime.errors import SidecarContractError
from padiem_embedded_runtime.events import project_event
from padiem_embedded_runtime.evidence import present_citations
from padiem_embedded_runtime.host_context import envelop_host_context
from padiem_embedded_runtime.lifecycle import EmbeddedShell
from padiem_embedded_runtime.streaming_lifecycle import (
    StreamFeedGuard,
    present_public_error,
    present_retry_affordance,
    present_stream_lifecycle,
)


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


def run_citation_journey(fixture: Mapping[str, object]) -> dict[str, object]:
    """Drive the S4 evidence/citation presentation over deterministic paths.

    Uses only fixture data. Each path projects one citation list and returns
    the public-safe presentation view, proving normal (ordered/dedup/labels),
    empty, and degraded (malformed-dropped) states without ever raising to the
    host or retaining raw provider/tool/terminal material.
    """
    if not isinstance(fixture, Mapping):
        raise SidecarContractError("citation fixture must be a mapping")
    normal = fixture.get("citations_normal")
    empty = fixture.get("citations_empty")
    degraded = fixture.get("citations_degraded")
    for name, value in (("citations_normal", normal), ("citations_empty", empty), ("citations_degraded", degraded)):
        if not isinstance(value, list):
            raise SidecarContractError(f"citation fixture needs a {name} list")

    paths: dict[str, object] = {}
    for name, items in (("normal", normal), ("empty", empty), ("degraded", degraded)):
        presentation = present_citations(items)
        paths[name] = presentation.to_public_dict()
    return {"paths": paths, "host_primary_journey": "unbroken"}


def run_attachment_journey(fixture: Mapping[str, object]) -> dict[str, object]:
    """Drive the S5 attachment input presentation over deterministic paths.

    Uses only fixture data. Projects normal/empty/degraded selection lists,
    the full host-driven lifecycle flow plus one malformed lifecycle, and a
    valid vs. URL-shaped opaque ref. Nothing here reads bytes, owns DOM,
    mints refs, or touches network/storage.
    """
    if not isinstance(fixture, Mapping):
        raise SidecarContractError("attachment fixture must be a mapping")
    selections_normal = fixture.get("selections_normal")
    selections_empty = fixture.get("selections_empty")
    selections_degraded = fixture.get("selections_degraded")
    lifecycle_flow = fixture.get("lifecycle_flow")
    lifecycle_malformed = fixture.get("lifecycle_malformed")
    ref_valid = fixture.get("ref_valid")
    ref_invalid = fixture.get("ref_invalid")
    for name, value in (
        ("selections_normal", selections_normal),
        ("selections_empty", selections_empty),
        ("selections_degraded", selections_degraded),
        ("lifecycle_flow", lifecycle_flow),
    ):
        if not isinstance(value, list):
            raise SidecarContractError(f"attachment fixture needs a {name} list")
    if not isinstance(lifecycle_malformed, Mapping):
        raise SidecarContractError("attachment fixture needs a lifecycle_malformed mapping")
    if not isinstance(ref_valid, str) or not isinstance(ref_invalid, str):
        raise SidecarContractError("attachment fixture needs ref_valid and ref_invalid strings")

    paths: dict[str, object] = {}
    for name, items in (
        ("selections_normal", selections_normal),
        ("selections_empty", selections_empty),
        ("selections_degraded", selections_degraded),
    ):
        paths[name] = present_selections(items).to_public_dict()

    paths["lifecycle_flow"] = [
        present_upload_lifecycle(step).to_public_dict()
        for step in lifecycle_flow
        if isinstance(step, Mapping)
    ]
    paths["lifecycle_malformed"] = present_upload_lifecycle(lifecycle_malformed).to_public_dict()
    paths["ref_valid"] = present_attachment_ref(ref_valid).to_public_dict()
    paths["ref_invalid"] = present_attachment_ref(ref_invalid).to_public_dict()
    return {"paths": paths, "host_primary_journey": "unbroken"}


def run_approval_journey(fixture: Mapping[str, object]) -> dict[str, object]:
    """Drive the S6 approval presentation over deterministic paths.

    Uses only fixture data. Projects normal/empty/degraded proposal lists,
    the staged confirmation-intent flow plus one invalid intent, the
    host-driven approval state flow plus one malformed state, and a valid vs
    URL-shaped upstream reference. Nothing here verifies decisions, mints
    authority, executes actions, or touches network/storage.
    """
    if not isinstance(fixture, Mapping):
        raise SidecarContractError("approval fixture must be a mapping")
    proposals_normal = fixture.get("proposals_normal")
    proposals_empty = fixture.get("proposals_empty")
    proposals_degraded = fixture.get("proposals_degraded")
    intent_flow = fixture.get("intent_flow")
    intent_malformed = fixture.get("intent_malformed")
    state_flow = fixture.get("state_flow")
    state_malformed = fixture.get("state_malformed")
    reference_valid = fixture.get("reference_valid")
    reference_invalid = fixture.get("reference_invalid")
    for name, value in (
        ("proposals_normal", proposals_normal),
        ("proposals_empty", proposals_empty),
        ("proposals_degraded", proposals_degraded),
        ("intent_flow", intent_flow),
        ("state_flow", state_flow),
    ):
        if not isinstance(value, list):
            raise SidecarContractError(f"approval fixture needs a {name} list")
    for name, value in (("intent_malformed", intent_malformed), ("state_malformed", state_malformed)):
        if not isinstance(value, Mapping):
            raise SidecarContractError(f"approval fixture needs a {name} mapping")
    if not isinstance(reference_valid, str) or not isinstance(reference_invalid, str):
        raise SidecarContractError("approval fixture needs reference strings")

    paths: dict[str, object] = {}
    for name, items in (
        ("proposals_normal", proposals_normal),
        ("proposals_empty", proposals_empty),
        ("proposals_degraded", proposals_degraded),
    ):
        paths[name] = present_approval_proposals(items).to_public_dict()

    paths["intent_flow"] = [
        present_confirmation_intent(step).to_public_dict()
        for step in intent_flow
        if isinstance(step, Mapping)
    ]
    paths["intent_malformed"] = present_confirmation_intent(intent_malformed).to_public_dict()

    paths["state_flow"] = [
        present_approval_state(step).to_public_dict()
        for step in state_flow
        if isinstance(step, Mapping)
    ]
    paths["state_malformed"] = present_approval_state(state_malformed).to_public_dict()

    paths["reference_valid"] = present_public_reference(reference_valid).to_public_dict()
    paths["reference_invalid"] = present_public_reference(reference_invalid).to_public_dict()
    return {"paths": paths, "host_primary_journey": "unbroken"}


def run_streaming_journey(fixture: Mapping[str, object]) -> dict[str, object]:
    """Drive the S7 streaming lifecycle/error/retry presentation over fixtures.

    Projects a canonical public-event flow through a display-only feed guard
    (fresh/duplicate/conflict ordering), a malformed event, allowlisted and
    rejected public-safe error views, and the retry-affordance permission
    matrix. Nothing here executes retries or cancellation, transports, owns a
    clock, or decides execution truth.
    """
    if not isinstance(fixture, Mapping):
        raise SidecarContractError("streaming fixture must be a mapping")
    lifecycle_flow = fixture.get("lifecycle_flow")
    lifecycle_malformed = fixture.get("lifecycle_malformed")
    error_flow = fixture.get("error_flow")
    affordance_flow = fixture.get("affordance_flow")
    if not isinstance(lifecycle_flow, list):
        raise SidecarContractError("streaming fixture needs a lifecycle_flow list")
    if not isinstance(error_flow, list) or not isinstance(affordance_flow, list):
        raise SidecarContractError("streaming fixture needs error/affordance lists")
    if not isinstance(lifecycle_malformed, Mapping):
        raise SidecarContractError("streaming fixture needs a lifecycle_malformed mapping")

    paths: dict[str, object] = {}

    guard = StreamFeedGuard()
    feed: list[dict[str, object]] = []
    for event in lifecycle_flow:
        if not isinstance(event, Mapping):
            continue
        presentation = present_stream_lifecycle(event)
        projected, ordering = guard.observe(presentation)
        feed.append({"ordering": ordering, **projected.to_public_dict()})
    paths["lifecycle_flow"] = feed

    paths["lifecycle_malformed"] = present_stream_lifecycle(lifecycle_malformed).to_public_dict()

    paths["error_flow"] = [
        present_public_error(item).to_public_dict()
        for item in error_flow
        if isinstance(item, Mapping)
    ]
    paths["affordance_flow"] = [
        present_retry_affordance(item).to_public_dict()
        for item in affordance_flow
        if isinstance(item, Mapping)
    ]
    return {"paths": paths, "host_primary_journey": "unbroken"}
