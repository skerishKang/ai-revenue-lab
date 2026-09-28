/* B66 · Quote Beta — quote-template-store.js
   브라우저 로컬(quoteBeta.*) bounded 템플릿 저장소.
   저장하는 것은 "표현과 배치"인 QuoteTemplateProfile 뿐이다.

   승인 경계(#3181 semantics):
     candidate  →  explicit approval  →  approved profile  →  활성/렌더 가능
   승인되지 않은 candidate 는 저장될 수 있지만 기본이 될 수도, 렌더에 쓰일 수도 없다.
   내장 기본 템플릿만 trusted built-in 예외다(코드·테스트에 명시).

   저장 금지: 신뢰되는 합계·원본 파일 바이트·자격증명·모델/도구 authority.
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

  function fail(code, message) {
    return { ok: false, code: code, message: message, store: null, template: null };
  }

  function isEntryApproved(entry) {
    return Boolean(entry) && Template.approvalIsValid(entry.approval, entry.fingerprint);
  }

  /* logo/stamp slot 은 non-live 로 선언되어 있다. 값을 선언해 놓고 조용히 무시하지 않도록
     저장·승인 시점에 명시적으로 거부한다. */
  function rejectionForContent(content) {
    if (!isPlainObject(content)) return "invalid_template_content";
    var slots = isPlainObject(content.slots) ? content.slots : {};
    if (String(slots.logo || "") || String(slots.stamp || "")) return "slot_rendering_not_supported";
    return null;
  }

  function toEntry(profile, options) {
    var opts = options || {};
    return {
      schemaVersion: Template.TEMPLATE_SCHEMA_VERSION,
      id: profile.id,
      name: profile.name.slice(0, MAX_STORED_NAME_CHARS),
      builtin: false,
      isDefault: Boolean(opts.isDefault),
      approval: profile.approval ? cloneJson(profile.approval) : null,
      createdAt: profile.createdAt,
      updatedAt: profile.updatedAt,
      fingerprint: profile.fingerprint,
      content: cloneJson(profile.content)
    };
  }

  function toProfile(entry, isDefault) {
    return Template.buildProfile({
      id: entry.id,
      name: entry.name,
      builtin: false,
      isDefault: isDefault === true,
      approval: entry.approval,
      createdAt: entry.createdAt,
      updatedAt: entry.updatedAt,
      content: entry.content
    });
  }

  /* ── 저장소 정규화: 손상/구버전/금지 키/중복 id/무효 승인은 조용히 버린다 ── */

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

      /* 승인되지 않은 candidate 는 기본이 될 수 없다. */
      var isDefault = profile.isDefault && profile.approved && !defaultTaken;
      if (isDefault) defaultTaken = true;

      templates.push({
        schemaVersion: Template.TEMPLATE_SCHEMA_VERSION,
        id: profile.id,
        name: profile.name.slice(0, MAX_STORED_NAME_CHARS),
        builtin: false,
        isDefault: isDefault,
        /* 지문이 어긋난 승인은 normalizeTemplate 단계에서 이미 버려졌다. */
        approval: profile.approval ? cloneJson(profile.approval) : null,
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

  /* ── 조회: 내장 기본은 항상 존재하며, 활성 기본은 정확히 하나 ── */

  function userDefaultId(store) {
    var found = store.templates.filter(function (entry) {
      return entry.isDefault && isEntryApproved(entry);
    });
    return found.length === 1 ? found[0].id : null;
  }

  function listTemplates(rawStore) {
    var store = normalizeStore(rawStore);
    var activeDefaultId = userDefaultId(store);
    var builtin = Template.builtInTemplate();
    builtin.isDefault = activeDefaultId === null;

    return [builtin].concat(store.templates.map(function (entry) {
      return toProfile(entry, entry.id === activeDefaultId);
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

  function isTemplateApproved(rawStore, id) {
    var template = getTemplate(rawStore, id);
    return Boolean(template) && template.approved === true;
  }

  function defaultTemplate(rawStore) {
    var found = listTemplates(rawStore).filter(function (entry) {
      return entry.isDefault && entry.approved;
    });
    return found.length === 1 ? found[0] : Template.builtInTemplate();
  }

  function defaultTemplateId(rawStore) {
    return defaultTemplate(rawStore).id;
  }

  /* ── 변경 연산: 모두 새 store 를 반환하고 원본을 변형하지 않는다 ── */

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

  function reservedId(id, store) {
    if (id === Template.BUILTIN_TEMPLATE_ID) return true;
    return store.templates.some(function (entry) { return entry.id === id; });
  }

  /* candidate 생성. 승인 증거가 함께 주어지지 않으면 unapproved 로 저장된다. */
  function createTemplate(rawStore, input, options) {
    var store = normalizeStore(rawStore);
    var opts = options || {};
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

    var contentIssue = rejectionForContent(content);
    if (contentIssue) return fail(contentIssue, "declared template field is not renderable in this MVP");

    var id = makeTemplateId(opts);
    if (reservedId(id, store)) return fail("duplicate_template_id", "template id already exists");

    var fingerprint = Template.templateFingerprint(content);
    var approval = null;
    if (opts.approval !== undefined && opts.approval !== null) {
      approval = Template.normalizeApproval(opts.approval, fingerprint);
      if (!approval) return fail("invalid_approval_evidence", "approval evidence does not match the template content");
    }

    var wantsDefault = opts.isDefault === true;
    if (wantsDefault && !approval) {
      return fail("template_not_approved", "an unapproved template cannot become the active default");
    }

    var stamp = stampOf(opts);
    var profile = Template.buildProfile({
      id: id,
      name: Template.normalizeTemplateName(input.name, id),
      builtin: false,
      isDefault: wantsDefault,
      approval: approval,
      createdAt: stamp,
      updatedAt: stamp,
      content: content
    });

    var templates = store.templates.map(function (entry) {
      return wantsDefault ? Object.assign({}, entry, { isDefault: false }) : entry;
    });
    templates.push(toEntry(profile, { isDefault: wantsDefault }));

    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "created", message: null, store: next, template: getTemplate(next, id) };
  }

  /* explicit approval 부여. 증거는 현재 content 지문과 일치해야 한다. */
  function approveTemplate(rawStore, id, evidence, options) {
    var store = normalizeStore(rawStore);
    if (Template.isBuiltInTemplate({ id: id })) {
      return fail("builtin_template_trusted", "the built-in template is already trusted and needs no approval");
    }
    var index = store.templates.findIndex(function (entry) { return entry.id === id; });
    if (index === -1) return fail("template_not_found", "template not found");

    var current = store.templates[index];
    var approval = Template.normalizeApproval(evidence, current.fingerprint);
    if (!approval) {
      return fail("invalid_approval_evidence", "approval evidence does not match the template content");
    }

    var updated = Object.assign({}, current, {
      approval: approval,
      updatedAt: stampOf(options)
    });

    var templates = store.templates.slice();
    templates[index] = updated;
    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "approved", message: null, store: next, template: getTemplate(next, id) };
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
    var contentChanged = Object.prototype.hasOwnProperty.call(patch, "content");
    var content = current.content;
    var approval = current.approval;

    if (contentChanged) {
      content = Template.normalizeTemplateContent(patch.content);
      if (!content) return fail("invalid_template_content", "template content is not a valid profile");
      var contentIssue = rejectionForContent(content);
      if (contentIssue) return fail(contentIssue, "declared template field is not renderable in this MVP");
      /* 내용이 바뀌면 기존 승인은 즉시 무효다 — 조용히 보존하지 않는다. */
      approval = null;
    }

    var wantsDefault = Object.prototype.hasOwnProperty.call(patch, "isDefault")
      ? Boolean(patch.isDefault)
      : false;
    /* 내용이 바뀌어 승인이 사라졌다면 기본 지위도 유지될 수 없다. */
    var keepDefault = !contentChanged && current.isDefault;
    var nextIsDefault = wantsDefault || keepDefault;

    var candidate = Template.buildProfile({
      id: current.id,
      name: Object.prototype.hasOwnProperty.call(patch, "name")
        ? Template.normalizeTemplateName(patch.name, current.name)
        : current.name,
      builtin: false,
      isDefault: nextIsDefault,
      approval: approval,
      createdAt: current.createdAt,
      updatedAt: stampOf(options),
      content: content
    });

    if (nextIsDefault && !candidate.approved) {
      return fail("template_not_approved", "an unapproved template cannot become the active default");
    }

    var updated = toEntry(candidate, { isDefault: nextIsDefault });
    var templates = store.templates.map(function (entry) {
      if (entry.id === updated.id) return updated;
      return nextIsDefault ? Object.assign({}, entry, { isDefault: false }) : entry;
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

  /* 복제본은 새 candidate 다 — 승인은 복사하지 않는다(다시 승인받아야 활성화된다). */
  function duplicateTemplate(rawStore, id, options) {
    var store = normalizeStore(rawStore);
    var source = getTemplate(store, id);
    if (!source) return fail("template_not_found", "template not found");
    if (store.templates.length >= MAX_TEMPLATES) {
      return fail("template_limit_reached", "template limit reached");
    }

    var opts = options || {};
    var newId = makeTemplateId(opts);
    if (reservedId(newId, store)) return fail("duplicate_template_id", "template id already exists");

    var stamp = stampOf(opts);
    var name = typeof opts.name === "string" && opts.name.trim()
      ? opts.name.trim()
      : source.name + " 사본";

    var profile = Template.buildProfile({
      id: newId,
      name: name,
      builtin: false,
      isDefault: false,
      approval: null,
      createdAt: stamp,
      updatedAt: stamp,
      content: cloneJson(source.content)
    });

    var templates = store.templates.slice();
    templates.push(toEntry(profile, { isDefault: false }));

    var next = { schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION, templates: templates };
    return { ok: true, code: "duplicated", message: null, store: next, template: getTemplate(next, newId) };
  }

  function setDefaultTemplate(rawStore, id) {
    var store = normalizeStore(rawStore);
    var target = getTemplate(store, id);
    if (!target) return fail("template_not_found", "template not found");

    if (target.builtin) {
      var cleared = {
        schemaVersion: TEMPLATE_STORE_SCHEMA_VERSION,
        templates: store.templates.map(function (entry) {
          return entry.isDefault ? Object.assign({}, entry, { isDefault: false }) : entry;
        })
      };
      return { ok: true, code: "default_builtin", message: null, store: cleared, template: Template.builtInTemplate() };
    }

    if (!target.approved) {
      return fail("template_not_approved", "an unapproved template cannot become the active default");
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
    isTemplateApproved: isTemplateApproved,
    isEntryApproved: isEntryApproved,
    defaultTemplate: defaultTemplate,
    defaultTemplateId: defaultTemplateId,
    createTemplate: createTemplate,
    approveTemplate: approveTemplate,
    updateTemplate: updateTemplate,
    deleteTemplate: deleteTemplate,
    duplicateTemplate: duplicateTemplate,
    setDefaultTemplate: setDefaultTemplate,
    readStore: readStore,
    writeStore: writeStore,
    clearStore: clearStore
  };
});
