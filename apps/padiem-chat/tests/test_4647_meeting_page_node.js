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
const sidebarCss = fs.readFileSync(path.join(root, "sidebar-utility.css"), "utf8");
const clawCss = fs.readFileSync(path.join(root, "claw-focus-layout.css"), "utf8");
const meetingCss = fs.readFileSync(path.join(root, "meeting-capture.css"), "utf8");
const frame = fs.readFileSync(path.join(root, "shared-six-panel-frame.css"), "utf8");
const surfaces = fs.readFileSync(path.join(root, "padiem-surfaces.css"), "utf8");
const cinematic = fs.readFileSync(path.join(root, "padiem-cinematic-chat.css"), "utf8");

test("Chat and Claw share a group; meeting, automation, library, calendar follow in exact order", () => {
  const order = [
    "newChatButton", "sidebarSearchButton", "clawNavButton",
    "meetingNavButton", "automationNavButton", "filesNavButton",
    "calendarNavButton", "connectorsNavButton", "skillsNavButton",
  ];
  const positions = order.map((id) => html.indexOf('id="' + id + '"'));
  assert.ok(positions.every((p) => p >= 0), "all existing navigation actions must be preserved");
  assert.deepEqual([...positions].sort((a, b) => a - b), positions);
  assert.ok(html.indexOf('class="sidebar-chat-claw-group"') < positions[0]);
  const workspace = html.indexOf('id="workspaceNav"');
  assert.ok(workspace > positions[2] && workspace < positions[3]);
  assert.match(sidebarCss, /\.sidebar-chat-claw-group\s*\{[\s\S]*?display:\s*flex;/);
  assert.match(clawCss, /#workspaceNav \.side-item:disabled\s*\{[\s\S]*?display:\s*flex;/);
  assert.equal((html.match(/id="meetingNavButton"/g) || []).length, 1);
  assert.doesNotMatch(html, /id="automationNavButton"[^>]*disabled/);
  assert.doesNotMatch(html, /id="filesNavButton"[^>]*disabled/);
  assert.doesNotMatch(html, /id="meetingNavButton"[^>]*disabled/);
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

test("one recorder, no private exit control, and the draft path still returns to Claw", () => {
  assert.match(capture, /getElementById\("meetingView"\)/);
  assert.match(capture, /getElementById\("meetingNavButton"\)/);
  assert.doesNotMatch(capture, /showModal\(|createElement\("dialog"\)|appendChild\(trigger\)/);
  assert.match(capture, /new win\.CustomEvent\("padiem:meeting-open"\)/);
  assert.match(app, /padiem:meeting-open/);
  assert.match(capture, /clawNav\.click\(\);/);
  assert.match(capture, /controller\.snapshot\(\)\.active && !uploadInFlight/);
  // Leaving the page is the sidebar's job, and the recorder still owns that gate.
  assert.doesNotMatch(capture, /meetingClose/);
  assert.match(capture, /\.side-nav \.side-item, #newChatButton/);
});

test("meeting header reuses the shared standalone view pattern and carries its own brand", () => {
  const start = html.indexOf('<section id="meetingView"');
  const meeting = html.slice(start, html.indexOf("</section>", start));
  assert.ok(start >= 0, "meeting workspace must exist");
  assert.match(meeting, /class="standalone-view-header meeting-header"/);
  assert.match(meeting, /class="standalone-view-kicker" data-locale-key="meeting-kicker"/);
  assert.match(meeting, /class="standalone-view-title" id="meetingTitle" data-locale-key="meeting-title"/);
  assert.doesNotMatch(meeting, /meetingClose|Claw로 돌아가기/);
  assert.doesNotMatch(meeting, /PADIEM CLAW/);
  assert.doesNotMatch(locale, /meeting-close/);
  // Every destination eyebrow is a Latin brand string in both locales; the meeting
  // page follows the same rule instead of translating the brand.
  assert.equal((locale.match(/"meeting-kicker": "PADIEM MEETING"/g) || []).length, 2);
  assert.match(locale, /"meeting-title": "Meeting notes"/);
  assert.match(locale, /"meeting-title": "회의록"/);
});

test("meeting first screen rises on the shared Chat/Claw curve", () => {
  assert.match(meetingCss, /\.meeting-header \{\s*animation: padiem-rise \.72s cubic-bezier\(\.2, \.75, \.2, 1\) both; \}/);
  assert.match(meetingCss, /\.meeting-panel \{\s*animation: padiem-rise \.82s \.08s cubic-bezier\(\.2, \.75, \.2, 1\) both; \}/);
  // The keyframes live in an imported sheet, so prove the page actually loads it.
  assert.match(surfaces, /@keyframes padiem-rise \{/);
  assert.match(cinematic, /@import url\('\.\/padiem-surfaces\.css'\);/);
  assert.match(html, /href="\.\/padiem-cinematic-chat\.css"/);
});

test("meeting view joins the shared glass frame instead of drawing its own surface", () => {
  assert.match(views, /html\[data-theme="padiem-glass"\][^\n]*\[data-state="meeting"\][^\n]*\.standalone-view-kicker \{/);
  assert.match(views, /html\[data-theme="padiem-glass"\][^\n]*\[data-state="meeting"\][^\n]*\.standalone-view-kicker::before/);
  assert.equal((frame.match(/\.automation-view, \.meeting-view/g) || []).length, 3,
    "meeting must be in all three six-panel frame lists");
  assert.ok(frame.includes(".calendar-view, .connectors-view"), "the owner visual-lock frame literal stays intact");
  assert.doesNotMatch(meetingCss, /max-width:\s*1080px/);
  assert.doesNotMatch(meetingCss, /\.meeting-header\s+(p|h2)\s*\{/);
  assert.match(meetingCss, /@media \(min-width: 921px\)[\s\S]*data-state="meeting"\] \.meeting-panel \{[\s\S]*border: 0;/);
  assert.match(meetingCss, /@media \(max-width: 920px\)[\s\S]*data-state="meeting"\] \.main-panel \{/);
});

test("meeting nav carries the horizontal note glyph and no square-grid glyph remains", () => {
  const nav = html.slice(html.indexOf('id="meetingNavButton"'), html.indexOf("</button>", html.indexOf('id="meetingNavButton"')));
  assert.match(nav, /class="side-icon" aria-hidden="true">▥/);
  assert.equal((html.match(/▦/g) || []).length, 0);
});

test("a visitor may open the meeting page while the session guard stays on the controls", () => {
  // The entry is no longer inert: the owner decision is that every screen is
  // browsable without a session, so the guard moved from the nav to the actions.
  assert.doesNotMatch(capture, /trigger\.disabled/);
  assert.match(capture, /shell\.dataset\.state = "meeting";/);
  assert.match(capture, /if \(!signedIn\) say\("PADIEM 로그인 후 회의록을 이용할 수 있습니다\."\);/);
  assert.match(capture, /startButton\.disabled = state\.active \|\| state\.pending \|\| !signedIn/);
  assert.match(capture, /draftInClaw\.disabled = state\.active \|\| !text\.value\.trim\(\) \|\| !signedIn/);
  assert.match(capture, /driveText\.disabled = state\.active \|\| !text\.value\.trim\(\) \|\| !signedIn \|\| uploadInFlight/);
  assert.match(capture, /startButton\.disabled = !signedIn \|\| controller\.snapshot\(\)\.active/);
});
