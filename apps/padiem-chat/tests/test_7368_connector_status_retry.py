"""#7368: 연결 화면 상태 조회의 앞단 손실 1회 자동 재시도 계약.

앞단(front)이 스스로 만든 실패(x-padiem-front 헤더 + 502/503/504)와 네트워크
오류는 0.8초 뒤 한 번만 다시 묻는다. 4xx, Chat 서버가 직접 낸 오류(x-padiem-front
헤더가 없는 응답), 호출자가 의도한 중단(AbortError)은 재시도하지 않고, 쓰기
요청은 이 함수로 보내도 항상 한 번만 나간다. 재시도 상한은 1회다.

행위 시험은 저장소의 node 하네스 패턴(subprocess + temp .cjs)으로 돌리고,
호출부 계약은 소스 고정으로 검증한다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TRANSPORT_PATH = STATIC / "chat-transport.js"
APP_PATH = STATIC / "app.js"
MANAGER_PATH = STATIC / "claw-connector-management.js"
DEVICE_PATH = STATIC / "claw-device-manager.js"
INDEX_PATH = STATIC / "index.html"


def _transport_source() -> str:
    return TRANSPORT_PATH.read_text(encoding="utf-8")


def _run_node_script(script: str) -> str:
    """Run a script from a temp file (Windows ~32K command-line limit)."""
    import os
    import tempfile

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".cjs", delete=False, encoding="utf-8", newline="\n",
    )
    try:
        handle.write(script)
        handle.close()
        completed = subprocess.run(
            ["node", handle.name],
            check=True,
            capture_output=True,
            text=True, encoding="utf-8",
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    return completed.stdout.strip()


DRIVER = """
global.window = globalThis;
%s

const calls = [];
let plan = [];
global.fetch = async (url, options = {}) => {
  calls.push({ url, method: String(options.method ?? "GET").toUpperCase() });
  // 실제 fetch처럼 이미 중단된 신호는 AbortError로 거절한다.
  if (options.signal?.aborted) {
    const aborted = new Error("The operation was aborted");
    aborted.name = "AbortError";
    throw aborted;
  }
  const step = plan.shift() ?? {};
  if (step.throw) throw new TypeError("Failed to fetch");
  return new Response(step.body ?? "{}", {
    status: step.status ?? 200,
    headers: step.headers ?? {},
  });
};

async function run(name, scenario) {
  calls.length = 0;
  plan = scenario.steps.slice();
  let outcome = { retried: 0 };
  try {
    const response = await PadiemChatTransport.fetchStatusWithRetry(
      scenario.url ?? "/api/connectors/status",
      scenario.options ?? {},
      { delayMs: 1, onRetry: () => outcome.retried = (outcome.retried ?? 0) + 1 },
    );
    outcome.status = response.status;
    outcome.ok = response.ok;
  } catch (error) {
    outcome.threw = error?.name ?? "Error";
  }
  outcome.calls = calls.length;
  outcome.methods = calls.map((c) => c.method);
  return outcome;
}

