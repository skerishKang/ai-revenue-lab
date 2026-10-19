const assert = require("node:assert");
const Template = require("../quote-template.js");
const Store = require("../quote-template-store.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) =>
  assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);

const clone = (value) => JSON.parse(JSON.stringify(value));
const NOW = "2026-09-28T00:00:00.000Z";
const LATER = "2026-09-28T09:00:00.000Z";
const BUILTIN = Template.BUILTIN_TEMPLATE_ID;

const builtinContent = () => clone(Store.defaultTemplate(Store.emptyStore()).content);
const FP = Template.templateFingerprint(builtinContent());
const evidence = (over) => Object.assign({
  schemaVersion: 1,
  status: "approved",
  contentFingerprint: FP,
  approvedBy: "central-cto",
  approvedAt: "2026-09-28T05:00:00Z"
}, over || {});

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
  check(defaults[0].approved === true, `${label}: the active default is an approved profile`);
}

/* QUOTE_TEMPLATE_STORE_BOUNDED / DEFAULT_EXACTLY_ONE — 빈 저장소 */
eq(Store.MAX_TEMPLATES, 20, "bounded template count");
eq(Store.DEFAULT_TEMPLATE_COUNT, 1, "single default invariant constant");
check(Store.TEMPLATE_STORAGE_KEY.indexOf("quoteBeta") === 0, "storage key stays in the B66 quoteBeta namespace");

const empty = Store.emptyStore();
eq(Store.listTemplates(empty).length, 1, "empty store exposes only the built-in default");
eq(Store.defaultTemplateId(empty), BUILTIN, "empty store default is the built-in template");
check(Store.defaultTemplate(empty).approved === true, "built-in default is approved by exception");
check(Store.defaultTemplate(empty).approvalBasis === "trusted_builtin", "built-in approval basis is explicit");
eq(Store.getTemplate(empty, BUILTIN).id, BUILTIN, "built-in is retrievable");
check(Store.getTemplate(empty, "missing") === null, "unknown template id returns null");
assertSingleDefault(empty, "empty store");

/* APPROVAL_REQUIRED_FOR_USER_PROFILE — 생성은 candidate 로만 저장된다 */
const created = Store.createTemplate(empty, { name: "우리 회사 양식", content: builtinContent() }, { id: "tpl-1", now: NOW });
check(created.ok === true, "create succeeds");
eq(created.store.templates.length, 1, "one user template stored");
eq(created.template.id, "tpl-1", "stable template id");
check(/^[0-9a-f]{64}$/.test(created.template.fingerprint), "created template has a content fingerprint");
eq(created.template.approved, false, "a fresh candidate is not approved");
eq(created.template.approvalBasis, "unapproved", "candidate records the unapproved basis");
eq(created.template.approval, null, "candidate carries no approval evidence");
eq(created.template.isDefault, false, "candidate is not the default");

/* UNAPPROVED_TEMPLATE_ACTIVATION=0 */
eq(Store.setDefaultTemplate(created.store, "tpl-1").code, "template_not_approved",
  "an unapproved candidate cannot become the default");
eq(Store.createTemplate(empty, { name: "x", content: builtinContent() }, { id: "d1", isDefault: true }).code,
  "template_not_approved", "create with isDefault and no approval is refused");
eq(Store.updateTemplate(created.store, "tpl-1", { isDefault: true }).code,
  "template_not_approved", "update to default without approval is refused");
eq(Store.defaultTemplateId(created.store), BUILTIN, "the built-in stays the active default");
assertSingleDefault(created.store, "after candidate create");

/* 저장된 user 템플릿은 내장 기본과 별개이며 원본 객체를 참조하지 않는다 */
const sourceContent = builtinContent();
const independent = Store.createTemplate(empty, { name: "독립", content: sourceContent }, { id: "tpl-ind", now: NOW });
sourceContent.style.accent = "#ff0000";
check(independent.store.templates[0].content.style.accent === "#17202a", "store deep-copies template content");
check(empty.templates.length === 0, "mutations never touch the original store (immutability)");
check(created.store.templates.length === 1, "create result is an independent store object");

