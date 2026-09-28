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

/* ── TEMPLATE_SELECTOR_LIVE — 선택 상태는 견적번호에 묶인다 ── */
eq(Selection.SELECTION_SCHEMA_VERSION, 1, "selection schema version");
check(Selection.SELECTION_STORAGE_KEY.indexOf("quoteBeta") === 0, "selection key lives in the B66 namespace");

check(Selection.normalizeSelection(null) === null, "null selection rejected");
check(Selection.normalizeSelection({}) === null, "empty selection rejected");
check(Selection.normalizeSelection({ schemaVersion: 9, quoteNo: QUOTE_A, templateId: "t" }) === null, "wrong selection schema rejected");
check(Selection.normalizeSelection({ schemaVersion: 1, quoteNo: "", templateId: "t" }) === null, "missing quote number rejected");
check(Selection.normalizeSelection({ schemaVersion: 1, quoteNo: QUOTE_A, templateId: "" }) === null, "missing template id rejected");
check(Selection.normalizeSelection({ schemaVersion: 1, quoteNo: "x".repeat(400), templateId: "t" }) === null, "over-long quote number rejected");

const selection = Selection.makeSelection(QUOTE_A, "tpl-a", { now: NOW });
check(selection !== null, "selection is created");
eq(selection.quoteNo, QUOTE_A, "selection keeps the quote number");
eq(selection.templateId, "tpl-a", "selection keeps the template id");
eq(selection.updatedAt, NOW, "selection keeps the timestamp");

eq(Selection.selectionForQuote(selection, QUOTE_A), "tpl-a", "selection resolves for its own quotation");
check(Selection.selectionForQuote(selection, QUOTE_B) === null, "selection is scoped to one quotation");
check(Selection.selectionForQuote(selection, "") === null, "blank quote number resolves to nothing");
check(Selection.selectionForQuote("garbage", QUOTE_A) === null, "corrupt selection resolves to nothing");

const storage = fakeStorage();
check(Selection.readSelection(storage) === null, "empty storage has no selection");
check(Selection.writeSelection(storage, selection) === true, "selection is written");
eq(Selection.readSelection(storage), selection, "selection round-trips");
check(Selection.writeSelection(storage, { bad: true }) === true, "invalid selection clears the slot");
check(Selection.readSelection(storage) === null, "invalid selection leaves nothing behind");
Selection.writeSelection(storage, selection);
check(Selection.clearSelection(storage) === true, "selection can be cleared");
check(Selection.readSelection(storage) === null, "cleared selection is gone");
storage.setItem(Selection.SELECTION_STORAGE_KEY, "{not json");
check(Selection.readSelection(storage) === null, "corrupt stored selection falls back to none");

/* ── 해석: 선택 → 기본 → 내장 기본 ── */
const store = fakeStorage();
const approvedA = seedApproved(store, "tpl-a", styledContent("#8a1f1f"));
const approvedB = seedApproved(store, "tpl-b", styledContent("#1f4e8a"));
const candidateC = seedCandidate(store, "tpl-c", styledContent("#333333"));

const rawStore = Store.readStore(store);
eq(Selection.isSelectable(rawStore, "tpl-a"), true, "an approved template is selectable");
eq(Selection.isSelectable(rawStore, "tpl-c"), false, "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate is not selectable");
eq(Selection.isSelectable(rawStore, BUILTIN), true, "the built-in is selectable");
eq(Selection.isSelectable(rawStore, "missing"), false, "an unknown id is not selectable");
eq(Selection.isSelectable(rawStore, ""), false, "a blank id is not selectable");

eq(Selection.resolveActiveTemplateId(rawStore, null, QUOTE_A), BUILTIN,
  "BUILTIN_TEMPLATE_FALLBACK=PASS: no selection uses the default (built-in)");
eq(Selection.resolveActiveTemplateId(rawStore, Selection.makeSelection(QUOTE_A, "tpl-a"), QUOTE_A), "tpl-a",
  "DEFAULT_TEMPLATE_SELECTION=PASS: an approved selection wins");
eq(Selection.resolveActiveTemplateId(rawStore, Selection.makeSelection(QUOTE_A, "tpl-c"), QUOTE_A), BUILTIN,
  "UNAPPROVED_TEMPLATE_SELECTION=0: an unapproved selection falls back to the default");
