// #7960: a live Chat session with an expired B54 canonical session must show
// the person a sign-in affordance, not just a dead error. The server code is
// fail-closed and the UI keeps the same re-login walk.
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const path = require("node:path");
const staticDir = path.join(__dirname, "..", "static");

const CODE = "chat_pc_b54_session_expired";
const KO = "로그인이 오래돼 PC 연결 확인이 필요합니다. 로그아웃 후 다시 로그인해 주세요.";

test("the streaming lane opens the sign-in dialog for the B54 expiry", () => {
  const stream = fs.readFileSync(path.join(staticDir, "chat-streaming-module.js"), "utf8");
  const start = stream.indexOf('error.code === "login_required"');
  assert.ok(start >= 0, "the existing login-required path is present");
  const tail = stream.slice(start, start + 900);
  assert.match(tail, /chat_pc_b54_session_expired/,
    "the B54 expiry shares the login path");
  assert.match(tail, /deps\.openAuthDialog\(\)/,
    "the shared path shows the sign-in dialog, i.e. the login button UI");
});

test("the server code carries the same human message on both UI surfaces", () => {
  const transport = fs.readFileSync(path.join(staticDir, "chat-transport.js"), "utf8");
  const app = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
  assert.match(transport, new RegExp(`case "${CODE}"`));
  assert.match(app, new RegExp(`${CODE}: Object.freeze`));
  assert.ok(transport.includes(KO));
});

test("ko and en locale carry the re-login walk", () => {
  const locale = fs.readFileSync(path.join(staticDir, "locale-pc-connect.js"), "utf8");
  assert.ok(locale.includes(KO));
  assert.match(locale, /Your sign-in is too old for the PC connection check/);
});