/* APPROVED_TEMPLATE_SAVE_AND_RENDER — 명시적 승인만 활성화한다 */
const approved = Store.approveTemplate(created.store, "tpl-1", evidence(), { now: LATER });
check(approved.ok === true, "approve succeeds");
eq(approved.template.approved, true, "approved template is active-eligible");
eq(approved.template.approvalBasis, "explicit_approval", "explicit approval basis recorded");
eq(approved.template.fingerprint, created.template.fingerprint, "approval does not change the fingerprint");
eq(approved.template.approval.contentFingerprint, FP, "approval binds the content fingerprint");
eq(approved.template.approval.approvedBy, "central-cto", "approver reference is retained");
eq(approved.template.approval.approvedAt, "2026-09-28T05:00:00Z", "approval timestamp is retained");
check(Store.isTemplateApproved(approved.store, "tpl-1") === true, "isTemplateApproved reports true");

eq(Store.approveTemplate(created.store, BUILTIN, evidence()).code, "builtin_template_trusted",
  "the built-in template needs no approval");
eq(Store.approveTemplate(created.store, "missing", evidence()).code, "template_not_found",
  "unknown template cannot be approved");
[
  evidence({ contentFingerprint: "f".repeat(64) }),
  evidence({ status: "candidate" }),
  evidence({ schemaVersion: 9 }),
  evidence({ approvedBy: "" }),
  evidence({ approvedAt: "not-a-date" }),
  null
].forEach((bad, index) => {
  eq(Store.approveTemplate(created.store, "tpl-1", bad).code, "invalid_approval_evidence",
    `invalid approval evidence refused #${index}`);
});

const asDefault = Store.setDefaultTemplate(approved.store, "tpl-1");
check(asDefault.ok === true, "an approved template can become the default");
eq(Store.defaultTemplateId(asDefault.store), "tpl-1", "approved user template is the active default");
assertSingleDefault(asDefault.store, "after approved default");

/* 지문이 맞는 사전 승인 생성도 허용된다 */
const preApproved = Store.createTemplate(
  empty,
  { name: "사전 승인", content: builtinContent() },
  { id: "tpl-pre", isDefault: true, approval: evidence(), now: NOW }
);
check(preApproved.ok === true, "create with matching approval and isDefault succeeds");
eq(preApproved.template.approved, true, "pre-approved template is approved");
eq(preApproved.template.isDefault, true, "pre-approved template can be the default");
assertSingleDefault(preApproved.store, "pre-approved create");
eq(
  Store.createTemplate(empty, { name: "x", content: builtinContent() }, { id: "tpl-bad", approval: evidence({ contentFingerprint: "0".repeat(64) }) }).code,
  "invalid_approval_evidence",
  "create with mismatched approval evidence is refused"
);

/* CONTENT_CHANGE_INVALIDATES_APPROVAL */
const restyledContent = builtinContent();
restyledContent.style.accent = "#8a1f1f";
const restyled = Store.updateTemplate(asDefault.store, "tpl-1", { content: restyledContent }, { now: LATER });
check(restyled.ok === true, "content update succeeds");
eq(restyled.template.approval, null, "content update drops the previous approval");
eq(restyled.template.approved, false, "content update leaves the template unapproved");
eq(restyled.template.isDefault, false, "approval loss also drops the default status");
eq(Store.defaultTemplateId(restyled.store), BUILTIN, "the built-in default returns after approval loss");
assertSingleDefault(restyled.store, "after approval invalidation");
check(restyled.template.fingerprint !== created.template.fingerprint, "content update moves the fingerprint");

/* metadata(이름)만 바꾸면 승인은 유지된다 */
const renamed = Store.updateTemplate(asDefault.store, "tpl-1", { name: "수정된 양식" }, { now: LATER });
check(renamed.ok === true, "rename succeeds");
eq(renamed.template.name, "수정된 양식", "name updated");
eq(renamed.template.approved, true, "rename keeps the approval");
eq(renamed.template.fingerprint, created.template.fingerprint, "rename keeps the fingerprint");
eq(renamed.template.isDefault, true, "approved default survives a rename");
eq(renamed.template.createdAt, created.template.createdAt, "createdAt preserved");
check(renamed.template.updatedAt !== renamed.template.createdAt, "updatedAt advances");
assertSingleDefault(renamed.store, "after rename");

