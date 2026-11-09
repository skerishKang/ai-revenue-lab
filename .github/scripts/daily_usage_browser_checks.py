#!/usr/bin/env python3
"""#6724 2차: 브라우저 실사용 흐름·캡처·느려짐 경고 (#6724, CTO 2026-11-10).

1차(`daily_real_usage_check.py`)는 API 수준에서 네 흐름을 실제 결과값으로
판정한다. 2차는 같은 러너에서 운영 화면(chat.padiem.net)을 실제로 열어 세
가지를 더 본다:

  browser_chat   로그인된 화면에서 질문 1개 → 답 글자 10자 이상 + 콘솔 오류 0
  browser_claw   같은 계정으로 Claw 화면에서 질문 1개 → 답 표시
                 (Chat 과 Claw 는 기능이 같다는 대표 결정: 한쪽만 되면 FAIL)
  browser_stamp  화면이 실제로 불러온 app.js 의 ?v= 스탬프가 배포 SHA 앞 8자리인지

이 파일은 두 층으로 나뉜다.

  * 판정 함수(answer_verdict, console_ok, stamp_verdict, slowdown_note,
    artifact_filename …)는 브라우저 없이 직접 호출할 수 있는 순수 함수다.
    시험은 이 함수들을 직접 부른다(`.github/tests/test_daily_usage_browser_helpers_261110.py`).
  * 실행기(run_browser_flows)는 그 판정에 입력을 모으는 얇은 층이다.
    Playwright 는 함수 안에서만 import 하므로 순수 함수 시험은 브라우저를
    설치하지 않아도 된다.

판정 계약은 1차와 같다.

  - 결과값이 기준이다. "응답이 왔다"가 아니라 화면에 실제로 뜬 답 글자다.
  - 자격 증명이 없으면 FAIL 이 아니라 SKIPPED 다(#6720 계약).
  - 값·쿠키·토큰·계정 이름은 로그에 남기지 않는다. 캡처는 찍기 전에 계정
    표시를 흐리게 만든다.
  - 콘솔 오류 허용 목록은 URL 범위로 좁힌다. 무관한 외부 자산만 허용하고
    제품 API 오류는 절대 허용하지 않는다.
"""

from __future__ import annotations

import io
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ORIGIN = "https://chat.padiem.net"
CHAT_URL = ORIGIN + "/"
CLAW_HASH = "#padiem-claw"

# 캡처는 항상 1440 폭(대표가 보는 데스크톱 폭)이다. 높이는 한 화면.
CAPTURE_WIDTH = 1440
CAPTURE_HEIGHT = 900
VIEWPORT = {"width": CAPTURE_WIDTH, "height": CAPTURE_HEIGHT}

CHAT_PROMPT = "지금 화면이 정상 동작하는지 한 문장으로 답해 주세요."
CLAW_PROMPT = CHAT_PROMPT

HEAD_CHAT = 10
ANSWER_WAIT_SECONDS = 90.0
NAVIGATE_TIMEOUT_MS = 60_000
SELECTOR_TIMEOUT_MS = 30_000

SLOWDOWN_FACTOR = 2.0
SLOWDOWN_HISTORY = 7
SLOWDOWN_LABEL = "SLOWDOWN_WARNING"

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,80}$")
_VERSION_IN_URL = re.compile(r"[?&]v=([A-Za-z0-9_.-]{1,64})")

# 콘솔 오류 허용 목록: (URL 정규식, 이유). URL 은 메시지가 가리키는 리소스다.
# 오늘 운영 화면은 외부 분석 스크립트를 싣지 않는다(정적 파일 확인). 그래서
# 허용 목록은 "제품과 무관한 정적 자산" 네 줄로만 유지한다. 새 항목을 넣을
# 때는 반드시 이유를 함께 적는다 — 목록이 넓어지면 콘솔 오류 0 판정이 무의미해진다.
CONSOLE_ALLOWLIST: tuple[tuple[str, str], ...] = (
    (r"^https?://fonts\.googleapis\.com/",
     "웹폰트 CSS 요청. 제품 로직·API 아님"),
    (r"^https?://fonts\.gstatic\.com/",
     "웹폰트 글리프 파일. 제품 로직·API 아님"),
    (r"/favicon\.ico(?:\?|$)",
     "파비콘 미제공. 화면 기능과 무관"),
    (r"/push-sw\.js(?:\?|$)",
     "푸시 서비스워커는 지원 브라우저에서만 등록된다. 미지원이면 404"),
)

