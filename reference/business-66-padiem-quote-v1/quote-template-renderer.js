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
  var CERTIFIED_PREVIEW_URL = /^\/api\/[A-Za-z0-9_/?=&.%-]{1,480}$/;
  var CGI_PREVIEW_PAGE_WIDTH = 595;

  var escapeHtml = Template.escapeHtml;

  var RULE_PATTERN = /^[0-9A-Za-z#.,%()\- ]{1,64}$/;
  var HEX_PATTERN = /^#[0-9a-fA-F]{3,8}$/;
  var MEASURE_PATTERN = /^[0-9A-Za-z.%]{1,16}$/;
  var PAGE_MARGIN_PATTERN = /^\d{1,2}(?:\.\d{1,2})?(?:mm|cm|in)$/;
  var PAGE_SIZE_DIMENSIONS = {
    A4: ["210mm", "297mm"],
    A5: ["148mm", "210mm"],
    Letter: ["8.5in", "11in"],
    Legal: ["8.5in", "14in"]
  };

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function textOrDash(value) {
    var v = String(value == null ? "" : value).trim();
    return v || "-";
  }

  function formatIssueDate(value, format) {
    var raw = String(value == null ? "" : value).trim();
    if (!raw || format === undefined || format === null || format === "" || format === "iso") return raw;
    var match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
    if (!match) return raw;
    if (format === "yyyy. mm.") return match[1] + ". " + match[2] + ".";
    if (format === "yyyy. mm. dd.") return match[1] + ". " + match[2] + ". " + match[3] + ".";
    return raw;
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

  function buildPageStyleVariables(page) {
    var source = isPlainObject(page) ? page : {};
    var size = Template.ALLOWED_PAGE_SIZES.indexOf(source.size) === -1 ? "A4" : source.size;
    var dimensions = PAGE_SIZE_DIMENSIONS[size] || PAGE_SIZE_DIMENSIONS.A4;
    var landscape = source.orientation === "landscape";
    var margin = typeof source.margin === "string" && PAGE_MARGIN_PATTERN.test(source.margin)
      ? source.margin
      : "10mm";
    return {
      "--quote-page-width": landscape ? dimensions[1] : dimensions[0],
      "--quote-page-height": landscape ? dimensions[0] : dimensions[1],
      "--quote-page-margin": margin
    };
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

    var senderContactValue = [
      String(normalizedDraft.sender.phone == null ? "" : normalizedDraft.sender.phone).trim(),
      String(normalizedDraft.sender.email == null ? "" : normalizedDraft.sender.email).trim()
    ].filter(Boolean).join(content.sender.contactSeparator);
    var senderContact = senderContactValue
      ? (String(content.sender.contactPrefix || "") + senderContactValue)
      : content.fallbackText;

    var recipientCompany = textOrDash(normalizedDraft.recipient.company);
    if (content.recipient.suffix) recipientCompany += " " + content.recipient.suffix;

    var summaryTerms = [];
    if (isPlainObject(content.summaryTerms)) {
      if (isPlainObject(content.summaryTerms.validity)) {
        summaryTerms.push({
          label: content.summaryTerms.validity.label,
          value: content.summaryTerms.validity.valuePrefix +
            normalizedDraft.meta.validDays +
            content.summaryTerms.validity.valueSuffix
        });
      }
      if (Array.isArray(content.summaryTerms.rows)) {
        content.summaryTerms.rows.forEach(function (row) {
          summaryTerms.push({ label: row.label, value: row.value });
        });
      }
    }

    var supplyLabel = content.totals.supplyLabel;
    if (!provisional && supplyLabel.indexOf("{firstItemName}") !== -1) {
      var firstItemName = effectiveItems.length
        ? String(effectiveItems[0].name == null ? "" : effectiveItems[0].name).trim()
        : "";
      supplyLabel = supplyLabel.split("{firstItemName}").join(firstItemName || content.fallbackText);
    }

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
      cgiV2: isPlainObject(content.cgiV2) ? content.cgiV2 : null,
      certifiedPreviewBaseUrl: typeof opts.certifiedPreviewBaseUrl === "string" && CERTIFIED_PREVIEW_URL.test(opts.certifiedPreviewBaseUrl)
        ? opts.certifiedPreviewBaseUrl
        : "",
      facts: {
        meta: {
          quoteNo: String(normalizedDraft.meta.quoteNo == null ? "" : normalizedDraft.meta.quoteNo),
          issueDate: String(normalizedDraft.meta.issueDate == null ? "" : normalizedDraft.meta.issueDate),
          issueDateDisplay: formatIssueDate(normalizedDraft.meta.issueDate, "yyyy. mm. dd."),
          validDays: normalizedDraft.meta.validDays,
          projectName: String(normalizedDraft.meta.projectName == null ? "" : normalizedDraft.meta.projectName)
        },
        sender: {
          company: String(normalizedDraft.sender.company == null ? "" : normalizedDraft.sender.company),
          rep: String(normalizedDraft.sender.rep == null ? "" : normalizedDraft.sender.rep),
          contactPerson: String(normalizedDraft.sender.contactPerson == null ? "" : normalizedDraft.sender.contactPerson),
          bizNo: String(normalizedDraft.sender.bizNo == null ? "" : normalizedDraft.sender.bizNo),
          address: String(normalizedDraft.sender.address == null ? "" : normalizedDraft.sender.address),
          phone: String(normalizedDraft.sender.phone == null ? "" : normalizedDraft.sender.phone),
          email: String(normalizedDraft.sender.email == null ? "" : normalizedDraft.sender.email)
        },
        recipient: {
          company: String(normalizedDraft.recipient.company == null ? "" : normalizedDraft.recipient.company),
          person: String(normalizedDraft.recipient.person == null ? "" : normalizedDraft.recipient.person),
          address: String(normalizedDraft.recipient.address == null ? "" : normalizedDraft.recipient.address),
          email: String(normalizedDraft.recipient.email == null ? "" : normalizedDraft.recipient.email)
        },
        taxRateText: Number.isFinite(Number(normalizedDraft.tax.rate))
          ? String(Math.round(Number(normalizedDraft.tax.rate) * 100)) + "%"
          : ""
      },
      page: isPlainObject(content.page) ? content.page : {},
      pageRule: buildPageRule(content.page),
      style: isPlainObject(content.style) ? content.style : {},
      styleVariables: Object.assign(
        {},
        buildStyleVariables(content.style),
        buildPageStyleVariables(content.page)
      ),
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
      itemsHeadingText: has("items") ? String(content.items.heading || "") : "",
      summaryTerms: summaryTerms,
      projectNameText: has("project") && content.project && normalizedDraft.meta.projectName
        ? content.project.prefix + normalizedDraft.meta.projectName
        : "",
      writtenTotalText: has("writtenTotal") && content.writtenTotal
        ? content.writtenTotal.prefix + (Core.formatKoreanMoneyWords(totals.grand) || content.fallbackText) + content.writtenTotal.suffix
        : "",
      meta: {
        quoteNoText: has("meta") ? content.meta.quoteNoPrefix + textOrDash(normalizedDraft.meta.quoteNo) : "",
        dateText: has("meta")
          ? content.meta.issueDatePrefix + textOrDash(formatIssueDate(normalizedDraft.meta.issueDate, content.meta.issueDateFormat))
          : "",
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
          contactPerson: has("parties") && content.sender.contactPersonPrefix && String(normalizedDraft.sender.contactPerson || "").trim()
            ? content.sender.contactPersonPrefix + String(normalizedDraft.sender.contactPerson).trim()
            : "",
          bizNo: has("parties") ? content.sender.bizNoPrefix + textOrDash(normalizedDraft.sender.bizNo) : "",
          address: has("parties") ? textOrDash(normalizedDraft.sender.address) : "",
          contact: has("parties") ? senderContact : ""
        },
        recipient: {
          heading: has("parties") ? content.recipient.heading : "",
          company: has("parties") ? recipientCompany : "",
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
          ? (provisional ? content.totals.provisional.subtotalLabel : supplyLabel)
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

  /* 인증 PDF 입력은 기존 projection 과 QuoteCore 확정값만 전달한다.
     미리보기 자산/data URL 은 private PDF bundle 의 입력이 아니다. */
  function buildCertifiedPdfRenderModel(draft, profile, options) {
    var normalizedDraft = Core.normalizeDraft(draft);
    if (!normalizedDraft) return null;
    var model = buildRenderModel(normalizedDraft, profile, options);
    if (!model || model.template.fallbackReason || model.taxReview.required) return null;
    var coreTotals = Core.computeDraftTotals(normalizedDraft);
    if (!coreTotals || (Array.isArray(coreTotals.detailGroups) && coreTotals.detailGroups.length) ||
        (Array.isArray(model.detailPages) && model.detailPages.length)) return null;
    var writtenWords = Core.formatKoreanMoneyWords(coreTotals.grand);
    if (writtenWords === null) return null;
    return {
      schemaVersion: model.schemaVersion,
      derivedBy: model.derivedBy,
      template: model.template,
      facts: model.facts,
      items: model.items,
      totals: model.totals,
      coreTotals: coreTotals,
      writtenWords: writtenWords,
      taxReview: model.taxReview
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

  function cgiMoneyText(value) {
    return String(value == null ? "" : value)
      .replace(/^\s*₩\s*/, "")
      .replace(/\s*원$/, "");
  }

  function ensureCgiCertifiedPreview(doc) {
    var section = doc.getElementById("cgiCertifiedPreview");
    if (section) return section;
    var cgiContent = doc.getElementById("cgiV2Content");
    if (!cgiContent || !cgiContent.parentNode) return null;
    section = doc.createElement("section");
    section.id = "cgiCertifiedPreview";
    section.className = "cgi-certified-preview";
    section.hidden = true;
    var image = doc.createElement("img");
    image.id = "cgiCertifiedPreviewBase";
    image.className = "cgi-certified-preview-base";
    image.alt = "";
    image.setAttribute("aria-hidden", "true");
    var overlay = doc.createElement("div");
    overlay.id = "cgiCertifiedPreviewOverlay";
    overlay.className = "cgi-certified-preview-overlay";
    section.appendChild(image);
    section.appendChild(overlay);
    cgiContent.parentNode.insertBefore(section, cgiContent);
    return section;
  }

  function addCgiCertifiedText(doc, overlay, key, text, x, baselineY, size, options) {
    var value = String(text == null ? "" : text);
    if (!value) return;
    var opts = isPlainObject(options) ? options : {};
    var el = doc.createElement("span");
    el.className = "cgi-certified-field cgi-certified-" + key;
    el.textContent = value;
    el.style.top = (baselineY - (size * 0.80)) + "pt";
    el.style.fontSize = size + "pt";
    el.style.fontFamily = opts.fontFamily || '"Malgun Gothic", "?? ??", sans-serif';
    el.style.fontWeight = opts.bold === true ? "700" : "400";
    if (Number.isFinite(Number(opts.rightX))) {
      el.style.right = (CGI_PREVIEW_PAGE_WIDTH - Number(opts.rightX)) + "pt";
      el.style.textAlign = "right";
    } else {
      el.style.left = Number(x) + "pt";
    }
    overlay.appendChild(el);
  }

  function applyCgiCertifiedPreview(doc, model) {
    var url = typeof model.certifiedPreviewBaseUrl === "string" ? model.certifiedPreviewBaseUrl : "";
    var section = ensureCgiCertifiedPreview(doc);
    if (!section) return false;
    var image = doc.getElementById("cgiCertifiedPreviewBase");
    var overlay = doc.getElementById("cgiCertifiedPreviewOverlay");
    var cgiContent = doc.getElementById("cgiV2Content");
    var paper = doc.getElementById("quotePaper");
    if (!url || !CERTIFIED_PREVIEW_URL.test(url) || !image || !overlay) {
      section.hidden = true;
      if (paper && typeof paper.removeAttribute === "function") paper.removeAttribute("data-certified-preview");
      return false;
    }

    if (image.getAttribute("src") !== url) image.setAttribute("src", url);
    section.hidden = false;
    if (cgiContent) cgiContent.hidden = true;
    if (paper && typeof paper.setAttribute === "function") paper.setAttribute("data-certified-preview", "true");
    overlay.textContent = "";

    var facts = isPlainObject(model.facts) ? model.facts : {};
    var meta = isPlainObject(facts.meta) ? facts.meta : {};
    var recipient = isPlainObject(facts.recipient) ? facts.recipient : {};
    var bold = { bold: true };
    var right = function (x, isBold) { return { rightX: x, bold: isBold === true }; };

    addCgiCertifiedText(doc, overlay, "quote-number", meta.quoteNo, 97.52, 148.30, 10.13);
    var dateParts = String(meta.issueDate || "").split("-");
    if (dateParts.length === 3) {
      addCgiCertifiedText(doc, overlay, "date-y", dateParts[0], 97.52, 169.38, 10.13);
      addCgiCertifiedText(doc, overlay, "date-m", dateParts[1], 135.96, 169.38, 10.13);
      addCgiCertifiedText(doc, overlay, "date-d", dateParts[2], 162.70, 169.38, 10.13);
    }
    addCgiCertifiedText(doc, overlay, "recipient", recipient.company, 84.99, 211.53, 10.13, bold);
    addCgiCertifiedText(doc, overlay, "project-head", meta.projectName, 84.99, 253.68, 9.351, bold);
    addCgiCertifiedText(doc, overlay, "project-row", meta.projectName, 55.29, 331.92, 9.832, bold);

    var rowY = [353.61, 375.31, 397.13];
    var amountRight = [520.29, 519.63, 519.63];
    (Array.isArray(model.items) ? model.items : []).filter(function (item) {
      return item && item.filler !== true;
    }).slice(0, 3).forEach(function (item, index) {
      var values = isPlainObject(item.values) ? item.values : {};
      addCgiCertifiedText(doc, overlay, "item-name-" + index, values.name, 55.29, rowY[index], 9.832);
      addCgiCertifiedText(doc, overlay, "item-qty-" + index, values.qty, 0, rowY[index], 9.832, right(341.83));
      addCgiCertifiedText(doc, overlay, "item-unit-price-" + index, cgiMoneyText(values.unitPrice), 0, rowY[index], 9.832, right(426.62));
      addCgiCertifiedText(doc, overlay, "item-amount-" + index, cgiMoneyText(values.amount), 0, rowY[index], 9.832, right(amountRight[index]));
    });

    addCgiCertifiedText(doc, overlay, "subtotal", cgiMoneyText(model.totals && model.totals.subtotalText), 0, 532.70, 9.832, right(520.34, true));
    addCgiCertifiedText(doc, overlay, "vat-rate", facts.taxRateText || "", 0, 554.39, 9.832, right(243.77));
    addCgiCertifiedText(doc, overlay, "vat", cgiMoneyText(model.totals && model.totals.vatText), 0, 554.39, 9.832, right(519.98, true));
    addCgiCertifiedText(doc, overlay, "grand", cgiMoneyText(model.totals && model.totals.grandText), 0, 576.09, 9.832, right(520.34, true));

    var written = String(model.writtenTotalText || "");
    var grandText = cgiMoneyText(model.totals && model.totals.grandText);
    if (written && grandText) written += " ( \\" + grandText + " )";
    addCgiCertifiedText(
      doc, overlay, "written-total", written, 26.03, 289.00, 11.75,
      { fontFamily: 'GulimChe, Gulim, "???", "??", monospace', bold: true }
    );
    return true;
  }

  function applyCgiV2(doc, model) {
    if (!doc || !isPlainObject(model) || model.layoutVariant !== "cgi-v2") return false;
    if (applyCgiCertifiedPreview(doc, model)) return true;
    var certifiedSection = doc.getElementById("cgiCertifiedPreview");
    if (certifiedSection) certifiedSection.hidden = true;
    var facts = isPlainObject(model.facts) ? model.facts : {};
    var meta = isPlainObject(facts.meta) ? facts.meta : {};
    var sender = isPlainObject(facts.sender) ? facts.sender : {};
    var recipient = isPlainObject(facts.recipient) ? facts.recipient : {};
    var cgi = isPlainObject(model.cgiV2) ? model.cgiV2 : {};

    var setText = function (id, value) {
      var el = doc.getElementById(id);
      if (el) el.textContent = value == null ? "" : String(value);
    };
    var setHtml = function (id, html) {
      var el = doc.getElementById(id);
      if (el) el.innerHTML = html;
    };

    setText("cgiV2Title", model.titleText);
    setText("cgiV2QuoteNo", meta.quoteNo);
    setText("cgiV2IssueDate", meta.issueDateDisplay || meta.issueDate);
    setText("cgiV2Author", sender.contactPerson || sender.rep);
    setText("cgiV2AuthorTel", sender.phone);
    setText("cgiV2Recipient", recipient.company);
    setText("cgiV2RecipientPerson", recipient.person);
    setText("cgiV2RecipientTel", "");
    setText("cgiV2Project", meta.projectName);
    setText("cgiV2BizNo", sender.bizNo);
    setText("cgiV2Slogan", cgi.slogan || "");
    setText("cgiV2SenderCompany", sender.company);
    setText(
      "cgiV2SenderAddress",
      [sender.address, sender.phone ? "TEL : " + sender.phone : "", cgi.fax || ""].filter(Boolean).join("\n")
    );
    setText("cgiV2SenderRep", sender.rep);
    setText("cgiV2WrittenTotal", model.writtenTotalText);
    setText("cgiV2GrandTop", cgiMoneyText(model.totals.grandText));
    setText("cgiV2Bank", cgi.bank || "");

    setHtml("cgiV2ItemsHead", model.columns.map(function (column) {
      var styles = [];
      if (column.width) styles.push("width:" + escapeHtml(column.width));
      if (column.align) styles.push("text-align:" + escapeHtml(column.align));
      var style = styles.length ? ' style="' + styles.join(";") + '"' : "";
      return "<th" + style + ">" + escapeHtml(column.label) + "</th>";
    }).join(""));

    var rows = [];
    if (meta.projectName) {
      rows.push(
        '<tr class="cgi-v2-project-row"><td></td><td colspan="' +
        Math.max(1, model.columns.length - 2) + '">' + escapeHtml(meta.projectName) +
        '</td><td></td></tr>'
      );
    }

    var items = Array.isArray(model.items) ? model.items : [];
    var actualCount = items.filter(function (item) { return !item.filler; }).length;
    var configuredAfter = Number(cgi.underfillAfterRows);
    var underfillAfter = Number.isInteger(configuredAfter)
      ? Math.max(actualCount, Math.min(items.length, configuredAfter))
      : items.length;

    items.forEach(function (item, index) {
      if (index === underfillAfter && cgi.underfillText) {
        rows.push('<tr class="cgi-v2-underfill"><td colspan="' + model.columns.length + '">' +
          escapeHtml(cgi.underfillText) + '</td></tr>');
      }
      var cells = model.columns.map(function (column) {
        var cls = [];
        if (column.align === "center") cls.push("cgi-v2-center");
        if (column.align === "right") cls.push("cgi-v2-right");
        if (item.filler) cls.push("cgi-v2-empty");
        var classAttr = cls.length ? ' class="' + cls.join(" ") + '"' : "";
        return "<td" + classAttr + ">" + escapeHtml(item.values[column.key]) + "</td>";
      }).join("");
      rows.push('<tr' + (item.filler ? ' class="cgi-v2-filler-row"' : "") + '>' + cells + "</tr>");
    });
    if (underfillAfter >= items.length && cgi.underfillText) {
      rows.push('<tr class="cgi-v2-underfill"><td colspan="' + model.columns.length + '">' +
        escapeHtml(cgi.underfillText) + '</td></tr>');
    }

    rows.push(
      '<tr class="cgi-v2-sum-row"><td></td><td class="cgi-v2-sum-label">' +
      escapeHtml(model.totals.subtotalLabel) +
      '</td><td></td><td></td><td></td><td></td><td class="cgi-v2-right">' +
      escapeHtml(cgiMoneyText(model.totals.subtotalText)) + '</td><td></td></tr>'
    );
    rows.push(
      '<tr class="cgi-v2-sum-row"><td></td><td class="cgi-v2-sum-label">' +
      escapeHtml(model.totals.vatLabel) +
      '</td><td></td><td></td><td class="cgi-v2-center">' +
      escapeHtml(facts.taxRateText || "") + '</td><td></td><td class="cgi-v2-right">' +
      escapeHtml(cgiMoneyText(model.totals.vatText)) + '</td><td></td></tr>'
    );
    rows.push(
      '<tr class="cgi-v2-grand-row"><td></td><td class="cgi-v2-sum-label">' +
      escapeHtml(model.totals.grandLabel) +
      '</td><td></td><td></td><td></td><td></td><td class="cgi-v2-right">' +
      escapeHtml(cgiMoneyText(model.totals.grandText)) + '</td><td></td></tr>'
    );
    setHtml("cgiV2Items", rows.join(""));

    setHtml("cgiV2Terms", (Array.isArray(cgi.terms) ? cgi.terms : []).map(function (term) {
      var validDays = meta.validDays == null ? "" : String(meta.validDays);
      var validityText = Number(meta.validDays) === 7 ? "1주일" : (validDays ? validDays + "일" : "");
      var renderedTerm = String(term)
        .replace("{validDays}", validDays)
        .replace("{validityText}", validityText);
      return "<li>" + escapeHtml(renderedTerm) + "</li>";
    }).join(""));

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
    var cgiContent = doc.getElementById("cgiV2Content");
    var genericContent = doc.getElementById("quoteGenericContent");
    var cgiMode = model.layoutVariant === "cgi-v2";
    if (cgiContent) cgiContent.hidden = !cgiMode;
    if (genericContent) genericContent.hidden = cgiMode;
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
    setText("pvItemsHeading", model.itemsHeadingText);
    setHtml("pvSummaryTerms", (Array.isArray(model.summaryTerms) ? model.summaryTerms : []).map(function (term) {
      return '<div class="quote-summary-term"><span>' + escapeHtml(term.label) +
        '</span><strong>' + escapeHtml(term.value) + "</strong></div>";
    }).join(""));

    setText("pvSenderHeading", sender.heading);
    setText("pvSenderCompany", sender.company);
    setText("pvSenderRep", sender.rep);
    setText("pvSenderContactPerson", sender.contactPerson);
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
      var formalTitleHead = model.layoutVariant === "formal-grid-v1" && page.titleText
        ? '<tr class="quote-detail-title-row"><th colspan="' + page.columns.length + '">' +
          escapeHtml(page.titleText) + "</th></tr>"
        : "";
      var standaloneTitle = formalTitleHead
        ? ""
        : '<h2 class="quote-detail-title">' + escapeHtml(page.titleText) + "</h2>";
      var colgroup = formalTitleHead
        ? "<colgroup>" + page.columns.map(function (column) {
            var style = column.width ? ' style="width:' + escapeHtml(column.width) + '"' : "";
            return "<col" + style + ">";
          }).join("") + "</colgroup>"
        : "";
      var headGroup = formalTitleHead
        ? "<thead>" + formalTitleHead + "</thead><tbody><tr class=\"quote-detail-column-row\">" + head + "</tr>"
        : "<thead><tr>" + head + "</tr></thead><tbody>";
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
        standaloneTitle +
        '<table class="quote-table">' + colgroup + headGroup + body + "</tbody></table>" +
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
    setPrivateImage("cgiV2Logo", model.slots && model.slots.logo);
    setPrivateImage("cgiV2Stamp", model.slots && model.slots.stamp);
    if (cgiMode) applyCgiV2(doc, model);

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
    buildPageStyleVariables: buildPageStyleVariables,
    buildPageRule: buildPageRule,
    applyCgiV2: applyCgiV2,
    formatIssueDate: formatIssueDate,
    buildRenderModel: buildRenderModel,
    buildCertifiedPdfRenderModel: buildCertifiedPdfRenderModel,
    applyRenderModel: applyRenderModel
  };
});
