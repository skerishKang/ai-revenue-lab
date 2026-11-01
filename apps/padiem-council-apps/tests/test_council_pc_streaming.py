"""2026-11-01 하나로 합치기 — 내 PC 다리와 스트리밍.

The independent app keeps the Chat util's PC bridge and turns generation into
a streamed answer. Both are executed through the shipped module; nothing here
asserts a string that the browser would not run.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from _council_module import run

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
JS = (STATIC / "council-app.js").read_text(encoding="utf-8")


def test_a_page_without_a_computer_says_so_calmly_and_offers_connect() -> None:
    obs = run("pc")["noPc"]
    # The picker is not offered while no PC is linked; one sentence and the
    # way to connect take its place. Nothing is styled as an error.
    assert obs["pickHidden"] is True
    assert obs["noteHidden"] is False
    assert obs["note"] == "컴퓨터를 연결하면 예전 글을 가져올 수 있습니다."
    assert obs["linkLabel"] == "컴퓨터 연결하기"
    assert obs["linkHref"] == "/#padiem-connectors"
    # No PC read is attempted just to show the sentence.
    assert obs["referenceReads"] == 0
    # Saving with no PC is the same guidance, not a failure dialog.
    assert obs["saveNotice"] == "컴퓨터를 연결하면 내 PC에 저장할 수 있습니다."
    assert obs["saveNoticeLink"] == "/#padiem-connectors"
    assert obs["saveNoticeTone"] == "info"


def test_a_picked_text_becomes_a_reference_in_both_prompts() -> None:
    obs = run("pc")
    assert obs["importedB"]["reads"] == [{"file_id": "pc-doc-1"}]
    assert obs["importedB"]["preview"] == "예전 축사 원고입니다. 문체를 참고하세요."
    assert "[참고 글 1: 예전 축사.hwp]" in obs["speechPrompt"]
    assert "그대로 옮기지 마세요" in obs["speechPrompt"]
    assert "예전 축사 원고입니다." in obs["speechPrompt"]
    assert "[참고 글 1: 예전 축사.hwp]" in obs["snsPrompt"]


def test_saving_to_the_pc_offers_a_new_dated_name_never_the_original() -> None:
    obs = run("pc")
    saved = obs["savedB"]
    # The stamp is the day the save runs — the app's todayStamp() reads the real
    # clock, so the expectation reads the same clock instead of pinning the day
    # this test was written (which made it fail on every later day).
    assert saved["fileName"] == f"축사_PC 가져오기 검증_{date.today().isoformat()}.txt"
    assert saved["content"] == obs["outputB"]
    assert obs["savedIsNewName"] is True, "a copy must never reuse the stored document name"
    assert obs["saveNoticeB"] == "내 PC에 저장했습니다."
    assert "save" in obs["openedModes"]


def test_a_pc_photo_is_read_through_the_file_route_and_uploaded() -> None:
    obs = run("pc")
    assert obs["pcDispatch"] == ["pc-photo-1"]
    assert "GET /api/pc/file?dispatch_id=pc-photo-1" in obs["endpoints"]
    assert obs["photoCount"] == "1장"
    assert obs["photoNames"] == ["현장사진.png"]
    assert obs["photoUpload"] == ["현장사진.png"]
    assert obs["alerts"] == [] and obs["pageErrors"] == []


def test_generation_is_streamed_from_the_stream_route() -> None:
    obs = run("streaming")
    assert obs["endpoint"] == "/api/chat/stream"
    assert obs["accept"] == "text/event-stream"
    # 0 → partial → final: the answer reached the draft before it finished.
    assert obs["lengths"][0] == 0
    intermediate = [n for n in obs["lengths"] if 0 < n < len(obs["expected"])]
    assert intermediate, obs["lengths"]
    assert obs["final"] == obs["expected"]
    assert obs["notice"] == ""
    assert obs["pageErrors"] == []


def test_the_timeout_and_error_copy_are_the_ones_6556_shipped() -> None:
    # 타임아웃 값은 2026-11-02 한도 감사 4번으로 120초 → 300초 임시 완화(근본은 진행 표시 전환).
    assert "GEN_TIMEOUT_MS = 300000" in JS
    assert "controller.abort()" in JS
    assert "signal: controller.signal" in JS
    assert 'GEN_ERROR_COPY' in JS
    assert "emptyResult()" in JS
    assert "JSON.stringify(data)" not in JS


def test_a_failed_generation_offers_retry_and_it_really_runs_again() -> None:
    obs = run("errors")
    assert obs["retryPresent"] is True
    assert obs["retried"]["calls"] == 1
    assert obs["retried"]["output"].startswith("생성된 초안 본문입니다.")
    assert obs["retried"]["notice"] == ""


def test_the_shared_dialog_speaks_korean_in_this_app() -> None:
    # The dialog reads its copy from the host locale. This app ships the
    # dialog's own Korean sentences instead of showing raw keys.
    assert '"pc-exchange-import-title": "내 PC에서 가져오기"' in JS
    assert '"pc-exchange-close": "닫기"' in JS
    # A host that already has a locale keeps it; the shim never overwrites it.
    assert "if (window.__padiemLocale && typeof window.__padiemLocale.text === \"function\") return;" in JS
    # Escape while the PC dialog is open closes the dialog, never the editor.
    assert "exchange.isOpen()" in JS and "exchange.close()" in JS


def test_a_record_reorder_is_the_book_order() -> None:
    obs = run("parity")
    assert obs["before"][0].startswith("1월 회의") and obs["before"][1].startswith("3월 회의")
    assert obs["afterMove"][0].startswith("3월 회의") and obs["afterMove"][1].startswith("1월 회의")
    # The book reads the list as it is shown — the moved record is first.
    assert obs["bookPrompt"].index("[기록: 3월 회의.txt]") < obs["bookPrompt"].index("[기록: 1월 회의.txt]")
    assert obs["alerts"] == [] and obs["pageErrors"] == []


def test_quick_period_ranges_still_select_the_records() -> None:
    obs = run("parity")
    assert obs["periodStatus"].startswith("2건을 선택했습니다")
    assert obs["selectedAfterQuick"] == 2
    assert obs["year"] == 2026


def test_a_stored_draft_reopens_with_the_naming_note() -> None:
    obs = run("parity")
    assert obs["speechBody"] == "지난 축사 본문"
    assert obs["speechNotice"].startswith("지난 축사.txt를 열었습니다.")
    assert "새 이름/덮어쓰기" in obs["speechNotice"]


def test_stored_sns_drafts_are_listed_and_reopen() -> None:
    obs = run("parity")
    assert obs["snsLabels"] and obs["snsLabels"][0].startswith("블로그 게시글.txt")
    assert obs["snsBody"] == "저장된 SNS 초안"
    assert obs["snsNotice"].startswith("블로그 게시글.txt를 열었습니다.")


def test_the_pc_bridge_reuses_the_existing_pc_routes_only() -> None:
    source = JS
    for route in ('"/api/pc/pairings"', '"/api/pc/reference"', '"/api/pc/file?dispatch_id="'):
        assert route in source, route
    # The dialog itself is this app's own copy of the shipped component.
    for name in ("pc-file-exchange.js", "pc-file-exchange.css"):
        assert (STATIC / name).is_file(), name
    assert 'script.src = "./static/pc-file-exchange.js"' in source
    # No second pairing screen: the connect link goes to the Chat Connectors page.
    assert 'COMPUTER_CONNECT_HREF = "/#padiem-connectors"' in source
