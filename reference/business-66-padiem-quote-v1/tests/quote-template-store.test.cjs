const assert = require("node:assert");
const Template = require("../quote-template.js");
const Store = require("../quote-template-store.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-28T00:00:00.000Z";

const builtinContent = () => clone(Store.defaultTemplate(Store.emptyStore()).content);

function fakeStorage(initial) {
  const map = new Map();
  if (initial !== undefined) map.set(Store.TEMPLATE_STORAGE_KEY, initial);
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => { map.set(key, String(value)); },
    removeItem: (key) => { map.delete(key); },
    keys: () => Array.from(map.keys())
  };
}

function assertSingleDefault(store, label) {
  eq(Store.countDefaults(store), Store.DEFAULT_TEMPLATE_COUNT, `${label}: exactly one default`);
  const defaults = Store.listTemplates(store).filter((entry) => entry.isDefault);
  eq(defaults.length, 1, `${label}: one default entry`);
}

/* QUOTE_TEMPLATE_STORE_BOUNDED / QUOTE_TEMPLATE_DEFAULT_EXACTLY_ONE — 빈 저장소 */
eq(Store.MAX_TEMPLATES, 20, "bounded template count");
eq(Store.DEFAULT_TEMPLATE_COUNT, 1, "single default invariant constant");
check(Store.TEMPLATE_STORAGE_KEY.indexOf("quoteBeta") === 0, "storage key stays in the B66 quoteBeta namespace");

const empty = Store.emptyStore();
const emptyList = Store.listTemplates(empty);
eq(emptyList.length, 1, "empty store exposes only the built-in default");
eq(emptyList[0].id, Template.BUILTIN_TEMPLATE_ID, "empty store default is the built-in template");
eq(emptyList[0].builtin, true, "built-in flag is set");
eq(Store.defaultTemplateId(empty), Template.BUILTIN_TEMPLATE_ID, "defaultTemplateId falls back to built-in");
assertSingleDefault(empty, "empty store");
eq(Store.getTemplate(empty, Template.BUILTIN_TEMPLATE_ID).id, Template.BUILTIN_TEMPLATE_ID, "built-in is retrievable");
check(Store.getTemplate(empty, "missing") === null, "unknown template id returns null");

/* QUOTE_TEMPLATE_CRUD — create */
const created = Store.createTemplate(empty, { name: "우리 회사 양식", content: builtinContent() }, { id: "tpl-1", now: NOW });
check(created.ok === true, "create succeeds");
eq(created.store.templates.length, 1, "one user template stored");
eq(created.template.id, "tpl-1", "stable template id");
eq(created.template.name, "우리 회사 양식", "template name stored");
eq(created.template.isDefault, false, "new template is not the default");
check(/^[0-9a-f]{64}$/.test(created.template.fingerprint), "created template has a content fingerprint");
eq(created.template.fingerprint, Template.templateFingerprint(builtinContent()), "fingerprint derives from content");
eq(Store.listTemplates(created.store).length, 2, "list exposes built-in plus user template");
assertSingleDefault(created.store, "after create");
eq(Store.defaultTemplate(created.store).id, Template.BUILTIN_TEMPLATE_ID, "built-in stays default while no user default exists");

/* 저장된 user 템플릿은 내장 기본과 별개이며 원본 객체를 참조하지 않는다 */
const sourceContent = builtinContent();
const independent = Store.createTemplate(Store.emptyStore(), { name: "독립", content: sourceContent }, { id: "tpl-ind", now: NOW });
sourceContent.style.accent = "#ff0000";
check(independent.store.templates[0].content.style.accent === "#111827", "store deep-copies template content");
check(empty.templates.length === 0, "mutations never touch the original store (immutability)");
check(created.store.templates.length === 1, "create result is an independent store object");

/* 거부: 금지 필드 / 잘못된 content / 잘못된 id */
eq(Store.createTemplate(Store.emptyStore(), { name: "x", content: builtinContent(), subtotal: 1000 }).code,
  "forbidden_template_field", "trusted totals are refused on create");
eq(Store.createTemplate(Store.emptyStore(), { name: "x", content: builtinContent(), apiKey: "sk-1" }).code,
  "forbidden_template_field", "credentials are refused on create");
eq(Store.createTemplate(Store.emptyStore(), { name: "x", content: builtinContent(), rawBytes: "AAAA" }).code,
  "forbidden_template_field", "raw uploaded bytes are refused on create");
