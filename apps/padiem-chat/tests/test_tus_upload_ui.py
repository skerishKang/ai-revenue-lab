"""#6579 3단계 — 조각 업로드 화면은 한 벌이다(진행률·자동 이어 올리기·한국어 안내).

세 화면(프로젝트 파일·Chat 첨부·웹 XLSX)이 각자 tus 클라이언트를 들면 재시도
규칙과 문구가 세 벌이 된다. 이 파일은 그 금지선을 고정한다.

#7186 R2: 규칙을 "소스에 이 문자열이 있나"가 아니라 **모듈을 실제로 돌려 얻은
요청·상태**로 확인한다(`_r5_transport_upload_harness`). 남은 문자열 검사는 셋뿐이고
이유는 각 시험의 docstring에 적었다: 금지 대상의 부재 자체가 계약인 경우다.
"""

from __future__ import annotations

import re
from pathlib import Path

# #7186 R2: tus·파일 레인·첨부 역량은 모듈 실행 관찰로 검사한다.
from _r5_transport_upload_harness import observations as transport_observations

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
SHARED = "tus-upload.js"
LANES = ("project-file-upload.js", "file-lane.js", "claw-web-xlsx-sources.js")


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def test_only_the_shared_module_speaks_the_tus_protocol():
    single = transport_observations()["tus"]["single"]
    # 한 번의 업로드가 남기는 요청 순서: 한도 → 생성 → 조각들 → 결과.
    assert single["order"] == ["OPTIONS", "POST", "PATCH", "PATCH", "PATCH", "GET"]
    # 조각 요청은 tus 규격 헤더(오프셋·offset 전용 content-type·버전)를 싣는다.
    assert single["patchContentType"] == ["application/offset+octet-stream"] * 3
    assert single["patchTusResumable"] == ["1.0.0"] * 3
    assert single["patchOffsets"] == ["0", "4", "8"]
    # 생성 요청은 전체 길이와 파일 메타데이터(tus 규격 base64)를 보낸다.
    assert single["post"]["uploadLength"] == "9"
    assert single["post"]["metadata"] == {"filename": "보고서 note.txt", "filetype": "text/plain"}
    assert single["options"]["tusResumable"] == "1.0.0"


def test_no_lane_installs_a_second_tus_client():
    """레인이 tus 프로토콜을 직접 쓰지 않는 것은 **부재 자체가 계약**이다.

    외부 클라이언트를 다시 들이면 이어 올리기 지문이 브라우저 저장소에 남고,
    재시도 규칙·문구가 레인마다 한 벌씩 늘어난다. 없는 것이 곧 지켜짐이므로
    실행 관찰로는 표현할 수 없어 문자열로 남긴다(그 레인의 동작은 하네스가 검사).
    """
    for name in LANES:
        text = _read(name)
        assert "new window.tus.Upload" not in text, name
        assert "new tus.Upload" not in text, name
        assert 'application/offset+octet-stream' not in text, name


def test_shared_module_is_the_only_script_and_carries_no_persistence():
    """저장소 API와 벤더링된 클라이언트의 부재도 부재 자체가 계약이다.

    이어 올리기 지문을 브라우저 저장소에 쓰는 순간 브라우저 저장소 금지 감사
    (b62_browser_persistence_audit)가 실패한다. 쓰지 않는다는 사실은 실행해서
    관찰할 대상이 아니라 소스에 없다는 사실로만 확인된다. 반면 "스크립트가 한
    벌"은 실제 index.html이 몇 번 부르는지이므로 그대로 문자열 횟수로 센다.
    """
    html = _read("index.html")
    assert html.count('src="./tus-upload.js"') == 1
    assert "tus-js-client" not in html
    shared = _read(SHARED)
    for forbidden in ("localStorage", "sessionStorage", "indexedDB",
                      "document.cookie", "serviceWorker", "CacheStorage"):
        assert forbidden not in shared, forbidden


def test_shared_module_keeps_progress_resume_and_first_party_korean_copy():
    tus = transport_observations()["tus"]
    single = tus["single"]
    # 진행률(%)은 콜백으로 올라오고 0~100 사이를 단조 증가한다.
    percents = [percent for _, percent in single["states"]]
    assert percents[0] == 0 and percents[-1] == 100
    assert percents == sorted(percents)
    assert all(0 <= percent <= 100 for percent in percents)
    assert single["states"][0][0] == "discovering"
    assert single["states"][-1][0] == "finalizing"
    assert single["progress"][-1] == [9, 9]
    # 조각 크기는 서버가 알려 준 X-Padiem-Tus-Chunk-Max를 따른다(4+4+1).
    assert single["patchSizes"] == [4, 4, 1]
    # 끊기면 HEAD로 서버 위치를 다시 물은 뒤 "resuming" 상태로 이어 올린다.
    resume = tus["resume"]
    assert resume["order"] == ["POST", "PATCH", "HEAD", "PATCH", "PATCH", "GET"]
    assert [phase for phase, _ in resume["phases"]].count("resuming") >= 1
    assert resume["patchOffsets"] == ["0", "4", "8"]
    # 중단은 재시도 없이 첫 요청에서 끝난다.
    assert tus["abortRequests"] == ["POST"]
    # 화면이 밖으로 내보내는 오류는 전부 1차 한국어 안내이고 서버 본문 문구가 아니다.
    for branch in (tus["tooLarge"], tus["serverBody"], tus["abort"]):
        assert branch["threw"] is True
        assert branch["safe"] is True
        assert "upstream said nope" not in branch["message"]
        assert re.search(r"[가-힣]", branch["message"]), branch["message"]
    # 413은 서버가 준 한도를 바이트 표기로 안내한다.
    assert tus["tooLarge"]["message"] == "파일이 너무 커요 — 최대 1MB까지 올릴 수 있어요."
    assert tus["tooLarge"]["code"] == "request_too_large"


def test_every_lane_points_at_its_own_tus_endpoint():
    tus = transport_observations()["tus"]
    shared = tus["single"]
    # 공용 모듈은 넘겨받은 엔드포인트를 그대로 쓴다(엔드포인트를 스스로 만들지 않음).
    assert shared["options"]["url"] == "/api/chat/attachments/tus"
    assert shared["post"]["url"] == "/api/chat/attachments/tus"
    assert shared["resultCall"]["url"].startswith("https://padiem.test/api/chat/attachments/tus/")
    lane = transport_observations()["lane"]
    # Chat 첨부 레인은 자기 엔드포인트로 공용 모듈을 부른다.
    assert lane["laneTus"]["urls"][0] == "/api/chat/attachments/tus"
    assert lane["laneTus"]["methods"][0] == "POST"
    assert lane["laneTus"]["result"] == {"fileId": "file_" + "c" * 32}
    # 웹 XLSX 화면은 여전히 자기 ENDPOINT를 만들고 10MB 이하 인라인 경로를 둔다.
    web_xlsx = _read("claw-web-xlsx-sources.js")
    assert 'ENDPOINT + "/tus"' in web_xlsx
    assert "shouldUseFileLane" in web_xlsx
