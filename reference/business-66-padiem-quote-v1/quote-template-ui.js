/* B66 · Quote Beta — quote-template-ui.js
   양식 선택/관리 UI 의 "순수" 표현 계층: 목록·옵션·상태 문구를 결정적으로 만든다.
   DOM 조작은 app.js 의 얇은 adapter 가 담당하고, 이 파일은 문자열/모델만 만든다.

   규칙:
   - 미승인 candidate 는 목록에 보이되 선택/기본 지정은 불가(disabled + 사유 표시).
   - canonical built-in 은 삭제/이름 변경 불가, 항상 선택 가능.
   - 모든 사용자 입력은 이스케이프한다. */

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.QuoteTemplateUi = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var STATUS_BUILTIN = "builtin";
  var STATUS_APPROVED = "approved";
  var STATUS_UNAPPROVED = "unapproved";

  var STATUS_LABELS = {};
  STATUS_LABELS[STATUS_BUILTIN] = "기본 제공";
  STATUS_LABELS[STATUS_APPROVED] = "승인됨";
  STATUS_LABELS[STATUS_UNAPPROVED] = "승인 대기";

  var ACTION_LABELS = {
    select: "이 양식 사용",
    default: "기본으로 설정",
    preview: "미리보기",
    rename: "이름 변경",
    duplicate: "복제",
    remove: "삭제"
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function statusKeyOf(template) {
    if (template && template.builtin === true) return STATUS_BUILTIN;
    if (template && template.approved === true) return STATUS_APPROVED;
    return STATUS_UNAPPROVED;
  }

  /* ── 선택 목록(현재 견적에 적용할 양식) ── */

  function buildOptions(templates, activeId) {
    return (Array.isArray(templates) ? templates : []).map(function (template) {
      var approved = template.approved === true;
      return {
        value: template.id,
        label: template.name + (template.isDefault ? " (기본 양식)" : ""),
        approved: approved,
        disabled: !approved,
        selected: template.id === activeId,
        statusKey: statusKeyOf(template),
        hint: approved ? "" : "승인 후 선택할 수 있습니다"
      };
    });
  }

  function renderOptionsMarkup(options) {
    return (Array.isArray(options) ? options : []).map(function (option) {
      var attrs = ' value="' + escapeHtml(option.value) + '"';
      if (option.disabled) attrs += " disabled";
      if (option.selected) attrs += " selected";
      if (option.hint) attrs += ' title="' + escapeHtml(option.hint) + '"';
      var suffix = option.disabled ? " — " + option.hint : "";
      return "<option" + attrs + ">" + escapeHtml(option.label + suffix) + "</option>";
    }).join("");
  }

  /* ── 관리 목록 행 ── */

  function buildRows(templates, uiState) {
    var state = uiState || {};
    var activeId = state.activeTemplateId || null;
    var previewId = state.previewTemplateId || null;
    var renamingId = state.renamingTemplateId || null;

    return (Array.isArray(templates) ? templates : []).map(function (template) {
      var approved = template.approved === true;
      var builtin = template.builtin === true;
      return {
        id: template.id,
        name: template.name,
        builtin: builtin,
        approved: approved,
        statusKey: statusKeyOf(template),
        statusLabel: STATUS_LABELS[statusKeyOf(template)],
        isDefault: template.isDefault === true,
        isActive: template.id === activeId,
        isPreviewing: template.id === previewId,
        isRenaming: template.id === renamingId,
        selectable: approved,
        canRename: !builtin,
        canDuplicate: true,
        canDelete: !builtin,
        canSetDefault: approved && template.isDefault !== true,
        canPreview: approved,
        fingerprintShort: String(template.fingerprint || "").slice(0, 12)
      };
    });
  }

  function actionButton(row, action, label, enabled) {
    var disabled = enabled ? "" : " disabled";
    var aria = escapeHtml(label + " — " + row.name);
    return '<button class="btn soft template-action" type="button"' +
      ' data-action="' + action + '"' +
      ' data-template-id="' + escapeHtml(row.id) + '"' +
      ' aria-label="' + aria + '"' +
      disabled + ">" + escapeHtml(label) + "</button>";
  }

  function renderRow(row) {
    var stateFlags = [];
    if (row.isActive) stateFlags.push("active");
    if (row.isDefault) stateFlags.push("default");
    if (row.isPreviewing) stateFlags.push("previewing");

    var badges = ['<span class="template-badge template-badge--' + row.statusKey + '">' +
      escapeHtml(row.statusLabel) + "</span>"];
    if (row.isDefault) badges.push('<span class="template-badge template-badge--default">기본 양식</span>');
    if (row.isActive) badges.push('<span class="template-badge template-badge--active">현재 견적</span>');
    if (row.isPreviewing) badges.push('<span class="template-badge template-badge--previewing">미리보기 중</span>');

    var nameBlock;
    if (row.isRenaming) {
      nameBlock =
        '<label class="template-rename"><span class="visually-hidden">양식 이름</span>' +
        '<input class="template-rename-input" type="text" data-role="rename-input"' +
        ' data-template-id="' + escapeHtml(row.id) + '"' +
        ' value="' + escapeHtml(row.name) + '" maxlength="80"></label>';
    } else {
      nameBlock = '<span class="template-row-name">' + escapeHtml(row.name) + "</span>";
    }

    var actions = [];
    if (row.isRenaming) {
      actions.push('<button class="btn primary template-action" type="button" data-action="rename-save" data-template-id="' +
        escapeHtml(row.id) + '" aria-label="' + escapeHtml(row.name + " 이름 저장") + '">저장</button>');
      actions.push('<button class="btn soft template-action" type="button" data-action="rename-cancel" data-template-id="' +
        escapeHtml(row.id) + '" aria-label="' + escapeHtml(row.name + " 이름 변경 취소") + '">취소</button>');
    } else {
      if (row.isPreviewing) {
        actions.push('<button class="btn primary template-action" type="button" data-action="preview-apply" data-template-id="' +
          escapeHtml(row.id) + '" aria-label="' + escapeHtml(row.name + " 미리보기 적용") + '">미리보기 적용</button>');
        actions.push('<button class="btn soft template-action" type="button" data-action="preview-cancel" data-template-id="' +
          escapeHtml(row.id) + '" aria-label="미리보기 취소">미리보기 취소</button>');
      } else {
        actions.push(actionButton(row, "preview", ACTION_LABELS.preview, row.canPreview));
        actions.push(actionButton(row, "select", ACTION_LABELS.select, row.selectable && !row.isActive));
      }
      actions.push(actionButton(row, "default", ACTION_LABELS.default, row.canSetDefault));
      actions.push(actionButton(row, "rename", ACTION_LABELS.rename, row.canRename));
      actions.push(actionButton(row, "duplicate", ACTION_LABELS.duplicate, row.canDuplicate));
      actions.push(actionButton(row, "remove", ACTION_LABELS.remove, row.canDelete));
    }

    return '<div class="template-row" role="listitem" data-template-id="' + escapeHtml(row.id) + '"' +
      ' data-state="' + stateFlags.join(" ") + '"' +
      ' aria-current="' + (row.isActive ? "true" : "false") + '">' +
      '<div class="template-row-main">' + nameBlock + badges.join("") +
      (row.approved ? "" : '<span class="template-row-hint">승인 후 이 견적에 적용할 수 있습니다</span>') +
      "</div>" +
      '<div class="template-row-actions">' + actions.join("") + "</div>" +
      "</div>";
  }

  function renderRowsMarkup(rows, uiState) {
    var state = uiState || {};
    var list = Array.isArray(rows) ? rows : [];
    var body = list.map(renderRow).join("");
    var banner = "";
    if (state.previewTemplateId) {
      var previewed = list.filter(function (row) { return row.isPreviewing; })[0];
      banner = '<div class="template-preview-banner" role="status">' +
        '<strong>미리보기 중</strong> — ' + escapeHtml(previewed ? previewed.name : state.previewTemplateId) +
        " (아직 적용되지 않았습니다)</div>";
    }
    return banner + body;
  }

  function buildStatusText(activeTemplate, uiState) {
    var state = uiState || {};
    if (!activeTemplate) return "사용할 양식을 찾지 못해 기본 견적서로 표시합니다.";
    var prefix = state.previewTemplateId ? "[미리보기] " : "";
    var tail = activeTemplate.builtin
      ? "기본 제공 양식을 사용 중입니다."
      : (activeTemplate.isDefault ? "저장한 기본 양식을 사용 중입니다." : "이 견적에 선택한 양식을 사용 중입니다.");
    if (state.fallbackReason === "template_not_approved") {
      return prefix + "선택한 양식을 적용할 수 없어 기본 견적서로 표시합니다.";
    }
    if (state.fallbackReason === "invalid_template_profile") {
      return prefix + "양식 정보가 손상되어 기본 견적서로 표시합니다.";
    }
    if (state.fallbackReason === "missing_selected_template") {
      return prefix + "선택한 양식이 삭제되어 기본 양식으로 표시합니다.";
    }
    return prefix + activeTemplate.name + " — " + tail;
  }

  return {
    STATUS_BUILTIN: STATUS_BUILTIN,
    STATUS_APPROVED: STATUS_APPROVED,
    STATUS_UNAPPROVED: STATUS_UNAPPROVED,
    STATUS_LABELS: STATUS_LABELS,
    ACTION_LABELS: ACTION_LABELS,
    escapeHtml: escapeHtml,
    statusKeyOf: statusKeyOf,
    buildOptions: buildOptions,
    renderOptionsMarkup: renderOptionsMarkup,
    buildRows: buildRows,
    renderRowsMarkup: renderRowsMarkup,
    buildStatusText: buildStatusText
  };
});
