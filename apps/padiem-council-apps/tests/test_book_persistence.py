"""#5942: the activity book persists, and a re-entry can reopen it.

The book builder used to stop at copy and download, so a draft vanished on refresh
and the stored list showed nothing on arrival. These tests run the shipped module
against the recording fake of the EXISTING project-file contract: generate → edit →
save → reload → reopen → re-save, plus the file-name separation that keeps a book
out of its own source-record list.
"""

from __future__ import annotations

from pathlib import Path

from _council_module import run

BOOK_PREFIX = "활동집 - "
OBSERVATION = run("book")


def test_a_press_saves_one_book_even_when_clicked_twice() -> None:
    # The second press lands while the first is still in flight: the button is
    # armed only when nothing is saving, so the draft cannot be stored twice.
    assert OBSERVATION["saveRequests"] == ["POST /api/projects/p1/files"]
    assert OBSERVATION["bookNamesA"] == [BOOK_PREFIX + "주민 안전 활동집.txt"]
    assert OBSERVATION["alerts"] == []


def test_the_draft_and_its_confirmation_survive_the_list_refresh_after_saving() -> None:
    kept = OBSERVATION["keptInA"]
    assert kept["draftHead"].strip().startswith("주민 안전 활동집")
    assert kept["resultHidden"] is False
    assert kept["saveLabel"] == "저장됨"


def test_a_reentry_lists_the_book_and_reopens_the_edited_body() -> None:
    assert OBSERVATION["openLabels"] == [BOOK_PREFIX + "주민 안전 활동집.txt (37자)"]
    # What the user typed into the draft, not the raw model answer, is what comes back.
    assert OBSERVATION["reopenedMatchesEdit"] is True
    assert OBSERVATION["reopenedHead"].startswith("주민 안전 활동집")
    assert OBSERVATION["resultHiddenAfterOpen"] is False


def test_stored_books_stay_out_of_the_record_selection() -> None:
    # One meeting record is stored, so exactly one checkbox may exist: the book
    # must never be offered as a source for another book.
    assert OBSERVATION["recordChecks"] == 1
    assert [label for label in OBSERVATION["recordLabels"] if label.startswith(BOOK_PREFIX)] == []
    # #A3: the meeting record carries doc_kind="meeting", so it no longer
    # surfaces as a speech manuscript either. The book stays out of both lists.
    assert all(
        not label.startswith(BOOK_PREFIX) for label in OBSERVATION["speechLabelsB"]
    ), "a book is not a speech manuscript"


def test_re_editing_and_saving_under_a_new_title_keeps_both_versions() -> None:
    # The name follows the draft's own first line, and a re-save never deletes a
    # stored book: the earlier version stays readable.
    assert OBSERVATION["openLabelsC"] == [
        BOOK_PREFIX + "주민 안전 활동집.txt (37자)",
        BOOK_PREFIX + "여름 활동 보고.txt (47자)",
    ]


def test_the_book_lane_reuses_the_existing_project_file_contract() -> None:
    assert set(OBSERVATION["endpoints"]) <= {
        "GET /api/auth/status",
        "POST /api/chat/stream",
        "GET /api/projects",
        "GET /api/projects/p1/files",
        "POST /api/projects/p1/files",
        "GET /api/projects/p1/files/f1",
        "GET /api/projects/p1/files/f2",
    }
    assert OBSERVATION["pageErrors"] == []


def test_the_book_editor_keeps_copy_and_download_next_to_the_new_save() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("static/council-app.js").read_text(
        encoding="utf-8"
    )
    # 2026-11-01: the download control is the three formats
    # [한글(HWPX)] [워드(DOCX)] [텍스트], next to copy and save as before.
    for control in ('"복사"', '"한글(HWPX)"', '"워드(DOCX)"', '"텍스트"', "활동집 저장"):
        assert control in source, control
    # The naming rule is the Chat util's, so a book saved from either surface
    # lists in both instead of becoming a second, incompatible family.
    assert 'const BOOK_PREFIX = "활동집 - ";' in source
    assert "function isManuscriptFile" in source and "function isStoredBook" in source
