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

  /* preview → apply 가 성공하면 미리보기 상태를 반드시 종료한다(배너도 사라져야 한다). */
  function resolveUiStateAfterApply(uiState, applyOk) {
    var next = Object.assign({}, uiState || {});
    if (applyOk === true) {
      next.previewTemplateId = null;
      next.renamingTemplateId = null;
    }
    return next;
  }

  function isPreviewActive(uiState) {
    return Boolean(uiState && uiState.previewTemplateId);
  }

  /* ── #3184 candidate 검토 화면 ── */

  var CANDIDATE_STATUS_LABELS = {
    idle: "대기",
    preflight_ok: "분석 대기",
    reviewing: "검토 중",
    approved: "승인됨",
    cancelled: "취소됨",
    failed: "실패"
  };

  var SOURCE_KIND_LABELS = {
    file: "선택한 파일",
    manual: "직접 입력",
    sample: "샘플"
  };

  function definitionRow(label, value) {
    return '<div class="review-def"><dt>' + escapeHtml(label) + '</dt><dd>' +
      escapeHtml(value == null || value === "" ? "—" : value) + "</dd></div>";
  }

  function buildReviewBlocks(review) {
    if (!review) return [];
    var blocks = [];

    blocks.push({
      key: "identity",
      title: "양식 이름과 출처",
      kind: "identity",
      name: review.name,
      rows: [
        { label: "출처", value: SOURCE_KIND_LABELS[review.provenance.sourceKind] || review.provenance.sourceKind },
        { label: "파일명", value: review.provenance.sourceName },
        { label: "수집 시각", value: review.provenance.capturedAt },
        { label: "내용 지문", value: review.fingerprintShort },
        { label: "상태", value: review.statusLabel }
      ]
    });

    blocks.push({
      key: "sections",
      title: "인식한 섹션",
      kind: "list",
      items: review.sections.map(function (section) { return section.label; })
    });

    blocks.push({
      key: "columns",
      title: "품목 표 열 / 순서",
      kind: "ordered",
      items: review.columns.map(function (column, index) {
        return (index + 1) + ". " + column.label + " (" + column.key + ")";
      })
    });

    blocks.push({
      key: "tax",
      title: "세금 · 합계 표시",
      kind: "defs",
      rows: [
        { label: "공급가액 라벨", value: review.tax.supplyLabel },
        { label: "합계 라벨", value: review.tax.grandLabel },
        { label: "부가세 라벨(별도)", value: review.tax.vatLabels.EXCLUSIVE },
        { label: "부가세 라벨(포함)", value: review.tax.vatLabels.INCLUSIVE },
        { label: "부가세 라벨(면세)", value: review.tax.vatLabels.EXEMPT },
        { label: "미확정 표시", value: review.tax.provisional.subtotalLabel + " / " + review.tax.provisional.vatText + " / " + review.tax.provisional.grandText }
      ]
    });

    blocks.push({
      key: "text",
      title: "고정 · 기본 문구",
      kind: "defs",
      rows: [
        { label: "문서 제목", value: review.text.title },
        { label: "빈 품목 안내", value: review.text.emptyNameText },
        { label: "빈 비고 안내", value: review.text.memoEmptyText },
        { label: "표시 문구", value: review.text.mark }
      ]
    });

    blocks.push({
      key: "layout",
      title: "페이지 · 레이아웃 · 스타일",
      kind: "defs",
      rows: [
        { label: "용지", value: review.layout.page.size + " / " + review.layout.page.orientation },
        { label: "여백", value: review.layout.page.margin },
        { label: "강조 색", value: review.layout.style.accent },
        { label: "제목 규칙", value: review.layout.style.titleRule },
        { label: "합계 폭", value: review.layout.style.totalsWidth },
        { label: "정렬", value: review.layout.style.headerAlignment + " / " + review.layout.style.metaAlignment + " / " + review.layout.style.numericAlignment }
      ]
    });

    blocks.push({
      key: "slots",
      title: "로고 · 도장 슬롯",
      kind: "slots",
      support: review.slots.support,
      declared: review.slots.declared,
      rows: [
        { label: "지원 상태", value: review.slots.support === "non_live" ? "아직 렌더하지 않음(non-live)" : review.slots.support },
        { label: "로고", value: review.slots.logo },
        { label: "도장", value: review.slots.stamp }
      ]
    });

    blocks.push({
      key: "notes",
      title: "경고 · 미확인 · 신뢰도",
      kind: "notes",
      warnings: review.warnings.map(function (note) { return note.message || note.code; }),
      unknowns: review.unknowns.map(function (note) { return note.message || note.code; }),
      confidence: review.confidence,
      evidence: review.evidence.map(function (item) { return item.label + ": " + item.value; })
    });

    return blocks;
  }

  function renderReviewBlock(block) {
    var body = "";
    if (block.kind === "identity") {
      body = '<label class="review-name"><span>양식 이름</span>' +
        '<input type="text" data-role="candidate-name" maxlength="80" value="' +
        escapeHtml(block.name || "") +
        '" aria-label="후보 양식 이름"></label>';
      body += '<dl class="review-defs">' + block.rows.map(function (row) {
        return definitionRow(row.label, row.value);
      }).join("") + "</dl>";
    } else if (block.kind === "list" || block.kind === "ordered") {
      var tag = block.kind === "list" ? "ul" : "ol";
      body = "<" + tag + ' class="review-list">' + block.items.map(function (item) {
        return "<li>" + escapeHtml(item) + "</li>";
      }).join("") + "</" + tag + ">";
    } else if (block.kind === "defs" || block.kind === "slots") {
      body = '<dl class="review-defs">' + block.rows.map(function (row) {
        return definitionRow(row.label, row.value);
      }).join("") + "</dl>";
    } else {
      body = '<dl class="review-defs">' + definitionRow("신뢰도", block.confidence === null ? "—" : String(block.confidence)) + "</dl>";
      body += '<p class="review-note-title">경고</p>';
      body += block.warnings.length
        ? '<ul class="review-list review-list--warning">' + block.warnings.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul>"
        : '<p class="review-empty">경고 없음</p>';
      body += '<p class="review-note-title">미확인</p>';
      body += block.unknowns.length
        ? '<ul class="review-list">' + block.unknowns.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul>"
        : '<p class="review-empty">미확인 항목 없음</p>';
      if (block.evidence.length) {
        body += '<p class="review-note-title">근거</p><ul class="review-list">' +
          block.evidence.map(function (item) { return "<li>" + escapeHtml(item) + "</li>"; }).join("") + "</ul>";
      }
    }

    return '<section class="review-block" data-review="' + escapeHtml(block.key) + '">' +
      "<h4>" + escapeHtml(block.title) + "</h4>" + body + "</section>";
  }

  function renderReviewMarkup(review, uiState) {
    var state = uiState || {};
    if (!review) {
      return '<p class="review-empty">검토할 후보가 없습니다.</p>';
    }
    var progress = (state.progress || []).map(function (step) {
      return '<li class="cloner-step' + (step.done ? " is-done" : "") + '">' + escapeHtml(step.label) + "</li>";
    }).join("");

    var blocks = buildReviewBlocks(review).map(renderReviewBlock).join("");

    return '<ol class="cloner-progress" aria-label="본뜨기 진행 단계">' + progress + "</ol>" +
      '<p class="review-status" role="status"><strong>' + escapeHtml(review.statusLabel) + "</strong>" +
      (state.approved ? " · 저장됨" : " · 아직 승인되지 않았습니다") + "</p>" +
      '<div class="review-grid" data-candidate-id="' + escapeHtml(review.candidateId) + '">' + blocks + "</div>";
  }

  function buildClonerStatusText(cloner, session) {
    if (!session) return "아직 시작하지 않았습니다.";
    if (session.status === "failed") {
      return "본뜨기를 진행할 수 없습니다 (" + (session.error ? session.error.code : "unknown") + ").";
    }
    if (session.status === "preflight_ok") {
      return "파일 검증은 끝났습니다. 문서 분석기는 아직 연결되지 않아 후보를 만들 수 없습니다.";
    }
    if (session.status === "reviewing") return "후보를 검토 중입니다. 승인 전에는 적용되지 않습니다.";
    if (session.status === "approved") return "승인되어 저장되었습니다.";
    if (session.status === "cancelled") return "본뜨기를 취소했습니다. 저장된 것은 없습니다.";
    return CANDIDATE_STATUS_LABELS[session.status] || session.status;
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
    resolveUiStateAfterApply: resolveUiStateAfterApply,
    isPreviewActive: isPreviewActive,
    CANDIDATE_STATUS_LABELS: CANDIDATE_STATUS_LABELS,
    SOURCE_KIND_LABELS: SOURCE_KIND_LABELS,
    buildReviewBlocks: buildReviewBlocks,
    renderReviewMarkup: renderReviewMarkup,
    buildClonerStatusText: buildClonerStatusText,
    buildStatusText: buildStatusText
  };
});
