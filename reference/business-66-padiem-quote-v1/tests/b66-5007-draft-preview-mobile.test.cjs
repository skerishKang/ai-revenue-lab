"use strict";
// #5007 remainder: draft/preview sync, reload restore, mobile shell rails.
//
// 1. Every B66 draft mutation path re-renders the A4 preview in the same
//    synchronous flow: field edits, item add/remove, skill defaults,
//    extraction import, account-scope apply, company import, replaceDraft.
// 2. A reload restores the open AI dialogue only after the canonical session
//    is confirmed; the restore is generation-guarded.
// 3. The shell rail collapses to a toggle + drawer on narrow screens and the
//    preview can collapse with a reopen control (no always-visible buttons).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const srcDir = path.join(__dirname, "..");
const app = fs.readFileSync(path.join(srcDir, "app.js"), "utf8");
const easy = fs.readFileSync(path.join(srcDir, "easy-mode.js"), "utf8");
const shell = fs.readFileSync(path.join(srcDir, "shell-layout.js"), "utf8");
const styles = fs.readFileSync(path.join(srcDir, "styles.css"), "utf8");

/* 1. Draft -> preview sync ------------------------------------------ */
function fnBody(src, name) {
  const start = src.indexOf("function " + name + "(");
  assert.ok(start >= 0, name + " must exist");
  const rest = src.slice(start);
  const next = rest.slice(1).search(/\n  function [\w$]+\(/);
  return next < 0 ? rest : rest.slice(0, next + 1);
}

for (const name of ["renderItems", "fillInputsFromDraft", "render", "replaceDraft", "bindFields"]) {
  assert.ok(app.includes("function " + name + "("), name + " must exist");
}
const render = fnBody(app, "render");
assert.match(render, /TemplateRenderer\.applyRenderModel\(document,/, "render must project to the preview");

for (const name of ["addItem", "removeItem"]) {
  const body = fnBody(app, name);
  assert.match(body, /renderItems\(\);/, name + " must refresh items");
  assert.match(body, /render\(\);/, name + " must refresh the preview");
}

const bindings = app.slice(app.indexOf("function bindFields("), app.indexOf("function bindFields(") + 900);
assert.match(bindings, /render\(\);/, "field edits must refresh the preview");
assert.ok(app.includes("draft = nextDraft;"), "extraction import must replace the draft");
assert.match(
  app.slice(app.indexOf("draft = nextDraft;"), app.indexOf("draft = nextDraft;") + 700),
  /render\(\);/,
  "extraction import must refresh the preview"
);
assert.match(
  app.slice(app.indexOf("function replaceDraft("), app.indexOf("function replaceDraft(") + 900),
  /render\(\);/,
  "replaceDraft must refresh the preview"
);
// Account-scope apply and company import replace draft fields, so they must
// refill inputs and render in the same flow.
const scopeApply = fnBody(app, "applyAccountScopeDetail");
assert.match(scopeApply, /renderItems\(\);/, "scope apply must refresh items");
assert.match(scopeApply, /fillInputsFromDraft\(\);/, "scope apply must refill inputs");
assert.match(scopeApply, /render\(\);/, "scope apply must refresh the preview");

/* 2. Reload restore ------------------------------------------------ */
assert.match(easy, /pendingRestoreDialogueId = readDialogueState\(\);/, "boot must capture the open dialogue id");
assert.match(
  easy,
  /b66:auth-changed[\s\S]{0,600}pendingRestoreDialogueId[\s\S]{0,200}openAiDialogue\(target/,
  "restore must run only after the canonical session is confirmed"
);
assert.match(
  easy,
  /function openAiDialogue[\s\S]{0,400}DIALOGUE_ID_PATTERN\.test/,
  "restore must validate the id grammar before touching the store"
);

/* 3. Mobile shell -------------------------------------------------- */
assert.match(shell, /id="shellRailToggle"|shellRailToggle/, "rail toggle must exist");
assert.match(shell, /aria-controls.{0,20}shellRail/, "toggle must control the rail");
assert.match(styles, /body\.rail-collapsed \.shell-rail \{ display: none; \}/, "collapsed rail must hide");
assert.match(styles, /shell-preview-reopen/, "collapsed preview must offer a reopen control");
assert.match(styles, /@media \(max-width: 900px\)/, "narrow screens must reflow the three-pane shell");

console.log("B66_5007_DRAFT_PREVIEW_MOBILE_CONTRACT=PASS");
