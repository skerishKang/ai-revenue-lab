// #4816: Node unit test for the shared voice turn controller (M2/M3/M4 coordinator).
// No browser, no network: pure state-machine contract.
"use strict";
const assert = require("assert");
const api = require("../static/voice-live-turn-controller.js");

let pass = 0;
let fail = 0;
function t(name, fn) {
  try {
    fn();
    pass += 1;
    process.stdout.write("ok - " + name + "\n");
  } catch (e) {
    fail += 1;
    process.stdout.write("NOT ok - " + name + ": " + (e && e.message ? e.message : String(e)) + "\n");
  }
}

function make(overrides) {
  overrides = overrides || {};
  let user = "u1";
  let busy = false;
  let enabled = true;
  const commits = [];
  const sends = [];
  const previews = [];
  const opts = {
    accountKey: user,
    getAccountKey: function () { return user; },
    getInFlight: function () { return busy; },
    getCanSubmit: function () { return enabled; },
    commitText: function (text) { commits.push(text); return true; },
    submit: function (text, meta) { sends.push([text, meta]); return true; },
    onPreview: function (text) { previews.push(text); },
  };
  Object.assign(opts, overrides);
  const c = api.create(opts);
  return {c: c, commits: commits, sends: sends, previews: previews};
}

const event = function (id, text, generation, flags) {
  const p = {
    accountKey: "u1",
    sessionGeneration: generation == null ? 1 : generation,
    accepted: true,
    endOfTurn: true,
    finalId: id,
    text: text,
  };
  if (flags) Object.assign(p, flags);
  return p;
};

t("constructor starts in basic mode (no auto-send)", function () {
  const {c} = make();
  assert.strictEqual(c.getState().mode, "basic");
  assert.strictEqual(c.getState().sessionGeneration, 1);
  assert.strictEqual(c.getState().waitingForAnswer, false);
});

t("setMode(\"live\") arms auto-send and advances generation", function () {
  const {c} = make();
  const g0 = c.getState().sessionGeneration;
  c.setMode("live");
  assert.strictEqual(c.getState().mode, "live");
  assert(c.getState().sessionGeneration > g0, "generation should rotate on mode change");
});

t("syncSessionGeneration adopts the composer run generation (set semantics)", function () {
  const {c} = make();
  c.syncSessionGeneration(7);
  assert.strictEqual(c.getState().sessionGeneration, 7);
  c.syncSessionGeneration(4);
  assert.strictEqual(c.getState().sessionGeneration, 4, "composer generation wins on sync");
});

t("interim text previews but never submits", function () {
  const {c, sends, previews} = make();
  c.setMode("live");
  const r = c.handleInterim({accountKey: "u1", sessionGeneration: c.getState().sessionGeneration, isInterim: true, text: "preview"});
  assert.strictEqual(r.submitted, false);
  assert.strictEqual(sends.length, 0);
  assert.strictEqual(previews.length, 1);
  assert.strictEqual(previews[0], "preview");
});

t("handleFinal rejects missing fields", function () {
  const {c, sends} = make();
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  const base = {accountKey: "u1", sessionGeneration: gen, accepted: true, endOfTurn: true, finalId: "f1", text: "hi"};
  t_inner("missing accountKey", function () { assert.strictEqual(c.handleFinal(Object.assign({}, base, {accountKey: undefined})).submitted, false); });
  t_inner("missing sessionGeneration", function () { assert.strictEqual(c.handleFinal(Object.assign({}, base, {sessionGeneration: undefined})).submitted, false); });
  t_inner("missing finalId", function () { assert.strictEqual(c.handleFinal(Object.assign({}, base, {finalId: undefined})).submitted, false); });
  t_inner("missing accepted", function () { assert.strictEqual(c.handleFinal(Object.assign({}, base, {accepted: undefined})).submitted, false); });
  t_inner("missing endOfTurn", function () { assert.strictEqual(c.handleFinal(Object.assign({}, base, {endOfTurn: undefined})).submitted, false); });
  t_inner("endOfTurn false", function () { assert.strictEqual(c.handleFinal(Object.assign({}, base, {endOfTurn: false})).submitted, false); });
  assert.strictEqual(sends.length, 0);
  function t_inner(name, fn) { t(name, fn); }
});

