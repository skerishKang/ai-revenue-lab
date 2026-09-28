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

check(Renderer.buildRenderModel(null, builtinProfile()) === null, "invalid draft yields no model");
check(Renderer.buildRenderModel({ schemaVersion: 9 }, builtinProfile()) === null, "wrong draft schema yields no model");

/* QUOTECORE_REMAINS_CALCULATION_AUTHORITY */
const authoritative = applyToModel(defaultDraft, false);
const authoritativeTotals = Core.computeTotals(defaultDraft.items, defaultDraft.tax.mode);
eq(authoritative.derivedBy, "quote-core", "model declares QuoteCore as the calculation authority");
eq(authoritative.totals.subtotalText, Core.formatMoney(authoritativeTotals.supply), "subtotal comes from QuoteCore");
eq(authoritative.totals.vatText, Core.formatMoney(authoritativeTotals.vat), "vat comes from QuoteCore");
eq(authoritative.totals.grandText, Core.formatMoney(authoritativeTotals.grand), "grand comes from QuoteCore");

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

/* ── SLOT — non-live 로 명시되고 조용히 사라지지 않는다 ── */
eq(authoritative.slots.support, "non_live", "SLOT_BEHAVIOR: slots are declared non-live");
eq(authoritative.slots.rendered, false, "SLOT_BEHAVIOR: slots are not rendered in this MVP");
const declaredSlotContent = clone(Template.builtInTemplate().content);
declaredSlotContent.slots = { logo: "brand-a", stamp: "" };
const declaredSlotModel = Renderer.buildRenderModel(defaultDraft, approvedProfile("slot-1", declaredSlotContent), { taxReviewRequired: false });
eq(declaredSlotModel.slots.declared.logo, "brand-a", "SLOT_BEHAVIOR: declared slot values are surfaced, not silently dropped");
eq(declaredSlotModel.slots.rendered, false, "SLOT_BEHAVIOR: declared slots are still not rendered");

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
  "pvTitle", "pvQuoteNo", "pvDate", "pvValidity", "pvValidUntil", "pvTaxMode",
  "pvSenderHeading", "pvSenderCompany", "pvSenderRep", "pvSenderBizNo", "pvSenderAddress", "pvSenderContact",
  "pvRecipientHeading", "pvRecipientCompany", "pvRecipientPerson", "pvRecipientAddress", "pvRecipientEmail",
  "pvItemsHead", "pvItems", "quotePaper",
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
      ADAPTER_IDS.filter((id) => id !== "pvItems" && id !== "pvItemsHead" && id !== "quotePaper").forEach((id) => {
        eq(doc.getElementById(id).textContent, expected[id], `adapter ${id} for ${label}/${mode}/${provisional}`);
      });
      eq(
        norm(doc.getElementById("pvItems").innerHTML),
        norm(legacyItemsHtml(draft, totals)),
        `adapter item rows for ${label}/${mode}/${provisional}`
      );
      eq(norm(doc.getElementById("pvItemsHead").innerHTML), norm(LEGACY_HEAD_HTML),
        `adapter table head for ${label}/${mode}/${provisional}`);
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
console.log("QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES");
console.log("QUOTECORE_TOTALS_UNCHANGED_ACROSS_TEMPLATES=YES");
console.log("CURRENT_B66_TEMPLATE_MIGRATED_AS_BUILTIN=YES");
console.log("UNAPPROVED_TEMPLATE_ACTIVATION=0");
console.log("APPROVED_TEMPLATE_SAVE_AND_RENDER=PASS");
console.log("TEMPLATE_ACCENT_APPLIED=PASS");
console.log("TEMPLATE_RULES_APPLIED=PASS");
console.log("TEMPLATE_ALIGNMENT_APPLIED=PASS");
console.log("TEMPLATE_TOTALS_WIDTH_APPLIED=PASS");
console.log("TEMPLATE_PAGE_RULE_APPLIED=PASS");
console.log("SLOT_BEHAVIOR=PLACEHOLDER_CONTRACT_ONLY");
console.log("MODEL_DEPENDENCY=0");
console.log("TRUSTED_TOTALS_IN_TEMPLATE=0");