# 텍스트로만 구분되는 브라우저 안내 문구. 네트워크 오류가 아니라 기능 감지다.
CONSOLE_TEXT_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("ServiceWorker registration failed",
     "ServiceWorker 미지원·비보안 컨텍스트 안내. 제품 흐름 아님"),
)


# ------------------------------------------------------------------ 콘솔 오류
def console_allow_reason(url: str, text: str = "") -> str | None:
    """허용 목록에 걸리면 이유를, 아니면 None 을 돌려준다."""
    candidate = url or ""
    for pattern, reason in CONSOLE_ALLOWLIST:
        if candidate and re.search(pattern, candidate):
            return reason
    joined = f"{candidate} {text or ''}"
    for needle, reason in CONSOLE_TEXT_ALLOWLIST:
        if needle in joined:
            return reason
    return None


def console_ok(events: list[tuple[str, str, str]]) -> tuple[bool, str]:
    """(오류 0 인가, 첫 실패의 안전 코드).

    events 는 (종류, 메시지, URL) 이다. 허용 목록에 없는 항목이 하나라도
    있으면 오류로 센다. 코드에는 값이 아니라 위치(host+path)만 남긴다.
    """
    for kind, text, url in events:
        if console_allow_reason(url, text) is not None:
            continue
        where = _resource_code(url)
        return False, f"console_error_{kind}_{where}"
    return True, "none"


def _resource_code(url: str) -> str:
    """URL 에서 host+path 만 안전 코드로. 쿼리·값은 버린다."""
    if not url:
        return "page"
    match = re.match(r"^[a-z]+://([^/]+)(/[^?#]*)?", url, re.IGNORECASE)
    if not match:
        return "page"
    host = re.sub(r"[^a-z0-9]+", "_", match.group(1).lower()).strip("_")
    path = re.sub(r"[^a-z0-9]+", "_", (match.group(2) or "")).strip("_")
    code = f"{host}_{path}".strip("_")[:60]
    return code or "page"


# ------------------------------------------------------------------ 답 판정
def answer_verdict(text: str | None, minimum: int = HEAD_CHAT) -> tuple[str, str, str]:
    """(판정, 코드, 앞부분). 화면에 뜬 글자가 기준이다."""
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    if len(flat) < minimum:
        return "FAIL", "screen_answer_too_short", flat[:minimum]
    return "PASS", "none", flat[:minimum]


def screen_parity(chat_verdict: str, claw_verdict: str) -> tuple[bool, str]:
    """두 화면의 결과가 같은가. 한쪽만 되면 FAIL 이다.

    Chat 과 Claw 는 기능이 같다는 대표 결정이 있으므로, 한 화면만 답을
    내는 것은 "다른 제품"이 아니라 회귀다.
    """
    if chat_verdict == claw_verdict:
        return True, "none"
    if claw_verdict == "PASS":
        return False, "screen_parity_claw_only"
    if chat_verdict == "PASS":
        return False, "screen_parity_chat_only"
    return True, "none"


# ------------------------------------------------------------------ 스탬프
def stamp_from_url(url: str | None) -> str:
    """app.js URL 의 ?v= 값. 없으면 빈 문자열."""
    match = _VERSION_IN_URL.search(url or "")
    return match.group(1) if match else ""


def stamp_verdict(
    observed: str,
    head_version: str,
    recent_versions: list[str] | tuple[str, ...] = (),
) -> tuple[str, str]:
    """(판정, 코드). 화면이 부른 app.js 스탬프와 배포 SHA 앞 8자리를 비교한다.

    release_chat.ps1 은 배포 직전 커밋의 앞 8자리로 정적 자산을 스탬프한다.
    그래서 화면의 스탬프는 "이 화면이 어느 커밋에서 나왔는가"다.

    - 스탬프가 없으면 FAIL: 배포가 스탬프를 거치지 않았다.
    - 스탬프가 현재 main 앞 8자리면 PASS.
    - main 의 최근 커밋 중 하나면 PASS + deploy_lag: 병합 직후 배포 전 창.
    - 그 밖(오래된 커밋·알 수 없는 값)이면 FAIL screen_deploy_missing:
      화면 배포가 누락됐다.
    """
    value = (observed or "").strip()
    if not value:
        return "FAIL", "screen_stamp_missing"
    expected = (head_version or "").strip()
    if expected and value == expected:
        return "PASS", "none"
    if value in {str(item).strip() for item in recent_versions if str(item).strip()}:
        return "PASS", "deploy_lag"
    return "FAIL", "screen_deploy_missing"


