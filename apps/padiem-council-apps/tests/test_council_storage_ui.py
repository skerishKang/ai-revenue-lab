"""2026-11-01 저장 안정화 + 화면 정리 (의원3종 독립 앱).

Every assertion here runs the SHIPPED ``static/council-app.js`` through the
Node harness (or reads the shipped sheet/markup for the visual contract).
The storage rules follow the Chat util's own shipped behaviour — one pinned
project, doc_kind, a 409 choice, an in-place roster — without a second store.
"""

from __future__ import annotations

import re
from pathlib import Path

from _council_module import run, local_asset_targets

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
JS = (STATIC / "council-app.js").read_text(encoding="utf-8")
CSS = (STATIC / "council-app.css").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")

SPEECH_FILE = re.compile(r"^축사_중복 이름 행사_\d{4}-\d{2}-\d{2}\.txt$")


def rule(selector: str) -> str:
    found = re.search(rf"(?:^|\n){re.escape(selector)}\s*\{{([^}}]*)\}}", CSS, re.S | re.M)
    assert found, f"missing rule: {selector}"
    return found.group(1)


# ── A1. 저장 프로젝트 고정 ──────────────────────────────────────────────────

def test_the_pinned_project_is_found_by_name_not_by_list_position() -> None:
    obs = run("storage")["otherFirst"]
    # 의원3종 is second in the listing; projects[0] would have been "다른 작업".
    assert obs["savedTo"] == ["/api/projects/p1/files"], obs
    assert obs["postCreates"] == 0, obs
    # Three tools opened together asked once; the promise is shared.
    assert obs["getReads"] == 1, obs


def test_the_project_is_created_once_when_it_is_genuinely_absent() -> None:
    obs = run("storage")["absent"]
    assert obs["postCreates"] == 1, obs
    assert obs["savedTo"] == ["/api/projects/p2/files"], obs


def test_a_failed_read_never_creates_a_project() -> None:
    obs = run("storage")["readFails"]
    assert obs["postCreates"] == 0, obs
    assert obs["savedTo"] == [], obs
    assert "프로젝트를 찾지 못했습니다" in obs["notice"], obs["notice"]
    # ...and the next attempt, after the read recovers, creates exactly once.
    retry = run("storage")["retry"]
    assert retry["postCreates"] == 1, retry
    assert len(retry["storedNames"]) == 1, retry


# ── A2. 생성 흐름 ───────────────────────────────────────────────────────────

def test_generation_aborts_after_120_seconds_and_never_prints_raw_json() -> None:
    assert "GEN_TIMEOUT_MS = 120000" in JS
    assert "controller.abort()" in JS
    assert "signal: controller.signal" in JS
    # The old fallback dumped the response body into the draft area.
    assert "JSON.stringify(data)" not in JS
    assert "emptyResult()" in JS


def test_the_generation_and_save_buttons_wait_for_the_answer() -> None:
    assert 'setNotice(notice, "생성 중…", "busy")' in JS
    assert "submitBtn.disabled = true;" in JS
    assert "saveBtn.disabled = busy || failed || !String(output.value || \"\").trim();" in JS


# ── A3. doc_kind · 409 ─────────────────────────────────────────────────────

def test_a_name_collision_offers_a_new_name_or_an_overwrite() -> None:
    obs = run("conflict")
    assert len(obs["firstName"]) == 1 and SPEECH_FILE.match(obs["firstName"][0]), obs["firstName"]
    first = obs["firstName"][0]
    stem = first[: -len(".txt")]
    assert obs["saveChoiceText"] == ["같은 이름의 글이 이미 있습니다: " + first]
    assert obs["choiceLabel"] == "새 이름으로 저장 (" + stem + " (2).txt)"
    assert obs["afterNew"] == [first, stem + " (2).txt"], obs["afterNew"]
    # Overwrite is a PUT of the SAME file: the id survives, the body is replaced.
    after = {row["id"]: row for row in obs["afterOverwrite"]}
    assert after["f1"]["text"] == "덮어쓴 본문", after
    assert "PUT /api/projects/p1/files/f1" in obs["endpoints"], obs["endpoints"]
    assert obs["alerts"] == [] and obs["pageErrors"] == []


