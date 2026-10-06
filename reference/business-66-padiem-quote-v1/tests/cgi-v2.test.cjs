const assert = require("node:assert");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Renderer = require("../quote-template-renderer.js");
const CgiV2 = require("../cgi-template-v2.js");
const check = (condition, label) => assert.ok(condition, "contract failed: " + label);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, "contract failed: " + label);

const candidate = CgiV2.candidate();
check(candidate, "CGI candidate builds");
eq(candidate.id, "cgi-v2", "CGI template id is stable");
eq(candidate.approved, false, "CGI profile is not trusted before explicit approval");
eq(candidate.content.layoutVariant, "cgi-v2", "CGI layout variant is explicit");
eq(candidate.content.page, { size: "A4", margin: "12mm", orientation: "portrait" }, "CGI A4 page authority");
eq(candidate.content.items.columns.map((c) => c.width),
  ["5.3%", "23.9%", "18.6%", "5.7%", "5.7%", "15.4%", "17.1%", "8.4%"],
  "CGI measured eight-column widths");

eq(candidate.content.cgiV2.bank, "", "CGI source profile contains no payment account");
eq(candidate.content.cgiV2.fax, "", "CGI source profile contains no customer-private fax");

const approved = CgiV2.approvedProfile({
  approvedBy: "operator:central",
  approvedAt: "2026-10-06T00:00:00.000Z",
  approvalRef: "issue-3521",
  privatePresentation: {
    bank: "테스트은행 000-000 테스트계정",
    fax: "FAX : 000-000-0000"
  }
});
check(approved && approved.approved === true, "CGI explicit approval activates profile");
eq(approved.approvalBasis, "explicit_approval", "CGI has no built-in trust exception");
eq(Template.isApprovedProfile(approved), true, "CGI approved profile satisfies template authority");

const draft = Core.normalizeDraft({
  schemaVersion: 1,
  meta: { quoteNo:"CGI-TEST-001", issueDate:"2026-10-06", validDays:14, source:"manual", projectName:"배관 교체 공사" },
  sender: { company:"(주)시지아이", rep:"김범신", contactPerson:"김범신", bizNo:"410-86-46283", address:"광주광역시", phone:"062-576-8100", email:"", presetId:"cgi-test" },
  recipient: { company:"대한건설", person:"구매담당", address:"", email:"" },
  items: [{ id:"item-1", name:"배관", spec:"", unit:"미터", qty:100, unitPrice:18000 }],
  tax: { mode:"EXCLUSIVE", rate:0.1 },
  memo:""
});
const model = Renderer.buildRenderModel(draft, approved, { taxReviewRequired:false });
check(model, "CGI render model builds");
eq(model.layoutVariant, "cgi-v2", "CGI reaches dedicated renderer path");
eq(model.facts.sender.company, "(주)시지아이", "company remains QuoteDraft authority");
eq(model.facts.recipient.company, "대한건설", "recipient remains QuoteDraft authority");
eq(model.facts.meta.validDays, 14, "validity remains QuoteDraft authority");
eq(model.styleVariables["--quote-page-margin"], "12mm", "screen margin uses CGI page authority");
eq(model.pageRule, "@page { size: A4; margin: 12mm; }", "PDF margin uses same page authority");
const totals = Core.computeDraftTotals(draft);
eq(model.totals.subtotalText, Core.formatMoney(totals.supply), "CGI supply is QuoteCore-authoritative");
eq(model.totals.vatText, Core.formatMoney(totals.vat), "CGI VAT is QuoteCore-authoritative");
eq(model.totals.grandText, Core.formatMoney(totals.grand), "CGI total is QuoteCore-authoritative");
eq(model.totals.grandText, "₩1,980,000", "CGI smoke total is exact");

const invalidTerms = CgiV2.content(); invalidTerms.cgiV2.terms = "not-an-array";
eq(Template.normalizeTemplateContent(invalidTerms), null, "malformed CGI terms fail closed");
const invalidRows = CgiV2.content(); invalidRows.cgiV2.underfillAfterRows = 999;
eq(Template.normalizeTemplateContent(invalidRows), null, "unbounded CGI rows fail closed");
const stray = JSON.parse(JSON.stringify(Template.builtInTemplate().content));
stray.cgiV2 = CgiV2.content().cgiV2;
eq(Template.normalizeTemplateContent(stray), null, "non-CGI template cannot smuggle CGI metadata");

console.log("B66_CGI_V2_TEMPLATE=PASS");
console.log("B66_CGI_V2_EXPLICIT_APPROVAL=PASS");
console.log("B66_CGI_V2_QUOTECORE_AUTHORITY=PASS");
console.log("B66_CGI_V2_PAGE_AUTHORITY=PASS");
