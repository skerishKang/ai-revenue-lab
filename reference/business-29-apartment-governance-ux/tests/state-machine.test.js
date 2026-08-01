/*  state-machine.test.js  —  repo-local deterministic test suite
 *
 *  Business 29 Phase 2 UX — governance ledger state machine.
 *  No browser, Playwright, CDP or WebBridge. Pure Node + git checks.
 *
 *  Run from repo root:
 *    node reference/business-29-apartment-governance-ux/tests/state-machine.test.js
 */

"use strict";

var assert = require("assert");
var fs = require("fs");
var path = require("path");
var child = require("child_process");

var workspace = path.resolve(__dirname, "..");
var repoRoot = path.resolve(__dirname, "..", "..", "..");

var SM = require(path.join(workspace, "scripts", "state-machine.js"));
var fixture = require(path.join(workspace, "scripts", "fixture.js"));

var failures = [];
function check(name, fn) {
  try {
    fn();
    console.log("[PASS] " + name);
  } catch (err) {
    failures.push(name);
    console.log("[FAIL] " + name + " — " + err.message);
  }
}

function git(args) {
  return child.execSync("git " + args, { cwd: repoRoot, encoding: "utf8" });
}

var REQUIRED_STATES = [
  "empty", "draft", "agenda-ready", "notice-review", "notice-published",
  "attendance-open", "quorum-incomplete", "quorum-recorded", "discussion-open",
  "dissent-recorded", "resolution-draft", "resolution-review", "resolution-approved",
  "action-pending", "action-overdue", "disclosure-review", "redaction-required",
  "public-notice-ready", "public-notice-published", "version-history",
  "system-error", "retry", "cancelled", "completed"
];

/* 1. 24-state contract coverage */
check("24-state contract coverage", function () {
  assert.strictEqual(SM.STATES.length, 24, "exactly 24 states");
  REQUIRED_STATES.forEach(function (s) {
    assert.ok(SM.STATES.indexOf(s) !== -1, "missing state " + s);
  });
  // each state has a deterministic reachability path and TRANSITIONS entry
  REQUIRED_STATES.forEach(function (s) {
    assert.ok(SM.pathTo(s) !== null, "no path to " + s);
    assert.ok(SM.TRANSITIONS[s], "no TRANSITIONS entry for " + s);
  });
  // all 24 reachable deterministically
  REQUIRED_STATES.forEach(function (s) {
    var m = SM.createMachineAt(fixture, s);
    assert.strictEqual(m.state, s, "reach " + s + " but got " + m.state);
  });
});

/* 2. 정상 전체 journey (includes one recoverable system error) */
check("정상 전체 journey (empty → completed)", function () {
  var m = SM.createMachine(fixture);
  var pathSteps = SM.fullJourneyPath();
  for (var i = 0; i < pathSteps.length; i++) {
    m.apply(pathSteps[i][0], pathSteps[i][1] || {});
  }
  assert.strictEqual(m.state, "completed");
  var hasError = m.events.some(function (e) { return e.to === "system-error"; });
  assert.ok(hasError, "full journey should exercise the one injected system error");
  var afterError = m.events.filter(function (e) { return e.to === "public-notice-published"; });
  assert.ok(afterError.length === 1, "notice published exactly once after recovery");
});

/* 3. quorum incomplete block */
check("quorum incomplete block (no discussion/resolution)", function () {
  var m = SM.createMachineAt(fixture, "quorum-incomplete");
  assert.strictEqual(m.allowed("openDiscussion"), false);
  assert.strictEqual(m.allowed("submitForReview"), false);
  assert.strictEqual(m.allowed("approveResolution"), false);
  assert.strictEqual(m.allowed("supplementAttendance"), true);
  assert.strictEqual(m.allowed("postponeMeeting"), true);
  assert.throws(function () { m.apply("openDiscussion"); });
  assert.throws(function () { m.apply("approveResolution"); });
});

/* 4. quorum supplement and recheck */
check("quorum supplement and recheck", function () {
  var m = SM.createMachineAt(fixture, "quorum-incomplete");
  // direct recheck without supplemented attendance is not a shortcut to recorded
  assert.strictEqual(m.apply("supplementAttendance"), "attendance-open");
  assert.strictEqual(m.apply("confirmQuorum", { attendance: 11, threshold: 10, manualConfirm: true }), "quorum-recorded");
  // manual confirm is required
  var m2 = SM.createMachineAt(fixture, "attendance-open");
  assert.throws(function () { m2.apply("confirmQuorum", { attendance: 11, threshold: 10, manualConfirm: false }); });
  // below threshold again stays incomplete
  var m3 = SM.createMachineAt(fixture, "attendance-open");
  assert.strictEqual(m3.apply("confirmQuorum", { attendance: 8, threshold: 10, manualConfirm: true }), "quorum-incomplete");
});

