#!/usr/bin/env python3
"""#7810 [리팩터링 v2 · T0] 화면 픽셀 비교 도구.

CSS를 바꾼 PR이 "화면이 그대로"임을 보이는 유일한 증거(#7809 공통 규칙 3).
로컬 정적 서버 + 모의 API로 기준(--before, 기본 origin/main)과 비교 대상
(--after, 기본 작업 트리)을 각각 띄워 같은 조합의 스크린샷을 찍고 픽셀 차이를
센다. 실제 서버·로그인·고객 계정을 쓰지 않고, 외부 요청은 전부 abort 한다.

조합: 테마 5(light·dark·padiem-glass·cinematic·padiem-home) × 폭 2
(1440×950, 390×844) × 화면 13.

안정화 규칙(#7187 반경 하네스 r41의 조사를 정리한 것):
- 움직임을 멈추는 CSS는 <style> 요소로 넣는다(스크립트 문자열 주입은 매 페이지
  SyntaxError를 내고 CSS가 적용되지 않는다).
- 정적 서버 대기열(backlog) 128 이상 — 요청이 몰리면 연결 거부로 초기화가 덜
  된 화면이 찍힌다.
- 화면 상태 서명·상태 문구·픽셀이 3번 연속 같을 때 찍는다(2연속은 지연 생성
  숨은 UI 덩어리를 못 잡았다).
- 비동기로 바뀌는 상태 문구(연결 확인 중 등)는 모의 응답·텍스트 고정으로
  같은 값이 되게 한다.
- 찍기 전 검증: 앱 초기화 표식 있음, 페이지 오류 0, 스크립트 로드 실패 0.
  불충분하면 같은 방법으로 최대 3회 다시 찍는다.

절차(#7810 검증 순서):
1. 제어쌍(--control): 같은 대상을 두 번 찍어 비교 — 0이어야 한다. 0이 아니면
   도구 문제다(종료 코드 2).
2. main 대 main(기본 옵션 실행) — 전 조합 0이어야 한다. 아니면 차이 난 조합의
   before·after·diff 이미지를 남기고 종료 코드 1.
3. 변조 시험(--tamper): 토큰 값 하나를 일부러 바꾸면 차이가 잡혀야 한다.
   잡히지 못하면 종료 코드 3.

종료 코드: 0 = 그 단계의 차이 없음(변조는 차이 검출 성공).

사용:
  python tools/chat_pixel_compare.py                          # before/after 비교
  python tools/chat_pixel_compare.py --control                # 제어쌍
  python tools/chat_pixel_compare.py --tamper                 # 변조 시험(claw)
  python tools/chat_pixel_compare.py --only theme=light screen=conversation
  python tools/chat_pixel_compare.py --changed-sheets util-menu.css chat-feedback.css
  python tools/chat_pixel_compare.py --computed ".project-drive-status" color
"""
from __future__ import annotations

import argparse
import functools
import http.server
import io
import json
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "apps/padiem-chat/static"
OUT_DIR = Path(r"E:\chat-qa\7810\261116")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chat_pixel_scope import screens_for_sheets  # noqa: E402  (#8055 범위)

THEMES = ("light", "dark", "padiem-glass", "cinematic", "padiem-home")
VIEWPORTS = {"1440x950": (1440, 950), "390x844": (390, 844)}

# name, page, hash, force(state, sectionId)|None, action, session
# action: messages=대화 템플릿 4통 주입, claw=연결 카드 문구 고정,
#         nav:<버튼 id>=앱 내비게이션 클릭, open:<버튼 id>=창 열기 클릭,
#         dialog:<dialog id>=showModal(), calendar=캘린더 모의 항목
SCREENS = (
    ("home-logout", "index.html", "", None, None, "guest"),
    ("home-login", "index.html", "", None, None, "signed_in"),
    ("conversation", "index.html", "", None, "messages", "guest"),
    ("claw", "index.html", "#padiem-claw", None, "claw", "guest"),
    ("util", "index.html", "#util", None, None, "guest"),
    ("calendar", "index.html", "", ("calendar", "calendarView"), "nav:calendarNavButton", "signed_in"),
    ("automation", "index.html", "", ("automation", "automationView"), "nav:automationNavButton", "guest"),
    ("library", "index.html", "", ("library", "libraryView"), "nav:filesNavButton", "signed_in"),
    ("settings-dialog", "index.html", "", None, "open:settingsButton", "guest"),
    ("profile-menu", "index.html", "", None, "open:profileGuestMenuButton", "guest"),
    ("feedback-dialog", "index.html", "", None, "open:feedbackButton", "guest"),
    ("project-dialog", "index.html", "", None, "dialog:projectDialog", "guest"),
    ("auth-dialog", "index.html", "", None, "open:guestLoginEntryButton", "guest"),
)

