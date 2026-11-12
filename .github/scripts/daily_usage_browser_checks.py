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
  browser_shared_login  공통 로그인(padiem-auth 이메일) → /api → 공통 로그아웃
                 (#7078 양성 표본. 쿠키 이름만 보고, 값은 읽지도 적지도 않음.
                 로그아웃 판정은 #7334가 운영에 실렸을 때만 의미가 있으므로
                 padiem_session을 심어 배포 여부를 흐름 안에서 판별한다)

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

# #7449(2026-11-11 CTO 결정)로 QA 계정은 용도별로 분리됐고, 이 브라우저 점검도
# daily_real_usage_check.py 가 import 하는 것과 같은 전용 smoke 쌍을 읽는다
# (#7503, #7440 4번). 옛 이름(B66_CGI_ALPHA_*)은 production 환경 변수·시크릿이라
# 이 점검의 워크플로는 더는 넘기지 않는다 — 이름이 어긋나면 browser_shared_login
# 이 매번 SKIPPED qa_credential_missing 이 된다. 값은 절대 출력하지 않는다.
QA_USERNAME_ENV = "QA_SMOKE_USERNAME"
QA_PASSWORD_ENV = "QA_SMOKE_PASSWORD"

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


# ------------------------------------------------------------------ 공통 로그인
# 브라우저 흐름 browser_shared_login (#7078): 공통 로그인(padiem-auth 이메일
# 로그인)으로 실제로 로그인하고, 쿠키 "이름"만으로 공통 3종을 확인한다.
# 쿠키 값은 읽지도 적지도 않는다. 로그아웃 판정은 #7334(공통 로그아웃이
# padiem_session도 지운다)가 운영에 실렸을 때만 의미가 있으므로, 흐름 안에서
# 배포 여부를 판별한다. 스탬프(?v=)·버전 엔드포인트로는 런타임 배포를 알 수
# 없다 — `?v=` 스탬프는 화면 배포만 가리키고 `/health`·응답 헤더·
# `/api/auth/status` 어디에도 런타임 SHA가 없다. 그래서 padiem_session을
# 일부러 심어 공통 로그아웃이 그 쿠키도 지우는지로 판별한다. 판별에 쓴
# padiem_session은 같은 흐름 안에서 반드시 정리(레거시 로그아웃)한다.
SHARED_ACCESS_COOKIE = "__Host-padiem-shared-access"
SHARED_REFRESH_COOKIE = "padiem_shared_refresh"
SHARED_MARKER_COOKIE = "__Host-padiem-shared-marker"
SHARED_COOKIE_NAMES = (SHARED_ACCESS_COOKIE, SHARED_REFRESH_COOKIE, SHARED_MARKER_COOKIE)
PADIEM_SESSION_COOKIE = "padiem_session"
SHARED_LOGOUT_PATH = "/auth/shared/logout"
LEGACY_LOGOUT_PATH = "/api/auth/logout"
SHARED_STATUS_PATH = "/api/auth/status"
SHARED_AUTH_HOST = "auth.padiem.net"


_SHARED_EMAIL_SHAPE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def shared_credential_ok(value) -> bool:
    """padiem-auth 이메일 로그인에 쓸 수 있는 자격 모양인가.

    모양만 본다(값은 기록하지 않는다). padiem-auth의 이메일 칸은 type=email이고
    인증 자격 RPC도 이메일 형태를 요구한다. 레거시 Chat 로그인은 username을
    쓰므로, 같은 자격이 padiem-auth에서는 통과하지 못할 수 있다.
    """
    if not isinstance(value, str):
        return False
    return bool(_SHARED_EMAIL_SHAPE.fullmatch(value.strip()))


def _name_set(names) -> set[str]:
    return {str(name) for name in (names or ()) if isinstance(name, str) and name}


def shared_access_cookie_verdict(names) -> tuple[str, str]:
    """(판정, 코드). 쿠키 "이름" 목록에 공통 access 쿠키가 있는가."""
    present = _name_set(names)
    if SHARED_ACCESS_COOKIE in present:
        return "PASS", "none"
    return "FAIL", "shared_cookie_missing"


def shared_status_verdict(authenticated, stage: str) -> tuple[str, str]:
    """(판정, 코드). stage는 after_login(참이어야) 또는 after_logout(거짓이어야)."""
    flag = bool(authenticated)
    if stage == "after_login":
        return ("PASS", "none") if flag else ("FAIL", "shared_api_unauthenticated")
    if stage == "after_logout":
        return ("PASS", "none") if not flag else ("FAIL", "logout_still_authenticated")
    raise ValueError("unknown_shared_stage")


