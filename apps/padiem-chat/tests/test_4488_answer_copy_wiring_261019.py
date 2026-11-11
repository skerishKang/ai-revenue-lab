"""#4488: the shared answer-copy module is actually wired.

B62 user-bubble, answer-bar, saved-output, and rich-code copy plus B66
real-answer copy call one canonical clipboard implementation; legacy branches
remain only as fallbacks. B66 product files stay product-neutral (Shared alias
only).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "packages/padiem-conversation-ui/answer-copy.js"
WORKFLOWS = ROOT / ".github/workflows"
SYNC_ANSWER_COPY = "scripts/sync_shared_answer_copy.py --check"


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


# #7186 R2: the user-copy wiring is checked by running the conversation module's
# addUserMessage and clicking the rendered copy button.
_USER_COPY_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

function makeElement(id) {
  const attrs = {};
  return {
    id, hidden: false, disabled: false, textContent: "", value: "", dataset: {},
    attrs, listeners: {}, children: [], style: {},
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return attrs[k] === undefined ? null : attrs[k]; },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
    appendChild(x) { this.children.push(x); return x; },
    remove() {},
    querySelector() { return null; },
  };
}
const sharedCalls = [], clipboardCalls = [], pendingTimers = [];
const fragments = [];
function makeFragment() {
  const bubble = makeElement("bubble");
  const chip = makeElement("chip");
  const avatar = makeElement("avatar");
  const clock = makeElement("clock");
  const copyBtn = makeElement("copyBtn");
  const editBtn = makeElement("editBtn");
  const fragment = makeElement("fragment");
  fragment.querySelector = (selector) => ({
    ".message-bubble": bubble,
    ".user-profile-chip": chip,
    ".user-avatar": avatar,
    ".user-action-time": clock,
    ".user-action-copy": copyBtn,
    ".user-action-edit": editBtn,
  }[selector] || null);
  fragment.nodes = { bubble, chip, avatar, clock, copyBtn, editBtn };
  fragments.push(fragment);
  return fragment;
}
const live = {
  messageList: makeElement("messageList"),
  accountName: { textContent: "Kim", hidden: false },
  accountInitial: () => "K",
  uiT: (key) => key,
  formatBytes: (n) => `fb-${n}`,
  formatClockTime: () => "ct-12:00",
};
const deps = {};
for (const key of Object.keys(live)) {
  Object.defineProperty(deps, key, {
    get() { return live[key]; },
    set(value) { live[key] = value; },
  });
}
const ctx = {
  document: {
    documentElement: { lang: "ko" },
    createElement: (t) => makeElement(t),
    getElementById: (id) => ({ content: { cloneNode: () => makeFragment() } }),
  },
  navigator: { clipboard: { writeText: async (t) => { clipboardCalls.push(t); } } },
  setTimeout: (fn) => { pendingTimers.push(fn); return pendingTimers.length; },
  clearTimeout: () => {},
  console,
  window: {
    PadiemSharedTooltip: null,
    PadiemAnswerCopy: { copyText: async (t) => { sharedCalls.push(t); return true; } },
  },
  Date, Promise, Error, Number, String, Boolean, Object, Array, JSON, Map, Set,
};
ctx.window.window = ctx.window;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__CONV_PATH__, "utf8"), ctx,
                { filename: "chat-conversation-module.js" });
const api = ctx.window.PadiemChatConversationModule.create(deps);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function main() {
  api.addUserMessage("안녕", null, {});
  fragments[0].nodes.copyBtn.click();
  await tick();
  const shared = sharedCalls.slice();
  const clipboard = clipboardCalls.slice();
  const flash = fragments[0].nodes.copyBtn.textContent;
  while (pendingTimers.length) pendingTimers.shift()();
  delete ctx.window.PadiemAnswerCopy;
  sharedCalls.length = 0;
  clipboardCalls.length = 0;
  api.addUserMessage("fallback", null, {});
  fragments[1].nodes.copyBtn.click();
  await tick();
  process.stdout.write(JSON.stringify({
    shared, clipboard, flash,
    fallbackClipboard: clipboardCalls.slice(),
    fallbackShared: sharedCalls.slice(),
  }));
}
main().catch((error) => { console.error(error); process.exit(1); });
"""