# 캘린더 모의 항목의 날짜: Date.now 고정 값(1762900000000)의 서울 날짜.
FROZEN_DATE = "2026-11-12"  # FROZEN 시각(2026-11-12 09:00 KST)의 날짜

# 찍기 전 검증: 앱 초기화 표식(index.html 초기화가 끝까지 갔다), 페이지 오류,
# 스크립트 로드 실패. 화면마다 추가 검증은 validate_marker에서 한다.
MARKER_INIT_ELEMENT = "accountProfileButton"

STABILIZE_CSS = (
    "*,*::before,*::after{animation:none!important;animation-duration:0s!important;"
    "transition:none!important;transition-duration:0s!important;caret-color:transparent!important;"
    "backdrop-filter:none!important;-webkit-backdrop-filter:none!important}"
    # dialog::backdrop의 흐림은 요소 선택자로 못 잡아 html·body에도 넣는다.
    "::backdrop{backdrop-filter:none!important;-webkit-backdrop-filter:none!important;"
    "animation:none!important;transition:none!important}"
)

# <style> 요소 주입(스크립트 문자열 주입의 SyntaxError 문제 회피 — r41 교훈).
STABILIZE_JS = (
    "(() => {"
    "const css = " + json.dumps(STABILIZE_CSS) + ";"
    "const install = () => {"
    "if (document.querySelector('style[data-padiem-stabilize]')) return;"
    "const style = document.createElement('style');"
    "style.textContent = css;"
    "style.setAttribute('data-padiem-stabilize', 'true');"
    "(document.head || document.documentElement).appendChild(style);"
    "};"
    "if (document.head || document.documentElement) install();"
    "else document.addEventListener('DOMContentLoaded', install, {once: true});"
    "})();"
)

GUEST_STATUS = {
    "ready": True, "authenticated": False, "user": None,
    "session_state": "guest", "shared_login_enabled": False,
    "shared_session_present": False, "status_reachable": True,
    "history_ready": False, "project_files_ready": False,
    "model_requires_session": False,
}
SIGNED_STATUS = {
    "ready": True, "authenticated": True,
    "user": {"email": "qa@padiem.local", "name": "QA"},
    "session_state": "active", "shared_login_enabled": False,
    "shared_session_present": False, "status_reachable": True,
    "history_ready": True, "project_files_ready": True,
    "model_requires_session": False,
}
MOCK_PROJECTS = {"projects": [
    {"id": "proj_qa0000000000000000000000000001", "name": "반도체 특허 검토"},
    {"id": "proj_qa0000000000000000000000000002", "name": "제주 가족여행"},
]}
MOCK_CONVERSATIONS = {"conversations": [
    {"id": "chat_" + "a" * 32, "title": "오늘 일정 요약", "pinned": True},
    {"id": "chat_" + "b" * 32, "title": "계약서 초안 검토"},
]}
MOCK_FILES = {"files": [
    {"id": "pf_qa0000000000000000000000000000001", "project_id": "proj_qa0000000000000000000000000001",
     "name": "판례 요약.md", "media_type": "text/markdown", "content_chars": 421},
    {"id": "pf_qa0000000000000000000000000000002", "project_id": "proj_qa0000000000000000000000000001",
     "name": "계약서 검토 목록.md", "media_type": "text/markdown", "content_chars": 128},
]}
MOCK_CALENDAR_ITEMS = {"ok": True, "projection": {"items": [
    {"id": "cal_qa_0001", "item_type": "appointment", "title": "QA 회의",
     "date": FROZEN_DATE, "time_start": "10:00", "time_end": "11:00"},
    {"id": "cal_qa_0002", "item_type": "work_log", "title": "문서 정리",
     "date": FROZEN_DATE},
]}}


