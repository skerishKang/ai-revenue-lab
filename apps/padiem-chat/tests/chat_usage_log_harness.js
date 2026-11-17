// #7718 usage log DOM harness — test-only fixture, no browser/network/production data.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const staticDir = process.argv[2];
const scenario = process.argv[3];

const FIXTURE = {
  metrics: [
    { key: "active", label: "활동 명예회원", value: 3 },
    { key: "left", label: "떠난 명예회원", value: 1 },
    { key: "new", label: "새 의견", value: 7 },
    { key: "resolved", label: "고침", value: 5 },
    { key: "return", label: "평균 다시 올 점수", value: "3.4" },
  ],
  rows: [
    { persona: "AI 정호", grade: "Plus", entries: [
      { round: 1, at: "2026.11.10", summary: "견적서 초안", score: 2 },
      { round: 2, at: "2026.11.12", summary: "회의정리", score: 3 },
      { round: 3, at: "2026.11.15", summary: "축사 다듬기", score: 4 },
    ] },
    { persona: "AI 민지", grade: "Free", entries: [
      { round: 1, at: "2026.11.11", summary: "PDF→Markdown", score: 3 },
      { round: 2, at: "2026.11.14", summary: "새 소식 확인", score: 4 },
    ] },
    { persona: "AI 수현", grade: "Pro", entries: [
      { round: 1, at: "2026.11.09", summary: "SNS 홍보", score: 4 },
      { round: 2, at: "2026.11.13", summary: "견적서 초안", score: 3 },
    ] },
  ],
};

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
const source = fs.readFileSync(path.join(staticDir, "chat-usage-log-module.js"), "utf8");
vm.runInContext(source, context, { filename: "chat-usage-log-module.js" });

const usage = context.window.PadiemUsageLog;
function fail(label) { console.error("FAIL " + label); process.exit(1); }

if (scenario === "default_is_empty") {
  usage.render();
  if (!empty.text().includes("사용 기록이 아직 없습니다")) fail("empty message");
  if (empty.hidden) fail("empty visible");
  if (!list.hidden) fail("list hidden");
  if (list.children.length) fail("no rows");
  if (metricHost.text().includes("3.4")) fail("no fixture metric");
  if (!metricHost.text().includes("—")) fail("metric placeholder");
  for (const name of ["AI 정호", "AI 민지", "AI 수현"]) {
    if (source.includes(name)) fail("production JS carries fixture name " + name);
  }
  if (source.includes("견적서 초안") || source.includes("3.4")) fail("production JS carries fixture value");
} else if (scenario === "fixture_injected") {
  usage.render(FIXTURE.rows, FIXTURE.metrics);
  if (metricHost.children.length !== 5) fail("metrics count");
  if (list.children.length !== 3) fail("persona count");
  if (!empty.hidden) fail("empty hidden with fixture");
  if (list.hidden) fail("list visible with fixture");
  const all = list.text();
  if (!all.includes("예쁜가")) fail("pretty score label");
  if (!all.includes("↑") || !all.includes("→") || !all.includes("↓")) fail("trend arrows");
  if (!all.includes("AI 정호")) fail("persona name");
} else {
  fail("unknown scenario " + scenario);
}
console.log(JSON.stringify({ passed: scenario }));