def shared_logout_verdict(names) -> tuple[str, str, str]:
    """(판정, 코드, head). 공통 로그아웃 직후 쿠키 "이름" 목록으로 판정한다.

    - 공통 3종 중 하나라도 남았으면 FAIL logout_residue. head에 남은 "이름"만
      남긴다(값 아님).
    - 공통 3종은 지워졌고 padiem_session만 남았으면 SKIPPED not_deployed.
      운영 런타임이 #7334 이전이라는 뜻이다.
    - 모두 없으면 PASS none.
    """
    present = _name_set(names)
    residue = [name for name in SHARED_COOKIE_NAMES if name in present]
    if PADIEM_SESSION_COOKIE in present:
        residue.append(PADIEM_SESSION_COOKIE)
    if any(name in SHARED_COOKIE_NAMES for name in residue):
        return "FAIL", "logout_residue", "remaining=" + ",".join(residue)
    if residue:
        return "SKIPPED", "not_deployed", ""
    return "PASS", "none", ""


#: #7364: the three Google rows whose workspace truth must resolve on a
#: shared-login session. A verified answer may be connected / not_connected /
#: ambiguous; only "unverified" means the shadow-backed authority was not
#: reached.
SHARED_GOOGLE_ROWS = (
    "connector:google:gmail@1",
    "connector:google:drive@1",
    "connector:google:calendar@1",
)

_SHARED_ENDPOINTS_JS = """
async () => {
  const out = { devices: 0, connectors: 0, rows: [] };
  try {
    const r = await fetch('/api/claw/local-access/devices',
      { headers: { Accept: 'application/json' }, cache: 'no-store' });
    out.devices = r.status;
  } catch { out.devices = -1; }
  try {
    const r = await fetch('/api/connectors/status',
      { headers: { Accept: 'application/json' }, cache: 'no-store' });
    out.connectors = r.status;
    if (r.status === 200) {
      const d = await r.json();
      const rows = Array.isArray(d && d.connectors) ? d.connectors : [];
      out.rows = rows.map((x) => ({
        connector_id: x && x.connector_id,
        workspace_state: x && x.workspace_state,
      }));
    }
  } catch { out.connectors = -1; }
  return out;
}
"""


def shared_endpoint_verdict(devices_status, rows) -> tuple[str, str, str]:
    """(#7364) 공유 로그인 세션의 두 표면 판정. 값은 세지 않고 상태만 본다.

    기대: devices 200, 그리고 Gmail·Drive·Calendar 세 행이 모두 존재하며
    `workspace_state`가 `unverified`가 아님. 판정 문구에는 상태 코드·개수만
    넣는다(세션·워크스페이스·계정 값 없음).
    """
    if devices_status != 200:
        return "FAIL", "shared_devices_%s" % (devices_status,), "devices=%s" % (devices_status,)
    by_id = {}
    for row in rows if isinstance(rows, list) else ():
        if isinstance(row, dict) and isinstance(row.get("connector_id"), str):
            by_id[row["connector_id"]] = row.get("workspace_state")
    missing = [cid for cid in SHARED_GOOGLE_ROWS if cid not in by_id]
    unverified = [
        cid for cid in SHARED_GOOGLE_ROWS
        if cid in by_id and by_id[cid] == "unverified"
    ]
    head = "devices=200 rows=%d" % (len(by_id),)
    if missing:
        return "FAIL", "shared_connector_rows_missing", head
    if unverified:
        return "FAIL", "shared_connectors_unverified", head
    return "PASS", "none", head



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
  // 대화 목록 제목도 계정 식별 요소다(제목에 이름·업무가 들어간다). 목록이
  // 캡처 직전에 비동기로 다시 그려져도 가려지도록 컨테이너 자체를 흐리게 한다
  // (자식에게 함께 적용된다). 필터만 바꾸므로 클릭·목록 동작은 그대로다.
  paint(document.getElementById('historyList'), 'history-list');
  document.querySelectorAll('#historyList .history-row, #historyList .history-item')
    .forEach((node) => paint(node, 'history-title'));
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

_AUTH_MASK_JS = """
() => {
  ['email', 'password', 'name'].forEach((id) => {
    const node = document.getElementById(id) || document.querySelector('input[name="' + id + '"]');
    if (node) node.style.filter = 'blur(7px)';
  });
}
"""

