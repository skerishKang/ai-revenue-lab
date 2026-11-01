"use strict";
// #5882 follow-up (261102): the pending-cap refusal shows a Korean sentence
// owned by locale.js, and keeps the internal server code off the panel.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const KO = "엑셀 선택 대기가 너무 많아요. 잠시 뒤 다시 시도하거나 열린 선택 창을 닫아 주세요.";
const MODULE = path.join(__dirname, "..", "static", "claw-web-xlsx-sources.js");

global.window = { __padiemLocale: { text: (key) => (key === "web-xlsx-pending-full" ? KO : key) } };
const office = require(MODULE);

assert.deepEqual(office.refusalPresentation("web_xlsx_selection_refused"),
  { message: KO, hideCode: true });
assert.equal(office.refusalPresentation("unauthorized"), null);
assert.equal(office.refusalPresentation("web_xlsx_selection_unavailable"), null);
assert.equal(office.refusalPresentation(undefined), null);

// Without the locale module the refusal still hides the machine code, and the
// panel's existing generic Korean sentence takes over (message stays empty
// here so jsonRequest falls through to its closed fallback chain).
delete require.cache[require.resolve(MODULE)];
global.window = {};
const bare = require(MODULE);
assert.deepEqual(bare.refusalPresentation("web_xlsx_selection_refused"),
  { message: "", hideCode: true });

// The sentence is owned by locale.js in both languages, never hand-written
// into the panel.
const sources = fs.readFileSync(MODULE, "utf8");
assert.ok(!sources.includes("엑셀 선택 대기가"));
assert.ok(sources.includes('"web-xlsx-pending-full"'));
const locale = fs.readFileSync(path.join(__dirname, "..", "static", "locale.js"), "utf8");
assert.equal(locale.split('"web-xlsx-pending-full"').length - 1, 2);
assert.ok(locale.includes(KO));
assert.ok(/web-xlsx-pending-full": "Too many Excel selections are waiting\./.test(locale));
console.log("web XLSX pending-cap copy: PASS");
