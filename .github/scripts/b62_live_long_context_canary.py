#!/usr/bin/env python3
"""Owner-authorized bounded B62 production QA: real login, 2 JSON turns, 1 SSE turn.

Uses ONLY the pre-existing CGI Alpha QA identity from the protected GitHub
production environment. Does not print secrets, cookies, user identity,
conversation text, vendor output, or response headers. Does not create accounts
or mutate admin model/tier authorization. A model HOLD is a BLOCK, not PASS.
"""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor

ORIGIN = "https://chat.padiem.net"
LOGIN = "/api/auth/password/login"
STATUS = "/api/auth/status"
CHAT = "/api/chat"
STREAM = "/api/chat/stream"
CONVERSATION = "/api/conversations/"
# login, status, two JSON turns, history, delete, composer SSE turn, delete
MAX_REQUESTS = 1 + 1 + 2 + 1 + 1 + 1 + 1
QA_BYTES_CAP = 400_000
RESPONSE_BYTES_CAP = 2_000_000
STREAM_LINE_CAP = 20_000
CHAT_TIMEOUT_SECONDS = 115
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,80}$")
_ID = re.compile(r"^chat_[0-9a-f]{32}$")


def synthetic_text(run_id: str) -> tuple[str, str]:
    # No real customer content or random live secret in prompts.
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:20].upper()
    marker = "PADIEM_QA_TAIL_" + digest
    body = ("이것은 고객정보가 없는 장문 채팅 문맥 보존 QA 자료입니다. "
            "문단에는 어떤 개인정보도 없으며 이전 대화 원문을 테스트합니다.\n") * 240
    text = ("아래의 장문 QA 문서를 읽고 완료라고만 대답하세요. "
            "다음 질문에서 문서 맨 끝의 표식을 물을 예정입니다.\n"
            + body + "\n마지막 표식: " + marker)
    assert len(text) > 8_000
    assert text.endswith(marker)
    assert len(text.encode("utf-8")) < QA_BYTES_CAP
    return text, marker


class CanaryError(Exception):
    def __init__(self, public_code: str):
        super().__init__(public_code)
        self.public_code = public_code


def bounded_call(opener, path: str, *, method: str = "GET", payload=None, timeout=25):
    assert path.startswith("/") and not path.startswith("//")
    headers = {
        "Accept": "application/json",
        "User-Agent": "PADIEM-B62-owner-long-context-canary/1.0",
        "Cache-Control": "no-store",
    }
    _version_header = os.environ.get("B62_STAGED_VERSION_HEADER", "")
    _version_id = os.environ.get("B62_STAGED_VERSION_ID", "")
    if _version_header and _version_id:
        # #5895 staged rollout: pin these probes to the version under test.
        headers[_version_header] = _version_id
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(data) > QA_BYTES_CAP:
            raise CanaryError("client_qa_transport_guard")
        headers.update({"Content-Type": "application/json", "Origin": ORIGIN, "Referer": ORIGIN + "/"})
    req = Request(ORIGIN + path, method=method, data=data, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as response:
            status = response.status
            body = response.read(RESPONSE_BYTES_CAP + 1)
    except HTTPError as err:
        status = err.code
        body = err.read(RESPONSE_BYTES_CAP + 1)
    except (TimeoutError, URLError, OSError) as exc:
        raise CanaryError("http_transport_unavailable") from exc
    if len(body) > RESPONSE_BYTES_CAP:
        raise CanaryError("http_response_exceeds_qa_guard")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise CanaryError("unexpected_http_json_shape") from None
    if not isinstance(data, dict):
        raise CanaryError("unexpected_http_json_shape")
    return status, data


def error_code(payload) -> str:
    value = payload.get("error", {})
    code = value.get("code") if isinstance(value, dict) else None
    return code if isinstance(code, str) and _CODE.fullmatch(code) else "no_safe_error_code"


def parse_stream(lines) -> dict:
    """Bounded SSE reader for the composer route contract (delta/done/error)."""
    delta_events = 0
    answer_chars = 0
    done = False
    conversation_id = None
    stream_error = None
    event_name = ""
    total_bytes = 0
    for count, line in enumerate(lines, 1):
        if count > STREAM_LINE_CAP:
            raise CanaryError("stream_line_cap_exceeded")
        total_bytes += len(line)
        if total_bytes > RESPONSE_BYTES_CAP:
            raise CanaryError("stream_response_exceeds_qa_guard")
        text = line.decode("utf-8", "replace").rstrip("\r\n")
        if text.startswith("event:"):
            event_name = text[6:].strip()
            continue
        if not text.startswith("data:"):
            continue
        try:
            payload = json.loads(text[5:].strip())
        except ValueError:
            raise CanaryError("unexpected_stream_json_shape") from None
        if not isinstance(payload, dict):
            raise CanaryError("unexpected_stream_json_shape")
        if event_name == "delta":
            delta = payload.get("delta")
            if isinstance(delta, str) and delta:
                delta_events += 1
                answer_chars += len(delta)
        elif event_name == "done":
            done = True
            candidate = payload.get("conversation_id")
            if isinstance(candidate, str) and _ID.fullmatch(candidate):
                conversation_id = candidate
            break
        elif event_name == "error":
            stream_error = error_code(payload)
            break
    return {
        "delta_events": delta_events,
        "answer_chars": answer_chars,
        "done": done,
        "conversation_id": conversation_id,
        "error_code": stream_error,
    }


def bounded_stream_call(opener, path: str, *, payload, timeout=CHAT_TIMEOUT_SECONDS) -> dict:
    assert path.startswith("/") and not path.startswith("//")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > QA_BYTES_CAP:
        raise CanaryError("client_qa_transport_guard")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "User-Agent": "PADIEM-B62-owner-stream-canary/1.0",
        "Cache-Control": "no-store",
        "Origin": ORIGIN,
        "Referer": ORIGIN + "/",
    }
    req = Request(ORIGIN + path, method="POST", data=data, headers=headers)
    try:
        response = opener.open(req, timeout=timeout)
    except HTTPError as err:
        body = err.read(RESPONSE_BYTES_CAP + 1)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError):
            parsed = None
        return {
            "status": err.code,
            "delta_events": 0,
            "answer_chars": 0,
            "done": False,
            "conversation_id": None,
            "error_code": error_code(parsed) if isinstance(parsed, dict) else "no_safe_error_code",
        }
    except (TimeoutError, URLError, OSError) as exc:
        raise CanaryError("http_transport_unavailable") from exc
    with response:
        parsed = parse_stream(response)
    parsed["status"] = response.status
    return parsed