def fetch_stub_js(mode: str) -> str:
    """모의 API: 알려진 경로는 고정 응답, 나머지 /api/* 는 즉시 같은 모양 404.

    정적 서버의 실제 404는 응답 타이밍이 흐들려 비동기 렌더가 갈린다(r41 확인).
    네트워크 경주를 제거해 같은 실패 경로를 매번 같은 순서로 걷게 만든다.
    비동기 상태 문구(연결 확인 중)가 다른 값으로 바뀌지 않게 한다.
    """
    status = json.dumps(SIGNED_STATUS if mode == "signed_in" else GUEST_STATUS)
    return """
(() => {
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  const JSON_HEADERS = { 'content-type': 'application/json' };
  const answer = (body, status) => Promise.resolve(new Response(JSON.stringify(body), {
    status: status, statusText: 'OK', headers: JSON_HEADERS,
  }));
  const offline = () => Promise.resolve(new Response('{"ok":false}', {
    status: 404, statusText: 'Not Found', headers: JSON_HEADERS,
  }));
  const AUTH_STATUS = __AUTH_STATUS__;
  const PROJECTS = __PROJECTS__;
  const CONVERSATIONS = __CONVERSATIONS__;
  const FILES = __FILES__;
  const CAL = __CAL__;
  window.fetch = (input, init) => {
    const url = String(typeof input === 'string' ? input : (input && input.url) || '');
    if (!url.includes('/api/')) return realFetch ? realFetch(input, init) : offline();
    if (url.includes('/api/auth/status')) return answer(AUTH_STATUS, 200);
    if (url.includes('/api/projects') && !url.includes('/api/projects/')) return answer(PROJECTS, 200);
    if (url.includes('/api/conversations')) return answer(CONVERSATIONS, 200);
    if (url.includes('/api/project-files')) return answer(FILES, 200);
    if (url.includes('/api/calendar/today') || url.includes('/api/calendar/upcoming')
        || url.includes('/api/calendar/items')) return answer(CAL, 200);
    return offline();
  };
})();
""".replace("__AUTH_STATUS__", status) \
       .replace("__PROJECTS__", json.dumps(MOCK_PROJECTS)) \
       .replace("__CONVERSATIONS__", json.dumps(MOCK_CONVERSATIONS)) \
       .replace("__FILES__", json.dumps(MOCK_FILES)) \
       .replace("__CAL__", json.dumps(MOCK_CALENDAR_ITEMS))


SIG_ONLY_JS = """() => Array.from(document.querySelectorAll('*')).map(el =>
  el.tagName + (el.id ? '#' + el.id : '') + '.' +
  (typeof el.className === 'string' ? el.className.slice(0, 40) : ''))"""

# 무거운 body.innerText 대신 알려진 비동기 상태 문구만 비교한다(r41).
VOLATILE_TEXT_JS = """() => {
  const ids = ['clawPcCardStatus', 'clawDriveCardStatus', 'clawGithubCardStatus',
               'clawConnectionFeedback', 'composerInteractionStatus',
               'libraryNote', 'calendarError', 'automationToggleStatus'];
  const parts = [];
  for (const id of ids) {
    const el = document.getElementById(id);
    parts.push(el ? el.textContent : '');
  }
  const pill = document.querySelector('.claw-connection-label');
  parts.push(pill ? pill.textContent : '');
  return parts.join('\\u0001');
}"""

OPEN_DIALOG_JS = """(arg) => {
  const dialog = document.getElementById(arg.dialogId);
  if (dialog && typeof dialog.showModal === 'function' && !dialog.open) {
    try { dialog.showModal(); } catch (e) { /* already open */ }
  }
  return dialog ? dialog.open : null;
}"""

CLICK_JS = """(arg) => {
  const button = document.getElementById(arg.buttonId);
  if (!button) return null;
  button.click();
  return true;
}"""

FIXTURE_JS = """(arg) => {
  const shell = document.querySelector('.app-shell');
  if (arg.forceState && shell) shell.dataset.state = arg.forceState;
  if (arg.sectionId) {
    const target = document.getElementById(arg.sectionId);
    if (target) {
      for (const section of document.querySelectorAll('section')) {
        if (section === target || section.contains(target) || target.contains(section)) continue;
        section.style.display = 'none';
      }
      target.hidden = false;
      target.style.display = 'block';
    }
  }
  if (arg.action === 'claw') {
    /* 클로 연결 카드 상태 문구는 인증·뷰 준비 순서 경합으로 갈린다(r41 프로브).
     * 게스트 단말 문구로 고정한다 — 텍스트 노드 고정일 뿐 CSS 검증과 무관. */
    const PIN = '로그인하세요';
    const pcCard = document.querySelector('[data-claw-card="computer"]');
    if (pcCard) pcCard.dataset.pcPhase = 'login_required';
    const pinAll = () => {
      for (const id of ['clawPcCardStatus', 'clawDriveCardStatus', 'clawGithubCardStatus']) {
        const el = document.getElementById(id);
        if (el && el.textContent !== PIN) el.textContent = PIN;
      }
    };
    pinAll();
    new MutationObserver(pinAll).observe(document.body, {subtree: true, childList: true, characterData: true});
  }
  if (arg.action === 'messages') {
    const empty = document.getElementById('emptyState');
    if (empty) empty.style.display = 'none';
    const list = document.getElementById('messageList');
    if (list) {
      list.hidden = false;
      const fill = (tplId, text, isAssistant) => {
        const tpl = document.getElementById(tplId);
        if (!tpl) return;
        const node = tpl.content.firstElementChild.cloneNode(true);
        if (isAssistant) {
          // 어시스턴트 템플릿에는 말풍선이 없고 본문 컨테이너가 있다.
          const content = node.querySelector('.assistant-content');
          if (content) {
            const p = document.createElement('p');
            p.textContent = text;
            content.appendChild(p);
          }
        } else {
          const bubble = node.querySelector('.message-bubble');
          if (bubble) bubble.textContent = text;
        }
        list.appendChild(node);
      };
      fill('userMessageTemplate', '안녕하세요, 오늘 일정을 요약해 주세요.', false);
      fill('assistantMessageTemplate', '네, 오늘 일정을 정리해 드릴게요.', true);
      fill('userMessageTemplate', '내일 회의 자료도 준비해 주세요.', false);
      fill('assistantMessageTemplate', '자료 초안을 만들어 두겠습니다.', true);
    }
  }
  return {
    state: shell ? shell.dataset.state : '',
    hash: location.hash,
    theme: document.documentElement.dataset.theme,
    messages: (document.getElementById('messageList') || {children: []}).children.length,
  };
}"""

