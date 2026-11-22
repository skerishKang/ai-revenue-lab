"""#8312 — /admin 게이트의 로그인 길과 복귀 동작 계약.

비로그인 게이트는 Chat 로그인 흐름(?admin_return=1)으로 곧장 들어가고, 로그인이
끝나면 /admin으로 돌아온다. 로그인했지만 관리자가 아닌 계정은 권한 없음 안내와
"다른 계정으로 로그인"(같은 종료 경로 → Chat 로그인 흐름)을 제공한다. 별도 로그인
화면은 만들지 않는다.

두 모듈을 node vm 하네스로 실제로 돌려 계산 값과 동작으로 확인한다. 시험 파일은
정적 원문을 문자열로 단언하지 않는다.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "static"
SHARED = BASE / "admin-session-shared.js"
ADMIN = BASE / "admin.js"


SHARED_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
function boot(search) {
  const winListeners = {};
  const timers = [];
  const storage = new Map();
  const calls = { replaceState: [], replace: [], clicks: 0 };
  const loginButton = {
    hidden: false, disabled: false,
    click() { calls.clicks += 1; authDialog.open = true; }, // clicking opens the login flow
  };
  const authDialog = { open: false };
  const windowObj = {
    location: {
      search, pathname: "/index.html", hash: "#ops",
      replace(url) { calls.replace.push(url); },
    },
    history: { replaceState(...args) { calls.replaceState.push(args); } },
    sessionStorage: {
      getItem(k) { return storage.has(k) ? storage.get(k) : null; },
      setItem(k, v) { storage.set(k, String(v)); },
      removeItem(k) { storage.delete(k); },
    },
    addEventListener(t, fn) { (winListeners[t] = winListeners[t] || []).push(fn); },
    setTimeout(fn) { timers.push(fn); return timers.length; },
  };
  const sandbox = {
    console, window: windowObj, URLSearchParams,
    setTimeout(fn) { fn(); },
    document: {
      getElementById(id) {
        if (id === "loginButton") return loginButton;
        if (id === "authDialog") return authDialog;
        return null;
      },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: "admin-session-shared.js" });
  const drain = () => {
    for (let guard = 0; timers.length && guard < 500; guard += 1) timers.shift()();
  };
  return {
    calls, storage, drain,
    fire(detail) { (winListeners["padiem:auth-state"] || []).forEach((fn) => fn({ detail })); },
    authDialog, loginButton,
  };
}
const result = { ok: true, checks: {} };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }

// 도착: 파라미터는 즉시 지워지고 플래그는 sessionStorage에 남는다(구글 리다이렉트 생존).
const returning = boot("?admin_return=1&keep=2");
check("param_stripped_keeps_rest", returning.calls.replaceState.length === 1
  && returning.calls.replaceState[0][2] === "/index.html?keep=2#ops");
check("flag_set", returning.storage.get("padiem_admin_return") === "1");

// 게스트: Chat 자신이 쓰는 로그인 버튼 경로로 로그인 흐름을 연다.
returning.fire({ authenticated: false, generation: 1 });
returning.drain();
check("guest_opens_login_flow", returning.calls.clicks === 1 && returning.authDialog.open === true);

// 로그인 완료: 플래그를 지우고 /admin으로 돌아온다.
returning.fire({ authenticated: true, generation: 2 });
check("returns_to_admin", returning.calls.replace.join(",") === "./admin");
check("flag_cleared_on_return", !returning.storage.has("padiem_admin_return"));
returning.fire({ authenticated: true, generation: 3 });
check("no_second_return", returning.calls.replace.length === 1);

// 파라미터 없는 평소 첫 화면: 아무 것도 하지 않는다.
const plain = boot("");
plain.fire({ authenticated: false, generation: 1 });
plain.drain();
plain.fire({ authenticated: true, generation: 2 });
check("plain_boot_untouched", plain.calls.clicks === 0 && plain.calls.replace.length === 0
  && plain.calls.replaceState.length === 0);

// 이미 열린 로그인 창: 다시 클릭하지 않는다.
const dialogOpen = boot("?admin_return=1");
dialogOpen.authDialog.open = true;
dialogOpen.fire({ authenticated: false, generation: 1 });
dialogOpen.drain();
check("open_dialog_not_clicked", dialogOpen.calls.clicks === 0);

// 숨은·못 쓰는 로그인 버튼: 클릭하지 않는다(서버 못 닿은 상태 등).
const gated = boot("?admin_return=1");
gated.loginButton.hidden = true;
gated.fire({ authenticated: false, generation: 1 });
gated.drain();
check("hidden_login_button_not_clicked", gated.calls.clicks === 0);

console.log(JSON.stringify(result));
"""


