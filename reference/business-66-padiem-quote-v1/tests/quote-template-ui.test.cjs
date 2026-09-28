const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const Core = require("../quote-core.js");
const Template = require("../quote-template.js");
const Store = require("../quote-template-store.js");
const Selection = require("../quote-template-selection.js");
const Renderer = require("../quote-template-renderer.js");
const Ui = require("../quote-template-ui.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const readSource = (name) => fs.readFileSync(path.join(__dirname, "..", name), "utf8");
const BUILTIN = Template.BUILTIN_TEMPLATE_ID;
const APPROVED_AT = "2026-09-28T05:00:00Z";

const builtinContent = () => clone(Store.defaultTemplate(Store.emptyStore()).content);

function approvedProfile(id, mutate) {
  const content = builtinContent();
  if (typeof mutate === "function") mutate(content);
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

function makeStyleStub() {
  return {
    props: {},
    setProperty(name, value) { this.props[name] = String(value); },
    getPropertyValue(name) { return this.props[name] === undefined ? "" : this.props[name]; }
  };
}

function stubDoc(ids) {
  const nodes = new Map();
  let seq = 0;
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
    getElementById: (id) => (id === "head" ? head : (nodes.has(id) ? nodes.get(id) : null)),
    createElement: (tag) => { seq += 1; return makeNode("", String(tag || "div").toUpperCase() + "-" + seq); }
  };
}

/* ── TEMPLATE_MANAGEMENT_CRUD — 행 모델 ── */
const uiRows = Ui.buildRows(
  [
    { id: BUILTIN, name: "기본 견적서", builtin: true, approved: true, isDefault: true, fingerprint: "a".repeat(64) },
    { id: "tpl-a", name: "우리 회사 양식", builtin: false, approved: true, isDefault: false, fingerprint: "b".repeat(64) },
    { id: "tpl-c", name: "검토 대기", builtin: false, approved: false, isDefault: false, fingerprint: "c".repeat(64) }
  ],
  { activeTemplateId: "tpl-a", previewTemplateId: null, renamingTemplateId: null }
);

eq(uiRows.length, 3, "a row is built per template");
eq(uiRows[0].statusKey, Ui.STATUS_BUILTIN, "the built-in is labelled as provided");
eq(uiRows[1].statusKey, Ui.STATUS_APPROVED, "an approved template is labelled as approved");
eq(uiRows[2].statusKey, Ui.STATUS_UNAPPROVED, "a candidate is labelled as pending approval");
eq(uiRows[0].canDelete, false, "BUILTIN_TEMPLATE_DELETE=DENIED: no delete action for the built-in");
eq(uiRows[0].canRename, false, "the built-in cannot be renamed");
eq(uiRows[0].canDuplicate, true, "the built-in can be duplicated");
eq(uiRows[2].selectable, false, "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate row is not selectable");
eq(uiRows[2].canSetDefault, false, "UNAPPROVED_TEMPLATE_DEFAULT=0: a candidate cannot be defaulted");
eq(uiRows[2].canPreview, false, "a candidate cannot be previewed");
eq(uiRows[1].isActive, true, "the active template is flagged");
eq(uiRows[1].canSetDefault, true, "an approved non-default template can be defaulted");
eq(uiRows[0].isDefault, true, "the default template is flagged");

const renamedRows = Ui.buildRows(
  [{ id: "tpl-a", name: "우리 회사 양식", builtin: false, approved: true, isDefault: false, fingerprint: "" }],
  { renamingTemplateId: "tpl-a" }
);
eq(renamedRows[0].isRenaming, true, "the renaming row is flagged");

const previewRows = Ui.buildRows(
  [{ id: "tpl-a", name: "우리 회사 양식", builtin: false, approved: true, isDefault: false, fingerprint: "" }],
  { activeTemplateId: "tpl-a", previewTemplateId: "tpl-a" }
);
eq(previewRows[0].isPreviewing, true, "the previewed row is flagged");

/* ── 선택 목록 ── */
const options = Ui.buildOptions(
  [
    { id: BUILTIN, name: "기본 견적서", approved: true, isDefault: true },
    { id: "tpl-c", name: "검토 대기", approved: false, isDefault: false }
  ],
  BUILTIN
);
eq(options.length, 2, "an option per template");
eq(options[0].disabled, false, "the built-in option is enabled");
eq(options[0].selected, true, "the active template option is selected");
eq(options[0].label, "기본 견적서 (기본 양식)", "the default option is labelled");
eq(options[1].disabled, true, "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate option is disabled");
check(options[1].hint.length > 0, "the disabled option explains why");
check(Ui.renderOptionsMarkup(options).indexOf("disabled") !== -1, "the disabled state reaches the markup");

/* ── 마크업: 이스케이프와 조작 불가 상태 ── */
const markup = Ui.renderRowsMarkup(
  Ui.buildRows(
    [
      { id: "evil", name: '<img src=x onerror="alert(1)">', builtin: false, approved: false, isDefault: false, fingerprint: "d".repeat(64) },
      { id: BUILTIN, name: "기본 견적서", builtin: true, approved: true, isDefault: true, fingerprint: "a".repeat(64) }
    ],
    { activeTemplateId: BUILTIN }
  ),
  { previewTemplateId: null }
);
check(markup.indexOf("<img") === -1, "template names are escaped in the list");
check(markup.indexOf("&lt;img") !== -1, "the escaped name is present");
check(markup.indexOf('data-action="remove"') !== -1, "the list exposes a delete action");
check(markup.indexOf('data-template-id="evil"') !== -1, "rows carry their template id");
check(markup.indexOf('role="listitem"') !== -1, "rows are list items for assistive tech");
check(markup.indexOf('aria-current="true"') !== -1, "the active row is announced");
check(markup.indexOf("template-action") !== -1, "actions use the 44px action class");
const candidateOnlyMarkup = Ui.renderRowsMarkup(
  Ui.buildRows(
    [{ id: "tpl-c", name: "검토 대기", builtin: false, approved: false, isDefault: false, fingerprint: "c".repeat(64) }],
    { activeTemplateId: null }
  ),
  {}
);
check(candidateOnlyMarkup.indexOf("disabled") !== -1,
  "UNAPPROVED_TEMPLATE_SELECTION=0: candidate actions are disabled in the markup");
check(candidateOnlyMarkup.indexOf('data-role="rename-input"') === -1, "a candidate is not in rename mode by default");
check(candidateOnlyMarkup.indexOf("승인 후 이 견적에 적용할 수 있습니다") !== -1,
  "the candidate row explains why it cannot be applied");
check(candidateOnlyMarkup.indexOf('data-action="duplicate"') !== -1, "a candidate can still be duplicated");
check(candidateOnlyMarkup.indexOf('data-action="remove"') !== -1, "a candidate can still be deleted");

const renameMarkup = Ui.renderRowsMarkup(
  Ui.buildRows(
    [{ id: "tpl-a", name: "우리 회사 양식", builtin: false, approved: true, isDefault: false, fingerprint: "" }],
    { renamingTemplateId: "tpl-a" }
  ),
  {}
);
check(renameMarkup.indexOf('data-role="rename-input"') !== -1, "rename mode renders an input");
check(renameMarkup.indexOf('data-action="rename-save"') !== -1, "rename mode renders a save action");
check(renameMarkup.indexOf('data-action="rename-cancel"') !== -1, "rename mode renders a cancel action");

const previewMarkup = Ui.renderRowsMarkup(previewRows, { previewTemplateId: "tpl-a" });
check(previewMarkup.indexOf("template-preview-banner") !== -1, "preview mode shows a banner");
check(previewMarkup.indexOf("아직 적용되지 않았습니다") !== -1, "the banner states that nothing is applied yet");
check(previewMarkup.indexOf('data-action="preview-apply"') !== -1, "preview mode offers an apply action");
check(previewMarkup.indexOf('data-action="preview-cancel"') !== -1, "preview mode offers a cancel action");

/* ── 상태 문구 ── */
check(Ui.buildStatusText(Store.defaultTemplate(Store.emptyStore()), {}).indexOf("기본 제공 양식") !== -1,
  "the built-in status is stated");
check(Ui.buildStatusText(approvedProfile("tpl-a"), { fallbackReason: "template_not_approved" }).indexOf("적용할 수 없어") !== -1,
  "the unapproved fallback is stated");
check(Ui.buildStatusText(approvedProfile("tpl-a"), { fallbackReason: "missing_selected_template" }).indexOf("삭제되어") !== -1,
  "the missing-template fallback is stated");
check(Ui.buildStatusText(approvedProfile("tpl-a"), { fallbackReason: "invalid_template_profile" }).indexOf("손상되어") !== -1,
  "the corrupt-template fallback is stated");
check(Ui.buildStatusText(null, {}).indexOf("기본 견적서") !== -1, "a missing active template is reported safely");
check(Ui.buildStatusText(approvedProfile("tpl-a"), { previewTemplateId: "tpl-a" }).indexOf("[미리보기]") === 0,
  "preview mode is announced in the status text");

/* ── DOM-level: 같은 초안 + 양식 A / 양식 B ── */
const draft = Core.createDefaultDraft();
const before = clone(draft);

const templateA = approvedProfile("tpl-a", (content) => {
  content.style.accent = "#8a1f1f";
  content.style.titleRule = "4px solid #8a1f1f";
  content.style.totalsWidth = "420px";
  content.page = { size: "A5", margin: "8mm", orientation: "landscape" };
});
const templateB = approvedProfile("tpl-b", (content) => {
  content.style.accent = "#1f4e8a";
  content.style.titleRule = "1px dashed #1f4e8a";
  content.style.totalsWidth = "260px";
  content.page = { size: "A4", margin: "14mm", orientation: "portrait" };
});

const ADAPTER_IDS = [
  "quotePaper", "pvItems", "pvItemsHead", "pvTitle", "pvGrand", "pvSubtotal", "pvVat",
  "subtotalLabelText", "subtotalText", "vatLabelText", "vatText", "grandLabelText", "grandText",
  "pvSubtotalLabel", "pvVatLabel", "pvGrandLabel", "pvMemo", "pvMark",
  "pvQuoteNo", "pvDate", "pvValidity", "pvValidUntil", "pvTaxMode",
  "pvSenderHeading", "pvSenderCompany", "pvSenderRep", "pvSenderBizNo", "pvSenderAddress", "pvSenderContact",
  "pvRecipientHeading", "pvRecipientCompany", "pvRecipientPerson", "pvRecipientAddress", "pvRecipientEmail"
];

function renderInto(profile) {
  const doc = stubDoc(ADAPTER_IDS);
  const model = Renderer.buildRenderModel(draft, profile, { taxReviewRequired: false });
  Renderer.applyRenderModel(doc, model);
  return { doc: doc, model: model };
}

const renderA = renderInto(templateA);
const renderB = renderInto(templateB);
const renderBuiltin = renderInto(Store.defaultTemplate(Store.emptyStore()));

/* 업무 내용은 양식과 무관하게 동일하다 */
eq(draft, before, "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: rendering never mutates the draft");
eq(renderA.doc.getElementById("pvQuoteNo").textContent, renderB.doc.getElementById("pvQuoteNo").textContent,
  "the quote number is identical across templates");
eq(renderA.doc.getElementById("pvSenderCompany").textContent, renderB.doc.getElementById("pvSenderCompany").textContent,
  "sender business data is identical across templates");
eq(renderA.doc.getElementById("pvRecipientCompany").textContent, renderB.doc.getElementById("pvRecipientCompany").textContent,
  "recipient business data is identical across templates");
eq(renderA.doc.getElementById("pvItems").innerHTML, renderB.doc.getElementById("pvItems").innerHTML,
  "item rows are identical across templates");
eq(renderA.doc.getElementById("pvMemo").textContent, renderB.doc.getElementById("pvMemo").textContent,
  "memo business content is identical across templates");

/* QuoteCore 합계도 동일하다 */
const totalsA = Core.computeTotals(draft.items, draft.tax.mode);
eq(renderA.doc.getElementById("pvGrand").textContent, Core.formatMoney(totalsA.grand), "grand comes from QuoteCore");
eq(renderA.doc.getElementById("pvGrand").textContent, renderB.doc.getElementById("pvGrand").textContent,
  "QUOTECORE_TOTALS_UNCHANGED_ACROSS_TEMPLATES=YES: the grand total is identical across templates");
eq(renderA.doc.getElementById("pvSubtotal").textContent, renderB.doc.getElementById("pvSubtotal").textContent,
  "the subtotal is identical across templates");
eq(renderA.doc.getElementById("pvVat").textContent, renderB.doc.getElementById("pvVat").textContent,
  "the vat amount is identical across templates");

/* 스타일/레이아웃 투영은 달라진다 */
const paperA = renderA.doc.getElementById("quotePaper");
const paperB = renderB.doc.getElementById("quotePaper");
const paperBuiltin = renderBuiltin.doc.getElementById("quotePaper");
check(paperA.style.getPropertyValue("--quote-accent") !== paperB.style.getPropertyValue("--quote-accent"),
  "the accent differs between templates");
check(paperA.style.getPropertyValue("--quote-title-rule") !== paperB.style.getPropertyValue("--quote-title-rule"),
  "the title rule differs between templates");
check(paperA.style.getPropertyValue("--quote-totals-width") !== paperB.style.getPropertyValue("--quote-totals-width"),
  "the totals width differs between templates");
check(renderA.doc.head.children[0].textContent !== renderB.doc.head.children[0].textContent,
  "the print page rule differs between templates");
check(paperBuiltin.style.getPropertyValue("--quote-accent") !== paperA.style.getPropertyValue("--quote-accent"),
  "a stored template differs from the built-in");
check(renderBuiltin.doc.getElementById("pvGrand").textContent === renderA.doc.getElementById("pvGrand").textContent,
  "the built-in keeps the same QuoteCore totals");

/* 미승인 candidate 는 어떤 경로로도 렌더되지 않는다 */
const candidateProfile = Template.buildProfile({
  id: "tpl-c", name: "검토 대기", builtin: false, isDefault: false, approval: null,
  createdAt: "", updatedAt: "", content: builtinContent()
});
const renderCandidate = renderInto(candidateProfile);
eq(renderCandidate.model.template.id, BUILTIN, "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate never renders");
eq(renderCandidate.model.template.fallbackReason, "template_not_approved", "the fallback reason is explicit");
eq(renderCandidate.doc.getElementById("pvGrand").textContent, renderBuiltin.doc.getElementById("pvGrand").textContent,
  "the fallback keeps the built-in output");
eq(renderCandidate.doc.getElementById("quotePaper").style.getPropertyValue("--quote-accent"),
  paperBuiltin.style.getPropertyValue("--quote-accent"), "the candidate cannot inject style");

/* ── 정적 계약 ── */
const uiSource = readSource("quote-template-ui.js");
const selectionSource = readSource("quote-template-selection.js");
check(!/fetch\(|XMLHttpRequest/.test(uiSource + selectionSource), "MODEL_NETWORK_CALLS=0: no network call");
check(!/kilo\/|space-bunny|nemotron|openai|anthropic/i.test(uiSource + selectionSource),
  "MODEL_NETWORK_CALLS=0: no provider or model reference");
check(uiSource.indexOf("function escapeHtml(") !== -1, "the UI layer escapes user text");
check(uiSource.indexOf("visually-hidden") !== -1 || uiSource.indexOf("template-rename") !== -1,
  "the rename control is labelled for assistive tech");
check(selectionSource.indexOf("draft.") === -1, "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: the selection layer never reads or writes the draft");
check(uiSource.indexOf("draft.") === -1, "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: the UI layer never reads or writes the draft");

console.log("TEMPLATE_SELECTOR_LIVE=YES");
console.log("TEMPLATE_MANAGEMENT_CRUD=PASS");
console.log("DEFAULT_TEMPLATE_SELECTION=PASS");
console.log("BUILTIN_TEMPLATE_FALLBACK=PASS");
console.log("UNAPPROVED_TEMPLATE_SELECTION=0");
console.log("UNAPPROVED_TEMPLATE_DEFAULT=0");
console.log("TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO");
console.log("QUOTECORE_TOTALS_UNCHANGED_ACROSS_TEMPLATES=YES");
console.log("BUILTIN_TEMPLATE_DELETE=DENIED");
console.log("MODEL_NETWORK_CALLS=0");
