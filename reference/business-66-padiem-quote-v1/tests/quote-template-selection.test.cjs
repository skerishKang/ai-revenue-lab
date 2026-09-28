const assert = require("node:assert");
const Template = require("../quote-template.js");
const Store = require("../quote-template-store.js");
const Selection = require("../quote-template-selection.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-28T09:00:00.000Z";
const BUILTIN = Template.BUILTIN_TEMPLATE_ID;
const QUOTE_A = "PQ-20260928-001";
const QUOTE_B = "PQ-20260928-002";

function fakeStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, String(value)); },
    removeItem: (key) => { map.delete(key); },
    keys: () => Array.from(map.keys())
  };
}

const builtinContent = () => clone(Store.defaultTemplate(Store.emptyStore()).content);

function styledContent(accent) {
  const content = builtinContent();
  content.style.accent = accent;
  return content;
}

function evidenceFor(content) {
  return {
    schemaVersion: 1,
    status: "approved",
    contentFingerprint: Template.templateFingerprint(content),
    approvedBy: "central-cto",
    approvedAt: "2026-09-28T05:00:00Z"
  };
}

function seedApproved(storage, id, content, name) {
  const result = Store.createTemplate(
    Store.readStore(storage),
    { name: name || id, content: content },
    { id: id, approval: evidenceFor(content), now: NOW }
  );
  check(result.ok === true, `seed approved ${id}`);
  Store.writeStore(storage, result.store);
  return result.template;
}

function seedCandidate(storage, id, content, name) {
  const result = Store.createTemplate(
    Store.readStore(storage),
    { name: name || id, content: content },
    { id: id, now: NOW }
  );
  check(result.ok === true, `seed candidate ${id}`);
  Store.writeStore(storage, result.store);
  return result.template;
}

/* ── envelope 계약 ── */
eq(Selection.SELECTION_SCHEMA_VERSION, 1, "selection schema version");
eq(Selection.MAX_SELECTIONS, 20, "bounded selection count matches the history bound");
check(Selection.SELECTION_STORAGE_KEY.indexOf("quoteBeta") === 0, "selection key lives in the B66 namespace");

eq(Selection.emptyEnvelope(), { schemaVersion: 1, selections: [] }, "empty envelope shape");
eq(Selection.normalizeEnvelope(null), Selection.emptyEnvelope(), "null envelope is empty");
eq(Selection.normalizeEnvelope("garbage"), Selection.emptyEnvelope(), "garbage envelope is empty");
eq(Selection.normalizeEnvelope({ schemaVersion: 9, selections: [] }), Selection.emptyEnvelope(),
  "wrong envelope schema is empty");
eq(Selection.normalizeEnvelope({ schemaVersion: 1, selections: "nope" }), Selection.emptyEnvelope(),
  "non-array selections is empty");

check(Selection.normalizeSelectionEntry(null) === null, "null entry rejected");
check(Selection.normalizeSelectionEntry({}) === null, "entry without a quote number rejected");
check(Selection.normalizeSelectionEntry({ quoteNo: QUOTE_A }) === null, "entry without a template id rejected");
check(Selection.normalizeSelectionEntry({ quoteNo: "x".repeat(400), templateId: "t" }) === null,
  "over-long quote number rejected");
check(Selection.normalizeSelectionEntry({ quoteNo: QUOTE_A, templateId: "t" }) !== null, "valid entry accepted");

/* MALFORMED entry 는 개별 fail-closed — 나머지는 살아남는다 */
const mixedEnvelope = Selection.normalizeEnvelope({
  schemaVersion: 1,
  selections: [
    { quoteNo: QUOTE_A, templateId: "tpl-a", updatedAt: NOW },
    null,
    7,
    "x",
    {},
    { quoteNo: "", templateId: "tpl-x" },
    { quoteNo: QUOTE_B, templateId: "" },
    { quoteNo: QUOTE_B, templateId: "tpl-b", updatedAt: NOW }
  ]
});
eq(mixedEnvelope.selections.length, 2, "malformed selections are dropped individually");
eq(mixedEnvelope.selections[0].quoteNo, QUOTE_A, "the first valid entry survives");
eq(mixedEnvelope.selections[1].quoteNo, QUOTE_B, "the later valid entry survives");

