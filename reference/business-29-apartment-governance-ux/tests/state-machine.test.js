/*  state-machine.test.js  —  repo-local deterministic test suite (repair)
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
    assert.ok(SM.pathTo(s) !== null, "no path to " + s);
    assert.ok(SM.TRANSITIONS[s], "no TRANSITIONS entry for " + s);
  });
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
    m.apply(pathSteps[i][0], pathSteps[i][1] || {}, SM.ctxFor(pathSteps[i][0]));
  }
  assert.strictEqual(m.state, "completed");
  assert.ok(m.events.some(function (e) { return e.to === "system-error"; }), "system error exercised");
  assert.strictEqual(m.data.disclosureApproved, true, "disclosure approved");
  assert.strictEqual(m.data.published, true, "final publication recorded");
  assert.ok(m.data.reviewedBy && m.data.reviewedVersion, "review recorded");
  assert.ok(m.data.publishedBy && m.data.publishedVersion, "publish recorded");
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
  assert.strictEqual(m.apply("supplementAttendance"), "attendance-open");
  assert.strictEqual(m.apply("confirmQuorum", { attendance: 11, threshold: 10, manualConfirm: true }), "quorum-recorded");
  var m2 = SM.createMachineAt(fixture, "attendance-open");
  assert.throws(function () { m2.apply("confirmQuorum", { attendance: 11, threshold: 10, manualConfirm: false }); });
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

/* 6. no premature disclosure at every lifecycle state */
check("no premature disclosure at every lifecycle state", function () {
  var EXPECTED = {
    "empty": 0, "draft": 0, "agenda-ready": 0, "notice-review": 0,
    "notice-published": 1, "attendance-open": 1, "quorum-incomplete": 1, "quorum-recorded": 1,
    "discussion-open": 1, "dissent-recorded": 1, "resolution-draft": 1, "resolution-review": 1,
    "resolution-approved": 1, "action-pending": 1, "action-overdue": 1, "disclosure-review": 1,
    "redaction-required": 1, "public-notice-ready": 1, "public-notice-published": 8,
    "version-history": 8, "completed": 8, "cancelled": 1, "system-error": 0, "retry": 0
  };
  REQUIRED_STATES.forEach(function (s) {
    var m = SM.createMachineAt(fixture, s);
    var pub = m.publicSurface();
    assert.strictEqual(pub.length, EXPECTED[s], s + ": expected " + EXPECTED[s] + " public projections, got " + pub.length);
    // every public object is a projection (never a raw business object)
    pub.forEach(function (p) {
      assert.ok(p.publicTitle !== undefined, "projection publicTitle");
      assert.ok(p.publicSummary !== undefined, "projection publicSummary");
      assert.ok(p.disclosureState !== undefined, "projection disclosureState");
      assert.ok(p.sourceObjectId !== undefined, "projection sourceObjectId");
      assert.strictEqual(p.text, undefined, "no raw text in projection");
      assert.strictEqual(p.roster, undefined, "no roster in projection");
      assert.strictEqual(p.owner, undefined, "no ActionItem owner in projection");
      assert.strictEqual(p.audit, undefined, "no audit internals in projection");
    });
  });
  // specific: before publication, final package objects never present
  ["dissent-recorded", "resolution-draft", "resolution-review", "resolution-approved", "disclosure-review", "redaction-required", "public-notice-ready"].forEach(function (s) {
    var m = SM.createMachineAt(fixture, s);
    var ids = m.publicSurface().map(function (p) { return p.id; });
    assert.strictEqual(ids.indexOf("resolution"), -1, s + ": resolution leaked");
    assert.strictEqual(ids.indexOf("dissent"), -1, s + ": dissent leaked");
    assert.strictEqual(ids.indexOf("doc-doc-1"), -1, s + ": document leaked");
    assert.strictEqual(ids.indexOf("action-summary"), -1, s + ": action summary leaked");
    assert.strictEqual(ids.indexOf("quorum"), -1, s + ": quorum result leaked");
  });
});

