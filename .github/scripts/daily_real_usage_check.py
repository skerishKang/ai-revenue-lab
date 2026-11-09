#!/usr/bin/env python3
"""#6724 1차: 매일 자동으로 실제 사용 흐름을 점검한다 (대표 승인 2026-11-09).

GitHub 러너에서 운영 사이트(chat.padiem.net)를 실제 사용자처럼 한 바퀴 돌고,
흐름별 판정을 "응답이 왔다"가 아니라 실제 결과값으로 한다:

  1. chat_turn      로그인 → 채팅 1턴        : 답 글자 수신(앞 10글자 기록)
  2. pc_read        PC 파일 읽기(커넥터 경로) : 실제 파일 내용 수신(앞 20자)
  3. voice_relay    실시간 음성 전사          : 전사 글자 수신(앞 10글자)
  4. relogin        로그아웃 → 다시 로그인    : 대화 목록 재로드

캘린더 흐름은 대표 결정으로 1차에서 뺀다. 튜토리얼 자동 생성은 2차다.

판정·보안 계약:
  - 자격 증명은 GitHub secrets/vars 로만 들어오고 절대 출력하지 않는다.
  - 결과값은 각 흐름이 정한 앞 자리(10/20자)만 남긴다. 그 외 본문·헤더·쿠키는
    로그에 남지 않는다.
  - 모든 코드는 소문자·숫자·밑줄뿐인 안전 코드다. 값·토큰은 코드에 섞지 않는다.
  - 자격 증명이 아예 없으면 FAIL 이 아니라 SKIPPED 로 기록한다(#6720 계약):
    경보는 실제 흐름 실패에만 울린다.
  - 시험 계정·토큰은 QA 전용이다. 이 점검은 컴2(운영 서버)에서 실행하지 않는다.

실패 시 0이 아닌 종료 코드로 끝난다. 워크플로가 실패로 끝나면 기존
nightly-qa-failure-issue 수집기가 이슈를 열거나 기존 이슈에 코멘트한다.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent.parent / "scripts" / "ops"))

from b62_live_logout_reuse_check import (  # noqa: E402
    CONVERSATIONS,
    LOGIN,
    LOGOUT,
    ORIGIN,
    STATUS,
    CanaryError,
    bounded_call,
    error_code,
)
from post_deploy_real_chat_smoke import (  # noqa: E402
    ORCHESTRATION,
    QA_PASSWORD_ENV,
    QA_USERNAME_ENV,
    conversation_id,
    decide,
    turn_payload,
)
from pc_read_measure import send_probe  # noqa: E402
import daily_usage_browser_checks as browser_checks  # noqa: E402

PC_TOKEN_ENV = "PADIEM_QA_PC_TOKEN"
PC_READ_PATH_ENV = "PADIEM_QA_PC_READ_PATH"
PC_READ_PATH_DEFAULT = "C:/Windows/win.ini"

VOICE_LIVE_TOKEN = "/api/voice/live-token"
VOICE_RELAY_WS_PATH = "/api/voice/relay"
PCM_MIME = "audio/pcm;rate=16000"
SAMPLE_RATE = 16000
VOICE_TEXT = "안녕하세요. 파디엠 실사용 점검 음성입니다."
VOICE_SECONDS = 5.0
CHUNK_SECONDS = 0.2
SETUP_WAIT_SECONDS = 10.0
TRANSCRIPT_WAIT_SECONDS = 25.0
HEAD_CHAT = 10
HEAD_PC = 20
HEAD_VOICE = 10

# 2차 브라우저 흐름. 판정은 daily_usage_browser_checks 의 순수 함수가 한다.
BROWSER_FLOWS = ("browser_chat", "browser_claw", "browser_stamp")
EXPECTED_HEAD_ENV = "PADIEM_EXPECTED_HEAD_SHA"
BROWSER_CAPTURE_DIR_ENV = "PADIEM_USAGE_CAPTURE_DIR"
BROWSER_CAPTURE_DIR_DEFAULT = "usage-browser-captures"
METRICS_PATH_ENV = "PADIEM_USAGE_METRICS_PATH"
METRICS_PATH_DEFAULT = "usage-metrics.json"

_HEAD_SANITIZE = re.compile(r"[^\x20-\x7e가-힣ㄱ-ㅎㅏ-ㅣ]")


def _head(value: str | None, limit: int) -> str:
    """결과값 앞부분만. 제어 문자·줄바꿈은 공백으로 바꾸고 길이를 제한한다."""
    if not isinstance(value, str) or not value.strip():
        return ""
    flat = _HEAD_SANITIZE.sub(" ", value).strip()
    return flat[:limit]


class Flow:
    """한 흐름의 판정 기록. 값은 head 로만 남긴다."""

    def __init__(self, name: str):
        self.name = name
        self.verdict = "FAIL"
        self.code = "flow_not_run"
        self.head = ""
        self.elapsed_ms = 0

    def pass_(self, head: str = "", code: str = "none") -> None:
        self.verdict, self.code, self.head = "PASS", code, head

    def skip(self, code: str) -> None:
        self.verdict, self.code, self.head = "SKIPPED", code, ""

    def fail(self, code: str) -> None:
        self.verdict, self.code, self.head = "FAIL", code, ""

    def line(self) -> str:
        return (f"USAGE_FLOW name={self.name} verdict={self.verdict} "
                f"elapsed_ms={self.elapsed_ms} code={self.code} head={self.head}")


def _credential_verdict() -> tuple[str, str]:
    username = os.environ.get(QA_USERNAME_ENV, "")
    password = os.environ.get(QA_PASSWORD_ENV, "")
    if not username or not password:
        return "SKIPPED", "qa_credential_missing"
    return "PRESENT", "none"


def _login(opener) -> str:
    """로그인하고 세션 쿠키 값을 돌려준다. 값은 절대 출력하지 않는다."""
    username = os.environ.get(QA_USERNAME_ENV, "")
    password = os.environ.get(QA_PASSWORD_ENV, "")
    status, body, cookie = bounded_call(
        opener, LOGIN, method="POST",
        payload={"identifier": username, "password": password},
    )
    if status != 200 or body.get("ok") is not True or not cookie:
        code = error_code(body) if isinstance(body, dict) else "no_json_body"
        raise CanaryError(f"login_refused_http_{status}_{code}")
    status, state, _ = bounded_call(opener, STATUS, cookie=cookie)
    if status != 200 or state.get("authenticated") is not True:
        raise CanaryError("session_unverified")
    return cookie


# ------------------------------------------------------------------ flow 1
def flow_chat_turn(flow: Flow, opener) -> str | None:
    """로그인 → 채팅 1턴. 답 글자를 실제로 받는다(앞 10글자 기록)."""
    cookie = _login(opener)
    status, payload, _ = bounded_call(
        opener, ORCHESTRATION, method="POST", payload=turn_payload(),
        timeout=120, cookie=cookie,
    )
    verdict, code = decide(status, payload)
    if verdict == "FAIL":
        flow.fail(code)
        return None
    answer = payload.get("answer") if isinstance(payload, dict) else None
    # 429/503 상한은 기존 계약대로 통과로 기록하되 코드를 남긴다.
    flow.pass_(_head(answer, HEAD_CHAT), code=code)
    return conversation_id(payload)


# ------------------------------------------------------------------ flow 2
def flow_pc_read(flow: Flow) -> None:
    """커넥터 경로 pc_read. 실제 파일 내용을 받는다(앞 20자 기록)."""
    token = os.environ.get(PC_TOKEN_ENV, "")
    if not token:
        # #6720 계약: 자격이 없는 것은 건너뜀으로 기록한다. 경보 대상이 아니다.
        flow.skip("pc_token_missing")
        return
    path = os.environ.get(PC_READ_PATH_ENV, "") or PC_READ_PATH_DEFAULT
    probe = send_probe(token, path)
    if probe.get("error"):
        flow.fail(f"pc_read_transport_{probe['error']}")
        return
    if probe.get("http_status") != 200:
        flow.fail(f"pc_read_http_{probe.get('http_status')}")
        return
    if probe.get("call_status") != "completed":
        flow.fail(f"pc_read_status_{probe.get('call_status')}_{probe.get('call_code')}")
        return
    head = _head(probe.get("content_head20"), HEAD_PC)
    if not head:
        flow.fail("pc_read_empty_content")
        return
    flow.pass_(head)


# ------------------------------------------------------------------ flow 3
def _tts_pcm16k() -> bytes:
    """한국어 음성(gTTS) → 16kHz mono s16le PCM. 실패는 안전 코드로만."""
    if shutil.which("ffmpeg") is None:
        raise CanaryError("voice_ffmpeg_missing")
    try:
        from gtts import gTTS
    except ImportError:
        raise CanaryError("voice_tts_package_missing")
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = os.path.join(tmp, "qa.mp3")
        raw = os.path.join(tmp, "qa.pcm")
        gTTS(text=VOICE_TEXT, lang="ko").save(mp3)
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", mp3, "-ar", str(SAMPLE_RATE),
             "-ac", "1", "-f", "s16le", "-acodec", "pcm_s16le", raw],
            capture_output=True, timeout=60,
        )
        if done.returncode != 0 or not os.path.exists(raw):
            raise CanaryError("voice_tts_convert_failed")
        with open(raw, "rb") as handle:
            return handle.read()


def _merge_chunk(acc: str, chunk: str) -> str:
    """브라우저와 같은 병합: 누적이거나 이어지거나 붙인다."""
    if not chunk:
        return acc
    if not acc:
        return chunk
    if chunk.startswith(acc):
        return chunk
    if acc.endswith(chunk):
        return acc
    return acc + chunk


async def _relay_transcribe(cookie: str, live: dict, pcm: bytes) -> tuple[str, int]:
    """릴레이 WS 로 음성을 보내고 전사 글자를 받는다. (전사, 닫힘 코드)."""
    import websockets

    setup = {
        "generationConfig": {"responseModalities": list(live.get("response_modalities", []))},
        "realtimeInputConfig": {"automaticActivityDetection":
                                {"silenceDurationMs": live.get("vad_silence_ms", 500)}},
        "inputAudioTranscription": {"languageCodes": [],
                                    "mode": live.get("input_audio_transcription_mode", "")},
    }
    # Google answers the setup with {"setupComplete": {}} — an EMPTY message
    # object, which is falsy in Python. Presence of the key is the completion
    # fact (the same test the browser makes); a truthiness test silently
    # discarded the completed setup and made every healthy relay look broken
    # (run 42638392269). The same trap applies to inputTranscription.finished.
    setup_done = lambda frame: isinstance(frame, dict) and "setupComplete" in frame
    chunk_bytes = int(SAMPLE_RATE * CHUNK_SECONDS) * 2
    chunks = [pcm[i:i + chunk_bytes] for i in range(0, len(pcm), chunk_bytes)]
    headers = {"Origin": ORIGIN, "User-Agent": "PADIEM-QA-real-usage-check/1.0"}
    if cookie:
        headers["Cookie"] = f"padiem_session={cookie}"
    url = ORIGIN.replace("https://", "wss://") + VOICE_RELAY_WS_PATH
    closed_code = 0

    async with _connect_ws(url, headers) as ws:
        await ws.send(json.dumps({"setup": setup}))
        deadline = time.monotonic() + SETUP_WAIT_SECONDS
        frame = None
        while time.monotonic() < deadline:
            try:
                frame = await _recv(ws, max(0.5, deadline - time.monotonic()))
            except Exception:
                break
            if frame is not None and setup_done(frame):
                break
            frame = None
        if frame is None:
            return "", closed_code or -1
        for chunk in chunks:
            await ws.send(json.dumps({"realtimeInput": {"mediaChunks": [
                {"mimeType": PCM_MIME,
                 "data": base64.b64encode(chunk).decode("ascii")}]}}))
            await asyncio.sleep(CHUNK_SECONDS)
        await ws.send(json.dumps({"realtimeInput": {"audioStreamEnd": True}}))

        transcript = ""
        deadline = time.monotonic() + TRANSCRIPT_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                frame = await _recv(ws, max(0.5, deadline - time.monotonic()))
            except Exception:
                break
            if frame is None:
                break
            content = frame.get("serverContent") if isinstance(frame, dict) else None
            if isinstance(content, dict):
                final = content.get("inputTranscription")
                if isinstance(final, dict) and isinstance(final.get("text"), str):
                    transcript = _merge_chunk(transcript, final["text"].strip())
                if (isinstance(final, dict) and "finished" in final and transcript.strip()):
                    break
                if content.get("turnComplete") and transcript.strip():
                    break
        return transcript.strip(), closed_code


def _connect_ws(url: str, headers: dict):
    """릴레이 연결자(connector)를 돌려준다. 여는 일은 호출부의 ``async with`` 다.

    ``websockets.connect`` 자체가 비동기 컨텍스트 매니저인 연결자이므로 이
    함수는 await 해서 넘기면 안 된다. ``async def`` 로 두면 ``async with`` 가
    연결자 대신 코루틴을 받아 매 실행
    ``TypeError: 'coroutine' object does not support the asynchronous context
    manager protocol`` 로 죽는다(실행 42664572275가 보고한
    voice_relay_transport_error_TypeError). 연결자를 그대로 넘긴다.
    """
    import websockets
    try:
        return websockets.connect(url, additional_headers=headers, max_size=2**22)
    except TypeError:
        # websockets < 14 는 헤더 인자 이름이 extra_headers 다. 연결자는 만들 때
        # 인자를 검사하므로 여기서 갈라도 실제 연결 전에 결정된다.
        return websockets.connect(url, extra_headers=headers, max_size=2**22)


async def _recv(ws, timeout: float) -> dict | None:
    """프레임 하나를 JSON 으로. 닫히면 닫힘 코드를 전역 대신 예외로 전달한다."""
    message = await asyncio.wait_for(ws.recv(), timeout=timeout)
    if isinstance(message, bytes):
        message = message.decode("utf-8", "replace")
    try:
        data = json.loads(message)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _voice_flow(cookie: str, live: dict, pcm: bytes) -> tuple[str, int]:
    try:
        return await _relay_transcribe(cookie, live, pcm)
    except Exception as exc:
        code = getattr(exc, "rcvd", None)
        close_code = getattr(code, "code", 0) or getattr(exc, "code", 0)
        if isinstance(close_code, int) and close_code:
            return "", close_code
        raise


def flow_voice(flow: Flow, cookie: str) -> None:
    """실시간 음성 전사. 전사 글자를 실제로 받는다(앞 10글자 기록)."""
    status, payload, _ = bounded_call(
        flow_opener(), VOICE_LIVE_TOKEN, method="POST", payload={},
        cookie=cookie, timeout=25,
    )
    if status == 401 or status == 403:
        flow.fail(f"voice_live_token_http_{status}_{error_code(payload)}")
        return
    if status == 503:
        flow.fail(f"voice_stt_unavailable_{error_code(payload)}")
        return
    if status != 200:
        flow.fail(f"voice_live_token_http_{status}_{error_code(payload)}")
        return
    live = payload.get("session") if isinstance(payload, dict) else None
    if not isinstance(live, dict) or not live.get("input_audio_transcription_mode"):
        flow.fail("voice_live_config_unexpected")
        return
    try:
        pcm = _tts_pcm16k()
    except CanaryError as exc:
        flow.fail(exc.public_code)
        return
    try:
        transcript, close_code = asyncio.run(_voice_flow(cookie, live, pcm))
    except TimeoutError:
        flow.fail("voice_relay_timeout")
        return
    except Exception as exc:
        # The exception class names the failure layer (handshake status, DNS,
        # TLS, protocol); the scrubbed message fragment says which. Neither
        # carries a header, cookie, token or the relay URL's value, and the
        # whitespace collapse keeps the USAGE_FLOW line parseable.
        detail = " ".join(str(exc).split())[:120].replace("padiem_session=", "session=")
        flow.fail(f"voice_relay_transport_error_{type(exc).__name__}_{detail}")
        return
    if close_code in (4401, 4503, 4500, 4429):
        flow.fail(f"voice_relay_closed_{close_code}")
        return
    if close_code not in (0, 1000, 1001) and not transcript:
        flow.fail(f"voice_relay_closed_{close_code}")
        return
    if not transcript:
        flow.fail("voice_transcript_empty")
        return
    flow.pass_(_head(transcript, HEAD_VOICE))


_OPENER = None


def flow_opener():
    global _OPENER
    if _OPENER is None:
        from urllib.request import build_opener
        _OPENER = build_opener()
    return _OPENER


# ------------------------------------------------------------------ flow 4
def flow_relogin(flow: Flow, old_cookie: str, saved_conversation: str | None) -> None:
    """로그아웃 → 다시 로그인 → 대화 목록 재로드."""
    status, body, _ = bounded_call(
        flow_opener(), LOGOUT, method="POST", payload={}, cookie=old_cookie)
    if status != 200 or body.get("ok") is not True:
        flow.fail(f"logout_http_{status}_{error_code(body)}")
        return
    status, state, _ = bounded_call(flow_opener(), STATUS, cookie=old_cookie)
    if status == 200 and state.get("authenticated") is True:
        flow.fail("logout_session_still_authenticated")
        return
    new_cookie = _login(flow_opener())
    status, listing, _ = bounded_call(flow_opener(), CONVERSATIONS, cookie=new_cookie)
    if status != 200:
        flow.fail(f"conversations_http_{status}_{error_code(listing)}")
        return
    items = None
    for key in ("conversations", "items", "results"):
        candidate = listing.get(key) if isinstance(listing, dict) else None
        if isinstance(candidate, list):
            items = candidate
            break
    if items is None:
        flow.fail("conversations_unexpected_shape")
        return
    flow.pass_(f"count={len(items)}")
    if saved_conversation:
        try:
            bounded_call(flow_opener(), CONVERSATIONS + "/" + saved_conversation,
                         method="DELETE", cookie=new_cookie)
        except Exception:
            pass


# ------------------------------------------------------------------ report
def _summary(flows: list[Flow]) -> str:
    rows = "\n".join(
        f"| {f.name} | {f.verdict} | {f.elapsed_ms} | {f.head or '-'} | {f.code} |"
        for f in flows)
    return ("| 흐름 | 판정 | 소요(ms) | 결과값 앞부분 | 코드 |\n"
            "|---|---|---|---|---|\n" + rows + "\n")


def flow_browser(flows: list[Flow], cookie: str) -> tuple[dict, list[str]]:
    """브라우저 3흐름. Playwright 가 없으면 FAIL 이 아니라 SKIPPED 다."""
    by_name = {flow.name: flow for flow in flows}
    if not cookie:
        for name in BROWSER_FLOWS:
            by_name[name].skip("no_session_from_flow_1")
        return {}, []
    head_version = os.environ.get(EXPECTED_HEAD_ENV, "")[:8]
    out_dir = os.environ.get(BROWSER_CAPTURE_DIR_ENV, "") or BROWSER_CAPTURE_DIR_DEFAULT
    try:
        results = browser_checks.run_browser_flows(
            cookie=cookie,
            out_dir=out_dir,
            head_version=head_version,
            username=os.environ.get(QA_USERNAME_ENV, ""),
        )
    except ImportError:
        for name in BROWSER_FLOWS:
            by_name[name].skip("playwright_missing")
        return {}, []
    except Exception as exc:
        # 실행기 자체가 죽으면 층 이름만 남긴다(값·쿠키 없음).
        for name in BROWSER_FLOWS:
            by_name[name].fail(f"browser_runner_error_{type(exc).__name__}")
        return {}, []
    captures: list[str] = []
    for name in BROWSER_FLOWS:
        payload = results.get(name) or {}
        flow = by_name[name]
        flow.verdict = payload.get("verdict", "FAIL")
        flow.code = payload.get("code", "browser_flow_missing")
        flow.head = payload.get("head", "")
        flow.elapsed_ms = int(payload.get("elapsed_ms", 0))
        captures.extend(payload.get("captures", []))
        # 허용 목록 밖 콘솔 오류는 안전 코드뿐이다(값·URL 쿼리 없음).
        for code in (payload.get("console_errors") or [])[:3]:
            print(f"USAGE_BROWSER name={name} console_error={code}")
    return results, captures


def _recent_history() -> dict[str, list[int]]:
    """직전 실행들의 흐름별 소요 ms. 없으면 빈 사전(경고 없음)."""
    if not os.environ.get("GITHUB_RUN_ID"):
        return {}
    return browser_checks.fetch_recent_flow_durations(
        repo=os.environ.get("GITHUB_REPOSITORY", ""),
        workflow_file="daily-real-usage-check.yml",
        before_run_id=os.environ.get("GITHUB_RUN_ID", ""),
        token=os.environ.get("GITHUB_TOKEN", ""),
    )


def _write_metrics(flows: list[Flow], captures: list[str], warnings: list[str],
                   history: dict[str, list[int]]) -> None:
    """흐름별 소요 ms 를 JSON 으로 남긴다. 다음 날 느려짐 비교의 입력이다."""
    path = os.environ.get(METRICS_PATH_ENV, "") or METRICS_PATH_DEFAULT
    payload = {
        "schema": "padiem-daily-usage-metrics/1",
        "flows": {flow.name: {"verdict": flow.verdict, "code": flow.code,
                              "elapsed_ms": flow.elapsed_ms, "head": flow.head}
                  for flow in flows},
        "captures": list(captures),
        "warnings": list(warnings),
        "history_samples": {name: len(values) for name, values in history.items()},
    }
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except OSError:
        print("USAGE_METRICS=NOT_WRITTEN")


def main() -> int:
    started = time.monotonic()
    cred_state, cred_code = _credential_verdict()
    flows = [Flow("chat_turn"), Flow("pc_read"), Flow("voice_relay"),
             Flow("browser_chat"), Flow("browser_claw"), Flow("browser_stamp"),
             Flow("relogin")]
    by_name = {flow.name: flow for flow in flows}
    browser_captures: list[str] = []

    opener = flow_opener()
    cookie = ""
    saved = None
    if cred_state == "SKIPPED":
        for flow in flows:
            flow.skip(cred_code)
    else:
        flow_chat = by_name["chat_turn"]
        flow_pc = by_name["pc_read"]
        flow_voice_f = by_name["voice_relay"]
        flow_re = by_name["relogin"]
        t0 = time.monotonic()
        try:
            cookie = _login(opener)
            saved = flow_chat_turn(flow_chat, opener)
        except CanaryError as exc:
            flow_chat.fail(exc.public_code)
        flow_chat.elapsed_ms = int((time.monotonic() - t0) * 1000)

        t0 = time.monotonic()
        try:
            flow_pc_read(flow_pc)
        except CanaryError as exc:
            flow_pc.fail(exc.public_code)
        except Exception:
            flow_pc.fail("pc_read_unexpected_error")
        flow_pc.elapsed_ms = int((time.monotonic() - t0) * 1000)

        t0 = time.monotonic()
        if cookie:
            try:
                flow_voice(flow_voice_f, cookie)
            except CanaryError as exc:
                flow_voice_f.fail(exc.public_code)
            except Exception:
                flow_voice_f.fail("voice_unexpected_error")
        else:
            flow_voice_f.skip("no_session_from_flow_1")
        flow_voice_f.elapsed_ms = int((time.monotonic() - t0) * 1000)

        # 브라우저 흐름은 반드시 relogin 앞이다. relogin 이 세션을 끊기 때문이다.
        browser_results, browser_captures = flow_browser(flows, cookie)

        t0 = time.monotonic()
        if cookie:
            try:
                flow_relogin(flow_re, cookie, saved)
            except CanaryError as exc:
                flow_re.fail(exc.public_code)
            except Exception:
                flow_re.fail("relogin_unexpected_error")
        else:
            flow_re.skip("no_session_from_flow_1")
        flow_re.elapsed_ms = int((time.monotonic() - t0) * 1000)

    for flow in flows:
        print(flow.line())

    history = _recent_history()
    warnings = []
    for flow in flows:
        note = browser_checks.slowdown_note(flow.name, flow.elapsed_ms,
                                           history.get(flow.name, []))
        if note:
            warnings.append(note)
    for note in warnings:
        print(note)

    _write_metrics(flows, browser_captures, warnings, history)

    failed = sum(1 for f in flows if f.verdict == "FAIL")
    total_ms = int((time.monotonic() - started) * 1000)
    verdict = "FAIL" if failed else "PASS"
    print(f"USAGE_CHECK verdict={verdict} flows={len(flows)} failed={failed} "
          f"elapsed_ms={total_ms}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("### 실사용 점검 (#6724 2차)\n\n" + _summary(flows))
            if browser_captures:
                handle.write("\n**캡처** (1440 폭, 14일 보관)\n\n")
                for name in browser_captures:
                    handle.write(f"- `{name}`\n")
            if warnings:
                handle.write("\n**느려짐 경고** (FAIL 아님)\n\n")
                for note in warnings:
                    handle.write(f"- {note}\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