_STATUS_JS = """
() => fetch('/api/auth/status', { headers: { Accept: 'application/json' }, cache: 'no-store' })
  .then((response) => response.json())
  .catch(() => null)
"""

_LOGOUT_JS = """
(path) => fetch(path, { method: 'POST', headers: { Accept: 'application/json' } })
  .then((response) => response.status)
  .catch(() => 0)
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
        # 목록·프로필이 캡처 직전에 늦게 그려진 경우가 있었다(run 43140652821).
        # 한 프레임 기다렸다가 한 번 더 가린 뒤 찍는다.
        page.wait_for_timeout(100)
        page.evaluate(_MASK_SCRIPT, username)
    except Exception:
        # 가리기가 실패하면 캡처를 남기지 않는다. 계정이 보이는 캡처보다 없다.
        return
    path = out_dir / artifact_filename(flow.name, step, name)
    page.screenshot(path=str(path), full_page=False)
    flow.captures.append(path.name)


# ------------------------------------------------------------------ 튜토리얼 대본
# #6724 2차: 단계 이름·설명을 코드 안 대본으로 둔다. 캡처와 1:1로 맞춰 두고,
# 문서 생성기는 실제로 남은 캡처만 문서에 넣는다(가리기 실패로 캡처를 건너뛴
# 단계는 문서에서도 빠진다).
TUTORIAL_TITLES = {
    "browser_chat": "Chat으로 질문하고 답 받기",
    "browser_claw": "Claw로 작업 요청하고 결과 받기",
    "browser_shared_login": "공통 로그인으로 들어가고 나오기",
}

TUTORIAL_STEPS: dict[str, tuple[tuple[int, str, str, str], ...]] = {
    "browser_chat": (
        (1, "open", "Chat 첫 화면", "로그인된 세션으로 Chat 첫 화면이 열린다."),
        (2, "question", "질문 입력", "질문을 입력하고 전송 버튼을 누른다."),
        (3, "answer", "답변 표시", "답변이 화면에 표시될 때까지 기다린다."),
    ),
    "browser_claw": (
        (1, "open", "Claw 작업영역", "사이드바에서 Claw 작업영역을 연다."),
        (2, "question", "작업 요청 입력", "Claw에 작업을 요청한다."),
        (3, "answer", "작업 결과 표시", "작업 결과가 화면에 표시될 때까지 기다린다."),
    ),
    "browser_shared_login": (
        (1, "open", "Chat 첫 화면", "공통 로그인 전 Chat 첫 화면이 열린다."),
        (2, "padiem-auth", "공통 로그인 화면", "padiem-auth 이메일 로그인 화면으로 이동한다."),
        (3, "callback", "로그인 완료", "로그인을 마치고 Chat으로 돌아온 화면이다."),
    ),
}


def tutorial_markdown(flow: str, verdict: str, captures: list[str],
                      elapsed_ms: int = 0, entry_ms: int = 0,
                      answer_ms: int = 0) -> str | None:
    """흐름 하나의 튜토리얼 초안. PASS 가 아니면 문서를 만들지 않는다(None)."""
    steps = TUTORIAL_STEPS.get(flow)
    if verdict != "PASS" or not steps:
        return None
    present = set(captures or [])
    lines = [f"# {TUTORIAL_TITLES[flow]}", "",
             "이 문서는 매일 실사용 점검 실행에서 자동으로 만든 초안입니다.", ""]
    used = 0
    for step, slug, title, description in steps:
        image = artifact_filename(flow, step, slug)
        if image not in present:
            continue
        used += 1
        lines += [f"## {used}. {title}", "", description, "",
                  f"![{title}](./{image})", ""]
    if used == 0:
        return None
    lines += ["## 걸린 시간", "",
              f"- 전체: {int(elapsed_ms)} ms",
              f"- 화면 진입: {int(entry_ms)} ms",
              f"- 질문에서 답까지: {int(answer_ms)} ms", ""]
    return "\n".join(lines)


def write_tutorials(results: dict[str, dict], out_dir: Path) -> list[str]:
    """흐름별 Markdown 초안 + 색인. 실패 흐름은 문서 없이 색인에만 적는다."""
    written: list[str] = []
    index = ["# 실사용 점검 튜토리얼 초안", "",
             "자동 생성 문서입니다. 실패한 흐름은 문서를 만들지 않습니다.", ""]
    for flow in TUTORIAL_STEPS:
        payload = results.get(flow) or {}
        doc = tutorial_markdown(
            flow,
            str(payload.get("verdict") or "FAIL"),
            list(payload.get("captures") or []),
            int(payload.get("elapsed_ms") or 0),
            int(payload.get("entry_ms") or 0),
            int(payload.get("answer_ms") or 0),
        )
        if doc is None:
            index.append(f"- {flow}: 이번 실행 실패 (문서를 만들지 않았습니다)")
            continue
        name = f"tutorial-{flow}.md"
        (out_dir / name).write_text(doc, encoding="utf-8")
        written.append(name)
        index.append(f"- [{flow}](./{name})")
    index.append("")
    (out_dir / "tutorial-index.md").write_text("\n".join(index), encoding="utf-8")
    written.append("tutorial-index.md")
    return written


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


def _shared_cookie_names(context) -> list[str]:
    """chat.padiem.net 쿠키의 "이름"만. 값은 읽지 않고 로그에도 남기지 않는다."""
    names: list[str] = []
    try:
        cookies = context.cookies()
    except Exception:
        return names
    for cookie in cookies:
        domain = str(cookie.get("domain", ""))
        name = cookie.get("name")
        if domain.endswith("chat.padiem.net") and isinstance(name, str) and name:
            names.append(name)
    return names


def _plant_legacy_session(context) -> None:
    """Flow 1과 같은 QA 자격으로 로그인해 padiem_session을 심는다.

    로그아웃 판정을 공허한 통과로 기록하지 않기 위한 배포 판별 장치다.
    옛 같은 호스트 API 로그인(/api/auth/password/login)은 공통 로그인 전환
    뒤 409 email_login_moved를 반환한다(#7449; 실행 43069955981에서 재확인).
    그래서 심기도 공통 로그인 클라이언트(login_session_cookie)로 한다 —
    스위치가 끝났으면 레거시 경로를, 409 email_login_moved면 공통 로그인
    폼을 따라가고 둘 다 padiem_session을 돌려준다. 판별에 쓴 세션은 같은
    흐름 안에서 레거시 로그아웃으로 정리한다.
    """
    from shared_login_client import SharedLoginError, login_session_cookie

    username = os.environ.get(QA_USERNAME_ENV, "")
    password = os.environ.get(QA_PASSWORD_ENV, "")
    try:
        cookie = login_session_cookie(ORIGIN, username, password)
    except SharedLoginError:
        raise RuntimeError("legacy_plant_login_refused") from None
    if not cookie:
        raise RuntimeError("legacy_plant_login_refused")
    context.add_cookies([{
        "name": PADIEM_SESSION_COOKIE,
        "value": cookie,
        "domain": "chat.padiem.net",
        "path": "/",
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }])


def _run_shared_login_flow(browser, chat_url: str, out_path: Path,
                           flow: "BrowserFlowResult", username: str,
                           console_sink: list) -> None:
    """공통 로그인(padiem-auth 이메일) 한 바퀴. 판정은 위의 순수 함수가 한다.

    캡처·가리기·콘솔 오류 규칙은 기존 브라우저 흐름과 같다. 공통 로그인은
    padiem_session을 만들지 않으므로 판별 전 브라우저에는 padiem_session이
    없다. 공통 로그아웃만 호출한다(UI 로그아웃은 레거시 경로까지 부르므로
    판별이 공허해진다).
    """
    qa_username = os.environ.get(QA_USERNAME_ENV, "")
    qa_password = os.environ.get(QA_PASSWORD_ENV, "")
    if not qa_username or not qa_password:
        flow.skip("qa_credential_missing")
        return
    if not shared_credential_ok(qa_username):
        # #6720 계약: 이 흐름에 쓸 자격이 없는 것과 같다. 실제 흐름 실패가
        # 아니므로 경보가 아니라 건너뜀으로 기록한다.
        flow.skip("qa_credential_not_email")
        return

    started = time.monotonic()
    context = browser.new_context(viewport=VIEWPORT, locale="ko-KR")
    page = context.new_page()
    page.set_default_timeout(SELECTOR_TIMEOUT_MS)
    _console_events(page, console_sink)
    stage = "open"
    try:
        page.goto(chat_url, wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
        _capture(page, out_path, flow, 1, "open", username)
        stage = "entry"
        page.goto(chat_url.rstrip("/") + "/auth/shared/start",
                  wait_until="domcontentloaded", timeout=NAVIGATE_TIMEOUT_MS)
        page.wait_for_url(lambda url: url.startswith(f"https://{SHARED_AUTH_HOST}/"),
                          timeout=NAVIGATE_TIMEOUT_MS)
        flow.entry_ms = int((time.monotonic() - started) * 1000)
        stage = "email"
        page.evaluate(_AUTH_MASK_JS)
        page.fill('input[name="email"]', qa_username)
        page.fill('input[name="password"]', qa_password)
        _capture(page, out_path, flow, 2, "padiem-auth", username)
        stage = "callback"
        page.click('form[action^="/login/password"] button[type="submit"]')
        page.wait_for_load_state("load", timeout=NAVIGATE_TIMEOUT_MS)
        deadline = time.monotonic() + 30.0
        names: list[str] = []
        while time.monotonic() < deadline:
            names = _shared_cookie_names(context)
            if SHARED_ACCESS_COOKIE in names:
                break
            page.wait_for_timeout(500)
        _capture(page, out_path, flow, 3, "callback", username)
        verdict, code = shared_access_cookie_verdict(names)
        if verdict != "PASS":
            flow.fail(code)
            return
        stage = "api"
        answer_started = time.monotonic()
        api = page.evaluate(_STATUS_JS)
        flow.answer_ms = int((time.monotonic() - answer_started) * 1000)
        verdict, code = shared_status_verdict(
            bool(api and api.get("authenticated")), "after_login")
        if verdict != "PASS":
            flow.fail(code)
            return
        # #7364: the same shared-login session must resolve the PC device
        # directory and the three workspace-backed connector rows. Recorded
        # before the logout (the session is gone afterwards) and judged at the
        # end so the logout stage is always exercised.
        stage = "endpoints"
        probe = page.evaluate(_SHARED_ENDPOINTS_JS) or {}
        endpoint_verdict, endpoint_code, endpoint_head = shared_endpoint_verdict(
            probe.get("devices"), probe.get("rows"))
        stage = "logout"
        _plant_legacy_session(context)
        page.evaluate(_LOGOUT_JS, SHARED_LOGOUT_PATH)
        names = _shared_cookie_names(context)
        verdict, code, head = shared_logout_verdict(names)
        if verdict == "FAIL":
            flow.head = head
            flow.fail(code)
            return
        if verdict == "SKIPPED":
            # 판별에 쓴 레거시 세션을 같은 흐름 안에서 정리한다.
            page.evaluate(_LOGOUT_JS, LEGACY_LOGOUT_PATH)
            api = page.evaluate(_STATUS_JS)
            recheck, recheck_code = shared_status_verdict(
                bool(api and api.get("authenticated")), "after_logout")
            if recheck != "PASS":
                flow.fail(recheck_code)
                return
            flow.head = "login=ok api=ok logout=not_deployed " + endpoint_head
            if endpoint_verdict != "PASS":
                flow.fail(endpoint_code)
                return
            flow.skip(code)
            return
        stage = "recheck"
        api = page.evaluate(_STATUS_JS)
        verdict, code = shared_status_verdict(
            bool(api and api.get("authenticated")), "after_logout")
        if verdict != "PASS":
            flow.fail(code)
            return
        flow.head = "login=ok api=ok logout=ok " + endpoint_head
        if endpoint_verdict != "PASS":
            flow.fail(endpoint_code)
            return
        flow.pass_(flow.head, "shared_login_ok")
    except Exception as exc:
        flow.fail(safe_code(f"shared_{stage}_{type(exc).__name__}"))
    finally:
        try:
            context.close()
        except Exception:
            pass


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
        "browser_shared_login": BrowserFlowResult("browser_shared_login"),
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

            shared = results["browser_shared_login"]
            shared_started = time.monotonic()
            shared_mark = len(sink)
            try:
                _run_shared_login_flow(browser, CHAT_URL, out_path, shared, username, sink)
            except Exception as exc:
                shared.fail(safe_code(f"shared_runner_error_{type(exc).__name__}"))
            _finish(shared, shared_started, sink, shared_mark)
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

    payloads = {name: flow.as_dict() for name, flow in results.items()}
    # 문서 생성 실패는 점검 판정을 바꾸지 않는다. 로그 한 줄만 남긴다.
    try:
        write_tutorials(payloads, out_path)
    except Exception as exc:
        print(f"USAGE_TUTORIAL error={type(exc).__name__}")
    return payloads