/* 7. approved projections only after final publication */
check("approved projections only after final publication", function () {
  var ready = SM.createMachineAt(fixture, "public-notice-ready");
  var readyIds = ready.publicSurface().map(function (p) { return p.id; });
  assert.strictEqual(readyIds.indexOf("resolution"), -1, "resolution not public before publish");
  assert.strictEqual(readyIds.indexOf("agenda-agenda-1"), -1, "agenda not public before publish");
  assert.strictEqual(readyIds.indexOf("doc-doc-1"), -1, "document not public before publish");
  assert.strictEqual(ready.data.published, false);

  var m = SM.createMachineAt(fixture, "public-notice-published");
  var ids = m.publicSurface().map(function (p) { return p.id; });
  assert.ok(ids.indexOf("meeting-notice") !== -1, "meeting notice public after publish");
  assert.ok(ids.indexOf("resolution") !== -1, "resolution approved projection public after publish");
  assert.ok(ids.indexOf("dissent") !== -1, "dissent projection public after publish");
  assert.ok(ids.indexOf("quorum") !== -1, "quorum projection public after publish");
  assert.ok(ids.indexOf("action-summary") !== -1, "action summary projection public after publish");
  assert.ok(ids.indexOf("doc-doc-1") !== -1, "redacted document projection public after publish");
  assert.strictEqual(m.data.published, true);
  m.publicSurface().forEach(function (p) {
    assert.ok(p.publishedBy, "projection publishedBy stamped");
    assert.ok(p.publishedVersion, "projection publishedVersion stamped");
  });
});

/* 8. redaction required before public + redaction returns to disclosure-review */
check("redaction before public and return to disclosure-review", function () {
  var m = SM.createMachineAt(fixture, "disclosure-review");
  // approvePublic blocked while a redactable private doc is unredacted
  assert.throws(function () {
    m.apply("approvePublic", { manualConfirm: true }, { actor: "검토자(합성)", role: "외부 검토자" });
  }, "approvePublic must block unfinished redaction");
  assert.strictEqual(m.apply("requestRedaction"), "redaction-required");
  assert.strictEqual(m.apply("confirmRedaction", { redactedText: "[마스킹] 합성" }), "disclosure-review", "confirmRedaction returns to disclosure-review");
  var doc = m.data.documents[0];
  assert.ok(doc.redacted && doc.redacted.confirmed === true, "redacted copy confirmed");
  assert.strictEqual(m.apply("approvePublic", { manualConfirm: true }, { actor: "검토자(합성)", role: "외부 검토자" }), "public-notice-ready");
  assert.strictEqual(m.apply("publishPublicNotice", { manualConfirm: true }, { actor: "회장(합성)", role: "대표회의 관리자" }), "public-notice-published");
  assert.strictEqual(m.data.disclosureApproved, true);
  assert.strictEqual(m.data.published, true);
});

/* 9. manual disclosure review gate + publish gate routing */
check("manual disclosure approval and final publish gates", function () {
  assert.strictEqual(SM.TRANSITIONS["action-pending"].proceedToDisclosure, "disclosure-review");
  assert.strictEqual(SM.TRANSITIONS["action-overdue"].proceedToDisclosure, "disclosure-review");
  assert.ok(!SM.TRANSITIONS["action-pending"]["public-notice-ready"], "no bypass to ready");
  assert.ok(!SM.TRANSITIONS["action-overdue"]["public-notice-published"], "no bypass to published");
  assert.ok(SM.TRANSITIONS["disclosure-review"].requestRedaction, "requestRedaction present");
  assert.ok(SM.TRANSITIONS["disclosure-review"].approvePublic, "approvePublic present");
  assert.ok(SM.TRANSITIONS["redaction-required"].confirmRedaction, "confirmRedaction present");
  assert.ok(SM.TRANSITIONS["public-notice-ready"].publishPublicNotice, "publishPublicNotice present");
  var m = SM.createMachineAt(fixture, "disclosure-review");
  assert.strictEqual(m.allowed("publishPublicNotice"), false, "publish not allowed before approval");
});