(async () => {
  const results = {};
  const front502 = { status: 502, headers: { "x-padiem-front": "upstream_transport_failed" } };
  const front503 = { status: 503, headers: { "x-padiem-front": "read_fallback_static" } };
  const front504 = { status: 504, headers: { "x-padiem-front": "upstream_timeout" } };
  const ok = { status: 200, body: JSON.stringify({ ok: true }) };

  // 시나리오는 공유 fetch 기록(plan·calls) 위에서 도니 순차 실행한다.
  results.first_fail_retry_success = await run("first_fail_retry_success", { steps: [front502, ok] });
  results.two_failures_stop_at_cap = await run("two_failures_stop_at_cap", { steps: [front502, front502] });
  results.unauthorized_is_not_retried = await run("unauthorized_is_not_retried", { steps: [{ status: 401 }] });
  results.server_503_is_not_retried = await run("server_503_is_not_retried", { steps: [{ status: 503 }] });
  results.front_503_is_retried = await run("front_503_is_retried", { steps: [front503, ok] });
  results.front_504_is_retried = await run("front_504_is_retried", { steps: [front504, ok] });
  results.network_error_retry_success = await run("network_error_retry_success", { steps: [{ throw: true }, ok] });
  results.network_error_twice_stops_at_cap = await run("network_error_twice_stops_at_cap", { steps: [{ throw: true }, { throw: true }] });
  results.write_is_never_retried = await run("write_is_never_retried", {
    url: "/api/connectors/github/start",
    options: { method: "POST" },
    steps: [front502, front502, front502],
  });
  results.abort_is_not_retried = await run("abort_is_not_retried", {
    options: { signal: AbortSignal.abort() },
    steps: [{ throw: true }, ok],
  });
  console.log(JSON.stringify(results));
})().catch((error) => { console.error(error); process.exit(1); });
""" % _transport_source()


def _outcome(name: str) -> dict:
    return json.loads(_run_node_script(DRIVER))[name]


def _without_methods(name: str) -> dict:
    outcome = _outcome(name)
    outcome.pop("methods", None)
    return outcome


def test_first_front_failure_is_retried_once_and_succeeds() -> None:
    outcome = _outcome("first_fail_retry_success")
    # 첫 실패 → 0.8초 뒤 1회 재시도 → 성공. 재시도 표시(hook)는 정확히 1번.
    assert _without_methods("first_fail_retry_success") == {
        "calls": 2, "retried": 1, "status": 200, "ok": True,
    }


def test_two_front_failures_stop_at_the_one_retry_cap() -> None:
    outcome = _outcome("two_failures_stop_at_cap")
    # 그래도 실패하면 호출부로 돌려준다(호출부가 기존대로 확인 실패를 표시한다).
    # 재시도 상한은 1회: 호출은 정확히 2번.
    assert outcome["calls"] == 2
    assert outcome["retried"] == 1
    assert outcome["status"] == 502
    assert outcome["ok"] is False


def test_unauthorized_is_never_retried() -> None:
    outcome = _outcome("unauthorized_is_not_retried")
    assert outcome["calls"] == 1
    assert outcome["retried"] == 0
    assert outcome["status"] == 401


def test_a_chat_server_503_is_never_retried() -> None:
    # x-padiem-front 헤더가 없는 503은 Chat 서버가 직접 낸 오류다(예: 기기
    # 디렉터리 미설정). 앞단 손실이 아니므로 재시도하지 않는다.
    outcome = _outcome("server_503_is_not_retried")
    assert outcome["calls"] == 1
    assert outcome["retried"] == 0


def test_front_made_503_and_504_are_retried() -> None:
    assert _outcome("front_503_is_retried")["calls"] == 2
    assert _outcome("front_504_is_retried")["calls"] == 2


def test_network_error_is_retried_once() -> None:
    assert _without_methods("network_error_retry_success") == {
        "calls": 2, "retried": 1, "status": 200, "ok": True,
    }
    twice = _outcome("network_error_twice_stops_at_cap")
    assert twice["calls"] == 2
    assert twice["retried"] == 1
    assert twice["threw"] == "TypeError"


def test_a_write_request_is_never_retried() -> None:
    outcome = _outcome("write_is_never_retried")  # keeps methods
    # POST는 세 번 실패 응답을 준비해도 첫 번째에서 끝난다: 재시도 없음.
    assert outcome["calls"] == 1
    assert outcome["retried"] == 0
    assert outcome["methods"] == ["POST"]


def test_a_caller_abort_is_never_retried() -> None:
    # 패널 닫기·계정 전환·읽기 시간 초과 같은 의도된 중단은 재시도하지 않는다.
    outcome = _outcome("abort_is_not_retried")
    assert outcome["calls"] == 1
    assert outcome["retried"] == 0
    assert outcome["threw"] == "AbortError"


def test_the_three_status_read_calls_route_through_the_helper() -> None:
    app = APP_PATH.read_text(encoding="utf-8")
    manager = MANAGER_PATH.read_text(encoding="utf-8")
    device = DEVICE_PATH.read_text(encoding="utf-8")

    # app.js loadConnectorStatus: the status read goes through the helper.
    assert "PadiemChatTransport.fetchStatusWithRetry(\"/api/connectors/status\"" in app
    assert 'fetch("/api/connectors/status"' not in app
    # claw-device-manager.js runLoad: the directory read goes through the helper.
    assert "PadiemChatTransport.fetchStatusWithRetry(ENDPOINT" in device
    # claw-connector-management.js json(): GET status reads retry, writes do not.
    assert "PadiemChatTransport.fetchStatusWithRetry(url" in manager

    # The helper itself refuses retries for non-read methods (call-order proof
    # that the github connect/pause/disconnect POSTs stay single-attempt).
    transport = _transport_source()
    assert 'String(options?.method ?? "GET").toUpperCase()' in transport
    assert 'const retryable = method === "GET" || method === "HEAD";' in transport
    # The retry delay and the front-loss marker rule live in the transport
    # module only; app.js gains no retry logic (module boundary, #7216).
    assert "STATUS_RETRY_DELAY_MS = 800" in transport
    assert 'x-padiem-front' in transport
    assert 'x-padiem-front' not in app
    assert 'x-padiem-front' not in manager
    assert 'x-padiem-front' not in device


def test_the_transport_module_loads_before_every_retry_caller() -> None:
    html = INDEX_PATH.read_text(encoding="utf-8")
    transport_at = html.index('<script src="./chat-transport.js"></script>')
    assert transport_at < html.index('<script src="./app.js"></script>')
    assert transport_at < html.index('<script src="./claw-connector-management.js"></script>')
    assert transport_at < html.index('<script src="./claw-device-manager.js"></script>')
