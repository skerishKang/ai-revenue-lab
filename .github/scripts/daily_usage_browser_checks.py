#!/usr/bin/env python3
"""#6724 2차: 브라우저 실사용 흐름·캡처·느려짐 경고 (#6724, CTO 2026-11-10).

1차(`daily_real_usage_check.py`)는 API 수준에서 네 흐름을 실제 결과값으로
판정한다. 2차는 같은 러너에서 운영 화면(chat.padiem.net)을 실제로 열어 세
가지를 더 본다:

  browser_chat   로그인된 화면에서 질문 1개 → 답 글자 10자 이상 + 콘솔 오류 0
  browser_claw   같은 계정으로 Claw 화면에서 질문 1개 → 답 표시
                 (Chat 과 Claw 는 기능이 같다는 대표 결정: 한쪽만 되면 FAIL)
  browser_stamp  화면이 실제로 불러온 app.js 의 ?v= 스탬프 커밋 이후에 화면 배포
                 대상 경로가 바뀌었는지(6시간 배포 창을 넘겼는지)

이 파일은 두 층으로 나뉜다.

  * 판정 함수(answer_verdict, answer_is_error_text, console_ok, stamp_verdict,
    slowdown_note, artifact_filename …)는 브라우저 없이 직접 호출할 수 있는
    순수 함수다. 오류 문구 목록은 static/locale.js 에서 읽는다(하드코딩 없음).
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

import functools
import io
import json
import os
import re
import statistics
import subprocess
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

# 오류 문구 거부 목록은 화면 문구 정의에서 읽는다(하드코딩 금지).
# 오류일 때 답 자리에 뜨는 글자는 static/locale.js 의 문구이고, app.js 의 오류
# 상자(buildRetryBox, app.js:938)가 같은 키를 쓴다. 실행 42680137340 은
# "답변을 불러오지 못했습니다. ..." 를 12자 넘는 답으로 오인해 PASS 로 기록했다.
STATIC_DIR = Path(__file__).resolve().parents[2] / "apps" / "padiem-chat" / "static"
ERROR_TEXT_KEY = re.compile(
    r"(load-failed|read-failed|save-failed|delete-failed|failed|error|unavailable|expired|rejected|invalid|cancelled)",
    re.I,
)
# 너무 짧은 값(?세션 만료?)은 정상 답변에도 부분 일치해 오판을 만든다.
ERROR_TEXT_MIN_CHARS = 10
NAVIGATE_TIMEOUT_MS = 60_000
SELECTOR_TIMEOUT_MS = 30_000

SLOWDOWN_FACTOR = 2.0
SLOWDOWN_HISTORY = 7
SLOWDOWN_LABEL = "SLOWDOWN_WARNING"

# Claw 진입 예산. #padiem-claw 해시만으로는 #clawWorkspace 가 hidden 인 채로
# 남고, 사이드바 클릭이 있어야 열린다. 예전에는 보임 확인이 30초를 기다린 뒤
# 클릭해서 Claw 소요가 통째로 30초 늘었다(실측: 클라이언트 대기 32~34초, 그 구간
# HTTP 0건). 이제 해시 이동 → 안 보이면 즉시 클릭 → 5초 안에 확인하고, 안 되면
# claw_entry_timeout 으로 FAIL 한다. 예산을 조용히 늘리지 않는다.
CLAW_ENTRY_BUDGET_MS = 5_000
ENTRY_IMMEDIATE_MS = 250

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
@functools.lru_cache(maxsize=8)
def static_error_texts(static_dir: str | None = None) -> tuple[str, ...]:
    """화면이 오류를 표시할 때 쓰는 문구 — static 문구 정의에서 읽는다.

    문구를 이 파일에 적어 두지 않는다. 제품이 문구를 바꾸면 목록도 같이
    따라가야 하고, 두 곳에 적으면 한쪽만 낡는다.
    """
    root = Path(static_dir) if static_dir else STATIC_DIR
    try:
        source = (root / "locale.js").read_text(encoding="utf-8")
    except OSError:
        return ()
    found: list[str] = []
    for key, value in re.findall(r'"([^"]+)"\s*:\s*"((?:[^"\\]|\\.)*)"', source):
        if not ERROR_TEXT_KEY.search(key):
            continue
        cleaned = re.sub(r"\s+", " ", value.replace('\\"', '"').replace("\\n", " ")).strip()
        if len(cleaned) >= ERROR_TEXT_MIN_CHARS:
            found.append(cleaned)
    return tuple(dict.fromkeys(found))


def answer_is_error_text(text: str | None, phrases: tuple[str, ...] | None = None) -> bool:
    """답 자리에 오류 문구가 있으면 True. 정상 답변에는 나타나지 않는 문장이다."""
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    if not flat:
        return False
    corpus = static_error_texts() if phrases is None else phrases
    for phrase in corpus:
        needle = re.sub(r"\s+", " ", phrase).strip().rstrip(".")
        if needle and needle in flat:
            return True
    return False


def answer_verdict(
    text: str | None,
    minimum: int = HEAD_CHAT,
    phrases: tuple[str, ...] | None = None,
) -> tuple[str, str, str]:
    """(판정, 코드, 앞부분). 화면에 뜬 글자가 기준이다."""
    flat = re.sub(r"\s+", " ", (text or "")).strip()
    if len(flat) < minimum:
        return "FAIL", "screen_answer_too_short", flat[:minimum]
    if answer_is_error_text(flat, phrases):
        return "FAIL", "answer_is_error_text", flat[:minimum]
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


def parity_target(code: str) -> str:
    """parity 실패 코드가 지목하는 흐름.

    `screen_parity_chat_only` 는 "Chat 만 답했다"이므로 잘못한 화면은 Claw 다.
    지목을 뒤집으면 멀쩡한 화면을 FAIL 로 기록한다(실제로 실행 42668928406 에서
    그렇게 기록됐다).
    """
    return "browser_claw" if code == "screen_parity_chat_only" else "browser_chat"


_MAX_CODE = 80


def safe_code(value: str) -> str:
    """어떤 문자열이든 소문자·숫자·밑줄의 안전 코드로 바꾼다.

    예외 클래스 이름에는 대문자가 섞인다(`browser_claw_Error`). 그대로 쓰면
    `_SAFE_CODE` 검사를 통과하지 못해 진단 정보가 `unsafe_code` 로 사라진다.
    """
    cleaned = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    if not cleaned:
        return "unknown"
    if not cleaned[0].isalpha():
        cleaned = f"e_{cleaned}"
    return cleaned[:_MAX_CODE]


# ------------------------------------------------------------------ 스탬프
def stamp_from_url(url: str | None) -> str:
    """app.js URL 의 ?v= 값. 없으면 빈 문자열."""
    match = _VERSION_IN_URL.search(url or "")
    return match.group(1) if match else ""


# 화면 배포 대상 경로. `deploy/chat-release/release_chat.ps1` 3단계의
# `git archive … -- apps/padiem-chat-front apps/padiem-chat/static apps/padiem-chat-pages`
# 와 같은 목록이다. 그 스크립트 헤더가 "화면 변경은 이 스크립트로만 배포된다"고
# 적고 있고, COM2 의 deploy_from_main.sh 는 채팅 런타임만 올린다. 목록이 갈라지면
# 이 판정이 조용히 틀리므로 시험이 release_chat.ps1 을 읽어 같음을 확인한다.
SCREEN_RELEASE_PATHS: tuple[str, ...] = (
    "apps/padiem-chat-front",
    "apps/padiem-chat/static",
    "apps/padiem-chat-pages",
)

# 스탬프 커밋 이후 화면 경로가 바뀐 커밋의 시각부터 이만큼까지는 배포가 진행 중인
# 창으로 본다. 넘으면 화면 배포 누락이다(#6724 CTO 지시).
SCREEN_LAG_LIMIT_SECONDS = 6 * 3600


def stamp_verdict(
    observed: str,
    head_sha: str,
    *,
    stamp_sha: str = "",
    screen_changes: list[tuple[str, int]] | None = None,
    ancestor: bool = True,
    now_epoch: int | None = None,
) -> tuple[str, str, str]:
    """(판정, 코드, 기록할 커밋).

    release_chat.ps1 은 배포 커밋의 앞 8자리로 정적 자산을 스탬프한다. 그래서
    화면의 스탬프는 "이 화면이 어느 커밋에서 나왔는가"다.

    이전 규칙(main 최근 30커밋 안이면 deploy_lag)은 화면 파일을 바꾼 PR 이
    머지되고 release 가 빠져도 30커밋 동안 잡지 못했다. 이제 스탬프 커밋과
    main 사이에서 **화면 배포 대상 경로**(SCREEN_RELEASE_PATHS)를 바꾼 커밋을
    센다.

    - 화면 경로를 바꾼 커밋이 없으면 PASS up_to_date: 화면은 최신이다.
    - 있으면 그중 가장 이른 커밋의 커밋(머지) 시각부터 지난 시간으로,
      6시간 이하면 PASS deploy_lag, 넘으면 FAIL screen_deploy_missing.
      기록에는 그 커밋의 앞 8자리를 남긴다(어느 변경이 배포에서 빠졌는지).
    - 스탬프 커밋을 저장소에서 찾지 못하면 FAIL screen_stamp_unknown.
    - 스탬프 커밋이 main 조상이 아니면 FAIL screen_stamp_not_on_main.
    - 이력을 읽지 못했으면(None) FAIL screen_history_unavailable:
      모르는 것을 통과시키지 않는다.
    """
    value = (observed or "").strip()
    if not value:
        return "FAIL", "screen_stamp_missing", ""
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", value):
        # 배포 스크립트는 SHA 앞 8자리를 넣는다. 그 모양이 아니면 다른 값이다.
        return "FAIL", "screen_stamp_malformed", value[:8]
    head = (head_sha or "").strip()[:8]
    if len(value) == 8 and head and value.lower() == head.lower():
        # 화면 스탬프가 main 그 자체다. 비교할 커밋이 없다.
        return "PASS", "up_to_date", value[:8]
    stamp = (stamp_sha or "").strip()
    if not stamp:
        return "FAIL", "screen_stamp_unknown", value[:8]
    if not ancestor:
        return "FAIL", "screen_stamp_not_on_main", stamp[:8]
    if screen_changes is None:
        return "FAIL", "screen_history_unavailable", stamp[:8]
    rollup = sorted(((str(sha).strip(), int(ts)) for sha, ts in screen_changes
                     if str(sha).strip()),
                    key=lambda item: item[1])
    if not rollup:
        return "PASS", "up_to_date", stamp[:8]
    first_sha, first_ts = rollup[0]
    clock = int(now_epoch if now_epoch is not None else time.time())
    if clock - first_ts <= SCREEN_LAG_LIMIT_SECONDS:
        return "PASS", "deploy_lag", first_sha[:8]
    return "FAIL", "screen_deploy_missing", first_sha[:8]


def _git(args: list[str], cwd: str | None = None) -> tuple[int, str]:
    """(종료 코드, 표준출력). git 이 없거나 실패해도 예외를 올리지 않는다."""
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                              text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return done.returncode, (done.stdout or "").strip()


def resolve_stamp_commit(prefix: str, cwd: str | None = None) -> str:
    """스탬프 앞 8자리 → 전체 SHA. 얕은 클론 밖이면 더 받아서 다시 찾는다.

    checkout 은 fetch-depth 30 이다. 스탬프 커밋이 그 밖이면 저장소에 객체가
    없으므로, 판정에 필요한 만큼만 더 받는다(--deepen, 안 되면 --unshallow).
    """
    value = (prefix or "").strip()
    if not value:
        return ""
    code, out = _git(["rev-parse", "--verify", "--quiet", f"{value}^{{commit}}"], cwd)
    if code == 0 and out:
        return out.splitlines()[0].strip()
    for fetch in (["fetch", "--deepen=500", "origin", "main"],
                  ["fetch", "--unshallow", "origin"]):
        _git(fetch, cwd)
        code, out = _git(["rev-parse", "--verify", "--quiet", f"{value}^{{commit}}"], cwd)
        if code == 0 and out:
            return out.splitlines()[0].strip()
    return ""


def screen_commits_since(stamp_sha: str, head: str = "HEAD",
                         cwd: str | None = None) -> list[tuple[str, int]] | None:
    """스탬프 커밋..head 사이에서 화면 배포 대상 경로를 바꾼 커밋 (오래된 순).

    각 항목은 (전체 SHA, 커밋 시각 epoch) 이다. squash 병합이면 커밋 시각이
    곧 머지 시각이다. None 은 "이력을 읽지 못했다"이며, 화면 최신 여부를 모르는
    상태이므로 판정에서 FAIL 로 다룬다.
    """
    if not (stamp_sha or "").strip():
        return None
    args = ["log", "--reverse", "--format=%H%x09%ct", f"{stamp_sha.strip()}..{head}",
            "--", *SCREEN_RELEASE_PATHS]
    code, out = _git(args, cwd)
    if code != 0:
        # 얕은 경계에 걸려 이력을 못 읽는 경우다. 한 번 전체 이력으로 재시도한다.
        _git(["fetch", "--unshallow", "origin"], cwd)
        code, out = _git(args, cwd)
        if code != 0:
            return None
    rows: list[tuple[str, int]] = []
    for line in out.splitlines():
        sha, _, stamp = line.partition("\t")
        if sha.strip() and stamp.strip().isdigit():
            rows.append((sha.strip(), int(stamp.strip())))
    return rows


def stamp_evidence(observed: str, head: str = "HEAD",
                   cwd: str | None = None) -> dict:
    """stamp_verdict 에 넘길 저장소 쪽 입력을 모은다(판정은 순수 함수가 한다)."""
    stamp_sha = resolve_stamp_commit(observed, cwd)
    ancestor = False
    screen_changes: list[tuple[str, int]] | None = None
    if stamp_sha:
        code, _ = _git(["merge-base", "--is-ancestor", stamp_sha, head], cwd)
        if code != 0:
            # 얕은 클론 경계는 조상 관계 증명을 막는다. 전체 이력으로 한 번 더.
            _git(["fetch", "--unshallow", "origin"], cwd)
            code, _ = _git(["merge-base", "--is-ancestor", stamp_sha, head], cwd)
        ancestor = code == 0
        if ancestor:
            screen_changes = screen_commits_since(stamp_sha, head, cwd)
    return {"stamp_sha": stamp_sha, "ancestor": ancestor,
            "screen_changes": screen_changes}


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
                value = history_sample(row)
                if value is not None:
                    collected.setdefault(str(name), []).append(value)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, zipfile.BadZipFile):
        return {name: values[-limit:] for name, values in collected.items()}
    return {name: values[-limit:] for name, values in collected.items()}


# ------------------------------------------------------------------ 캡처 이름
def entry_verdict(waited_ms: int | None,
                  budget_ms: int = CLAW_ENTRY_BUDGET_MS) -> tuple[str, str, int]:
    """(판정, 코드, 진입 ms). None 은 "예산 안에 안 보였다"이다.

    Claw 진입은 화면이 뜨는 시간만 본다. 예산을 넘기면 FAIL claw_entry_timeout
    이며, 기다리는 시간을 늘려 통과시키지 않는다.
    """
    if waited_ms is None:
        return "FAIL", "claw_entry_timeout", int(budget_ms)
    value = int(waited_ms)
    if value > budget_ms:
        return "FAIL", "claw_entry_timeout", value
    if value <= ENTRY_IMMEDIATE_MS:
        return "OK", "immediate", max(0, value)
    return "OK", "waited", max(0, value)


def history_sample(row: object) -> int | None:
    """느려짐 이력 표본. 행이 밝힌 기준(basis)만 쓴다.

    브라우저 흐름은 answer 구간(answer_ms)이 기준이고, 나머지 흐름은 총합이다.
    기준이 없는 옛 실행(총합만 있던 스키마)은 섞지 않는다 — 30초 진입 대기 같은
    옛 값이 새 answer 기준의 중앙값을 오염시키면 경고가 영영 안 울린다.
    """
    if not isinstance(row, dict):
        return None
    basis = row.get("basis")
    if basis == "answer":
        value = row.get("answer_ms")
    elif basis == "total":
        value = row.get("elapsed_ms")
    else:
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


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
        # 진입(화면이 뜨기까지)과 질문 전송~답 표시를 나눠 남긴다(#6724).
        self.entry_ms = 0
        self.answer_ms = 0
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
            "code": safe_code(self.code),
            "head": self.head,
            "elapsed_ms": self.elapsed_ms,
            "entry_ms": self.entry_ms,
            "answer_ms": self.answer_ms,
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


# 컴포저와 Claw 작업영역은 hidden 속성으로 열린다. CSS 레이아웃(offsetParent)
# 보다 hidden 이 실제 상태에 가깐다.
COMPOSER_VISIBLE_JS = """() => {
  const el = document.getElementById('composerForm');
  return !!el && el.offsetParent !== null;
}"""

CLAW_VISIBLE_JS = """() => {
  const el = document.getElementById('clawWorkspace');
  return !!el && !el.hidden;
}"""



def _visible_now(page, script: str) -> bool:
    try:
        return bool(page.evaluate(script))
    except Exception:
        return False


def _wait_visible(page, script: str, started: float, budget_ms: int) -> int | None:
    """예산 안에 보이면 기다린 ms, 끝내 안 보이면 None."""
    deadline = started + budget_ms / 1000.0
    while time.monotonic() < deadline:
        if _visible_now(page, script):
            return int((time.monotonic() - started) * 1000)
        page.wait_for_timeout(100)
    return None


def _open_claw(page, url: str, budget_ms: int = CLAW_ENTRY_BUDGET_MS) -> int | None:
    """Claw 화면 진입: 해시 이동 → 안 보이면 클릭 → 짧은 예산 안에서 확인.

    `#padiem-claw` 해시만으로는 `#clawWorkspace` 가 hidden 인 채로 남는다(실측:
    그 상태로 30초를 기다린 뒤 클릭해야 열렸고, 그동안 HTTP 요청은 0건이었다).
    그래서 이동 직후 보이지 않으면 곧바로 사이드바를 누르고, 예산은 짧게 둔다.
    """
    started = time.monotonic()
    page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
    if _visible_now(page, CLAW_VISIBLE_JS):
        return int((time.monotonic() - started) * 1000)
    remaining = budget_ms - int((time.monotonic() - started) * 1000)
    if remaining > 0:
        try:
            page.click("#clawNavButton", timeout=remaining)
        except Exception:
            pass
    return _wait_visible(page, CLAW_VISIBLE_JS, started, budget_ms)


def _finish(flow: BrowserFlowResult, started: float,
            sink: list[tuple[str, str, str]], mark: int) -> None:
    """소요 시간을 확정하고, 허용 목록 밖 콘솔 오류가 있으면 FAIL 로 내린다."""
    flow.elapsed_ms = int((time.monotonic() - started) * 1000)
    flow.console_errors = _error_codes(sink[mark:])
    if flow.verdict == "PASS" and flow.console_errors:
        flow.fail(flow.console_errors[0])


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
            stage = "open"
            answer_started = None
            try:
                page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
                page.wait_for_function(COMPOSER_VISIBLE_JS)
                chat.entry_ms = int((time.monotonic() - started) * 1000)
                _capture(page, out_path, chat, 1, "open", username)
                stage = "question"
                answer_started = time.monotonic()
                _submit(page, CHAT_PROMPT)
                _capture(page, out_path, chat, 2, "question", username)
                stage = "answer"
                answer = _wait_answer(page)
                chat.answer_ms = int((time.monotonic() - answer_started) * 1000)
                _capture(page, out_path, chat, 3, "answer", username)
                verdict, code, head = answer_verdict(answer.get("text"))
                if verdict == "PASS":
                    chat.pass_(head, code)
                else:
                    chat.fail(code)
            except Exception as exc:
                if answer_started is not None:
                    chat.answer_ms = int((time.monotonic() - answer_started) * 1000)
                # 어느 단계에서 깨졌는지가 진단의 전부다.
                chat.fail(safe_code(f"{chat.name}_{stage}_{type(exc).__name__}"))
            _finish(chat, started, sink, mark)

            claw = results["browser_claw"]
            started = time.monotonic()
            claw_mark = len(sink)
            stage = "open"
            answer_started = None
            try:
                # 해시로 먼저 들어가고, 안 보이면 곧바로 사이드바를 누른다. 그 뒤
                # 5초 예산 안에서만 보임을 확인한다 — 예산을 조용히 늘리지 않는다.
                waited = _open_claw(page, CHAT_URL + CLAW_HASH)
                claw.entry_ms = int((time.monotonic() - started) * 1000)
                state, entry_code, _ = entry_verdict(waited)
                _capture(page, out_path, claw, 1, "open", username)
                if state != "OK":
                    # 작업영역이 열리지 않았다. 화면 상태를 캡처해 두고 FAIL 한다.
                    claw.fail(entry_code)
                else:
                    stage = "question"
                    answer_started = time.monotonic()
                    _submit(page, CLAW_PROMPT)
                    _capture(page, out_path, claw, 2, "question", username)
                    stage = "answer"
                    answer = _wait_answer(page)
                    claw.answer_ms = int((time.monotonic() - answer_started) * 1000)
                    _capture(page, out_path, claw, 3, "answer", username)
                    verdict, code, head = answer_verdict(answer.get("text"))
                    if verdict != "PASS":
                        claw.fail(code)
                    else:
                        product = (answer.get("product") or "").strip()
                        if product and "claw" not in product.lower():
                            # 같은 셸을 쓰지만 답한 제품은 분리해 기록한다.
                            claw.fail("screen_wrong_product")
                        else:
                            claw.pass_(head, code)
            except Exception as exc:
                if answer_started is not None:
                    claw.answer_ms = int((time.monotonic() - answer_started) * 1000)
                claw.fail(safe_code(f"{claw.name}_{stage}_{type(exc).__name__}"))
            _finish(claw, started, sink, claw_mark)

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
                evidence = stamp_evidence(observed)
                verdict, code, blame = stamp_verdict(observed, head_version, **evidence)
                if verdict == "PASS":
                    stamp.pass_(blame or observed, code)
                else:
                    # 스탬프는 배포 SHA 앞 8자리 조각이다. 쿠키·토큰이 아니므로
                    # 어느 커밋 화면인지(지목된 커밋) 진단에 남긴다.
                    stamp.head = blame or observed
                    stamp.fail(code)
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
            # 한쪽만 답한 경우다. 원인 코드를 이미 가진 흐름은 덮어쓰지 않는다.
            target = results[parity_target(code)]
            if target.verdict != "FAIL":
                target.fail(code)

    return {name: flow.as_dict() for name, flow in results.items()}
