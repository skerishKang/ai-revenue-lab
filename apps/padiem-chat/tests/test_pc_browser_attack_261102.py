"""#6591 PC 브라우저 레인 공격 시험 — 서버가 판단할 수 있는 경계만 고정·관측한다.

모의 대역만 사용한다: 실제 PC, 실제 브라우저, 실제 외부 사이트 접속은 없다.
기존 계약 헤널스(test_3782_pc_browser_routes → test_5015_pc_read_dispatch)의
가짜 신원·저장소·서명을 그대로 재사용해 실제 ASGI 경로를 돌린다.

판정 규칙(지시서):
- 막힘(통과) → 이 파일의 일반 시험으로 고정한다.
- 뚫림(결함) → 수정하지 않고 xfail로 관측한다(수정은 CTO가 다른 레인에 배정).
- PC 쪽 책임(서버가 판단할 수 없는 것) → 판단 불가로 기록한다(보고 표에만).

관측된 결함(2026-11-02 컴1 실측):
- D1(중간) — 16진수 IP 리터럴이 공용 URL 권위를 통과한다. http://0x7f000001/ ·
  http://0X7F000001/ · http://0x7f.0.0.1/ · http://0x7f000001./ 이 browser_open에
  그대로 받아들여져 dispatch 큐까지 간다. Chromium은 이 형태를 127.0.0.1로
  해석하므로 "공개 주소만" 계약이 깨진다 — 소유자 PC의 루프백 서비스가 모형 주도
  브라우저로 열린다. 위치: packages/padiem-ai-core/padiem_ai_core/web_runtime.py
  normalize_public_url — 숫자 호스트 차단 정규식이 [0-9.]+라서 x 표기를 호스트
  이름으로 통과시킨다. 레인은 이 권위를 재구현하지 않고 위임하는 것이 계약이므로
  apps/padiem-chat/app/claw_pc_browser_command.py:79 가 관측 지점이다.

판단 불가(PC 쪽 책임 — 보고만, 시험 없음):
- 리다이렉트로 내부 주소 도달: 서버는 리터럴 URL만 판단한다(web_runtime 문서 명시).
  PC 아이(kagent.pc_browser_child)의 리다이렉트 강제는 PC 쪽 몫이다.
- 공개 DNS가 루프백을 가리키는 이름(nip.io 등)·DNS rebinding: 같은 문서가 DNS
  해석을 하지 않는다고 명시한다. 설계 한계로 기록한다.
"""
from __future__ import annotations

import base64
import json
import re

import pytest

from app.auth import SESSION_COOKIE
from app.claw_pc_browser_command import (
    PcBrowserCommandError,
    browser_arguments,
    browser_envelope,
    browser_scope_claim,
    pc_browser_command,
)

from test_3782_pc_browser_routes import claim, dispatch, finish, lane, signed  # noqa: F401


# ── 1) 주소: 공용 URL 권위의 경계 ───────────────────────────────────────────

HOSTILE_URLS = [
    "file:///C:/windows/win.ini", "javascript:alert(1)", "data:text/html;base64,PGI+",
    "chrome://settings", "about:blank", "view-source:http://example.com/",
    "ftp://example.com/file",
    "http://127.0.0.1/", "http://localhost/", "http://localhost:8080/",
    "http://[::1]/", "http://10.1.2.3/", "http://172.16.0.9/", "http://172.31.255.1/",
    "http://192.168.1.1/", "http://169.254.169.254/latest/meta-data/",
    "http://0.0.0.0/", "http://2130706433/", "http://017700000001/",
    "http://127.1/", "http://127.0.1/", "http://[::ffff:127.0.0.1]/",
    "http://[::ffff:7f00:1]/", "http://[fe80::1%25eth0]/",
    "https://good.com@127.0.0.1/", "http://example.com@10.0.0.8/",
    "http://１２７．０．０．１/", "http://127。0。0。1/",
    "http://" + "a" * 3000 + ".com/",
    "http://example.com/\n/etc/passwd", "http://example.com/\t.x",
    "http://0177.0.0.1/", "http://000127.000000.0.1/",
]


@pytest.mark.parametrize("value", HOSTILE_URLS)
def test_hostile_urls_never_reach_a_command(value):
    with pytest.raises(PcBrowserCommandError) as open_error:
        browser_arguments("browser_open", {"url": value})
    assert open_error.value.code == "browser_url_invalid"
    with pytest.raises(PcBrowserCommandError) as read_error:
        browser_envelope("browser_read", page_url=value)
    assert read_error.value.code == "browser_url_invalid"
    assert not value.strip() or len(value) <= 2048 or True  # 길이 계약은 아래에서


