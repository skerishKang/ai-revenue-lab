"""#7166 첫 화면 정리 — 입력창 PC 상태 칩의 점 중복과 Claw 입력창 문구.

계약:

* 입력창 칩은 상태 점을 **하나만** 그린다. 점은 CSS 요소(`.composer-pc-status-dot`)이고
  상태별 색을 갖는다. 공용 어휘(`connector-vocabulary.js`)의 `●`/`○` 접두사는
  다른 화면의 계약이므로 그대로 두고, 이 칩에서만 벗긴다.
* Claw 일반 화면의 입력창 안내 문구는 `claw-input-placeholder` locale 키(ko/en)에서
  온다. Chat은 기존 `input` 키를 그대로 쓴다.
* 안내 문구는 320·390 폭에서 한 줄로 들어간다(칩이 예약한 오른쪽 여백 제외).

브라우저 검사는 실제 index.html·CSS·JS를 정적 서버로 열고 API만 mock한다.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
LISTEN_BACKLOG = 128

SIGNED_IN = {"ok": True, "authenticated": True, "ready": True,
             "user": {"name": "대표", "email": "owner@example.com"}}
MARKERS = re.compile(r"[●○]")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = LISTEN_BACKLOG


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        threading.Thread(target=web.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


def read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def locale_copy(key: str, lang: str) -> str:
    """Read one literal out of locale.js by key and language block."""
    source = read("locale.js")
    if lang == "ko":
        block = source[source.index("ko: {"):source.index("en: {")]
    else:
        block = source[source.index("en: {"):]
        block = block[:block.index("\n    }")]
    match = re.search(rf'"{re.escape(key)}":\s*"([^"]*)"', block)
    assert match, f"{key} missing from locale.js {lang} block"
    return match.group(1)


def vocab_line(key: str, lang: str = "ko") -> str:
    source = read("connector-vocabulary.js")
    match = re.search(
        rf'{key}:\s*Object\.freeze\(\{{\s*ko: "([^"]+)",\s*en: "([^"]+)"',
        source)
    assert match, f"{key} missing from connector-vocabulary.js"
    return match.group(1 if lang == "ko" else 2)


def chip_line(key: str, lang: str = "ko") -> str:
    """The same vocabulary line with the leading ●/○ the chip draws itself."""
    return re.sub(r"^[●○]\s*", "", vocab_line(key, lang))


DIRECTORY_ONE_PC = {
    "ok": True, "available": True, "ownerScoped": True,
    "devices": [
        {"deviceId": "home", "deviceName": "집 컴퓨터", "platform": "Windows",
         "state": "CONNECTED", "usable": True, "online": True,
         "expired": False, "revoked": False},
    ],
}
DIRECTORY_EMPTY = {
    "ok": True, "available": True, "ownerScoped": True, "devices": [],
}
# 두 서버 진실(디렉터리·페어링)이 서로 다른 상태를 그리면 칩이 마지막에 받은
# 쪽으로 다시 칠해진다. 실서비스에서는 둘이 같은 PC를 말하므로 여기서도 맞춘다.
PAIRINGS_ONE_PC = {"ok": True, "links": [
    {"link_id": "home", "state": "active", "online": True, "name": "집 컴퓨터"}]}
PAIRINGS_EMPTY = {"ok": True, "links": []}


def _serve_page(page, payload, pairings):
    # Playwright matches routes last-registered-first, so the generic /api/
    # refusal goes in first and the three real reads go in after it.
    page.route(
        re.compile(r".*/api/.*$"),
        lambda route: route.fulfill(
            status=404, content_type="application/json", body="{}"),
    )
    page.route(
        re.compile(r".*/api/pc/pairings$"),
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(pairings, ensure_ascii=False),
        ),
    )
    page.route(
        re.compile(r".*/api/auth/status$"),
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(SIGNED_IN, ensure_ascii=False),
        ),
    )
    page.route(
        re.compile(r".*/api/claw/local-access/devices$"),
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        ),
    )


def _open(page, server):
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#composerPcStatus").wait_for(state="attached", timeout=15_000)
    page.wait_for_timeout(300)


def _read_directory(page):
    page.evaluate("() => window.PadiemComputerConnectionState.requestRead()")


def _wait_state(page, state):
    page.wait_for_function(
        """(expected) => {
          const chip = document.getElementById('composerPcStatus');
          return chip ? chip.dataset.state === expected : false;
        }""",
        arg=state,
        timeout=10_000,
    )


CHIP = """() => {
  const chip = document.getElementById('composerPcStatus');
  const label = document.querySelector('.composer-pc-status-label');
  const dot = document.querySelector('.composer-pc-status-dot');
  const face = document.querySelector('.composer-pc-status-face');
  const probe = document.createElement('span');
  probe.style.color = 'var(--success)';
  document.body.append(probe);
  const success = getComputedStyle(probe).color;
  probe.remove();
  return {
    state: chip ? chip.dataset.state : null,
    label: label ? label.textContent.trim() : null,
    dots: document.querySelectorAll('.composer-pc-status-dot').length,
    dotColor: dot ? getComputedStyle(dot).backgroundColor : null,
    successColor: success,
    faceText: face ? face.innerText.replace(/\\s+/g, ' ') : null,
  };
}"""


# ---------------------------------------------------------------- 소스 계약


def test_the_claw_placeholder_is_a_locale_key_in_both_languages() -> None:
    ko = locale_copy("claw-input-placeholder", "ko")
    en = locale_copy("claw-input-placeholder", "en")
    assert ko and en
    assert ko != locale_copy("input", "ko"), "Claw 문구는 Chat과 달라야 한다"
    assert en != locale_copy("input", "en")


def test_the_composer_reads_the_claw_key_and_chat_keeps_input() -> None:
    app = read("app.js") + read("chat-claw-status-module.js")
    assert '"claw-input-placeholder"' in app
    assert '"input"' in app


def test_the_static_markup_does_not_hardcode_the_claw_copy() -> None:
    html = read("index.html")
    assert locale_copy("claw-input-placeholder", "ko") not in html
    assert locale_copy("claw-input-placeholder", "en") not in html


def test_the_shared_vocabulary_still_owns_the_marked_lines() -> None:
    """다른 화면(Claw 카드·팝오버)은 점 요소가 없어 ●/○ 접두사를 계속 쓴다."""
    vocab = read("connector-vocabulary.js")
    assert "● 연결됨" in vocab
    assert "○ 연결 안 됨" in vocab


# ---------------------------------------------------------------- 브라우저 계약


@requires_browser
@pytest.mark.parametrize("width", (1440, 390))
def test_a_connected_chip_draws_one_green_dot(browser, server, width) -> None:
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve_page(page, DIRECTORY_ONE_PC, PAIRINGS_ONE_PC)
    _open(page, server)
    _read_directory(page)
    _wait_state(page, "connected")
    chip = page.evaluate(CHIP)
    assert chip["dots"] == 1, chip
    assert not MARKERS.search(chip["label"]), chip
    assert chip["label"] == chip_line("connected"), chip
    # 점 색은 상태색(--success)이고, 모니터 안 체크 표시가 상태를 한 번 더 말한다.
    assert chip["dotColor"] == chip["successColor"], chip
    assert not errors, errors
    page.close()


@requires_browser
@pytest.mark.parametrize("width", (1440, 390))
def test_a_disconnected_chip_also_draws_one_dot(browser, server, width) -> None:
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve_page(page, DIRECTORY_EMPTY, PAIRINGS_EMPTY)
    _open(page, server)
    _read_directory(page)
    _wait_state(page, "disconnected")
    chip = page.evaluate(CHIP)
    assert chip["dots"] == 1, chip
    assert not MARKERS.search(chip["label"]), chip
    assert chip["label"] == chip_line("disconnected"), chip
    assert not errors, errors
    page.close()


@requires_browser
def test_chat_and_claw_show_different_one_line_placeholders(browser, server) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _serve_page(page, DIRECTORY_ONE_PC, PAIRINGS_ONE_PC)
    _open(page, server)
    placeholder = page.evaluate("""() => {
      const ta = document.getElementById('messageInput');
      const cs = getComputedStyle(ta);
      return {text: ta.placeholder, clientH: ta.clientHeight,
              scrollH: ta.scrollHeight, font: cs.font,
              padLeft: cs.paddingLeft, padRight: cs.paddingRight};
    }""")
    assert placeholder["text"] == locale_copy("input", "ko")

    page.evaluate("() => document.getElementById('clawNavButton').click()")
    page.wait_for_timeout(400)
    claw = page.evaluate("""() => {
      const ta = document.getElementById('messageInput');
      return {text: ta.placeholder, clientH: ta.clientHeight,
              scrollH: ta.scrollHeight, state: document.querySelector('.app-shell').dataset.state};
    }""")
    assert claw["state"] == "claw"
    assert claw["text"] == locale_copy("claw-input-placeholder", "ko")
    # 한 줄: 안내 문구가 입력 상자 높이를 넘지 않는다.
    assert claw["scrollH"] <= claw["clientH"] + 1, claw

    page.evaluate("() => window.__padiemLocale.apply('en', true)")
    page.wait_for_timeout(500)
    english = page.evaluate(
        "() => document.getElementById('messageInput').placeholder")
    assert english == locale_copy("claw-input-placeholder", "en")
    assert not errors, errors
    page.close()
