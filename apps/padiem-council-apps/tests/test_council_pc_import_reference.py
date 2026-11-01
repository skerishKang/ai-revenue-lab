"""2026-11-02 — 축사·SNS 참고 글 "내 PC에서 예전 글 가져오기"가 문서까지.

The council reference picker now offers exactly the formats the tools can use:

- 텍스트(.txt·.md)는 #5895의 /api/pc/reference 읽기를 그대로 쓴다.
- 문서(.hwpx·.docx·.pdf)는 기존 소유자 검증 경로(/api/pc/file)로 원본 바이트를
  읽고, #6584의 tus 프로젝트 파일 경로로 이 앱의 프로젝트에 올린다. 완료 때
  Chat의 문서 해석 권위가 추출해 둔 본문(GET …/files/{id} → file.content)이 곧
  참고 글이 된다. 새 업로드·추출 경로는 없다.
- 구형 .hwp는 #6598과 같은 사유 코드 문자열(legacy_hwp_unsupported)과 그 문장으로,
  어떤 읽기도 부르기 전에 거절한다(#6598 미머지 — 문자열만 미리 맞춘다).
- 다른 계정의 PC 파일은 서버의 소유자 범위 404 하나로 끝난다 — 외래 id는 모르는
  id와 구분되지 않고, 화면은 조용한 안내 문장으로 답하며 아무것도 올리지 않는다.

These tests own the browser side through the shipped module harness; the tus
lane and the extraction authority stay pinned by the chat suite.
"""

from __future__ import annotations

from pathlib import Path

from _council_module import run

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
JS = (STATIC / "council-app.js").read_text(encoding="utf-8")

ACCEPT = [".hwpx", ".docx", ".txt", ".md", ".pdf", ".hwp"]


def test_the_reference_picker_offers_only_the_reference_formats() -> None:
    obs = run("pc_import")
    # 축사와 SNS의 참고 글 대화상자가 같은 형식 목록을 건다. .hwp는 목록에 남아
    # 있다 — 골랐을 때 #6598의 문장으로 안내하기 위함이다(숨기면 안내가 없다).
    assert obs["doc"]["accept"] == ACCEPT
    assert obs["snsAccept"] == ACCEPT
    # 다른 열기(사진 추가·내 PC에 저장)에는 필터를 걸지 않는다.
    assert run("pc")["accepts"][1] is None


def test_a_pc_document_becomes_a_reference_through_the_project_lane() -> None:
    obs = run("pc_import")
    doc = obs["doc"]
    # 원본 바이트는 기존 소유자 검증 경로(/api/pc/file)로만 읽는다.
    assert doc["dispatches"] == ["pc-doc-hwpx"]
    # 올리는 곳은 #6584 tus 프로젝트 파일 경로 — 이 앱이 초안을 저장하는 같은
    # 프로젝트(의원3종)다.
    assert doc["upload"]["name"] == "예전 축사.hwpx"
    assert doc["upload"]["mediaType"] == "application/hwp+zip"
    assert doc["upload"]["projectId"] == "p1"
    assert doc["upload"]["byteCount"] == 6  # HWPX는 zip — PC 파일의 PK 헤더가 그대로 갔다
    # Chat의 추출 결과가 곧 참고 글 미리보기로 붙는다.
    assert doc["preview"] == "문서에서 추출한 예전 축사 본문입니다."
    assert "GET /api/projects/p1/files/f1" in obs["endpoints"]


def test_a_legacy_hwp_pick_is_refused_with_the_6598_reason() -> None:
    obs = run("pc_import")
    hwp = obs["hwp"]
    assert hwp["status"] == "기존 HWP 파일은 아직 지원하지 않습니다."
    # 거절은 형식에 대한 것 — 어떤 읽기(파일·참조)도 부르지 않았다.
    assert hwp["dispatchesAfter"] == 1
    assert hwp["uploadsAfter"] == 1
    assert hwp["referenceReadsAfter"] == 0
    # #6598이 아직 머지 전이어도 사유 코드 문자열은 미리 맞춰 둔다 — 이 경로가
    # 같은 코드를 답하는 순간에도 같은 문장이 나온다.
    assert 'code === "legacy_hwp_unsupported"' in JS
    assert "기존 HWP 파일은 아직 지원하지 않습니다." in JS


def test_a_text_file_still_imports_through_the_reference_route() -> None:
    obs = run("pc_import")
    textMd = obs["textMd"]
    assert textMd["reads"] == [{"file_id": "pc-doc-md"}]
    assert textMd["status"] == ""
    # 문서 다음에 온 텍스트도 같은 목록에 붙는다.
    assert textMd["previews"][1] == "예전 인사말 원고입니다. 문체를 참고하세요."


def test_another_accounts_pc_file_is_refused_without_any_upload() -> None:
    obs = run("pc_import")
    foreign = obs["foreign"]
    # 서버가 소유자 범위 404로 거절한다(외래 id는 모르는 id와 같다).
    assert "GET /api/pc/file?dispatch_id=pc-file-other-account" in obs["endpoints"]
    assert foreign["status"] == (
        "이 파일은 참고 글로 읽지 못했어요. 글자가 들어 있는 문서를 골라 주세요.")
    assert foreign["dispatchesAfter"] == 2
    assert foreign["uploadsAfter"] == 1


def test_a_failed_document_upload_says_so_and_keeps_the_list() -> None:
    obs = run("pc_import")
    fail = obs["uploadFail"]
    assert fail["status"] == "문서를 프로젝트에 올리지 못했습니다. 잠시 후 다시 시도해 주세요."
    assert fail["uploadsAfter"] == 1
    # 실패한 가져오기는 목록을 늘리지 않는다 — 참고 글은 성공한 것만 담는다.
    assert len(obs["textMd"]["previews"]) == 2


def test_an_empty_extraction_never_becomes_a_reference() -> None:
    obs = run("pc_import")
    assert obs["emptyDoc"]["status"] == (
        "이 파일은 참고 글로 읽지 못했어요. 글자가 들어 있는 문서를 골라 주세요.")


def test_both_references_reach_the_prompt_in_order() -> None:
    obs = run("pc_import")
    prompt = obs["speechPrompt"]
    assert "[참고 글 1: 예전 축사.hwpx]" in prompt
    assert "문서에서 추출한 예전 축사 본문입니다." in prompt
    assert prompt.index("[참고 글 1: 예전 축사.hwpx]") < prompt.index("[참고 글 2: 예전 인사말.md]")
    assert obs["alerts"] == [] and obs["pageErrors"] == []


def test_the_document_lane_reuses_the_shared_tus_modules_of_this_app() -> None:
    # tus 공용 모듈과 프로젝트 파일 레인 어댑터는 이 앱의 사본으로 실린다 —
    # 다른 앱의 자산 경로를 향하지 않는다(#5728 사진 리사이즈 사본과 같은 규칙).
    for name in ("tus-upload.js", "project-file-upload.js"):
        assert (STATIC / name).is_file(), name
        assert f'./static/{name}"' in JS, f"the bare local URL stays the fallback: {name}"
    assert "window.PadiemProjectFileUpload" in JS
    # 새 업로드 경로가 아니다: 프로젝트 파일 tus 컬렉션은 #6584의 주소 그대로다.
    wrapper = (STATIC / "project-file-upload.js").read_text(encoding="utf-8")
    assert '"/api/projects/" + encodeURIComponent(projectId) + "/files/tus"' in wrapper