/* 거부: 금지 필드 / 잘못된 content / 잘못된 id / built-in */
eq(Store.createTemplate(empty, { name: "x", content: builtinContent(), subtotal: 1000 }).code,
  "forbidden_template_field", "trusted totals are refused on create");
eq(Store.createTemplate(empty, { name: "x", content: builtinContent(), apiKey: "sk-1" }).code,
  "forbidden_template_field", "credentials are refused on create");
eq(Store.createTemplate(empty, { name: "x", content: builtinContent(), rawBytes: "AAAA" }).code,
  "forbidden_template_field", "raw uploaded bytes are refused on create");
eq(Store.createTemplate(empty, { name: "x", content: { schema: "nope" } }).code,
  "invalid_template_content", "invalid content is refused on create");
eq(Store.createTemplate(empty, { name: "x", content: builtinContent() }, { id: BUILTIN }).code,
  "duplicate_template_id", "built-in id is reserved");
eq(Store.createTemplate(approved.store, { name: "y", content: builtinContent() }, { id: "tpl-1" }).code,
  "duplicate_template_id", "duplicate id is refused");
check(Store.createTemplate(empty, "nope").ok === false, "non-object input is refused");
eq(Store.updateTemplate(asDefault.store, "tpl-1", { content: builtinContent(), subtotal: 1 }).code,
  "forbidden_template_field", "update refuses trusted totals");
eq(Store.updateTemplate(asDefault.store, BUILTIN, { name: "x" }).code,
  "builtin_template_immutable", "built-in cannot be updated");
eq(Store.updateTemplate(asDefault.store, "missing", { name: "x" }).code,
  "template_not_found", "unknown template cannot be updated");
eq(Store.updateTemplate(asDefault.store, "tpl-1", { content: { nope: true } }).code,
  "invalid_template_content", "invalid content update is refused");

/* SLOT_BEHAVIOR — private assets require account-bound Saved Quote Skill authority */
const logoAssetId = "b66asset_" + "a".repeat(32);
const stampAssetId = "b66asset_" + "b".repeat(32);
const slotContent = builtinContent();
slotContent.slots = { logo: logoAssetId, stamp: "" };
eq(Store.createTemplate(empty, { name: "slot", content: slotContent }, { id: "tpl-slot" }).code,
  "private_asset_requires_account_skill", "browser-local template cannot own a private logo ref");
eq(Store.updateTemplate(asDefault.store, "tpl-1", { content: slotContent }).code,
  "private_asset_requires_account_skill", "browser-local update cannot activate a private logo ref");
const stampContent = clone(builtinContent());
stampContent.slots = { logo: "", stamp: stampAssetId };
eq(Store.createTemplate(empty, { name: "stamp", content: stampContent }, { id: "tpl-stamp" }).code,
  "private_asset_requires_account_skill", "browser-local template cannot own a private stamp ref");

/* QUOTE_TEMPLATE_DUPLICATE — 복제본은 다시 승인받아야 하는 candidate 다 */
const duplicated = Store.duplicateTemplate(asDefault.store, "tpl-1", { id: "tpl-copy", now: LATER });
check(duplicated.ok === true, "duplicate succeeds");
eq(duplicated.template.fingerprint, created.template.fingerprint, "duplicate keeps the content fingerprint");
eq(duplicated.template.approved, false, "duplicate is an unapproved candidate");
eq(duplicated.template.isDefault, false, "duplicate is not the default");
check(duplicated.template.name.indexOf("사본") !== -1, "duplicate name is marked as a copy");
eq(Store.setDefaultTemplate(duplicated.store, "tpl-copy").code, "template_not_approved",
  "the duplicated candidate cannot be activated without approval");
const builtinCopy = Store.duplicateTemplate(empty, BUILTIN, { id: "tpl-from-builtin", now: LATER });
check(builtinCopy.ok === true, "built-in template can be copied");
eq(builtinCopy.template.approved, false, "the built-in copy is an unapproved candidate");
eq(builtinCopy.template.fingerprint, Template.builtInTemplate().fingerprint, "copy keeps the built-in fingerprint");
eq(Store.duplicateTemplate(asDefault.store, "missing").code, "template_not_found", "unknown template cannot be duplicated");

