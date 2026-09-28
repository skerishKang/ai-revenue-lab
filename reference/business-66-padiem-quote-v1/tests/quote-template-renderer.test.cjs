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

/* ── 레거시 render() 재현 (변경 전 app.js 의 표시 로직을 독립적으로 옮긴 것) ──
   이 테스트의 회귀 판정 기준이다. 렌더러가 여기서 벗어나면 화면이 달라진 것이다. */

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

function applyToModel(draft, provisional) {
  const profile = Store.defaultTemplate(Store.emptyStore());
  return Renderer.buildRenderModel(draft, profile, { taxReviewRequired: provisional });
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

function stubDoc() {
  const nodes = new Map();
  return {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, { id, textContent: null, innerHTML: null });
      return nodes.get(id);
    },
    nodes
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
eq(
  applyToModel(defaultDraft, false),
  applyToModel(defaultDraft, false),
  "same draft + same template yields an identical model"
);
eq(
  Renderer.buildRenderModel(defaultDraft, Template.builtInTemplate(), {}),
  Renderer.buildRenderModel(defaultDraft, Template.builtInTemplate(), { taxReviewRequired: false }),
  "missing options match taxReviewRequired=false"
);

/* 렌더러 소스는 결정적이어야 한다 */
const rendererSource = readSource("quote-template-renderer.js");
check(!/Math\.random|Date\.now|new Date\(/.test(rendererSource), "renderer has no time/random dependency");
check(!/fetch\(|XMLHttpRequest|axios/.test(rendererSource), "renderer performs no network request");
check(!/kilo\/|sensenova\/|space-bunny|nemotron|openai|anthropic/i.test(rendererSource), "renderer names no provider or model");

/* 입력 불변: 렌더링은 draft 를 변형하지 않는다 */
const before = JSON.stringify(defaultDraft);
applyToModel(defaultDraft, true);
eq(JSON.parse(before), JSON.parse(JSON.stringify(defaultDraft)), "renderer does not mutate the draft");

/* QUOTECORE_REMAINS_CALCULATION_AUTHORITY */
const authoritative = applyToModel(defaultDraft, false);
const authoritativeTotals = Core.computeTotals(defaultDraft.items, defaultDraft.tax.mode);
eq(authoritative.derivedBy, "quote-core", "model declares QuoteCore as the calculation authority");
eq(authoritative.totals.subtotalText, Core.formatMoney(authoritativeTotals.supply), "subtotal comes from QuoteCore");
eq(authoritative.totals.vatText, Core.formatMoney(authoritativeTotals.vat), "vat comes from QuoteCore");
eq(authoritative.totals.grandText, Core.formatMoney(authoritativeTotals.grand), "grand comes from QuoteCore");

/* template 만 바꿔도 QuoteCore totals 는 동일하다 */
const restyledContent = clone(Template.builtInTemplate().content);
restyledContent.style.accent = "#2563eb";
restyledContent.totals.supplyLabel = "공급가액 합계";
restyledContent.items.columns.reverse();
const restyledProfile = Template.buildProfile({
  id: "tpl-restyle", name: "다른 양식", builtin: false, isDefault: false,
  createdAt: "", updatedAt: "", content: restyledContent
});
const restyledModel = Renderer.buildRenderModel(defaultDraft, restyledProfile, { taxReviewRequired: false });
eq(restyledModel.totals.grandText, authoritative.totals.grandText, "template change keeps QuoteCore grand total");
eq(restyledModel.totals.vatText, authoritative.totals.vatText, "template change keeps QuoteCore vat");
eq(restyledModel.totals.subtotalText, authoritative.totals.subtotalText, "template change keeps QuoteCore subtotal");
check(restyledModel.totals.subtotalLabel === "공급가액 합계", "template change does change the label");
eq(restyledModel.columns.map((column) => column.key), ["amount", "unitPrice", "qty", "name"], "template column order is honoured");
check(restyledModel.template.fingerprint !== authoritative.template.fingerprint, "restyled template has its own fingerprint");

/* draft 금액이 바뀌면 QuoteCore 파생 합계만 바뀐다 */
const richerDraft = Core.normalizeDraft(Object.assign(clone(defaultDraft), {
  items: [{ id: "item-1", name: "서비스 구축", qty: 3, unitPrice: 1000000 }]
}));
const richerModel = Renderer.buildRenderModel(richerDraft, Template.builtInTemplate(), { taxReviewRequired: false });
check(richerModel.totals.grandText !== authoritative.totals.grandText, "draft change moves the QuoteCore grand total");

/* 섹션 게이팅: 프로필이 실제로 문서 구성을 소유한다 */
function profileWithout(section) {
  const content = clone(Template.builtInTemplate().content);
  content.sections = content.sections.filter((name) => name !== section);
  return Template.buildProfile({
    id: "tpl-nosec", name: "섹션 제거", builtin: false, isDefault: false,
    createdAt: "", updatedAt: "", content: content
  });
}
const noMemo = Renderer.buildRenderModel(defaultDraft, profileWithout("memo"), { taxReviewRequired: false });
check(noMemo.memoText === "", "removing the memo section clears the memo text");
const noTitle = Renderer.buildRenderModel(defaultDraft, profileWithout("title"), { taxReviewRequired: false });
check(noTitle.titleText === "", "removing the title section clears the title text");
const noTotals = Renderer.buildRenderModel(defaultDraft, profileWithout("totals"), { taxReviewRequired: false });
check(noTotals.totals.subtotalText === "" && noTotals.totals.grandText === "", "removing the totals section clears totals text");
const noParties = Renderer.buildRenderModel(defaultDraft, profileWithout("parties"), { taxReviewRequired: false });
check(noParties.parties.sender.company === "" && noParties.parties.recipient.company === "", "removing the parties section clears party text");
check(noMemo.totals.grandText === authoritative.totals.grandText, "removing a section never changes QuoteCore totals");

/* 잘못된 프로필은 내장 기본으로 복구된다 */
check(
  Renderer.buildRenderModel(defaultDraft, { schemaVersion: 99 }, { taxReviewRequired: false }).template.id
    === Template.BUILTIN_TEMPLATE_ID,
  "invalid profile falls back to the built-in template"
);
check(Renderer.buildRenderModel(null, Template.builtInTemplate()) === null, "invalid draft yields no model");
check(Renderer.buildRenderModel({ schemaVersion: 9 }, Template.builtInTemplate()) === null, "wrong draft schema yields no model");

/* DOM adapter: 모델 → 실제 요소. index.html 에 존재하는 id 만 대상으로 한다 */
const pageHtml = readSource("index.html");
const ADAPTER_IDS = [
  "pvTitle", "pvQuoteNo", "pvDate", "pvValidity", "pvValidUntil", "pvTaxMode",
  "pvSenderHeading", "pvSenderCompany", "pvSenderRep", "pvSenderBizNo", "pvSenderAddress", "pvSenderContact",
  "pvRecipientHeading", "pvRecipientCompany", "pvRecipientPerson", "pvRecipientAddress", "pvRecipientEmail",
  "pvItemsHead", "pvItems",
  "subtotalLabelText", "subtotalText", "vatLabelText", "vatText", "grandLabelText", "grandText",
  "pvSubtotalLabel", "pvSubtotal", "pvVatLabel", "pvVat", "pvGrandLabel", "pvGrand", "pvMemo", "pvMark"
];
ADAPTER_IDS.forEach((id) => {
  check(pageHtml.includes(`id="${id}"`), `index.html exposes adapter target ${id}`);
});

const adapterSource = readSource("quote-template-renderer.js");
ADAPTER_IDS.forEach((id) => {
  check(adapterSource.includes(`"${id}"`), `adapter writes element ${id}`);
});

drafts.forEach(([label, base]) => {
  modes.forEach((mode) => {
    [false, true].forEach((provisional) => {
      const draft = Core.normalizeDraft(Object.assign(clone(base), { tax: { mode: mode, rate: 0.1 } }));
      const totals = Core.computeTotals(draft.items, draft.tax.mode);
      const model = applyToModel(draft, provisional);
      const doc = stubDoc();
      check(Renderer.applyRenderModel(doc, model) === true, "adapter reports success");
      const expected = legacyProjection(draft, provisional);
      ADAPTER_IDS.filter((id) => id !== "pvItems" && id !== "pvItemsHead").forEach((id) => {
        eq(doc.getElementById(id).textContent, expected[id], `adapter ${id} for ${label}/${mode}/${provisional}`);
      });
      eq(
        norm(doc.getElementById("pvItems").innerHTML),
        norm(legacyItemsHtml(draft, totals)),
        `adapter item rows for ${label}/${mode}/${provisional}`
      );
      eq(
        norm(doc.getElementById("pvItemsHead").innerHTML),
        norm(LEGACY_HEAD_HTML),
        `adapter table head for ${label}/${mode}/${provisional}`
      );
    });
  });
});

/* 어댑터는 HTML 을 이스케이프한다 */
const htmlDoc = stubDoc();
Renderer.applyRenderModel(htmlDoc, applyToModel(htmlDraft, false));
const htmlRows = htmlDoc.getElementById("pvItems").innerHTML;
check(htmlRows.indexOf("<b>") === -1 && htmlRows.indexOf("&lt;b&gt;") !== -1, "item name is escaped in the rendered table");
check(htmlDoc.getElementById("pvSenderCompany").textContent === '<img src=x onerror="alert(1)">',
  "textContent targets keep raw text (no double escaping)");
eq(
  htmlRows.indexOf("onerror"),
  -1,
  "injected attribute text stays inert"
);

/* 어댑터 방어: 잘못된 입력은 크래시 대신 false */
check(Renderer.applyRenderModel(null, authoritative) === false, "adapter without document fails safe");
check(Renderer.applyRenderModel(stubDoc(), null) === false, "adapter without model fails safe");
check(Renderer.applyRenderModel(stubDoc(), "nope") === false, "adapter with junk model fails safe");

/* 이스케이프 단일 구현이 변형 전 app.js 와 동일하다 */
[
  "", "plain", "<script>", 'a"b', "a'b", "a&b", "<>&\"'", "한글 & <b>"
].forEach((sample) => {
  eq(Template.escapeHtml(sample), legacyEscape(sample), `escape parity for ${JSON.stringify(sample)}`);
});
eq(Renderer.escapeHtml, Template.escapeHtml, "renderer re-exports the single escap implementation");

/* 레거시 마크업과 생성 마크업의 정규화 비교 (공백만 다름) */
const legacyHeadFromPage = /<thead><tr id="pvItemsHead">([\s\S]*?)<\/tr><\/thead>/.exec(pageHtml);
check(legacyHeadFromPage !== null, "index.html still carries the table head");
eq(norm(legacyHeadFromPage[1]), norm(LEGACY_HEAD_HTML), "index.html head matches the profile-generated head");

console.log("QUOTE_TEMPLATE_RENDERER_DETERMINISTIC=YES");
console.log("CURRENT_DEFAULT_VISUAL_REGRESSION=0");
console.log("QUOTECORE_REMAINS_CALCULATION_AUTHORITY=YES");
console.log("CURRENT_B66_TEMPLATE_MIGRATED_AS_BUILTIN=YES");
console.log("MODEL_DEPENDENCY=0");
console.log("TRUSTED_TOTALS_IN_TEMPLATE=0");