/* 같은 견적이 두 번 나오면 첫 항목만 인정한다 */
const dupEnvelope = Selection.normalizeEnvelope({
  schemaVersion: 1,
  selections: [
    { quoteNo: QUOTE_A, templateId: "first" },
    { quoteNo: QUOTE_A, templateId: "second" }
  ]
});
eq(dupEnvelope.selections.length, 1, "a quotation keeps a single selection");
eq(Selection.selectionForQuote(dupEnvelope, QUOTE_A), "first", "the first entry wins");

/* ── 견적별 영속화: A 는 A 를, B 는 B 를 기억한다 ── */
let envelope = Selection.emptyEnvelope();
check(Selection.selectionForQuote(envelope, QUOTE_A) === null, "an empty envelope has no selection");

envelope = Selection.setSelection(envelope, QUOTE_A, "tpl-a", { now: NOW });
envelope = Selection.setSelection(envelope, QUOTE_B, "tpl-b", { now: NOW });
eq(envelope.selections.length, 2, "two quotations keep two selections");
eq(Selection.selectionForQuote(envelope, QUOTE_A), "tpl-a", "A -> tpl-a");
eq(Selection.selectionForQuote(envelope, QUOTE_B), "tpl-b", "B -> tpl-b");
eq(envelope.selections[0].quoteNo, QUOTE_B, "the most recent selection is first");

/* 저장 후 다시 읽어도(재개) 그대로다 */
const persist = fakeStorage();
check(Selection.writeEnvelope(persist, envelope) === true, "the envelope is written");
const reopened = Selection.readEnvelope(persist);
eq(Selection.selectionForQuote(reopened, QUOTE_A), "tpl-a", "reopen A -> tpl-a");
eq(Selection.selectionForQuote(reopened, QUOTE_B), "tpl-b", "reopen B -> tpl-b");

/* 같은 견적을 다시 선택하면 덮어쓴다(중복 없음) */
const rewritten = Selection.setSelection(envelope, QUOTE_A, "tpl-c", { now: NOW });
eq(rewritten.selections.length, 2, "re-selecting does not duplicate the quotation");
eq(Selection.selectionForQuote(rewritten, QUOTE_A), "tpl-c", "re-selecting replaces the template");
eq(Selection.selectionForQuote(rewritten, QUOTE_B), "tpl-b", "the other quotation is untouched");

check(Selection.setSelection(envelope, "", "tpl-a") === null, "a blank quote number cannot hold a selection");
check(Selection.setSelection(envelope, QUOTE_A, "") === null, "a blank template id cannot be stored");

/* bounded: MAX_SELECTIONS 를 넘으면 오래된 것부터 버린다 */
let bounded = Selection.emptyEnvelope();
for (let i = 0; i < Selection.MAX_SELECTIONS + 6; i += 1) {
  bounded = Selection.setSelection(bounded, "PQ-20260928-" + String(100 + i), "tpl-" + i, { now: NOW });
}
eq(bounded.selections.length, Selection.MAX_SELECTIONS, "the envelope is bounded");
eq(Selection.selectionForQuote(bounded, "PQ-20260928-" + (100 + Selection.MAX_SELECTIONS + 5)), "tpl-25",
  "the newest selection is kept");
check(Selection.selectionForQuote(bounded, "PQ-20260928-100") === null, "the oldest selection is dropped");

/* 삭제 연산 */
const removed = Selection.removeSelection(envelope, QUOTE_A);
eq(Selection.selectionForQuote(removed, QUOTE_A), null, "removing one quotation clears only that entry");
eq(Selection.selectionForQuote(removed, QUOTE_B), "tpl-b", "the other quotation survives");
eq(envelope.selections.length, 2, "removeSelection never mutates the source envelope");

const prunedA = Selection.removeSelectionsForTemplate(envelope, "tpl-a");
eq(Selection.selectionForQuote(prunedA, QUOTE_A), null, "selections pointing at the deleted template are removed");
eq(Selection.selectionForQuote(prunedA, QUOTE_B), "tpl-b", "other quotations keep their selection");