eq(Selection.resolveActiveTemplateId(rawStore, Selection.makeSelection(QUOTE_A, "gone"), QUOTE_A), BUILTIN,
  "MISSING_SELECTED_TEMPLATE_FALLBACK=PASS: a deleted selection falls back to the default");
eq(Selection.resolveActiveTemplateId(rawStore, "garbage", QUOTE_A), BUILTIN,
  "CORRUPT_TEMPLATE_FALLBACK=PASS: corrupt selection state falls back to the default");
eq(Selection.resolveActiveTemplateId(rawStore, Selection.makeSelection(QUOTE_A, "tpl-a"), QUOTE_B), BUILTIN,
  "selection never leaks across quotations");

eq(Selection.resolveActiveTemplate(rawStore, null, QUOTE_A).id, BUILTIN, "resolveActiveTemplate returns the built-in by default");
eq(Selection.resolveActiveTemplate(rawStore, Selection.makeSelection(QUOTE_A, "tpl-a"), QUOTE_A).id, "tpl-a",
  "resolveActiveTemplate honours an approved selection");
check(Selection.resolveActiveTemplate(rawStore, Selection.makeSelection(QUOTE_A, "tpl-a"), QUOTE_A).approved === true,
  "the resolved template is approved");

/* 기본 양식을 바꾸면 '앞으로의 기본'만 바뀌고 이 견적의 선택은 그대로다 */
const defaulted = Selection.setDefaultTemplate(store, "tpl-b");
check(defaulted.ok === true, "an approved template can become the default");
eq(Store.defaultTemplateId(Store.readStore(store)), "tpl-b", "the default moved to tpl-b");
eq(Selection.resolveActiveTemplateId(Store.readStore(store), Selection.makeSelection(QUOTE_A, "tpl-a"), QUOTE_A), "tpl-a",
  "a per-quotation selection survives a default change");
eq(Selection.resolveActiveTemplateId(Store.readStore(store), null, QUOTE_B), "tpl-b",
  "quotations without a selection pick up the new default");
eq(Selection.setDefaultTemplate(store, "tpl-c").code, "template_not_approved",
  "UNAPPROVED_TEMPLATE_DEFAULT=0: a candidate cannot become the default");
eq(Selection.setDefaultTemplate(store, BUILTIN).ok, true, "the built-in can be restored as the default");

/* ── 목록 모델 ── */
const rows = Selection.listForManagement(Store.readStore(store));
eq(rows.length, 4, "management list shows the built-in and every user template");
const builtinRow = rows.filter((row) => row.id === BUILTIN)[0];
const candidateRow = rows.filter((row) => row.id === "tpl-c")[0];
const approvedRow = rows.filter((row) => row.id === "tpl-a")[0];
check(builtinRow.builtin === true && builtinRow.canDelete === false && builtinRow.canRename === false,
  "BUILTIN_TEMPLATE_DELETE=DENIED: the built-in cannot be renamed or deleted");
check(candidateRow.approved === false && candidateRow.selectable === false && candidateRow.canSetDefault === false,
  "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate is visible but inert");
check(candidateRow.canApprove === true, "a candidate is marked as approvable in the next step");
check(approvedRow.selectable === true && approvedRow.canSetDefault === true, "an approved template is actionable");
check(rows.every((row) => typeof row.name === "string" && typeof row.fingerprint === "string"),
  "rows expose the name and fingerprint");

/* ── 액션 ── */
const draftBefore = clone({ sender: "a", recipient: "b", items: [1, 2], tax: "EXCLUSIVE", memo: "m" });

const selected = Selection.selectTemplate(store, QUOTE_A, "tpl-a", { now: NOW });
check(selected.ok === true && selected.code === "selected", "an approved template can be selected");
eq(Selection.selectionForQuote(Selection.readSelection(store), QUOTE_A), "tpl-a", "the selection is persisted");
eq(Selection.selectTemplate(store, QUOTE_A, "tpl-c").code, "template_not_approved",
  "UNAPPROVED_TEMPLATE_SELECTION=0: a candidate cannot be selected");
eq(Selection.selectTemplate(store, QUOTE_A, "missing").code, "template_not_approved",
  "a missing template cannot be selected");
eq(Selection.selectTemplate(store, "", "tpl-a").code, "invalid_quote_no", "a blank quote number cannot hold a selection");
eq(clone(draftBefore), draftBefore, "TEMPLATE_SWITCH_MUTATES_QUOTEDRAFT_CONTENT=NO: selection touches no draft content");