# ------------------------------------------------------------------ 느려짐
def median_of(history: list[int]) -> int | None:
    values = sorted(int(x) for x in history if isinstance(x, int) and x > 0)
    if not values:
        return None
    return int(statistics.median(values))


def slowdown_note(name: str, elapsed_ms: int, history: list[int]) -> str | None:
    """직전 7회 중앙값의 2배를 넘으면 경고 한 줄. FAIL 은 아니다."""
    window = [int(x) for x in (history or []) if isinstance(x, int) and x > 0]
    window = window[-SLOWDOWN_HISTORY:]
    median = median_of(window)
    if median is None or median <= 0:
        return None
    if elapsed_ms > median * SLOWDOWN_FACTOR:
        ratio = elapsed_ms / median
        return (f"{SLOWDOWN_LABEL} {name} elapsed_ms={elapsed_ms} "
                f"median_ms={median} samples={len(window)} ratio={ratio:.1f}")
    return None


# ------------------------------------------------------------------ 실행 이력
_ARTIFACT_FILE = "usage-metrics.json"
_METRICS_PREFIX = "daily-usage-metrics"


def fetch_recent_flow_durations(
    *,
    repo: str,
    workflow_file: str,
    before_run_id: str,
    token: str = "",
    limit: int = SLOWDOWN_HISTORY,
    timeout: float = 20.0,
) -> dict[str, list[int]]:
    """직전 실행들의 흐름별 소요 ms. 실패하면 조용히 빈 사전을 돌려준다.

    느려짐 경고는 부가 정보다. 이력 API 가 느리거나 막혀도 점검 판정에는
    영향이 없어야 하므로, 어떤 예외도 흐름을 FAIL 로 만들지 않는다.
    """
    token = token or os.environ.get("GITHUB_TOKEN", "")
    if not token or not repo or not before_run_id:
        return {}
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PADIEM-daily-usage-metrics/1.0",
    }
    base = f"https://api.github.com/repos/{repo}"

    def _get_json(url: str) -> dict:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(2_000_000).decode("utf-8"))

    def _get_bytes(url: str) -> bytes:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(4_000_000)

    collected: dict[str, list[int]] = {}
    try:
        runs = _get_json(
            f"{base}/actions/workflows/{workflow_file}/runs"
            f"?branch=main&status=success&per_page={max(limit * 2, 10)}"
        ).get("workflow_runs", [])
        previous = [run for run in runs
                    if str(run.get("id", "")) != str(before_run_id)]
        previous = previous[:limit]
        for run in reversed(previous):  # 가장 오래된 것부터 쌓는다
            run_id = run.get("id")
            if not run_id:
                continue
            artifacts = _get_json(f"{base}/actions/runs/{run_id}/artifacts") \
                .get("artifacts", [])
            chosen = next((item for item in artifacts
                           if str(item.get("name", "")).startswith(_METRICS_PREFIX)), None)
            if not chosen or not chosen.get("archive_download_url"):
                continue
            archive = zipfile.ZipFile(io.BytesIO(_get_bytes(chosen["archive_download_url"])))
            member = next((name for name in archive.namelist()
                           if name.endswith(_ARTIFACT_FILE)), None)
            if member is None:
                continue
            payload = json.loads(archive.read(member).decode("utf-8"))
            for name, row in (payload.get("flows") or {}).items():
                value = row.get("elapsed_ms") if isinstance(row, dict) else None
                if isinstance(value, int) and value > 0:
                    collected.setdefault(str(name), []).append(value)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, zipfile.BadZipFile):
        return {name: values[-limit:] for name, values in collected.items()}
    return {name: values[-limit:] for name, values in collected.items()}


# ------------------------------------------------------------------ 캡처 이름
def artifact_filename(flow: str, step: int, name: str) -> str:
    """흐름_단계번호_단계이름.png — 예: browser_chat_01_open.png"""
    safe_flow = re.sub(r"[^a-z0-9_]+", "_", flow.strip().lower()).strip("_")
    safe_name = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")
    return f"{safe_flow}_{int(step):02d}_{safe_name or 'step'}.png"