/* 5. dissent retention */
check("dissent retention through resolution", function () {
  var m = SM.createMachineAt(fixture, "resolution-approved");
  assert.ok(m.data.dissent, "dissent retained");
  assert.strictEqual(m.data.dissent.retained, true);
  assert.strictEqual(m.data.resolution.dissentRef, m.data.dissent.agenda);
});

/* 6. private object public-surface exclusion */
check("private object excluded from public surface", function () {
  var m = SM.createMachineAt(fixture, "public-notice-published");
  var pub = m.publicObjects();
  pub.forEach(function (o) {
    assert.notStrictEqual(o.disclosure, "private", "private object leaked to public surface");
  });
  var leakedDiscussion = fixture.discussion.notes.some(function (n) { return n.disclosure === "private"; });
  assert.ok(leakedDiscussion, "fixture has a private discussion note");
  // roster stays private
  assert.strictEqual(fixture.attendance.disclosure, "private");
  // the redacted document appears as redacted (not private, not raw)
  var doc = m.data.documents[0];
  assert.strictEqual(doc.disclosure, "redacted");
  assert.ok(doc.redacted && doc.redacted.confirmed === true, "redacted copy confirmed");
});

/* 7. redaction before public */
check("redaction required before public", function () {
  var m = SM.createMachineAt(fixture, "disclosure-review");
  assert.throws(function () { m.apply("approvePublic"); }, "approvePublic must be blocked while a redactable private doc is unredacted");
  assert.strictEqual(m.apply("requestRedaction"), "redaction-required");
  assert.strictEqual(m.apply("confirmRedaction", { redactedText: "[마스킹] 예산 총액만 공개 (합성)" }), "public-notice-ready");
  assert.strictEqual(m.apply("publishPublicNotice"), "public-notice-published");
});

/* 8. manual disclosure review gate */
check("manual disclosure review gate", function () {
  // no direct path from action-pending/action-overdue to public-notice-ready or published
  assert.strictEqual(SM.TRANSITIONS["action-pending"].proceedToDisclosure, "disclosure-review");
  assert.strictEqual(SM.TRANSITIONS["action-overdue"].proceedToDisclosure, "disclosure-review");
  assert.ok(!SM.TRANSITIONS["action-pending"]["public-notice-ready"], "no bypass");
  assert.ok(!SM.TRANSITIONS["action-overdue"]["public-notice-published"], "no bypass");
  // public-notice-ready/published only reachable through disclosure-review
  assert.ok(SM.TRANSITIONS["disclosure-review"].requestRedaction, "requestRedaction gate present");
  assert.ok(SM.TRANSITIONS["disclosure-review"].approvePublic, "approvePublic gate present");
  assert.ok(SM.TRANSITIONS["redaction-required"].confirmRedaction, "confirmRedaction gate present");
  // approvePublic is blocked while a redactable private doc is unredacted
  var m = SM.createMachineAt(fixture, "disclosure-review");
  assert.throws(function () { m.apply("approvePublic"); });
  assert.strictEqual(m.state, "disclosure-review");
  m.apply("requestRedaction");
  m.apply("confirmRedaction", { redactedText: "[마스킹] 합성" });
  assert.strictEqual(m.state, "public-notice-ready");
});

/* 9. overdue ActionItem */
check("overdue ActionItem surfaced", function () {
  var m = SM.createMachineAt(fixture, "action-overdue");
  assert.ok(m.data.actions.length >= 1);
  assert.strictEqual(m.data.actions[0].overdue, true);
  assert.strictEqual(m.state, "action-overdue");
});

/* 10. system-error and retry state preservation */
check("system-error → retry preserves state", function () {
  var m = SM.createMachineAt(fixture, "notice-review");
  assert.strictEqual(m.apply("publishNotice"), "system-error");
  assert.strictEqual(m._recoverState, "notice-review", "recover target preserved");
  assert.throws(function () { m.apply("completeAgenda"); }, "system-error blocks other actions");
  assert.strictEqual(m.apply("retry"), "retry");
  assert.strictEqual(m.apply("recover"), "notice-review");
  assert.ok(!m.data.notice, "no data written by the failed action");
  assert.strictEqual(m.apply("publishNotice"), "notice-published");
});

/* 11. cancelled/completed behavior */
check("cancelled and completed terminal behavior", function () {
  var mc = SM.createMachineAt(fixture, "cancelled");
  assert.ok(mc.data.postponedNotice, "postponement notice created");
  assert.strictEqual(mc.allowed("startMeeting"), false);
  assert.throws(function () { mc.apply("startMeeting"); });
  var md = SM.createMachineAt(fixture, "completed");
  assert.strictEqual(md.state, "completed");
  assert.throws(function () { md.apply("viewHistory"); }, "completed is terminal");
});

