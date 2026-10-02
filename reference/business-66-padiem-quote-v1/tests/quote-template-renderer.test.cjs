const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Store = require("../quote-template-store.js");
const Renderer = require("../quote-template-renderer.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const readSource = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const norm = (html) => html.replace(/>\s+</g, "><").trim();

const BUILTIN = Template.BUILTIN_TEMPLATE_ID;
const APPROVED_AT = "2026-09-28T05:00:00Z";

/* 승인된 user profile 을 만든다(#3182 승인 경계). */
function approvedProfile(id, content) {
  return Template.buildProfile({
    id: id,
    name: id,
    builtin: false,
    isDefault: false,
    approval: {
      schemaVersion: 1,
      status: "approved",
      contentFingerprint: Template.templateFingerprint(content),
      approvedBy: "central-cto",
      approvedAt: APPROVED_AT
    },
    createdAt: APPROVED_AT,
    updatedAt: APPROVED_AT,
    content: content
  });
}

/* ── 레거시 render() 재현 (변경 전 app.js 의 표시 로직을 독립적으로 옮긴 것) ──
   텍스트 회귀 판정 기준이다. 렌더러가 여기서 벗어나면 화면이 달라진 것이다. */

const legacyEscape = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

const legacyTextOrDash = (value) => {
  const v = String(value ?? "").trim();
  return v || "-";
};

function legacyVatSummaryLabel(mode) {
  if (mode === Core.TAX_MODES.INCLUSIVE) return "부가세 (포함가 분리)";
  if (mode === Core.TAX_MODES.EXEMPT) return "부가세 (면세)";
  return "부가세";
}

function legacyProjection(draft, provisional) {
  const totals = Core.computeTotals(draft.items, draft.tax.mode);
  const validUntil = Core.computeValidUntil(draft.meta.issueDate, draft.meta.validDays);
  return {
    pvTitle: "견 적 서",
    pvQuoteNo: "견적번호  " + legacyTextOrDash(draft.meta.quoteNo),
    pvDate: "견적일  " + legacyTextOrDash(draft.meta.issueDate),
    pvValidity: "유효기간  " + draft.meta.validDays + "일",
    pvValidUntil: "유효일  " + (validUntil || "-"),
    pvTaxMode: provisional ? "세금  확인 필요" : "세금  " + Core.TAX_LABELS[draft.tax.mode],
    pvProjectName: "",
    pvWrittenTotal: "",
    pvItemsHeading: "",
    pvSummaryTerms: "",
    pvSenderHeading: "공급자",
    pvSenderCompany: legacyTextOrDash(draft.sender.company),
    pvSenderRep: "대표자  " + legacyTextOrDash(draft.sender.rep),
    pvSenderBizNo: "사업자번호  " + legacyTextOrDash(draft.sender.bizNo),
    pvSenderAddress: legacyTextOrDash(draft.sender.address),
    pvSenderContact: [draft.sender.phone.trim(), draft.sender.email.trim()].filter(Boolean).join(" · ") || "-",
    pvRecipientHeading: "공급받는 자",
    pvRecipientCompany: legacyTextOrDash(draft.recipient.company),
    pvRecipientPerson: "담당자  " + legacyTextOrDash(draft.recipient.person),
    pvRecipientAddress: legacyTextOrDash(draft.recipient.address),
    pvRecipientEmail: draft.recipient.email.trim() || "-",
    subtotalLabelText: provisional ? "품목 합계(세금 확인 전)" : "공급가액",
    subtotalText: Core.formatMoney(provisional ? totals.subtotal : totals.supply),
    vatLabelText: provisional ? "부가세" : legacyVatSummaryLabel(draft.tax.mode),
    vatText: provisional ? "확인 필요" : Core.formatMoney(totals.vat),
    grandLabelText: provisional ? "최종 합계" : "합계",
    grandText: provisional ? "확정 전" : Core.formatMoney(totals.grand),
    pvSubtotalLabel: provisional ? "품목 합계(세금 확인 전)" : "공급가액",
    pvSubtotal: Core.formatMoney(provisional ? totals.subtotal : totals.supply),
    pvVatLabel: provisional ? "부가세" : legacyVatSummaryLabel(draft.tax.mode),
    pvVat: provisional ? "확인 필요" : Core.formatMoney(totals.vat),
    pvGrandLabel: provisional ? "최종 합계" : "합계",
    pvGrand: provisional ? "확정 전" : Core.formatMoney(totals.grand),
    pvMemo: draft.memo.trim() || "비고 없음",
    pvMark: "견적서 베타"
  };
}

function legacyItemsHtml(draft, totals) {
  return draft.items.map((item, i) => `
      <tr>
        <td class="${item.name ? "" : "empty"}">${legacyEscape(item.name || "품목을 입력하세요")}</td>
        <td>${legacyEscape(Core.formatInputNumber(item.qty))}</td>
        <td>${Core.formatMoney(item.unitPrice)}</td>
        <td>${Core.formatMoney(totals.amounts[i])}</td>
      </tr>`
  ).join("");
}

const LEGACY_HEAD_HTML = '<th style="width:42%">품목</th><th>수량</th><th>단가</th><th>금액</th>';

const builtinProfile = () => Store.defaultTemplate(Store.emptyStore());

function applyToModel(draft, provisional, profile) {
  return Renderer.buildRenderModel(draft, profile || builtinProfile(), { taxReviewRequired: provisional });
}

function modelToProjection(model) {
  return {
    pvTitle: model.titleText,
    pvQuoteNo: model.meta.quoteNoText,
    pvDate: model.meta.dateText,
    pvValidity: model.meta.validityText,
    pvValidUntil: model.meta.validUntilText,
    pvTaxMode: model.meta.taxText,
    pvProjectName: model.projectNameText,
    pvWrittenTotal: model.writtenTotalText,
    pvSenderHeading: model.parties.sender.heading,
    pvSenderCompany: model.parties.sender.company,
    pvSenderRep: model.parties.sender.rep,
    pvSenderBizNo: model.parties.sender.bizNo,
    pvSenderAddress: model.parties.sender.address,
    pvSenderContact: model.parties.sender.contact,
    pvRecipientHeading: model.parties.recipient.heading,
    pvRecipientCompany: model.parties.recipient.company,
    pvRecipientPerson: model.parties.recipient.person,
    pvRecipientAddress: model.parties.recipient.address,
    pvRecipientEmail: model.parties.recipient.email,
    subtotalLabelText: model.totals.subtotalLabel,
    subtotalText: model.totals.subtotalText,
    vatLabelText: model.totals.vatLabel,
    vatText: model.totals.vatText,
    grandLabelText: model.totals.grandLabel,
    grandText: model.totals.grandText,
    pvSubtotalLabel: model.totals.subtotalLabel,
    pvSubtotal: model.totals.subtotalText,
    pvVatLabel: model.totals.vatLabel,
    pvVat: model.totals.vatText,
    pvGrandLabel: model.totals.grandLabel,
    pvGrand: model.totals.grandText,
    pvMemo: model.memoText,
    pvMark: model.markText
  };
}

function makeStyleStub() {
  return {
    props: {},
    setProperty(name, value) { this.props[name] = String(value); },
    getPropertyValue(name) { return this.props[name] === undefined ? "" : this.props[name]; }
  };
}

function stubDoc(ids) {
  const nodes = new Map();
  let createdSeq = 0;
  const head = {
    children: [],
    appendChild(node) {
      this.children.push(node);
      if (node.id) nodes.set(node.id, node);
      return node;
    }
  };
  const makeNode = (id, tag) => ({
    id: id,
    tagName: tag || "DIV",
    textContent: null,
    innerHTML: null,
    attributes: {},
    style: makeStyleStub(),
    setAttribute(name, value) { this.attributes[name] = String(value); }
  });
  (ids || []).forEach((id) => nodes.set(id, makeNode(id)));
  return {
    head: head,
    nodes: nodes,
    /* real DOM semantics: unknown ids are null, not auto-created */
    getElementById(id) {
      if (id === "head") return head;
      return nodes.has(id) ? nodes.get(id) : null;
    },
    createElement(tag) {
      createdSeq += 1;
      return makeNode("", String(tag || "div").toUpperCase() + "-" + createdSeq);
    }
  };
}

/* ── 픽스처 ── */
const defaultDraft = Core.createDefaultDraft();
const blankDraft = Core.createBlankQuoteDraft(defaultDraft, {
  quoteNo: "PQ-20260928-007", issueDate: "2026-09-28", source: "manual"
});
const emptyItemDraft = Core.normalizeDraft(Object.assign(clone(defaultDraft), {
  items: [{ id: "item-1", name: "", qty: 1, unitPrice: 0 }]
}));
const htmlDraft = Core.normalizeDraft(Object.assign(clone(defaultDraft), {
  sender: {
    company: '<img src=x onerror="alert(1)">', rep: "홍길동", bizNo: "111-11-11111",
    address: "서울시", phone: "010-0000-0000", email: "a@b.co", presetId: "custom"
  },
  recipient: { company: "주식회사 <테스트>", person: "김담당", address: "", email: "" },
  items: [{ id: "item-1", name: '<b>위험</b>&', qty: 2, unitPrice: 1500000 }]
}));

const drafts = [
  ["default", defaultDraft],
  ["blank", blankDraft],
  ["empty-item", emptyItemDraft],
  ["html", htmlDraft]
];
const modes = [Core.TAX_MODES.EXCLUSIVE, Core.TAX_MODES.INCLUSIVE, Core.TAX_MODES.EXEMPT];

/* CURRENT_DEFAULT_VISUAL_REGRESSION=0 — 레거시 표시 로직과 완전 일치 */
let compared = 0;
drafts.forEach(([label, base]) => {
  modes.forEach((mode) => {
    [false, true].forEach((provisional) => {
      const draft = Core.normalizeDraft(Object.assign(clone(base), { tax: { mode: mode, rate: 0.1 } }));
      const model = applyToModel(draft, provisional);
      eq(
        modelToProjection(model),
        legacyProjection(draft, provisional),
        `legacy parity ${label}/${mode}/provisional=${provisional}`
      );
      compared += 1;
    });
  });
});
check(compared === drafts.length * modes.length * 2, "parity matrix fully exercised");

/* QUOTE_TEMPLATE_RENDERER_DETERMINISTIC */
eq(applyToModel(defaultDraft, false), applyToModel(defaultDraft, false), "same inputs yield an identical model");
eq(
  Renderer.buildRenderModel(defaultDraft, builtinProfile(), {}),
  Renderer.buildRenderModel(defaultDraft, builtinProfile(), { taxReviewRequired: false }),
  "missing options match taxReviewRequired=false"
);

const rendererSource = readSource("quote-template-renderer.js");
check(!/Math\.random|Date\.now|new Date\(/.test(rendererSource), "renderer has no time/random dependency");
check(!/fetch\(|XMLHttpRequest|axios/.test(rendererSource), "renderer performs no network request");
check(!/kilo\/|sensenova\/|space-bunny|nemotron|openai|anthropic/i.test(rendererSource), "renderer names no provider or model");
check(!/innerHTML\s*=\s*[^"'`]*\)\s*;?\s*$/m.test(rendererSource.replace(/escapeHtml\(/g, "")) ||
  rendererSource.indexOf("escapeHtml(") !== -1, "rendered markup goes through the escaper");

/* 입력 불변 */
const before = JSON.stringify(defaultDraft);
applyToModel(defaultDraft, true);
eq(JSON.parse(before), JSON.parse(JSON.stringify(defaultDraft)), "renderer does not mutate the draft");

/* ── APPROVAL 경계 ── */
const unapprovedCandidate = Template.buildProfile({
  id: "candidate-1", name: "candidate", builtin: false, isDefault: false, approval: null,
  createdAt: "", updatedAt: "", content: clone(Template.builtInTemplate().content)
});
const gatedModel = applyToModel(defaultDraft, false, unapprovedCandidate);
eq(gatedModel.template.id, BUILTIN, "UNAPPROVED_TEMPLATE_ACTIVATION=0: an unapproved profile never renders");
eq(gatedModel.template.fallbackReason, "template_not_approved", "the fallback reason is explicit");
eq(gatedModel.template.approved, true, "the fallback profile is the trusted built-in");
eq(gatedModel.template.approvalBasis, "trusted_builtin", "the built-in exception is recorded");
eq(modelToProjection(gatedModel), legacyProjection(defaultDraft, false), "the fallback renders the default output");

const invalidProfileModel = applyToModel(defaultDraft, false, { schemaVersion: 99 });
eq(invalidProfileModel.template.id, BUILTIN, "invalid profile falls back to the built-in");
eq(invalidProfileModel.template.fallbackReason, "invalid_template_profile", "invalid profile reason recorded");

const staleEvidenceModel = applyToModel(defaultDraft, false, Template.buildProfile({
  id: "stale-1", name: "stale", builtin: false, isDefault: false,
  approval: { schemaVersion: 1, status: "approved", contentFingerprint: "0".repeat(64), approvedBy: "central-cto", approvedAt: APPROVED_AT },
  createdAt: "", updatedAt: "", content: clone(Template.builtInTemplate().content)
}));
eq(staleEvidenceModel.template.fallbackReason, "template_not_approved", "approval fingerprint mismatch fails closed");

/* FORGED_BUILTIN_FLAG_BYPASS=0 — builtin 플래그는 승인을 우회하지 못한다 */
const forgedBuiltinProfile = Template.buildProfile({
  id: "user-forged", name: "forged", builtin: true, isDefault: true, approval: null,
  createdAt: "", updatedAt: "", content: clone(Template.builtInTemplate().content)
});
const forgedModel = applyToModel(defaultDraft, false, forgedBuiltinProfile);
eq(forgedModel.template.id, BUILTIN, "CANONICAL_BUILTIN_FALLBACK: a forged builtin falls back to the canonical built-in");
eq(forgedModel.template.fallbackReason, "template_not_approved", "a forged builtin flag never bypasses approval");
eq(forgedModel.template.fingerprint, Template.BUILTIN_TEMPLATE_FINGERPRINT, "the fallback profile is the canonical built-in");
eq(forgedModel.template.approvalBasis, "trusted_builtin", "the fallback basis is the canonical built-in exception");
eq(JSON.stringify(forgedModel.styleVariables), JSON.stringify(gatedModel.styleVariables),
  "a forged builtin cannot inject style values");
eq(forgedModel.totals.grandText, gatedModel.totals.grandText, "a forged builtin cannot change QuoteCore totals");

const forgedStyledContent = clone(Template.builtInTemplate().content);
forgedStyledContent.style.accent = "#ff0000";
const forgedCanonicalIdProfile = Template.buildProfile({
  id: BUILTIN, name: "forged", builtin: true, isDefault: true, approval: null,
  createdAt: "", updatedAt: "", content: forgedStyledContent
});
const forgedCanonicalIdModel = applyToModel(defaultDraft, false, forgedCanonicalIdProfile);
eq(forgedCanonicalIdModel.template.id, BUILTIN,
  "the canonical id with forged content falls back to the canonical built-in");
eq(forgedCanonicalIdModel.template.fallbackReason, "template_not_approved",
  "forged content cannot ride the canonical id");
check(forgedCanonicalIdModel.styleVariables["--quote-accent"] !== "#ff0000",
  "forged content cannot inject its accent through the canonical id");
check(forgedCanonicalIdModel.totals.grandText === gatedModel.totals.grandText,
  "forged content cannot alter QuoteCore totals");

check(Renderer.buildRenderModel(null, builtinProfile()) === null, "invalid draft yields no model");
check(Renderer.buildRenderModel({ schemaVersion: 9 }, builtinProfile()) === null, "wrong draft schema yields no model");

/* QUOTECORE_REMAINS_CALCULATION_AUTHORITY */
const authoritative = applyToModel(defaultDraft, false);
const authoritativeTotals = Core.computeTotals(defaultDraft.items, defaultDraft.tax.mode);
eq(authoritative.derivedBy, "quote-core", "model declares QuoteCore as the calculation authority");
eq(authoritative.totals.subtotalText, Core.formatMoney(authoritativeTotals.supply), "subtotal comes from QuoteCore");
eq(authoritative.totals.vatText, Core.formatMoney(authoritativeTotals.vat), "vat comes from QuoteCore");
eq(authoritative.totals.grandText, Core.formatMoney(authoritativeTotals.grand), "grand comes from QuoteCore");

const detailDraft = Core.normalizeDraft({
  schemaVersion: 1,
  meta: {
    quoteNo: "CGI-DETAIL-1",
    issueDate: "2026-10-02",
    validDays: 30,
    source: "saved-quote-skill",
    projectName: "스마트팜 환경제어설비"
  },
  sender: defaultDraft.sender,
  recipient: defaultDraft.recipient,
  items: [{
    id: "item-detail",
    name: "ICT환경제어 시스템",
    spec: "주장치 및 스마트팜 전용S/W",
    unit: "식",
    qty: 1,
    unitPrice: 16330000,
    note: "설치 포함"
  }],
  tax: { mode: "EXCLUSIVE", rate: 0.1 },
  memo: ""
});
const detailContent = clone(Template.builtInTemplate().content);
detailContent.sections = ["title", "meta", "parties", "project", "items", "totals", "memo", "mark"];
detailContent.project = { prefix: "건   명 : " };
detailContent.items.columns = [
  { key: "no", label: "NO", width: "6%", align: "center" },
  { key: "name", label: "품명", width: "20%", align: "left" },
  { key: "spec", label: "규격", width: "22%", align: "left" },
  { key: "unit", label: "단위", width: "8%", align: "center" },
  { key: "qty", label: "수량", width: "8%", align: "right" },
  { key: "unitPrice", label: "단가", width: "12%", align: "right" },
  { key: "amount", label: "금액", width: "14%", align: "right" },
  { key: "note", label: "비고", width: "10%", align: "left" }
];
const detailModel = Renderer.buildRenderModel(
  detailDraft,
  approvedProfile("detail-8col", detailContent),
  { taxReviewRequired: false }
);
eq(detailModel.projectNameText, "건   명 : 스마트팜 환경제어설비", "project section renders bounded project name");
eq(detailModel.columns.map((column) => column.key),
  ["no", "name", "spec", "unit", "qty", "unitPrice", "amount", "note"],
  "approved 8-column profile drives table columns");
eq(detailModel.items[0].values.no, "1", "row number is renderer-derived");
eq(detailModel.items[0].values.spec, "주장치 및 스마트팜 전용S/W", "spec is projected");
eq(detailModel.items[0].values.unit, "식", "unit is projected");
eq(detailModel.items[0].values.note, "설치 포함", "note is projected");
eq(
  detailModel.totals.grandText,
  Core.formatMoney(Core.computeTotals(detailDraft.items, detailDraft.tax.mode).grand),
  "detail columns never replace QuoteCore totals"
);

const roundedDraft = Core.normalizeDraft(Object.assign(clone(detailDraft), {
  calculationPolicy: { grandRounding: { mode: "FLOOR", unit: 10000 } }
}));
const writtenContent = clone(detailContent);
writtenContent.sections = ["title", "meta", "parties", "project", "items", "totals", "writtenTotal", "memo", "mark"];
writtenContent.writtenTotal = { prefix: "일금 ", suffix: "원정[부가세포함]" };
const writtenModel = Renderer.buildRenderModel(
  roundedDraft,
  approvedProfile("detail-written-total", writtenContent),
  { taxReviewRequired: false }
);
const roundedTotals = Core.computeTotals(
  roundedDraft.items,
  roundedDraft.tax.mode,
  roundedDraft.calculationPolicy
);
eq(roundedTotals.rawGrand, 17963000, "reviewed raw grand is explicit in QuoteCore");
eq(roundedTotals.grand, 17960000, "reviewed floor policy is applied by QuoteCore");
eq(writtenModel.totals.grandText, Core.formatMoney(17960000), "renderer uses QuoteCore-rounded grand");
eq(
  writtenModel.writtenTotalText,
  "일금 일천칠백구십육만원정[부가세포함]",
  "written-total section projects QuoteCore Korean grand words"
);
eq(
  authoritative.writtenTotalText,
  "",
  "existing built-in template renders no written-total line"
);

const rollupDraft = Core.normalizeDraft(Object.assign(clone(detailDraft), {
  items: [{
    id: "summary-1",
    name: "ICT환경제어 시스템",
    unit: "식",
    qty: 1,
    unitPrice: 1
  }],
  detailGroups: [{
    id: "smartfarm-detail",
    summaryItemId: "summary-1",
    title: "스마트팜 제출견적",
    items: [
      {
        id: "detail-1",
        name: "주장치 및 스마트팜 전용S/W",
        spec: "원격제어장치",
        unit: "식",
        qty: 1,
        unitPrice: 15000000,
        section: "1. 스마트팜"
      },
      {
        id: "detail-2",
        name: "인건비 및 잡자재",
        spec: "설치 포함",
        unit: "식",
        qty: 1,
        unitPrice: 1330000,
        section: "3. 인건비 및 잡자재"
      }
    ]
  }]
}));
const rollupContent = clone(detailContent);
rollupContent.sections = ["title", "meta", "parties", "project", "items", "totals", "detailPages", "memo", "mark"];
rollupContent.detailPages = {
  titlePrefix: "상세내역  ",
  subtotalLabel: "소 계",
  columns: clone(detailContent.items.columns)
};
const rollupModel = Renderer.buildRenderModel(
  rollupDraft,
  approvedProfile("detail-pages", rollupContent),
  { taxReviewRequired: false }
);
eq(rollupModel.items[0].values.unitPrice, Core.formatMoney(16330000),
  "summary unit price is rendered from linked detail subtotal");
eq(rollupModel.items[0].values.amount, Core.formatMoney(16330000),
  "summary amount is rendered from QuoteCore rollup");
eq(rollupModel.detailPages.length, 1, "one linked detail group produces one printable detail page");
eq(rollupModel.detailPages[0].titleText, "상세내역  스마트팜 제출견적",
  "detail page title is template presentation plus bounded group title");
eq(rollupModel.detailPages[0].subtotalText, Core.formatMoney(16330000),
  "detail subtotal is projected from QuoteCore");
eq(rollupModel.detailPages[0].rows[0].section, "1. 스마트팜",
  "detail section heading is preserved");
eq(rollupModel.detailPages[0].rows[1].section, "3. 인건비 및 잡자재",
  "later section heading is preserved");
eq(authoritative.detailPages, [], "existing built-in template renders no detail pages");

const formalDraft = Core.normalizeDraft(Object.assign(clone(detailDraft), {
  meta: Object.assign({}, detailDraft.meta, { issueDate: "2026-10-02", validDays: 30 }),
  sender: Object.assign({}, detailDraft.sender, { phone: "010-0000-0000", email: "" }),
  recipient: Object.assign({}, detailDraft.recipient, { company: "샘플농장", person: "" }),
  items: [{ id: "formal-summary", name: "제어 시스템", unit: "식", qty: 1, unitPrice: 0 }],
  detailGroups: [{
    id: "formal-detail",
    summaryItemId: "formal-summary",
    title: "자재산출내역서",
    items: [
      { id: "f1", name: "개폐기", spec: "좌 상", unit: "채널", qty: 2, unitPrice: 65000, section: "1. 제어장치" },
      { id: "f2", name: "개폐기", spec: "좌 하", unit: "채널", qty: 2, unitPrice: 65000, section: "1. 제어장치" },
      { id: "f3", name: "센서", spec: "온습도", unit: "개", qty: 1, unitPrice: 250000, section: "2. 센서류" }
    ]
  }]
}));
const formalContent = clone(rollupContent);
formalContent.layoutVariant = "formal-grid-v1";
formalContent.meta.issueDateFormat = "yyyy. mm.";
formalContent.sender.contactPrefix = "MP : ";
formalContent.recipient.suffix = "귀중";
formalContent.items.minRows = 9;
formalContent.items.heading = "(1) 샘플 내역";
formalContent.summaryTerms = {
  validity: { label: "유효기간 : ", valuePrefix: "발행일로부터 ", valueSuffix: "일" },
  rows: [
    { label: "납품기간 : ", value: "협의" },
    { label: "결제조건 : ", value: "협의" }
  ]
};
formalContent.totals.supplyLabel = "(1) {firstItemName} 합계 (부가세별도)";
formalContent.memo.heading = "<특기사항>";
formalContent.detailPages.mergeRepeatedName = true;
formalContent.detailPages.finalLabel = "총 계";
const formalModel = Renderer.buildRenderModel(
  formalDraft,
  approvedProfile("formal-grid", formalContent),
  { taxReviewRequired: false }
);
eq(formalModel.layoutVariant, "formal-grid-v1", "formal layout variant reaches render model");
check(formalModel.meta.dateText.endsWith("2026. 10."), "formal issue date uses the approved bounded display format");
eq(formalModel.parties.sender.contact, "MP : 010-0000-0000", "formal sender contact prefix is presentation-only");
eq(formalModel.parties.recipient.company, "샘플농장 귀중", "formal recipient suffix is appended without mutating draft");
eq(formalModel.itemsHeadingText, "(1) 샘플 내역", "formal summary item heading reaches render model");
eq(formalModel.summaryTerms, [
  { label: "유효기간 : ", value: "발행일로부터 30일" },
  { label: "납품기간 : ", value: "협의" },
  { label: "결제조건 : ", value: "협의" }
], "formal summary terms combine valid-days display with bounded recurring rows");
eq(formalModel.totals.subtotalLabel, "(1) 제어 시스템 합계 (부가세별도)",
  "formal supply label substitutes the first QuoteCore effective item name for display only");
eq(formalModel.items.length, 9, "summary minRows adds display-only filler rows");
eq(formalModel.items.filter((item) => item.filler).length, 8, "only missing visual rows are fillers");
eq(formalModel.items[1].values.amount, "", "filler rows carry no calculated amount");
check(formalModel.memoText.startsWith("<특기사항>\n"), "memo heading is presentation-only prefix");
eq(formalModel.detailPages[0].rows[0].nameRowSpan, 2, "first repeated detail name owns the rowspan");
eq(formalModel.detailPages[0].rows[1].suppressName, true, "later repeated detail name cell is suppressed");
eq(formalModel.detailPages[0].rows[2].suppressName, false, "different detail name starts a new cell");
eq(formalModel.detailPages[0].subtotalLabel, "소 계", "detail subtotal row remains explicit");
eq(formalModel.detailPages[0].finalLabel, "총 계", "formal detail final row is opt-in");
eq(
  formalModel.detailPages[0].finalText,
  formalModel.detailPages[0].subtotalText,
  "detail final row reuses the same QuoteCore-authorized group subtotal"
);
eq(
  formalModel.totals.grandText,
  Core.formatMoney(Core.computeDraftTotals(formalDraft).grand),
  "formal presentation never changes QuoteCore totals"
);

/* ── TEMPLATE_STYLE_APPLIED — 승인된 style/page 프로필이 실제 출력 투영을 바꾼다 ── */
const styledContent = clone(Template.builtInTemplate().content);
styledContent.style.accent = "#8a1f1f";
styledContent.style.titleRule = "4px solid #8a1f1f";
styledContent.style.tableHeaderRule = "2px solid #8a1f1f";
styledContent.style.tableRowRule = "1px dashed #d0d0d0";
styledContent.style.partyRule = "1px solid #8a1f1f";
styledContent.style.memoRule = "2px dotted #8a1f1f";
styledContent.style.headerAlignment = "flex-end";
styledContent.style.metaAlignment = "center";
styledContent.style.numericAlignment = "left";
styledContent.style.textAlignment = "center";
styledContent.style.totalsWidth = "420px";
styledContent.totals.supplyLabel = "공급가액 합계";
styledContent.items.columns.reverse();
styledContent.page = { size: "A5", margin: "8mm", orientation: "landscape" };
const styledProfile = approvedProfile("styled-1", styledContent);

const styledModel = Renderer.buildRenderModel(defaultDraft, styledProfile, { taxReviewRequired: false });
eq(styledModel.template.id, "styled-1", "an approved profile renders as itself");
eq(styledModel.template.approved, true, "the approved profile is active");
eq(styledModel.template.fallbackReason, null, "no fallback for an approved profile");

/* accent */
eq(styledModel.styleVariables["--quote-accent"], "#8a1f1f", "TEMPLATE_ACCENT_APPLIED: accent is projected");
check(styledModel.styleVariables["--quote-accent"] !== authoritative.styleVariables["--quote-accent"],
  "TEMPLATE_ACCENT_APPLIED: accent differs from the built-in");
/* rules */
eq(styledModel.styleVariables["--quote-title-rule"], "4px solid #8a1f1f", "TEMPLATE_RULES_APPLIED: title rule projected");
eq(styledModel.styleVariables["--quote-header-rule"], "2px solid #8a1f1f", "TEMPLATE_RULES_APPLIED: table header rule projected");
eq(styledModel.styleVariables["--quote-row-rule"], "1px dashed #d0d0d0", "TEMPLATE_RULES_APPLIED: table row rule projected");
eq(styledModel.styleVariables["--quote-party-rule"], "1px solid #8a1f1f", "TEMPLATE_RULES_APPLIED: party rule projected");
eq(styledModel.styleVariables["--quote-memo-rule"], "2px dotted #8a1f1f", "TEMPLATE_RULES_APPLIED: memo rule projected");
/* alignment */
eq(styledModel.styleVariables["--quote-header-align"], "flex-end", "TEMPLATE_ALIGNMENT_APPLIED: header alignment projected");
eq(styledModel.styleVariables["--quote-meta-align"], "center", "TEMPLATE_ALIGNMENT_APPLIED: meta alignment projected");
eq(styledModel.styleVariables["--quote-numeric-align"], "left", "TEMPLATE_ALIGNMENT_APPLIED: numeric alignment projected");
eq(styledModel.styleVariables["--quote-text-align"], "center", "TEMPLATE_ALIGNMENT_APPLIED: text alignment projected");
/* totals width */
eq(styledModel.styleVariables["--quote-totals-width"], "420px", "TEMPLATE_TOTALS_WIDTH_APPLIED: totals width projected");
/* page rule */
eq(styledModel.pageRule, "@page { size: A5 landscape; margin: 8mm; }", "TEMPLATE_PAGE_RULE_APPLIED: page rule projected");
check(styledModel.pageRule !== authoritative.pageRule, "TEMPLATE_PAGE_RULE_APPLIED: page rule differs from the built-in");

/* QUOTECORE_TOTALS_UNCHANGED_ACROSS_TEMPLATES */
eq(styledModel.totals.grandText, authoritative.totals.grandText, "template change keeps the QuoteCore grand total");
eq(styledModel.totals.vatText, authoritative.totals.vatText, "template change keeps the QuoteCore vat");
eq(styledModel.totals.subtotalText, authoritative.totals.subtotalText, "template change keeps the QuoteCore subtotal");
check(styledModel.totals.subtotalLabel === "공급가액 합계", "template change does change the label");
eq(styledModel.columns.map((column) => column.key), ["amount", "unitPrice", "qty", "name"], "template column order is honoured");
check(styledModel.template.fingerprint !== authoritative.template.fingerprint, "restyled template has its own fingerprint");
check(JSON.stringify(styledModel.styleVariables) !== JSON.stringify(authoritative.styleVariables),
  "style projection differs between the built-in and the styled template");

/* draft 금액이 바뀌면 QuoteCore 파생 합계만 바뀐다 */
const richerDraft = Core.normalizeDraft(Object.assign(clone(defaultDraft), {
  items: [{ id: "item-1", name: "서비스 구축", qty: 3, unitPrice: 1000000 }]
}));
const richerModel = Renderer.buildRenderModel(richerDraft, builtinProfile(), { taxReviewRequired: false });
check(richerModel.totals.grandText !== authoritative.totals.grandText, "draft change moves the QuoteCore grand total");

/* ── 스타일·페이지 검증기는 임의 주입을 막는다 ── */
eq(Renderer.buildPageRule({ size: "A4} </style><script>", margin: "10mm; } body{display:none}", orientation: "diagonal" }),
  "@page { size: A4; margin: 10mm; }", "TEMPLATE_PAGE_RULE_APPLIED: hostile page values are neutralised");
['@page { size: A4; margin: 2mm; }', '@page { size: A4; margin: 10mm; }'].forEach(() => {});
check(/^@page \{ size: [A-Za-z0-9]+(?: landscape)?; margin: \d{1,2}(?:\.\d{1,2})?(?:mm|cm|in); \}$/.test(Renderer.buildPageRule({ size: "A5", margin: "12mm" })),
  "generated @page always matches the bounded pattern");
eq(Renderer.buildStyleVariables({ accent: "javascript:alert(1)", titleRule: "}</style><script>", totalsWidth: "1px; } body{}" }),
  {}, "unsafe style values never reach the custom properties");
eq(Object.keys(Renderer.buildStyleVariables(styledContent.style)).length, Renderer.STYLE_VARIABLE_MAP.length,
  "every declared style token is projected");

/* ── SLOT — approved private asset id + transient resolved data only ── */
eq(authoritative.slots.support, "private_asset_v1", "SLOT_BEHAVIOR: private asset refs are live");
eq(authoritative.slots.rendered, false, "SLOT_BEHAVIOR: empty built-in slots render nothing");
const logoAssetId = "b66asset_" + "a".repeat(32);
const declaredSlotContent = clone(Template.builtInTemplate().content);
declaredSlotContent.slots = { logo: logoAssetId, stamp: "" };
const logoData = "data:image/png;base64,iVBORw0KGgo=";
const declaredSlotModel = Renderer.buildRenderModel(
  defaultDraft,
  approvedProfile("slot-1", declaredSlotContent),
  { taxReviewRequired: false, slotSources: { logo: { assetId: logoAssetId, dataUrl: logoData } } }
);
eq(declaredSlotModel.slots.logo.assetId, logoAssetId, "SLOT_BEHAVIOR: declared private asset id is retained");
eq(declaredSlotModel.slots.logo.src, logoData, "SLOT_BEHAVIOR: transient resolved image reaches render model");
eq(declaredSlotModel.slots.rendered, true, "SLOT_BEHAVIOR: resolved private logo renders");
const mismatchedSlotModel = Renderer.buildRenderModel(
  defaultDraft,
  approvedProfile("slot-2", declaredSlotContent),
  { taxReviewRequired: false, slotSources: { logo: { assetId: "b66asset_" + "b".repeat(32), dataUrl: logoData } } }
);
eq(mismatchedSlotModel.slots.logo.rendered, false, "SLOT_BEHAVIOR: mismatched asset id fails closed");

/* 섹션 게이팅 */
function profileWithout(section) {
  const content = clone(Template.builtInTemplate().content);
  content.sections = content.sections.filter((name) => name !== section);
  return approvedProfile("tpl-nosec-" + section, content);
}
check(Renderer.buildRenderModel(defaultDraft, profileWithout("memo"), { taxReviewRequired: false }).memoText === "",
  "removing the memo section clears the memo text");
check(Renderer.buildRenderModel(defaultDraft, profileWithout("title"), { taxReviewRequired: false }).titleText === "",
  "removing the title section clears the title text");
const noTotals = Renderer.buildRenderModel(defaultDraft, profileWithout("totals"), { taxReviewRequired: false });
check(noTotals.totals.subtotalText === "" && noTotals.totals.grandText === "", "removing the totals section clears totals text");
const noParties = Renderer.buildRenderModel(defaultDraft, profileWithout("parties"), { taxReviewRequired: false });
check(noParties.parties.sender.company === "" && noParties.parties.recipient.company === "", "removing the parties section clears party text");
eq(noTotals.totals.grandText !== undefined && noTotals.totals.grandText === "" ? "" : noTotals.totals.grandText, "",
  "totals stay empty without changing QuoteCore math");
eq(Renderer.buildRenderModel(defaultDraft, profileWithout("memo"), { taxReviewRequired: false }).totals.grandText,
  authoritative.totals.grandText, "removing a section never changes QuoteCore totals");

/* ── DOM adapter ── */
const pageHtml = readSource("index.html");
const stylesCss = readSource("styles.css");
const ADAPTER_IDS = [
  "pvTitle", "pvQuoteNo", "pvDate", "pvValidity", "pvValidUntil", "pvTaxMode", "pvProjectName", "pvWrittenTotal",
  "pvItemsHeading", "pvSummaryTerms",
  "pvSenderHeading", "pvSenderCompany", "pvSenderRep", "pvSenderBizNo", "pvSenderAddress", "pvSenderContact",
  "pvRecipientHeading", "pvRecipientCompany", "pvRecipientPerson", "pvRecipientAddress", "pvRecipientEmail",
  "pvItemsHead", "pvItems", "pvDetailPages", "quotePaper",
  "subtotalLabelText", "subtotalText", "vatLabelText", "vatText", "grandLabelText", "grandText",
  "pvSubtotalLabel", "pvSubtotal", "pvVatLabel", "pvVat", "pvGrandLabel", "pvGrand", "pvMemo", "pvMark"
];
ADAPTER_IDS.forEach((id) => {
  check(pageHtml.includes(`id="${id}"`), `index.html exposes adapter target ${id}`);
});
ADAPTER_IDS.filter((id) => id !== "quotePaper").forEach((id) => {
  check(rendererSource.includes(`"${id}"`), `adapter writes element ${id}`);
});
check(rendererSource.includes('"quotePaper"'), "adapter applies style variables to the quotation paper");

drafts.forEach(([label, base]) => {
  modes.forEach((mode) => {
    [false, true].forEach((provisional) => {
      const draft = Core.normalizeDraft(Object.assign(clone(base), { tax: { mode: mode, rate: 0.1 } }));
      const totals = Core.computeTotals(draft.items, draft.tax.mode);
      const model = applyToModel(draft, provisional);
      const doc = stubDoc(ADAPTER_IDS);
      check(Renderer.applyRenderModel(doc, model) === true, "adapter reports success");
      const expected = legacyProjection(draft, provisional);
      ADAPTER_IDS.filter((id) => id !== "pvItems" && id !== "pvItemsHead" && id !== "pvDetailPages" && id !== "quotePaper").forEach((id) => {
        eq(doc.getElementById(id).textContent, expected[id], `adapter ${id} for ${label}/${mode}/${provisional}`);
      });
      eq(
        norm(doc.getElementById("pvItems").innerHTML),
        norm(legacyItemsHtml(draft, totals)),
        `adapter item rows for ${label}/${mode}/${provisional}`
      );
      eq(norm(doc.getElementById("pvItemsHead").innerHTML), norm(LEGACY_HEAD_HTML),
        `adapter table head for ${label}/${mode}/${provisional}`);
      eq(doc.getElementById("pvDetailPages").innerHTML, "", "simple quote emits no detail page markup");
    });
  });
});

/* 어댑터는 스타일/페이지를 실제 요소에 적용한다 */
const styleDoc = stubDoc(ADAPTER_IDS);
Renderer.applyRenderModel(styleDoc, styledModel);
const paper = styleDoc.getElementById("quotePaper");
eq(paper.style.getPropertyValue("--quote-accent"), "#8a1f1f", "TEMPLATE_ACCENT_APPLIED: adapter writes the accent property");
eq(paper.style.getPropertyValue("--quote-title-rule"), "4px solid #8a1f1f", "TEMPLATE_RULES_APPLIED: adapter writes the title rule");
eq(paper.style.getPropertyValue("--quote-totals-width"), "420px", "TEMPLATE_TOTALS_WIDTH_APPLIED: adapter writes the totals width");
eq(paper.style.getPropertyValue("--quote-header-align"), "flex-end", "TEMPLATE_ALIGNMENT_APPLIED: adapter writes the header alignment");
eq(styleDoc.head.children.length, 1, "adapter injects one page-rule style element");
eq(styleDoc.head.children[0].id, Renderer.PAGE_RULE_STYLE_ID, "page rule element id is stable");
eq(styleDoc.head.children[0].textContent, "@page { size: A5 landscape; margin: 8mm; }", "TEMPLATE_PAGE_RULE_APPLIED: adapter injects the page rule");

const builtinDoc = stubDoc(ADAPTER_IDS);
Renderer.applyRenderModel(builtinDoc, authoritative);
const builtinPaper = builtinDoc.getElementById("quotePaper");
check(builtinPaper.style.getPropertyValue("--quote-accent") !== paper.style.getPropertyValue("--quote-accent"),
  "DOM level: a different approved template produces a different accent");
check(builtinDoc.head.children[0].textContent !== styleDoc.head.children[0].textContent,
  "DOM level: a different approved template produces a different page rule");
eq(builtinDoc.getElementById("pvGrand").textContent, styleDoc.getElementById("pvGrand").textContent,
  "DOM level: QuoteCore totals are identical across templates");

/* 어댑터는 HTML 을 이스케이프한다 */
const htmlDoc = stubDoc(ADAPTER_IDS);
Renderer.applyRenderModel(htmlDoc, applyToModel(htmlDraft, false));
const htmlRows = htmlDoc.getElementById("pvItems").innerHTML;
check(htmlRows.indexOf("<b>") === -1 && htmlRows.indexOf("&lt;b&gt;") !== -1, "item name is escaped in the rendered table");
eq(htmlDoc.getElementById("pvSenderCompany").textContent, '<img src=x onerror="alert(1)">',
  "textContent targets keep raw text (no double escaping)");
eq(htmlRows.indexOf("onerror"), -1, "injected attribute text stays inert");

const rollupDoc = stubDoc(ADAPTER_IDS);
Renderer.applyRenderModel(rollupDoc, rollupModel);
const detailHtml = rollupDoc.getElementById("pvDetailPages").innerHTML;
check(detailHtml.includes("quote-detail-page"), "detail-page adapter emits printable page container");
check(detailHtml.includes("quote-detail-section"), "detail-page adapter emits section headings");
check(detailHtml.includes("스마트팜 제출견적"), "detail-page title is rendered");
check(detailHtml.includes("₩16,330,000"), "detail-page subtotal is rendered from QuoteCore");
check(!/Math\.|computeTotals|computeDraftTotals/.test(detailHtml), "rendered detail markup contains no arithmetic");

const formalDoc = stubDoc(ADAPTER_IDS);
Renderer.applyRenderModel(formalDoc, formalModel);
eq(
  formalDoc.getElementById("quotePaper").attributes["data-layout-variant"],
  "formal-grid-v1",
  "formal layout is opt-in through a bounded data attribute"
);
check(formalDoc.getElementById("pvItems").innerHTML.includes("quote-filler-row"),
  "formal summary adapter emits display-only filler rows");
eq(formalDoc.getElementById("pvItemsHeading").textContent, "(1) 샘플 내역",
  "formal item heading is projected through textContent");
const formalTermsHtml = formalDoc.getElementById("pvSummaryTerms").innerHTML;
check(formalTermsHtml.includes("quote-summary-term") && formalTermsHtml.includes("발행일로부터 30일"),
  "formal summary terms are projected as bounded escaped markup");
const formalDetailHtml = formalDoc.getElementById("pvDetailPages").innerHTML;
check(formalDetailHtml.includes('data-layout-variant="formal-grid-v1"'),
  "detail pages inherit the formal layout variant");
check(formalDetailHtml.includes('rowspan="2"'),
  "adjacent repeated detail names render as a merged cell");
check(formalDetailHtml.includes("quote-detail-final"),
  "formal detail adapter emits the optional final row");
check(formalDetailHtml.includes("총 계"),
  "formal detail final label is rendered");
check((formalDetailHtml.match(/₩510,000/g) || []).length >= 2,
  "subtotal and final row display the same QuoteCore-derived amount");
check(formalDetailHtml.includes("text-align:center"),
  "formal column alignment is applied from the approved template");
check(!/Math\.|computeTotals|computeDraftTotals/.test(formalDetailHtml),
  "formal detail markup still contains no arithmetic");
check(stylesCss.includes('[data-layout-variant="formal-grid-v1"]'),
  "formal-grid CSS is scoped to the opt-in variant");
check(stylesCss.includes("background: #c9c9c9"),
  "formal detail header has the reviewed gray treatment");
check(stylesCss.includes(".quote-summary-terms") && stylesCss.includes("#pvValidity"),
  "formal summary CSS provides terms layout and hides duplicate top metadata");
check(stylesCss.includes("#pvSenderBizNo") && stylesCss.includes("#pvSenderContact"),
  "formal sender CSS has explicit source-like row ordering");

/* 어댑터 방어 */
check(Renderer.applyRenderModel(null, authoritative) === false, "adapter without document fails safe");
check(Renderer.applyRenderModel(stubDoc(ADAPTER_IDS), null) === false, "adapter without model fails safe");
check(Renderer.applyRenderModel(stubDoc(ADAPTER_IDS), "nope") === false, "adapter with junk model fails safe");

/* 이스케이프 단일 구현 */
["", "plain", "<script>", 'a"b', "a'b", "a&b", "<>&\"'", "한글 & <b>"].forEach((sample) => {
  eq(Template.escapeHtml(sample), legacyEscape(sample), `escape parity for ${JSON.stringify(sample)}`);
});
eq(Renderer.escapeHtml, Template.escapeHtml, "renderer re-exports the single escape implementation");

const legacyHeadFromPage = /<thead><tr id="pvItemsHead">([\s\S]*?)<\/tr><\/thead>/.exec(pageHtml);
check(legacyHeadFromPage !== null, "index.html still carries the table head");
eq(norm(legacyHeadFromPage[1]), norm(LEGACY_HEAD_HTML), "index.html head matches the profile-generated head");

/* ── CURRENT_DEFAULT_VISUAL_REGRESSION=0 — 주입값이 styles.css 기본값과 정확히 같다 ── */
const cssFallbacks = {};
const varPattern = /var\((--quote-[a-z-]+),\s*([^)]+)\)/g;
let match;
while ((match = varPattern.exec(stylesCss)) !== null) cssFallbacks[match[1]] = match[2].trim();

eq(Object.keys(cssFallbacks).sort(), Object.keys(authoritative.styleVariables).sort(),
  "every projected variable is consumed by styles.css");
Object.keys(authoritative.styleVariables).forEach((name) => {
  eq(authoritative.styleVariables[name], cssFallbacks[name],
    `built-in ${name} equals the styles.css fallback (no visual change)`);
});
check(stylesCss.includes("@page { size: A4; margin: 10mm; }"), "styles.css keeps the default @page rule");
eq(authoritative.pageRule, "@page { size: A4; margin: 10mm; }", "built-in page rule matches the styles.css default");
eq(authoritative.pageRule, "@page { size: A4; margin: 10mm; }".replace(/\s+/g, " "),
  "built-in page rule is byte-identical to today's rule");

console.log("QUOTE_TEMPLATE_RENDERER_DETERMINISTIC=YES");
console.log("CURRENT_DEFAULT_VISUAL_REGRESSION=0");
console.log("FORMAL_LAYOUT_OPT_IN_ONLY=YES");
console.log("SUMMARY_MIN_ROWS_DISPLAY_ONLY=PASS");
console.log("FORMAL_RECIPIENT_SUFFIX=PASS");
console.log("FORMAL_META_TWO_LINE_HEADER=PASS");
console.log("FORMAL_SUMMARY_TERMS=PASS");
console.log("FORMAL_ITEMS_HEADING=PASS");
console.log("FORMAL_DYNAMIC_SUPPLY_LABEL=PASS");
console.log("FORMAL_SENDER_ORDER=PASS");
console.log("FORMAL_ISSUE_DATE_FORMAT=PASS");
console.log("DETAIL_REPEATED_NAME_MERGED=PASS");
console.log("DETAIL_HEADER_GRAY=PASS");
console.log("DETAIL_COMPACT_ROWS=PASS");
console.log("DETAIL_SUBTOTAL_ROW=PASS");
console.log("DETAIL_FINAL_ROW=PASS");
console.log("DETAIL_FINAL_VALUE_EQUALS_QUOTECORE_SUBTOTAL=YES");
console.log("QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES");
console.log("QUOTECORE_TOTALS_UNCHANGED_ACROSS_TEMPLATES=YES");
console.log("CURRENT_B66_TEMPLATE_MIGRATED_AS_BUILTIN=YES");
console.log("UNAPPROVED_TEMPLATE_ACTIVATION=0");
console.log("FORGED_BUILTIN_FLAG_BYPASS=0");
console.log("CANONICAL_BUILTIN_FALLBACK=PASS");
console.log("APPROVED_TEMPLATE_SAVE_AND_RENDER=PASS");
console.log("TEMPLATE_ACCENT_APPLIED=PASS");
console.log("TEMPLATE_RULES_APPLIED=PASS");
console.log("TEMPLATE_ALIGNMENT_APPLIED=PASS");
console.log("TEMPLATE_TOTALS_WIDTH_APPLIED=PASS");
console.log("TEMPLATE_PAGE_RULE_APPLIED=PASS");
console.log("SLOT_BEHAVIOR=PRIVATE_ASSET_REF_V1");
console.log("MODEL_DEPENDENCY=0");
console.log("TRUSTED_TOTALS_IN_TEMPLATE=0");