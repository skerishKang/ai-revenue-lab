const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Renderer = require("../quote-template-renderer.js");
const Skill = require("../quote-skill.js");
const Bridge = require("../quote-embed-bridge.js");

const NOW = "2026-10-01T05:00:00.000Z";

function approvedSkill() {
  const base = {
    id: "skill-embed-test",
    name: "우리 견적서",
    fixedDefaults: {
      sender: {
        company: "한빛설비",
        rep: "김대표",
        bizNo: "123-45-67890",
        address: "광주광역시",
        phone: "062-000-0000",
        email: "quote@example.com",
        presetId: "saved-skill"
      },
      validDays: 30,
      taxMode: "EXCLUSIVE",
      memo: "발주 후 일정 협의"
    },
    variableSchema: {
      recipient: true,
      quoteNo: true,
      issueDate: true,
      items: true,
      memo: true,
      taxMode: true
    },
    internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
    provenance: {
      sourceKind: "manual",
      sourceName: "",
      sourceRef: "manual:operator",
      capturedAt: NOW,
      warnings: [],
      unknowns: [],
      evidence: []
    },
    approval: null,
    createdAt: NOW,
    updatedAt: NOW
  };
  const candidate = Skill.buildSkill(base);
  assert.ok(candidate && candidate.approved === false);
  const approved = Skill.buildSkill(Object.assign({}, base, {
    approval: {
      schemaVersion: 1,
      status: "approved",
      skillFingerprint: candidate.fingerprint,
      approvedBy: "central-cto",
      approvedAt: NOW,
      approvalRef: "issue-3310"
    }
  }));
  assert.ok(approved && approved.approved === true);
  return approved;
}

function fakeDocument() {
  const ids = [
    "pvTitle", "pvQuoteNo", "pvDate", "pvValidity", "pvValidUntil", "pvTaxMode",
    "pvSenderHeading", "pvSenderCompany", "pvSenderRep", "pvSenderBizNo",
    "pvSenderAddress", "pvSenderContact", "pvRecipientHeading",
    "pvRecipientCompany", "pvRecipientPerson", "pvRecipientAddress",
    "pvRecipientEmail", "pvItemsHead", "pvItems", "pvSubtotalLabel",
    "pvSubtotal", "pvVatLabel", "pvVat", "pvGrandLabel", "pvGrand",
    "pvMemo", "pvMark", "quotePaper", "embedStatus"
  ];
  const elements = new Map();
  for (const id of ids) {
    const vars = {};
    elements.set(id, {
      id,
      textContent: "",
      innerHTML: "",
      dataset: {},
      style: {
        setProperty(name, value) { vars[name] = value; },
        vars
      }
    });
  }
  const head = {
    children: [],
    appendChild(node) {
      this.children.push(node);
      if (node.id) elements.set(node.id, node);
      return node;
    }
  };
  return {
    head,
    elements,
    getElementById(id) { return elements.get(id) || null; },
    getElementsByTagName(name) { return name === "head" ? [head] : []; },
    createElement(tag) { return { tagName: tag.toUpperCase(), id: "", textContent: "" }; }
  };
}

const skill = approvedSkill();
const candidate = {
  recipient: { company: "ABC건설", person: null, address: null, email: null },
  quoteNo: null,
  issueDate: null,
  items: [{ name: "배관", qty: 20, unitPrice: 30000 }],
  memo: null,
  taxMode: null,
  missing: []
};

const normalized = Bridge.normalizeRenderMessage({
  type: Bridge.REQUEST_TYPE,
  requestId: "req-1",
  skill,
  candidate
});
assert.ok(normalized);
assert.equal(normalized.requestId, "req-1");

const defaults = Core.createDefaultDraft();
const input = Bridge.buildStructuredInput(candidate, Core);
assert.equal(input.quoteNo, defaults.meta.quoteNo);
assert.equal(input.issueDate, defaults.meta.issueDate);
assert.equal(input.recipient.company, "ABC건설");
assert.equal(input.items[0].qty, 20);
assert.equal(input.items[0].unitPrice, 30000);

