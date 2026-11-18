"""#7976 — a missing PC folder is "not found", never a broken JSON page."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from app import claw_pc_query_step_driver as driver
from test_261105_pc_list_structured_items import _install_wire, _list, _owner_run  # noqa: F401


def test_a_not_found_verdict_is_a_distinct_stage(monkeypatch) -> None:
    _install_wire(monkeypatch, output=json.dumps({"error": "path_not_found"}))
    with pytest.raises(driver.ToolHandlerError) as caught:
        _list()
    assert caught.value.code == "pc_path_not_found"


def test_a_broken_page_still_names_its_own_failure(monkeypatch) -> None:
    _install_wire(monkeypatch, output="this is not json")
    with pytest.raises(driver.ToolHandlerError) as caught:
        _list()
    assert caught.value.code == "pc_list_output_invalid"


@pytest.mark.parametrize("value,expected", [
    ("D:/.", "D:"), ("D:/./CGI", "D:/CGI"), ("c:\\", "C:"),
])
def test_a_granted_drive_folds_dot_segments(value, expected) -> None:
    context = {"roots": [{"label": "D:"}, {"label": "C:"}]}
    assert driver._pc_path_against_granted_drive(value, context) == expected


def test_a_dotdot_walk_is_still_refused() -> None:
    assert driver._pc_path_against_granted_drive(
        "D:/../secret", {"roots": [{"label": "D:"}]}) == "D:/../secret"
    assert driver._pc_list_folder_prefix("D:/../secret", ("D:",)) is None
