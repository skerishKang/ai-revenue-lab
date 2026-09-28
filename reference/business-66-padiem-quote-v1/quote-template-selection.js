/* B66 · Quote Beta — quote-template-selection.js
   "현재 견적에 쓸 양식" 과 "향후 기본 양식" 을 분리해서 다루는 상태/액션 계층.

   불변식:
   - 양식 전환은 QuoteDraft 의 업무 내용을 절대 건드리지 않는다(템플릿 정체성과 초안 내용은 별개).
   - 승인되지 않은 candidate 는 목록에 보일 수는 있어도 선택/적용/기본 지정이 될 수 없다.
   - canonical built-in 만이 승인 예외이며(#3182), forged builtin 플래그로는 우회할 수 없다.
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

  /* ── 선택 상태: 견적번호에 묶인다(견적을 다시 열어도 결정적) ── */

  function normalizeSelection(raw) {
    if (!isPlainObject(raw)) return null;
    if (raw.schemaVersion !== SELECTION_SCHEMA_VERSION) return null;
    var quoteNo = boundedQuoteNo(raw.quoteNo);
    if (!quoteNo) return null;
    var templateId = boundedId(raw.templateId);
    if (!templateId) return null;
    return {
      schemaVersion: SELECTION_SCHEMA_VERSION,
      quoteNo: quoteNo,
      templateId: templateId,
      updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt.slice(0, 40) : ""
    };
  }

  function selectionForQuote(rawSelection, quoteNo) {
    var selection = normalizeSelection(rawSelection);
    var target = boundedQuoteNo(quoteNo);
    if (!selection || !target || selection.quoteNo !== target) return null;
    return selection.templateId;
  }

  function makeSelection(quoteNo, templateId, options) {
    var target = boundedQuoteNo(quoteNo);
    var id = boundedId(templateId);
    if (!target || !id) return null;
    return {
      schemaVersion: SELECTION_SCHEMA_VERSION,
      quoteNo: target,
      templateId: id,
      updatedAt: stampOf(options)
    };
  }

  function readSelection(storage) {
    if (!storage || typeof storage.getItem !== "function") return null;
    try {
      return normalizeSelection(JSON.parse(storage.getItem(SELECTION_STORAGE_KEY) || "null"));
    } catch (err) {
      return null;
    }
  }

  function writeSelection(storage, selection) {
    if (!storage || typeof storage.setItem !== "function") return false;
    var normalized = normalizeSelection(selection);
    try {
      if (!normalized) {
        storage.removeItem(SELECTION_STORAGE_KEY);
        return true;
      }
      storage.setItem(SELECTION_STORAGE_KEY, JSON.stringify(normalized));
      return true;
    } catch (err) {
      return false;
    }
  }

  function clearSelection(storage) {
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

  function resolveActiveTemplateId(rawStore, rawSelection, quoteNo) {
    var selected = selectionForQuote(rawSelection, quoteNo);
    if (selected && isSelectable(rawStore, selected)) return selected;
    return Store.defaultTemplateId(rawStore);
  }

  function resolveActiveTemplate(rawStore, rawSelection, quoteNo) {
    var id = resolveActiveTemplateId(rawStore, rawSelection, quoteNo);
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
    var selection = makeSelection(quoteNo, id, options);
    if (!selection) return fail("invalid_quote_no");
    if (!writeSelection(storage, selection)) return fail("selection_storage_failed");
    return ok("selected", { selection: selection, template: Store.getTemplate(store, id) });
  }

  function setDefaultTemplate(storage, templateId) {
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    var result = Store.setDefaultTemplate(store, id);
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    return ok(result.code, { template: result.template });
  }

  function renameTemplate(storage, templateId, name) {
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    if (!isSelectable(store, id) && !Store.getTemplate(store, id)) return fail("template_not_found");
    var trimmed = String(name == null ? "" : name).trim();
    if (!trimmed) return fail("invalid_template_name");
    var result = Store.updateTemplate(store, id, { name: trimmed.slice(0, MAX_SELECTION_NAME_CHARS) });
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    return ok("renamed", { template: result.template });
  }

  function duplicateTemplate(storage, templateId, options) {
    var store = Store.readStore(storage);
    var id = boundedId(templateId);
    if (!id) return fail("invalid_template_id");
    var opts = options || {};
    var result = Store.duplicateTemplate(store, id, { now: stampOf(opts), name: opts.name });
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    return ok("duplicated", { template: result.template });
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

    /* 삭제된 양식을 쓰던 견적은 다음 해석에서 기본 양식으로 안전하게 되돌아간다. */
    var selection = readSelection(storage);
    if (selection && selection.templateId === id) writeSelection(storage, null);

    return ok("deleted", { templateId: id, defaultTemplateId: Store.defaultTemplateId(result.store) });
  }

  /* 새 양식 만들기 = 현재 활성(승인된) 양식을 본뜬 candidate. 승인 전에는 적용할 수 없다. */
  function createCandidate(storage, options) {
    var store = Store.readStore(storage);
    var opts = options || {};
    var sourceId = boundedId(opts.sourceTemplateId) || resolveActiveTemplateId(store, readSelection(storage), opts.quoteNo);
    var source = Store.getTemplate(store, sourceId);
    if (!source) return fail("template_not_found");

    var result = Store.createTemplate(
      store,
      { name: typeof opts.name === "string" && opts.name.trim() ? opts.name.trim() : source.name + " 사본", content: source.content },
      { now: stampOf(opts) }
    );
    if (!result.ok) return fail(result.code, result.message);
    if (!Store.writeStore(storage, result.store)) return fail("template_storage_failed");
    return ok("created", { template: result.template });
  }

  return {
    SELECTION_SCHEMA_VERSION: SELECTION_SCHEMA_VERSION,
    SELECTION_STORAGE_KEY: SELECTION_STORAGE_KEY,
    normalizeSelection: normalizeSelection,
    selectionForQuote: selectionForQuote,
    makeSelection: makeSelection,
    readSelection: readSelection,
    writeSelection: writeSelection,
    clearSelection: clearSelection,
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