/* 10. approval gates */
check("approvePublic gate checks", function () {
  var m = SM.createMachineAt(fixture, "disclosure-review");
  // without manual confirm → BLOCK
  assert.throws(function () {
    m.apply("approvePublic", {}, { actor: "검토자(합성)", role: "외부 검토자" });
  }, "manualConfirm required");
  // wrong role → BLOCK
  assert.throws(function () {
    m.apply("approvePublic", { manualConfirm: true }, { actor: "회장(합성)", role: "대표회의 관리자" });
  }, "reviewer role required");
  // unfinished redaction → BLOCK (role ok, manual ok)
  assert.throws(function () {
    m.apply("approvePublic", { manualConfirm: true }, { actor: "검토자(합성)", role: "외부 검토자" });
  }, "redaction required");
});

/* 11. publish gates */
check("publishPublicNotice gate checks", function () {
  var m = SM.createMachineAt(fixture, "public-notice-ready");
  // before approval: cannot reach/execute publish from earlier states
  var pre = SM.createMachineAt(fixture, "disclosure-review");
  assert.strictEqual(pre.allowed("publishPublicNotice"), false, "publish not allowed pre-approval");
  // without manual confirm → BLOCK
  assert.throws(function () {
    m.apply("publishPublicNotice", {}, { actor: "회장(합성)", role: "대표회의 관리자" });
  }, "admin final confirm required");
  // wrong role → BLOCK
  assert.throws(function () {
    m.apply("publishPublicNotice", { manualConfirm: true }, { actor: "검토자(합성)", role: "외부 검토자" });
  }, "admin role required");
  // correct → publish
  assert.strictEqual(m.apply("publishPublicNotice", { manualConfirm: true }, { actor: "회장(합성)", role: "대표회의 관리자" }), "public-notice-published");
  assert.strictEqual(m.data.published, true);
});

/* 12. overdue ActionItem */
check("overdue ActionItem surfaced", function () {
  var m = SM.createMachineAt(fixture, "action-overdue");
  assert.ok(m.data.actions.length >= 1);
  assert.strictEqual(m.data.actions[0].overdue, true);
});

/* 13. system-error and retry state preservation */
check("system-error → retry preserves state", function () {
  var m = SM.createMachineAt(fixture, "notice-review");
  assert.strictEqual(m.apply("publishNotice"), "system-error");
  assert.strictEqual(m._recoverState, "notice-review");
  assert.throws(function () { m.apply("completeAgenda"); }, "system-error blocks other actions");
  assert.strictEqual(m.apply("retry"), "retry");
  assert.strictEqual(m.apply("recover"), "notice-review");
  assert.ok(!m.data.notice, "no data written by failed action");
  assert.strictEqual(m.apply("publishNotice"), "notice-published");
});

/* 14. cancelled/completed behavior */
check("cancelled and completed terminal behavior", function () {
  var mc = SM.createMachineAt(fixture, "cancelled");
  assert.ok(mc.data.postponedNotice, "postponement notice created");
  assert.strictEqual(mc.allowed("startMeeting"), false);
  assert.throws(function () { mc.apply("startMeeting"); });
  var md = SM.createMachineAt(fixture, "completed");
  assert.strictEqual(md.state, "completed");
  assert.throws(function () { md.apply("viewHistory"); }, "completed is terminal");
});

/* 15. Version + AuditEvent generation with actor/role/sequence */
check("Version + AuditEvent generation", function () {
  var m = SM.createMachineAt(fixture, "completed");
  assert.ok(m.events.length >= 20, "journey produces many events");
  m.events.forEach(function (e, i) {
    assert.strictEqual(e.version, i + 1, "version increments deterministically");
    assert.strictEqual(e.sequence, i + 1, "sequence matches version");
    assert.ok(e.from !== undefined && e.to !== undefined && e.action !== undefined, "from/to/action present");
    assert.ok(e.actor && e.role, "actor and role recorded");
  });
});