ADMIN_HARNESS = r"""
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const pageHtml = fs.readFileSync(process.argv[3], "utf8");
const SESSION = JSON.parse(process.argv[4]);

function makeElement(id) {
  return {
    id, hidden: true, textContent: "", className: "", href: "", disabled: false,
    dataset: {}, listeners: {},
    addEventListener(t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); },
    fire(t) { (this.listeners[t] || []).forEach((fn) => fn({})); },
    append() {}, replaceChildren() {}, setAttribute() {}, getAttribute() { return null; },
    childElementCount: 0,
  };
}
async function boot() {
  const elements = {};
  const get = (id) => (elements[id] = elements[id] || makeElement(id));
  const calls = { fetch: [], assign: [] };
  const windowObj = {
    PADIEM_ADMIN_CONFIG: {},
    location: { assign(url) { calls.assign.push(url); } },
  };
  windowObj.fetch = (input, init) => {
    const url = String(input);
    calls.fetch.push({ url, method: (init && init.method) || "GET" });
    let body = "{}";
    let status = 404;
    if (url.includes("/api/admin/session")) { body = JSON.stringify(SESSION); status = 200; }
    else if (url.includes("/api/pc/pairings")) { body = JSON.stringify({ ok: true, links: [] }); status = 200; }
    return Promise.resolve(new Response(body, {
      status, headers: { "content-type": "application/json" },
    }));
  };
  const sandbox = {
    console, window: windowObj, Response, fetch: windowObj.fetch,
    setTimeout(fn) { fn(); },
    document: { getElementById: get, createElement: () => makeElement("created") },
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: "admin.js" });
  for (let i = 0; i < 20; i += 1) await new Promise((r) => setTimeout(r, 5));
  return { elements: (id) => get(id), calls };
}
const result = { ok: true, checks: {} };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }

(async () => {
const page = await boot();
const gatePanel = page.elements("gatePanel");
const adminContent = page.elements("adminContent");
const gateTitle = page.elements("gateTitle");
const gateCopy = page.elements("gateCopy");
const loginLink = page.elements("gateLoginLink");
const switchButton = page.elements("gateSwitchButton");

if (SESSION.authenticated === true && SESSION.role) {
  check("admin_opens_hub", gatePanel.hidden === true && adminContent.hidden === false);
} else if (SESSION.authenticated === true) {
  check("markup_login_link_href", /id="gateLoginLink"\s+href="\.\/index\.html\?admin_return=1"/.test(pageHtml));
  check("nonadmin_gate_copy", gateTitle.textContent === "관리자 권한이 없습니다"
    && gateCopy.textContent.includes("관리자 권한이 없습니다"));
  check("nonadmin_shows_switch", loginLink.hidden === true && switchButton.hidden === false);
  check("gate_hides_hub", gatePanel.hidden === false && adminContent.hidden === true);
  switchButton.fire("click");
  for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 5));
  const logoutCalls = page.calls.fetch.map((c) => c.url + " " + c.method);
  check("switch_ends_session_like_chat", logoutCalls.join("|").includes("/auth/shared/logout POST")
    && logoutCalls.join("|").includes("/api/auth/logout POST"));
  check("switch_hands_over_to_chat_login",
    page.calls.assign.join(",") === "./index.html?admin_return=1");
  check("switch_button_disabled_while_leaving", switchButton.disabled === true);
} else {
  check("guest_gate_copy", gateTitle.textContent === "로그인이 필요합니다"
    && gateCopy.textContent.includes("Chat 로그인"));
  check("guest_shows_login", loginLink.hidden === false && switchButton.hidden === true);
  check("gate_hides_hub", gatePanel.hidden === false && adminContent.hidden === true);
}

console.log(JSON.stringify(result));
})();
"""


def _run_harness(harness: str, module: Path, *args: str) -> dict:
    handle = tempfile.NamedTemporaryFile("w", suffix=".cjs", delete=False, encoding="utf-8", newline="\n")
    try:
        handle.write(harness)
        handle.close()
        completed = subprocess.run(
            ["node", handle.name, str(module), *args],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
    result = json.loads(completed.stdout.strip())
    assert result["ok"] is True, result["checks"]
    return result


def test_admin_return_reuses_chat_login_and_returns() -> None:
    _run_harness(SHARED_HARNESS, SHARED)


CAPS_ALL = {key: True for key in (
    "admin_hub", "role_management", "chat_admin", "claw_admin",
    "central_model_admin", "b66_platform_admin", "b66_customer_admin")}
CAPS_NONE = {key: False for key in CAPS_ALL}


def test_guest_gate_points_at_the_chat_login_flow() -> None:
    _run_harness(ADMIN_HARNESS, ADMIN, BASE / "admin.html", json.dumps({
        "authenticated": False, "role": None, "capabilities": dict(CAPS_NONE)}))


def test_non_admin_gate_offers_switching_accounts_through_chat_logout() -> None:
    _run_harness(ADMIN_HARNESS, ADMIN, BASE / "admin.html", json.dumps({
        "authenticated": True, "role": None, "capabilities": dict(CAPS_NONE)}))


def test_admin_session_opens_the_hub_without_a_gate() -> None:
    _run_harness(ADMIN_HARNESS, ADMIN, BASE / "admin.html", json.dumps({
        "authenticated": True, "role": "SUPER_ADMIN", "capabilities": dict(CAPS_ALL)}))
