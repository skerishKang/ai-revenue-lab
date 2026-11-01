"""#6065: switching the content country must move the stored lists with it.

Found while executing the S5 acceptance item "국가별 문서 저장·필터·재진입" on production.
Measured there with generous waits, so this is not a race: after saving a kr document,
switching the select kr -> uk -> fr kept showing `S5TEST-kr-meeting.txt` in the saved
list and in the activity archive for all three countries, and only a page reload moved
the list to the country actually selected.

The filter (`sameCountry`, #6046) was never missing. Nothing re-ran it: a list was
filtered only when its tool rebuilt it, i.e. on a save or a load.

These tests run the SHIPPED `static/council-app.js` in the Node harness, and they also
pin that the fix changed nothing on the wire.
"""

from __future__ import annotations

from _council_module import run

import re

# 축사 파일 이름은 행사명과 날짜를 함께 쓴다(B7): 축사_행사명_YYYY-MM-DD.txt
UK_DOC = re.compile(r"^축사_UK hall address_\d{4}-\d{2}-\d{2}\.txt$")
FR_DOC = re.compile(r"^축사_Salle communale_\d{4}-\d{2}-\d{2}\.txt$")
KR_DOC = re.compile(r"^축사_주민 센터 행사_\d{4}-\d{2}-\d{2}\.txt$")
KR_MEETING = "주민 안전 회의.txt"


def only(pattern, rows):
    assert len(rows) == 1 and pattern.match(rows[0]), rows
    return rows[0]


def observation() -> dict:
    return run("country_filter")


def test_each_country_shows_only_its_own_documents_without_a_reload() -> None:
    seen = observation()["seen"]
    only(UK_DOC, seen["list_after_saving_uk"])
    only(FR_DOC, seen["list_after_saving_fr"])
    only(KR_DOC, seen["list_after_saving_kr"])


def test_switching_away_hides_the_previous_country_immediately() -> None:
    """The defect: before the fix every one of these still listed the last document."""
    seen = observation()["seen"]
    assert seen["kr_sees_when_last_saved_was_uk"] == [], seen["kr_sees_when_last_saved_was_uk"]
    assert seen["kr_sees_when_last_saved_was_fr"] == [], seen["kr_sees_when_last_saved_was_fr"]
    only(KR_DOC, seen["kr_sees_when_last_saved_was_kr"])


def test_switching_back_restores_the_list_without_a_reload() -> None:
    only(KR_DOC, observation()["seen"]["final_list"])


def test_the_activity_archive_follows_the_country_and_its_own_kind() -> None:
    """#A3: the meeting archive lists meeting records only.

    A stored 축사 is a speech (doc_kind), so it no longer appears as a source
    record for an activity book; the archive follows the selected country.
    """
    obs = observation()
    assert obs["krArchive"] == [KR_MEETING], obs["krArchive"]
    assert obs["frArchive"] == [], obs["frArchive"]


def test_a_stored_document_keeps_the_country_it_was_saved_under() -> None:
    stored = dict(observation()["storedCountries"])
    assert len(stored) == 4, stored
    by_country = {}
    for name, country in stored.items():
        by_country.setdefault(country, []).append(name)
    only(UK_DOC, by_country["uk"])
    only(FR_DOC, by_country["fr"])
    assert KR_MEETING in by_country["kr"]
    only(KR_DOC, [row for row in by_country["kr"] if row != KR_MEETING])


def test_the_fix_changes_nothing_on_the_wire() -> None:
    """Generation payload and stored-document shape are exactly the #6046 contract."""
    obs = observation()
    # `mode` is gone from the request contract (chat-mode remnant removal) and
    # `country` is gone from the chat request too (B3). The stored-document save
    # still carries it: that is a different, live API.
    assert set(obs["chatBodyKeys"]) == {"messages,tier,util"}, obs["chatBodyKeys"]
    assert all("country" not in body for body in obs["chatBodyKeys"])
    assert set(obs["saveBodyKeys"]) == {"country,doc_kind,media_type,name,text",
                                        "doc_kind,media_type,name,text"}, obs["saveBodyKeys"]
    assert obs["saveCountries"] == ["uk", "fr", "kr(absent)", "kr(absent)"], obs["saveCountries"]


def test_switching_country_never_creates_or_deletes_a_document() -> None:
    """Filtering is a projection, not a mutation."""
    assert len(observation()["storedCountries"]) == 4