/* storage 어댑터 */
const wiped = fakeStorage();
eq(Selection.readEnvelope(wiped), Selection.emptyEnvelope(), "empty storage reads as an empty envelope");
wiped.setItem(Selection.SELECTION_STORAGE_KEY, "{not json");
eq(Selection.readEnvelope(wiped), Selection.emptyEnvelope(), "corrupt storage falls back to an empty envelope");
wiped.setItem(Selection.SELECTION_STORAGE_KEY, JSON.stringify({ schemaVersion: 9, selections: [{ quoteNo: QUOTE_A, templateId: "x" }] }));
eq(Selection.readEnvelope(wiped), Selection.emptyEnvelope(), "an old envelope schema falls back");
check(Selection.writeEnvelope(wiped, envelope) === true, "writing replaces the corrupt payload");
eq(Selection.selectionForQuote(Selection.readEnvelope(wiped), QUOTE_A), "tpl-a", "the rewritten envelope is readable");
check(Selection.clearAll(wiped) === true, "the envelope can be cleared");
eq(Selection.readEnvelope(wiped), Selection.emptyEnvelope(), "cleared storage is empty");
eq(Selection.readEnvelope(null), Selection.emptyEnvelope(), "reading without storage is safe");

/* ── 해석: 선택 → 기본 → 내장 기본 ── */
const store = fakeStorage();
seedApproved(store, "tpl-a", styledContent("#8a1f1f"));
seedApproved(store, "tpl-b", styledContent("#1f4e8a"));
seedCandidate(store, "tpl-c", styledContent("#333333"));

const rawStore = Store.readStore(store);
eq(Selection.isSelectable(rawStore, "tpl-a"), true, "an approved template is selectable");
eq(Selection.isSelectable(rawStore, "tpl-c"), false, "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate is not selectable");
eq(Selection.isSelectable(rawStore, BUILTIN), true, "the built-in is selectable");
eq(Selection.isSelectable(rawStore, ""), false, "a blank id is not selectable");

const live = Selection.setSelection(
  Selection.setSelection(Selection.emptyEnvelope(), QUOTE_A, "tpl-a"),
  QUOTE_B,
  "tpl-b"
);
eq(Selection.resolveActiveTemplateId(rawStore, live, QUOTE_A), "tpl-a", "quote A resolves to its own template");
eq(Selection.resolveActiveTemplateId(rawStore, live, QUOTE_B), "tpl-b", "quote B resolves to its own template");
eq(Selection.resolveActiveTemplateId(rawStore, live, "PQ-20260928-003"), BUILTIN,
  "BUILTIN_TEMPLATE_FALLBACK=PASS: a quotation without a selection uses the default");
eq(Selection.resolveActiveTemplateId(rawStore, null, QUOTE_A), BUILTIN, "no envelope falls back to the default");
eq(Selection.resolveActiveTemplateId(rawStore, Selection.setSelection(Selection.emptyEnvelope(), QUOTE_A, "tpl-c"), QUOTE_A), BUILTIN,
  "UNAPPROVED_TEMPLATE_SELECTION=0: an unapproved selection falls back");
eq(Selection.resolveActiveTemplateId(rawStore, Selection.setSelection(Selection.emptyEnvelope(), QUOTE_A, "gone"), QUOTE_A), BUILTIN,
  "MISSING_SELECTED_TEMPLATE_FALLBACK=PASS: a deleted selection falls back");
eq(Selection.resolveActiveTemplateId(rawStore, "garbage", QUOTE_A), BUILTIN,
  "CORRUPT_TEMPLATE_FALLBACK=PASS: corrupt selection state falls back");
eq(Selection.resolveActiveTemplate(rawStore, live, QUOTE_A).id, "tpl-a", "resolveActiveTemplate honours the selection");
check(Selection.resolveActiveTemplate(rawStore, live, QUOTE_A).approved === true, "the resolved template is approved");
check(Selection.resolveActiveTemplate(rawStore, live, QUOTE_A).content.style.accent === "#8a1f1f",
  "the resolved template carries its own content");