t("rejects stale generation and unauthenticated account", function () {
  const {c, sends} = make();
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  assert.strictEqual(c.handleFinal(event("f1", "hi", gen - 1)).submitted, false, "stale generation");
  assert.strictEqual(c.handleFinal(Object.assign({}, event("f1", "hi", gen), {accountKey: "u2"})).submitted, false, "account mismatch");
  assert.strictEqual(sends.length, 0);
});

t("rejects while another answer is pending (overlap)", function () {
  const {c, sends} = make();
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  assert.strictEqual(c.handleFinal(event("f1", "first", gen)).submitted, true, "first submits");
  assert.strictEqual(c.handleFinal(event("f2", "second", gen)).submitted, false, "overlap blocked");
  assert.strictEqual(sends.length, 1);
});

t("exactly one submit per accepted turn and dedup repeats", function () {
  const {c, sends} = make();
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  const r1 = c.handleFinal(event("f1", "hello", gen));
  assert.strictEqual(r1.submitted, true);
  assert.strictEqual(sends.length, 1);
  assert.strictEqual(sends[0][0], "hello");
  assert.strictEqual(c.handleFinal(event("f1", "hello", gen)).submitted, false, "duplicate finalId rejected");
  assert.strictEqual(sends.length, 1);
});

t("next turn allowed after answer settled", function () {
  const {c, sends} = make();
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  const first = c.handleFinal(event("f1", "first", gen));
  assert.strictEqual(first.submitted, true);
  assert.strictEqual(c.markAnswerSettled({accountKey: "u1", finalKey: first.finalKey}).ok, true, "settle accepted");
  assert.strictEqual(c.markAnswerSettled({accountKey: "u1", finalKey: "wrong"}).ok, false, "wrong answer rejected");
  assert.strictEqual(c.handleFinal(event("f2", "second", gen)).submitted, true, "next turn submits");
  assert.strictEqual(sends.length, 2);
});

t("account switch revokes pending turn", function () {
  const {c, sends} = make();
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  assert.strictEqual(c.handleFinal(event("f1", "hi", gen)).submitted, true);
  c.setAccountKey("u2");
  assert.strictEqual(c.handleFinal(event("f2", "stale", c.getState().sessionGeneration)).submitted, false, "new account blocked");
  assert.strictEqual(sends.length, 1);
});

t("cancel revokes pending turn", function () {
  const {c, sends} = make();
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  assert.strictEqual(c.handleFinal(event("f1", "hi", gen)).submitted, true);
  c.cancel();
  assert.strictEqual(c.handleFinal(event("f2", "stale", c.getState().sessionGeneration)).submitted, false, "cancel revoked");
  assert.strictEqual(sends.length, 1);
});

t("unauthenticated adapter blocks submission", function () {
  const c = api.create({
    accountKey: "u1", getAccountKey: function () { return null; },
    getInFlight: function () { return false; }, getCanSubmit: function () { return true; },
    commitText: function () { return true; }, submit: function () { return true; },
  });
  c.setMode("live");
  assert.strictEqual(c.handleFinal(event("f1", "hi", c.getState().sessionGeneration)).submitted, false);
});

t("in-flight submission blocks further sends", function () {
  const {c, sends} = make({getCanSubmit: function () { return false; }});
  c.setMode("live");
  const gen = c.getState().sessionGeneration;
  assert.strictEqual(c.handleFinal(event("f1", "hi", gen)).submitted, false, "not ready while not submittable");
  assert.strictEqual(sends.length, 0);
});

process.stdout.write(fail === 0 ? "ALL PASS (" + pass + ")\n" : "FAILURES: " + fail + " / " + (pass + fail) + "\n");
process.exit(fail === 0 ? 0 : 1);