/* 기본 템플릿 삭제 → 내장 기본으로 복구 (기본은 항상 존재) */
const deleted = Store.deleteTemplate(asDefault.store, "tpl-1");
check(deleted.ok === true, "delete succeeds");
eq(deleted.store.templates.length, 0, "delete removes the template");
eq(Store.defaultTemplateId(deleted.store), BUILTIN, "deleting the default falls back to the built-in");
assertSingleDefault(deleted.store, "after deleting the default");
eq(Store.deleteTemplate(asDefault.store, BUILTIN).code, "builtin_template_immutable", "built-in cannot be deleted");
eq(Store.deleteTemplate(asDefault.store, "missing").code, "template_not_found", "unknown template cannot be deleted");

/* 내장 기본으로 되돌리기 */
const backToBuiltin = Store.setDefaultTemplate(asDefault.store, BUILTIN);
eq(Store.defaultTemplateId(backToBuiltin.store), BUILTIN, "built-in can be restored as default");
assertSingleDefault(backToBuiltin.store, "after restoring built-in default");
check(backToBuiltin.store.templates.every((entry) => entry.isDefault === false), "restoring built-in clears user defaults");

/* QUOTE_TEMPLATE_STORE_BOUNDED — MAX 초과 생성 거부 / 정규화 절단 */
let full = Store.emptyStore();
for (let i = 0; i < Store.MAX_TEMPLATES; i += 1) {
  const result = Store.createTemplate(full, { name: `템플릿 ${i}`, content: builtinContent() }, { id: `tpl-${i}`, now: NOW });
  check(result.ok === true, `bulk create #${i}`);
  full = result.store;
}
eq(Store.listTemplates(full).length, Store.MAX_TEMPLATES + 1, "bounded list size");
eq(Store.createTemplate(full, { name: "넘침", content: builtinContent() }, { id: "tpl-over", now: NOW }).code,
  "template_limit_reached", "create beyond MAX_TEMPLATES is refused");

/* MALFORMED_TEMPLATE_STORAGE_FALLBACK */
[
  null, undefined, "nope", 42, [], { schemaVersion: 99, templates: [] },
  { schemaVersion: 1, templates: "nope" },
  { schemaVersion: 1, templates: [null, 7, "x", {}, { schemaVersion: 9 }] },
  { templates: [] }
].forEach((raw, index) => {
  const normalized = Store.normalizeStore(raw);
  eq(normalized.templates.length, 0, `malformed store #${index} yields no templates`);
  eq(Store.defaultTemplateId(normalized), BUILTIN, `malformed store #${index} falls back to built-in`);
  assertSingleDefault(normalized, `malformed store #${index}`);
});

/* 저장 항목 수준의 방어 */
const userJson = Template.serializeTemplate(Store.getTemplate(approved.store, "tpl-1"));

const leakyEntry = Object.assign(clone(userJson), { id: "leaky" });
leakyEntry.content = Object.assign(clone(leakyEntry.content), { subtotal: 1234 });
eq(Store.normalizeStore({ schemaVersion: 1, templates: [leakyEntry] }).templates.length, 0,
  "stored entry carrying trusted totals is dropped");

const tamperedEntry = Object.assign(clone(userJson), { id: "tampered", fingerprint: "0".repeat(64) });
eq(Store.normalizeStore({ schemaVersion: 1, templates: [tamperedEntry] }).templates.length, 0,
  "tampered fingerprint entry is dropped");

/* 승인 지문이 내용과 어긋나면 승인만 버리고 후보로 남긴다 */
const restyledJson = clone(userJson);
restyledJson.content = Object.assign(clone(restyledJson.content), { style: Object.assign({}, restyledJson.content.style, { accent: "#004400" }) });
restyledJson.fingerprint = Template.templateFingerprint(restyledJson.content);
const staleStore = Store.normalizeStore({ schemaVersion: 1, templates: [restyledJson] });
eq(staleStore.templates.length, 1, "the stale-approval entry is kept as a candidate");
eq(staleStore.templates[0].approval, null, "the stale approval is dropped");
eq(Store.defaultTemplateId(staleStore), BUILTIN, "a stale-approval entry cannot be the default");

