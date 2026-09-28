/* B66 · Quote Beta — quote-template-selection.js
   "현재 견적에 쓸 양식" 과 "향후 기본 양식" 을 분리해서 다루는 상태/액션 계층.

   저장 형태는 견적별 selection 을 담는 bounded versioned envelope 다:
     { schemaVersion, selections: [{ quoteNo, templateId, updatedAt }, ...] }
   - 견적 A 와 B 의 선택이 서로를 덮어쓰지 않는다(견적별 영속화).
   - 최근 순으로 보관하고 MAX_SELECTIONS 를 넘으면 오래된 것부터 버린다.
   - 손상된 entry 는 그 entry 만 버리고 나머지는 살린다(개별 fail-closed).

   불변식:
   - 양식 전환은 QuoteDraft 의 업무 내용을 절대 건드리지 않는다.
   - 승인되지 않은 candidate 는 목록에 보일 수는 있어도 선택/적용/기본 지정이 될 수 없다.
   - 선택된 양식이 사라졌거나 손상되면 기본 양식 → 내장 기본 순으로 안전하게 되돌아간다.
   (DOM 없음 · 브라우저/Node 양쪽에서 실행) */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-template.js"), require("./quote-template-store.js"));
  } else {
    root.QuoteTemplateSelection = factory(root.QuoteTemplate, root.QuoteTemplateStore);
  }
})(typeof self !== "undefined" ? self : this, function (Template, Store) {
  "use strict";

  if (!Template) throw new Error("QuoteTemplate is required");
  if (!Store) throw new Error("QuoteTemplateStore is required");

  var SELECTION_SCHEMA_VERSION = 1;
  var SELECTION_STORAGE_KEY = "quoteBetaTemplateSelection.v1";
  var MAX_SELECTIONS = 20;
  var MAX_QUOTE_NO_CHARS = 120;
  var MAX_TEMPLATE_ID_CHARS = 64;
  var MAX_SELECTION_NAME_CHARS = Template.MAX_TEMPLATE_NAME_CHARS;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function boundedId(value) {
    var id = String(value == null ? "" : value).trim();
    if (!id || id.length > MAX_TEMPLATE_ID_CHARS) return "";
    return id;
  }

  function boundedQuoteNo(value) {
    var quoteNo = String(value == null ? "" : value).trim();
    if (!quoteNo || quoteNo.length > MAX_QUOTE_NO_CHARS) return "";
    return quoteNo;
  }

  function stampOf(options) {
    var opts = options || {};
    return typeof opts.now === "string" && opts.now
      ? opts.now.slice(0, 40)
      : new Date().toISOString();
  }

  /* ── envelope 정규화: 손상 entry 는 그 entry 만 버린다 ── */

  function emptyEnvelope() {
    return { schemaVersion: SELECTION_SCHEMA_VERSION, selections: [] };
  }

  function normalizeSelectionEntry(raw) {
    if (!isPlainObject(raw)) return null;
    var quoteNo = boundedQuoteNo(raw.quoteNo);
    if (!quoteNo) return null;
    var templateId = boundedId(raw.templateId);
    if (!templateId) return null;
    return {
      quoteNo: quoteNo,
      templateId: templateId,
      updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt.slice(0, 40) : ""
    };
  }

  function normalizeEnvelope(raw) {
    if (!isPlainObject(raw)) return emptyEnvelope();
    if (raw.schemaVersion !== SELECTION_SCHEMA_VERSION) return emptyEnvelope();
    if (!Array.isArray(raw.selections)) return emptyEnvelope();

    var selections = [];
    var seen = Object.create(null);
    raw.selections.forEach(function (entry) {
      var normalized = normalizeSelectionEntry(entry);
      if (!normalized) return;                       /* 손상 entry 만 버린다 */
      if (seen[normalized.quoteNo]) return;          /* 견적별 하나만 유지 */
      seen[normalized.quoteNo] = true;
      if (selections.length >= MAX_SELECTIONS) return;
      selections.push(normalized);
    });

    return { schemaVersion: SELECTION_SCHEMA_VERSION, selections: selections };
  }

  function selectionForQuote(rawEnvelope, quoteNo) {
    var envelope = normalizeEnvelope(rawEnvelope);
    var target = boundedQuoteNo(quoteNo);
    if (!target) return null;
    var match = envelope.selections.filter(function (entry) { return entry.quoteNo === target; });
    return match.length === 1 ? match[0].templateId : null;
  }

  function currentSelection(rawEnvelope, quoteNo) {
    var envelope = normalizeEnvelope(rawEnvelope);
    var target = boundedQuoteNo(quoteNo);
    if (!target) return null;
    var match = envelope.selections.filter(function (entry) { return entry.quoteNo === target; });
    return match.length === 1 ? match[0] : null;
  }

  function setSelection(rawEnvelope, quoteNo, templateId, options) {
    var target = boundedQuoteNo(quoteNo);
    var id = boundedId(templateId);
    if (!target || !id) return null;

    var envelope = normalizeEnvelope(rawEnvelope);
    var entry = { quoteNo: target, templateId: id, updatedAt: stampOf(options) };

    var rest = envelope.selections.filter(function (existing) { return existing.quoteNo !== target; });
    rest.unshift(entry);                              /* 최근 선택이 앞으로 */
    return {
      schemaVersion: SELECTION_SCHEMA_VERSION,
      selections: rest.slice(0, MAX_SELECTIONS)
    };
  }

  function removeSelection(rawEnvelope, quoteNo) {
    var target = boundedQuoteNo(quoteNo);
    var envelope = normalizeEnvelope(rawEnvelope);
    if (!target) return envelope;
    return {
      schemaVersion: SELECTION_SCHEMA_VERSION,
      selections: envelope.selections.filter(function (entry) { return entry.quoteNo !== target; })
    };
  }

  /* 양식을 지울 때는 그 양식을 참조하는 selection 만 지운다(다른 견적은 유지). */
  function removeSelectionsForTemplate(rawEnvelope, templateId) {
    var id = boundedId(templateId);
    var envelope = normalizeEnvelope(rawEnvelope);
    if (!id) return envelope;
    return {
      schemaVersion: SELECTION_SCHEMA_VERSION,
      selections: envelope.selections.filter(function (entry) { return entry.templateId !== id; })
    };
  }

  function readEnvelope(storage) {
    if (!storage || typeof storage.getItem !== "function") return emptyEnvelope();
    try {
      return normalizeEnvelope(JSON.parse(storage.getItem(SELECTION_STORAGE_KEY) || "null"));
    } catch (err) {
      return emptyEnvelope();
    }
  }

  function writeEnvelope(storage, rawEnvelope) {
    if (!storage || typeof storage.setItem !== "function") return false;
    try {
      storage.setItem(SELECTION_STORAGE_KEY, JSON.stringify(normalizeEnvelope(rawEnvelope)));
      return true;
    } catch (err) {
      return false;
    }
  }

  function clearAll(storage) {
    if (!storage || typeof storage.removeItem !== "function") return false;
    try {
      storage.removeItem(SELECTION_STORAGE_KEY);
      return true;
    } catch (err) {
      return false;
    }
  }

  /* ── 해석: 선택 → 기본 → 내장 기본. 미승인/부재/손상은 모두 안전하게 되돌린다 ── */

  function isSelectable(rawStore, templateId) {
    var id = boundedId(templateId);
    if (!id) return false;
    var template = Store.getTemplate(rawStore, id);
    return Boolean(template) && template.approved === true;
  }

  function resolveActiveTemplateId(rawStore, rawEnvelope, quoteNo) {
    var selected = selectionForQuote(rawEnvelope, quoteNo);
    if (selected && isSelectable(rawStore, selected)) return selected;
    return Store.defaultTemplateId(rawStore);
  }

  function resolveActiveTemplate(rawStore, rawEnvelope, quoteNo) {
    var id = resolveActiveTemplateId(rawStore, rawEnvelope, quoteNo);
    var template = Store.getTemplate(rawStore, id);
    if (template && template.approved === true) return template;
    /* 기본 양식까지 손상된 경우에도 내장 기본은 항상 존재한다. */
    return Store.defaultTemplate(rawStore);
  }

  /* ── 목록: 승인 여부/기본 여부를 함께 노출한다(미승인도 보이지만 선택 불가) ── */

  function listForManagement(rawStore) {
    return Store.listTemplates(rawStore).map(function (template) {
      return {
        id: template.id,
        name: template.name,
        builtin: template.builtin === true,
        approved: template.approved === true,
        approvalBasis: template.approvalBasis,
        isDefault: template.isDefault === true,
        fingerprint: template.fingerprint,
        selectable: template.approved === true,
        canRename: !template.builtin,
        canDuplicate: true,
        canDelete: !template.builtin,
        canSetDefault: template.approved === true && template.isDefault !== true,
        canApprove: template.approved !== true && !template.builtin
      };
    });
  }

  /* ── 액션: 모두 결과 코드를 돌려주고, 실패하면 아무것도 바꾸지 않는다 ── */

  function ok(code, extra) {
    return Object.assign({ ok: true, code: code }, extra || {});
  }

  function fail(code, message) {
    return { ok: false, code: code, message: message || null };
  }

  function selectTemplate(storage, quoteNo, templateId, options) {
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    if (!isSelectable(store, id)) return fail("template_not_approved");

    var envelope = setSelection(readEnvelope(storage), quoteNo, id, options);
    if (!envelope) return fail("invalid_quote_no");
    if (!writeEnvelope(storage, envelope)) return fail("selection_storage_failed");

    return ok("selected", {
      selection: currentSelection(envelope, quoteNo),
      envelope: envelope,
      template: Store.getTemplate(store, id)
    });
  }

  function setDefaultTemplate(storage, templateId) {
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    var result = Store.setDefaultTemplate(store, id);
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    /* 기본 변경은 기존 견적별 explicit selection 을 건드리지 않는다. */
    return ok(result.code, { template: result.template, envelope: readEnvelope(storage) });
  }

  function renameTemplate(storage, templateId, name) {
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    if (!Store.getTemplate(store, id)) return fail("template_not_found");
    var trimmed = String(name == null ? "" : name).trim();
    if (!trimmed) return fail("invalid_template_name");
    var result = Store.updateTemplate(store, id, { name: trimmed.slice(0, MAX_SELECTION_NAME_CHARS) });
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    return ok("renamed", { template: result.template, envelope: readEnvelope(storage) });
  }

  function duplicateTemplate(storage, templateId, options) {
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    var opts = options || {};
    var result = Store.duplicateTemplate(store, id, { now: stampOf(opts), name: opts.name });
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    return ok("duplicated", { template: result.template, envelope: readEnvelope(storage) });
  }

  /* 삭제는 반드시 확인을 거친다. 확인이 없으면 아무것도 바꾸지 않는다. */
  function deleteTemplate(storage, templateId, options) {
    var opts = options || {};
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    var target = Store.getTemplate(store, id);
    if (!target) return fail("template_not_found");
    if (target.builtin) return fail("builtin_template_immutable", "기본 견적서는 삭제할 수 없습니다.");

    var ask = typeof opts.confirm === "function" ? opts.confirm : function () { return false; };
    if (ask(target) !== true) return fail("delete_cancelled");

    var result = Store.deleteTemplate(store, id);
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");

    /* 이 양식을 참조하는 selection 만 제거한다 — 다른 견적의 selection 은 유지된다. */
    var pruned = removeSelectionsForTemplate(readEnvelope(storage), id);
    writeEnvelope(storage, pruned);

    return ok("deleted", { templateId: id, envelope: pruned, defaultTemplateId: Store.defaultTemplateId(result.store) });
  }

  /* 새 양식 만들기 = 현재 활성(승인된) 양식을 본뜬 candidate. 승인 전에는 적용할 수 없다. */
  function createCandidate(storage, options) {
    var store = Store.readStore(storage);
    var opts = options || {};
    var sourceId = boundedId(opts.sourceTemplateId) ||
      resolveActiveTemplateId(store, readEnvelope(storage), opts.quoteNo);
    var source = Store.getTemplate(store, sourceId);
    if (!source) return fail("template_not_found");

    var result = Store.createTemplate(
      store,
      {
        name: typeof opts.name === "string" && opts.name.trim() ? opts.name.trim() : source.name + " 사본",
        content: source.content
      },
      { now: stampOf(opts) }
    );
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    return ok("created", { template: result.template, envelope: readEnvelope(storage) });
  }

  return {
    SELECTION_SCHEMA_VERSION: SELECTION_SCHEMA_VERSION,
    SELECTION_STORAGE_KEY: SELECTION_STORAGE_KEY,
    MAX_SELECTIONS: MAX_SELECTIONS,
    emptyEnvelope: emptyEnvelope,
    normalizeEnvelope: normalizeEnvelope,
    normalizeSelectionEntry: normalizeSelectionEntry,
    selectionForQuote: selectionForQuote,
    currentSelection: currentSelection,
    setSelection: setSelection,
    removeSelection: removeSelection,
    removeSelectionsForTemplate: removeSelectionsForTemplate,
    readEnvelope: readEnvelope,
    writeEnvelope: writeEnvelope,
    clearAll: clearAll,
    isSelectable: isSelectable,
    resolveActiveTemplateId: resolveActiveTemplateId,
    resolveActiveTemplate: resolveActiveTemplate,
    listForManagement: listForManagement,
    selectTemplate: selectTemplate,
    setDefaultTemplate: setDefaultTemplate,
    renameTemplate: renameTemplate,
    duplicateTemplate: duplicateTemplate,
    deleteTemplate: deleteTemplate,
    createCandidate: createCandidate
  };
});