/* 16. fixture mirror */
check("fixture.js mirrors data/fixture.json", function () {
  var json = JSON.parse(fs.readFileSync(path.join(workspace, "data", "fixture.json"), "utf8"));
  assert.deepStrictEqual(fixture, json);
});

/* 17. leak prevention — serialize final public surface */
check("final public surface leaks no private raw data", function () {
  var m = SM.createMachineAt(fixture, "public-notice-published");
  var s = JSON.stringify(m.publicSurface());
  assert.strictEqual(s.indexOf("roster"), -1, "attendance roster leaked");
  assert.strictEqual(s.indexOf("동대표 갑"), -1, "roster member name leaked");
  assert.strictEqual(s.indexOf("정비 견적을 관리사무소가"), -1, "private discussion text leaked");
  assert.strictEqual(s.indexOf("redaction 대상 문서"), -1, "raw private document note leaked");
  assert.strictEqual(s.indexOf("owner"), -1, "private ActionItem owner leaked");
  assert.strictEqual(s.indexOf("_tick"), -1, "machine internals leaked");
  assert.strictEqual(s.indexOf("audit"), -1, "audit internals leaked");
});

/* 18. audit actor — distinct roles produce distinct event actors */
check("audit actor varies by acting role", function () {
  var m = SM.createMachine(fixture);
  var pathSteps = SM.pathTo("discussion-open");
  for (var i = 0; i < pathSteps.length; i++) {
    m.apply(pathSteps[i][0], pathSteps[i][1] || {}, SM.ctxFor(pathSteps[i][0]));
  }
  m.apply("recordDissent", {}, { actor: "동대표 갑(합성)", role: "동대표·위원" });
  m.apply("finalizeDiscussion", {}, { actor: "회장(합성)", role: "대표회의 관리자" });
  m.apply("submitForReview", {}, { actor: "회장(합성)", role: "대표회의 관리자" });
  m.apply("approveResolution", {}, { actor: "회장(합성)", role: "대표회의 관리자" });
  m.apply("registerActions", {}, { actor: "사무소장(합성)", role: "관리사무소" });
  m.apply("markOverdue", {}, { actor: "사무소장(합성)", role: "관리사무소" });
  m.apply("proceedToDisclosure", {}, { actor: "회장(합성)", role: "대표회의 관리자" });
  m.apply("requestRedaction", {}, { actor: "검토자(합성)", role: "외부 검토자" });
  m.apply("confirmRedaction", { redactedText: "[마스킹] 합성" }, { actor: "검토자(합성)", role: "외부 검토자" });
  m.apply("approvePublic", { manualConfirm: true }, { actor: "검토자(합성)", role: "외부 검토자" });
  m.apply("publishPublicNotice", { manualConfirm: true }, { actor: "회장(합성)", role: "대표회의 관리자" });

  function eventFor(action) {
    for (var j = m.events.length - 1; j >= 0; j--) {
      if (m.events[j].action === action) return m.events[j];
    }
    return null;
  }
  var evDissent = eventFor("recordDissent");
  var evRegister = eventFor("registerActions");
  var evApprove = eventFor("approvePublic");
  var evPublish = eventFor("publishPublicNotice");
  assert.ok(evDissent, "recordDissent event");
  assert.strictEqual(evDissent.role, "동대표·위원");
  assert.strictEqual(evDissent.actor, "동대표 갑(합성)");
  assert.strictEqual(evRegister.role, "관리사무소");
  assert.strictEqual(evRegister.actor, "사무소장(합성)");
  assert.strictEqual(evApprove.role, "외부 검토자");
  assert.strictEqual(evApprove.actor, "검토자(합성)");
  assert.strictEqual(evPublish.role, "대표회의 관리자");
  assert.strictEqual(evPublish.actor, "회장(합성)");
  var actors = [evDissent.actor, evRegister.actor, evApprove.actor, evPublish.actor];
  assert.notStrictEqual(new Set(actors).size, 1, "not all events share one actor");
});

