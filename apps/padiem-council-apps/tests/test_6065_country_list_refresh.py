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

UK_DOC = "UK hall address.txt"
FR_DOC = "Salle communale.txt"
KR_DOC = "주민 센터 행사.txt"
KR_MEETING = "주민 안전 회의.txt"


def observation() -> dict:
    return run("country_filter")


def test_each_country_shows_only_its_own_documents_without_a_reload() -> None:
    seen = observation()["seen"]
    assert seen["list_after_saving_uk"] == [UK_DOC], seen["list_after_saving_uk"]
    assert seen["list_after_saving_fr"] == [FR_DOC], seen["list_after_saving_fr"]
    assert seen["list_after_saving_kr"] == [KR_DOC], seen["list_after_saving_kr"]


def test_switching_away_hides_the_previous_country_immediately() -> None:
    """The defect: before the fix every one of these still listed the last document."""
    seen = observation()["seen"]
    assert seen["kr_sees_when_last_saved_was_uk"] == [], seen["kr_sees_when_last_saved_was_uk"]
    assert seen["kr_sees_when_last_saved_was_fr"] == [], seen["kr_sees_when_last_saved_was_fr"]
    assert seen["kr_sees_when_last_saved_was_kr"] == [KR_DOC]


def test_switching_back_restores_the_list_without_a_reload() -> None:
    assert observation()["seen"]["final_list"] == [KR_DOC]


def test_the_activity_archive_follows_the_country_too() -> None:
    obs = observation()
    assert obs["krArchive"] == [KR_DOC, KR_MEETING], obs["krArchive"]
    assert obs["frArchive"] == [FR_DOC], obs["frArchive"]
    assert KR_DOC not in obs["frArchive"] and KR_MEETING not in obs["frArchive"]


def test_a_stored_document_keeps_the_country_it_was_saved_under() -> None:
    stored = dict(observation()["storedCountries"])
    assert stored == {UK_DOC: "uk", FR_DOC: "fr", KR_DOC: "kr", KR_MEETING: "kr"}, stored


def test_the_fix_changes_nothing_on_the_wire() -> None:
    """Generation payload and stored-document shape are exactly the #6046 contract."""
    obs = observation()
    # `mode` is gone from the request contract (chat-mode remnant removal), so the
    # only bodies this module can put on the wire are these two key sets.
    assert set(obs["chatBodyKeys"]) == {"country,messages,tier,util",
                                        "messages,tier,util"}, obs["chatBodyKeys"]
    assert set(obs["saveBodyKeys"]) == {"country,media_type,name,text",
                                        "media_type,name,text"}, obs["saveBodyKeys"]
    assert obs["saveCountries"] == ["uk", "fr", "kr(absent)", "kr(absent)"], obs["saveCountries"]


def test_switching_country_never_creates_or_deletes_a_document() -> None:
    """Filtering is a projection, not a mutation."""
    assert len(observation()["storedCountries"]) == 4