const doc = fakeDocument();
const rendered = Bridge.renderRequest(
  {
    type: Bridge.REQUEST_TYPE,
    requestId: "req-1",
    skill,
    candidate
  },
  { Core, SavedSkill: Skill, Renderer },
  doc
);
assert.equal(rendered.ok, true);
assert.equal(rendered.printReady, true);
assert.equal(rendered.quoteNo, defaults.meta.quoteNo);
assert.equal(rendered.issueDate, defaults.meta.issueDate);
assert.equal(doc.getElementById("pvSenderCompany").textContent, "한빛설비");
assert.equal(doc.getElementById("pvRecipientCompany").textContent, "ABC건설");
assert.match(doc.getElementById("pvItems").innerHTML, /배관/);
assert.notEqual(doc.getElementById("pvSubtotal").textContent, "");
assert.notEqual(doc.getElementById("pvGrand").textContent, "");
assert.ok(doc.getElementById("quotePaper").style.vars["--quote-accent"]);

const response = Bridge.publicResponse(rendered, "req-1");
assert.deepEqual(Object.keys(response).sort(), [
  "code", "issueDate", "missing", "ok", "printReady", "quoteNo", "requestId", "type"
].sort());
assert.ok(!("totals" in response));
assert.ok(!("skill" in response));
assert.ok(!("renderModel" in response));

const unapproved = JSON.parse(JSON.stringify(skill));
unapproved.approval = null;
const denied = Bridge.renderRequest(
  {
    type: Bridge.REQUEST_TYPE,
    requestId: "req-denied",
    skill: unapproved,
    candidate
  },
  { Core, SavedSkill: Skill, Renderer },
  fakeDocument()
);
assert.equal(denied.ok, false);
assert.equal(denied.code, "skill_not_approved");

assert.equal(Bridge.normalizeRenderMessage({
  type: Bridge.REQUEST_TYPE,
  requestId: "req-bad",
  skill,
  candidate,
  tenant_id: "tenant_evil"
}), null);

const source = fs.readFileSync(path.join(__dirname, "..", "quote-embed-bridge.js"), "utf8");
const boot = fs.readFileSync(path.join(__dirname, "..", "quote-embed-browser.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "..", "embed.html"), "utf8");
const allEmbedSource = source + "\n" + boot + "\n" + html;

for (const forbidden of [
  "localStorage", "sessionStorage", "indexedDB", "FileReader", "FormData",
  "XMLHttpRequest", "WebSocket", "navigator.sendBeacon"
]) {
  assert.ok(!allEmbedSource.includes(forbidden), "forbidden embed capability: " + forbidden);
}
assert.ok(!/\bfetch\s*\(/.test(allEmbedSource), "embed performs no fetch");
assert.match(html, /connect-src 'none'/);
assert.match(html, /quote-core\.js/);
assert.match(html, /quote-template\.js/);
assert.match(html, /quote-template-renderer\.js/);
assert.match(html, /quote-skill\.js/);
assert.ok(!html.includes("app.js"));
assert.ok(!html.includes("easy-mode.js"));
assert.ok(!html.includes("file-intake.js"));
assert.ok(!html.includes("quote-skill-store.js"));

console.log("B66_CANONICAL_EMBED_BRIDGE=PASS");
console.log("DUPLICATED_QUOTECORE=0");
console.log("DUPLICATED_RENDERER=0");
console.log("NETWORK_CALLS_FROM_EMBED=0");
console.log("LOCAL_STORAGE_CALLS=0");
console.log("SOURCE_DOCUMENT_PARSE_CALLS=0");
console.log("QUOTE_NO_BROWSER_DEFAULT=YES");
console.log("ISSUE_DATE_BROWSER_DEFAULT=YES");
