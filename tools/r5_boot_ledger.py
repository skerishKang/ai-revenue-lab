#!/usr/bin/env python3
"""R5 0단계(0-3) — 초기 화면 장부 도구.

로그아웃 상태 페이지를 1440·390 두 폭으로 열어 부팅 순간의 장부를 JSON으로
남긴다. 단계 PR마다 이동 전후의 JSON이 같음을 본문에 붙이는 데 쓴다(제품 코드
불변의 증거). 상시 시험(고정 기준 파일)으로 두지 않는다 — 다른 레인의 기능
PR을 막지 않기 위해서다(설계 문서 §3.3 0-3).

장부 항목:
  (가) document.body 구조 해시 — 태그·id·class·핵심 속성·자식 순서만(문구·시각 제외)
  (나) 로드 중 addEventListener 호출 — 대상·이벤트. 정렬 다중집합 해시가 비교
      기준이고(listener_multiset_hash), 원시 순서(listener_sequence)는 참고용이다 —
      동적 스크립트 주입 때문에 순서 자체는 실행마다 달라질 수 있다.
  (다) 창에 생긴 Padiem*·__padiem* 이름
  (라) 초기 요청 주소 — 앱이 fetch로 부른 것(네트워크 도착 순서 아님). 비교
      기준은 주소 집합 해시(request_addresses_hash, 정렬·중복 제외)이고, 재확인
      경로의 반복 횟수는 실행마다 ±1회 흔들릴 수 있어 원시 목록은 참고용이다.

운영 서버·배포에 접근하지 않는다. static 파일을 로컬 HTTP 서버로 띄우고,
/api/* 는 정해진 401 응답으로, 그 밖의 외부 요청은 차단한다 — 네트워크 없이
결정적으로 같은 부팅을 재현하기 위해서다.

사용:
  python tools/r5_boot_ledger.py --out 장부.json
  python tools/r5_boot_ledger.py --statics apps/padiem-chat/static --out 장부.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DEFAULT = Path(__file__).resolve().parents[1] / "apps/padiem-chat/static"

# /api/* 에 대한 정해진 로그아웃 응답. /api/auth/status 는 실제 게스트 응답과
# 같은 모양으로 답한다 — "대답 없음"으로 처리되어 소비자가 다시 묻는 경로가
# 돌면 부팅 자체가 비결정적이 된다(재시도가 기록에 섞인다). /health 도 200으로
# 답해 프로브 재시도를 막는다. 그 외 /api/* 는 결정적 401이다.
API_401_BODY = json.dumps(
    {"ok": False, "error": {"code": "unauthorized", "message": "boot ledger stub"}}
).encode("utf-8")
AUTH_STATUS_GUEST_BODY = json.dumps(
    {
        "ready": True,
        "authenticated": False,
        "history_ready": True,
        "user": None,
        "model_requires_session": True,
        "session_state": "guest",
        "methods": {"google": False, "password": True},
    }
).encode("utf-8")
HEALTH_BODY = json.dumps({"status": "ok", "app": "padiem-chat"}).encode("utf-8")

INIT_SCRIPT = r"""
(() => {
  "use strict";
  const log = [];
  window.__r5BootLedgerListeners = log;
  const original = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function (type, listener, options) {
    try {
      let target = "unknown";
      if (this === window) target = "window";
      else if (this === document) target = "document";
      else if (this && this.nodeType === 1) {
        target = String(this.tagName || "").toLowerCase();
        if (this.id) target += "#" + this.id;
      }
      log.push(target + " " + String(type));
    } catch (_) { /* 장부 기록은 부트를 막지 않는다 */ }
    return original.call(this, type, listener, options);
  };
  // 초기 요청은 브라우저 호출 순서(앱이 부른 순서)로 기록한다. 네트워크 도착
  // 순서는 병렬 자산 적재 때문에 매번 달라지므로 장부의 대상이 아니다.
  const fetches = [];
  window.__r5BootLedgerFetches = fetches;
  const originalFetch = window.fetch ? window.fetch.bind(window) : null;
  window.fetch = function (input, init) {
    try {
      let method = "GET";
      let url = "";
      if (typeof input === "string" || input instanceof URL) {
        url = String(input);
        if (init && init.method) method = String(init.method);
      } else if (input && input.url) {
        url = String(input.url);
        method = String(input.method || "GET");
      }
      let path = url;
      try { path = new URL(url, location.href).pathname + new URL(url, location.href).search; } catch (_) {}
      fetches.push(method + " " + path);
    } catch (_) { /* 장부 기록은 부트를 막지 않는다 */ }
    return originalFetch ? originalFetch(input, init) : Promise.reject(new Error("no fetch"));
  };
})();
"""

# 구조 해시에 넣는 속성: 화면 상태를 가르는 것들만(시각·문구·임의 값 제외).
STRUCTURE_ATTRS = ("id", "class", "hidden", "role", "aria-hidden", "data-state", "data-view", "open", "disabled", "type")


def structure_hash(page) -> str:
    """document.body 부터의 구조를 결정적 문자열로 직렬화해 해시한다."""
    payload = page.evaluate(
        """(attrs) => {
      const row = (el) => {
        const item = { t: el.tagName };
        for (const a of attrs) {
          const v = el.getAttribute ? el.getAttribute(a) : null;
          if (v !== null && v !== "") item[a] = v;
        }
        const children = [];
        for (const child of el.children) {
          if (child.tagName === "SCRIPT" || child.tagName === "LINK" || child.tagName === "STYLE") continue;
          children.push(row(child));
        }
        if (children.length) item.c = children;
        return item;
      };
      return JSON.stringify(row(document.body));
    }""",
        list(STRUCTURE_ATTRS),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def window_names(page) -> list[str]:
    return page.evaluate(
        """() => Object.keys(window)
          .filter((k) => k.startsWith("Padiem") || k.startsWith("__padiem"))
          .sort()"""
    )


def make_handler(static_dir: Path, requests: list, lock: threading.Lock):
    class LedgerHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(static_dir), **kwargs)

        def do_GET(self):  # noqa: N802 — http.server API
            with lock:
                requests.append(f"GET {self.path.split('?')[0]}")
            if self.path.split("?")[0] == "/api/auth/status":
                self._stub(200, AUTH_STATUS_GUEST_BODY)
                return
            if self.path.split("?")[0] == "/health":
                self._stub(200, HEALTH_BODY)
                return
            if self.path.startswith("/api/"):
                self._stub(401, API_401_BODY)
                return
            super().do_GET()

        def _stub(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802 — keep the bounded POST probe
            with lock:
                requests.append(f"POST {self.path.split('?')[0]}")
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            body = API_401_BODY
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # 콘솔 소음 제거
            pass

    return LedgerHandler


def boot_once(static_dir: Path, width: int, height: int) -> dict:
    from playwright.sync_api import sync_playwright

    requests: list[str] = []
    lock = threading.Lock()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(static_dir, requests, lock))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": width, "height": height})
            page.add_init_script(INIT_SCRIPT)

            def route_handler(route):
                url = route.request.url
                if url.startswith(base):
                    route.continue_()
                else:
                    # 외부 요청(폰트·분석 등)은 결정성을 위해 차단한다.
                    route.abort()

            page.route("**/*", route_handler)
            page.goto(base + "/index.html", wait_until="load")
            # 요청·리스너 기록이 정지 상태가 될 때까지 기다린다(재시도 백오프가
            # 끝난 뒤 스냅샷). 500ms 동안 변화가 없으면 2회 확인 후 정지로 본다.
            stable_rounds = 0
            last = -1
            for _ in range(40):
                page.wait_for_timeout(500)
                current = page.evaluate(
                    "() => window.__r5BootLedgerFetches.length + window.__r5BootLedgerListeners.length"
                )
                if current == last:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                    last = current
            listeners = page.evaluate("() => window.__r5BootLedgerListeners.slice()")
            fetches = page.evaluate("() => window.__r5BootLedgerFetches.slice()")
            ledger = {
                "width": width,
                "body_structure_hash": structure_hash(page),
                # 부팅은 동적 스크립트 주입(conversation-motion.js 등)과 비동기
                # 소비자 경쟁이 있어 호출 '순서'가 실행마다 달라질 수 있다. 전후
                # 비교는 정렬한 다중집합 해시로 하고, 원시 순서는 참고용으로 남긴다.
                "listener_multiset_hash": hashlib.sha256(
                    "\n".join(sorted(listeners)).encode("utf-8")
                ).hexdigest(),
                "listener_sequence": listeners,
                "window_names": window_names(page),
                # 재확인 경로(음성 identity 등)는 생명주기 이벤트 타이밍에 따라
                # ±1회씩 흔들린다. 비교 기준은 주소 집합(정렬·중복 제외)이고,
                # 반복 횟수는 원시 목록에서 확인한다.
                "request_addresses_hash": hashlib.sha256(
                    "\n".join(sorted(set(fetches))).encode("utf-8")
                ).hexdigest(),
                "initial_requests": fetches,
            }
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return ledger


def main() -> None:
    parser = argparse.ArgumentParser(description="R5 boot ledger (0-3)")
    parser.add_argument("--statics", type=Path, default=STATIC_DEFAULT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--widths", default="1440,390")
    args = parser.parse_args()

    entries = [boot_once(args.statics, int(w), 900 if int(w) >= 800 else 844) for w in args.widths.split(",") if w.strip()]
    args.out.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"boot ledger written: {args.out} ({len(entries)} widths)")


if __name__ == "__main__":
    main()
