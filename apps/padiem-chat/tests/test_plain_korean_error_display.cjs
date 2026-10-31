// Exercise the shipped transport and both Chat error renderers together.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const staticDir = path.join(__dirname, "..", "static");
global.window = globalThis;
vm.runInThisContext(fs.readFileSync(path.join(staticDir, "chat-transport.js"), "utf8"));
const app = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const start = app.indexOf("  const FAILURE_CODE_PATTERN =");
const end = app.indexOf("\n  function renderCancelled(", start);
assert.ok(start >= 0 && end > start);
const context = {
  document: {createElement: (tag) => ({tag})},
  uiT: (key) => key === "error-code-reference" ? "참고 코드" : key,
  MESSAGE_LIFECYCLE: {FAILED: "failed", TIMED_OUT: "timed_out"},
  PadiemChatLifecycle: {set: (article, value) => { article.state = value; }},
  window: {PadiemChatLifecycle: {applyRuntimeLabel: () => {}}},
  buildRetryBox: (message) => ({message, children: [], appendChild(child) {this.children.push(child);}}),
  revealErrorState: () => {},
};
const render = vm.runInNewContext("(function(){" + app.slice(start, end) +
  "\nreturn {renderError, renderStreamError};})()", context);

for (const [code, status, expected] of [
  ["entitlement_unavailable", 503, "지금은 서비스를 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."],
  ["invalid_request", 400, "요청 내용을 확인할 수 없습니다. 내용을 확인한 뒤 다시 시도해 주세요."],
  ["unknown_failure", 500, "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."],
]) {
  const data = {ok: false, error: {code, message: "private provider error " + code}};
  const failure = PadiemChatTransport.errorFor(data, "unsafe fallback", status);
  assert.equal(failure.code, code);
  assert.equal(failure.terminalRecord, true);
  assert.equal(failure.message, expected);
  assert.equal(PadiemChatTransport.streamErrorMessage(data, status), expected);
  assert.ok(!failure.message.includes(code));
  for (const streaming of [false, true]) {
    const content = {
      children: [], replaceChildren() {this.children = [];},
      querySelector() {return null;}, appendChild(box) {this.children.push(box);},
    };
    const article = {querySelector: (selector) => selector === ".assistant-content" ? content : {}};
    if (streaming) {
      render.renderStreamError(article, expected, [], null, null, false, "failed", null, failure.code);
    } else {
      render.renderError(article, failure.message, [], null, null, null, false, "failed", null, failure.code);
    }
    const box = content.children[0];
    assert.equal(box.message, expected);
    assert.equal(box.children.length, 1);
    assert.equal(box.children[0].tag, "small");
    assert.equal(box.children[0].className, "error-code");
    assert.equal(box.children[0].textContent, "참고 코드: " + code);
    assert.equal(article.state, "failed");
  }
}
// Stream messages must use the closed mapping, even before the first token.
const streamStart = app.indexOf("  async function requestStreamingAnswer(");
const streamEnd = app.indexOf("\n  function cancelActiveStream(", streamStart);
const stream = app.slice(streamStart, streamEnd);
assert.ok(stream.includes(": chatTransport.streamErrorMessage(data);"));
assert.ok(!stream.includes("? data.error.message"));
console.log("three error cases: sentence and separate reference verified");
