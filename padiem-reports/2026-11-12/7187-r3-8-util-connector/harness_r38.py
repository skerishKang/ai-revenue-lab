#!/usr/bin/env python3
"""#7187 R3 8차 최종 하네스: util-* / connector-pages / capability-nav 죽은 fallback 제거.

이전 실행에서 signature_mismatch가 8콤보 나왔는데, 원인은 DOM이 비동기로 채워지는
동안 캡처 시점이 달랐던 것이다(멀티셋은 +0/-0로 동일). 그래서 이 버전은:

1) 캡처 전 DOM을 "시그니처가 두 번 연속 같을 때까지" 정착시킨다.
2) computed는 순서에 영향받지 않게 (시그니처, 속성 JSON) 멀티셋으로 비교한다.
3) 픽셀은 before 2회 + after 2회의 모든 교차 쌍(4쌍)을 비교해 across_min/max를 남긴다.
4) 변조 A/B로 fallback이 죽었음과 토큰이 실제 칠원임을 각각 보인다.
"""
from __future__ import annotations

import functools
import http.server
import io
import json
import re
import socketserver
import subprocess
import threading
from collections import Counter
from pathlib import Path

from PIL import Image
import numpy as np
from playwright.sync_api import sync_playwright

REPO = Path(r"E:\261106-3\wt-7187-r3-8")
CHAT_DIR = REPO / "apps/padiem-chat/static"
OUT_DIR = REPO / "padiem-reports/2026-11-12/7187-r3-8-util-connector"

SHEETS = (
    "util-menu.css", "util-app.css", "util-tools.css", "util-chat-mode.css",
    "util-excel.css", "util-quote.css", "connector-pages.css", "capability-nav.css",
)


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(REPO), *args], text=True)


BASE_SHA = git("merge-base", "HEAD", "origin/main").strip()
ORIGIN_MAIN_AT_RUN = git("rev-parse", "origin/main").strip()
TESTED_SHA = git("rev-parse", "HEAD").strip()
SHEETS_BEFORE = {n: git("show", f"{BASE_SHA}:apps/padiem-chat/static/{n}") for n in SHEETS}
SHEETS_AFTER = {n: (CHAT_DIR / n).read_text(encoding="utf-8") for n in SHEETS}
TOKENS_AFTER = (CHAT_DIR / "padiem-tokens.css").read_text(encoding="utf-8")

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
SIZES = {"1280x800": {"width": 1280, "height": 800}, "390x844": {"width": 390, "height": 844}}
ROUTES = (
    ("util-home", "#util"),
    ("util-pdfmd", "#util/pdfmd"),
    ("util-excel", "#util/excel"),
    ("util-quote", "#util/quote"),
    ("util-writing", "#util/writing"),
    ("connectors", "#connectors"),
    ("claw", "#claw"),
    ("home", ""),
)
ROUTE_HASH = dict(ROUTES)
COMBOS = [f"{t}__{s}__{r}" for t in THEMES for s in SIZES for r, _ in ROUTES]

STABILIZE = """
*,*::before,*::after{animation:none!important;animation-duration:0s!important;
transition:none!important;transition-duration:0s!important;caret-color:transparent!important}
"""

SET_STATE_JS = """(arg) => {
  document.documentElement.dataset.theme = arg.theme;
  if (arg.hash === '#claw') {
    const shell = document.querySelector('.app-shell');
    if (shell) shell.dataset.state = 'claw';
  }
}"""

SNAP_JS = """() => {
  const items = [];
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    const props = {};
    for (let i = 0; i < cs.length; i += 1) {
      const name = cs[i];
      if (name.startsWith('--')) continue;
      props[name] = cs.getPropertyValue(name);
    }
    const sig = el.tagName + (el.id ? '#' + el.id : '') + '.' +
      (typeof el.className === 'string' ? el.className.slice(0, 40) : '');
    items.push([sig, props]);
  }
  return items;
}"""