/* 19. keyboard contract markers */
check("keyboard contract markers", function () {
  var html = fs.readFileSync(path.join(workspace, "index.html"), "utf8");
  assert.ok(html.indexOf('class="skip-link"') !== -1, "skip link");
  assert.ok(html.indexOf('aria-live="polite"') !== -1, "aria-live");
  assert.ok(html.indexOf('role="tablist"') !== -1, "tablist");
  assert.ok(html.indexOf('role="tab"') !== -1, "tabs");
  assert.ok(html.indexOf("tabindex") !== -1, "focusable main");
  assert.ok(html.indexOf("<button") !== -1, "native buttons");
});

/* 20. required authority labels */
check("required authority labels (Phase 1 grammar preserved)", function () {
  var html = fs.readFileSync(path.join(workspace, "index.html"), "utf8");
  var css = fs.readFileSync(path.join(workspace, "styles", "main.css"), "utf8");
  assert.ok(html.indexOf("Resident Assembly Ledger") !== -1, "English masthead");
  assert.ok(html.indexOf("주민총회 원장") !== -1, "Korean masthead");
  ["공개", "비공개", "redacted", "규약·근거", "의결", "감사 기록"].forEach(function (t) {
    assert.ok((html + css).indexOf(t) !== -1, "label missing: " + t);
  });
  assert.ok(css.indexOf("--forest") !== -1 && css.indexOf("--brick") !== -1 && css.indexOf("--brass") !== -1, "charcoal/forest/brick/brass");
});

/* 21. 390px CSS contract markers */
check("390px CSS contract markers", function () {
  var css = fs.readFileSync(path.join(workspace, "styles", "main.css"), "utf8");
  assert.ok(css.indexOf("@media(max-width:390px)") !== -1, "explicit 390px breakpoint");
  assert.ok(css.indexOf("@media(prefers-reduced-motion:reduce)") !== -1, "reduced motion");
});

