"""#6579 3단계 — 조각 업로드 화면은 한 벌이다(진행률·자동 이어 올리기·한국어 안내).

세 화면(프로젝트 파일·Chat 첨부·웹 XLSX)이 각자 tus 클라이언트를 들면 재시도
규칙과 문구가 세 벌이 된다. 이 파일은 그 금지선만 고정한다: tus 업로드 객체는
공용 모듈 한 곳에서만 만들고, 각 화면은 자기 엔드포인트와 결과 검증만 갖는다.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SHARED = "tus-upload.js"
LANES = ("project-file-upload.js", "file-lane.js", "claw-web-xlsx-sources.js")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_only_the_shared_module_constructs_a_tus_upload():
    shared = _read(SHARED)
    assert "new window.tus.Upload" in shared
    for name in LANES:
        text = _read(name)
        assert "new window.tus.Upload" not in text, name
        assert "new tus.Upload" not in text, name


def test_shared_module_is_loaded_once_after_the_vendored_client():
    html = _read("index.html")
    assert html.count('src="./tus-upload.js"') == 1
    assert html.index('src="./tus-js-client-4.3.1.min.js"') < html.index('src="./tus-upload.js"')


def test_shared_module_keeps_progress_resume_and_first_party_korean_copy():
    shared = _read(SHARED)
    # 진행률(%)과 이어 올리기 판단, 자동 재시도 지연이 한 곳에 있다.
    assert "percent" in shared
    assert "onShouldRetry" in shared
    assert "retryDelays" in shared
    assert "resuming" in shared
    # 화면이 서버 본문 문구를 그대로 노출하지 않는다(1차 한국어 안내만).
    for phrase in ("다시 시도", "올릴 수 없어요", "끊겼어요"):
        assert phrase in shared
    assert "uiMessageSafe" in shared


def test_every_lane_points_at_its_own_tus_endpoint():
    assert "/api/projects/" in _read("project-file-upload.js")
    assert "/api/chat/attachments/tus" in _read("file-lane.js")
    web_xlsx = _read("claw-web-xlsx-sources.js")
    assert 'ENDPOINT + "/tus"' in web_xlsx
    # 웹 XLSX는 10MB 이하 인라인 경로를 그대로 둔다.
    assert "shouldUseFileLane" in web_xlsx
