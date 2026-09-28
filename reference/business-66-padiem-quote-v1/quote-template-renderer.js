/* B66 · Quote Beta — quote-template-renderer.js
   normalized QuoteDraft + 승인된 QuoteTemplateProfile → 결정적 render projection.
   모델 호출이 없고, 금액·세금·유효일은 오직 QuoteCore 에서 파생된다.
   순수 계산(buildRenderModel)과 DOM 적용(applyRenderModel)을 분리한다. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory(require("./quote-core.js"), require("./quote-template.js"));
  } else {
    root.QuoteTemplateRenderer = factory(root.QuoteCore, root.QuoteTemplate);
  }
})(typeof self !== "undefined" ? self : this, function (Core, Template) {
  "use strict";

  if (!Core) throw new Error("QuoteCore is required");
  if (!Template) throw new Error("QuoteTemplate is required");

  var RENDER_MODEL_SCHEMA_VERSION = 1;
  var CALCULATION_AUTHORITY = "quote-core";

  var escapeHtml = Template.escapeHtml;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function textOrDash(value) {
    var v = String(value == null ? "" : value).trim();
    return v || "-";
  }

  /* 프로필의 표현 문자열은 템플릿이 소유하고, 값은 QuoteCore 파생값만 쓴다. */
  function buildRenderModel(draft, profile, options) {
    var normalizedDraft = Core.normalizeDraft(draft);
    if (!normalizedDraft) return null;

    /* 잘못된 프로필은 계산을 멈추지 않고 내장 기본으로 되돌린다(기본은 항상 존재). */
    var stored = Template.normalizeTemplate(profile);
    var template = stored || Template.builtInTemplate();
    var content = template.content;
    var opts = isPlainObject(options) ? options : {};
    var provisional = opts.taxReviewRequired === true;

    var sections = content.sections.slice();
    var has = function (name) { return sections.indexOf(name) !== -1; };

    var totals = Core.computeTotals(normalizedDraft.items, normalizedDraft.tax.mode);
    var validUntil = Core.computeValidUntil(normalizedDraft.meta.issueDate, normalizedDraft.meta.validDays);
    var mode = normalizedDraft.tax.mode;

    var emptyNameText = content.items.emptyNameText;
    var columns = has("items") ? content.items.columns.map(function (column) {
      return { key: column.key, label: column.label, width: column.width, align: column.align };
    }) : [];

    var items = has("items") ? normalizedDraft.items.map(function (item, index) {
      var emptyName = !String(item.name == null ? "" : item.name);
      return {
        index: index,
        emptyName: emptyName,
        values: {
          name: emptyName ? emptyNameText : item.name,
          qty: Core.formatInputNumber(item.qty),
          unitPrice: Core.formatMoney(item.unitPrice),
          amount: Core.formatMoney(totals.amounts[index])
        }
      };
    }) : [];

    var senderContact = [
      String(normalizedDraft.sender.phone == null ? "" : normalizedDraft.sender.phone).trim(),
      String(normalizedDraft.sender.email == null ? "" : normalizedDraft.sender.email).trim()
    ].filter(Boolean).join(content.sender.contactSeparator) || content.fallbackText;

    return {
      schemaVersion: RENDER_MODEL_SCHEMA_VERSION,
      derivedBy: CALCULATION_AUTHORITY,
      template: {
        id: template.id,
        name: template.name,
        builtin: template.builtin,
        fingerprint: template.fingerprint
      },
      sections: sections,
      page: isPlainObject(content.page) ? content.page : {},
      style: isPlainObject(content.style) ? content.style : {},
      columns: columns,
      titleText: has("title") ? content.title.text : "",
      meta: {
        quoteNoText: has("meta") ? content.meta.quoteNoPrefix + textOrDash(normalizedDraft.meta.quoteNo) : "",
        dateText: has("meta") ? content.meta.issueDatePrefix + textOrDash(normalizedDraft.meta.issueDate) : "",
        validityText: has("meta")
          ? content.meta.validityPrefix + normalizedDraft.meta.validDays + content.meta.validityUnit
          : "",
        validUntilText: has("meta") ? content.meta.validUntilPrefix + (validUntil || content.fallbackText) : "",
        taxText: has("meta")
          ? (provisional ? content.meta.taxReviewText : content.meta.taxPrefix + Core.TAX_LABELS[mode])
          : ""
      },
      parties: {
        sender: {
          heading: has("parties") ? content.sender.heading : "",
          company: has("parties") ? textOrDash(normalizedDraft.sender.company) : "",
          rep: has("parties") ? content.sender.repPrefix + textOrDash(normalizedDraft.sender.rep) : "",
          bizNo: has("parties") ? content.sender.bizNoPrefix + textOrDash(normalizedDraft.sender.bizNo) : "",
          address: has("parties") ? textOrDash(normalizedDraft.sender.address) : "",
          contact: has("parties") ? senderContact : ""
        },
        recipient: {
          heading: has("parties") ? content.recipient.heading : "",
          company: has("parties") ? textOrDash(normalizedDraft.recipient.company) : "",
          person: has("parties") ? content.recipient.personPrefix + textOrDash(normalizedDraft.recipient.person) : "",
          address: has("parties") ? textOrDash(normalizedDraft.recipient.address) : "",
          email: has("parties")
            ? (String(normalizedDraft.recipient.email == null ? "" : normalizedDraft.recipient.email).trim() || content.fallbackText)
            : ""
        }
      },
      items: items,
      totals: {
        subtotalLabel: has("totals")
          ? (provisional ? content.totals.provisional.subtotalLabel : content.totals.supplyLabel)
          : "",
        subtotalText: has("totals") ? Core.formatMoney(provisional ? totals.subtotal : totals.supply) : "",
        vatLabel: has("totals")
          ? (provisional
            ? content.totals.provisional.vatLabel
            : (content.totals.vatLabels[mode] || content.totals.vatLabels.EXCLUSIVE))
          : "",
        vatText: has("totals")
          ? (provisional ? content.totals.provisional.vatText : Core.formatMoney(totals.vat))
          : "",
        grandLabel: has("totals")
          ? (provisional ? content.totals.provisional.grandLabel : content.totals.grandLabel)
          : "",
        grandText: has("totals")
          ? (provisional ? content.totals.provisional.grandText : Core.formatMoney(totals.grand))
          : ""
      },
      memoText: has("memo")
        ? (String(normalizedDraft.memo == null ? "" : normalizedDraft.memo).trim() || content.memo.emptyText)
        : "",
      markText: has("mark") ? content.mark.text : "",
      taxReview: { required: provisional }
    };
  }

  /* ── 얇은 DOM adapter: projection 을 기존 화면 요소에 적용한다 ── */

  function applyRenderModel(doc, model) {
    if (!doc || typeof doc.getElementById !== "function" || !isPlainObject(model)) return false;

    var setText = function (id, value) {
      var el = doc.getElementById(id);
      if (el) el.textContent = value == null ? "" : String(value);
    };
    var setHtml = function (id, html) {
      var el = doc.getElementById(id);
      if (el) el.innerHTML = html;
    };

    var sender = model.parties.sender;
    var recipient = model.parties.recipient;
    var totals = model.totals;

    setText("pvTitle", model.titleText);
    setText("pvQuoteNo", model.meta.quoteNoText);
    setText("pvDate", model.meta.dateText);
    setText("pvValidity", model.meta.validityText);
    setText("pvValidUntil", model.meta.validUntilText);
    setText("pvTaxMode", model.meta.taxText);

    setText("pvSenderHeading", sender.heading);
    setText("pvSenderCompany", sender.company);
    setText("pvSenderRep", sender.rep);
    setText("pvSenderBizNo", sender.bizNo);
    setText("pvSenderAddress", sender.address);
    setText("pvSenderContact", sender.contact);

    setText("pvRecipientHeading", recipient.heading);
    setText("pvRecipientCompany", recipient.company);
    setText("pvRecipientPerson", recipient.person);
    setText("pvRecipientAddress", recipient.address);
    setText("pvRecipientEmail", recipient.email);

    setHtml("pvItemsHead", model.columns.map(function (column) {
      var width = column.width ? ' style="width:' + escapeHtml(column.width) + '"' : "";
      return "<th" + width + ">" + escapeHtml(column.label) + "</th>";
    }).join(""));

    setHtml("pvItems", model.items.map(function (item) {
      var cells = model.columns.map(function (column) {
        if (column.key === "name") {
          return '<td class="' + (item.emptyName ? "empty" : "") + '">' + escapeHtml(item.values.name) + "</td>";
        }
        return "<td>" + escapeHtml(item.values[column.key]) + "</td>";
      }).join("");
      return "<tr>" + cells + "</tr>";
    }).join(""));

    setText("subtotalLabelText", totals.subtotalLabel);
    setText("subtotalText", totals.subtotalText);
    setText("vatLabelText", totals.vatLabel);
    setText("vatText", totals.vatText);
    setText("grandLabelText", totals.grandLabel);
    setText("grandText", totals.grandText);

    setText("pvSubtotalLabel", totals.subtotalLabel);
    setText("pvSubtotal", totals.subtotalText);
    setText("pvVatLabel", totals.vatLabel);
    setText("pvVat", totals.vatText);
    setText("pvGrandLabel", totals.grandLabel);
    setText("pvGrand", totals.grandText);

    setText("pvMemo", model.memoText);
    setText("pvMark", model.markText);

    return true;
  }

  return {
    RENDER_MODEL_SCHEMA_VERSION: RENDER_MODEL_SCHEMA_VERSION,
    CALCULATION_AUTHORITY: CALCULATION_AUTHORITY,
    escapeHtml: escapeHtml,
    buildRenderModel: buildRenderModel,
    applyRenderModel: applyRenderModel
  };
});