/* 저장 항목이 default 라고 주장해도 미승인이면 무시된다 */
const unapprovedDefaultJson = clone(userJson);
unapprovedDefaultJson.approval = null;
unapprovedDefaultJson.isDefault = true;
const unapprovedStore = Store.normalizeStore({ schemaVersion: 1, templates: [unapprovedDefaultJson] });
eq(unapprovedStore.templates[0].isDefault, false, "an unapproved stored default is demoted");
eq(Store.defaultTemplateId(unapprovedStore), BUILTIN, "unapproved stored default falls back to built-in");
assertSingleDefault(unapprovedStore, "unapproved stored default");

/* user default 2개 → 정규화 후 정확히 1개 */
const doubleDefault = {
  schemaVersion: 1,
  templates: [
    Object.assign(clone(userJson), { id: "d1", isDefault: true }),
    Object.assign(clone(userJson), { id: "d2", isDefault: true })
  ]
};
const doubleFixed = Store.normalizeStore(doubleDefault);
eq(doubleFixed.templates.length, 2, "both templates survive");
eq(doubleFixed.templates.filter((entry) => entry.isDefault).length, 1, "duplicate defaults collapse to one");
assertSingleDefault(doubleFixed, "duplicate defaults");
eq(Store.defaultTemplateId(doubleFixed), "d1", "first declared default wins");

/* 내장 id 로 저장된 항목은 무시된다 + 중복 id 는 첫 항목만 */
const smuggledBuiltin = Object.assign(clone(userJson), { id: BUILTIN });
eq(Store.normalizeStore({ schemaVersion: 1, templates: [smuggledBuiltin] }).templates.length, 0, "built-in id is never stored");
check(Store.listTemplates({ schemaVersion: 1, templates: [smuggledBuiltin] }).length === 1,
  "built-in id entry leaves only the built-in default");

const dupIds = Store.normalizeStore({
  schemaVersion: 1,
  templates: [
    Object.assign(clone(userJson), { id: "same" }),
    Object.assign(clone(userJson), { id: "same", name: "두번째" })
  ]
});
eq(dupIds.templates.length, 1, "duplicate ids collapse to the first entry");
eq(dupIds.templates[0].name, userJson.name, "first entry wins");

/* FORGED_BUILTIN_FLAG_BYPASS=0 — builtin 플래그로 승인/기본을 우회할 수 없다 */
const forgedEntry = {
  schemaVersion: 1, id: "user-forged", name: "forged", builtin: true, isDefault: true, approval: null,
  createdAt: NOW, updatedAt: NOW,
  fingerprint: Template.BUILTIN_TEMPLATE_FINGERPRINT, content: builtinContent()
};
const forgedStore = Store.normalizeStore({ schemaVersion: 1, templates: [forgedEntry] });
eq(forgedStore.templates.length, 1, "a forged builtin claim is kept only as a candidate");
eq(forgedStore.templates[0].isDefault, false, "a forged builtin claim cannot become the default");
eq(forgedStore.templates[0].approval, null, "a forged builtin claim carries no approval");
eq(Store.isTemplateApproved(forgedStore, "user-forged"), false, "a forged builtin claim is not approved");
eq(Store.defaultTemplateId(forgedStore), BUILTIN, "CANONICAL_BUILTIN_FALLBACK: the canonical built-in is the default");
assertSingleDefault(forgedStore, "forged builtin claim");
eq(Store.setDefaultTemplate(forgedStore, "user-forged").code, "template_not_approved",
  "a forged builtin claim cannot be activated");
eq(Store.updateTemplate(forgedStore, "user-forged", { isDefault: true }).code, "template_not_approved",
  "a forged builtin claim cannot be promoted by update");

const forgedCanonicalIdRaw = Object.assign({}, forgedEntry, { id: BUILTIN });
eq(Store.normalizeStore({ schemaVersion: 1, templates: [forgedCanonicalIdRaw] }).templates.length, 0,
  "the canonical built-in id is never storable even with a forged flag");
eq(Store.defaultTemplate(Store.normalizeStore({ schemaVersion: 1, templates: [forgedCanonicalIdRaw] })).id, BUILTIN,
  "CANONICAL_BUILTIN_FALLBACK: the synthesized canonical built-in remains the fallback");

