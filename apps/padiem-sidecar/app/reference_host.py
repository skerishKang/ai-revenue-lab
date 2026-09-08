"""B53 repository-local reference host for the Sidecar conformance journey.

Deterministic, network-free, fixture-driven. Uses only IP-SIDECAR
primitives and fake/stub Engine/Control Plane ports. Proves the
product-adapter boundary at the B53 product surface.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from padiem_embedded_runtime.errors import SidecarContractError

from .product_adapter import ProductAdapter, SidecarProductConfig


def load_fixture() -> dict:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "local_conformance.json"
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def run_conformance_journey(fixture: Mapping[str, object]) -> dict[str, object]:
    """Drive the B53 conformance journey over fixture data.

    Proves the product-adapter boundary: host context, stream lifecycle,
    evidence/citation, attachment ref, approval/action intent, diagnostics,
    and fail-safe disable — all via IP-SIDECAR primitives and fake/stub
    Engine/Control Plane ports only.
    """
    if not isinstance(fixture, Mapping):
        raise SidecarContractError("conformance fixture must be a mapping")

    config = SidecarProductConfig(
        product_id="padiem-sidecar",
        product_name="Padiem Sidecar",
        install_mode="embed",
        theme="dark",
        brand="B53",
        locale="ko",
    )
    adapter = ProductAdapter(config)
    paths: dict[str, object] = {}

    # --- host context + bootstrap + diagnostics ---
    bootstrap_raw = fixture.get("bootstrap")
    context_valid = fixture.get("context_valid")
    context_malformed = fixture.get("context_malformed")
    if not isinstance(bootstrap_raw, Mapping):
        raise SidecarContractError("conformance fixture needs bootstrap mapping")
    if not isinstance(context_valid, Mapping):
        raise SidecarContractError("conformance fixture needs context_valid mapping")
    if not isinstance(context_malformed, Mapping):
        raise SidecarContractError("conformance fixture needs context_malformed mapping")

    outcome = adapter.intake(bootstrap_raw, context_valid)
    paths["intake_valid"] = outcome.to_public_dict()
    paths["shell_state_after_valid"] = adapter.shell.state

    malformed_outcome = adapter.intake(bootstrap_raw, context_malformed)
    paths["intake_malformed"] = malformed_outcome.to_public_dict()
    paths["shell_state_after_malformed"] = adapter.shell.state

    paths["diagnostics"] = adapter.diagnostics.to_public_dict() if adapter.diagnostics else {}

    # --- stream lifecycle + public-safe error ---
    stream_flow = fixture.get("streaming_flow")
    stream_malformed = fixture.get("streaming_malformed")
    error_flow = fixture.get("error_flow")
    affordance_flow = fixture.get("affordance_flow")
    if not isinstance(stream_flow, list):
        raise SidecarContractError("conformance fixture needs streaming_flow list")
    if not isinstance(error_flow, list) or not isinstance(affordance_flow, list):
        raise SidecarContractError("conformance fixture needs error/affordance lists")
    if not isinstance(stream_malformed, Mapping):
        raise SidecarContractError("conformance fixture needs streaming_malformed mapping")

    paths["stream_feed"] = adapter.stream_feed(stream_flow)
    paths["stream_malformed"] = adapter.stream_event(stream_malformed).to_public_dict()
    paths["error_flow"] = [
        adapter.public_error(item).to_public_dict()
        for item in error_flow
        if isinstance(item, Mapping)
    ]
    paths["affordance_flow"] = [
        adapter.retry_affordance(item).to_public_dict()
        for item in affordance_flow
        if isinstance(item, Mapping)
    ]

    # --- evidence/citation ---
    citations_normal = fixture.get("citations_normal")
    citations_degraded = fixture.get("citations_degraded")
    if not isinstance(citations_normal, list):
        raise SidecarContractError("conformance fixture needs citations_normal list")
    if not isinstance(citations_degraded, list):
        raise SidecarContractError("conformance fixture needs citations_degraded list")
    paths["citations_normal"] = adapter.citations(citations_normal).to_public_dict()
    paths["citations_degraded"] = adapter.citations(citations_degraded).to_public_dict()

    # --- attachment selection/ref ---
    selections_normal = fixture.get("selections_normal")
    selections_degraded = fixture.get("selections_degraded")
    ref_valid = fixture.get("attachment_ref_valid")
    ref_invalid = fixture.get("attachment_ref_invalid")
    if not isinstance(selections_normal, list):
        raise SidecarContractError("conformance fixture needs selections_normal list")
    if not isinstance(selections_degraded, list):
        raise SidecarContractError("conformance fixture needs selections_degraded list")
    if not isinstance(ref_valid, str) or not isinstance(ref_invalid, str):
        raise SidecarContractError("conformance fixture needs attachment_ref strings")
    paths["selections_normal"] = adapter.selections(selections_normal).to_public_dict()
    paths["selections_degraded"] = adapter.selections(selections_degraded).to_public_dict()
    paths["attachment_ref_valid"] = adapter.attachment_ref(ref_valid).to_public_dict()
    paths["attachment_ref_invalid"] = adapter.attachment_ref(ref_invalid).to_public_dict()

    # --- approval/action intent ---
    proposals_normal = fixture.get("approval_proposals_normal")
    intent_flow = fixture.get("approval_intent_flow")
    state_flow = fixture.get("approval_state_flow")
    state_malformed = fixture.get("approval_state_malformed")
    if not isinstance(proposals_normal, list):
        raise SidecarContractError("conformance fixture needs approval_proposals_normal list")
    if not isinstance(intent_flow, list):
        raise SidecarContractError("conformance fixture needs approval_intent_flow list")
    if not isinstance(state_flow, list):
        raise SidecarContractError("conformance fixture needs approval_state_flow list")
    if not isinstance(state_malformed, Mapping):
        raise SidecarContractError("conformance fixture needs approval_state_malformed mapping")
    paths["approval_proposals_normal"] = adapter.approval_proposals(proposals_normal).to_public_dict()
    paths["approval_intent_flow"] = [
        adapter.confirmation_intent(step).to_public_dict()
        for step in intent_flow
        if isinstance(step, Mapping)
    ]
    paths["approval_state_flow"] = [
        adapter.approval_state(step).to_public_dict()
        for step in state_flow
        if isinstance(step, Mapping)
    ]
    paths["approval_state_malformed"] = adapter.approval_state(state_malformed).to_public_dict()

    # --- fail-safe disable ---
    disable_result = adapter.disable("conformance complete")
    paths["disable"] = disable_result.to_public_dict()
    paths["shell_state_after_disable"] = adapter.shell.state

    return {"paths": paths, "host_primary_journey": "unbroken"}


if __name__ == "__main__":
    journey = run_conformance_journey(load_fixture())
    print(json.dumps(journey, ensure_ascii=False, indent=2))
