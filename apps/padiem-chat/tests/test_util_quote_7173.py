"""#7173 PR4 — the quote draft tool opens inside the Util app.

Pinned here:
- the screen lives in util-quote.js/util-quote.css (app.js untouched),
- the draft reuses the existing deterministic manual-intake preview through the
  Util app's signed-in wrapper (/api/util/quote/preview) — no model, no execute
  lane, no second backend,
- input → result stays in the app; "Claw에서 실행" is only a secondary action,
- markdown is rendered by util-tools-markdown.js and copied as plain text,
- error sentences are Korean copy, never a status token.

The Node harness executes the REAL util-quote.js against a DOM shim with a fake
preview endpoint, so the request contract, the result paint, copy, regenerate,
the secondary Claw action and the failure copy are executed rather than grepped.
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
QUOTE_JS = (STATIC / "util-quote.js").read_text(encoding="utf-8")
QUOTE_CSS = (STATIC / "util-quote.css").read_text(encoding="utf-8")
UTIL_JS = (STATIC / "util-app.js").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
MARKDOWN_JS = (STATIC / "util-tools-markdown.js").read_text(encoding="utf-8")


# ── static boundary ────────────────────────────────────────────────────────


def test_the_page_loads_the_quote_module_and_sheet_before_the_app() -> None:
    assert '<link rel="stylesheet" href="./util-quote.css" />' in INDEX
    assert '<script src="./util-quote.js" defer></script>' in INDEX
    assert (INDEX.index("./util-tools-markdown.js") < INDEX.index("./util-quote.js")
            < INDEX.index("./util-app.js"))


def test_the_util_app_mounts_the_quote_screen_from_its_own_module() -> None:
    assert "window.PadiemUtilQuote" in UTIL_JS
    assert 'tool.id === "quote"' in UTIL_JS
    assert "window.PadiemUtilQuote.mount(body)" in UTIL_JS


def test_app_js_gains_no_quote_logic() -> None:
    for token in ("util-quote", "PadiemUtilQuote", "/api/util/quote/preview"):
        assert token not in APP_JS, token


def test_the_screen_posts_to_the_signed_in_wrapper_only() -> None:
    assert 'window.fetch("/api/util/quote/preview"' in QUOTE_JS
    assert 'method: "POST"' in QUOTE_JS
    assert 'credentials: "include"' in QUOTE_JS
    assert 'content: values.content' in QUOTE_JS
    assert 'channel: values.channel' in QUOTE_JS
    assert 'action: values.action' in QUOTE_JS
    assert 'sender_hint: values.sender_hint || null' in QUOTE_JS
    # The execute lane is never reached from this screen.
    assert "manual-intake/execute" not in QUOTE_JS
    assert "claw-generate" not in QUOTE_JS


def test_markdown_is_rendered_and_the_copy_is_plain() -> None:
    assert "window.PadiemUtilMarkdown" in QUOTE_JS
    assert 'markdown.render(host, value)' in QUOTE_JS
    assert "const text = plainAnswer(lastPreview && lastPreview.result_text).trim();" in QUOTE_JS
    for sink in (".innerHTML", ".outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in QUOTE_JS, sink


def test_the_screen_has_one_primary_button_and_the_secondary_claw_action() -> None:
    assert QUOTE_JS.count('element("button", "util-generate"') == 1
    assert 'element("button", "util-result-button", t("copy"))' in QUOTE_JS
    assert 'element("button", "util-result-button util-result-generate", t("regenerate"))' in QUOTE_JS
    assert 'element("button", "util-result-button util-quote-claw", t("clawExecute"))' in QUOTE_JS
    assert 'document.getElementById("clawNavButton")' in QUOTE_JS
    assert 'document.getElementById("clawQuoteCard")' in QUOTE_JS
    assert 'setStatus(t("required"), "error")' in QUOTE_JS


def test_the_error_copy_is_korean_sentences_not_status_tokens() -> None:
    for key in ("authNeeded", "rateLimited", "tooLong", "generic", "invalid"):
        assert key in QUOTE_JS, key
    assert "status + " not in QUOTE_JS
    assert "`${err.status}" not in QUOTE_JS


def test_the_sheet_uses_tokens_and_responsive_guards() -> None:
    rules = parse_rules(QUOTE_CSS)
    row = [r for r in rules if ".util-quote-form .util-field-row" in r.selectors]
    assert row and declaration(row[0], "grid-template-columns") == "1fr 1fr"
    claw = find_rules_with_selector(rules, ".util-quote-claw")
    assert claw and declaration(claw[0], "border-color") == "var(--input-border-strong)"
    assert "var(--line," not in QUOTE_CSS
    assert "var(--focus-ring," not in QUOTE_CSS
    assert "@media (max-width: 720px)" in QUOTE_CSS
    assert "@media (prefers-reduced-motion: reduce)" in QUOTE_CSS


# ── behaviour: the real util-quote.js in a Node DOM shim ───────────────────

HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const source = fs.readFileSync(process.argv[2], "utf8");
const markdownSource = fs.readFileSync(process.argv[3], "utf8");
const scenario = JSON.parse(process.env.SCENARIO || "{}");
const calls = [], copies = [];
let authState = scenario.signedOut ? { authenticated: false }
  : (scenario.auth === undefined ? { authenticated: true } : scenario.auth);

const createdTags = [];
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
    const value = el.getAttribute(attr[1]);
    if (value === null) return false;
    return attr[2] === undefined || value === attr[2];
  }
  return el.tagName === String(sel).toUpperCase();
}
function find(root, sel) { let out = null; walk(root, (e) => { if (!out && e !== root && matches(e, sel)) out = e; }); return out; }
function findAll(root, sel) { const out = []; walk(root, (e) => { if (e !== root && matches(e, sel)) out.push(e); }); return out; }
function text(root) { let out = ""; walk(root, (e) => { if (typeof e.textContent === "string") out += e.textContent + "\n"; }); return out; }

function namedButton(id, mark) {
  const button = El("button"); button.id = id;
  button.addEventListener("click", () => calls.push(mark));
  return button;
}
const loginButton = namedButton("loginButton", "login-button");
const clawNav = namedButton("clawNavButton", "claw-nav");
const clawCard = namedButton("clawQuoteCard", "claw-card");
const byId = { loginButton, clawNavButton: clawNav, clawQuoteCard: clawCard };

const document = {
  readyState: "complete",
  documentElement: { lang: scenario.lang || "ko" },
  createElement: (tag) => { createdTags.push(String(tag).toLowerCase()); return El(tag); },
  createTextNode: (value) => { const node = El("#text"); node.textContent = String(value); return node; },
  getElementById: (id) => byId[id] || null,
  addEventListener: () => {},
};

const PREVIEW_MARKDOWN = "# 견적서 초안 요약\n\n- 요청 채널: kakao\n- 요청자: 테스트 고객\n\n## 견적서 초안 (DRAFT)\n\n- **필수** 항목 확인\n- 두 번째 항목\n\n| 품목 | 수량 |\n|---|---|\n| 요청 품목 | 1 |\n";
function okResponse(spec) {
  const preview = {
    title: spec && spec.title ? spec.title : "견적서 초안 (DRAFT) — 테스트 고객",
    result_text: spec && spec.result_text !== undefined ? spec.result_text : PREVIEW_MARKDOWN,
    memory_proposals: [],
  };
  return Promise.resolve({
    ok: true, status: 200,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve({ ok: true, preview: preview }),
  });
}
function failResponse(spec) {
  return Promise.resolve({
    ok: false, status: spec.status || 500,
    headers: { get: () => "application/json" },
    json: () => Promise.resolve({ error: { code: spec.code || "invalid_request" } }),
  });
}
const requests = [];
const responses = Array.isArray(scenario.responses) ? scenario.responses.slice() : [];
function fetchStub(url, init) {
  requests.push({ url: url, init: init, body: JSON.parse((init && init.body) || "{}") });
  const spec = responses.length ? responses.shift() : { status: 200 };
  if (spec.throw) return Promise.reject(new Error("network"));
  if (spec.status && spec.status !== 200) return failResponse(spec);
  return okResponse(spec);
}
const listeners = {};
const windowObj = {
  fetch: fetchStub,
  addEventListener: (type, fn) => { listeners[type] = fn; },
  PadiemAuthSession: { get: () => authState },
  PadiemAnswerCopy: { copyText: (value) => { copies.push(value); return Promise.resolve(true); } },
};
const sandbox = { document: document, window: windowObj, console: console, setTimeout: () => 0, clearTimeout: () => {} };
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(markdownSource, sandbox, { filename: "util-tools-markdown.js" });
vm.runInContext(source, sandbox, { filename: "util-quote.js" });

const api = windowObj.PadiemUtilQuote;
const result = { ok: true, checks: {}, requests: requests, text: "" };
function check(name, cond) { result.checks[name] = Boolean(cond); if (!cond) result.ok = false; }
function tick() { return new Promise((resolve) => setImmediate(resolve)); }

(async () => {
  check("api", Boolean(api) && typeof api.mount === "function");

  if (scenario.signedOut) {
    const host = El("div"); host.className = "util-tool-body";
    check("mount_signed_out", api.mount(host) === true);
    check("gate_shown", Boolean(find(host, ".util-gate")) && !find(host, ".util-form"));
    check("gate_says_login", /로그인/.test(text(host)));
    find(host, ".util-gate-login").click();
    check("gate_opens_chat_login", calls.indexOf("login-button") >= 0);
    authState = { authenticated: true };
    listeners["padiem:auth-state"]();
    check("auth_event_remounts_form", Boolean(find(host, ".util-form")) && !find(host, ".util-gate"));
    console.log(JSON.stringify(result));
    return;
  }

  const host = El("div"); host.className = "util-tool-body";
  check("mount", api.mount(host) === true);
  check("marks_host", host.getAttribute("data-util-mounted") === "form");
  const form = find(host, ".util-form");
  check("form_present", Boolean(form));
  const generate = find(host, ".util-generate");
  check("one_primary_generate", Boolean(generate) && generate.type === "submit");
  const content = find(host, "#utilQuoteField-content");
  check("required_field_is_native_required", Boolean(content) && content.required === true);
  check("request_max_length", content && content.maxLength === 12000);

  form.listeners.submit({ preventDefault() {} });
  await tick();
  check("empty_submit_blocked", requests.length === 0);
  check("empty_submit_says_required", /요청 원문/.test(text(host)) || scenario.lang === "en");

  content.value = "A상사에서 10박스 견적 요청";
  const channel = find(host, "#utilQuoteField-channel");
  const action = find(host, "#utilQuoteField-action");
  const sender = find(host, "#utilQuoteField-sender_hint");
  if (channel) channel.value = "email";
  if (action) action.value = "order";
  if (sender) sender.value = "A상사 담당자";
  form.listeners.submit({ preventDefault() {} });
  await tick();
  check("one_request", requests.length === 1);
  const sent = requests[0] || { body: {} };
  check("posts_the_preview_wrapper", sent.url === "/api/util/quote/preview");
  check("posts_with_credentials", sent.init && sent.init.credentials === "include");
  check("posts_required_accept", sent.init && sent.init.headers && sent.init.headers.Accept === "application/json");
  check("sends_content", sent.body.content === "A상사에서 10박스 견적 요청");
  check("sends_channel", sent.body.channel === "email");
  check("sends_action", sent.body.action === "order");
  check("sends_sender_hint", sent.body.sender_hint === "A상사 담당자");

  if (scenario.errorStatus) {
    check("error_has_no_status_token", text(host).indexOf(String(scenario.errorStatus)) < 0);
    check("error_is_a_korean_sentence", /[가-힣]/.test(text(host)) || scenario.lang === "en");
    result.text = text(host);
    console.log(JSON.stringify(result));
    return;
  }

  const output = find(host, "#utilQuoteOutput");
  const res = find(host, "#utilQuoteResult");
  check("result_visible", res && res.hidden === false);
  check("result_title", /견적서 초안|Quote draft/.test(text(host)));
  check("md_heading", Boolean(find(output, "h5")));
  check("md_list", Boolean(find(output, "ul")));
  check("md_no_markers_on_screen", text(output).indexOf("##") < 0 && text(output).indexOf("**") < 0);
  check("md_script_not_inserted", createdTags.indexOf("script") < 0);

  find(host, "[data-util-copy]").click();
  await tick();
  const copied = copies[0] || "";
  check("copy_uses_the_shared_module", copies.length === 1);
  check("copy_plain_no_markers", copied.indexOf("##") < 0 && copied.indexOf("**") < 0);
  check("copy_keeps_bullets", copied.indexOf("• ") >= 0);
  check("copy_feedback", /복사됨|Copied/.test(text(host)));

  find(host, "[data-util-regenerate]").click();
  await tick();
  check("regenerate_requests_again", requests.length === 2);

  find(host, "[data-util-claw]").click();
  check("claw_secondary_navigates", calls.indexOf("claw-nav") >= 0 && calls.indexOf("claw-card") >= 0);

  result.text = text(host);
  console.log(JSON.stringify(result));
})();
'''


def _run_harness(scenario: dict) -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the util-quote harness"
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "util_quote_harness.js"
        harness.write_text(HARNESS, encoding="utf-8")
        env = dict(os.environ)
        env["SCENARIO"] = json.dumps(scenario)
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "util-quote.js"),
             str(STATIC / "util-tools-markdown.js")],
            capture_output=True, text=True, encoding="utf-8", env=env, check=False,
        )
    assert completed.stdout.strip(), completed.stdout + completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _assert_checks(result: dict, names) -> None:
    assert result["ok"] is True, {k: v for k, v in result["checks"].items() if not v}
    for name in names:
        assert result["checks"].get(name) is True, name


def test_behaviour_quote_preview_copy_regenerate_and_claw_secondary() -> None:
    result = _run_harness({})
    _assert_checks(result, (
        "api", "mount", "marks_host", "form_present", "one_primary_generate",
        "required_field_is_native_required", "request_max_length",
        "empty_submit_blocked", "empty_submit_says_required",
        "one_request", "posts_the_preview_wrapper", "posts_with_credentials",
        "posts_required_accept", "sends_content", "sends_channel", "sends_action",
        "sends_sender_hint", "result_visible", "result_title", "md_heading", "md_list",
        "md_no_markers_on_screen", "md_script_not_inserted", "copy_uses_the_shared_module",
        "copy_plain_no_markers", "copy_keeps_bullets", "copy_feedback",
        "regenerate_requests_again", "claw_secondary_navigates",
    ))


def test_behaviour_signed_out_shows_the_login_gate() -> None:
    result = _run_harness({"signedOut": True})
    _assert_checks(result, ("mount_signed_out", "gate_shown", "gate_says_login",
                            "gate_opens_chat_login", "auth_event_remounts_form"))


def test_behaviour_refusals_read_as_sentences() -> None:
    for status, code, sentence in (
        (401, "unauthorized", "로그인이 필요합니다"),
        (429, "rate_limited", "잠시 후"),
        (400, "content_too_long", "너무 깁니다"),
        (500, "preview_generation_failed", "다시 시도"),
    ):
        result = _run_harness({"errorStatus": status,
                               "responses": [{"status": status, "code": code}]})
        _assert_checks(result, ("error_has_no_status_token", "error_is_a_korean_sentence"))
        assert sentence in result["text"], (status, result["text"])