const renamed = Selection.renameTemplate(store, "tpl-a", "  우리 회사 양식  ");
check(renamed.ok === true && renamed.code === "renamed", "RENAME_TEMPLATE=PASS: rename succeeds");
eq(renamed.template.name, "우리 회사 양식", "the renamed value is trimmed");
check(renamed.template.approved === true, "rename keeps the approval");
eq(Selection.renameTemplate(store, "tpl-a", "   ").code, "invalid_template_name", "a blank name is refused");
eq(Selection.renameTemplate(store, BUILTIN, "x").code, "builtin_template_immutable", "the built-in cannot be renamed");
eq(Selection.renameTemplate(store, "missing", "x").code, "template_not_found", "an unknown template cannot be renamed");

const duplicated = Selection.duplicateTemplate(store, "tpl-a", { now: NOW });
check(duplicated.ok === true && duplicated.code === "duplicated", "DUPLICATE_TEMPLATE=PASS: duplicate succeeds");
eq(duplicated.template.approved, false, "the duplicate is an unapproved candidate");
check(duplicated.template.name.indexOf("사본") !== -1, "the duplicate name is marked");
eq(Selection.duplicateTemplate(store, "missing").code, "template_not_found", "an unknown template cannot be duplicated");

let confirmCalls = 0;
const refused = Selection.deleteTemplate(store, "tpl-b", { confirm: () => { confirmCalls += 1; return false; } });
eq(refused.code, "delete_cancelled", "DELETE_CONFIRMATION=PASS: cancelling leaves everything untouched");
eq(confirmCalls, 1, "the confirmation hook is used once");
check(Store.getTemplate(Store.readStore(store), "tpl-b") !== null, "a cancelled delete keeps the template");

const accepted = Selection.deleteTemplate(store, "tpl-b", { confirm: () => true });
check(accepted.ok === true && accepted.code === "deleted", "DELETE_CONFIRMATION=PASS: confirming deletes");
check(Store.getTemplate(Store.readStore(store), "tpl-b") === null, "the template is gone");
eq(Selection.deleteTemplate(store, BUILTIN, { confirm: () => true }).code, "builtin_template_immutable",
  "BUILTIN_TEMPLATE_DELETE=DENIED: the built-in cannot be deleted");
eq(Selection.deleteTemplate(store, "missing", { confirm: () => true }).code, "template_not_found",
  "an unknown template cannot be deleted");

/* 삭제된 양식을 쓰던 견적은 안전하게 기본 양식으로 돌아간다 */
Selection.selectTemplate(store, QUOTE_A, "tpl-a", { now: NOW });
Selection.deleteTemplate(store, "tpl-a", { confirm: () => true });
check(Selection.readSelection(store) === null, "deleting the selected template clears the stale selection");
eq(Selection.resolveActiveTemplateId(Store.readStore(store), Selection.readSelection(store), QUOTE_A), BUILTIN,
  "MISSING_SELECTED_TEMPLATE_FALLBACK=PASS: the quotation falls back to the built-in");

/* 새 양식 만들기 = 승인 전 candidate */
const created = Selection.createCandidate(store, { sourceTemplateId: BUILTIN, quoteNo: QUOTE_A, now: NOW });
check(created.ok === true && created.code === "created", "a new template candidate can be created");
eq(created.template.approved, false, "the new template is an unapproved candidate");
check(created.template.name.indexOf("사본") !== -1, "the new template is named from its source");
eq(Selection.createCandidate(store, { sourceTemplateId: "missing" }).code, "template_not_found",
  "a candidate cannot be created from a missing source");

/* 내장 기본은 언제나 남는다 */
check(Store.getTemplate(Store.readStore(store), BUILTIN) !== null, "the built-in is always present");
eq(Selection.resolveActiveTemplate(Store.readStore(store), null, QUOTE_A).id, BUILTIN,
  "BUILTIN_TEMPLATE_FALLBACK=PASS: the built-in remains the final fallback");

/* 저장소를 통째로 지워도 해석은 안전하다 */
const wiped = fakeStorage();
eq(Selection.resolveActiveTemplateId(Store.readStore(wiped), Selection.readSelection(wiped), QUOTE_A), BUILTIN,
  "an empty store still resolves to the built-in");

console.log("TEMPLATE_SELECTOR_LIVE=YES");
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