/* 22. external runtime dependency 0 */
check("external runtime dependency 0", function () {
  var files = ["index.html", "scripts/fixture.js", "scripts/state-machine.js", "scripts/app.js", "styles/main.css", "data/fixture.json"];
  files.forEach(function (f) {
    var content = fs.readFileSync(path.join(workspace, f), "utf8");
    var m = content.match(/https?:\/\//g);
    assert.ok(!m, f + " contains external runtime URL(s): " + (m || []).join(","));
  });
});

/* 23. JavaScript syntax */
check("JavaScript syntax", function () {
  ["scripts/fixture.js", "scripts/state-machine.js", "scripts/app.js"].forEach(function (f) {
    var r = child.spawnSync(process.execPath, ["--check", path.join(workspace, f)], { encoding: "utf8" });
    assert.strictEqual(r.status, 0, f + " syntax error: " + r.stderr);
  });
});

/* 24. allowed-scope check */
check("allowed-scope check (only reference/business-29-apartment-governance-ux/ changed)", function () {
  var diff = git("diff --name-only origin/main...HEAD").trim();
  if (diff) {
    diff.split("\n").forEach(function (p) {
      assert.ok(p.indexOf("reference/business-29-apartment-governance-ux/") === 0, "out-of-scope committed path: " + p);
    });
  }
  var refStatus = git("status --porcelain=v1 -z -- reference/");
  if (refStatus) {
    refStatus.split("\0").forEach(function (rec) {
      if (!rec) return;
      var p = rec.slice(3);
      assert.ok(p.indexOf("reference/business-29-apartment-governance-ux/") === 0, "out-of-scope reference change: " + p);
    });
  }
});

/* 25. git diff --check */
check("git diff --check clean", function () {
  var out = git("diff --check origin/main...HEAD").trim();
  assert.strictEqual(out, "", "whitespace errors in branch diff:\n" + out);
  var wd = git("diff --check").trim();
  assert.strictEqual(wd, "", "whitespace errors in working tree:\n" + wd);
});

/* 26. raw governance objects default private */
check("raw governance objects default private", function () {
  assert.strictEqual(fixture.rules[0].disclosure, "private", "rule disclosure private");
  fixture.agenda.forEach(function (a) { assert.strictEqual(a.disclosure, "private", "agenda private: " + a.id); });
  assert.strictEqual(fixture.dissent.disclosure, "private", "dissent private");
  assert.strictEqual(fixture.resolution.disclosure, "private", "resolution private");
  var json = JSON.parse(fs.readFileSync(path.join(workspace, "data", "fixture.json"), "utf8"));
  assert.strictEqual(json.rules[0].disclosure, "private");
  assert.strictEqual(json.resolution.disclosure, "private");
  // raw private objects still do not appear on the public surface
  var m = SM.createMachineAt(fixture, "public-notice-published");
  var ids = m.publicSurface().map(function (p) { return p.id; });
  assert.ok(ids.indexOf("meeting-notice") !== -1, "notice projection public");
  assert.ok(ids.indexOf("agenda-agenda-1") !== -1, "agenda approved projection public");
  assert.ok(ids.indexOf("resolution") !== -1, "resolution approved projection public");
});

/* 27. projection review provenance recorded by approvePublic */
check("projection review provenance recorded after approvePublic", function () {
  var m = SM.createMachineAt(fixture, "public-notice-ready");
  assert.ok(m.data.approvedProjections.length > 0, "approved projections exist");
  m.data.approvedProjections.forEach(function (p) {
    assert.ok(p.reviewedBy, "reviewedBy present: " + p.id);
    assert.ok(p.reviewedVersion, "reviewedVersion present: " + p.id);
  });
  assert.ok(m.data.reviewedBy && m.data.reviewedVersion, "approval review recorded");
});

/* 28. projection publication provenance recorded by publishPublicNotice */
check("projection publication provenance recorded after publish", function () {
  var m = SM.createMachineAt(fixture, "public-notice-published");
  m.publicSurface().forEach(function (p) {
    assert.ok(p.publishedBy, "publishedBy present: " + p.id);
    assert.ok(p.publishedVersion, "publishedVersion present: " + p.id);
    assert.ok(p.reviewedBy && p.reviewedVersion, "review provenance retained: " + p.id);
  });
  assert.ok(m.data.publishedBy && m.data.publishedVersion, "publication recorded");
});

/* 29. publish blocked when review provenance missing */
check("publish blocked when review provenance missing", function () {
  var m = SM.createMachineAt(fixture, "public-notice-ready");
  m.data.approvedProjections[0].reviewedBy = null;
  assert.throws(function () {
    m.apply("publishPublicNotice", { manualConfirm: true }, { actor: "회장(합성)", role: "대표회의 관리자" });
  }, "review provenance required before publish");
  m.data.approvedProjections[0].reviewedBy = "검토자(합성)";
  assert.strictEqual(m.apply("publishPublicNotice", { manualConfirm: true }, { actor: "회장(합성)", role: "대표회의 관리자" }), "public-notice-published");
});

/* 30. notice and postponed notice carry full provenance schema */
check("notice projections carry full provenance schema", function () {
  var mn = SM.createMachineAt(fixture, "notice-published");
  var n = mn.publicSurface()[0];
  ["publicTitle", "publicSummary", "disclosureState", "sourceObjectId", "reviewedBy", "reviewedVersion", "publishedBy", "publishedVersion"].forEach(function (k) {
    assert.ok(n[k] !== undefined, "meeting notice field: " + k);
  });
  var mc = SM.createMachineAt(fixture, "cancelled");
  var p = mc.publicSurface()[0];
  ["publicTitle", "publicSummary", "disclosureState", "sourceObjectId", "reviewedBy", "reviewedVersion", "publishedBy", "publishedVersion"].forEach(function (k) {
    assert.ok(p[k] !== undefined, "postponed notice field: " + k);
  });
});

/* 31. resident tab boundary enforced in app.js source */
check("resident tab boundary enforced (app.js source)", function () {
  var app = fs.readFileSync(path.join(workspace, "scripts", "app.js"), "utf8");
  assert.ok(app.indexOf('currentRole === "일반 주민"') !== -1, "resident check present");
  assert.ok(app.indexOf('currentTab = "ledger"') !== -1, "currentTab reset to ledger present");
  assert.ok(app.indexOf("panelResidentView()") !== -1, "resident view used");
  assert.ok(app.indexOf("tabAllowed(currentRole, currentTab)") !== -1, "renderRuleTabs role re-check");
  assert.ok(app.indexOf("tabAllowed(currentRole, tab)") !== -1, "tab click role guard");
  assert.ok(app.indexOf("btn.disabled = !allowed") !== -1, "tabs disabled for unauthorized roles");
  assert.ok(app.indexOf("일반 주민은 Disclosure 검토를 거쳐 게시된 공개 projection만 열람할 수 있습니다.") !== -1, "resident reason text");
});

/* 32. internal tabs exclude 일반 주민 (app.js source) */
check("internal tabs exclude 일반 주민", function () {
  var app = fs.readFileSync(path.join(workspace, "scripts", "app.js"), "utf8");
  assert.ok(app.indexOf('rulebook: ["대표회의 관리자", "동대표·위원", "관리사무소", "감사", "외부 검토자"]') !== -1, "rulebook role list excludes resident");
  assert.ok(app.indexOf('documents: ["대표회의 관리자", "관리사무소", "감사", "외부 검토자"]') !== -1, "documents role list excludes resident");
  assert.ok(app.indexOf('history: ["대표회의 관리자", "동대표·위원", "관리사무소", "감사", "외부 검토자"]') !== -1, "history role list excludes resident");
  var html = fs.readFileSync(path.join(workspace, "index.html"), "utf8");
  assert.ok(html.indexOf('id="tab-note"') !== -1, "tab reason note element present");
});

/* 33. resident role switch resets currentTab (app.js source) */
check("resident role switch resets currentTab", function () {
  var app = fs.readFileSync(path.join(workspace, "scripts", "app.js"), "utf8");
  var reset = app.indexOf('if (currentRole === "일반 주민") {');
  assert.ok(reset !== -1, "resident branch present");
  assert.ok(app.indexOf('currentTab = "ledger";', reset) !== -1, "reset to ledger inside resident branch");
});

/* 34. resident screen HTML leaks no raw governance information */
check("resident screen HTML leaks no raw governance data", function () {
  function residentHtml(m) {
    return m.publicSurface().map(function (o) {
      return "<li><strong>" + (o.publicTitle || o.id) + "</strong> " + (o.disclosureState || "public") + "<small>" + (o.publicSummary || "") + "</small></li>";
    }).join("");
  }
  var m = SM.createMachineAt(fixture, "public-notice-published");
  var h = residentHtml(m);
  assert.strictEqual(h.indexOf("재적 대표의 3분의 1"), -1, "raw rule excerpt leaked");
  assert.strictEqual(h.indexOf("redaction 대상 문서"), -1, "private document note leaked");
  assert.strictEqual(h.indexOf("동대표 갑"), -1, "attendance roster leaked");
  assert.strictEqual(h.indexOf("정비 견적을 관리사무소가"), -1, "private discussion leaked");
  assert.strictEqual(h.indexOf("owner"), -1, "ActionItem owner leaked");
  assert.strictEqual(h.indexOf("state_change"), -1, "audit internals leaked");
});

console.log("");
if (failures.length) {
  console.log(failures.length + " check(s) failed.");
  process.exit(1);
}
console.log("All 34 Business 29 Phase 2 UX final boundary repair checks passed.");
