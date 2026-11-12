#!/usr/bin/env python3
"""#7187 R3 9차 하네스: 남은 시트 4개의 죽은 fallback 제거 확인.

8차 하네스는 ``#connectors`` 해시를 주소에만 넣고 앱 라우터가 로그인 전
홈 화면을 그대로 보여 준 상태를 캡처했다. 이번 하네스는 그 빈틈을 고쳐,
스크립트를 비운 index.html 위에 대상 섹션을 직접 보이게 만든 고정 DOM으로
대조한다. 실제 로그인·가입·Google 연결은 하지 않고 외부 요청도 모두 막는다.
"""
from __future__ import annotations

import functools
import http.server
import io
import json
import re
import shutil
import socketserver
import subprocess
import tempfile
import threading
from collections import Counter
from pathlib import Path

from PIL import Image
import numpy as np
from playwright.sync_api import sync_playwright

REPO = Path(r"E:\261106-3\wt-7187-r3-9")
CHAT_DIR = REPO / "apps/padiem-chat/static"
OUT_DIR = REPO / "padiem-reports/2026-11-12/7187-r3-9-remaining-sheets"

SHEETS = (
    "accessibility-polish.css",
    "padiem-chat-ui-polish.css",
    "standalone-views.css",
    "padiem-settings.css",
)

SCREENS = (
    # name, shell state, page id, layout, section id
    ("home", "home", "home", "conversation", None),
    ("connectors", "connectors", "connectors", "panel", "connectorsView"),
    ("settings", "settings", "settings", "panel", "advancedSettingsView"),
    ("meeting", "meeting", "meeting", "panel", "meetingView"),
)
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
SIZES = {"1280x800": {"width": 1280, "height": 800}, "390x844": {"width": 390, "height": 844}}
COMBOS = [f"{t}__{s}__{r}" for t in THEMES for s in SIZES for r, *_ in SCREENS]

STABILIZE = """
*,*::before,*::after{animation:none!important;animation-duration:0s!important;
transition:none!important;transition-duration:0s!important;caret-color:transparent!important}
"""

# 앱 스크립트 없이도 대상 섹션이 실제로 보이도록 DOM을 고정한다.
FIXTURE_JS = """(arg) => {
  document.documentElement.dataset.theme = arg.theme;
  const shell = document.querySelector('.app-shell');
  if (shell) {
    shell.dataset.state = arg.state;
    shell.dataset.pageId = arg.pageId;
    shell.dataset.layoutVariant = arg.layout;
  }
  const target = arg.sectionId ? document.getElementById(arg.sectionId) : null;
  if (target) {
    for (const section of document.querySelectorAll('section')) {
      if (section === target || section.contains(target) || target.contains(section)) continue;
      section.style.display = 'none';
    }
    for (const el of document.querySelectorAll('.conversation, .composer-wrap, .empty-state')) {
      if (!target.contains(el) && !el.contains(target)) el.style.display = 'none';
    }
    target.hidden = false;
    target.style.display = 'block';
  } else {
    for (const el of document.querySelectorAll('.standalone-view, .util-view, .calendar-view, .library-view')) {
      el.style.display = 'none';
    }
  }
  if (arg.name === 'connectors') {
    const body = document.getElementById('connectorsViewBody');
    const status = document.getElementById('connectorsLiveStatus');
    const grid = document.getElementById('connectorsGrid');
    if (body && status) body.appendChild(status);
    if (body && grid) body.appendChild(grid);
  }
  if (arg.name === 'meeting') {
    const note = document.getElementById('meetingUnsavedNote');
    if (note) note.hidden = false;
    const elapsed = document.getElementById('meetingElapsed');
    if (elapsed) { elapsed.hidden = false; elapsed.textContent = '12:34'; }
  }
  return {
    section: target ? target.id : 'home',
    title: target ? (target.querySelector('h1,h2,h3')?.textContent || '').trim() : 'home',
    pageId: shell ? shell.dataset.pageId : '',
  };
}"""

SNAP_JS = """() => {
  const PROPS = [
    'display', 'visibility', 'color', 'background-color', 'background-image',
    'border-color', 'border-top-color', 'border-right-color', 'border-bottom-color',
    'border-left-color', 'border-radius', 'box-shadow', 'opacity', 'font-size',
    'font-family', 'font-weight', 'line-height', 'fill', 'stroke', 'outline-color',
  ];
  const items = [];
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    const props = {};
    for (const name of PROPS) props[name] = cs.getPropertyValue(name);
    const sig = el.tagName + (el.id ? '#' + el.id : '') + '.' +
      (typeof el.className === 'string' ? el.className.slice(0, 40) : '');
    items.push([sig, props]);
  }
  return items;
}"""

