"""#7173 PR2 — the three council-family tools open inside the Util app.

Pinned here:
- the tool screens live in util-tools.js/util-tools.css (app.js untouched),
- generation reuses the shipped council/Chat contract
  (POST /api/chat/stream with util:"speech"|"sns"|"meeting", tier, same
  origin, credentials include) — the prompt builders stay verbatim,
- the screen never leaves the app: no /apps/council link, no Claw transfer,
- one required-field check, one primary button, result with copy + regenerate,
- error sentences come from the Chat Korean copy table, never a status token.

The Node harness runs the REAL util-tools.js against a DOM shim with a fake
same-origin stream endpoint, so the request contract, the result paint, copy,
regenerate and the failure copy are all executed rather than grepped.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from css_rules import declaration, find_rules_with_selector, parse_rules

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
TOOLS_JS = (STATIC / "util-tools.js").read_text(encoding="utf-8")
CONTRACT_JS = (STATIC / "util-tools-contract.js").read_text(encoding="utf-8")
MARKDOWN_JS = (STATIC / "util-tools-markdown.js").read_text(encoding="utf-8")
TOOLS_CSS = (STATIC / "util-tools.css").read_text(encoding="utf-8")
UTIL_JS = (STATIC / "util-app.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
COUNCIL_JS = (ROOT.parent / "padiem-council-apps" / "static" / "council-app.js").read_text(encoding="utf-8")

TOOL_IDS = ("speech", "sns", "meeting")


# ── static boundary ────────────────────────────────────────────────────────


def test_the_page_loads_the_tool_module_and_sheet() -> None:
    assert '<link rel="stylesheet" href="./util-tools.css" />' in INDEX
    assert '<script src="./util-tools-markdown.js" defer></script>' in INDEX
    assert '<script src="./util-tools-contract.js" defer></script>' in INDEX
    assert '<script src="./util-tools.js" defer></script>' in INDEX
    # The tool modules load first: util-app.js renders the first route at
    # readyState "interactive", so a module loaded after it misses that paint.
    assert (INDEX.index("./util-tools-markdown.js") < INDEX.index("./util-tools-contract.js")
            < INDEX.index("./util-tools.js") < INDEX.index("./util-app.js"))


def test_the_result_is_formatted_and_the_copy_is_plain() -> None:
    # The formatter builds nodes; nothing assembles HTML.
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in MARKDOWN_JS, sink
    assert "document.createElement" in MARKDOWN_JS and "document.createTextNode" in MARKDOWN_JS
    assert "const HEADING = /^(#{1,4})\\s+(.+)$/;" in MARKDOWN_JS
    assert 'out.push("• " + stripInline(bullet[1]).trim());' in MARKDOWN_JS
    assert "window.PadiemUtilMarkdown = Object.freeze({ render: render, plain: plain });" in MARKDOWN_JS
    # The screen renders; the copy path projects plain text from the answer.
    assert "function renderAnswer(host, value)" in TOOLS_JS
    assert "markdown.render(host, value)" in TOOLS_JS
    assert "const text = plainAnswer(lastAnswer).trim();" in TOOLS_JS


def test_app_js_gains_no_tool_logic() -> None:
    for token in ("util-tools", "PadiemUtilTools", "api/chat/stream\"", "행사명"):
        assert token not in APP_JS, token
    assert len(APP_JS.splitlines()) <= 6172


def test_the_screen_never_sends_the_visitor_out_of_the_app() -> None:
    for gone in ("/apps/council", "location.assign", "location.href", "clawNavButton", "window.open"):
        assert gone not in TOOLS_JS, gone
        assert gone not in CONTRACT_JS, gone
    # The one sign-in action calls the Chat shell's own dialog button.
    assert 'document.getElementById("loginButton")' in TOOLS_JS


def test_generation_reuses_the_council_contract() -> None:
    assert 'window.PadiemUtilContract' in TOOLS_JS
    assert 'window.fetch("/api/chat/stream"' in CONTRACT_JS
    assert 'method: "POST"' in CONTRACT_JS
    assert 'credentials: "include"' in CONTRACT_JS
    assert 'payload = { messages: [{ role: "user", content: prompt }], tier: selectedTier(), util: util };' in CONTRACT_JS
    assert "window.PadiemTierSelection" in CONTRACT_JS
    assert "window.PadiemAuthSession" in TOOLS_JS
    assert "window.PadiemAnswerCopy" in TOOLS_JS
    assert 'host.setAttribute("data-util-mounted", "form")' in TOOLS_JS


def test_the_prompt_builders_stay_verbatim_with_the_council_app() -> None:
    shared = (
        "다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.",
        "축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요.",
        "다음 회의 내용을 정리해 주세요.",
        "다음 항목으로 정리해 주세요:",
        "제목, 본문, 해시태그를 구분하여 작성해 주세요.",
    )
    for phrase in shared:
        assert phrase in CONTRACT_JS, phrase
        assert phrase in COUNCIL_JS, phrase
    assert "util: util" in CONTRACT_JS
    for scope in TOOL_IDS:
        assert f'id: "{scope}"' in UTIL_JS


def test_the_error_copy_is_the_chat_table_not_a_status_token() -> None:
    for key in ('"timeout"', '"connection-error"', '"claw-error-auth-needed"',
                '"claw-error-rate-limited"', '"claw-error-generic"'):
        assert key in CONTRACT_JS, key
    assert "window.__padiemLocale" in CONTRACT_JS
    # A status number must never be padded into a sentence.
    assert "status + " not in CONTRACT_JS
    assert "`${err.status}" not in CONTRACT_JS


def test_the_screen_has_one_primary_button_and_a_result_area() -> None:
    assert TOOLS_JS.count('element("button", "util-generate"') == 1
    assert 'element("button", "util-result-button", t("copy"))' in TOOLS_JS
    assert 'element("button", "util-result-button util-result-generate", t("regenerate"))' in TOOLS_JS
    assert 'setStatus(t("required"), "error")' in TOOLS_JS
    assert 'setStatus(t("generating"), "busy")' in TOOLS_JS
    # No unsafe sink: the module builds nodes.
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML"):
        assert sink not in TOOLS_JS, sink


def test_the_sheet_uses_tokens_only() -> None:
    rules = parse_rules(TOOLS_CSS)
    generate = [r for r in rules if any(s == ".util-generate" for s in r.selectors)]
    assert generate and declaration(generate[0], "background") == "var(--primary-bg)"
    assert declaration(generate[0], "color") == "#fff"
    focus = find_rules_with_selector(rules, ".util-generate:focus-visible")
    assert focus and declaration(focus[0], "outline") == "3px solid var(--primary-focus)"
    field_rules = find_rules_with_selector(rules, ".util-input")
    assert field_rules and declaration(field_rules[0], "border") == "1px solid var(--input-border-strong)"
    assert "var(--line," not in TOOLS_CSS
    assert "var(--focus-ring," not in TOOLS_CSS
    assert "var(--input-border-strong," not in TOOLS_CSS
    assert "@media (prefers-reduced-motion: reduce)" in TOOLS_CSS
    assert "@media (max-width: 720px)" in TOOLS_CSS


# ── behaviour: the real util-tools.js in a Node DOM shim ───────────────────

HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const contractSource = fs.readFileSync(process.argv[3], "utf8");
const markdownSource = fs.readFileSync(process.argv[4], "utf8");
const scenario = JSON.parse(process.env.SCENARIO || "{}");
const calls = [], copies = [];
let authState = scenario.signedOut ? { authenticated: false }
  : (scenario.auth === undefined ? { authenticated: true } : scenario.auth);

function El(tag) {
  const node = {
    tagName: (tag || "div").toUpperCase(), id: "", className: "", type: "",
    textContent: "", value: "", rows: 0, required: false, placeholder: "",
    hidden: false, disabled: false, focused: false, noValidate: false,
    children: [], attrs: {}, listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn; },
    setAttribute(k, v) { this.attrs[k] = v; if (k === "id") this.id = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    appendChild(n) { this.children.push(n); n.parentElement = this; return n; },
    replaceChildren(...ns) { this.children.length = 0; ns.forEach((n) => this.appendChild(n)); },
    focus() { this.focused = true; },
    click() { if (this.listeners.click) this.listeners.click({ target: this }); },
    querySelector(sel) { return find(this, sel); },
    querySelectorAll(sel) { return findAll(this, sel); },
  };
  return node;
}
function walk(el, fn) { if (!el) return; fn(el); (el.children || []).forEach((c) => walk(c, fn)); }
function matches(el, sel) {
  if (!sel) return false;
  if (sel.charAt(0) === ".") return String(el.className).split(/\s+/).indexOf(sel.slice(1)) >= 0;
  if (sel.charAt(0) === "#") return el.id === sel.slice(1);
  const attr = /^\[([a-zA-Z-]+)(?:="([^"]*)")?\]$/.exec(sel);
  if (attr) {
    if (attr[1] === "name") {
      if (!el.name) return false;
      return attr[2] === undefined || el.name === attr[2];
    }
    const value = el.getAttribute(attr[1]);
    if (value === null) return false;
    return attr[2] === undefined || value === attr[2];
  }
  return el.tagName === String(sel).toUpperCase();
}
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function text(root) { let out = ""; walk(root, (e) => { if (typeof e.textContent === "string") out += e.textContent + "\n"; }); return out; }

const loginButton = El("button"); loginButton.id = "loginButton";
loginButton.addEventListener("click", () => calls.push("login-button"));
const document = {
  readyState: "complete",
  documentElement: { lang: scenario.lang || "ko" },
  createElement: (tag) => { createdTags.push(String(tag).toLowerCase()); return El(tag); },
  createTextNode: (value) => { const node = El("#text"); node.textContent = String(value); return node; },
  getElementById: (id) => (id === "loginButton" ? loginButton : null),
  addEventListener: () => {},
};
const createdTags = [];
const requests = [];
const responses = Array.isArray(scenario.responses) ? scenario.responses.slice() : [];
function nextResponse() {
  const spec = responses.length ? responses.shift() : { status: 200, answer: "초안 본문" };
  if (spec.throw) return Promise.reject(new Error("network"));
  if (!spec.ok && spec.status !== undefined && spec.status !== 200) {
    return Promise.resolve({
      ok: false, status: spec.status, headers: { get: () => "application/json" },
      json: () => Promise.resolve(spec.body || { error: { code: spec.code || "invalid_request" } }),
      body: null,
    });
  }
  return Promise.resolve({
    ok: true, status: 200, headers: { get: () => "application/json" },
    json: () => Promise.resolve({ answer: spec.answer === undefined ? "초안 본문" : spec.answer }),
    body: null,
  });
}
function fetchStub(url, init) {
  requests.push({ url: url, init: init, body: JSON.parse((init && init.body) || "{}") });
  return nextResponse();
}
const listeners = {};
const windowObj = {
  fetch: fetchStub,
  addEventListener: (type, fn) => { listeners[type] = fn; },
  PadiemAuthSession: { get: () => authState },
  PadiemTierSelection: { get: () => scenario.tier || "free" },
  PadiemAnswerCopy: { copyText: (value) => { copies.push(value); return Promise.resolve(true); } },
  __padiemLocale: { text: (key) => ({ timeout: "응답 시간 초과", "connection-error": "연결 오류",
    "claw-error-auth-needed": "로그인이 필요합니다. 다시 로그인한 뒤 시도해 주세요.",
    "claw-error-rate-limited": "요청이 잠시 많습니다. 잠시 후 다시 시도해 주세요.",
    "claw-error-generic": "실행 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요." }[key] || key) },
};
const sandbox = { document: document, window: windowObj, console: console, setTimeout: () => 0, clearTimeout: () => {} };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(markdownSource, sandbox, { filename: "util-tools-markdown.js" });
vm.runInContext(contractSource, sandbox, { filename: "util-tools-contract.js" });
vm.runInContext(source, sandbox, { filename: "util-tools.js" });

const api = windowObj.PadiemUtilTools;
const result = { ok: true, checks: {}, requests: requests, text: "" };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
function tick() { return new Promise((resolve) => setImmediate(resolve)); }

(async () => {
  check("api", Boolean(api) && api.TOOL_KEYS.length === 3);

  if (scenario.signedOut) {
    const host = El("div"); host.className = "util-tool-body";
    check("mount_signed_out", api.mount("speech", host) === true);
    check("gate_shown", Boolean(find(host, ".util-gate")) && !find(host, ".util-form"));
    check("gate_says_login", /로그인/.test(text(host)));
    find(host, ".util-gate-login").click();
    check("gate_opens_chat_login", calls.indexOf("login-button") >= 0);
    // The auth-state event remounts the same screen once signed in.
    authState = { authenticated: true };
    listeners["padiem:auth-state"]();
    check("auth_event_remounts_form", Boolean(find(host, ".util-form")) && !find(host, ".util-gate"));
    console.log(JSON.stringify(result));
    return;
  }

  const host = El("div"); host.className = "util-tool-body";
  check("mount", api.mount(scenario.tool || "speech", host) === true);
  check("marks_host", host.getAttribute("data-util-mounted") === "form");
  const form = find(host, ".util-form");
  check("form_present", Boolean(form));
  const generate = find(host, ".util-generate");
  check("one_primary_generate", Boolean(generate) && generate.type === "submit");
  const requiredEvent = find(host, "#utilToolField-event") || find(host, "#utilToolField-title");
  check("required_field_is_native_required", Boolean(requiredEvent) && requiredEvent.required === true);

  // Empty submit: the required-field sentence, and no request at all.
  form.listeners.submit({ preventDefault() {} });
  await tick();
  check("empty_submit_blocked", requests.length === 0);
  check("empty_submit_says_required", /필수 항목/.test(text(host)));

  const fields = findAll(host, "[name]");
  fields.forEach((input) => {
    if (input.name === "event") input.value = "제78주년 광복절 기념식";
    if (input.name === "title") input.value = "10월 주민 민원 회의";
    if (input.name === "content") input.value = "정원 사업 신청 방법과 지원 금액을 안내했다.";
  });
  if (scenario.platform) {
    const tab = find(host, '[data-platform="' + scenario.platform + '"]');
    tab.listeners.click({ target: tab });
  }
  form.listeners.submit({ preventDefault() {} });
  await tick();
  check("one_request", requests.length === 1);
  const sent = requests[0] || { body: {} };
  check("posts_the_stream_route", sent.url === "/api/chat/stream");
  check("posts_with_credentials", sent.init && sent.init.credentials === "include");
  check("declares_the_util_scope", sent.body.util === (scenario.tool || "speech"));
  check("carries_the_tier", sent.body.tier === (scenario.tier || "free"));
  const content = sent.body.messages && sent.body.messages[0] && sent.body.messages[0].content;
  check("single_user_turn", Array.isArray(sent.body.messages) && sent.body.messages.length === 1
        && sent.body.messages[0].role === "user");
  check("prompt_has_the_input", typeof content === "string"
        && (content.indexOf("제78주년 광복절 기념식") >= 0 || content.indexOf("10월 주민 민원 회의") >= 0));
  if (scenario.tool === "sns") {
    check("sns_platform_guide", typeof content === "string" && content.indexOf("인스타그램 게시글") >= 0);
  }
  if (scenario.tool === "meeting") {
    check("meeting_prompt", typeof content === "string" && content.indexOf("다음 회의 내용을 정리해 주세요.") === 0);
  }
  if (scenario.errorStatus) {
    await tick();
    check("error_has_no_status_token", text(host).indexOf(String(scenario.errorStatus)) < 0);
    check("error_is_a_korean_sentence", /[가-힣]/.test(text(host)));
  } else {
    const output = find(host, ".util-result-output");
    check("result_painted", output && (scenario.markdown
      ? /오늘의 요약/.test(text(output)) : text(output).indexOf("초안 본문") >= 0));
    if (scenario.markdown) {
      check("md_heading", Boolean(find(output, "h5")) && /오늘의 요약/.test(text(output)));
      const list = find(output, "ul");
      check("md_list", Boolean(list) && findAll(list, "li").length === 2);
      check("md_bold", Boolean(find(output, "strong")) && /중요/.test(text(find(output, "strong"))));
      check("md_no_markers_on_screen", text(output).indexOf("##") < 0 && text(output).indexOf("**") < 0);
      check("md_script_not_inserted", createdTags.indexOf("script") < 0
        && text(output).indexOf("<script>") >= 0);
    }
    const res = find(host, ".util-result");
    check("result_visible", res && res.hidden === false);
    find(host, "[data-util-copy]").click();
    await tick();
    if (scenario.markdown) {
      const copied = copies[0] || "";
      check("copy_plain_no_markers", copied.indexOf("##") < 0 && copied.indexOf("**") < 0);
      check("copy_plain_heading_line", copied.indexOf("오늘의 요약\n") === 0);
      check("copy_plain_bullets", copied.indexOf("• 중요") >= 0);
      check("copy_keeps_hashtag", copied.indexOf("#주민정원") >= 0);
      check("copy_keeps_line_breaks", copied.split("\n").length >= 4);
      check("copy_plain_blank_line", copied.indexOf("\n\n") >= 0);
    } else {
      check("copy_uses_the_shared_module", copies.length === 1 && copies[0] === "초안 본문");
    }
    check("copy_feedback", /복사됨/.test(text(host)));
    find(host, "[data-util-regenerate]").click();
    await tick();
    check("regenerate_requests_again", requests.length === 2);
  }
  result.text = text(host);
  console.log(JSON.stringify(result));
})();
'''


def _run_harness(scenario: dict) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-tools harness"
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "util_tools_harness.js"
        harness.write_text(HARNESS, encoding="utf-8")
        env = dict(os.environ)
        env["SCENARIO"] = json.dumps(scenario)
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "util-tools.js"), str(STATIC / "util-tools-contract.js"),
             str(STATIC / "util-tools-markdown.js")],
            capture_output=True, text=True, encoding="utf-8", env=env, check=False,
        )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _assert_checks(result: dict, names) -> None:
    assert result["ok"] is True, {k: v for k, v in result["checks"].items() if not v}
    for name in names:
        assert result["checks"].get(name) is True, name


def test_behaviour_speech_generation_copy_and_regenerate() -> None:
    result = _run_harness({"tool": "speech", "tier": "plus"})
    _assert_checks(result, (
        "api", "mount", "marks_host", "form_present", "one_primary_generate",
        "required_field_is_native_required", "empty_submit_blocked", "empty_submit_says_required",
        "one_request", "posts_the_stream_route", "posts_with_credentials",
        "declares_the_util_scope", "carries_the_tier", "single_user_turn", "prompt_has_the_input",
        "result_painted", "result_visible", "copy_uses_the_shared_module", "copy_feedback",
        "regenerate_requests_again",
    ))
    assert result["requests"][0]["body"]["util"] == "speech"


def test_behaviour_sns_platform_switch_changes_the_prompt() -> None:
    result = _run_harness({"tool": "sns", "platform": "instagram"})
    _assert_checks(result, ("mount", "declares_the_util_scope", "sns_platform_guide", "result_painted"))


def test_behaviour_meeting_summary() -> None:
    result = _run_harness({"tool": "meeting"})
    _assert_checks(result, ("required_field_is_native_required", "meeting_prompt",
                            "declares_the_util_scope", "result_painted"))


MARKDOWN_ANSWER = (
    "## 오늘의 요약\n\n"
    "- **중요** 안건을 먼저 봅니다\n"
    "- 정원 사업 신청 #주민정원\n\n"
    "<script>alert(1)</script>"
)


def test_behaviour_markdown_renders_and_copy_is_plain() -> None:
    result = _run_harness({"tool": "speech", "markdown": True,
                           "responses": [{"status": 200, "answer": MARKDOWN_ANSWER}]})
    _assert_checks(result, (
        "md_heading", "md_list", "md_bold", "md_no_markers_on_screen",
        "md_script_not_inserted", "copy_plain_no_markers", "copy_plain_heading_line",
        "copy_plain_bullets", "copy_keeps_hashtag", "copy_keeps_line_breaks",
        "copy_plain_blank_line", "copy_feedback",
    ))


def test_behaviour_signed_out_shows_the_login_gate() -> None:
    result = _run_harness({"signedOut": True})
    _assert_checks(result, ("mount_signed_out", "gate_shown", "gate_says_login",
                            "gate_opens_chat_login", "auth_event_remounts_form"))


def test_behaviour_refusals_read_as_chat_sentences() -> None:
    for status, sentence in ((401, "로그인이 필요합니다"), (429, "요청이 잠시 많습니다"), (500, "실행 중 오류")):
        result = _run_harness({"tool": "speech", "errorStatus": status,
                               "responses": [{"status": status, "ok": False}]})
        _assert_checks(result, ("error_has_no_status_token", "error_is_a_korean_sentence"))
        assert sentence in result["text"], result["text"]
