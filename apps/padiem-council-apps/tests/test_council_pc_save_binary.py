"""2026-11-02 한글(HWPX)·워드(DOCX) 내 PC에 저장 — 의원 앱 저장 흐름.

The council app builds the document bytes in the browser, uploads them to the
owner's own project first (the library keeps them), and hands the exact bytes
to the PC save dialog through /api/pc/save's project_file_id source. These
tests own the browser-side contract through the shipped module harness; the
server-side contract is pinned in
apps/padiem-chat/tests/test_council_pc_save_binary_261102.py.
"""

from __future__ import annotations

import base64
from datetime import date

from _council_module import run

TODAY = date.today().isoformat()


def test_the_pc_save_button_first_asks_which_format_to_write() -> None:
    chooser = run("pc")["saveChooser"]
    assert chooser["text"] == "어떤 형식으로 저장할까요?"
    # 기본(첫 버튼)은 한글이고, #5895의 텍스트 저장은 세 번째 선택으로 남는다.
    assert chooser["choices"] == ["한글", "워드", "텍스트"]


def test_saving_a_speech_document_uploads_hwpx_bytes_then_hands_them_to_the_pc() -> None:
    obs = run("pc_save_binary")
    upload = obs["upload"]
    assert upload["name"] == f"축사_주민 감사의 밤_{TODAY}.hwpx"
    assert upload["mediaType"] == "application/hwp+zip"
    # 라이브러리 묶음 규칙: 결과 종류가 doc_kind로 함께 올라간다.
    assert upload["docKind"] == "speech"
    # HWPX는 zip이다 — 브라우저가 만든 바이트 그대로 올라갔음의 최소 증거.
    assert base64.b64decode(upload["bytes"])[:2] == b"PK"
    # PC 저장은 올라간 프로젝트 파일의 file_id 소스로 불린다(f1은 하네스가
    # 붙이는 첫 고정 id — 업로드 응답의 id가 그대로 저장 요청에 실린다).
    assert obs["save"] == {"path": "문서/2026", "file_id": "f1"}
    assert obs["notice"] == "내 PC의 문서 폴더에 저장했어요."


def test_an_sns_post_saves_as_docx_under_the_sns_kind() -> None:
    docx = run("pc_save_binary")["docx"]
    assert docx["upload"]["name"] == f"SNS_블로그 게시글_{TODAY}.docx"
    assert docx["upload"]["mediaType"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert docx["upload"]["docKind"] == "sns"
    assert docx["savePosted"] is True
    assert docx["notice"] == "내 PC의 문서 폴더에 저장했어요."


def test_a_failed_project_upload_says_so_and_offers_a_retry() -> None:
    fail = run("pc_save_binary")["uploadFail"]
    assert fail["notice"] == "문서를 프로젝트에 올리지 못했습니다. 잠시 후 다시 시도해 주세요."
    assert fail["hasRetry"] is True


def test_a_failed_pc_save_never_claims_success() -> None:
    fail = run("pc_save_binary")["saveFail"]
    # 대화상자 계약: 실패한 저장은 onSave를 부르지 않는다 — 성공 문장도 오지 않는다.
    assert fail["notice"] == "PC에 저장할 준비 중…"
    assert fail["savesAfter"] == 2  # 첫 저장과 실패한 저장, 두 요청 모두 서버에 도달


def test_no_linked_computer_guides_before_any_byte_moves() -> None:
    no_pc = run("pc_save_binary")["noPc"]
    assert no_pc["notice"] == "컴퓨터를 연결하면 내 PC에 저장할 수 있습니다."
    assert no_pc["uploadsAfter"] == 3   # 앞선 세 번의 저장 시도에서만 올라갔다
    assert no_pc["savesAfter"] == 2     # 이 클릭으로는 아무것도 오르지 않았다