def _run_user_copy_harness() -> dict:
    import json
    import shutil
    import subprocess

    conv = ROOT / "apps/padiem-chat/static/chat-conversation-module.js"
    node = shutil.which("node")
    assert node, "node runtime is required"
    script = _USER_COPY_HARNESS.replace("__CONV_PATH__", json.dumps(str(conv)))
    completed = subprocess.run(
        [node, "-e", script],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_canonical_exports_copy_contract():
    text = CANONICAL.read_text(encoding="utf-8")
    assert 'VERSION = "shared-answer-copy-v1"' in text
    assert "function copyText(text)" in text
    assert "SharedAnswerCopy" in text
    assert "PadiemAnswerCopy" in text


def test_b62_index_loads_shared_answer_copy():
    html = _read("apps/padiem-chat/static/index.html")
    assert '<script src="./shared-answer-copy.js"></script>' in html
    shared_at = html.index("./shared-answer-copy.js")
    assert shared_at < html.index("./app.js")
    assert shared_at < html.index("./rich-response.js")
    assert shared_at < html.index("./outputs.js")


def test_b62_answer_actions_use_only_the_shared_copy_execution():
    for relative in (
        "apps/padiem-chat/static/outputs.js",
        "apps/padiem-chat/static/rich-response.js",
    ):
        js = _read(relative)
        assert "window.PadiemAnswerCopy || window.SharedAnswerCopy" in js
        assert "api.copyText(text)" in js
        assert "function fallbackCopy" not in js
        assert "navigator.clipboard" not in js
        assert "document.execCommand" not in js


def test_b62_copy_actions_stay_on_completed_assistant_answers():
    for relative in (
        "apps/padiem-chat/static/outputs.js",
        "apps/padiem-chat/static/rich-response.js",
    ):
        js = _read(relative)
        assert 'messageList.querySelectorAll(".assistant-message").forEach(enhanceAssistantMessage)' in js
        assert 'article.querySelector(".assistant-content")' in js
        assert "if (!lifecycleApi().isCompleted(article))" in js


def test_b62_user_copy_calls_shared_first():
    # #7186 R2: 문자열 순서 대신 addUserMessage의 복사 클릭을 실행한다(#4488).
    # 공유 복사 경로가 우선이고, 공유 스크립트가 없을 때만 레거시
    # navigator.clipboard 경로가 폴백으로 실행된다.
    payload = _run_user_copy_harness()
    assert payload["shared"] == ["안녕"]
    assert payload["clipboard"] == []
    assert payload["fallbackClipboard"] == ["fallback"]
    assert payload["fallbackShared"] == []


def test_b66_index_loads_shared_answer_copy_before_easy_mode():
    html = _read("reference/business-66-padiem-quote-v1/index.html")
    assert '<script src="shared-answer-copy.js" defer></script>' in html
    assert html.index("shared-answer-copy.js") < html.index("easy-mode.js")


def test_b66_real_answers_opt_in_and_status_stays_out():
    easy = _read("reference/business-66-padiem-quote-v1/easy-mode.js")
    assert "window.SharedAnswerCopy" in easy
    assert "PadiemAnswerCopy" not in easy
    assert "Padiem" not in easy
    assert "opts.copyAction === true" in easy
    assert "appendCopyAction(body, content)" in easy
    assert easy.count("copyAction: true") == 1
    assert 'const isModelAnswer = result.answer_origin === "registered_model_completion";' in easy
    assert "copyAction: isModelAnswer" in easy


def test_b66_copy_uses_shared_execution_and_truthful_feedback():
    easy = _read("reference/business-66-padiem-quote-v1/easy-mode.js")
    assert "sharedCopy.copyText(text)" in easy
    assert 'App.toast(ok ? "답변을 복사했습니다." : "답변을 복사하지 못했습니다.");' in easy


def test_static_copies_match_canonical_bytes():
    original = CANONICAL.read_bytes()
    for relative in (
        "apps/padiem-chat/static/shared-answer-copy.js",
        "reference/business-66-padiem-quote-v1/shared-answer-copy.js",
    ):
        assert (ROOT / relative).read_bytes() == original


def test_release_paths_check_shared_answer_copy():
    b62 = (WORKFLOWS / "b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
    b66 = (WORKFLOWS / "b66-neutral-pages-beta.yml").read_text(encoding="utf-8")
    assert b62.count(SYNC_ANSWER_COPY) >= 2
    assert b66.count(SYNC_ANSWER_COPY) >= 1


def test_shared_answer_copy_changes_trigger_release_paths():
    b62 = (WORKFLOWS / "b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
    b66 = (WORKFLOWS / "b66-neutral-pages-beta.yml").read_text(encoding="utf-8")
    assert '"apps/padiem-chat/static/shared-answer-copy.js"' in b62
    for workflow in (b62, b66):
        assert "scripts/sync_shared_answer_copy.py" in workflow