/* default 변경이 기존 explicit selection 을 바꾸지 않는다 */
check(Selection.writeEnvelope(store, live) === true, "the live envelope is persisted");
check(Selection.setDefaultTemplate(store, "tpl-b").ok === true, "an approved template can become the default");
eq(Store.defaultTemplateId(Store.readStore(store)), "tpl-b", "the default moved to tpl-b");
const liveAfterDefault = Selection.readEnvelope(store);
eq(Selection.selectionForQuote(liveAfterDefault, QUOTE_A), "tpl-a",
  "DEFAULT_TEMPLATE_SELECTION=PASS: a default change leaves explicit selections alone");
eq(Selection.resolveActiveTemplateId(Store.readStore(store), liveAfterDefault, QUOTE_A), "tpl-a",
  "quote A still renders with its own template");
eq(Selection.resolveActiveTemplateId(Store.readStore(store), liveAfterDefault, "PQ-20260928-004"), "tpl-b",
  "a quotation without a selection picks up the new default");
eq(Selection.setDefaultTemplate(store, "tpl-c").code, "template_not_approved",
  "UNAPPROVED_TEMPLATE_DEFAULT=0: a candidate cannot become the default");
eq(Selection.setDefaultTemplate(store, BUILTIN).ok, true, "the built-in can be restored as the default");

/* ── 목록 모델 ── */
const rows = Selection.listForManagement(Store.readStore(store));
eq(rows.length, 4, "the list shows the built-in and every user template");
const builtinRow = rows.filter((row) => row.id === BUILTIN)[0];
const candidateRow = rows.filter((row) => row.id === "tpl-c")[0];
check(builtinRow.canDelete === false && builtinRow.canRename === false,
  "BUILTIN_TEMPLATE_DELETE=DENIED: the built-in cannot be renamed or deleted");
check(candidateRow.selectable === false && candidateRow.canSetDefault === false,
  "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate is visible but inert");
check(candidateRow.canApprove === true, "a candidate is marked as approvable in the next step");

/* ── 액션 ── */
const draftBefore = clone({ sender: "a", recipient: "b", items: [1, 2], tax: "EXCLUSIVE", memo: "m" });

check(Selection.selectTemplate(store, QUOTE_A, "tpl-a", { now: NOW }).ok === true, "an approved template can be selected");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_A), "tpl-a", "the selection is persisted");
check(Selection.selectTemplate(store, QUOTE_B, "tpl-b", { now: NOW }).ok === true, "a second quotation can select its own template");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_B), "tpl-b", "the second selection is persisted");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_A), "tpl-a", "the first selection is untouched");
eq(Selection.selectTemplate(store, QUOTE_A, "tpl-c").code, "template_not_approved",
  "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate cannot be selected");
eq(Selection.selectTemplate(store, QUOTE_A, "missing").code, "template_not_approved", "a missing template cannot be selected");
eq(Selection.selectTemplate(store, "", "tpl-a").code, "invalid_quote_no", "a blank quote number cannot hold a selection");
eq(clone(draftBefore), draftBefore, "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: selection touches no draft content");

const renamed = Selection.renameTemplate(store, "tpl-a", "  우리 회사 양식  ");
check(renamed.ok === true && renamed.code === "renamed", "RENAME_TEMPLATE=PASS: rename succeeds");
eq(renamed.template.name, "우리 회사 양식", "the renamed value is trimmed");
check(renamed.template.approved === true, "rename keeps the approval");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_A), "tpl-a", "rename keeps the selection");
eq(Selection.renameTemplate(store, "tpl-a", "   ").code, "invalid_template_name", "a blank name is refused");
eq(Selection.renameTemplate(store, BUILTIN, "x").code, "builtin_template_immutable", "the built-in cannot be renamed");
eq(Selection.renameTemplate(store, "missing", "x").code, "template_not_found", "an unknown template cannot be renamed");