/* Storage 어댑터 — 승인 증거까지 왕복한다 */
const storage = fakeStorage();
check(Store.readStore(null).templates.length === 0, "readStore without storage is empty");
eq(Store.readStore(storage), Store.emptyStore(), "readStore on empty storage is an empty store");
check(Store.writeStore(storage, asDefault.store) === true, "writeStore succeeds");
eq(Store.readStore(storage), Store.normalizeStore(Store.serializeStore(asDefault.store)), "store round-trips through storage");
eq(Store.defaultTemplateId(Store.readStore(storage)), "tpl-1", "the approved default survives the round trip");
check(Store.readStore(storage).templates[0].approval !== null, "approval evidence survives the round trip");
assertSingleDefault(Store.readStore(storage), "round trip");

const corrupt = fakeStorage("{not json");
eq(Store.readStore(corrupt).templates.length, 0, "corrupt JSON falls back to an empty store");
eq(Store.defaultTemplateId(Store.readStore(corrupt)), BUILTIN, "corrupt JSON still has a default");
const wrongSchemaStorage = fakeStorage(JSON.stringify({ schemaVersion: 99, templates: [{ id: "x" }] }));
eq(Store.readStore(wrongSchemaStorage).templates.length, 0, "wrong stored schema version falls back");

check(Store.clearStore(storage) === true, "clearStore succeeds");
check(storage.keys().length === 0, "clearStore removes the template key");
check(Store.writeStore({}, asDefault.store) === false, "writeStore without setItem reports failure");
check(Store.clearStore({}) === false, "clearStore without removeItem reports failure");

/* RAW_SOURCE_FILE_PERSISTENCE=0 / TRUSTED_TOTALS_IN_TEMPLATE=0 — 직렬화 결과 */
const serializedText = JSON.stringify(Store.serializeStore(asDefault.store));
["subtotal", "supply", "vat", "grand", "total", "rawBytes", "fileBytes", "dataUrl",
  "base64", "apiKey", "credential", "password", "provider_id", "model_id"
].forEach((key) => {
  check(serializedText.indexOf('"' + key + '":') === -1, `serialized store must not contain a ${key} field`);
});
check(serializedText.indexOf("data:") === -1, "serialized store must not contain embedded data URLs");
check(serializedText.indexOf(BUILTIN) === -1, "built-in template is never persisted");
check(serializedText.indexOf("quoteBeta") === -1, "storage namespace is not duplicated inside payloads");

/* 승인 증거도 bounded 이며 민감 키를 담지 않는다 */
const storedApproval = Store.serializeStore(asDefault.store).templates[0].approval;
check(storedApproval !== null, "approval evidence is persisted for approved templates");
eq(Template.findForbiddenKeys(storedApproval), [], "approval evidence carries no forbidden fields");
check(storedApproval.approvedBy.length <= Template.MAX_APPROVER_REF_CHARS, "approver reference is bounded");
check(storedApproval.contentFingerprint === Template.templateFingerprint(asDefault.store.templates[0].content),
  "persisted approval is bound to the persisted content");

console.log("QUOTE_TEMPLATE_STORE_BOUNDED=YES");
console.log("QUOTE_TEMPLATE_DEFAULT_EXACTLY_ONE=YES");
console.log("QUOTE_TEMPLATE_CRUD=PASS");
console.log("QUOTE_TEMPLATE_DUPLICATE=PASS");
console.log("MALFORMED_TEMPLATE_STORAGE_FALLBACK=PASS");
console.log("TEMPLATE_FINGERPRINT_DETERMINISTIC=PASS");
console.log("APPROVAL_REQUIRED_FOR_USER_PROFILE=YES");
console.log("UNAPPROVED_TEMPLATE_ACTIVATION=0");
console.log("FORGED_BUILTIN_FLAG_BYPASS=0");
console.log("CANONICAL_BUILTIN_FALLBACK=PASS");
console.log("CONTENT_CHANGE_INVALIDATES_APPROVAL=YES");
console.log("APPROVED_TEMPLATE_SAVE_AND_RENDER=PASS");
console.log("SLOT_BEHAVIOR=PRIVATE_ASSET_REF_V1");
console.log("RAW_SOURCE_FILE_PERSISTENCE=0");
console.log("TRUSTED_TOTALS_IN_TEMPLATE=0");
console.log("MODEL_DEPENDENCY=0");