eq(Store.createTemplate(Store.emptyStore(), { name: "x", content: { schema: "nope" } }).code,
  "invalid_template_content", "invalid content is refused on create");
eq(Store.createTemplate(Store.emptyStore(), { name: "x", content: builtinContent() }, { id: Template.BUILTIN_TEMPLATE_ID }).code,
  "duplicate_template_id", "built-in id is reserved");
eq(Store.createTemplate(created.store, { name: "y", content: builtinContent() }, { id: "tpl-1" }).code,
  "duplicate_template_id", "duplicate id is refused");
check(Store.createTemplate(Store.emptyStore(), "nope").ok === false, "non-object input is refused");

/* QUOTE_TEMPLATE_STORE_BOUNDED — MAX 초과 생성 거부 */
let full = Store.emptyStore();
for (let i = 0; i < Store.MAX_TEMPLATES; i += 1) {
  const result = Store.createTemplate(full, { name: `템플릿 ${i}`, content: builtinContent() }, { id: `tpl-${i}`, now: NOW });
  check(result.ok === true, `bulk create #${i}`);
  full = result.store;
}
eq(Store.listTemplates(full).length, Store.MAX_TEMPLATES + 1, "bounded list size");
eq(Store.createTemplate(full, { name: "넘침", content: builtinContent() }, { id: "tpl-over", now: NOW }).code,
  "template_limit_reached", "create beyond MAX_TEMPLATES is refused");

/* QUOTE_TEMPLATE_CRUD — update */
const renamed = Store.updateTemplate(created.store, "tpl-1", { name: "수정된 양식" }, { now: "2026-09-28T01:00:00.000Z" });
check(renamed.ok === true, "update succeeds");
eq(renamed.template.name, "수정된 양식", "name updated");
eq(renamed.template.fingerprint, created.template.fingerprint, "name-only update keeps the fingerprint");
eq(renamed.template.createdAt, created.template.createdAt, "createdAt preserved");
check(renamed.template.updatedAt !== renamed.template.createdAt, "updatedAt advances");

const restyledContent = builtinContent();
restyledContent.style.accent = "#1d4ed8";
const restyled = Store.updateTemplate(created.store, "tpl-1", { content: restyledContent }, { now: NOW });
check(restyled.template.fingerprint !== created.template.fingerprint, "content update changes the fingerprint");
eq(Store.updateTemplate(created.store, "tpl-1", { content: builtinContent(), subtotal: 1 }).code,
  "forbidden_template_field", "update refuses trusted totals");
eq(Store.updateTemplate(created.store, Template.BUILTIN_TEMPLATE_ID, { name: "x" }).code,
  "builtin_template_immutable", "built-in cannot be updated");
eq(Store.updateTemplate(created.store, "missing", { name: "x" }).code,
  "template_not_found", "unknown template cannot be updated");
eq(Store.updateTemplate(created.store, "tpl-1", { content: { nope: true } }).code,
  "invalid_template_content", "invalid content update is refused");

/* QUOTE_TEMPLATE_DUPLICATE */
const duplicated = Store.duplicateTemplate(created.store, "tpl-1", { id: "tpl-copy", now: NOW });
check(duplicated.ok === true, "duplicate succeeds");
eq(duplicated.store.templates.length, 2, "duplicate adds a template");
eq(duplicated.template.id, "tpl-copy", "duplicate gets a new id");
eq(duplicated.template.fingerprint, created.template.fingerprint, "duplicate keeps the same content fingerprint");
eq(duplicated.template.isDefault, false, "duplicate is not the default");
check(duplicated.template.name.indexOf("사본") !== -1, "duplicate name is marked as a copy");
const builtinCopy = Store.duplicateTemplate(Store.emptyStore(), Template.BUILTIN_TEMPLATE_ID, { id: "tpl-from-builtin", now: NOW });
check(builtinCopy.ok === true, "built-in template can be copied");
eq(builtinCopy.template.fingerprint, Template.builtInTemplate().fingerprint, "built-in copy keeps the built-in fingerprint");
eq(Store.duplicateTemplate(created.store, "missing").code, "template_not_found", "unknown template cannot be duplicated");

