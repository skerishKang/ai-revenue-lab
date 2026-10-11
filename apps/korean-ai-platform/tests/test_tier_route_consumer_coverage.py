"""#2802. B14 is the final execution authority, so its gate must run on a declaration change.

`product_tier_routes.py` declares which provider/model backs Padiem Plus/Pro/Max, and B14
decides whether that route can actually execute. The drift guard for exactly that risk lives
here: `test_tier_registry_v1.py::test_executable_registry_routes_exist_in_b14_catalog`.
Before this child, `Validate B14 Alpha` triggered only on `apps/korean-ai-platform/**`, so a
PR that changed nothing but the declaration shipped without ever running it — the one change
where the guard matters most.

The assertions read the workflow text rather than importing a parser on purpose: this gate is
dependency-locked (`uv sync --frozen`) and no YAML dependency is added for it. Because the
workflow lists its own file under `pull_request.paths`, removing the trigger is the edit that
runs this test and fails it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/validate-b14-alpha.yml"
REGISTRY_TEST = Path(__file__).resolve().parent / "test_tier_registry_v1.py"

DECLARATION_PATH = (
    "packages/padiem-control-plane/padiem_control_plane/product_tier_routes.py"
)
SELF_PATH = ".github/workflows/validate-b14-alpha.yml"
B14_APP_PATH = "apps/korean-ai-platform/**"


def _pull_request_path_filters(text: str) -> list[str]:
    """Return the literal entries of on.pull_request.paths, in file order."""
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^  pull_request:\s*$", line)), None
    )
    assert start is not None, "Validate B14 Alpha has no pull_request trigger"
    paths_index = next(
        (
            i
            for i in range(start + 1, len(lines))
            if re.match(r"^\s{4}paths:\s*$", lines[i])
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


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), f"expected the B14 alpha workflow at {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


def test_b14_suite_runs_when_the_shared_tier_declaration_changes() -> None:
    filters = _pull_request_path_filters(_workflow_text())
    assert DECLARATION_PATH in filters, (
        "B14 is the execution authority for product-tier routes: a declaration change must "
        "run the suite that checks declared routes exist in the B14 catalog. See #2802."
    )


def test_trigger_names_the_declaration_file_and_not_the_whole_package() -> None:
    # A `packages/padiem-control-plane/**` filter would run the heaviest B14 gate on every
    # control-plane edit, which is noise that gets ignored and stops being a signal.
    filters = _pull_request_path_filters(_workflow_text())
    assert "packages/padiem-control-plane/**" not in filters
    assert not [
        entry
        for entry in filters
        if entry.startswith("packages/padiem-control-plane/") and entry.endswith("/**")
    ], "no broad control-plane glob may stand in for the exact declaration path"


def test_workflow_still_pins_its_own_file_so_the_guard_is_self_enforcing() -> None:
    filters = _pull_request_path_filters(_workflow_text())
    assert SELF_PATH in filters, (
        "without its own path the workflow would not run when someone edited its trigger list, "
        "and the assertions above could be deleted silently"
    )
    assert B14_APP_PATH in filters, "the pre-existing B14 app trigger must remain"


def test_the_drift_guard_this_trigger_exists_to_run_is_still_present() -> None:
    # The trigger is pointless if the check it protects goes away: this names the B14 catalog
    # drift guard so deleting it has to pass through this file too.
    source = REGISTRY_TEST.read_text(encoding="utf-8")
    assert "def test_executable_registry_routes_exist_in_b14_catalog" in source
    assert "is not registered in the B14 catalog" in source
