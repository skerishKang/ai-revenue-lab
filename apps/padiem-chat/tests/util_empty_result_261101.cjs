const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");
const base = path.join(__dirname, "..", "static");
const transportSource = fs.readFileSync(path.join(base, "chat-transport.js"), "utf8");
const source = fs.readFileSync(path.join(base, "util-menu.js"), "utf8");
const start = source.indexOf("  const GEN_ERROR_COPY =");
const end = source.indexOf("\n  async function getProjects()", start);
const host = {
  TextDecoder, TextEncoder, AbortController, Response, ReadableStream,
  setTimeout, clearTimeout, console, window: {},
  document: { createElement: () => ({}) },
};
vm.createContext(host);
vm.runInContext(transportSource, host);
const api = vm.runInContext("(function(){"+source.slice(start,end)+";return {apiChat,showGenerationFailure};})()",host);
function response(chunks) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), {headers: {"Content-Type": "text/event-stream"}});
}
function show(error) {
  const output = {value: "", parentNode: null};
  const retry = {hidden: true};
  api.showGenerationFailure(output, retry, error);
  assert.equal(retry.hidden, false);
  assert.ok(!output.value.includes("private_provider_code"));
  return output.value;
}
(async () => {
  const progress = [], sent = [];
  host.fetch = async (url, opts) => {
    sent.push([url, JSON.parse(opts.body), opts.credentials]);
    return response(['event: delta\ndata: {"delta":"첫"}\n\n',
      'event: delta\ndata: {"delta":" 문장"}\n\n',
      'event: done\ndata: {"done":true}\n\n']);
  };
  assert.equal(await api.apiChat("test", "speech", text => progress.push(text)), "첫 문장");
  assert.deepEqual(progress, ["첫", "첫 문장"]);
  assert.equal(sent[0][0], "/api/chat/stream");
  assert.equal(sent[0][1].util, "speech");
  assert.equal(sent[0][2], "include");
  for (const [label, chunks] of [
    ["empty", ['event: done\ndata: {"done":true}\n\n']],
    ["interrupted", ['event: delta\ndata: {"delta":"일부"}\n\n']],
    ["error", ['event: error\ndata: {"error":{"code":"private_provider_code","message":"secret"}}\n\n']],
  ]) {
    host.fetch = async () => response(chunks);
    let caught;
    try { await api.apiChat("test", "speech", () => {}); } catch (error) { caught = error; }
    assert.ok(caught, label);
    const text = show(caught);
    if (label !== "error") assert.ok(text.includes("답을 받지 못했습니다. 다시 시도해 주세요."));
  }
  host.fetch = async () => new Response(JSON.stringify({answer:""}), {headers:{"Content-Type":"application/json"}});
  await assert.rejects(api.apiChat("test","speech"), (e) => { assert.ok(show(e).includes("답을 받지 못했습니다.")); return true; });
  console.log("stream, empty, interruption and error: PASS");
})().catch(error => { console.error(error); process.exitCode = 1; });