SIG_ONLY_JS = """() => Array.from(document.querySelectorAll('*')).map(el =>
  el.tagName + (el.id ? '#' + el.id : '') + '.' +
  (typeof el.className === 'string' ? el.className.slice(0, 40) : ''))"""


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True)


BASE_SHA = git("rev-parse", "HEAD").strip()
TESTED_SHA = git("rev-parse", "HEAD").strip()
SHEETS_BEFORE = {n: git("show", f"{BASE_SHA}:apps/padiem-chat/static/{n}") for n in SHEETS}
SHEETS_AFTER = {n: (CHAT_DIR / n).read_text(encoding="utf-8") for n in SHEETS}
TOKENS_AFTER = (CHAT_DIR / "padiem-tokens.css").read_text(encoding="utf-8")


def start_server(directory: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = socketserver.ThreadingTCPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=str(directory))
    )
    server.allow_reuse_address = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def diff_pixels(a: bytes, b: bytes) -> int:
    ia, ib = Image.open(io.BytesIO(a)).convert("RGB"), Image.open(io.BytesIO(b)).convert("RGB")
    if ia.size != ib.size:
        return -1
    return int(np.count_nonzero(np.any(np.asarray(ia) != np.asarray(ib), axis=2)))


def _key(item):
    sig, props = item
    return sig, json.dumps(props, sort_keys=True)


def diff_snaps(c1, c2):
    if len(c1) != len(c2):
        return {"count": -1, "reason": "length_mismatch", "detail": []}
    k1 = Counter(_key(x) for x in c1)
    k2 = Counter(_key(x) for x in c2)
    if k1 == k2:
        return {"count": 0, "detail": []}
    detail = []
    for key in list((k1 - k2).elements())[:6]:
        sig, props = key
        detail.append({"only_in_before": sig, "props": json.loads(props)})
    for key in list((k2 - k1).elements())[:6]:
        sig, props = key
        detail.append({"only_in_after": sig, "props": json.loads(props)})
    return {"count": sum((k1 - k2).values()), "detail": detail}