def run() -> int:
    username = os.environ.get("B66_CGI_ALPHA_USERNAME", "")
    password = os.environ.get("B66_CGI_ALPHA_PASSWORD", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not username or not password or not run_id:
        print("B62_LONG_CONTEXT_CANARY=BLOCKED_NO_APPROVED_QA_CREDENTIAL")
        return 3
    prompt, marker = synthetic_text(run_id)
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    chat_id = None
    stream_chat_id = None
    try:
        code, body = bounded_call(
            opener, LOGIN, method="POST",
            payload={"identifier": username, "password": password},
        )
        if code != 200 or body.get("ok") is not True:
            print("B62_LOGIN=FAILED", "HTTP=" + str(code), "CODE=" + error_code(body))
            return 4
        code, state = bounded_call(opener, STATUS)
        if code != 200 or state.get("authenticated") is not True:
            print("B62_OWNER_SESSION=FAILED", "HTTP=" + str(code))
            return 4
        print("B62_OWNER_SESSION=PASS")
        print("B62_QA_LONG_MESSAGE_CHARS=" + str(len(prompt)))
        code, body = bounded_call(
            opener, CHAT, method="POST", timeout=CHAT_TIMEOUT_SECONDS,
            payload={
                "mode": "auto", "tier": "plus",
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        print("B62_FIRST_CHAT_HTTP=" + str(code))
        if code != 200:
            print("B62_FIRST_CHAT_ERROR_CODE=" + error_code(body))
            print("B62_LONG_CONTEXT_LIVE_ACCEPTANCE=BLOCKED" if code in (401, 403, 429, 503)
                  else "B62_LONG_CONTEXT_LIVE_ACCEPTANCE=FAILED")
            return 5
        chat_id = body.get("conversation_id")
        if not isinstance(chat_id, str) or not _ID.fullmatch(chat_id):
            raise CanaryError("completed_model_missing_canonical_history_id")
        if not isinstance(body.get("answer"), str) or not body["answer"].strip():
            raise CanaryError("completed_model_missing_answer")
        print("B62_FIRST_MODEL_RESPONSE=PASS")
        code, detail = bounded_call(opener, CONVERSATION + chat_id)
        if code != 200:
            raise CanaryError("owner_history_readback_failed")
        saved = detail.get("conversation")
        msgs = saved.get("messages") if isinstance(saved, dict) else None
        if not isinstance(msgs, list) or len(msgs) < 2:
            raise CanaryError("owner_history_readback_invalid")
        stored_user = msgs[0].get("content", "") if isinstance(msgs[0], dict) else ""
        if not isinstance(stored_user, str) or len(stored_user) > 8_000:
            raise CanaryError("display_preview_contract_invalid")
        print("B62_D1_DISPLAY_PREVIEW=PASS")
        question = ("이전 대화에서 길게 제시한 QA 원문의 가장 마지막에 있던 표식을 "
                    "정확히 하나만 다시 적어 주세요. 추측하지 마세요.")
        code, result = bounded_call(
            opener, CHAT, method="POST", timeout=CHAT_TIMEOUT_SECONDS,
            payload={
                "mode": "auto", "tier": "plus", "conversation_id": chat_id,
                # Deliberately supply the displayed 8k previews to mimic the
                # reopened browser. Server must recover full owner R2 text.
                "messages": [
                    {"role": "user", "content": stored_user},
                    {"role": "assistant", "content": str(msgs[1].get("content", ""))},
                    {"role": "user", "content": question},
                ],
            },
        )
        print("B62_SECOND_CHAT_HTTP=" + str(code))
        if code != 200:
            print("B62_SECOND_CHAT_ERROR_CODE=" + error_code(result))
            print("B62_LONG_CONTEXT_LIVE_ACCEPTANCE=FAILED")
            return 6
        answer = result.get("answer")
        if not isinstance(answer, str) or marker not in answer:
            print("B62_LONG_CONTEXT_TAIL_RECALL=FAILED")
            print("B62_LONG_CONTEXT_LIVE_ACCEPTANCE=FAILED")
            return 7
        print("B62_LONG_CONTEXT_TAIL_RECALL=PASS")
        print("B62_LONG_CONTEXT_LIVE_ACCEPTANCE=PASS")
        stream = bounded_stream_call(
            opener, STREAM,
            payload={
                "mode": "auto", "tier": "plus",
                "messages": [{"role": "user", "content":
                              "정상 작동 여부 확인입니다. 한 문장으로 답해 주세요."}],
            },
        )
        print("B62_STREAM_CHAT_HTTP=" + str(stream["status"]))
        if stream["status"] != 200:
            print("B62_STREAM_ERROR_CODE=" + stream["error_code"])
            print("B62_COMPOSER_STREAM_LIVE_ACCEPTANCE="
                  + ("BLOCKED" if stream["status"] in (401, 403, 429, 503) else "FAILED"))
            return 9
        print("B62_STREAM_DELTA_EVENTS=" + str(stream["delta_events"]))
        print("B62_STREAM_ANSWER_CHARS=" + str(stream["answer_chars"]))
        if stream["error_code"] is not None or not stream["done"] \
                or stream["delta_events"] < 1 or stream["answer_chars"] < 1:
            print("B62_STREAM_ERROR_CODE=" + (stream["error_code"] or "none"))
            print("B62_COMPOSER_STREAM_LIVE_ACCEPTANCE=FAILED")
            return 9
        print("B62_STREAM_DONE=PASS")
        stream_chat_id = stream["conversation_id"]
        print("B62_COMPOSER_STREAM_LIVE_ACCEPTANCE=PASS")
        return 0
    except CanaryError as exc:
        print("B62_LONG_CONTEXT_CANARY_ERROR=" + exc.public_code)
        print("B62_LONG_CONTEXT_LIVE_ACCEPTANCE=FAILED")
        return 8
    finally:
        for handle in (chat_id, stream_chat_id):
            if handle is None:
                continue
            try:
                status, cleanup = bounded_call(opener, CONVERSATION + handle, method="DELETE")
                if status == 200 and cleanup.get("deleted") is True:
                    print("B62_QA_CONVERSATION_CLEANUP=PASS")
                else:
                    print("B62_QA_CONVERSATION_CLEANUP=NEEDS_REVIEW")
            except Exception:
                print("B62_QA_CONVERSATION_CLEANUP=NEEDS_REVIEW")
        print("B62_QA_PASSWORD_OR_COOKIE_LOGGED=0")
        print("B62_QA_CUSTOMER_DATA_OR_RAW_RESPONSE_LOGGED=0")


def self_test() -> int:
    import io
    text, mark = synthetic_text("offline-proof")
    assert len(text) > 8_000 and text.endswith(mark)
    assert len(text.encode("utf-8")) < QA_BYTES_CAP
    assert _ID.fullmatch("chat_" + "a" * 32)
    assert error_code({"error": {"code": "model_profile_unassigned"}}) == "model_profile_unassigned"
    assert error_code({"error": {"code": "danger\nhello"}}) == "no_safe_error_code"
    assert ORIGIN == "https://chat.padiem.net"
    assert STREAM == "/api/chat/stream"
    assert MAX_REQUESTS == 8
    assert CHAT_TIMEOUT_SECONDS < 120
    parsed = parse_stream(io.BytesIO(
        b'event: delta\ndata: {"delta":"ok"}\n\n'
        b'event: done\ndata: {"done":true,"conversation_id":"chat_' + b"a" * 32 + b'"}\n\n'
    ))
    assert parsed["delta_events"] == 1 and parsed["answer_chars"] == 2
    assert parsed["done"] is True and parsed["error_code"] is None
    assert parsed["conversation_id"] == "chat_" + "a" * 32
    empty = parse_stream(io.BytesIO(
        b'event: error\ndata: {"error":{"code":"empty_upstream_answer","message":"x"}}\n\n'
    ))
    assert empty["error_code"] == "empty_upstream_answer" and empty["done"] is False
    print("B62_LONG_CONTEXT_CANARY_SOURCE=PASS")
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    if sys.argv[1:] != ["--authorized-live"]:
        print("B62_LONG_CONTEXT_DEFAULT_LIVE_EXECUTION=BLOCKED")
        sys.exit(2)
    sys.exit(run())
