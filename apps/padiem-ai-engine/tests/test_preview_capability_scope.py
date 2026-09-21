"""Isolate-scoped capability posture override contract tests (#2786 Stage 11-C).

M1 scope: ``capability_manifest`` gains an optional, explicitly bounded override
that a *marked non-production* pilot isolate may install. The declared truth is
unchanged by default, an override can only raise a DEFERRED capability to
AVAILABLE, and every malformed or out-of-scope request is ignored.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.agent_preview_authority import (  # noqa: E402
    DEPLOY_ENV_NAME,
    ENABLE_ENV_NAME,
    PREVIEW_ENABLE_MARKER,
    preview_capability_overrides,
    preview_lane_enabled,
)
from app.capability_manifest import (  # noqa: E402
    CapabilityState,
    current_capability_manifest,
    current_posture_overrides,
    require_compatible_capability,
    set_posture_overrides,
)


@pytest.fixture(autouse=True)
def _clean_isolate_override():
    set_posture_overrides(None)
    yield
    set_posture_overrides(None)


def test_default_and_empty_override_are_the_declared_truth() -> None:
    declared = current_capability_manifest()
    assert declared.capability_state("agent_skill_runtime") is CapabilityState.AVAILABLE
    assert declared.capability_state("completed_execution") is CapabilityState.AVAILABLE
    assert declared.capability_state("memory_rag") is CapabilityState.DEFERRED
    assert declared.capability_state("provider_selection") is CapabilityState.UNAVAILABLE
    assert current_posture_overrides() is None

    # An empty mapping and an explicit ``None`` both mean "no override".
    assert current_capability_manifest({}).to_public_dict() == declared.to_public_dict()
    assert (
        current_capability_manifest(None).to_public_dict() == declared.to_public_dict()
    )


def test_preview_override_raises_only_the_named_capability() -> None:
    before = current_capability_manifest()
    after = current_capability_manifest(
        {"memory_rag": CapabilityState.AVAILABLE}
    )

    assert after.capability_state("memory_rag") is CapabilityState.AVAILABLE
    changed = [
        item.id
        for item in after.capabilities
        if after.capability_state(item.id) is not before.capability_state(item.id)
    ]
    assert changed == ["memory_rag"]
    assert (
        after.require_capability("memory_rag").state
        is CapabilityState.AVAILABLE
    )


def test_out_of_scope_and_malformed_overrides_are_ignored() -> None:
    declared = current_capability_manifest()
    rejected = (
        {"not_a_declared_capability": CapabilityState.AVAILABLE},
        {"memory_rag": "available"},
        {"memory_rag": None},
        {"provider_selection": CapabilityState.AVAILABLE},  # UNAVAILABLE cannot widen
        {"completed_execution": CapabilityState.DEFERRED},  # AVAILABLE cannot lower
        {"memory_rag": CapabilityState.UNAVAILABLE},  # nor can DEFERRED lower
    )
    for overrides in rejected:
        assert (
            current_capability_manifest(overrides).to_public_dict()
            == declared.to_public_dict()
        )
        assert (
            current_capability_manifest(overrides).capability_state(
                "memory_rag"
            )
            is CapabilityState.DEFERRED
        )


def test_isolate_override_applies_and_clears() -> None:
    set_posture_overrides({"memory_rag": CapabilityState.AVAILABLE})
    assert current_posture_overrides() == {
        "memory_rag": CapabilityState.AVAILABLE
    }
    assert (
        current_capability_manifest().capability_state("memory_rag")
        is CapabilityState.AVAILABLE
    )
    # An explicit argument still wins over the installed isolate default.
    assert (
        current_capability_manifest({}).capability_state("memory_rag")
        is CapabilityState.DEFERRED
    )
    # The require entrypoint sees the isolate default.
    assert (
        require_compatible_capability("memory_rag").state
        is CapabilityState.AVAILABLE
    )

    # A malformed install clears instead of leaving a partial override behind.
    set_posture_overrides("not a mapping")  # type: ignore[arg-type]
    assert current_posture_overrides() is None
    assert (
        current_capability_manifest().capability_state("memory_rag")
        is CapabilityState.DEFERRED
    )
    assert (
        current_capability_manifest().capability_state("agent_skill_runtime")
        is CapabilityState.AVAILABLE
    )
    assert (
        require_compatible_capability.__name__ == "require_compatible_capability"
    )  # import is exercised above


def test_preview_posture_requires_a_marked_non_production_isolate() -> None:
    assert preview_capability_overrides({}) is None
    assert preview_capability_overrides({ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER}) is None
    assert (
        preview_capability_overrides({DEPLOY_ENV_NAME: "preview"}) is None
    )
    for production_marker in ("production", "prod", "prd", "PRODUCTION"):
        assert (
            preview_capability_overrides(
                {
                    DEPLOY_ENV_NAME: production_marker,
                    ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER,
                }
            )
            is None
        )
    assert (
        preview_capability_overrides(
            {DEPLOY_ENV_NAME: "not a valid env!!", ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER}
        )
        is None
    )
    assert (
        preview_capability_overrides(
            {DEPLOY_ENV_NAME: "preview", ENABLE_ENV_NAME: "ENABLE_SOMETHING_ELSE"}
        )
        is None
    )

    assert preview_lane_enabled(
        {DEPLOY_ENV_NAME: "preview", ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER}
    )
    assert preview_capability_overrides(
        {DEPLOY_ENV_NAME: " Preview ", ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER}
    ) == {"agent_skill_runtime": CapabilityState.AVAILABLE}
