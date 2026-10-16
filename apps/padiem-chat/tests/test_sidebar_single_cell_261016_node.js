"use strict";
// Source integration contract: guards against returning to detached cells or
// accidentally breaking the existing server-backed #4471 search controller.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.resolve(__dirname, "../static");
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const html = read("index.html"), css = read("sidebar-unified.css");
const app = read("app.js"), search = read("conversation-search.js");

test("one visual New Chat + Search row with two independent buttons", () => {
  const start = html.indexOf('class="sidebar-actions-row sidebar-unified-row"');
  const end = html.indexOf("</div>", start);
  assert.ok(start > 0 && end > start);
  const region = html.slice(start, end);
  assert.equal((region.match(/<button\b/g) || []).length, 2);
  assert.ok(region.indexOf('id="newChatButton"') < region.indexOf('id="sidebarSearchButton"'));
  assert.match(region, /id="sidebarSearchButton"/);
  assert.match(region, /class="visually-hidden" data-locale-key="search"/);
  assert.match(css, /sidebar-unified-row\s*\{[\s\S]*?gap:\s*0/);
  assert.match(css, /\.sidebar-actions-row\.sidebar-unified-row > \.sidebar-search-item\s*\{/);
});

test("search remains the existing credential-free server-backed conversation search", () => {
  assert.match(search, /const SEARCH_ENDPOINT = "\/api\/conversations\/search"/);
  assert.match(search, /getElementById\("sidebarSearchButton"\)/);
  assert.match(search, /sidebarSearchButton\.addEventListener\("click"/);
  assert.match(search, /auth\.historyReady === true/);
  assert.match(search, /openHit\(conversation\.id\)/);
});

test("project and recent history keep distinct accessible primary and secondary actions", () => {
  assert.match(app, /row\.className = "project-row"/);
  assert.match(app, /button\.className = "recent-item project-item"/);
  assert.match(app, /manage\.className = "project-manage"/);
  assert.match(app, /row\.append\(button, manage\)/);
  assert.match(app, /row\.className = "history-row"/);
  assert.match(app, /button\.className = "recent-item history-item"/);
  assert.match(app, /actions\.className = "history-actions"/);
  assert.match(app, /more\.className = "history-more"/);
  assert.match(app, /row\.append\(button, actions\)/);
  assert.match(css, /\.project-row, \.history-row\)/);
  assert.match(css, /background: transparent !important/);
});

test("single shared row styles and label baselines override prior frame styles last", () => {
  assert.ok(html.indexOf('src="./conversation-search.js"') >= 0);
  assert.ok(html.indexOf('href="./sidebar-unified.css"') > html.indexOf('href="./shared-six-panel-frame.css"'));
  assert.match(css, /#projectsSection \.section-heading-row/);
  assert.match(css, /#historySection > h2/);
  assert.match(css, /#projectsSection \.section-heading-row h2 \{ margin: 0; \}/);
  assert.doesNotMatch(css, /#workspaceNav|calendarNavButton|connectorsNavButton/);
});