/* QUOTE_TEMPLATE_DEFAULT_EXACTLY_ONE — 기본 지정과 강등 */
const asDefault = Store.setDefaultTemplate(duplicated.store, "tpl-copy");
check(asDefault.ok === true, "set default succeeds");
eq(Store.defaultTemplateId(asDefault.store), "tpl-copy", "user template becomes the default");
assertSingleDefault(asDefault.store, "after set default");

const backToBuiltin = Store.setDefaultTemplate(asDefault.store, Template.BUILTIN_TEMPLATE_ID);
eq(Store.defaultTemplateId(backToBuiltin.store), Template.BUILTIN_TEMPLATE_ID, "built-in can be restored as default");
assertSingleDefault(backToBuiltin.store, "after restoring built-in default");
check(backToBuiltin.store.templates.every((entry) => entry.isDefault === false), "restoring built-in clears user defaults");

/* 기본 템플릿 삭제 → 내장 기본으로 복구 (기본은 항상 존재) */
const deleted = Store.deleteTemplate(asDefault.store, "tpl-copy");
check(deleted.ok === true, "delete succeeds");
eq(deleted.store.templates.length, 1, "delete removes the template");
eq(Store.defaultTemplateId(deleted.store), Template.BUILTIN_TEMPLATE_ID, "deleting the default falls back to the built-in");
assertSingleDefault(deleted.store, "after deleting the default");
eq(Store.deleteTemplate(asDefault.store, Template.BUILTIN_TEMPLATE_ID).code,
  "builtin_template_immutable", "built-in cannot be deleted");
eq(Store.deleteTemplate(asDefault.store, "missing").code, "template_not_found", "unknown template cannot be deleted");

/* MALFORMED_TEMPLATE_STORAGE_FALLBACK — 손상 저장소는 내장 기본으로 복구 */
[
  null, undefined, "nope", 42, [], { schemaVersion: 99, templates: [] },
  { schemaVersion: 1, templates: "nope" },
  { schemaVersion: 1, templates: [null, 7, "x", {}, { schemaVersion: 9 }] },
  { templates: [] }
].forEach((raw, index) => {
  const normalized = Store.normalizeStore(raw);
  eq(normalized.templates.length, 0, `malformed store #${index} yields no templates`);
  eq(Store.defaultTemplateId(normalized), Template.BUILTIN_TEMPLATE_ID, `malformed store #${index} falls back to built-in`);
  assertSingleDefault(normalized, `malformed store #${index}`);
  check(Store.defaultTemplate(normalized) !== null, `malformed store #${index} always has a default`);
});

/* user 템플릿 직렬화본(내장 기본이 아님)을 손상 시나리오의 기준으로 쓴다 */
const userTemplateJson = Template.serializeTemplate(created.template);

/* 금지 필드를 담은 저장 항목은 조용히 버려진다 */
const leakyEntry = Object.assign(clone(userTemplateJson), { id: "leaky" });
leakyEntry.content = Object.assign(clone(leakyEntry.content), { subtotal: 1234 });
const leakyStore = Store.normalizeStore({ schemaVersion: 1, templates: [leakyEntry] });
eq(leakyStore.templates.length, 0, "stored entry carrying trusted totals is dropped");

/* 손상 지문 항목도 버려진다 */
const tamperedEntry = Object.assign(clone(userTemplateJson), { id: "tampered", fingerprint: "0".repeat(64) });
eq(Store.normalizeStore({ schemaVersion: 1, templates: [tamperedEntry] }).templates.length, 0, "tampered fingerprint entry is dropped");

/* user default 2개 → 정규화 후 정확히 1개 */
const doubleDefault = {
  schemaVersion: 1,
  templates: [
    Object.assign(clone(userTemplateJson), { id: "d1", isDefault: true }),
    Object.assign(clone(userTemplateJson), { id: "d2", isDefault: true })
  ]
};
const doubleFixed = Store.normalizeStore(doubleDefault);
eq(doubleFixed.templates.length, 2, "both templates survive");
eq(doubleFixed.templates.filter((entry) => entry.isDefault).length, 1, "duplicate defaults collapse to one");
assertSingleDefault(doubleFixed, "duplicate defaults");
eq(Store.defaultTemplateId(doubleFixed), "d1", "first declared default wins");