# ------------------------------------------------------------------ 실행기
_MASK_SCRIPT = """
(username) => {
  const EMAIL = /[\\w.+-]+@[\\w-]+\\.[\\w.-]+/;
  const ACCOUNT_KEYS = /(account|email|profile|avatar|user-name)/i;
  const painted = [];
  const paint = (node, why) => {
    if (!node) return;
    node.style.filter = 'blur(7px)';
    node.setAttribute('data-qa-masked', why);
    painted.push(why);
  };
  ['accountName', 'accountAvatar', 'accountTitle', 'accountDeleteConfirmEmail',
   'accountSharedDeleteConfirmEmail'].forEach((id) => paint(document.getElementById(id), id));
  document.querySelectorAll('[data-locale-key], .user-profile-chip, .account-row, .settings-account')
    .forEach((node) => {
      const key = node.getAttribute('data-locale-key') || node.className || '';
      if (ACCOUNT_KEYS.test(key)) paint(node, 'account-ui');
    });
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const value = (node.nodeValue || '').trim();
    if (!value) continue;
    const looksLikeEmail = EMAIL.test(value);
    const looksLikeAccount = username && value.includes(username);
    if (looksLikeEmail || looksLikeAccount) paint(node.parentElement, 'text');
  }
  return painted.length;
}
"""

_ANSWER_JS = """
() => {
  const rows = Array.from(document.querySelectorAll('.assistant-message .assistant-content'));
  if (!rows.length) return {text: '', product: ''};
  const last = rows[rows.length - 1];
  const article = last.closest('.assistant-message');
  const label = article ? article.querySelector('[data-assistant-product]') : null;
  return {text: (last.innerText || '').trim(), product: label ? (label.textContent || '').trim() : ''};
}
"""

_APP_JS_URLS_JS = """
() => {
  const seen = new Set();
  performance.getEntriesByType('resource').forEach((entry) => {
    if (/(^|\\/)app\\.js(\\?|$)/.test(entry.name)) seen.add(entry.name);
  });
  document.querySelectorAll('script[src]').forEach((node) => {
    if (/(^|\\/)app\\.js(\\?|$)/.test(node.src)) seen.add(node.src);
  });
  return Array.from(seen);
}
"""


def _error_codes(events: list[tuple[str, str, str]]) -> list[str]:
    """허용 목록에 걸리지 않는 콘솔 오류의 안전 코드 목록."""
    codes = []
    for kind, text, url in events:
        if console_allow_reason(url, text) is not None:
            continue
        codes.append(console_ok([(kind, text, url)])[1])
    return codes


class BrowserFlowResult:
    """한 브라우저 흐름의 결과. 값은 앞부분만 남긴다."""

    def __init__(self, name: str):
        self.name = name
        self.verdict = "FAIL"
        self.code = "flow_not_run"
        self.head = ""
        self.elapsed_ms = 0
        self.captures: list[str] = []
        self.console_errors: list[str] = []

    def pass_(self, head: str = "", code: str = "none") -> None:
        self.verdict, self.code, self.head = "PASS", code, head

    def skip(self, code: str) -> None:
        self.verdict, self.code, self.head = "SKIPPED", code, ""

    def fail(self, code: str) -> None:
        self.verdict, self.code, self.head = "FAIL", code, ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "verdict": self.verdict,
            "code": self.code if _SAFE_CODE.match(self.code or "") else "unsafe_code",
            "head": self.head,
            "elapsed_ms": self.elapsed_ms,
            "captures": list(self.captures),
            "console_errors": list(self.console_errors),
        }


def _capture(page, out_dir: Path, flow: BrowserFlowResult, step: int, name: str,
             username: str) -> None:
    """계정 표시를 흐리게 만든 뒤 1440 폭 한 화면을 남긴다."""
    try:
        page.evaluate(_MASK_SCRIPT, username)
    except Exception:
        # 가리기가 실패하면 캡처를 남기지 않는다. 계정이 보이는 캡처보다 없다.
        return
    path = out_dir / artifact_filename(flow.name, step, name)
    page.screenshot(path=str(path), full_page=False)
    flow.captures.append(path.name)


def _console_events(page, sink: list[tuple[str, str, str]]) -> None:
    def on_console(message):
        try:
            if message.type != "error":
                return
            location = message.location or {}
            sink.append(("console", (message.text or "")[:200], str(location.get("url") or "")))
        except Exception:
            sink.append(("console", "", ""))

    def on_pageerror(error):
        sink.append(("pageerror", str(error)[:200], ""))

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)


def _submit(page, prompt: str) -> None:
    page.fill("#messageInput", prompt)
    page.click("#sendButton")


def _answer_text(page) -> dict:
    return page.evaluate(_ANSWER_JS)


def _wait_answer(page) -> dict:
    deadline = time.monotonic() + ANSWER_WAIT_SECONDS
    payload = {"text": "", "product": ""}
    while time.monotonic() < deadline:
        payload = _answer_text(page)
        if len((payload.get("text") or "").strip()) >= HEAD_CHAT:
            return payload
        page.wait_for_timeout(1000)
    return payload


