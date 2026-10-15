"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../static");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const app = fs.readFileSync(path.join(root, "app.js"), "utf8");
const capture = fs.readFileSync(path.join(root, "meeting-capture.js"), "utf8");
const views = fs.readFileSync(path.join(root, "standalone-views.css"), "utf8");
const locale = fs.readFileSync(path.join(root, "locale.js"), "utf8");

test("meeting has one first-class menu entry alongside Claw", () => {
  const claw = html.indexOf('id="clawNavButton"');
  const meeting = html.indexOf('id="meetingNavButton"');
  const calendar = html.indexOf('id="calendarNavButton"');
  assert.ok(claw > 0 && claw < meeting && meeting < calendar);
  assert.equal((html.match(/id="meetingNavButton"/g) || []).length, 1);
  assert.match(html, /id="meetingNavButton"[^>]+aria-controls="meetingView"[^>]+disabled/);
  assert.match(html, /data-locale-key="nav-meeting"/);
  assert.match(locale, /"nav-meeting": "Meeting notes"/);
  assert.match(locale, /"nav-meeting": "회의록"/);
});

test("meeting is a central workspace, never modal or second site", () => {
  assert.match(html, /<section id="meetingView" class="standalone-view meeting-view"[^>]*hidden>/);
  assert.doesNotMatch(html, /<dialog id="meetingDialog"/);
  assert.ok(html.indexOf('class="main-panel"') < html.indexOf('id="meetingView"'));
  assert.match(views, /\.app-shell\[data-state="meeting"\] \.meeting-view/);
  assert.match(views, /\.app-shell\[data-state="meeting"\] \.composer-wrap/);
  assert.match(app, /meetingView\.hidden = state !== "meeting"/);
  assert.match(app, /meetingNav\.setAttribute\("aria-current", state === "meeting"/);
});

test("Claw and menu share one recorder and explicit return path", () => {
  assert.match(capture, /getElementById\("meetingView"\)/);
  assert.match(capture, /getElementById\("meetingNavButton"\)/);
  assert.doesNotMatch(capture, /showModal\(|createElement\("dialog"\)|appendChild\(trigger\)/);
  assert.match(capture, /new win\.CustomEvent\("padiem:meeting-open"\)/);
  assert.match(app, /padiem:meeting-open/);
  assert.match(capture, /find\("clawNavButton"\)\?\.click\(\)/);
  assert.match(capture, /controller\.snapshot\(\)\.active && !uploadInFlight/);
});