/* 12. Version + AuditEvent generation */
check("Version + AuditEvent generation", function () {
  var m = SM.createMachineAt(fixture, "completed");
  assert.ok(m.events.length >= 20, "journey produces many events");
  m.events.forEach(function (e, i) {
    assert.strictEqual(e.version, i + 1, "version increments deterministically");
    assert.strictEqual(e.audit.type, "state_change");
    assert.ok(e.at === "t" + (i + 1), "deterministic sequence marker");
  });
});

/* fixture mirror == fixture.json */
check("fixture.js mirrors data/fixture.json", function () {
  var json = JSON.parse(fs.readFileSync(path.join(workspace, "data", "fixture.json"), "utf8"));
  assert.deepStrictEqual(fixture, json);
});

/* 13. keyboard contract markers */
check("keyboard contract markers", function () {
  var html = fs.readFileSync(path.join(workspace, "index.html"), "utf8");
  assert.ok(html.indexOf('class="skip-link"') !== -1, "skip link");
  assert.ok(html.indexOf('aria-live="polite"') !== -1, "aria-live");
  assert.ok(html.indexOf('role="tablist"') !== -1, "tablist");
  assert.ok(html.indexOf('role="tab"') !== -1, "tabs");
  assert.ok(html.indexOf("tabindex") !== -1, "focusable main");
  assert.ok(html.indexOf("<button") !== -1, "native buttons (keyboard operable)");
});

/* 14. required authority labels */
check("required authority labels (Phase 1 grammar preserved)", function () {
  var html = fs.readFileSync(path.join(workspace, "index.html"), "utf8");
  var css = fs.readFileSync(path.join(workspace, "styles", "main.css"), "utf8");
  assert.ok(html.indexOf("Resident Assembly Ledger") !== -1, "English masthead");
  assert.ok(html.indexOf("주민총회 원장") !== -1, "Korean masthead");
  ["공개", "비공개", "redacted", "규약·근거", "의결", "감사 기록"].forEach(function (t) {
    assert.ok((html + css).indexOf(t) !== -1, "label missing: " + t);
  });
  assert.ok(css.indexOf("--forest") !== -1 && css.indexOf("--brick") !== -1 && css.indexOf("--brass") !== -1, "charcoal/forest/brick/brass direction");
});

/* 15. 390px CSS contract markers */
check("390px CSS contract markers", function () {
  var css = fs.readFileSync(path.join(workspace, "styles", "main.css"), "utf8");
  assert.ok(css.indexOf("@media(max-width:390px)") !== -1, "explicit 390px breakpoint");
  assert.ok(css.indexOf("@media(prefers-reduced-motion:reduce)") !== -1, "reduced motion");
});

/* 16. external runtime dependency 0 */
check("external runtime dependency 0", function () {
  var files = ["index.html", "scripts/fixture.js", "scripts/state-machine.js", "scripts/app.js", "styles/main.css", "data/fixture.json"];
  files.forEach(function (f) {
    var content = fs.readFileSync(path.join(workspace, f), "utf8");
    var m = content.match(/https?:\/\//g);
    assert.ok(!m, f + " contains external runtime URL(s): " + (m || []).join(","));
  });
});

/* 17. JavaScript syntax */
check("JavaScript syntax", function () {
  ["scripts/fixture.js", "scripts/state-machine.js", "scripts/app.js"].forEach(function (f) {
    var r = child.spawnSync(process.execPath, ["--check", path.join(workspace, f)], { encoding: "utf8" });
    assert.strictEqual(r.status, 0, f + " syntax error: " + r.stderr);
  });
});

/* 18. allowed-scope check */
check("allowed-scope check (only reference/business-29-apartment-governance-ux/ changed)", function () {
  var diff = git("diff --name-only origin/main...HEAD").trim();
  if (diff) {
    diff.split("\n").forEach(function (p) {
      assert.ok(p.indexOf("reference/business-29-apartment-governance-ux/") === 0, "out-of-scope committed path: " + p);
    });
  }
  var refStatus = git("status --porcelain -- reference/").trim();
  if (refStatus) {
    refStatus.split("\n").forEach(function (line) {
      var p = line.slice(3);
      assert.ok(p.indexOf("reference/business-29-apartment-governance-ux/") === 0, "out-of-scope reference change: " + p);
    });
  }
});

/* 19. git diff --check */
check("git diff --check clean", function () {
  var out = git("diff --check origin/main...HEAD").trim();
  assert.strictEqual(out, "", "whitespace errors in branch diff:\n" + out);
  var wd = git("diff --check").trim();
  assert.strictEqual(wd, "", "whitespace errors in working tree:\n" + wd);
});

console.log("");
if (failures.length) {
  console.log(failures.length + " check(s) failed.");
  process.exit(1);
}
console.log("All " + 19 + " Business 29 Phase 2 UX checks passed.");