def run_browser_flows(
    *,
    cookie: str,
    out_dir: str | os.PathLike[str],
    head_version: str,
    recent_versions: list[str] | tuple[str, ...] = (),
    username: str = "",
) -> dict[str, dict]:
    """세 흐름을 실제 화면에서 돌리고 결과를 돌려준다.

    로그인은 이미 검증된 API 로그인 도우미(1차 `_login`)가 받은 세션 쿠키를
    브라우저 컨텍스트에 그대로 넣는다. 새 로그인 틀을 만들지 않는다.
    """
    from playwright.sync_api import sync_playwright

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    results: dict[str, BrowserFlowResult] = {
        "browser_chat": BrowserFlowResult("browser_chat"),
        "browser_claw": BrowserFlowResult("browser_claw"),
        "browser_stamp": BrowserFlowResult("browser_stamp"),
    }
    sink: list[tuple[str, str, str]] = []

    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(args=["--no-sandbox"])
        try:
            context = browser.new_context(viewport=VIEWPORT, locale="ko-KR")
            context.add_cookies([{
                "name": "padiem_session",
                "value": cookie,
                "domain": "chat.padiem.net",
                "path": "/",
                "httpOnly": True,
                "secure": True,
                "sameSite": "Lax",
            }])
            page = context.new_page()
            page.set_default_timeout(SELECTOR_TIMEOUT_MS)
            _console_events(page, sink)

            chat = results["browser_chat"]
            started = time.monotonic()
            mark = len(sink)
            try:
                page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
                page.wait_for_selector("#composerForm", state="visible")
                _capture(page, out_path, chat, 1, "open", username)
                _submit(page, CHAT_PROMPT)
                _capture(page, out_path, chat, 2, "question", username)
                answer = _wait_answer(page)
                _capture(page, out_path, chat, 3, "answer", username)
                verdict, code, head = answer_verdict(answer.get("text"))
                if verdict == "PASS":
                    chat.pass_(head, code)
                else:
                    chat.fail(code)
            except Exception as exc:
                chat.fail(f"browser_chat_{type(exc).__name__}")
            chat.elapsed_ms = int((time.monotonic() - started) * 1000)
            chat.console_errors = _error_codes(sink[mark:])
            if chat.verdict == "PASS" and chat.console_errors:
                # 콘솔 오류 0 이 이 흐름의 판정 조건이다. 답이 와도 오류가 있으면 FAIL.
                chat.fail(chat.console_errors[0])

            claw = results["browser_claw"]
            started = time.monotonic()
            claw_mark = len(sink)
            try:
                page.click("#clawNavButton")
                page.wait_for_selector("#clawWorkspace", state="visible")
                _capture(page, out_path, claw, 1, "open", username)
                _submit(page, CLAW_PROMPT)
                _capture(page, out_path, claw, 2, "question", username)
                answer = _wait_answer(page)
                _capture(page, out_path, claw, 3, "answer", username)
                verdict, code, head = answer_verdict(answer.get("text"))
                if verdict == "PASS":
                    claw.pass_(head, code)
                else:
                    claw.fail(code)
            except Exception as exc:
                claw.fail(f"browser_claw_{type(exc).__name__}")
            claw.elapsed_ms = int((time.monotonic() - started) * 1000)
            claw.console_errors = _error_codes(sink[claw_mark:])
            if claw.verdict == "PASS" and claw.console_errors:
                claw.fail(claw.console_errors[0])

            stamp = results["browser_stamp"]
            started = time.monotonic()
            try:
                urls = page.evaluate(_APP_JS_URLS_JS) or []
                observed = ""
                for url in urls:
                    observed = stamp_from_url(url)
                    if observed:
                        break
                _capture(page, out_path, stamp, 1, "app-version", username)
                verdict, code = stamp_verdict(observed, head_version, recent_versions)
                stamp.pass_(observed, code) if verdict == "PASS" else stamp.fail(code)
            except Exception as exc:
                stamp.fail(f"browser_stamp_{type(exc).__name__}")
            stamp.elapsed_ms = int((time.monotonic() - started) * 1000)
        finally:
            browser.close()

    # 대표 결정: Chat 과 Claw 는 기능이 같다. 한쪽만 답하면 그 흐름은 FAIL.
    chat, claw = results["browser_chat"], results["browser_claw"]
    if chat.verdict in ("PASS", "FAIL") and claw.verdict in ("PASS", "FAIL"):
        ok, code = screen_parity(chat.verdict, claw.verdict)
        if not ok:
            target = claw if "claw_only" in code else chat
            target.fail(code)

    return {name: flow.as_dict() for name, flow in results.items()}
