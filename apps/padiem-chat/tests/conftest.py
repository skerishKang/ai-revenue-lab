from __future__ import annotations

from pathlib import Path

import pytest

import app.model_policy as model_policy_module


_HOLD_POLICY_MODULES = {
    "test_attachments.py",
    "test_auth_history.py",
    "test_model_policy.py",
    "test_plus_space_bunny_image.py",
    "test_saved_outputs.py",
    "test_tier_route_consumer_coverage.py",
    "test_unassigned_profile_gate.py",
}


@pytest.fixture(autouse=True)
def _synthetic_plus_route_for_non_policy_contracts(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep unrelated Chat regressions independent from successor-model selection.

    Production source remains fail-closed with no executable Plus route. Tests whose
    purpose is to verify that HOLD state are excluded above. Every other Chat test
    gets one synthetic executable Plus model so it can continue testing its own
    contract (history, grounding, Claw transport, quota, errors, UI, etc.).
    """

    module_name = Path(str(request.fspath)).name
    if module_name in _HOLD_POLICY_MODULES:
        return

    executable = frozenset({model_policy_module.DEFAULT_B14_MODEL_ID})
    monkeypatch.setattr(
        model_policy_module,
        "EXECUTABLE_B14_MODEL_IDS",
        executable,
    )

    module = request.module
    if hasattr(module, "EXECUTABLE_B14_MODEL_IDS"):
        monkeypatch.setattr(
            module,
            "EXECUTABLE_B14_MODEL_IDS",
            executable,
            raising=False,
        )