def test_a_refused_save_shows_the_servers_message() -> None:
    obs = run("conflict")
    assert obs["failureNotice"] == "저장하지 못했습니다: 저장소가 잠시 응답하지 않습니다."
    assert obs["failureTone"] == "error"


def test_each_list_asks_for_its_own_doc_kind() -> None:
    assert 'kind: "speech"' in JS and 'kind: "sns"' in JS
    assert 'kind: "meeting"' in JS and 'kind: "book"' in JS
    assert "function isSpeechFile(file)" in JS and "function isMeetingFile(file)" in JS
    assert "function isBookFile(file)" in JS


# ── A4. SNS 사진 ────────────────────────────────────────────────────────────

def test_the_roster_is_rewritten_in_place_and_only_its_photos_return() -> None:
    obs = run("roster")
    assert obs["rosterPosts"] == 1, obs
    assert obs["rosterWrites"] >= 1, obs
    assert obs["rosterDeletes"] == 0, obs
    assert obs["rosterCount"] == 1, obs
    assert obs["rosterNames"] == ["둘.png", "하나.png"], obs["rosterNames"]
    # A stored image the roster does not name never comes back.
    assert obs["strayRestored"] is False, obs
    assert obs["namesB"] == ["둘.png", "하나.png"], obs["namesB"]


def test_a_big_photo_is_shrunk_before_the_upload() -> None:
    obs = run("roster")
    assert obs["resizeCalls"] == 2, obs
    uploaded = dict(obs["uploadTypes"])
    assert uploaded["하나.png"] == "image/png", obs["uploadTypes"]
    # The resizer ships inside this app; no Chat asset is fetched.
    assert (STATIC / "photo-resize.js").is_file()
    assert not any(target.startswith("./assets/") is False for target in local_asset_targets(CSS))


# ── A5. 런타임 오류 ─────────────────────────────────────────────────────────

def test_escape_while_typing_keeps_the_editor_open() -> None:
    obs = run("runtime")
    assert obs["opened"] == "speech"
    assert obs["afterTypingEscape"] == "speech", "Escape inside a field closed the editor"
    assert obs["afterPlainEscape"] is None
    assert obs["pageErrors"] == []


def test_the_book_save_scan_never_calls_find_on_a_nodelist() -> None:
    assert 'Array.from(arc.querySelectorAll(".council-book-open"))' in JS
    assert 'arc.querySelectorAll(".council-book-open") || []' not in JS


# ── B6 · B7. 화면 정리 ─────────────────────────────────────────────────────

def test_the_workspace_exit_is_korean_and_the_close_control_is_legible() -> None:
    assert "&larr; 처음으로" in HTML
    assert "시네마틱 홈으로" not in HTML
    close = rule("html.council-in-workspace .council-card.active .council-card-select")
    assert "color: var(--text)" in close, close
    assert "border: var(--pa-hair) solid var(--line)" in close, close


def test_copy_save_and_download_are_the_row_directly_under_the_result() -> None:
    order = run("generate")["actionOrder"]
    assert order["speech"] == ["councilSpeechCopy", "councilSpeechSave", "councilSpeechDownload"]
    assert order["sns"] == ["councilSnsCopy", "councilSnsSave", "councilSnsDownload"]
    assert order["meeting"] == ["councilMeetingCopy", "councilMeetingSave", "councilMeetingDownload"]
    assert order["book"] == ["councilBookCopy", "councilBookSave", "councilBookDownload"]
    # The primary action is the copy control.
    assert "council-primary" in JS
    assert ".council-actions .council-primary" in CSS


def test_the_speech_file_name_uses_the_event_and_the_date() -> None:
    obs = run("generate")
    assert obs["downloads"] == ["축사_제78주년 광복절 기념식_2026-08-15.txt"]
    assert "축사_제78주년 광복절 기념식_2026-08-15.txt" in obs["savedNames"]


# ── B8. 축사 입력 ──────────────────────────────────────────────────────────

