"""#5002 후속(2026-11-01): 화면에 보이는 오류 문구는 한국어 한 문장이다.

세 가지를 고정한다.

1. **문구표** — `static/locale.js`의 ko 사전이 오류 키에 기술 용어(HTTP·상태코드·
   `timeout`·`unauthorized`·`rate limit`)가 아닌 한국어 문장을 주는지.
2. **코드→문장 연결** — 앞단·서버가 내려보내는 `upstream_timeout` 같은 코드가
   화면에서 원문이 아니라 `uiT("timeout")` 문장으로 도달하는 경로.
3. **원문 노출 금지** — 서버 상태 토큰을 그대로 `textContent`에 싣던 세 곳과,
   앞단(WAF 프록시)이 브라우저 내비게이션에 JSON 원문을 주던 경로.

앞단 자체의 동작(HTML/JSON 분기·재시도 링크·경로 이스케이프)은
`apps/padiem-chat-front/test/error_copy.test.mjs`가 실제 응답으로 검증한다.
이 모듈은 그 파일의 존재와 사용 배선까지 함께 본다.
"""

from __future__ import annotations

import re
from pathlib import Path

CHAT = Path(__file__).resolve().parents[1]
STATIC = CHAT / "static"
FRONT = CHAT.parent / "padiem-chat-front"

LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
FRONT_WORKER = (FRONT / "worker.mjs").read_text(encoding="utf-8")
FRONT_COPY = (FRONT / "error-copy.mjs").read_text(encoding="utf-8")
FRONT_TEST = (FRONT / "test" / "error_copy.test.mjs").read_text(encoding="utf-8")

# The technical tokens that must never be the words a user reads.
TECHNICAL = re.compile(
    r"\b(?:HTTP|https?|JSON|[0-9]{3}\b|timeout|unauthorized|rate limit|upstream|"
    r"transport|error code|exception|null|undefined|502|503|504)\b",
    re.IGNORECASE,
)
HANGUL = re.compile(r"[\uac00-\ud7a3]")


def ko_table() -> dict[str, str]:
    start = LOCALE.index("const labels = {")
    ko_start = LOCALE.index("ko: {", start)
    ko_body = LOCALE[ko_start:LOCALE.index("\n    en: {", ko_start)]
    return dict(re.findall(r'"([a-z0-9][a-z0-9-]{1,60})":\s*"([^"]*)"', ko_body))


ERROR_KEYS = (
    "timeout", "connection-error", "try-again", "retry", "answer-load-failed",
    "stream-incomplete", "stream-continue-failed", "stream-complete-invalid",
    "history-load-failed", "history-retry", "conversation-load-failed",
    "claw-error-generic", "claw-error-auth-needed", "claw-error-rate-limited",
    "claw-error-empty", "claw-error-storage", "claw-error-too-large",
    "pc-exchange-no-pc", "pc-exchange-no-answer", "pc-exchange-save-failed",
    "status-unknown",
)


def test_the_korean_error_table_covers_every_screen_facing_failure():
    table = ko_table()
    missing = [key for key in ERROR_KEYS if key not in table]
    assert not missing, f"ko 사전에 없는 오류 키: {missing}"


def test_no_error_line_reads_as_a_technical_token():
    table = ko_table()
    offenders = {
        key: table[key] for key in ERROR_KEYS
        if TECHNICAL.search(table[key]) or not HANGUL.search(table[key])
    }
    assert not offenders, f"기술 용어가 화면 문구로 남음: {offenders}"


def test_the_retry_action_is_a_korean_word_not_retry():
    table = ko_table()
    assert table["retry"] == "다시 시도"
    assert table["history-retry"] == "다시 시도"
    # "Retry" as a button label is what the owner asked to remove.
    assert not re.search(r'"(?:retry|history-retry)":\s*"Retry"', LOCALE[:LOCALE.index("\n    en: {")])


def test_upstream_timeout_reaches_the_screen_as_a_korean_sentence():
    # The code is classified, the classification chooses the copy, and the copy
    # key exists in the Korean table.
    assert 'error && error.code === "upstream_timeout" ? MESSAGE_LIFECYCLE.TIMED_OUT' in APP_JS
    assert 'lifecycle === MESSAGE_LIFECYCLE.TIMED_OUT ? uiT("timeout")' in APP_JS
    assert re.search(r'"timeout":\s*"[^"]*[가-힣][^"]*"', LOCALE)


def test_the_server_status_token_is_never_echoed_as_screen_copy():
    """Three places printed a raw server token when the table had no entry.

    The run-history badge is deliberately NOT one of them: #3933 and
    `test_b54_claw_run_history_ui` require `clawRunStatusLabel` to keep the raw
    token, because an invented label there would read as a derived run status.
    That contract is asserted below so this file cannot quietly undo it.
    """
    assert 'meta.textContent = statusText === statusKey ? uiT("status-unknown") : statusText;' in APP_JS
    assert 'badge.textContent = memory.status === "approved" ? clawT("claw-memory-status-approved") : uiT("status-unknown");' in APP_JS
    assert ', value: memory.status === "approved" ? clawT("claw-memory-status-approved") : uiT("status-unknown") },' in APP_JS
    # The old echoes are gone, not merely shadowed by a new line.
    assert '? String(item.status || "") : statusText' not in APP_JS
    assert ': (memory.status || "")' not in APP_JS
    # The protected contract still holds.
    assert "return text === key ? raw : text;" in APP_JS


def test_an_empty_completed_answer_is_not_committed_as_a_turn():
    # The streaming path already refused a blank completion; the completed path
    # accepted `answer: ""` and painted an empty bubble.
    assert re.search(r'if \(!data\.answer\.trim\(\)\) \{', TRANSPORT)
    assert "답변이 비어 왔습니다. 다시 시도해 주세요." in TRANSPORT


def test_the_front_door_answers_a_navigation_with_a_page_and_a_machine_with_json():
    assert 'import { errorPageHtml, wantsHtml } from "./error-copy.mjs";' in FRONT_WORKER
    assert "function requestFailure(request, status, code)" in FRONT_WORKER
    assert FRONT_WORKER.count("return requestFailure(request, ") == 4
    assert "if (wantsHtml(request)) {" in FRONT_WORKER
    # The JSON arm is unchanged, so every existing consumer keeps its contract.
    assert 'JSON.stringify({ error: { code, message:' in FRONT_WORKER


def test_the_front_copy_lives_in_one_file_and_carries_no_secrets():
    assert FRONT_TEST, "the front door's own behaviour test must exist"
    assert "export const ERROR_COPY" in FRONT_COPY
    for code in ("upstream_timeout", "upstream_transport_failed", "service_unavailable"):
        assert code in FRONT_COPY
    assert "function escapeHtml" in FRONT_COPY
    # The login callback carries state/code in its query; neither may be echoed.
    assert "never the query" in FRONT_COPY or "not where those belong" in FRONT_COPY
    assert 'assert.doesNotMatch(body, /SECRETSTATE|SECRETCODE/);' in FRONT_TEST


def test_the_front_door_still_never_reads_or_rewrites_bodies():
    # The proxy contract is unchanged by a copy fix: no body reads were added.
    assert ".json()" not in FRONT_WORKER
    assert ".arrayBuffer()" not in FRONT_WORKER
    assert "/text\/event-stream/i" in FRONT_WORKER  # SSE still passes through