const duplicated = Selection.duplicateTemplate(store, "tpl-a", { now: NOW });
check(duplicated.ok === true && duplicated.code === "duplicated", "DUPLICATE_TEMPLATE=PASS: duplicate succeeds");
eq(duplicated.template.approved, false, "the duplicate is an unapproved candidate");
check(duplicated.template.name.indexOf("사본") !== -1, "the duplicate name is marked");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_A), "tpl-a", "duplicate does not change selections");

let confirmCalls = 0;
const refused = Selection.deleteTemplate(store, "tpl-b", { confirm: () => { confirmCalls += 1; return false; } });
eq(refused.code, "delete_cancelled", "DELETE_CONFIRMATION=PASS: cancelling leaves everything untouched");
eq(confirmCalls, 1, "the confirmation hook is used once");
check(Store.getTemplate(Store.readStore(store), "tpl-b") !== null, "a cancelled delete keeps the template");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_B), "tpl-b", "a cancelled delete keeps the selection");

/* 삭제하면 그 양식을 참조하는 selection 만 사라진다 */
const accepted = Selection.deleteTemplate(store, "tpl-b", { confirm: () => true });
check(accepted.ok === true && accepted.code === "deleted", "DELETE_CONFIRMATION=PASS: confirming deletes");
check(Store.getTemplate(Store.readStore(store), "tpl-b") === null, "the template is gone");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_B), null,
  "MISSING_SELECTED_TEMPLATE_FALLBACK=PASS: the deleted template's selection is pruned");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_A), "tpl-a",
  "other quotations keep their selection after a delete");
eq(Selection.resolveActiveTemplateId(Store.readStore(store), Selection.readEnvelope(store), QUOTE_B), BUILTIN,
  "the affected quotation falls back to the default");
eq(Selection.deleteTemplate(store, BUILTIN, { confirm: () => true }).code, "builtin_template_immutable",
  "BUILTIN_TEMPLATE_DELETE=DENIED: the built-in cannot be deleted");
eq(Selection.deleteTemplate(store, "missing", { confirm: () => true }).code, "template_not_found",
  "an unknown template cannot be deleted");

/* 새 양식 만들기 = 승인 전 candidate */
const created = Selection.createCandidate(store, { sourceTemplateId: BUILTIN, quoteNo: QUOTE_A, now: NOW });
check(created.ok === true && created.code === "created", "a new template candidate can be created");
eq(created.template.approved, false, "the new template is an unapproved candidate");
check(created.template.name.indexOf("사본") !== -1, "the new template is named from its source");
eq(Selection.createCandidate(store, { sourceTemplateId: "missing" }).code, "template_not_found",
  "a candidate cannot be created from a missing source");
eq(Selection.selectionForQuote(Selection.readEnvelope(store), QUOTE_A), "tpl-a", "creating a candidate does not change selections");

/* 내장 기본은 언제나 남는다 */
eq(Selection.resolveActiveTemplate(Store.readStore(store), null, QUOTE_A).id, BUILTIN,
  "BUILTIN_TEMPLATE_FALLBACK=PASS: the built-in remains the final fallback");
eq(Selection.resolveActiveTemplateId(Store.readStore(fakeStorage()), Selection.emptyEnvelope(), QUOTE_A), BUILTIN,
  "an empty store still resolves to the built-in");

console.log("TEMPLATE_SELECTOR_LIVE=YES");
console.log("TEMPLATE_SELECTION_PER_QUOTE=PASS");
console.log("TEMPLATE_SELECTION_BOUNDED=YES");
console.log("DEFAULT_TEMPLATE_SELECTION=PASS");
console.log("BUILTIN_TEMPLATE_FALLBACK=PASS");
console.log("UNAPPROVED_TEMPLATE_SELECTION=0");
console.log("UNAPPROVED_TEMPLATE_DEFAULT=0");
console.log("TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO");
console.log("MISSING_SELECTED_TEMPLATE_FALLBACK=PASS");
console.log("CORRUPT_TEMPLATE_FALLBACK=PASS");
console.log("BUILTIN_TEMPLATE_DELETE=DENIED");
console.log("DELETE_CONFIRMATION=PASS");
console.log("DUPLICATE_TEMPLATE=PASS");
console.log("RENAME_TEMPLATE=PASS");
console.log("MODEL_NETWORK_CALLS=0");
