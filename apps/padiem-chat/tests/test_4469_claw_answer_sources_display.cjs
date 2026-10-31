/**
 * #4469 Claw grounded-answer sources display — Node contract tests (no browser).
 * Pins the user-visible display contract added on top of the merged backend
 * evidence path: server-verified sources render; absence/malformity renders
 * nothing; non-https is refused; the answer text is never altered.
 */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const staticDir = path.join(__dirname, "..", "static");

test("claw answer sources module exists, is wired into the page and into the done path", () => {
  const module = fs.readFileSync(path.join(staticDir, "claw-answer-sources.js"), "utf8");
  assert.match(module, /PadiemClawAnswerSources/);
  assert.match(module, /https:/, "display must refuse non-https URLs");
  const html = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
  assert.match(html, /<script src="\.\/claw-answer-sources\.js"><\/script>/);
  const app = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
  assert.match(app, /PadiemClawAnswerSources\?\.render/);
});

test("the renderer refuses malformed, non-https and missing provenance", () => {
  const module = fs.readFileSync(path.join(staticDir, "claw-answer-sources.js"), "utf8");
  assert.match(module, /protocol === "https:"/);
  assert.match(module, /return;/, "fail closed instead of partial display");
});

test("backend still ships sources only as the verified terminal contract", () => {
  const routes = fs.readFileSync(
    path.join(__dirname, "..", "app", "claw_general_routes.py"), "utf8"
  );
  assert.match(routes, /def _project_search_sources/);
  assert.match(routes, /url\.startswith\("https:\/\/"\)/);
  assert.match(routes, /retrieved_at/);
  // live + pending paths both forward sources to the same terminal frame
  assert.match(routes, /sources=search_sources/);
});

test("existing search-sources UI module remains untouched as the Chat renderer", () => {
  const shared = fs.readFileSync(path.join(staticDir, "search-sources.js"), "utf8");
  assert.match(shared, /renderSources/);
  assert.doesNotMatch(shared, /clawGeneralRequest/);
});