/* 내장 id 로 저장된 항목은 무시된다 + MAX 초과는 잘린다 + 중복 id 는 첫 항목만 */
const smuggledBuiltin = Object.assign(clone(userTemplateJson), { id: Template.BUILTIN_TEMPLATE_ID });
eq(Store.normalizeStore({ schemaVersion: 1, templates: [smuggledBuiltin] }).templates.length, 0, "built-in id is never stored");
check(Store.listTemplates({ schemaVersion: 1, templates: [smuggledBuiltin] }).length === 1, "built-in id entry leaves only the built-in default");

const many = [];
for (let i = 0; i < Store.MAX_TEMPLATES + 5; i += 1) {
  many.push(Object.assign(clone(userTemplateJson), { id: `bulk-${i}` }));
}
const overfull = Store.normalizeStore({ schemaVersion: 1, templates: many });
eq(overfull.templates.length, Store.MAX_TEMPLATES, "normalization truncates to MAX_TEMPLATES");
check(overfull.templates.every((entry) => entry.id !== Template.BUILTIN_TEMPLATE_ID), "built-in id is never stored");

const dupIds = Store.normalizeStore({
  schemaVersion: 1,
  templates: [
    Object.assign(clone(userTemplateJson), { id: "same" }),
    Object.assign(clone(userTemplateJson), { id: "same", name: "두번째" })
  ]
});
eq(dupIds.templates.length, 1, "duplicate ids collapse to the first entry");
eq(dupIds.templates[0].name, created.template.name, "first entry wins");

/* Storage 어댑터 */
const storage = fakeStorage();
check(Store.readStore(null).templates.length === 0, "readStore without storage is empty");
eq(Store.readStore(storage), Store.emptyStore(), "readStore on empty storage is an empty store");
check(Store.writeStore(storage, created.store) === true, "writeStore succeeds");
eq(Store.readStore(storage), Store.normalizeStore(Store.serializeStore(created.store)), "store round-trips through storage");
eq(Store.defaultTemplateId(Store.readStore(storage)), Template.BUILTIN_TEMPLATE_ID, "round-trip keeps exactly one default");

const corrupt = fakeStorage("{not json");
eq(Store.readStore(corrupt).templates.length, 0, "corrupt JSON falls back to an empty store");
eq(Store.defaultTemplateId(Store.readStore(corrupt)), Template.BUILTIN_TEMPLATE_ID, "corrupt JSON still has a default");
const wrongSchemaStorage = fakeStorage(JSON.stringify({ schemaVersion: 99, templates: [{ id: "x" }] }));
eq(Store.readStore(wrongSchemaStorage).templates.length, 0, "wrong stored schema version falls back");

check(Store.clearStore(storage) === true, "clearStore succeeds");
check(storage.keys().length === 0, "clearStore removes the template key");
check(Store.writeStore({}, created.store) === false, "writeStore without setItem reports failure");
check(Store.clearStore({}) === false, "clearStore without removeItem reports failure");

/* RAW_SOURCE_FILE_PERSISTENCE=0 / TRUSTED_TOTALS_IN_TEMPLATE=0 — 직렬화 결과에 남지 않는다 */
const serializedText = JSON.stringify(Store.serializeStore(duplicated.store));
["subtotal", "supply", "vat", "grand", "total", "rawBytes", "fileBytes", "dataUrl",
  "base64", "apiKey", "credential", "password", "provider_id", "model_id"
].forEach((key) => {
  check(serializedText.indexOf('"' + key + '":') === -1, `serialized store must not contain a ${key} field`);
});
check(serializedText.indexOf("data:") === -1, "serialized store must not contain embedded data URLs");
check(serializedText.indexOf(Template.BUILTIN_TEMPLATE_ID) === -1, "built-in template is never persisted");
check(serializedText.indexOf("quoteBeta") === -1, "storage namespace is not duplicated inside payloads");

console.log("QUOTE_TEMPLATE_STORE_BOUNDED=YES");
console.log("QUOTE_TEMPLATE_DEFAULT_EXACTLY_ONE=YES");
console.log("QUOTE_TEMPLATE_CRUD=PASS");
console.log("QUOTE_TEMPLATE_DUPLICATE=PASS");
console.log("MALFORMED_TEMPLATE_STORAGE_FALLBACK=PASS");
console.log("TEMPLATE_FINGERPRINT_DETERMINISTIC=PASS");
console.log("RAW_SOURCE_FILE_PERSISTENCE=0");
console.log("TRUSTED_TOTALS_IN_TEMPLATE=0");
console.log("MODEL_DEPENDENCY=0");