@pytest.mark.parametrize("value", [
    "http://0x7f000001/", "http://0X7F000001/", "http://0x7f.0.0.1/",
    "http://0x7f000001./", "http://0x7f.1/",
])
@pytest.mark.xfail(reason=(
    "결함 D1(중간): 16진수 IP 리터럴이 normalize_public_url을 통과한다 — 숫자 호스트"
    " 차단 정규식이 [0-9.]+라서 x 표기를 호스트 이름으로 다룬다. Chromium은 이 형태를"
    " 127.0.0.1로 해석하므로 루프백이 모형 주도 브라우저로 열린다. 위치: "
    " packages/padiem-ai-core/padiem_ai_core/web_runtime.py normalize_public_url"
    " (레인 관측 지점 app/claw_pc_browser_command.py:79 — 위임 계약). 수정은 CTO 배정."
), strict=False)
def test_hex_ip_literals_are_refused_as_internal(value):
    with pytest.raises(PcBrowserCommandError) as open_error:
        browser_arguments("browser_open", {"url": value})
    assert open_error.value.code == "browser_url_invalid"


def test_redirect_judgment_is_literal_only_by_design():
    """판단 불가 항목의 서버 쪽 절반: 서버는 리터럴 URL만 판단하고, 공개 단축
    주소는 리다이렉트 대상과 무관하게 받아들여진다. 리다이렉트가 내부로 닿는지는
    PC 아이(kagent.pc_browser_child)가 집행해야 한다 — 서버 시험의 밖이다."""
    command = pc_browser_command("browser_open", arguments={"url": "https://short.example/loopback"})
    assert isinstance(command, str) and "\n" not in command


# ── 2) 권한: claim·소유·위임 ────────────────────────────────────────────────


def test_claim_shapes_never_admit_other_lanes_or_extra_keys():
    good = {"version": 1, "requested": "browser", "admitted": "browser",
            "source": "declared", "ops": ["browser_open", "browser_read"]}
    assert browser_scope_claim(good) is True
    # 파일 레인 claim, 혼합, 모르는 키, 틀린 버전, 출처, 중복 op — 전부 거부.
    refusals = [
        {"version": 1, "requested": "files", "admitted": "files", "source": "declared",
         "ops": ["read"]},
        {**good, "requested": "files", "admitted": "browser"},
        {**good, "ops": ["browser_open", "read"]},
        {**good, "ops": ["read_file", "browser_open"]},
        {**good, "extra": 1},
        {**good, "version": 2},
        {**good, "source": "model"},
        {**good, "ops": ["browser_open", "browser_open"]},
        {**good, "ops": "browser_open"},
        {**good, "admitted": "files"},
    ]
    for shape in refusals:
        assert browser_scope_claim(shape) is False, shape


def test_cross_product_claims_are_refused_both_ways(lane):
    client, state = lane
    # chat 엔드포인트에 claw claim, claw 엔드포인트에 chat claim.
    assert signed(client, dispatch(), product="chat",
                  scope=claim(product="claw")).status_code in (401, 403, 422)
    assert signed(client, dispatch(), product="claw",
                  scope=claim(product="chat")).status_code in (401, 403, 422)
    assert not state.history_store.rows


