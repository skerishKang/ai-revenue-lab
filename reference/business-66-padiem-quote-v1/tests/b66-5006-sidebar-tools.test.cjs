"use strict";
// #5006: CGI sidebar AI work tools and connection management.
//
// 1. The existing quote menus stay exactly where they are; the new sections
//    are appended after them in the rail's remaining space.
// 2. AI work tools are entry points into the product that already owns those
//    views. B66 never reads that product's files, schedules or conversations,
//    and the link opens a new tab so the in-progress quote is untouched.
// 3. Drive status reuses the mounted Drive surface's own verdict; PC status
//    reuses the existing #4434 device directory read. Neither is re-derived,
//    and neither may claim a connection the server has not confirmed.
// 4. A missing grant, a signed-out session and a failed read each report
//    their own distinct state instead of one generic failure.
// 5. Mobile keeps the existing drawer behaviour; no always-visible button is
//    added outside the rail.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const srcDir = path.join(__dirname, "..");
const shell = fs.readFileSync(path.join(srcDir, "shell-layout.js"), "utf8");
const worker = fs.readFileSync(path.join(srcDir, "_worker.js"), "utf8");
const styles = fs.readFileSync(path.join(srcDir, "styles.css"), "utf8");

/* 1. Existing quote menus are preserved ---------------------------------- */
for (const id of ["shellNewQuote", "shellManualQuote", "shellRecentQuote",
                   "shellPreviousAiDialogue", "shellPreviousGuidedDialogue"]) {
  assert.ok(shell.includes('"' + id + '"'), "existing quote menu must remain: " + id);
}
assert.ok(shell.indexOf("shellPreviousGuidedDialogue") < shell.indexOf("shellToolMeeting"),
  "the new sections must come after the existing quote menus");

/* 2. Work tools are links, not embedded data ---------------------------- */
assert.match(shell, /var CHAT_WORKSPACE_ORIGIN = "https:\/\/chat\.padiem\.net"/);
for (const id of ["shellToolMeeting", "shellToolAutomation", "shellToolLibrary",
                  "shellToolCalendar"]) {
  assert.ok(shell.includes('"' + id + '"'), "work tool entry must exist: " + id);
}
// They must navigate, never fetch another product's data.
assert.doesNotMatch(shell, /fetch\([^)]*meeting|fetch\([^)]*calendar|fetch\([^)]*automation/,
  "B66 must not read the other product's views");
// New tab keeps the in-progress quote and the other product's own session.
assert.match(shell, /window\.open\(href, "_blank", "noopener,noreferrer"\)/);
// Only the hash Chat actually supports is deep-linked.
assert.ok(shell.includes('hash: "#padiem-automation"'),
  "automation uses the hash Chat really supports");
assert.match(shell, /item\.setAttribute\("role", "link"\)/);
assert.match(shell, /item\.addEventListener\("keydown"/, "link must be keyboard operable");

/* 3. Connection management reuses the existing surfaces ----------------- */
assert.match(shell, /\/api\/padiem\/b66\/connect\/devices/,
  "PC status must reuse the #4434 device directory read");
assert.match(worker,
  /\["\/api\/padiem\/b66\/connect\/devices", \["GET", "\/api\/b66\/connect\/devices"\]\]/,
  "the relay must bound the existing read-only device path");
assert.doesNotMatch(worker, /connect\/devices.*"POST"/,
  "the PC status relay is read-only");
assert.match(shell, /B66QuoteDriveUiInstance/,
  "Drive status must reuse the mounted Drive surface");
assert.match(shell, /settingsDriveChoice/,
  "the Drive entry must open the existing Drive settings surface");
assert.doesNotMatch(shell, /async function refreshDriveStatus[\s\S]{0,400}fetch\(/,
  "Drive status must not re-fetch or re-derive the Drive session");

/* 4. Honest, distinct connection states --------------------------------- */
for (const state of ["signed-out", "not-enabled", "unavailable"]) {
  assert.ok(shell.includes('"' + state + '"'), "connection state must exist: " + state);
}
assert.match(shell, /response\.status === 403 \|\| response\.status === 404/,
  "an unprovisioned grant must be distinguished from an empty list");
assert.match(shell, /payload\.ownerScoped !== true/,
  "a non-owner-scoped envelope must never count as a read");
assert.match(shell, /device\.state === "CONNECTED"/,
  "only the canonical CONNECTED state may be described as connected");
// No optimistic wording anywhere.
assert.doesNotMatch(shell, /pcStatus\.textContent = "컴퓨터 연결됨"/,
  "status text must never be assigned without a verified read");
assert.match(styles, /\.shell-connection-status\[data-state="ready"\]/);

/* 5. Layout is unchanged -------------------------------------------------- */
assert.match(styles, /body\.rail-collapsed \.shell-rail \{ display: none; \}/,
  "the mobile drawer behaviour must stay");
assert.match(styles, /@media \(max-width: 900px\)/, "the narrow-shell reflow must stay");
assert.match(shell, /syncMobileDefault\(\);/,
  "the existing mobile default must still run");

console.log("B66_5006_SIDEBAR_WORKTOOLS_AND_CONNECTIONS=PASS");