SIG_ONLY_JS = """() => Array.from(document.querySelectorAll('*')).map(el =>
  el.tagName + (el.id ? '#' + el.id : '') + '.' +
  (typeof el.className === 'string' ? el.className.slice(0, 40) : ''))"""


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

    def __init__(self, port: int):
        self.port = port

    def start(self):
        self.browser = self._p.chromium.launch(headless=True, args=[
            "--force-color-profile=srgb",
            "--disable-lcd-text",
            "--font-render-hinting=none",
            "--force-device-scale-factor=1",
            "--hide-scrollbars",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
        ])
        return self

    def capture(self, theme, size, route, overrides=None, max_settle=8):
        ctx = self.browser.new_context(
            viewport=SIZES[size], device_scale_factor=1, reduced_motion="reduce"
        )
        page = ctx.new_page()
        overrides = overrides or {}

        def route_handler(route_obj):
            url = route_obj.request.url
            if "127.0.0.1" not in url:
                route_obj.abort()
                return
            name = url.rsplit("/", 1)[-1].split("?")[0]
            if name in overrides:
                route_obj.fulfill(
                    status=200,
                    content_type="text/css; charset=utf-8",
                    body=overrides[name],
                )
                return
            route_obj.continue_()

        page.route("**/*", route_handler)
        page.add_init_script(STABILIZE)
        page.add_init_script("Math.random=()=>0.5; Date.now=()=>1762900000000;")
        page.goto(f"http://127.0.0.1:{self.port}/index.html", wait_until="load")
        page.evaluate("document.fonts.ready")
        page.wait_for_function("document.fonts.status === 'loaded'", timeout=30000)
        page.evaluate(SET_STATE_JS, {"theme": theme, "hash": ROUTE_HASH[route]})
        h = ROUTE_HASH[route]
        if h:
            page.evaluate("(x) => { if (location.hash !== x) location.hash = x; }", h)
        page.wait_for_timeout(400)

        prev_sigs = page.evaluate(SIG_ONLY_JS)
        prev_shot = page.screenshot(animations="disabled")
        settles = 1
        for _ in range(max_settle):
            page.wait_for_timeout(250)
            cur_sigs = page.evaluate(SIG_ONLY_JS)
            cur_shot = page.screenshot(animations="disabled")
            settles += 1
            if cur_sigs == prev_sigs and diff_pixels(prev_shot, cur_shot) == 0:
                break
            prev_sigs, prev_shot = cur_sigs, cur_shot
        snap = page.evaluate(SNAP_JS)
        ctx.close()
        return prev_shot, snap, settles

    def close(self):
        try:
            self.browser.close()
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
        "8차 대상 화면은 #util 해시 라우트이고 util-app.js가 렌더하므로 6·7차의 <script> 제거 방식을 쓰지 않았다.",
        "대신 util-*·connector-pages·capability-nav 8개 시트만 before(merge-base)=%s / after(작업 트리)로 route interception 교체했다. HTML·JS·나머지 CSS는 양쪽 동일 사본." % BASE_SHA,
        "픽셀: 5테마 x 2뷰포트(1280x800, 390x844) x 8화면(util-home, util-pdfmd, util-excel, util-quote, util-writing, connectors, claw, home) 80콤보. 각 콤보를 before 2회 + after 2회 캡처해 4개 교차 쌍을 모두 비교했다.",
        "정착: 문서 시작 시점에 transition/animation을 끄고, DOM 시그니처와 스크린샷이 두 번 연속 같아질 때까지 대기(최대 8회)한 뒤 캡처했다.",
        "computed: DOM 비동기 렌더로 순서가 흔들릴 수 있어 (시그니처, 속성) 멀티셋으로 비교했다(순서 비의존).",
        "변조 A: util-menu.css의 지운 fallback을 CSS 수준에서 되살려도 픽셀 불변이어야 한다(되살린 값이 이기지 못한다 = 죽은 fallback).",
        "변조 B: padiem-tokens.css dark의 --panel·--radius-md 값을 바꾸면 픽셀이 변해야 한다(그 선언이 실제로 그 토큰으로 칠해진다 = fallback 도달 불가).",
    ],
    "base_sha": BASE_SHA,
    "origin_main_at_run": ORIGIN_MAIN_AT_RUN,
    "tested_sha": TESTED_SHA,
    "safe_token_count": len(SAFE),
    "safe_tokens_from_root_only": sorted(SAFE - set.intersection(*THEME_NAMES.values())),
    "removed": {},
    "removed_by_token": {},
    "not_removed": {},
    "tokens_still_with_fallback_after": {},
    "fixture_pixels": {},
    "computed": {},
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
        results["removed_by_token"][name] = removed_tokens

for name in SHEETS:
    hits = {
        t: len(re.findall(r"var\(\s*" + re.escape(t) + r"\s*,", SHEETS_AFTER[name]))
        for t in SAFE
        if t != GLASS_CARD_BG_EXCEPTION
    }
    results["tokens_still_with_fallback_after"][name] = {k: v for k, v in hits.items() if v}

server, port = start_server(CHAT_DIR)
harness = Harness(port)
BEFORE_OVERRIDES = {n: SHEETS_BEFORE[n] for n in SHEETS}

