const assert = require("node:assert");
const Template = require("../quote-template.js");
const Skill = require("../quote-skill.js");
const Store = require("../quote-skill-store.js");

const check = (condition, label) => assert.ok(condition, `contract failed: ${label}`);
const eq = (actual, expected, label) => assert.deepStrictEqual(actual, expected, `contract failed: ${label}`);
const NOW = "2026-09-29T11:00:00.000Z";

function fakeStorage() {
  const map = new Map();
  return {
    getItem: (key) => map.has(key) ? map.get(key) : null,
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key)
  };
}

function makeSkill(id, name) {
  const base = {
    id,
    name,
    fixedDefaults: {
      sender: { company: "한빛설비", rep: "김대표", bizNo: "123-45-67890", address: "광주", phone: "", email: "", presetId: "saved-skill" },
      validDays: 30,
      taxMode: "EXCLUSIVE",
      memo: "기본 비고"
    },
    variableSchema: { recipient: true, quoteNo: true, issueDate: true, items: true, memo: true, taxMode: true },
    internalTemplate: Template.serializeTemplate(Template.builtInTemplate()),
    provenance: { sourceKind: "file", sourceName: "quote.pdf", sourceRef: "source:x", capturedAt: NOW, warnings: [], unknowns: [], evidence: [] },
    approval: null,
    createdAt: NOW,
    updatedAt: NOW
  };
  const pending = Skill.buildSkill(base);
  return Skill.buildSkill(Object.assign({}, base, {
    approval: { schemaVersion: 1, status: "approved", skillFingerprint: pending.fingerprint, approvedBy: "central-cto", approvedAt: NOW, approvalRef: "issue-3218" }
  }));
}

const a = makeSkill("skill-a", "우리회사 일반 견적서");
const b = makeSkill("skill-b", "공사 견적서");
const storage = fakeStorage();

eq(Store.readStore(storage), Store.emptyStore(), "empty storage is safe");
let saved = Store.saveApprovedSkill(Store.emptyStore(), a);
check(saved.ok === true, "approved skill can be saved");
saved = Store.saveApprovedSkill(saved.store, b);
check(saved.ok === true, "a second approved skill can be saved");
eq(Store.listSkills(saved.store).length, 2, "MY_QUOTATION_LIST=PASS");

const pending = JSON.parse(JSON.stringify(a));
pending.approval = null;
eq(Store.saveApprovedSkill(saved.store, pending).code, "skill_not_approved", "UNAPPROVED_SAVED_QUOTE_SKILL_ACTIVATION=0");

const defaulted = Store.setDefaultSkill(saved.store, "skill-b");
check(defaulted.ok === true, "approved skill can become default");
eq(Store.defaultSkill(defaulted.store).id, "skill-b", "default skill is resolved");

const beforeFingerprint = Store.getSkill(defaulted.store, "skill-a").fingerprint;
const renamed = Store.renameSkill(defaulted.store, "skill-a", "우리회사 납품 견적서", { now: NOW });
check(renamed.ok === true, "MY_QUOTATION_RENAME=PASS");
eq(renamed.skill.name, "우리회사 납품 견적서", "renamed skill is visible");
eq(renamed.skill.fingerprint, beforeFingerprint, "renaming does not recompile or invalidate business behavior");

const removed = Store.deleteSkill(renamed.store, "skill-b");
check(removed.ok === true, "MY_QUOTATION_DELETE=PASS");
eq(Store.getSkill(removed.store, "skill-b"), null, "deleted skill is gone");
eq(Store.defaultSkill(removed.store), null, "deleting the default falls back safely to no Saved Quote Skill");

check(Store.writeStore(storage, removed.store) === true, "bounded local store can be persisted");
eq(Store.readStore(storage), Store.normalizeStore(removed.store), "persisted store round-trips");

storage.setItem(Store.STORAGE_KEY, "{broken");
eq(Store.readStore(storage), Store.emptyStore(), "corrupt store fails safe");
check(Store.clearStore(storage) === true, "skill store can be cleared without clearing unrelated origin data");

console.log("quote-skill-store contracts: PASS");