CLAW_CONTENT_JS = """() => ({
  state: (document.querySelector('.app-shell') || {dataset: {}}).dataset.state || '',
  hero: document.body.innerText.includes('클로입니다'),
  cards: document.querySelectorAll('[data-claw-card]').length,
})"""


FROZEN_CLOCK_JS = """
(() => {
  const FROZEN = 1794441600000;
  Math.random = () => 0.5;
  const RealDate = Date;
  class FrozenDate extends RealDate {
    constructor(...args) {
      if (args.length === 0) super(FROZEN);
      else super(...args);
    }
    static now() { return FROZEN; }
  }
  Object.setPrototypeOf(FrozenDate, RealDate);
  window.Date = FrozenDate;
})();
"""

class Server(socketserver.ThreadingTCPServer):
    request_queue_size = 128  # 연결 거부로 초기화가 덜 된 화면이 찍히는 것 방지
    daemon_threads = True
    allow_reuse_address = True


def start_server(directory: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = Server(("127.0.0.1", 0), functools.partial(Quiet, directory=str(directory)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def materialize_revision(rev: str) -> Path:
    """git 리비전의 static 트리를 임시 폴더에 꺼낸다(git archive + tarfile).

    파이프로 tar에 바로 흘리면 Windows에서 읽기가 막힐 수 있어, 아카이브를
    파일로 쓰고 표준 라이브러리 tarfile 로 푼다(읽기 전용).
    """
    out = Path(tempfile.mkdtemp(prefix="pixel_rev_"))
    archive_path = out / "_archive.tar"
    done = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--output", str(archive_path), rev,
         "apps/padiem-chat/static"],
        capture_output=True, text=True,
    )
    if done.returncode != 0:
        raise SystemExit(f"git archive 실패: {rev}\n{done.stderr[:400]}")
    import tarfile
    with tarfile.open(archive_path) as bundle:
        bundle.extractall(out)  # 저장소 자기 자신의 archive — 신뢰한 내용만 담긴다.
    archive_path.unlink()
    return out / "apps/padiem-chat/static"


def diff_pixels(a: bytes, b: bytes) -> int:
    ia = Image.open(io.BytesIO(a)).convert("RGB")
    ib = Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        return -1
    return int(np.count_nonzero(np.any(np.asarray(ia) != np.asarray(ib), axis=2)))


def diff_pixels_noise(a: bytes, b: bytes) -> int:
    """페인트 디더링을 제외한 차이 픽셀 수.

    채널별 ±1 색 반올림(안티에일리어싱·디더링)은 무차이로 본다(#7187 r41
    판정: noise_pixels). 그 위의 차이(값 차이 2 이상)만 센다.
    """
    ia = Image.open(io.BytesIO(a)).convert("RGB")
    ib = Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        return -1
    return int(np.count_nonzero(np.any(np.abs(
        np.asarray(ia).astype(np.int16) - np.asarray(ib).astype(np.int16)) > 1, axis=2)))


# 콤보 하나가 "차이 없음"으로 인정되는 디더링 잔차 상한(#7187 r41 noise_pixels).
NOISE_PIXELS = 8


def diff_image(a: bytes, b: bytes) -> bytes:
    ia = np.asarray(Image.open(io.BytesIO(a)).convert("RGB")).astype(np.int16)
    ib = np.asarray(Image.open(io.BytesIO(b)).convert("RGB")).astype(np.int16)
    delta = np.abs(ia - ib).max(axis=2)
    heat = np.zeros((*delta.shape, 3), dtype=np.uint8)
    heat[..., 0] = np.clip(delta * 8, 0, 255)
    heat[delta > 0, 1] = 60
    buffer = io.BytesIO()
    Image.fromarray(heat).save(buffer, "PNG")
    return buffer.getvalue()


def save_png(data: bytes, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(data)).convert("RGB").save(path, "PNG")


class Browser:
    """한 스레드에 playwright sync API 인스턴스는 하나만 띄운다.

    여러 Compare(서로 다른 포트·route 치환)가 이 실행기를 공유한다.
    """

    def __init__(self):
        self._playwright = None
        self.browser = None

    def start(self):
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(headless=True, args=[
            # Repaint whole tiles in both captures. Partial rasterization can
            # produce different edge pixels on the same antialiased SVG path.
            "--disable-gpu-rasterization",
            "--disable-partial-raster",
            "--force-color-profile=srgb",
            "--disable-lcd-text",
            "--font-render-hinting=none",
            "--force-device-scale-factor=1",
            "--hide-scrollbars",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
        ])
        return self

    def close(self):
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self._playwright:
                self._playwright.stop()


class Compare:
    def __init__(self, port: int, runner: Browser, overrides: dict[str, str] | None = None):
        self.port = port
        self.runner = runner
        self.overrides = overrides or {}
        self.browser = runner.browser

    def start(self):
        return self

    def close(self):
        pass  # 브라우저 실행기는 소유자(Browser)가 닫는다.

    def _settle(self, page, max_rounds=24):
        """상태 서명·상태 문구·픽셀이 3번 연속 같아질 때까지 기다린다."""
        prev_sigs = page.evaluate(SIG_ONLY_JS)
        prev_text = page.evaluate(VOLATILE_TEXT_JS)
        prev_shot = page.screenshot(animations="disabled")
        settles = 1
        stable = 0
        for _ in range(max_rounds):
            page.wait_for_timeout(300)
            cur_sigs = page.evaluate(SIG_ONLY_JS)
            cur_text = page.evaluate(VOLATILE_TEXT_JS)
            cur_shot = page.screenshot(animations="disabled")
            settles += 1
            if (cur_sigs == prev_sigs and cur_text == prev_text
                    and diff_pixels(prev_shot, cur_shot) == 0):
                stable += 1
                if stable >= 3:
                    return True, cur_shot, settles
            else:
                stable = 0
            prev_sigs, prev_text, prev_shot = cur_sigs, cur_text, cur_shot
        return False, prev_shot, settles

    def capture(self, theme: str, size_name: str, screen: tuple, mode: str = "guest"):
        name, page_file, init_hash, force, action, session = screen
        width, height = VIEWPORTS[size_name]
        ctx = self.browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1, reduced_motion="reduce",
        )
        page = ctx.new_page()
        page_errors: list[str] = []
        js_failed: list[str] = []
        page.on("pageerror", lambda e: page_errors.append(str(e)[:200]))

        def _on_reqfailed(req):
            u = req.url
            if u.endswith(".js") or u.endswith("index.html"):
                js_failed.append(f"{req.failure} {u[-70:]}")

        page.on("requestfailed", _on_reqfailed)

        def route_handler(route_obj):
            # 핸들러가 fulfill/continue/abort 없이 빠지면 요청이 영구 대기가
            # 되어 page.goto 가 타임아웃된다(r41 최소 재현). 어떤 예외가 나도
            # 요청을 반드시 마무리한다.
            try:
                url = route_obj.request.url
                if "127.0.0.1" not in url:
                    route_obj.abort()
                    return
                base = url.split("127.0.0.1", 1)[-1].split("?")[0].rsplit("/", 1)[-1]
                if base in self.overrides:
                    route_obj.fulfill(
                        status=200, content_type="text/css; charset=utf-8",
                        body=self.overrides[base],
                    )
                    return
                route_obj.continue_()
            except Exception:
                try:
                    route_obj.abort()
                except Exception:
                    pass

        page.route("**/*", route_handler)
        page.add_init_script(STABILIZE_JS)
        page.add_init_script(fetch_stub_js(session))
        # Math.random·Date.now·new Date() 를 고정한다. new Date() 가 시계를
        # 그대로 읽으면 캘린더 '오늘' 표시가 실행 날마다 바뀐다.
        page.add_init_script(FROZEN_CLOCK_JS)
        page.goto(f"http://127.0.0.1:{self.port}/{page_file}?theme={theme}{init_hash}",
                  wait_until="load")
        try:
            page.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3500)
        if theme == "padiem-glass":
            # 유리 껍질 수렴 애니메이션이 끝날 때까지 기다린다(있을 때만).
            try:
                page.wait_for_function(
                    "!window.__padiemGlassShell || "
                    "window.__padiemGlassShell.progress() === window.__padiemGlassShell.target()",
                    timeout=6000,
                )
            except Exception:
                pass
        marker = page.evaluate(FIXTURE_JS, {
            "forceState": force[0] if force else "",
            "sectionId": force[1] if force else "",
            "action": action or "",
        })
        for step in (action or "").split(","):
            if step.startswith("nav:"):
                marker["nav_clicked"] = page.evaluate(CLICK_JS, {"buttonId": step[4:]})
                page.wait_for_timeout(700)
            elif step.startswith("open:"):
                marker["clicked"] = page.evaluate(CLICK_JS, {"buttonId": step[5:]})
                page.wait_for_timeout(500)
            elif step.startswith("dialog:"):
                marker["dialog_open"] = page.evaluate(OPEN_DIALOG_JS, {"dialogId": step[7:]})
                page.wait_for_timeout(500)
        ok, shot, settles = self._settle(page)
        if name == "claw":
            # 정착 뒤에도 클로 내용이 살아 있는지 확인한다(r41 두 번째 상태 방어).
            marker["claw"] = page.evaluate(CLAW_CONTENT_JS)
        marker.update(self._validate_state(page, name))
        if page_file.endswith("index.html"):
            marker["app_init"] = page.evaluate(
                f"() => !!document.getElementById('{MARKER_INIT_ELEMENT}')"
            )
        marker["pageerrors"] = page_errors[:4]
        marker["js_failed"] = js_failed[:4]
        ctx.close()
        return shot, ok, settles, marker

    def _validate_state(self, page, name: str) -> dict:
        """화면이 의도한 상태로 찍혔는지 확인하는 표식."""
        checks = {
            "settings-dialog": "() => ({open: document.getElementById('settingsDialog')?.open === true})",
            "profile-menu": "() => ({open: document.getElementById('profileMenu')?.hidden === false})",
            "feedback-dialog": "() => ({open: document.getElementById('feedbackDialog')?.open === true})",
            "project-dialog": "() => ({open: document.getElementById('projectDialog')?.open === true})",
            "auth-dialog": "() => ({open: document.getElementById('authDialog')?.open === true})",
            "calendar": "() => ({visible: !!document.querySelector('.app-shell[data-state=\\'calendar\\'] #calendarView')})",
            "automation": "() => ({visible: !!document.querySelector('.app-shell[data-state=\\'automation\\'] #automationView')})",
            "library": "() => ({visible: !!document.querySelector('.app-shell[data-state=\\'library\\'] #libraryView')})",
            "util": "() => ({visible: !!document.querySelector('.app-shell[data-state=\\'util\\']')})",
        }
        if name in checks:
            return page.evaluate(checks[name])
        return {}

    def capture_validated(self, theme, size_name, screen, tries=3):
        name = screen[0]
        expected = {
            "claw": lambda m: m.get("claw", {}).get("hero") is True
                and m.get("claw", {}).get("cards", 0) >= 3,
            "conversation": lambda m: m.get("messages", 0) >= 4,
            "settings-dialog": lambda m: m.get("open") is True,
            "profile-menu": lambda m: m.get("open") is True,
            "feedback-dialog": lambda m: m.get("open") is True,
            "project-dialog": lambda m: m.get("open") is True,
            "auth-dialog": lambda m: m.get("open") is True,
            "calendar": lambda m: m.get("visible") is True,
            "automation": lambda m: m.get("visible") is True,
            "library": lambda m: m.get("visible") is True,
            "util": lambda m: m.get("visible") is True,
        }
        last = None
        last_exc = None
        for attempt in range(1, tries + 1):
            try:
                shot, ok, settles, marker = self.capture(theme, size_name, screen)
            except Exception as exc:
                last_exc = f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]}"
                print(f"    retry {name} attempt={attempt} capture_error={last_exc}", flush=True)
                continue
            state_ok = True
            if screen[3]:
                state_ok = marker.get("state") == screen[3][0]
            if name in expected:
                state_ok = state_ok and expected[name](marker)
            if page_file_ok(screen):
                # 온전한 페이지: 초기화 표식 + 페이지 오류 0 + 스크립트 로드 실패 0.
                state_ok = state_ok and marker.get("app_init") is True \
                    and not marker.get("pageerrors") and not marker.get("js_failed")
            last = (shot, ok, settles, marker, attempt, state_ok)
            if ok and state_ok:
                return last
            print(f"    retry {name} attempt={attempt} ok={ok} state={marker.get('state')} "
                  f"app_init={marker.get('app_init')} pageerrors={marker.get('pageerrors')} "
                  f"js_failed={marker.get('js_failed')} marker_keys={sorted(marker)}", flush=True)
        if last is None:
            raise RuntimeError(f"capture {name} failed after {tries} tries: {last_exc}")
        return last


