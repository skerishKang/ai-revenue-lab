"""#2800: the shared tier declaration must not be able to change without running Chat.

`app/model_policy.py` resolves every Plus/Pro/Max request through
`padiem_control_plane.product_tier_routes.active_route_for()`, so editing the declaration
alone changes which provider Chat sends users to. `B62 Padiem Chat CI` used to list only
`apps/padiem-chat/**`, `apps/korean-ai-platform/**` and `packages/padiem-ai-core/**`, so that
edit ran no Chat test at all.

The workflow lists its own file under `pull_request.paths`, which makes this test
self-guarding: deleting the trigger is the change that runs the suite which then fails.

Text parsing only — no YAML dependency is added to the B62 lockfile.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.model_policy import (
    DEFAULT_B14_MODEL_ID,
    EXECUTABLE_B14_MODEL_IDS,
    LOW_B14_MODEL_ID,
)
from padiem_control_plane.product_tier_routes import (
    ProductTierLabel,
    ProductRouteStatus,
    active_route_for,
    get_tier,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/b62-padiem-chat-ci.yml"
CONTRACT_PATH = "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py"


def _pull_request_path_filters(text: str) -> list[str]:
    """Return the literal entries of on.pull_request.paths, in file order."""
    lines = text.splitlines()
    start = next(
        (index for index, line in enumerate(lines) if re.match(r"^  pull_request:\s*$", line)),
        None,
    )
    assert start is not None, "workflow has no pull_request trigger"
    paths_index = next(
        (
            index
            for index in range(start + 1, len(lines))
            if re.match(r"^\s{4}paths:\s*$", lines[index])
        ),
        None,
    )
    assert paths_index is not None, "pull_request trigger has no paths filter"
    filters: list[str] = []
    for line in lines[paths_index + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        entry = re.match(r"^\s{6}-\s*(.+?)\s*$", line)
        if entry is None:
            break
        filters.append(entry.group(1).strip("'\""))
    return filters


def test_chat_ci_runs_when_the_shared_tier_declaration_changes() -> None:
    assert CONTRACT_PATH in _pull_request_path_filters(WORKFLOW.read_text(encoding="utf-8")), (
        "Chat resolves product tiers from this file, so its suite must run when it changes; "
        "see #2800"
    )


def test_trigger_stays_narrow_to_the_declaration_file() -> None:
    filters = _pull_request_path_filters(WORKFLOW.read_text(encoding="utf-8"))
    assert not [entry for entry in filters if entry.endswith("padiem-control-plane/**")], (
        "watching the whole control-plane package would run B62 on unrelated edits"
    )


def test_chat_current_route_expectation_is_derived_not_restated() -> None:
    # The assertion a switch has to keep passing, stated without naming any model: Chat's
    # Plus identity and its executable set must equal whatever the declaration says.
    plus = active_route_for(ProductTierLabel.PLUS)
    assert plus is not None and plus.model_id, "Padiem Plus must expose an executable route"
    assert LOW_B14_MODEL_ID == plus.model_id
    assert DEFAULT_B14_MODEL_ID == plus.model_id
    assert set(EXECUTABLE_B14_MODEL_IDS) == {
        route.model_id
        for tier in (ProductTierLabel.PLUS, ProductTierLabel.PRO, ProductTierLabel.MAX)
        for route in get_tier(tier).routes
        if route.status is ProductRouteStatus.EXECUTABLE
    }


def test_owner_policy_invariants_are_not_traded_for_coverage() -> None:
    for tier in (ProductTierLabel.PLUS, ProductTierLabel.PRO, ProductTierLabel.MAX):
        definition = get_tier(tier)
        assert definition.silent_fallback_allowed is False
        assert "auto" not in definition.label.value.lower()
        assert "fallback" not in definition.label.value.lower()
        executable = [
            route for route in definition.routes if route.status is ProductRouteStatus.EXECUTABLE
        ]
        assert len(executable) <= 1
