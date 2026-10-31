"""#6199 — 예전 축사·SNS 글을 [고쳐 쓰기]로 다시 열어 고치고 저장하는 흐름.

#5731 made the stored list real (kind, same-name 409, version keeping) but the
list only displayed a body. This module pins the chain the shipped browser
module now offers, run against the real ``static/util-menu.js`` through
``tests/_5785_util_harness.js`` (scenario ``edit``):

- the list's rows are the reopen action, and only this tool's kind appears;
- reopening loads the stored body into the SAME editable draft — one editor,
  not a second one, and the screen states which stored name is being edited;
- saving an edited piece goes through the existing same-name 409 → 새 이름 /
  덮어쓰기 flow, keeps ``doc_kind``, and the previous body stays as a version row
  that the list does not show as an item;
- a piece that is gone says its real status out loud, with no success wording.

The server half (409 payload, PUT versioning, owner 404) is pinned in
``test_5731_util_save_kind_and_version.py``.
"""

from __future__ import annotations

import pytest

from _5785_util_runner import run

SPEECH = "작년 신년사.txt"
MEETING = "봄 행사 기록.txt"
SNS = "개교 소식.txt"


@pytest.fixture(scope="module")
def edit() -> dict:
    return run("edit")


def test_a_stored_piece_opens_through_a_reopen_action(edit: dict) -> None:
    rows = edit["initialRows"]
    assert rows, "the saved list must offer its stored pieces"
    assert all(label.startswith("고쳐 쓰기: ") for label in rows), rows
    assert any(SPEECH in label for label in rows), rows
    # #5731's kind rule still holds: another tool's writing is not here.
    assert not any(MEETING in label for label in rows), rows


def test_reopening_fills_the_existing_editor_with_the_stored_body(edit: dict) -> None:
    assert edit["loadedBody"] == "작년 신년사 본문입니다."
    # One editor: 고쳐 쓰기 reuses the shipped draft area, it does not build a
    # second read-only view next to it.
    assert edit["editorCount"] == 1
    assert edit["editStateVisible"] is True
    state = edit["editStateText"]
    assert SPEECH in state
    assert "덮어쓰기" in state and "버전" in state


def test_a_same_name_save_asks_instead_of_stacking(edit: dict) -> None:
    assert edit["askText"] == "같은 이름의 글이 이미 있습니다: " + SPEECH
    labels = edit["askLabels"]
    assert labels[0].startswith("새 이름으로 저장"), labels
    assert labels[1].startswith("덮어쓰기"), labels
    # The question came before any second row: nothing was written yet.
    assert edit["rowsBeforeChoice"] == 2


def test_saving_under_a_new_name_keeps_the_kind_and_adds_one_row(edit: dict) -> None:
    rows = edit["speechRowsAfterNewName"]
    names = [row["name"] for row in rows]
    assert names.count(SPEECH) == 1, names
    # nextFreeName numbers the stem: 작년 신년사.txt -> 작년 신년사 (2).txt
    assert "작년 신년사 (2).txt" in names, names
    listed = edit["listAfterNewName"]
    assert sum(1 for label in listed if "작년 신년사 (" in label) == 1, listed


def test_overwriting_the_same_row_keeps_the_previous_body_as_a_version(
    edit: dict,
) -> None:
    assert edit["overwrittenBody"] == "작년 신년사 본문입니다. 덮어쓴 문장입니다."
    assert edit["overwrittenKind"] == "speech"
    versions = edit["versionRows"]
    assert len(versions) == 1, versions
    version = versions[0]
    assert version["name"] == "작년 신년사 (이전 1).txt"
    assert version["doc_version_of"] == "f71"
    assert version["doc_kind"] == "speech"
    assert version["content"] == "작년 신년사 본문입니다."
    # A version row is history, not an item in the list.
    assert not any("(이전" in label for label in edit["listAfterOverwrite"])
    assert any(SPEECH in label and "24자" in label for label in edit["listAfterOverwrite"])


def test_a_missing_piece_reports_its_real_failure(edit: dict) -> None:
    alert = edit["goneAlert"]
    assert alert, "opening a deleted piece must not pass silently"
    assert alert == "저장된 축사를 찾을 수 없습니다. 다른 계정의 글이거나 삭제된 글입니다."
    # No promise of a future feature, and no success wording on a failure.
    assert "곧" not in alert
    assert "저장됨" not in alert
    assert edit["alerts"] == [alert]


def test_sns_reopens_and_saves_without_touching_the_speech_rows(edit: dict) -> None:
    labels = edit["snsLabels"]
    assert len(labels) == 1 and SNS in labels[0], labels
    assert edit["snsLoadedBody"] == "개교 소식 본문입니다."
    assert SNS in edit["snsStateText"]
    assert sorted(edit["snsStored"]) == sorted([SNS, "개교 소식 (2).txt"])
    # The speech list kept exactly its own rows through the SNS save.
    assert sorted(edit["speechStored"]) == sorted([SPEECH, "작년 신년사 (2).txt"])


def test_the_flow_uses_only_the_existing_project_file_routes(edit: dict) -> None:
    allowed = {
        "GET /api/pc/pairings",
        "GET /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
    }
    for endpoint in edit["endpoints"]:
        if endpoint in allowed:
            continue
        # A detail read and the version-keeping overwrite are the existing
        # single-file routes, never a new one.
        assert endpoint.startswith("GET /api/projects/p1/files/") or endpoint == (
            "PUT /api/projects/p1/files/f71"
        ), endpoint
    assert edit["pageErrors"] == []