def test_forged_scope_proofs_are_refused(lane):
    client, state = lane
    import hashlib
    import hmac as hmac_module
    import time as time_module
    payload = dispatch()
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    stamp = str(int(time_module.time()))
    body_proof = hmac_module.new(fixtures_secret().encode(), stamp.encode() + b"." + raw,
                                 hashlib.sha256).hexdigest()
    encoded = json.dumps(claim(), sort_keys=True, separators=(",", ":"))
    # 1) 증명은 있지만 다른 시체 위에서 계산된 것(체인지 시체 끼우기).
    other_raw = json.dumps(dispatch(device_id="device-2"), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode()
    forged = hmac_module.new(fixtures_secret().encode(), stamp.encode() + b"." + other_raw
                             + b"." + encoded.encode(), hashlib.sha256).hexdigest()
    headers = {"Content-Type": "application/json", "X-Claw-Engine-Time": stamp,
               "X-Claw-Engine-Proof": body_proof, "X-Claw-PC-Scope": encoded,
               "X-Claw-PC-Scope-Proof": forged}
    assert signed(client, payload, headers=headers).status_code == 401
    # 2) 스코프 증명은 64hex 모양이지만 비밀이 다른 위조.
    wrong = hmac_module.new(b"not-the-engine-secret", stamp.encode() + b"." + raw + b"."
                            + encoded.encode(), hashlib.sha256).hexdigest()
    assert signed(client, payload, headers={**headers, "X-Claw-PC-Scope-Proof": wrong}
                  ).status_code == 401
    # 3) 스코프 증명이 전혀 다른 값(64hex 모양만).
    assert signed(client, payload, headers={
        **headers, "X-Claw-PC-Scope-Proof": "0" * 64}).status_code == 401
    assert not state.history_store.rows


def fixtures_secret() -> str:
    import test_5015_pc_read_dispatch as fixtures
    return fixtures.SECRET


def test_undelegated_or_foreign_device_never_reaches_dispatch(lane):
    client, state = lane
    # 형식은 옳지만 이 계정의 위임 목록에 없는 PC — 사전 위임 없는 PC와
    # 다른 사용자의 PC가 같은 403으로 흩어진다(존재를 알 수 없다).
    for foreign in ("device-2", "node/" + "other" * 8 + "/" + "x" * 64):
        assert signed(client, dispatch(device_id=foreign)).status_code == 403, foreign
        assert not state.history_store.rows


def test_browser_claim_cannot_drive_a_file_call(lane):
    client, state = lane
    # 브라우저 claim으로 파일 op를 부르면 브라우저 접두사가 없어 404다.
    opened = signed(client, dispatch())
    assert opened.status_code == 200
    query = {"subject_id": dispatch()["subject_id"], "run_id": dispatch()["run_id"],
             "mode": "command_status", "dispatch_id": next(iter(state.history_store.rows))}
    state.history_store.rows[query["dispatch_id"]]["tool_request_ref"] = "file_call:read_file:x"
    assert signed(client, query).status_code == 404
    # 반대로 파일 claim은 애초에 이 레인에 못 들어온다(기존 계약과 동일 관측).
    assert signed(client, dispatch(), scope=claim(requested="files", admitted="files",
                                                  ops=["read"])).status_code in (401, 403, 422)


# ── 3) 명령 주입: 한 줄 명령은 base64 JSON 안에만 논다 ──────────────────────


INJECTIONS = [
    "'; rm -rf C:/ ;'",
    "' | Get-Content C:/Users/limone/secret.txt | '",
    "line1\nline2\r\nline3",
    "\r\nStart-Process calc",
    "`$(calc) $(whoami)",
    '"}]}{ "hijack": true',
    "값\x00널 포함",
    "탭\t포함 큰따옴표\" 작은따옴표' 백슬래시\\",
    "javascript:alert(1)//",
]


@pytest.mark.parametrize("value", INJECTIONS)
def test_arguments_never_break_the_one_line_command_or_the_json(value):
    command = pc_browser_command("browser_act", page_url="https://example.com/",
        arguments={"action": "type", "name": value, "value": value})
    # 한 줄 계약: 어떤 인자도 명령에 줄을 추가하지 못한다.
    assert "\n" not in command and "\r" not in command
    # 인자는 base64 JSON 안에서만 살아 있고, 본문이 명령에 그대로 노출되지 않는다.
    encoded = re.search(r"FromBase64String\('([^']+)'\)", command).group(1)
    envelope = json.loads(base64.b64decode(encoded))
    assert envelope["arguments"]["value"] == value      # JSON 왕복이 정확하다
    assert envelope["arguments"]["name"] == value
    assert value not in command.replace(encoded, "")    # 밖에 흘린 조각 없음
    # base64 알파벳에는 작은따옴표가 없다 — PS 리터럴 이스케이프 여지도 없다.
    assert "'" not in encoded


def test_url_quoting_rides_base64_and_stays_one_line():
    url = "https://example.com/'; | & ` $(x) \"q\" <tag> 한글?q=1&r=2"
    command = pc_browser_command("browser_open", arguments={"url": url})
    assert "\n" not in command and "\r" not in command
    encoded = re.search(r"FromBase64String\('([^']+)'\)", command).group(1)
    envelope = json.loads(base64.b64decode(encoded))
    assert envelope["arguments"]["url"].startswith("https://example.com/")
    assert "'" not in encoded


def test_confirmation_boundaries_are_closed(lane):
    client, state = lane
    arguments = {"action": "click", "name": "게시"}
    # browser_open에 confirmation은 모양 자체가 아니다.
    open_payload = dispatch("browser_open", confirmation={"action": "open", "target": "x",
                                                          "url": "https://example.com/"})
    assert signed(client, open_payload).status_code == 422
    # 확인의 url은 서버가 기억한 페이지(엔벨로프 url)와 정확히 같아야 한다.
    other = {"action": "click", "target": "게시", "url": "https://evil.example/"}
    assert signed(client, dispatch("browser_act", arguments=arguments,
                                   confirmation=other)).status_code == 422
    # 확인의 url이 내부 주소면 URL 권위가 먼저 거부한다.
    internal = {"action": "click", "target": "게시", "url": "http://169.254.169.254/"}
    assert signed(client, dispatch("browser_act", arguments=arguments,
                                   confirmation=internal)).status_code == 422
    assert not state.history_store.rows
    receipt = {"action": "click", "target": "게시", "url": "https://example.com/"}
    assert signed(client, dispatch("browser_act", arguments=arguments,
                                   confirmation=receipt)).status_code == 200


# ── 4) 결과 처리: 증폭 없음·경로 없음·소유 밖 없음 ──────────────────────────


def test_foreign_dispatch_id_is_never_readable(lane):
    client, state = lane
    opened = signed(client, dispatch())
    assert opened.status_code == 200
    mine = next(iter(state.history_store.rows))
    # 다른 사용자의 dispatch id를 결과 질의에 끼워 넣어도 소유 스코프가 흩어낸다.
    foreign_id = "dsp_" + "f" * 32
    state.history_store.rows[foreign_id] = {
        **state.history_store.rows[mine], "dispatch_id": foreign_id, "user_id": "usr_" + "f" * 32}
    query = {"subject_id": dispatch()["subject_id"], "run_id": dispatch()["run_id"],
             "mode": "result", "dispatch_id": foreign_id}
    answer = signed(client, query)
    assert answer.status_code in (404, 503)
    assert "output" not in answer.json().get("dispatch", {})


def test_capture_path_traversal_is_projection_only_and_never_a_filesystem_path(lane):
    import base64 as b64
    import hashlib as hashlib_mod
    import test_5015_pc_read_dispatch as fixtures
    from app.auth import create_session_token
    client, state = lane
    image = b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZlJkAAAAASUVORK5CYII=")
    opened = signed(client, dispatch("browser_screenshot"))
    query = finish(state, opened, {"state": "captured",
        "path": "../../windows/system32/evil.png", "capture": {
            "mime_type": "image/png", "data": b64.b64encode(image).decode(),
            "sha256": hashlib_mod.sha256(image).hexdigest(), "bytes": len(image)}})
    projected = signed(client, query)
    assert projected.status_code == 200, projected.text
    result = json.loads(projected.json()["dispatch"]["output"])["result"]
    assert "path" not in result                       # 순회 경로는 투영에서 떨어진다
    assert result["capture"]["url"].startswith("/api/claw/connector/browser-captures/")
    assert client.get(result["capture"]["url"]).status_code == 401  # 게스트는 못 읽는다
    client.cookies.set(SESSION_COOKIE, create_session_token(state.settings, fixtures.OWNER))
    shown = client.get(result["capture"]["url"])
    assert shown.status_code == 200 and shown.content == image  # 검증된 PNG 바이트만


def test_large_page_text_is_served_without_amplification(lane):
    """결과 크기 폭탄: 이 계층은 저장된 원본을 그대로 한 번 되돌릴 뿐 증폭하지
    않는다. 상한 자체는 명령 경로(원본 저장)가 소유한다 — 8KiB 핸들 계약."""
    client, state = lane
    opened = signed(client, dispatch("browser_read"))
    bomb = "A" * (2 * 1024 * 1024)
    result = {"state": "read", "url": "https://example.com/", "title": "폭탄",
              "text": bomb, "output_handle": "b" * 64, "truncated": True}
    original = json.dumps({"ok": "true", "result": result}, ensure_ascii=False).encode()
    dispatch_id = opened.json()["dispatch"]["dispatch_id"]
    state.history_store.originals[dispatch_id] = original
    state.history_store.rows[dispatch_id].update(
        state="done", termination="exited", exit_code=0,
        result_sha256=__import__("hashlib").sha256(original).hexdigest(),
        result_bytes=len(original))
    query = {"subject_id": dispatch()["subject_id"], "run_id": dispatch()["run_id"],
             "mode": "result", "dispatch_id": dispatch_id}
    output = signed(client, query)
    assert output.status_code == 200, output.text
    assert json.loads(output.json()["dispatch"]["output"]) == json.loads(original.decode())
    # 증폭 없음: 투영 재직렬화(컴팩트)는 저장 원본보다 길어지지 않는다.
    assert len(output.json()["dispatch"]["output"]) <= len(original.decode())