def page_file_ok(screen) -> bool:
    return screen[1].endswith("index.html")


def combos(selected: dict, allowed_screens: tuple[str, ...] | None = None) -> list[tuple]:
    out = []
    for theme in THEMES:
        if selected.get("theme") and selected["theme"] != theme:
            continue
        for size_name in VIEWPORTS:
            if selected.get("viewport") and selected["viewport"] != size_name:
                continue
            for screen in SCREENS:
                if selected.get("screen") and selected["screen"] != screen[0]:
                    continue
                if allowed_screens is not None and screen[0] not in allowed_screens:
                    continue
                out.append((theme, size_name, screen))
    return out


def parse_only(pairs: list[str]) -> dict:
    allowed = {"theme", "screen", "viewport"}
    out: dict = {}
    for pair in pairs or []:
        key, _, value = pair.partition("=")
        if key not in allowed or not value:
            raise SystemExit(f"--only 는 {'/'.join(sorted(allowed))}=값 형태: {pair}")
        out[key] = value
    return out


def run_compare(a: Compare, b: Compare, pairs_list: list[tuple], label: str,
                out_dir: Path, save_all_after: Path | None = None,
                re_pairs: int = 1) -> list[dict]:
    results = []
    for index, (theme, size_name, screen) in enumerate(pairs_list, 1):
        combo = f"{theme}__{size_name}__{screen[0]}"
        pairs: list[int] = []
        settled = [0, 0]
        attempts = [0, 0]
        state_ok = [True, True]
        for round_index in range(1 + re_pairs):
            shot_a, ok_a, settles_a, marker_a, try_a, state_a = a.capture_validated(theme, size_name, screen)
            shot_b, ok_b, settles_b, marker_b, try_b, state_b = b.capture_validated(theme, size_name, screen)
            noise = diff_pixels_noise(shot_a, shot_b)
            pairs.append(noise)
            settled = [settles_a, settles_b]
            attempts = [try_a, try_b]
            state_ok = [state_a, state_b]
            if noise <= NOISE_PIXELS:
                break
            # 같은 방법으로 한 번만 다시 잡아 비(flake)와 실차이를 구분한다(r41).
            print(f"    re-pair {combo} round={round_index + 1} pixel={noise}", flush=True)
        noise = min(pairs)
        raw = diff_pixels(shot_a, shot_b)
        results.append({"combo": combo, "pixel": raw, "noise": noise,
                        "pairs": pairs,
                        "settles": settled, "attempts": attempts, "state_ok": state_ok})
        if save_all_after:
            save_png(shot_b, save_all_after / f"{combo}.png")
        print(f"[{label} {index}/{len(pairs_list)}] {combo} raw={raw} noise={noise} "
              f"settles={settled[0]}/{settled[1]} attempts={attempts[0]}/{attempts[1]} "
              f"pairs={pairs}", flush=True)
        if noise > NOISE_PIXELS:
            stem = f"{label}__{combo}".replace("/", "_")
            save_png(shot_a, out_dir / f"{stem}__before.png")
            save_png(shot_b, out_dir / f"{stem}__after.png")
            save_png(diff_image(shot_a, shot_b), out_dir / f"{stem}__diff.png")
            results[-1]["images"] = [f"{stem}__before.png", f"{stem}__after.png", f"{stem}__diff.png"]
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--before", default="origin/main", help="기준 git 리비전(기본 origin/main)")
    parser.add_argument("--after", default=None, help="비교 대상 리비전. 없으면 작업 트리")
    parser.add_argument("--control", action="store_true", help="제어쌍: 같은 대상 두 번 찍어 비교")
    parser.add_argument("--tamper", action="store_true", help="변조 시험: 토큰 하나를 바꿔 차이 검출")
    parser.add_argument("--only", nargs="*", default=[], help="--only theme=<이름> screen=<이름> viewport=<1440x950|390x844>")
    parser.add_argument("--computed", nargs=2, metavar=("선택자", "속성"), help="다섯 테마에서 계산 값 출력")
    parser.add_argument("--limit", type=int, default=0, help="조합 수 제한(연결 확인용)")
    parser.add_argument("--changed-sheets", nargs="*", default=[], metavar="시트.css",
                        help="바뀐 CSS 시트만 넘겨 그 시트가 닿는 화면만 비교")
    parser.add_argument("--out", default=str(OUT_DIR), help="산출물 폴더(기본 %(default)s)")
    args = parser.parse_args()

    selected = parse_only(args.only)
    changed_sheets = [name for name in (args.changed_sheets or []) if name]
    # #8055: 바뀐 시트가 닿는 화면만 고른다. 모르는 시트·공용 시트는 전 화면.
    allowed_screens = screens_for_sheets(STATIC, changed_sheets) if changed_sheets else None
    pairs_list = combos(selected, allowed_screens)
    if args.limit:
        pairs_list = pairs_list[:args.limit]
    if changed_sheets:
        print(json.dumps({"phase": "scope", "changed_sheets": changed_sheets,
                          "screens": list(allowed_screens or []),
                          "combos": len(pairs_list)}, ensure_ascii=False), flush=True)
        if not pairs_list:
            raise SystemExit("--changed-sheets 로 고른 조합이 없다(화면 이름/--only 확인)")

    if args.computed:
        server, port = start_server(STATIC)
        runner = Browser().start()
        comp = Compare(port, runner)
        try:
            out = {}
            for theme in THEMES:
                page = comp.browser.new_context(viewport={"width": 1440, "height": 950}).new_page()
                page.add_init_script(STABILIZE_JS)
                page.goto(f"http://127.0.0.1:{port}/index.html?theme={theme}", wait_until="load")
                page.wait_for_timeout(3500)
                out[theme] = page.evaluate(
                    "(args) => { const el = document.querySelector(args.sel);"
                    " return el ? getComputedStyle(el).getPropertyValue(args.prop) : null; }",
                    {"sel": args.computed[0], "prop": args.computed[1]},
                )
                page.context.close()
            print(json.dumps(out, ensure_ascii=False, indent=2))
        finally:
            runner.close()
            server.shutdown()
            server.server_close()
        return

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if changed_sheets:
        (out_dir / "scope_report.json").write_text(
            json.dumps({"changed_sheets": changed_sheets,
                        "screens": list(allowed_screens or []),
                        "combos": len(pairs_list)}, ensure_ascii=False, indent=1),            encoding="utf-8")

    started = time.time()

    if args.control:
        server, port = start_server(STATIC)
        runner = Browser().start()
        comp = Compare(port, runner).start()
        try:
            # 제어쌍은 2번까지 다시 잡는다. 그래도 0이 아니면 도구 문제다.
            results = run_compare(comp, comp, pairs_list, "control", out_dir, re_pairs=2)
        finally:
            runner.close()
            server.shutdown()
            server.server_close()
        nonzero = [r for r in results if r["noise"] > NOISE_PIXELS]
        print(json.dumps({"phase": "control", "combos": len(results),
                          "nonzero": [r["combo"] for r in nonzero],
                          "seconds": round(time.time() - started, 1)}, ensure_ascii=False, indent=2))
        (out_dir / f"control_report.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        sys.exit(2 if nonzero else 0)

    if args.tamper:
        # 변조 시험: --after 쪽 토큰 하나를 바꾼 사본으로 claw 화면을 찍는다.
        # --radius-pill 999px→0px 는 클로 화면의 pill 모서리(연결 카드·버튼)가
        # 실제로 칠원을 보여 준다(#7187 r41: 1,510픽셀). --radius-sm 10→13px 는
        # 클로에서 보이는 10px 요소가 brand-mark 1개뿐이라 잡히지 않을 수 있다
        # (r41 관찰 — 이번 실측에서도 0). 999px→40px 는 높이 80px 이하 요소에서
        # 클램프로 무차이므로 쓰지 않는다.
        tokens = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")
        token_name, old, new = "--radius-pill", "999px", "0px"
        if f"{token_name}: {old};" not in tokens:
            print(f"변조 대상 토큰을 찾지 못했다: {token_name}: {old};")
            sys.exit(3)
        mutated = tokens.replace(f"{token_name}: {old};", f"{token_name}: {new};", 1)
        screen = next(s for s in SCREENS if s[0] == "claw")
        server, port = start_server(STATIC)
        runner = Browser().start()
        clean_side = Compare(port, runner)
        tampered_side = Compare(port, runner, overrides={"padiem-tokens.css": mutated})
        try:
            theme, size_name = "dark", "1440x950"
            clean = clean_side.capture_validated(theme, size_name, screen)
            mutated_shot = tampered_side.capture_validated(theme, size_name, screen)
            pixels = diff_pixels(clean[0], mutated_shot[0])
            report = {"phase": "tamper", "token": token_name, "mutation": f"{old}→{new}",
                      "screen": "claw", "pixel": pixels,
                      "seconds": round(time.time() - started, 1)}
            print(json.dumps(report, ensure_ascii=False, indent=2))
            (out_dir / "tamper_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            sys.exit(0 if pixels > NOISE_PIXELS else 3)
        finally:
            runner.close()
            server.shutdown()
            server.server_close()

    # 기본: before/after 비교.
    before_tree = materialize_revision(args.before)
    after_tree = STATIC if args.after is None else materialize_revision(args.after)
    server_before, port_before = start_server(before_tree)
    server_after, port_after = start_server(after_tree)
    runner = Browser().start()
    side_before = Compare(port_before, runner)
    side_after = Compare(port_after, runner)
    try:
        # after 쪽 캡처를 모두 남긴다 — 각 화면이 의도한 상태로 찍혔는지
        # 사람이 직접 열어 확인하는 용도(#7810).
        results = run_compare(side_before, side_after, pairs_list, "before-after", out_dir,
                              save_all_after=out_dir / "captures")
    finally:
        runner.close()
        server_before.shutdown()
        server_before.server_close()
        server_after.shutdown()
        server_after.server_close()
    nonzero = [r for r in results if r["noise"] > NOISE_PIXELS]
    print(json.dumps({"phase": "before-after", "before": args.before,
                      "combos": len(results),
                      "nonzero": [r["combo"] for r in nonzero],
                      "noise_note": "채널별 ±1 색 반올림 제외 뒤 잔차 8픽셀 이하는 페인트 디더링으로 무차이(r41 noise_pixels)",
                      "seconds": round(time.time() - started, 1)}, ensure_ascii=False, indent=2))
    (out_dir / "compare_report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(1 if nonzero else 0)


if __name__ == "__main__":
    main()