def test_the_speech_form_shows_four_fields_first_and_folds_the_rest() -> None:
    obs = run("speech_form")
    assert obs["foldTag"] == "DETAILS", "the extra fields fold under 더 자세히"
    assert all(obs["foldedFields"]), obs["foldedFields"]
    assert obs["lengthOptions"] == ["1분", "3분", "5분"], obs["lengthOptions"]
    # The primary four live in the open fieldset.
    assert obs["directlyVisible"] == ["event", "audience", "author", "length"]


def test_each_speech_field_carries_an_example_and_the_title_is_remembered() -> None:
    obs = run("speech_form")
    for name, placeholder in obs["placeholders"].items():
        assert placeholder.startswith("예:"), (name, placeholder)
    assert obs["rememberedAuthor"] == "지역구 국회의원 김의민"
    assert "padiem-council-speech-author" in JS


# ── B9. 글씨·터치·겹침 ─────────────────────────────────────────────────────

def test_body_type_is_16px_and_name_tags_are_at_least_14px() -> None:
    fields = rule(".council-form input,\n.council-form textarea,\n.council-form select")
    assert "font-size: 16px" in fields, fields
    assert "font-size: 16px" in rule(".council-archive-item button")
    assert "font-size: 16px" in rule(".council-saved-item .council-saved-open")
    assert "font-size: 14px" in rule(".council-photo-name")
    assert "min-height: 44px" in fields
    # The card description is body copy too, and the narrow block keeps 16px.
    tail = CSS.split("/* ══ end of the ported token layer", 1)[-1]
    card_desc = re.search(r"(?m)^\.council-card > p\s*\{([^}]*)\}", tail)
    assert card_desc and "font-size: 16px" in card_desc.group(1), card_desc
    assert ".council-body { font-size: 16px; }" in CSS
    assert ".council-body { font-size: 15px; }" not in CSS


def test_the_date_and_selection_rows_are_44px() -> None:
    assert "min-height: 44px" in rule(".council-book-period input")
    assert "min-height: 44px" in rule(".council-book-period button")
    assert "min-height: 44px" in rule(".council-save")


def test_the_narrow_form_and_the_wide_sns_column_do_not_collide() -> None:
    # Inputs may not push a grid column wider than the screen.
    fields = rule(".council-form input,\n.council-form textarea,\n.council-form select")
    assert "min-width: 0" in fields and "width: 100%" in fields
    assert "min-width: 0" in rule(".council-card-body > *")
    narrow = re.search(r"@media \(max-width: 390px\)\s*\{(.*?)\n\}", CSS, re.S)
    assert narrow and ".council-book-period { display: grid" in narrow.group(1)


# ── B10. 한국어 화면 ───────────────────────────────────────────────────────

def test_the_screen_strings_are_korean() -> None:
    for english in ("PARLIAMENTARY AI STUDIO", "AI WORK TOOLS",
                    "PEOPLE &middot; DEMOCRACY", "TXT 다운로드"):
        assert english not in HTML + JS, english
    assert "국회 AI 업무 스튜디오" in HTML and "AI 업무 도구" in HTML
    assert "텍스트 다운로드" in JS


def test_the_activity_book_is_named_활동집_on_screen() -> None:
    # The model prompt keeps its shipped wording; the screen does not.
    for shown in ("책/활동집 초안", "책/활동집에 포함", "선택 기록으로 책/활동집"):
        assert shown not in JS, shown
    assert "활동집 초안" in JS
    assert "활동집에 포함" in JS
    assert "선택 기록으로 활동집 초안 생성" in JS


def test_english_and_french_are_hidden_from_the_language_setting() -> None:
    setting = HTML[HTML.index('id="councilCountry"') - 400: HTML.index('id="councilCountry"') + 400]
    assert '<option value="kr">' in setting
    for hidden in ("us", "uk", "fr", "English", "Français"):
        assert hidden not in setting, hidden
    assert "결과물은 한국어로 작성됩니다" in HTML
    # A host that still remembers an older uk/fr choice is clamped to the one
    # language the selector can actually show.
    assert 'options.indexOf(stored) < 0 ? "kr" : stored' in JS