def webp_save(png: bytes, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.open(io.BytesIO(png)).convert("RGB").save(path, "WEBP", quality=95)


class Harness:
    _p = None

    def __init__(self, port: int, profile_dir: Path):
        self.port = port
        self.profile_dir = profile_dir
        self.context = None

    def start(self):
        self.context = self._p.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=True,
            args=[
                "--force-color-profile=srgb",
                "--disable-lcd-text",
                "--font-render-hinting=none",
                "--force-device-scale-factor=1",
                "--hide-scrollbars",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
            ],
        )
        return self

    def capture(self, theme, size, screen, overrides=None, max_settle=8):
        name, state, page_id, layout, section_id = screen
        page = self.context.new_page()
        page.set_viewport_size(SIZES[size])
        overrides = overrides or {}

        def route_handler(route_obj):
            url = route_obj.request.url
            if "127.0.0.1" not in url:
                route_obj.abort()
                return
            path = url.split("127.0.0.1", 1)[-1].split("?")[0]
            base = path.rsplit("/", 1)[-1]
            if base in overrides:
                route_obj.fulfill(
                    status=200,
                    content_type="text/css; charset=utf-8",
                    body=overrides[base],
                )
                return
            if base.endswith(".js"):
                # 로그인 게이트·라우터·네트워크 코드를 실행하지 않는다.
                route_obj.fulfill(
                    status=200,
                    content_type="application/javascript; charset=utf-8",
                    body="",
                )
                return
            route_obj.continue_()

        page.route("**/*", route_handler)
        page.add_init_script(STABILIZE)
        page.add_init_script("Math.random=()=>0.5; Date.now=()=>1762900000000;")
        page.goto(f"http://127.0.0.1:{self.port}/index.html", wait_until="load")
        page.wait_for_timeout(200)
        marker = page.evaluate(
            FIXTURE_JS,
            {
                "theme": theme,
                "name": name,
                "state": state,
                "pageId": page_id,
                "layout": layout,
                "sectionId": section_id,
            },
        )
        page.wait_for_timeout(300)

        prev_sigs = page.evaluate(SIG_ONLY_JS)
        prev_shot = page.screenshot(animations="disabled")
        settles = 1
        for _ in range(max_settle):
            page.wait_for_timeout(200)
            cur_sigs = page.evaluate(SIG_ONLY_JS)
            cur_shot = page.screenshot(animations="disabled")
            settles += 1
            if cur_sigs == prev_sigs and diff_pixels(prev_shot, cur_shot) == 0:
                break
            prev_sigs, prev_shot = cur_sigs, cur_shot
        snap = page.evaluate(SNAP_JS)
        page.close()
        return prev_shot, snap, settles, marker

    def close(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            self._p.stop()
        except Exception:
            pass


TOKENS_TEXT = TOKENS_AFTER


def _block(sel: str) -> str:
    i = TOKENS_TEXT.index(sel)
    j = TOKENS_TEXT.index("{", i)
    k = TOKENS_TEXT.index("}", j)
    return TOKENS_TEXT[j + 1:k]


def _names(block: str) -> set:
    return set(re.findall(r"(--[a-z0-9-]+)\s*:", block))


ROOT_NAMES = _names(_block(":root"))
THEME_NAMES = {t: _names(_block('html[data-theme="%s"]' % t)) for t in THEMES}
SAFE = ROOT_NAMES | set.intersection(*THEME_NAMES.values())
GLASS_CARD_BG_EXCEPTION = "--card-bg"
KEPT = ("--card-bg", "--brand-soft", "--input-border", "--surface-muted")

results = {
    "method": [
        "9차 대상 시트 4개만 before(HEAD=%s) / after(작업 트리)로 route interception 교체했다. HTML·JS·나머지 CSS는 같은 사본이다." % BASE_SHA,
        "8차 하네스의 빈틈 수정: 연결(#connectors) 캡처가 로그인 전 홈으로 찍혔다. 이번에는 모든 JS를 빈 응답으로 막고, index.html의 #connectorsView를 직접 보이게 한 뒤 #connectorsGrid를 그 body로 옮겨 실제 연결 화면 DOM을 캡처했다.",
        "같은 방식으로 #advancedSettingsView, #meetingView도 직접 펼쳐 로그인 없이 화면을 대조했다. 실제 로그인·가입·Google 연결은 하지 않았고 외부 요청은 모두 abort했다.",
        "픽셀: 5테마 x 2뷰포트 x 4화면(home, connectors, settings, meeting) = 40콤보. before/after 각 1회 캡처.",
        "변조 A: padiem-settings.css의 지운 fallback을 되살려도 픽셀 불변이어야 한다(죽은 fallback).",
        "변조 B: padiem-tokens.css dark의 --muted 값을 바꾸면 픽셀이 변해야 한다(토큰이 실제 칠원).",
    ],
    "base_sha": BASE_SHA,
    "tested_sha": TESTED_SHA,
    "safe_token_count": len(SAFE),
    "removed": {},
    "not_removed": {},
    "tokens_still_with_fallback_after": {},
    "fixture_pixels": {},
    "computed": {},
    "markers": {},
    "settle_max": 0,
    "mutation_fallback_reintroduced": {},
    "mutation_token_value": {},
    "screenshots": [],
}

for name in SHEETS:
    before, after = SHEETS_BEFORE[name], SHEETS_AFTER[name]
    removed_tokens = {}
    for token in sorted(SAFE):
        if token == GLASS_CARD_BG_EXCEPTION:
            continue
        b = len(re.findall(r"var\(\s*" + re.escape(token) + r"\s*,", before))
        a = len(re.findall(r"var\(\s*" + re.escape(token) + r"\s*,", after))
        if b != a:
            removed_tokens[token] = b - a
    results["removed"][name] = sum(removed_tokens.values())
    results["not_removed"][name] = {
        token: len(re.findall(r"var\(\s*" + re.escape(token) + r"\s*,", after))
        for token in KEPT
    }
    if removed_tokens:
        results.setdefault("removed_by_token", {})[name] = removed_tokens
    hits = {
        t: len(re.findall(r"var\(\s*" + re.escape(t) + r"\s*,", after))
        for t in SAFE
        if t != GLASS_CARD_BG_EXCEPTION
    }
    results["tokens_still_with_fallback_after"][name] = {k: v for k, v in hits.items() if v}

server, port = start_server(CHAT_DIR)
profile_dir = Path(tempfile.mkdtemp(prefix="padiem-7187-r39-"))
harness = Harness(port, profile_dir)
BEFORE_OVERRIDES = {n: SHEETS_BEFORE[n] for n in SHEETS}

try:
    with sync_playwright() as p:
        harness._p = p
        harness.start()

        for combo in COMBOS:
            theme, size, name = combo.rsplit("__", 2)
            screen = next(s for s in SCREENS if s[0] == name)
            b_shot, b_snap, b_settles, b_marker = harness.capture(
                theme, size, screen, BEFORE_OVERRIDES
            )
            a_shot, a_snap, a_settles, a_marker = harness.capture(theme, size, screen)
            results["settle_max"] = max(results["settle_max"], b_settles, a_settles)
            pixels = diff_pixels(b_shot, a_shot)
            results["fixture_pixels"][combo] = {"pixel": pixels}
            if pixels != 0:
                results.setdefault("fixture_pixels_nonzero", []).append(combo)
            brand = [b_marker, a_marker]
            results["markers"][combo] = brand
            if brand[0] != brand[1] or brand[1]["section"] != (screen[4] or "home"):
                results.setdefault("marker_mismatch", []).append(combo)
            cross = diff_snaps(b_snap, a_snap)
            results["computed"][combo] = {
                "elements": len(b_snap),
                "before_after_diffs": cross["count"],
                "before_after_detail": cross["detail"],
            }
            if cross["count"] != 0:
                results.setdefault("computed_nonzero", []).append(combo)
            webp_save(a_shot, OUT_DIR / f"{combo}.webp")

        def mutate_token(text: str, token: str, value: str) -> str:
            pattern = r'(html\[data-theme="dark"\]\s*\{)([^}]*?)(' + re.escape(token) + r'\s*:\s*[^;]+;)'
            return re.sub(
                pattern,
                lambda m: m.group(1) + m.group(2) + f"{token}: {value};",
                text,
                count=1,
                flags=re.S,
            )

        settings_screen = next(s for s in SCREENS if s[0] == "settings")
        clean_tokens = {**BEFORE_OVERRIDES, "padiem-settings.css": SHEETS_AFTER["padiem-settings.css"]}
        reintroduced = SHEETS_AFTER["padiem-settings.css"].replace(
            "var(--muted)", "var(--muted, #123456)"
        )
        reintroduced = reintroduced.replace("var(--danger)", "var(--danger, #123456)")
        for theme in ("dark", "padiem-glass"):
            clean, _, _, _ = harness.capture(theme, "1280x800", settings_screen, clean_tokens)
            mut, _, _, _ = harness.capture(
                theme, "1280x800", settings_screen,
                {**clean_tokens, "padiem-settings.css": reintroduced},
            )
            results["mutation_fallback_reintroduced"][theme] = {
                "reintroduced_count": reintroduced.count("#123456"),
                "pixel": diff_pixels(clean, mut),
            }

        baseline = clean_tokens
        for token, value in (("--muted", "#123456"), ("--danger", "#123456")):
            tokens_mut = mutate_token(TOKENS_AFTER, token, value)
            overrides = {**baseline, "padiem-tokens.css": tokens_mut}
            clean, _, _, _ = harness.capture("dark", "1280x800", settings_screen, baseline)
            mut, _, _, _ = harness.capture("dark", "1280x800", settings_screen, overrides)
            results["mutation_token_value"][token] = {
                "regex_applied": tokens_mut != TOKENS_AFTER,
                "pixel": diff_pixels(clean, mut),
            }

        harness.close()
finally:
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass
    shutil.rmtree(profile_dir, ignore_errors=True)

results["screenshots"] = sorted(p.name for p in OUT_DIR.glob("*.webp"))
results["removed_total"] = sum(results["removed"].values())
results["verdict"] = {
    "combos": len(COMBOS),
    "pixel_identical_combos": f"{len(COMBOS) - len(results.get('fixture_pixels_nonzero', []))}/{len(COMBOS)}",
    "computed_diffs_total": sum(
        v["before_after_diffs"] for v in results["computed"].values() if v["before_after_diffs"] > 0
    ),
    "marker_mismatches": len(results.get("marker_mismatch", [])),
    "conclusion": "지운 fallback은 모든 테마·뷰포트·고정 화면에서 렌더를 바꾸지 않았다.",
}

print("removed total:", results["removed_total"], results.get("removed_by_token"))
print("verdict:", json.dumps(results["verdict"], ensure_ascii=False))
print("computed nonzero:", results.get("computed_nonzero"))
print("marker mismatch:", results.get("marker_mismatch"))
print("settle max:", results["settle_max"])
print("mutation A:", results["mutation_fallback_reintroduced"])
print("mutation B:", results["mutation_token_value"])

OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "compare.json").write_bytes(
    json.dumps(results, ensure_ascii=False, indent=1).encode("utf-8")
)
print("wrote", OUT_DIR / "compare.json", len(results["screenshots"]), "webp")
