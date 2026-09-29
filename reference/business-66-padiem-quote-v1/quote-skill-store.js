/* B66 · Quote Beta — quote-skill-store.js
   승인된 Saved Quote Skill("내 견적서") 전용 bounded browser-local store.

   - raw uploaded source bytes are never stored here.
   - unapproved Skill cannot be persisted or activated.
   - default Skill is optional; absence means the built-in quotation fallback remains available.
   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-skill.js"));
  } else {
    root.SavedQuoteSkillStore = factory(root.SavedQuoteSkill);
  }
})(typeof self !== "undefined" ? self : this, function (Skill) {
  "use strict";

  if (!Skill) throw new Error("SavedQuoteSkill is required");

  var STORE_SCHEMA_VERSION = 1;
  var STORAGE_KEY = "quoteBetaSavedSkill.v1";
  var MAX_SKILLS = 20;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function emptyStore() {
    return { schemaVersion: STORE_SCHEMA_VERSION, defaultSkillId: null, skills: [] };
  }

  function fail(code, message) {
    return { ok: false, code: code, message: message || null, store: null, skill: null };
  }

  function ok(code, store, skill, extra) {
    return Object.assign({ ok: true, code: code, message: null, store: store, skill: skill || null }, extra || {});
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function normalizeStore(raw) {
    if (!isPlainObject(raw) || raw.schemaVersion !== STORE_SCHEMA_VERSION || !Array.isArray(raw.skills)) {
      return emptyStore();
    }
    var skills = [];
    var seen = Object.create(null);
    raw.skills.slice(0, MAX_SKILLS).forEach(function (entry) {
      var skill = Skill.normalizeSkill(entry);
      if (!skill || skill.approved !== true || seen[skill.id]) return;
      seen[skill.id] = true;
      skills.push(Skill.serializeSkill(skill));
    });
    var defaultSkillId = Skill.normalizeSkillId(raw.defaultSkillId);
    if (!defaultSkillId || !seen[defaultSkillId]) defaultSkillId = null;
    return { schemaVersion: STORE_SCHEMA_VERSION, defaultSkillId: defaultSkillId, skills: skills };
  }

  function serializeStore(raw) {
    var store = normalizeStore(raw);
    return {
      schemaVersion: STORE_SCHEMA_VERSION,
      defaultSkillId: store.defaultSkillId,
      skills: store.skills.map(function (entry) { return cloneJson(entry); })
    };
  }

  function listSkills(raw) {
    var store = normalizeStore(raw);
    return store.skills.map(function (entry) {
      var skill = Skill.normalizeSkill(entry);
      skill.isDefault = skill.id === store.defaultSkillId;
      return skill;
    });
  }

  function getSkill(raw, id) {
    var normalizedId = Skill.normalizeSkillId(id);
    if (!normalizedId) return null;
    var match = listSkills(raw).filter(function (skill) { return skill.id === normalizedId; });
    return match.length === 1 ? match[0] : null;
  }

  function defaultSkill(raw) {
    var store = normalizeStore(raw);
    return store.defaultSkillId ? getSkill(store, store.defaultSkillId) : null;
  }

  function saveApprovedSkill(raw, candidate) {
    var store = normalizeStore(raw);
    var skill = Skill.normalizeSkill(candidate);
    if (!skill || skill.approved !== true) return fail("skill_not_approved", "only approved Saved Quote Skills can be stored");
    if (store.skills.some(function (entry) { return entry.id === skill.id; })) {
      return fail("duplicate_skill_id", "skill id already exists");
    }
    if (store.skills.length >= MAX_SKILLS) return fail("skill_limit_reached", "skill limit reached");
    var next = {
      schemaVersion: STORE_SCHEMA_VERSION,
      defaultSkillId: store.defaultSkillId,
      skills: store.skills.concat([Skill.serializeSkill(skill)])
    };
    return ok("saved", next, getSkill(next, skill.id));
  }

  function renameSkill(raw, id, name, options) {
    var store = normalizeStore(raw);
    var current = getSkill(store, id);
    if (!current) return fail("skill_not_found");
    var nextName = Skill.normalizeSkillName(name, "");
    if (!nextName) return fail("invalid_skill_name");
    var stamp = options && typeof options.now === "string" ? options.now.slice(0, 40) : current.updatedAt;
    var skills = store.skills.map(function (entry) {
      if (entry.id !== current.id) return entry;
      var copy = cloneJson(entry);
      copy.name = nextName;
      copy.updatedAt = stamp;
      return copy;
    });
    var next = { schemaVersion: STORE_SCHEMA_VERSION, defaultSkillId: store.defaultSkillId, skills: skills };
    var renamed = getSkill(next, current.id);
    if (!renamed || renamed.fingerprint !== current.fingerprint) return fail("skill_rename_changed_fingerprint");
    return ok("renamed", next, renamed);
  }

  function deleteSkill(raw, id) {
    var store = normalizeStore(raw);
    var current = getSkill(store, id);
    if (!current) return fail("skill_not_found");
    var next = {
      schemaVersion: STORE_SCHEMA_VERSION,
      defaultSkillId: store.defaultSkillId === current.id ? null : store.defaultSkillId,
      skills: store.skills.filter(function (entry) { return entry.id !== current.id; })
    };
    return ok("deleted", next, null, { skillId: current.id });
  }

  function setDefaultSkill(raw, id) {
    var store = normalizeStore(raw);
    if (id === null || id === undefined || id === "") {
      return ok("default_cleared", { schemaVersion: STORE_SCHEMA_VERSION, defaultSkillId: null, skills: store.skills }, null);
    }
    var skill = getSkill(store, id);
    if (!skill || skill.approved !== true) return fail("skill_not_found");
    var next = { schemaVersion: STORE_SCHEMA_VERSION, defaultSkillId: skill.id, skills: store.skills };
    return ok("default_set", next, getSkill(next, skill.id));
  }

  function readStore(storage) {
    if (!storage || typeof storage.getItem !== "function") return emptyStore();
    try {
      return normalizeStore(JSON.parse(storage.getItem(STORAGE_KEY) || "null"));
    } catch (err) {
      return emptyStore();
    }
  }

  function writeStore(storage, raw) {
    if (!storage || typeof storage.setItem !== "function") return false;
    try {
      storage.setItem(STORAGE_KEY, JSON.stringify(serializeStore(raw)));
      return true;
    } catch (err) {
      return false;
    }
  }

  function clearStore(storage) {
    if (!storage || typeof storage.removeItem !== "function") return false;
    try {
      storage.removeItem(STORAGE_KEY);
      return true;
    } catch (err) {
      return false;
    }
  }

  return {
    STORE_SCHEMA_VERSION: STORE_SCHEMA_VERSION,
    STORAGE_KEY: STORAGE_KEY,
    MAX_SKILLS: MAX_SKILLS,
    emptyStore: emptyStore,
    normalizeStore: normalizeStore,
    serializeStore: serializeStore,
    listSkills: listSkills,
    getSkill: getSkill,
    defaultSkill: defaultSkill,
    saveApprovedSkill: saveApprovedSkill,
    renameSkill: renameSkill,
    deleteSkill: deleteSkill,
    setDefaultSkill: setDefaultSkill,
    readStore: readStore,
    writeStore: writeStore,
    clearStore: clearStore
  };
});
