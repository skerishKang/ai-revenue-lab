// #7718 usage log DOM harness — no browser, no network, no production data.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const staticDir = process.argv[2];
const scenario = process.argv[3];

class Node {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.className = "";
    this.textContent = "";
    this.hidden = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); return node; }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  addEventListener() {}
  querySelector(selector) {
    return this.children.find((child) => child.className.split(/\s+/).includes(selector.slice(1))) || null;
  }
  text() {
    if (this.children.length) return this.children.map((child) => child.text()).join(" ");
    return this.textContent;
  }
}

const metricHost = new Node("div"); metricHost.className = "usage-metrics";
const list = new Node("ol"); list.className = "usage-list"; list.hidden = true;
const empty = new Node("p"); empty.className = "usage-empty"; empty.hidden = true;
const panel = new Node("section"); panel.children.push(metricHost, list, empty);
const tab = new Node("button");
const document = {
  getElementById(id) {
    if (id === "feedbackUsagePanel") return panel;
    if (id === "feedbackUsageTab") return tab;
    return null;
  },
  createElement(tag) { return new Node(tag); },
};

const context = { document, window: {}, console };
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(staticDir, "chat-usage-log-module.js"), "utf8"), context,
  { filename: "chat-usage-log-module.js" });

const usage = context.window.PadiemUsageLog;
function fail(label) { console.error("FAIL " + label); process.exit(1); }

if (scenario === "fixture") {
  usage.render();
  if (metricHost.children.length !== 5) fail("metrics count");
  if (list.children.length !== 3) fail("persona count");
  if (!empty.hidden) fail("empty hidden with fixture");
  if (list.hidden) fail("list visible with fixture");
  const all = list.text();
  if (!all.includes("예쁜가")) fail("pretty score label");
  if (!all.includes("↑") || !all.includes("→")) fail("trend arrows");
  if (!all.includes("AI 정호")) fail("persona name");
} else if (scenario === "empty") {
  usage.render([], []);
  if (!list.hidden) fail("list hidden when empty");
  if (empty.hidden) fail("empty shown when no rows");
  if (!empty.text().includes("사용 기록이 아직 없습니다")) fail("empty message");
} else if (scenario === "admin_tab") {
  const source = fs.readFileSync(path.join(staticDir, "chat-feedback-module.js"), "utf8");
  if (!source.includes('usageTab: "feedbackUsageTab"')) fail("usage tab node missing");
  if (!source.includes('nodes.usageTab.hidden = !adminView')) fail("admin-only tab missing");
  if (!source.includes('"compose", "own", "admin", "usage"')) fail("view loop missing");
} else {
  fail("unknown scenario " + scenario);
}
console.log(JSON.stringify({ passed: scenario }));
