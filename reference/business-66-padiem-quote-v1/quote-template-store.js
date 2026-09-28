/* B66 · Quote Beta — quote-template-store.js
   브라우저 로컬(quoteBeta.*) bounded 템플릿 저장소.
   저장하는 것은 "표현과 배치"인 QuoteTemplateProfile 뿐이다.
   신뢰되는 합계·원본 파일 바이트·자격증명·모델/도구 authority 는 저장하지 않는다.
   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-template.js"));
  } else {
    root.QuoteTemplateStore = factory(root.QuoteTemplate);
  }
})(typeof self !== "undefined" ? self : this, function (Template) {
  "use strict";

  if (!Template) throw new Error("QuoteTemplate is required");

  var TEMPLATE_STORE_SCHEMA_VERSION = 1;
  var TEMPLATE_STORAGE_KEY = "quoteBetaTemplate.v1";
  var MAX_TEMPLATES = 20;
  var DEFAULT_TEMPLATE_COUNT = 1;
  var MAX_STORED_NAME_CHARS = Template.MAX_TEMPLATE_NAME_CHARS;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function emptyStore() {
    return { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: [] };
  }

  /* ── 저장소 정규화: 손상/구버전/금지 키/중복 id 는 조용히 버린다 ── */

  function normalizeStore(raw) {
    if (!isPlainObject(raw)) return emptyStore();
    if (raw.schemaVersion !== TEMPLATE_STORE_SCHEMA_VERSION) return emptyStore();
    if (!Array.isArray(raw.templates)) return emptyStore();

    var templates = [];
    var seen = Object.create(null);
    var defaultTaken = false;

    raw.templates.slice(0, MAX_TEMPLATES).forEach(function (entry) {
      var profile = Template.normalizeTemplate(entry);
      if (!profile) return;
      if (profile.builtin || profile.id === Template.BUILTIN_TEMPLATE_ID) return;
      if (seen[profile.id]) return;
      seen[profile.id] = true;

      var isDefault = profile.isDefault && !defaultTaken;
      if (isDefault) defaultTaken = true;

      templates.push({
        schemaVersion: Template.TEMPLATE_SCHEMA_VERSION,
        id: profile.id,
        name: profile.name.slice(0, MAX_STORED_NAME_CHARS),
        builtin: false,
        isDefault: isDefault,
        createdAt: profile.createdAt,
        updatedAt: profile.updatedAt,
        fingerprint: profile.fingerprint,
        content: cloneJson(profile.content)
      });
    });

    return { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
  }

  function serializeStore(rawStore) {
    var store = normalizeStore(rawStore);
    return {
      schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION,
      templates: store.templates.map(Template.serializeTemplate)
    };
  }

  /* ── 조회: 내장 기본은 항상 존재하며, 정확히 하나만 default 다 ── */

  function userDefaultId(store) {
    var found = store.templates.filter(function (entry) { return entry.isDefault; });
    return found.length === 1 ? found[0].id : null;
  }

  function listTemplates(rawStore) {
    var store = normalizeStore(rawStore);
    var activeDefaultId = userDefaultId(store);
    var builtin = Template.builtInTemplate();
    builtin.isDefault = activeDefaultId === null;

    return [builtin].concat(store.templates.map(function (entry) {
      return Template.buildProfile({
        id: entry.id,
        name: entry.name,
        builtin: false,
        isDefault: entry.id === activeDefaultId,
        createdAt: entry.createdAt,
        updatedAt: entry.updatedAt,
        content: entry.content
      });
    }));
  }

  function countDefaults(rawStore) {
    return listTemplates(rawStore).filter(function (entry) { return entry.isDefault; }).length;
  }

  function getTemplate(rawStore, id) {
    if (typeof id !== "string" || !id) return null;
    var match = listTemplates(rawStore).filter(function (entry) { return entry.id === id; });
    return match.length === 1 ? match[0] : null;
  }

  function defaultTemplate(rawStore) {
    var list = listTemplates(rawStore);
    var found = list.filter(function (entry) { return entry.isDefault; });
    return found.length === 1 ? found[0] : Template.builtInTemplate();
  }

  function defaultTemplateId(rawStore) {
    return defaultTemplate(rawStore).id;
  }

  /* ── 변경 연산: 모두 새 store 를 반환하고 원본을 변형하지 않는다 ── */

  function fail(code, message) {
    return { ok: false, code: code, message: message, store: null, template: null };
  }

  function makeTemplateId(options) {
    var opts = options || {};
    if (typeof opts.id === "string" && Template.normalizeTemplateId(opts.id)) return opts.id;
    var stamp = Date.now().toString(36);
    var suffix = Math.random().toString(36).slice(2, 8);
    return "template-" + stamp + "-" + suffix;
  }

  function stampOf(options) {
    var opts = options || {};
    return typeof opts.now === "string" && opts.now
      ? opts.now.slice(0, 40)
      : new Date().toISOString();
  }

  function demoteDefaults(templates) {
    return templates.map(function (entry) {
      return entry.isDefault ? Object.assign({}, entry, { isDefault: false }) : entry;
    });
  }

  function createTemplate(rawStore, input, options) {
    var store = normalizeStore(rawStore);
    if (!isPlainObject(input)) return fail("invalid_template_content", "template input must be an object");

    var forbidden = Template.findForbiddenKeys(input);
    if (forbidden.length > 0) {
      return fail("forbidden_template_field", "template contains forbidden fields: " + forbidden.join(", "));
    }

    if (store.templates.length >= MAX_TEMPLATES) {
      return fail("template_limit_reached", "template limit reached");
    }

    var content = Template.normalizeTemplateContent(input.content);
    if (!content) return fail("invalid_template_content", "template content is not a valid profile");

    var id = makeTemplateId(options);
    if (id === Template.BUILTIN_TEMPLATE_ID) {
      return fail("duplicate_template_id", "built-in template id is reserved");
    }
    if (store.templates.some(function (entry) { return entry.id === id; })) {
      return fail("duplicate_template_id", "template id already exists");
    }

    var stamp = stampOf(options);
    var isDefault = Boolean(options && options.isDefault);
    var templates = isDefault ? demoteDefaults(store.templates) : store.templates.slice();

    templates.push({
      schemaVersion: Template.TEMPLATE_SCHEMA_VERSION,
      id: id,
      name: Template.normalizeTemplateName(input.name, id).slice(0, MAX_STORED_NAME_CHARS),
      builtin: false,
      isDefault: isDefault,
      createdAt: stamp,
      updatedAt: stamp,
      fingerprint: Template.templateFingerprint(content),
      content: content
    });

    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "created", message: null, store: next, template: getTemplate(next, id) };
  }

  function updateTemplate(rawStore, id, patch, options) {
    var store = normalizeStore(rawStore);
    if (Template.isBuiltInTemplate({ id: id })) {
      return fail("builtin_template_immutable", "built-in template cannot be modified");
    }
    var index = store.templates.findIndex(function (entry) { return entry.id === id; });
    if (index === -1) return fail("template_not_found", "template not found");
    if (!isPlainObject(patch)) return fail("invalid_template_content", "patch must be an object");

    var forbidden = Template.findForbiddenKeys(patch);
    if (forbidden.length > 0) {
      return fail("forbidden_template_field", "template contains forbidden fields: " + forbidden.join(", "));
    }

    var current = store.templates[index];
    var content = current.content;
    if (Object.prototype.hasOwnProperty.call(patch, "content")) {
      content = Template.normalizeTemplateContent(patch.content);
      if (!content) return fail("invalid_template_content", "template content is not a valid profile");
    }

    var updated = {
      schemaVersion: Template.TEMPLATE_SCHEMA_VERSION,
      id: current.id,
      name: Object.prototype.hasOwnProperty.call(patch, "name")
        ? Template.normalizeTemplateName(patch.name, current.name).slice(0, MAX_STORED_NAME_CHARS)
        : current.name,
      builtin: false,
      isDefault: Object.prototype.hasOwnProperty.call(patch, "isDefault")
        ? Boolean(patch.isDefault)
        : current.isDefault,
      createdAt: current.createdAt,
      updatedAt: stampOf(options),
      fingerprint: Template.templateFingerprint(content),
      content: content
    };

    var templates = store.templates.map(function (entry) {
      if (entry.id === updated.id) return updated;
      return updated.isDefault ? Object.assign({}, entry, { isDefault: false }) : entry;
    });

    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "updated", message: null, store: next, template: getTemplate(next, id) };
  }

  function deleteTemplate(rawStore, id) {
    var store = normalizeStore(rawStore);
    if (Template.isBuiltInTemplate({ id: id })) {
      return fail("builtin_template_immutable", "built-in template cannot be deleted");
    }
    var index = store.templates.findIndex(function (entry) { return entry.id === id; });
    if (index === -1) return fail("template_not_found", "template not found");

    var templates = store.templates.filter(function (entry) { return entry.id !== id; });
    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "deleted", message: null, store: next, template: null };
  }

  function duplicateTemplate(rawStore, id, options) {
    var store = normalizeStore(rawStore);
    var source = getTemplate(store, id);
    if (!source) return fail("template_not_found", "template not found");
    if (store.templates.length >= MAX_TEMPLATES) {
      return fail("template_limit_reached", "template limit reached");
    }

    var opts = options || {};
    var newId = makeTemplateId(opts);
    if (newId === Template.BUILTIN_TEMPLATE_ID || store.templates.some(function (entry) { return entry.id === newId; })) {
      return fail("duplicate_template_id", "template id already exists");
    }

    var stamp = stampOf(opts);
    var name = typeof opts.name === "string" && opts.name.trim()
      ? opts.name.trim()
      : source.name + " 사본";

    var templates = store.templates.slice();
    templates.push({
      schemaVersion: Template.TEMPLATE_SCHEMA_VERSION,
      id: newId,
      name: name.slice(0, MAX_STORED_NAME_CHARS),
      builtin: false,
      isDefault: false,
      createdAt: stamp,
      updatedAt: stamp,
      fingerprint: source.fingerprint,
      content: cloneJson(source.content)
    });

    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "duplicated", message: null, store: next, template: getTemplate(next, newId) };
  }

  function setDefaultTemplate(rawStore, id) {
    var store = normalizeStore(rawStore);
    var target = getTemplate(store, id);
    if (!target) return fail("template_not_found", "template not found");

    if (target.builtin) {
      var cleared = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: demoteDefaults(store.templates) };
      return { ok: true, code: "default_builtin", message: null, store: cleared, template: Template.builtInTemplate() };
    }

    var templates = store.templates.map(function (entry) {
      return Object.assign({}, entry, { isDefault: entry.id === id });
    });
    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "default_set", message: null, store: next, template: getTemplate(next, id) };
  }

  /* ── Storage 어댑터 (선택): Storage-like 객체만 받는다 ── */

  function readStore(storage) {
    if (!storage || typeof storage.getItem !== "function") return emptyStore();
    try {
      return normalizeStore(JSON.parse(storage.getItem(TEMPLATE_STORAGE_KEY) || "null"));
    } catch (err) {
      return emptyStore();
    }
  }

  function writeStore(storage, rawStore) {
    if (!storage || typeof storage.setItem !== "function") return false;
    try {
      storage.setItem(TEMPLATE_STORAGE_KEY, JSON.stringify(serializeStore(rawStore)));
      return true;
    } catch (err) {
      return false;
    }
  }

  function clearStore(storage) {
    if (!storage || typeof storage.removeItem !== "function") return false;
    try {
      storage.removeItem(TEMPLATE_STORAGE_KEY);
      return true;
    } catch (err) {
      return false;
    }
  }

  return {
    TEMPLATE_STORE_SCHEMA_VERSION: TEMPLATE_STORE_SCHEMA_VERSION,
    TEMPLATE_STORAGE_KEY: TEMPLATE_STORAGE_KEY,
    MAX_TEMPLATES: MAX_TEMPLATES,
    DEFAULT_TEMPLATE_COUNT: DEFAULT_TEMPLATE_COUNT,
    emptyStore: emptyStore,
    normalizeStore: normalizeStore,
    serializeStore: serializeStore,
    listTemplates: listTemplates,
    countDefaults: countDefaults,
    getTemplate: getTemplate,
    defaultTemplate: defaultTemplate,
    defaultTemplateId: defaultTemplateId,
    createTemplate: createTemplate,
    updateTemplate: updateTemplate,
    deleteTemplate: deleteTemplate,
    duplicateTemplate: duplicateTemplate,
    setDefaultTemplate: setDefaultTemplate,
    readStore: readStore,
    writeStore: writeStore,
    clearStore: clearStore
  };
});