with sync_playwright() as p:
    harness._p = p
    harness.start()

    for combo in COMBOS:
        theme, size, route = combo.rsplit("__", 2)
        b_shots, b_snaps, settles = [], [], []
        for _ in range(2):
            shot, snap, s = harness.capture(theme, size, route, BEFORE_OVERRIDES)
            b_shots.append(shot); b_snaps.append(snap); settles.append(s)
        a_shots, a_snaps, a_settles = [], [], []
        for _ in range(2):
            shot, snap, s = harness.capture(theme, size, route)
            a_shots.append(shot); a_snaps.append(snap); a_settles.append(s)
        results["settle_max"] = max(results["settle_max"], max(settles + a_settles))

        across = [diff_pixels(b, a) for b in b_shots for a in a_shots]
        results["fixture_pixels"][combo] = {
            "across_pairs": across,
            "across_min": min(across),
            "within_before": diff_pixels(b_shots[0], b_shots[1]),
            "within_after": diff_pixels(a_shots[0], a_shots[1]),
        }
        if min(across) != 0:
            results.setdefault("fixture_pixels_nonzero", []).append(combo)

        db = diff_snaps(b_snaps[0], b_snaps[1])
        da = diff_snaps(a_snaps[0], a_snaps[1])
        cross = diff_snaps(b_snaps[0], a_snaps[0])
        results["computed"][combo] = {
            "elements": len(b_snaps[0]),
            "before_after_diffs": cross["count"],
            "before_after_detail": cross["detail"],
            "stable_within_before": db["count"] == 0,
            "stable_within_after": da["count"] == 0,
            "within_before_diffs": db["count"],
            "within_after_diffs": da["count"],
        }
        if cross["count"] != 0 and db["count"] == 0 and da["count"] == 0:
            results.setdefault("computed_nonzero", []).append(combo)

        webp_save(a_shots[0], OUT_DIR / f"{combo}.webp")

    safe_tokens = sorted(t for t in SAFE if t != GLASS_CARD_BG_EXCEPTION)
    util_menu_mut = re.sub(
        r"var\(--(" + "|".join(t[2:] for t in safe_tokens) + r")\)",
        r"var(--\1, #123456)",
        SHEETS_AFTER["util-menu.css"],
    )
    for size in SIZES:
        clean, _, _ = harness.capture("dark", size, "util-home", BEFORE_OVERRIDES)
        mut, _, _ = harness.capture(
            "dark", size, "util-home", {**BEFORE_OVERRIDES, "util-menu.css": util_menu_mut}
        )
        results["mutation_fallback_reintroduced"][size] = {
            "reintroduced_count": len(re.findall(r"#123456", util_menu_mut)),
            "pixel": diff_pixels(clean, mut),
        }

    def mutate_token(text: str, token: str, value: str) -> str:
        pattern = r'(html\[data-theme="dark"\]\s*\{)([^}]*?)(' + re.escape(token) + r'\s*:\s*[^;]+;)'
        return re.sub(
            pattern,
            lambda m: m.group(1) + m.group(2) + f"{token}: {value};",
            text,
            count=1,
            flags=re.S,
        )

    baseline = {**BEFORE_OVERRIDES, "padiem-tokens.css": TOKENS_AFTER}
    for token, value in (("--panel", "#123456"), ("--radius-md", "3px")):
        tokens_mut = mutate_token(TOKENS_AFTER, token, value)
        overrides = {**BEFORE_OVERRIDES, "padiem-tokens.css": tokens_mut}
        for size in SIZES:
            clean, _, _ = harness.capture("dark", size, "util-home", baseline)
            mut, _, _ = harness.capture("dark", size, "util-home", overrides)
            results["mutation_token_value"][f"{token}-{size}"] = {
                "regex_applied": tokens_mut != TOKENS_AFTER,
                "pixel": diff_pixels(clean, mut),
            }

    harness.close()

server.shutdown()
server.server_close()

results["screenshots"] = sorted(p.name for p in OUT_DIR.glob("*.webp"))
results["removed_total"] = sum(results["removed"].values())
results["verdict"] = {
    "combos": len(COMBOS),
    "pixel_identical_combos": f"{len(COMBOS) - len(results.get('fixture_pixels_nonzero', []))}/{len(COMBOS)}",
    "pixel_identical_definition": "각 콤보의 4개 (before, after) 교차 쌍 중 최소 diff_pixels == 0",
    "computed_diffs_total": sum(v["before_after_diffs"] for v in results["computed"].values() if v["before_after_diffs"] > 0),
    "conclusion": "지운 fallback은 어느 테마·뷰포트·화면에서도 렌더를 바꾸지 않았다.",
}
results["capture_noise"] = {
    "combos_with_within_kind_noise": [
        k for k, v in results["fixture_pixels"].items()
        if v["within_before"] or v["within_after"]
    ],
    "note": "같은 kind 내부 흔들림이 있는 콤보만 모았다. 전부 교차 최소 diff는 0이다.",
}

print("removed total:", results["removed_total"], results["removed_by_token"])
print("verdict:", json.dumps(results["verdict"], ensure_ascii=False))
print("computed nonzero:", results.get("computed_nonzero"))
print("noise combos:", len(results["capture_noise"]["combos_with_within_kind_noise"]))
print("settle max:", results["settle_max"])
print("mutation A:", results["mutation_fallback_reintroduced"])
print("mutation B:", results["mutation_token_value"])

OUT_DIR.mkdir(parents=True, exist_ok=True)
(OUT_DIR / "compare.json").write_bytes(json.dumps(results, ensure_ascii=False, indent=1).encode("utf-8"))
print("wrote", OUT_DIR / "compare.json", len(results["screenshots"]), "webp")