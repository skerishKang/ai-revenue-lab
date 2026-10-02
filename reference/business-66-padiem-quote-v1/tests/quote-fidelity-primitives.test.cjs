const assert = require("node:assert");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Renderer = require("../quote-template-renderer.js");

const NOW = "2026-10-02T05:10:00.000Z";
const clone = (v) => JSON.parse(JSON.stringify(v));

function approvedProfile(id, content) {
  const draft = Template.buildProfile({
    id, name: "real-company fidelity", builtin: false, isDefault: false,
    approval: null, createdAt: NOW, updatedAt: NOW, content
  });
  assert.ok(draft && draft.approved === false);
  return Template.buildProfile({
    id, name: "real-company fidelity", builtin: false, isDefault: false,
    approval: {
      schemaVersion: 1,
      status: "approved",
      contentFingerprint: draft.fingerprint,
      approvedBy: "central-cto",
      approvedAt: NOW,
      approvalRef: "issue-3411"
    },
    createdAt: NOW, updatedAt: NOW, content
  });
}

const legacy = Template.normalizeTemplateContent(clone(Template.builtInTemplate().content));
assert.ok(legacy, "legacy four-column template still normalizes");
assert.deepEqual(
  legacy.items.columns.map((x) => x.key),
  ["name", "qty", "unitPrice", "amount"],
  "legacy column shape is byte-semantically preserved"
);

const content = clone(Template.builtInTemplate().content);
content.layoutVersion = 2;
content.meta.projectNamePrefix = "건명 : ";
content.items.columns = [
  { key: "sequence", label: "NO", width: "6%", align: "center" },
  { key: "name", label: "품명", width: "24%", align: "left" },
  { key: "specification", label: "규격", width: "18%", align: "left" },
  { key: "unit", label: "단위", width: "8%", align: "center" },
  { key: "qty", label: "수량", width: "8%", align: "right" },
  { key: "unitPrice", label: "단가", width: "12%", align: "right" },
  { key: "amount", label: "금액", width: "16%", align: "right" },
  { key: "rowNote", label: "비고", width: "8%", align: "left" }
];
content.totals.showWrittenGrand = true;
content.totals.writtenGrandPrefix = "일금 ";

const normalizedContent = Template.normalizeTemplateContent(content);
assert.ok(normalizedContent, "eight-column real-company template normalizes");
assert.equal(normalizedContent.meta.projectNamePrefix, "건명 : ");
assert.equal(normalizedContent.totals.showWrittenGrand, true);
assert.equal(normalizedContent.totals.writtenGrandPrefix, "일금 ");
assert.equal(normalizedContent.items.columns.length, 8);

const missingRequired = clone(content);
missingRequired.items.columns = missingRequired.items.columns.filter((x) => x.key !== "amount");
assert.equal(Template.normalizeTemplateContent(missingRequired), null, "amount column stays required");

const profile = approvedProfile("tpl-fidelity-3411", normalizedContent);
assert.ok(profile.approved === true);

const draft = Core.normalizeDraft({
  ...Core.createDefaultDraft(),
  meta: {
    ...Core.createDefaultDraft().meta,
    quoteNo: "CGI-TEST-001",
    issueDate: "2026-10-02",
    projectName: "스마트팜 환경제어 구축"
  },
  recipient: { company: "테스트 거래처", person: "담당자", address: "", email: "" },
  items: [{
    id: "item-1",
    sequence: "1",
    name: "환경제어 장치",
    specification: "CGI-X1",
    unit: "SET",
    qty: 2,
    unitPrice: 500000,
    rowNote: "설치 포함"
  }],
  tax: { mode: "EXCLUSIVE", rate: 0.10 }
});
assert.ok(draft);

const totals = Core.computeTotals(draft.items, draft.tax.mode);
const model = Renderer.buildRenderModel(draft, profile, { taxReviewRequired: false });
assert.ok(model);
assert.equal(model.meta.projectNameText, "건명 : 스마트팜 환경제어 구축");
assert.deepEqual(model.columns.map((x) => x.key), [
  "sequence", "name", "specification", "unit", "qty", "unitPrice", "amount", "rowNote"
]);
assert.equal(model.items[0].values.sequence, "1");
assert.equal(model.items[0].values.specification, "CGI-X1");
assert.equal(model.items[0].values.unit, "SET");
assert.equal(model.items[0].values.rowNote, "설치 포함");
assert.equal(model.totals.grandText, Core.formatMoney(totals.grand));
assert.equal(
  model.totals.writtenGrandText,
  "일금 " + Core.formatKoreanMoneyWords(totals.grand),
  "written total is presentation derived from canonical QuoteCore grand"
);

const provisional = Renderer.buildRenderModel(draft, profile, { taxReviewRequired: true });
assert.equal(provisional.totals.writtenGrandText, "", "unconfirmed tax never shows written final total");

const after = Core.computeTotals(draft.items, draft.tax.mode);
assert.deepEqual(after, totals, "template fidelity fields never change QuoteCore totals");

console.log("LEGACY_4_COLUMN_TEMPLATE_COMPAT=PASS");
console.log("REAL_COMPANY_8_COLUMN_TEMPLATE=PASS");
console.log("PROJECT_NAME_PRESENTATION=PASS");
console.log("KOREAN_WRITTEN_TOTAL_FROM_CANONICAL_GRAND=PASS");
console.log("TEMPLATE_CALCULATION_AUTHORITY=0");
console.log("QUOTECORE_AUTHORITY=YES");
