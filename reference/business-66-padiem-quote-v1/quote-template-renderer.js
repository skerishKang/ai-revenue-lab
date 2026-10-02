/* B66 · Quote Beta — quote-template-renderer.js
   normalized QuoteDraft + 승인된 QuoteTemplateProfile → 결정적 render projection.

   - 모델 호출이 없고, 금액·세금·유효일은 오직 QuoteCore 에서 파생된다.
   - 승인되지 않은 user profile 은 내장 기본으로 fallback 하고 이유를 남긴다.
   - 스타일·페이지는 bounded/validated 값만 CSS custom property 와 @page 규칙으로 적용한다.
     임의 CSS 문자열 실행은 하지 않는다.
   - 순수 계산(buildRenderModel)과 DOM 적용(applyRenderModel)을 분리한다. */

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
  var PAGE_RULE_STYLE_ID = "quote-template-page";
  var ASSET_ID_PATTERN = /^b66asset_[0-9a-f]{32}$/;
  var DATA_IMAGE_PATTERN = /^data:image\/(?:png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/;
  var MAX_SLOT_SOURCE_CHARS = 384 * 1024;

  var escapeHtml = Template.escapeHtml;

  var RULE_PATTERN = /^[0-9A-Za-z#.,%()\- ]{1,64}$/;
  var HEX_PATTERN = /^#[0-9a-fA-F]{3,8}$/;
  var MEASURE_PATTERN = /^[0-9A-Za-z.%]{1,16}$/;
  var PAGE_MARGIN_PATTERN = /^\d{1,2}(?:\.\d{1,2})?(?:mm|cm|in)$/;

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function textOrDash(value) {
    var v = String(value == null ? "" : value).trim();
    return v || "-";
  }

  var isRule = function (value) { return typeof value === "string" && RULE_PATTERN.test(value); };
  var isHex = function (value) { return typeof value === "string" && HEX_PATTERN.test(value); };
  var isMeasure = function (value) { return typeof value === "string" && MEASURE_PATTERN.test(value); };
  var isAlignment = function (value) { return Template.ALLOWED_ALIGNMENTS.indexOf(value) !== -1; };
  var isJustify = function (value) { return Template.ALLOWED_JUSTIFY.indexOf(value) !== -1; };

  /* 프로필 스타일 → 실제 CSS custom property. 값은 이미 검증되어 있고, 여기서도 재검증한다. */
  var STYLE_VARIABLE_MAP = [
    ["--quote-accent", "accent", isHex],
    ["--quote-title-rule", "titleRule", isRule],
    ["--quote-header-rule", "tableHeaderRule", isRule],
    ["--quote-row-rule", "tableRowRule", isRule],
    ["--quote-party-rule", "partyRule", isRule],
    ["--quote-memo-rule", "memoRule", isRule],
    ["--quote-header-align", "headerAlignment", isJustify],
    ["--quote-meta-align", "metaAlignment", isAlignment],
    ["--quote-numeric-align", "numericAlignment", isAlignment],
    ["--quote-text-align", "textAlignment", isAlignment],
    ["--quote-totals-width", "totalsWidth", isMeasure]
  ];

  function buildStyleVariables(style) {
    var source = isPlainObject(style) ? style : {};
    var variables = {};
    STYLE_VARIABLE_MAP.forEach(function (entry) {
      var value = source[entry[1]];
      if (entry[2](value)) variables[entry[0]] = value;
    });
    return variables;
  }

  /* 프로필 페이지 규칙 → bounded @page 문자열. enum/정규식 검증을 통과한 값만 조합한다. */
  function buildPageRule(page) {
    var source = isPlainObject(page) ? page : {};
    var size = Template.ALLOWED_PAGE_SIZES.indexOf(source.size) === -1 ? "A4" : source.size;
    var margin = typeof source.margin === "string" && PAGE_MARGIN_PATTERN.test(source.margin)
      ? source.margin
      : "10mm";
    var landscape = source.orientation === "landscape";
    return "@page { size: " + (landscape ? size + " landscape" : size) + "; margin: " + margin + "; }";
  }

  function resolvePrivateSlot(assetId, rawSource) {
    var id = typeof assetId === "string" && ASSET_ID_PATTERN.test(assetId) ? assetId : "";
    if (!id || !isPlainObject(rawSource) || rawSource.assetId !== id) {
      return { assetId: id, src: "", rendered: false };
    }
    var src = typeof rawSource.dataUrl === "string" ? rawSource.dataUrl : "";
    if (!src || src.length > MAX_SLOT_SOURCE_CHARS || !DATA_IMAGE_PATTERN.test(src)) {
      return { assetId: id, src: "", rendered: false };
    }
    return { assetId: id, src: src, rendered: true };
  }

  /* 프로필의 표현 문자열은 템플릿이 소유하고, 값은 QuoteCore 파생값만 쓴다. */
  function buildRenderModel(draft, profile, options) {
    var normalizedDraft = Core.normalizeDraft(draft);
    if (!normalizedDraft) return null;

    /* 승인 경계: 미승인 candidate 는 활성 profile 이 될 수 없다. 내장 기본만 예외다. */
    var stored = Template.normalizeTemplate(profile);
    var fallbackReason = null;
    var template;
    if (!stored) {
      template = Template.builtInTemplate();
      fallbackReason = "invalid_template_profile";
    } else if (!stored.approved) {
      /* 승인 전 preview 전용 분기: 동일 파이프라인으로 candidate 내용을 렌더하되
         미승인 preview 임을 모델에 명시한다. 저장/활성화 경로가 아니다. */
      if (isPlainObject(options) && options.previewUnapprovedCandidate === true) {
        template = stored;
        fallbackReason = "preview_unapproved_candidate";
      } else {
        template = Template.builtInTemplate();
        fallbackReason = "template_not_approved";
      }
    } else {
      template = stored;
    }

    var content = template.content;
    var opts = isPlainObject(options) ? options : {};
    var provisional = opts.taxReviewRequired === true;

    var sections = content.sections.slice();
    var has = function (name) { return sections.indexOf(name) !== -1; };

    var totals = Core.computeDraftTotals(normalizedDraft);
    if (!totals) return null;
    var validUntil = Core.computeValidUntil(normalizedDraft.meta.issueDate, normalizedDraft.meta.validDays);
    var mode = normalizedDraft.tax.mode;

    var emptyNameText = content.items.emptyNameText;
    var columns = has("items") ? content.items.columns.map(function (column) {
      return { key: column.key, label: column.label, width: column.width, align: column.align };
    }) : [];

    var effectiveItems = Array.isArray(totals.effectiveItems) ? totals.effectiveItems : normalizedDraft.items;
    var items = has("items") ? effectiveItems.map(function (item, index) {
      var emptyName = !String(item.name == null ? "" : item.name);
      return {
        index: index,
        emptyName: emptyName,
        filler: false,
        values: {
          no: String(index + 1),
          name: emptyName ? emptyNameText : item.name,
          spec: String(item.spec == null ? "" : item.spec),
          unit: String(item.unit == null ? "" : item.unit),
          qty: Core.formatInputNumber(item.qty),
          unitPrice: Core.formatMoney(item.unitPrice),
          amount: Core.formatMoney(totals.amounts[index]),
          note: String(item.note == null ? "" : item.note)
        }
      };
    }) : [];
    var minRows = Number(content.items && content.items.minRows);
    if (has("items") && Number.isInteger(minRows) && minRows > items.length) {
      while (items.length < minRows) {
        items.push({
          index: items.length,
          emptyName: false,
          filler: true,
          values: { no: "", name: "", spec: "", unit: "", qty: "", unitPrice: "", amount: "", note: "" }
        });
      }
    }

    var detailPages = [];
    if (has("detailPages") && content.detailPages && Array.isArray(totals.detailGroups)) {
      var detailColumns = content.detailPages.columns.map(function (column) {
        return { key: column.key, label: column.label, width: column.width, align: column.align };
      });
      detailPages = totals.detailGroups.map(function (group, groupIndex) {
        var rows = group.items.map(function (item, itemIndex) {
          return {
            index: itemIndex,
            section: String(item.section == null ? "" : item.section),
            nameRowSpan: 1,
            suppressName: false,
            values: {
              no: String(itemIndex + 1),
              name: String(item.name == null ? "" : item.name),
              spec: String(item.spec == null ? "" : item.spec),
              unit: String(item.unit == null ? "" : item.unit),
              qty: Core.formatInputNumber(item.qty),
              unitPrice: Core.formatMoney(item.unitPrice),
              amount: Core.formatMoney(group.amounts[itemIndex]),
              note: String(item.note == null ? "" : item.note)
            }
          };
        });
        if (content.detailPages.mergeRepeatedName === true) {
          var start = 0;
          while (start < rows.length) {
            var end = start + 1;
            while (
              end < rows.length &&
              rows[end].values.name === rows[start].values.name &&
              rows[end].section === rows[start].section
            ) {
              end += 1;
            }
            rows[start].nameRowSpan = end - start;
            for (var mergeIndex = start + 1; mergeIndex < end; mergeIndex += 1) {
              rows[mergeIndex].suppressName = true;
            }
            start = end;
          }
        }
        return {
          id: group.id,
          summaryItemId: group.summaryItemId,
          titleText: content.detailPages.titlePrefix + (group.title || String(groupIndex + 1)),
          columns: detailColumns,
          rows: rows,
          subtotalLabel: content.detailPages.subtotalLabel,
          subtotalText: Core.formatMoney(group.subtotal),
          finalLabel: content.detailPages.finalLabel || "",
          finalText: content.detailPages.finalLabel ? Core.formatMoney(group.subtotal) : ""
        };
      });
    }

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
        approved: template.approved,
        approvalBasis: template.approvalBasis,
        fingerprint: template.fingerprint,
        fallbackReason: fallbackReason
      },
      sections: sections,
      layoutVariant: typeof content.layoutVariant === "string" ? content.layoutVariant : "",
      page: isPlainObject(content.page) ? content.page : {},
      pageRule: buildPageRule(content.page),
      style: isPlainObject(content.style) ? content.style : {},
      styleVariables: buildStyleVariables(content.style),
      slots: (function () {
        var sources = isPlainObject(opts.slotSources) ? opts.slotSources : {};
        var logo = resolvePrivateSlot(String(content.slots && content.slots.logo || ""), sources.logo);
        var stamp = resolvePrivateSlot(String(content.slots && content.slots.stamp || ""), sources.stamp);
        return {
          support: Template.SLOT_SUPPORT,
          rendered: logo.rendered || stamp.rendered,
          logo: logo,
          stamp: stamp
        };
      })(),
      columns: columns,
      titleText: has("title") ? content.title.text : "",
      projectNameText: has("project") && content.project && normalizedDraft.meta.projectName
        ? content.project.prefix + normalizedDraft.meta.projectName
        : "",
      writtenTotalText: has("writtenTotal") && content.writtenTotal
        ? content.writtenTotal.prefix + (Core.formatKoreanMoneyWords(totals.grand) || content.fallbackText) + content.writtenTotal.suffix
        : "",
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
      detailPages: detailPages,
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
        ? ((content.memo && content.memo.heading ? content.memo.heading + "\n" : "") +
          (String(normalizedDraft.memo == null ? "" : normalizedDraft.memo).trim() || content.memo.emptyText))
        : "",
      markText: has("mark") ? content.mark.text : "",
      taxReview: { required: provisional }
    };
  }

  /* ── 얇은 DOM adapter: projection 을 기존 화면 요소에 적용한다 ── */

  function ensurePageRule(doc, rule) {
    if (!doc || typeof doc.createElement !== "function") return false;
    var head = doc.head || (typeof doc.getElementsByTagName === "function" ? doc.getElementsByTagName("head")[0] : null);
    if (!head || typeof head.appendChild !== "function") return false;

    var element = typeof doc.getElementById === "function" ? doc.getElementById(PAGE_RULE_STYLE_ID) : null;
    if (!element) {
      element = doc.createElement("style");
      element.id = PAGE_RULE_STYLE_ID;
      head.appendChild(element);
    }
    element.textContent = rule;
    return true;
  }

  function applyStyleVariables(doc, model) {
    var paper = typeof doc.getElementById === "function" ? doc.getElementById("quotePaper") : null;
    if (!paper || !paper.style || typeof paper.style.setProperty !== "function") return false;
    var targets = [paper];
    if (typeof doc.querySelectorAll === "function") {
      Array.prototype.forEach.call(
        doc.querySelectorAll("#pvDetailPages .quote-detail-page"),
        function (detailPage) { targets.push(detailPage); }
      );
    }
    targets.forEach(function (target) {
      if (!target || !target.style || typeof target.style.setProperty !== "function") return;
      Object.keys(model.styleVariables).forEach(function (name) {
        target.style.setProperty(name, model.styleVariables[name]);
      });
    });
    return true;
  }

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
    var paper = doc.getElementById("quotePaper");
    if (paper && typeof paper.setAttribute === "function") {
      if (model.layoutVariant) paper.setAttribute("data-layout-variant", model.layoutVariant);
      else if (typeof paper.removeAttribute === "function") paper.removeAttribute("data-layout-variant");
    }

    setText("pvTitle", model.titleText);
    setText("pvQuoteNo", model.meta.quoteNoText);
    setText("pvDate", model.meta.dateText);
    setText("pvValidity", model.meta.validityText);
    setText("pvValidUntil", model.meta.validUntilText);
    setText("pvTaxMode", model.meta.taxText);
    setText("pvProjectName", model.projectNameText);
    setText("pvWrittenTotal", model.writtenTotalText);

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
      var styles = [];
      if (column.width) styles.push("width:" + escapeHtml(column.width));
      if (model.layoutVariant && column.align) styles.push("text-align:" + escapeHtml(column.align));
      var style = styles.length ? ' style="' + styles.join(";") + '"' : "";
      return "<th" + style + ">" + escapeHtml(column.label) + "</th>";
    }).join(""));

    setHtml("pvItems", model.items.map(function (item) {
      var cells = model.columns.map(function (column) {
        var style = model.layoutVariant && column.align
          ? ' style="text-align:' + escapeHtml(column.align) + '"'
          : "";
        if (column.key === "name") {
          var cls = ' class="' + (item.emptyName ? "empty" : "") + '"';
          return "<td" + cls + style + ">" + escapeHtml(item.values.name) + "</td>";
        }
        return "<td" + style + ">" + escapeHtml(item.values[column.key]) + "</td>";
      }).join("");
      return item.filler
        ? '<tr class="quote-filler-row">' + cells + "</tr>"
        : "<tr>" + cells + "</tr>";
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

    setHtml("pvDetailPages", (Array.isArray(model.detailPages) ? model.detailPages : []).map(function (page) {
      var head = page.columns.map(function (column) {
        var styles = [];
        if (column.width) styles.push("width:" + escapeHtml(column.width));
        if (model.layoutVariant && column.align) styles.push("text-align:" + escapeHtml(column.align));
        var style = styles.length ? ' style="' + styles.join(";") + '"' : "";
        return "<th" + style + ">" + escapeHtml(column.label) + "</th>";
      }).join("");
      var lastSection = null;
      var body = page.rows.map(function (row) {
        var sectionHtml = "";
        if (row.section && row.section !== lastSection) {
          lastSection = row.section;
          sectionHtml = '<tr class="quote-detail-section"><td colspan="' +
            page.columns.length + '">' + escapeHtml(row.section) + "</td></tr>";
        }
        var cells = page.columns.map(function (column) {
          if (column.key === "name" && row.suppressName) return "";
          var styles = [];
          if (model.layoutVariant && column.align) styles.push("text-align:" + escapeHtml(column.align));
          var style = styles.length ? ' style="' + styles.join(";") + '"' : "";
          var rowspan = column.key === "name" && row.nameRowSpan > 1
            ? ' rowspan="' + row.nameRowSpan + '"'
            : "";
          return "<td" + rowspan + style + ">" + escapeHtml(row.values[column.key]) + "</td>";
        }).join("");
        return sectionHtml + "<tr>" + cells + "</tr>";
      }).join("");
      var layoutAttr = model.layoutVariant
        ? ' data-layout-variant="' + escapeHtml(model.layoutVariant) + '"'
        : "";
      return '<section class="quote-paper quote-detail-page" data-detail-group="' + escapeHtml(page.id) + '"' + layoutAttr + '>' +
        '<h2 class="quote-detail-title">' + escapeHtml(page.titleText) + "</h2>" +
        '<table class="quote-table"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table>" +
        '<div class="quote-detail-subtotal"><span>' + escapeHtml(page.subtotalLabel) +
        '</span><strong>' + escapeHtml(page.subtotalText) + "</strong></div>" +
        (page.finalLabel
          ? '<div class="quote-detail-final"><span>' + escapeHtml(page.finalLabel) +
            '</span><strong>' + escapeHtml(page.finalText) + "</strong></div>"
          : "") +
        "</section>";
    }).join(""));

    var setPrivateImage = function (id, slot) {
      var el = doc.getElementById(id);
      if (!el) return;
      var source = isPlainObject(slot) && slot.rendered === true ? slot.src : "";
      if (source) {
        el.setAttribute("src", source);
        el.hidden = false;
      } else {
        el.removeAttribute("src");
        el.hidden = true;
      }
    };
    setPrivateImage("pvLogo", model.slots && model.slots.logo);
    setPrivateImage("pvStamp", model.slots && model.slots.stamp);

    /* 스타일/페이지: 검증된 custom property 와 bounded @page 규칙만 적용한다. */
    applyStyleVariables(doc, model);
    ensurePageRule(doc, model.pageRule);

    return true;
  }

  return {
    RENDER_MODEL_SCHEMA_VERSION: RENDER_MODEL_SCHEMA_VERSION,
    CALCULATION_AUTHORITY: CALCULATION_AUTHORITY,
    PAGE_RULE_STYLE_ID: PAGE_RULE_STYLE_ID,
    STYLE_VARIABLE_MAP: STYLE_VARIABLE_MAP,
    escapeHtml: escapeHtml,
    buildStyleVariables: buildStyleVariables,
    buildPageRule: buildPageRule,
    buildRenderModel: buildRenderModel,
    applyRenderModel: applyRenderModel
  };
});