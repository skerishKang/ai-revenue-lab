/* B66 · Quote Beta — app.js (UI 레이어)
   상태는 QuoteDraft 하나(quote-core.js)로 관리하고 화면은 항상 draft에서 파생.
   draft는 localStorage에 자동 저장되며, 복원 실패 시 기본 데모 상태로 fallback. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const Core = window.QuoteCore;
  const Extraction = window.QuoteExtraction || null;
  const History = window.QuoteHistory || null;
  const Template = window.QuoteTemplate || null;
  const TemplateStore = window.QuoteTemplateStore || null;
  const TemplateRenderer = window.QuoteTemplateRenderer || null;
  const TemplateSelection = window.QuoteTemplateSelection || null;
  const TemplateUi = window.QuoteTemplateUi || null;
  const TemplateCandidate = window.QuoteTemplateCandidate || null;
  const TemplateCloner = window.QuoteTemplateCloner || null;
  const FileIntake = window.B66FileIntake || null;
  const SavedSkill = window.SavedQuoteSkill || null;
  const SkillStore = window.SavedQuoteSkillStore || null;
  const SkillUi = window.SavedQuoteSkillUi || null;
  const TAX_REVIEW_STORAGE_KEY = "quoteBeta.taxReview.v1";
  const TAX_REVIEW_SCHEMA_VERSION = 1;

  /* ── 상태: QuoteDraft ── */

  let draft = loadDraft() || Core.createDefaultDraft();
  let lastExtractionReview = null;
  let taxReviewRequired = loadTaxReviewRequired(draft);
  let suppressNextDraftSave = false;
  let clonerSession = null;
  let itemSeq = draft.items.reduce((max, it) => {
    const n = parseInt(String(it.id).replace(/^item-/, ""), 10);
    return Number.isFinite(n) ? Math.max(max, n) : max;
  }, 0);

  function nextItemId() {
    itemSeq += 1;
    return "item-" + itemSeq;
  }

  function loadDraft() {
    try {
      return Core.normalizeDraft(JSON.parse(localStorage.getItem(Core.DRAFT_STORAGE_KEY) || "null"));
    } catch (err) {
      return null;
    }
  }

  function normalizeTaxReviewState(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    if (raw.schemaVersion !== TAX_REVIEW_SCHEMA_VERSION || raw.required !== true) return null;
    if (typeof raw.quoteNo !== "string" || !raw.quoteNo.trim() || raw.quoteNo.length > 120) return null;
    return {
      schemaVersion: TAX_REVIEW_SCHEMA_VERSION,
      quoteNo: raw.quoteNo.trim(),
      required: true
    };
  }

  function loadTaxReviewRequired(activeDraft) {
    try {
      const state = normalizeTaxReviewState(
        JSON.parse(localStorage.getItem(TAX_REVIEW_STORAGE_KEY) || "null")
      );
      const quoteNo = String(activeDraft && activeDraft.meta && activeDraft.meta.quoteNo || "").trim();
      return Boolean(state && quoteNo && state.quoteNo === quoteNo);
    } catch (err) {
      return false;
    }
  }

  function persistTaxReviewRequired(required) {
    try {
      if (!required) {
        localStorage.removeItem(TAX_REVIEW_STORAGE_KEY);
        return true;
      }
      const quoteNo = String(draft && draft.meta && draft.meta.quoteNo || "").trim();
      if (!quoteNo) {
        localStorage.removeItem(TAX_REVIEW_STORAGE_KEY);
        return false;
      }
      localStorage.setItem(TAX_REVIEW_STORAGE_KEY, JSON.stringify({
        schemaVersion: TAX_REVIEW_SCHEMA_VERSION,
        quoteNo,
        required: true
      }));
      return true;
    } catch (err) {
      return false;
    }
  }

  function saveDraft() {
    if (suppressNextDraftSave) {
      suppressNextDraftSave = false;
      return;
    }
    try {
      localStorage.setItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(draft));
    } catch (err) {
      /* 저장 실패는 데모 진행을 막지 않음 */
    }
  }

  function cloneDraft(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function replaceDraft(nextDraft, options) {
    const normalized = Core.normalizeDraft(nextDraft);
    if (!normalized) return { ok: false, error: "invalid_draft" };
    draft = normalized;
    taxReviewRequired = Boolean(options && options.requireTaxReview);
    persistTaxReviewRequired(taxReviewRequired);
    itemSeq = draft.items.reduce((max, it) => {
      const n = parseInt(String(it.id).replace(/^(?:item-|extracted-item-)/, ""), 10);
      return Number.isFinite(n) ? Math.max(max, n) : max;
    }, 0);
    renderItems();
    fillInputsFromDraft();
    render();
    renderTaxReviewState();
    if (options && options.toast) toast(options.toast);
    return { ok: true, draft: cloneDraft(draft) };
  }

  function loadHistoryEnvelope() {
    if (!History) return null;
    try {
      return History.normalizeEnvelope(JSON.parse(localStorage.getItem(History.HISTORY_STORAGE_KEY) || "null"));
    } catch (err) {
      return History.normalizeEnvelope(null);
    }
  }

  function loadQuoteNoSequence() {
    if (!History) return null;
    try {
      return History.normalizeSequenceState(
        JSON.parse(localStorage.getItem(History.SEQUENCE_STORAGE_KEY) || "null")
      );
    } catch (err) {
      return History.normalizeSequenceState(null);
    }
  }

  function quoteNoCandidates() {
    if (!History) return [];
    const envelope = loadHistoryEnvelope();
    const candidates = envelope ? envelope.entries.map((entry) => entry.draft) : [];
    if (History.isMeaningfulDraft(draft)) candidates.push(draft);
    return candidates;
  }

  function allocateFreshQuoteNo(now) {
    if (!History) return Core.createDefaultDraft().meta.quoteNo;
    const allocation = History.allocateQuoteNo(
      loadQuoteNoSequence(),
      quoteNoCandidates(),
      now instanceof Date ? now : new Date()
    );
    try {
      localStorage.setItem(History.SEQUENCE_STORAGE_KEY, JSON.stringify(allocation.state));
    } catch (err) {
      /* 번호는 history/draft와 대조해 계산되므로 sequence 저장 실패만으로 진행을 막지 않음 */
    }
    return allocation.quoteNo;
  }

  function createFreshDraft(source, now) {
    const dt = now instanceof Date ? now : new Date();
    const fresh = Core.createDefaultDraft();
    fresh.meta.quoteNo = allocateFreshQuoteNo(dt);
    fresh.meta.issueDate = Core.isoFormat(dt);
    fresh.meta.source = source || "manual";
    return fresh;
  }

  function createBlankNextDraft(now) {
    const dt = now instanceof Date ? now : new Date();
    return Core.createBlankQuoteDraft(draft, {
      quoteNo: allocateFreshQuoteNo(dt),
      issueDate: Core.isoFormat(dt),
      source: "manual"
    });
  }

  function copyHistoryAsNew(entry, now) {
    if (!History) return null;
    const dt = now instanceof Date ? now : new Date();
    return History.copyAsNew(entry, {
      now: dt,
      quoteNo: allocateFreshQuoteNo(dt)
    });
  }

  function saveCurrentToHistory() {
    if (!History) return { ok: false, error: "history_unavailable" };
    const before = loadHistoryEnvelope();
    const quoteNo = String(draft.meta.quoteNo || "").trim();
    const existed = Boolean(before && before.entries.some((entry) =>
      String(entry.draft.meta.quoteNo || "").trim() === quoteNo
    ));
    const envelope = History.upsertEntryByQuoteNo(before, draft);
    try {
      localStorage.setItem(History.HISTORY_STORAGE_KEY, JSON.stringify(envelope));
    } catch (err) {
      return { ok: false, error: "history_storage_failed" };
    }
    toast(existed
      ? "같은 견적번호의 최근 견적을 최신 내용으로 업데이트했습니다."
      : "이 견적을 최근 견적에 저장했습니다.");
    window.dispatchEvent(new CustomEvent("b66:history-changed"));
    return { ok: true, updated: existed, envelope: cloneDraft(envelope) };
  }

  /* ── 공통 유틸 ── */

  /* 이스케이프는 렌더러와 같은 단일 구현을 쓴다. */
  const escapeHtml = (value) => TemplateRenderer.escapeHtml(value);

  function toast(message, duration) {
    $("toast").textContent = message;
    $("toast").classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => $("toast").classList.remove("show"), duration || 1800);
  }

  function resetBrowserLocalData() {
    if (!window.confirm("이 브라우저에 저장한 견적, 발신자, 최근 견적 기록을 초기화할까요?")) {
      return false;
    }

    const keys = [
      Core.DRAFT_STORAGE_KEY,
      Core.SENDER_STORAGE_KEY,
      History && History.HISTORY_STORAGE_KEY,
      History && History.SEQUENCE_STORAGE_KEY,
      TemplateStore && TemplateStore.TEMPLATE_STORAGE_KEY,
      TemplateSelection && TemplateSelection.SELECTION_STORAGE_KEY,
      SkillStore && SkillStore.STORAGE_KEY,
      TAX_REVIEW_STORAGE_KEY
    ].filter(Boolean);

    try {
      keys.forEach((key) => localStorage.removeItem(key));
    } catch (err) {
      toast("브라우저 저장 데이터를 지우지 못했습니다.");
      return false;
    }

    draft = Core.createDefaultDraft();
    lastExtractionReview = null;
    taxReviewRequired = false;
    itemSeq = draft.items.length;
    suppressNextDraftSave = true;
    templateUiState.previewTemplateId = null;
    templateUiState.renamingTemplateId = null;
    skillUiState.activeSkillId = null;
    clonerSession = null;

    renderItems();
    fillInputsFromDraft();
    renderTaxReviewState();
    renderTemplateUi();
    render();
    window.dispatchEvent(new CustomEvent("b66:local-data-reset"));
    window.dispatchEvent(new CustomEvent("b66:history-changed"));
    toast("이 브라우저에 저장한 견적 데이터를 초기화했습니다.", 3000);
    return true;
  }

  function renderTaxReviewState() {
    const row = $("taxRow");
    const note = $("taxReviewNote");
    const select = $("taxMode");
    if (!row || !note || !select) return;

    let placeholder = select.querySelector('option[data-tax-review-placeholder="true"]');
    if (taxReviewRequired) {
      if (!placeholder) {
        placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "부가세 방식을 선택해 주세요";
        placeholder.dataset.taxReviewPlaceholder = "true";
        select.prepend(placeholder);
      }
      select.value = "";
    } else {
      if (placeholder) placeholder.remove();
      select.value = draft.tax.mode;
    }

    row.classList.toggle("tax-review-required", taxReviewRequired);
    note.hidden = !taxReviewRequired;
    select.setAttribute("aria-invalid", String(taxReviewRequired));
  }

  function focusTaxReview() {
    if (!taxReviewRequired) return false;
    renderTaxReviewState();
    $("taxMode").focus({ preventScroll: true });
    $("taxRow").scrollIntoView({ block: "center", behavior: "smooth" });
    return true;
  }

  function focusReadinessTarget(code) {
    let target = null;
    if (code === "quote_no") target = $("quoteNo");
    else if (code === "issue_date") target = $("quoteDate");
    else if (code === "sender_company") target = $("senderCompany");
    else if (code === "recipient") target = $("recipientCompany");
    else if (code === "items") target = document.querySelector("#items .item-name");

    if (!target) return false;
    target.focus({ preventScroll: true });
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    return true;
  }

  function printReadinessFailure() {
    if (taxReviewRequired) {
      return {
        code: "tax_review",
        message: "부가세 방식을 확인한 뒤 PDF로 저장해 주세요."
      };
    }

    const readiness = Core.printReadiness(draft);
    if (readiness.ready) return null;

    const code = readiness.missing[0];
    const messages = {
      invalid_draft: "견적 내용을 다시 확인해 주세요.",
      quote_no: "견적번호를 입력한 뒤 PDF로 저장해 주세요.",
      issue_date: "올바른 견적일을 선택한 뒤 PDF로 저장해 주세요.",
      sender_company: "보내는 사람의 상호를 입력한 뒤 PDF로 저장해 주세요.",
      recipient: "받는 업체명이나 담당자를 입력한 뒤 PDF로 저장해 주세요.",
      items: "품목명과 수량을 하나 이상 입력한 뒤 PDF로 저장해 주세요."
    };
    return {
      code,
      message: messages[code] || "견적 필수 내용을 확인한 뒤 PDF로 저장해 주세요."
    };
  }

  /* ── draft 필드 ↔ 입력 요소 바인딩 ── */

  const FIELD_BINDINGS = [
    ["senderCompany", "sender", "company"],
    ["senderRep", "sender", "rep"],
    ["senderBizNo", "sender", "bizNo"],
    ["senderAddress", "sender", "address"],
    ["senderPhone", "sender", "phone"],
    ["senderEmail", "sender", "email"],
    ["recipientCompany", "recipient", "company"],
    ["recipientPerson", "recipient", "person"],
    ["recipientAddress", "recipient", "address"],
    ["recipientEmail", "recipient", "email"],
    ["quoteNo", "meta", "quoteNo"],
    ["memo", "memo", null]
  ];

  function setDraftValue(group, key, value) {
    if (key === null) draft[group] = value;
    else draft[group][key] = value;
  }

  function ensureValidityOption(days) {
    const sel = $("validity");
    const v = String(days);
    if (![...sel.options].some((o) => o.value === v)) {
      const opt = document.createElement("option");
      opt.value = v;
      opt.textContent = v + "일";
      sel.appendChild(opt);
    }
    sel.value = v;
  }

  function fillInputsFromDraft() {
    FIELD_BINDINGS.forEach(([id, group, key]) => {
      $(id).value = key === null ? draft[group] : draft[group][key];
    });
    $("quoteDate").value = draft.meta.issueDate;
    ensureValidityOption(draft.meta.validDays);
    $("taxMode").value = draft.tax.mode;
    $("senderPreset").value = draft.sender.presetId === "custom" ? "custom" : "sample";
  }

  function bindFields() {
    FIELD_BINDINGS.forEach(([id, group, key]) => {
      $(id).addEventListener("input", (e) => {
        setDraftValue(group, key, e.target.value);
        render();
      });
    });
    $("quoteDate").addEventListener("input", (e) => {
      draft.meta.issueDate = e.target.value;
      render();
    });
    $("validity").addEventListener("change", (e) => {
      draft.meta.validDays = Core.parseMoney(e.target.value);
      render();
    });
    $("taxMode").addEventListener("change", (e) => {
      if (!e.target.value) return;
      draft.tax.mode = e.target.value;
      taxReviewRequired = false;
      persistTaxReviewRequired(false);
      renderTaxReviewState();
      render();
    });
  }

  /* ── future extraction bridge: validated facts → editable QuoteDraft ── */

  function cloneJson(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function validateExtractionResult(raw) {
    if (!Extraction || typeof Extraction.normalizeExtraction !== "function") {
      return { ok: false, error: "extraction_contract_unavailable" };
    }
    return Extraction.normalizeExtraction(raw);
  }

  function applyExtractionResult(raw, options) {
    if (!options || options.confirmed !== true) {
      return { ok: false, error: "review_confirmation_required" };
    }
    if (!Extraction || typeof Extraction.buildDraftCandidate !== "function") {
      return { ok: false, error: "extraction_contract_unavailable" };
    }

    const candidate = Extraction.buildDraftCandidate(draft, raw);
    if (!candidate.ok) return candidate;

    const nextDraft = Core.normalizeDraft(candidate.value.draft);
    if (!nextDraft) return { ok: false, error: "draft_normalization_failed" };

    draft = nextDraft;
    lastExtractionReview = cloneJson(candidate.value.review);

    renderItems();
    fillInputsFromDraft();
    render();
    toast("추출한 내용을 검토 가능한 견적 초안에 반영했습니다.");

    return { ok: true, draft: cloneJson(draft), review: cloneJson(lastExtractionReview) };
  }

  function getLastExtractionReview() {
    return lastExtractionReview ? cloneJson(lastExtractionReview) : null;
  }

  /* ── 품목 행: 단가/수량은 text 입력(콤마 허용) + blur 시 표시 포맷 ── */

  function buildItemRow(item, index, effectiveUnitPrice) {
    const row = document.createElement("div");
    const linkedDetail = Boolean(item.detailSectionId);
    const displayedUnitPrice = linkedDetail ? effectiveUnitPrice : item.unitPrice;
    row.className = "item-row";
    row.innerHTML = `
      <input class="item-name" aria-label="품목명" value="${escapeHtml(item.name)}" placeholder="품목명">
      <div class="item-cell qty">
        <span class="cell-label">수량</span>
        <input class="item-qty" aria-label="수량" type="text" inputmode="decimal" value="${escapeHtml(Core.formatInputNumber(item.qty))}">
      </div>
      <div class="item-cell price">
        <span class="cell-label">단가</span>
        <input class="item-price" aria-label="${linkedDetail ? "단가 (상세내역 합계에서 자동 계산)" : "단가"}" type="text" inputmode="numeric" value="${escapeHtml(Core.formatInputNumber(displayedUnitPrice))}" ${linkedDetail ? 'readonly aria-readonly="true" data-derived="detail-section"' : ""}>
      </div>
      <div class="amount"><span class="amount-label">금액</span><span class="amount-value"></span></div>
      <button class="icon-btn remove-item" aria-label="품목 삭제" title="품목 삭제">×</button>
    `;
    row.querySelector(".item-name").addEventListener("input", (e) => {
      draft.items[index].name = e.target.value;
      render();
    });
    row.querySelector(".item-qty").addEventListener("input", (e) => {
      draft.items[index].qty = Core.parseMoney(e.target.value);
      render();
    });
    row.querySelector(".item-qty").addEventListener("change", (e) => {
      e.target.value = Core.formatInputNumber(Core.parseMoney(e.target.value));
    });
    row.querySelector(".item-price").addEventListener("input", (e) => {
      if (linkedDetail) return;
      draft.items[index].unitPrice = Core.parseMoney(e.target.value);
      render();
    });
    row.querySelector(".item-price").addEventListener("change", (e) => {
      if (linkedDetail) {
        e.target.value = Core.formatInputNumber(effectiveUnitPrice);
        return;
      }
      e.target.value = Core.formatInputNumber(Core.parseMoney(e.target.value));
    });
    row.querySelector(".remove-item").addEventListener("click", () => removeItem(index));
    return row;
  }

  function renderItems() {
    const host = $("items");
    host.innerHTML = "";
    const totals = Core.computeDraftTotals(draft);
    draft.items.forEach((item, index) => host.appendChild(
      buildItemRow(item, index, totals && totals.unitPrices[index] !== undefined ? totals.unitPrices[index] : item.unitPrice)
    ));
  }

  function addItem() {
    draft.items.push({ id: nextItemId(), name: "", qty: 1, unitPrice: 0 });
    renderItems();
    render();
    const rows = $("items").querySelectorAll(".item-row");
    rows[rows.length - 1].querySelector(".item-name").focus();
  }

  function removeItem(index) {
    const detailSectionId = draft.items[index] && draft.items[index].detailSectionId;
    if (draft.items.length === 1) {
      draft.items[0] = { id: draft.items[0].id, name: "", qty: 1, unitPrice: 0 };
    } else {
      draft.items.splice(index, 1);
    }
    if (detailSectionId && Array.isArray(draft.detailSections)) {
      draft.detailSections = draft.detailSections.filter((section) => section.id !== detailSectionId);
      if (draft.detailSections.length === 0) delete draft.detailSections;
    }
    renderItems();
    render();
  }

  /* ── 렌더링: 승인된 템플릿 + QuoteCore 파생값 → 결정적 render projection ── */

  function loadTemplateStore() {
    if (!TemplateStore) return null;
    try {
      return TemplateStore.normalizeStore(
        JSON.parse(localStorage.getItem(TemplateStore.TEMPLATE_STORAGE_KEY) || "null")
      );
    } catch (err) {
      return TemplateStore.normalizeStore(null);
    }
  }

  /* ── 견적서 양식: "이 견적의 양식" 과 "향후 기본 양식" 을 분리한다 ──
     양식 전환은 QuoteDraft 의 업무 내용을 건드리지 않는다. ── */

  const templateUiState = {
    manageOpen: false,
    previewTemplateId: null,
    renamingTemplateId: null
  };

  function templateStorage() {
    return typeof localStorage === "undefined" ? null : localStorage;
  }

  function currentTemplateId() {
    if (!TemplateSelection) return null;
    return TemplateSelection.selectionForQuote(
      TemplateSelection.readEnvelope(templateStorage()),
      draft.meta.quoteNo
    );
  }

  /* ── 내 견적서: 선택된 승인 Skill 의 내부 profile 이 미리보기 layout authority.
     template store/selection 을 건드리지 않으며, 실패 시 내장으로 fallback. ── */

  const skillUiState = { activeSkillId: null, serverSkill: null, serverSlotSources: {} };
  let skillUiApi = null;

  function activeSkillProfile() {
    if (!SavedSkill || !Template || !skillUiState.activeSkillId) return null;
    try {
      let skill = null;
      if (
        skillUiState.serverSkill &&
        skillUiState.serverSkill.id === skillUiState.activeSkillId
      ) {
        skill = SavedSkill.normalizeSkill(skillUiState.serverSkill);
      } else if (SkillStore && typeof localStorage !== "undefined") {
        skill = SkillStore.getSkill(SkillStore.readStore(localStorage), skillUiState.activeSkillId);
      }
      if (!skill || skill.approved !== true) return null;
      const profile = Template.normalizeTemplate(skill.internalTemplate);
      return profile && Template.isApprovedProfile(profile) ? profile : null;
    } catch (err) {
      return null;
    }
  }

  function applySkillToForm(skill) {
    skillUiState.serverSkill = null;
    skillUiState.serverSlotSources = {};
    if (!skill || !SkillUi) {
      skillUiState.activeSkillId = null;
      toast("기본 견적서로 작성합니다.");
      render();
      return true;
    }
    const values = SkillUi.formValuesFromSkill(skill);
    if (!values) return false;
    skillUiState.activeSkillId = skill.id;
    /* 회사 기본값만 적용한다. 거래처/번호/날짜/품목은 건별 입력으로 남긴다. */
    draft.sender = Object.assign({}, draft.sender, values.sender, { presetId: "custom" });
    draft.meta.validDays = values.validDays;
    draft.tax.mode = values.taxMode;
    draft.memo = values.memo;
    saveDraft();
    fillInputsFromDraft();
    renderItems();
    render();
    toast("내 견적서 기본값을 적용했습니다. 거래처와 품목은 새로 입력하세요.");
    return true;
  }

  function setServerSkill(skill, slotSources) {
    if (!SavedSkill || !Template) return false;
    const normalized = SavedSkill.normalizeSkill(skill);
    if (!normalized || normalized.approved !== true) return false;
    const profile = Template.normalizeTemplate(normalized.internalTemplate);
    if (!profile || !Template.isApprovedProfile(profile)) return false;
    skillUiState.serverSkill = normalized;
    skillUiState.serverSlotSources = slotSources && typeof slotSources === "object"
      ? slotSources
      : {};
    skillUiState.activeSkillId = normalized.id;
    render();
    return true;
  }

  function clearServerSkill() {
    const activeWasServer = Boolean(
      skillUiState.serverSkill &&
      skillUiState.serverSkill.id === skillUiState.activeSkillId
    );
    skillUiState.serverSkill = null;
    skillUiState.serverSlotSources = {};
    if (activeWasServer) skillUiState.activeSkillId = null;
    render();
    return true;
  }

  function renderPreviewModel(model) {
    if (!model || !TemplateRenderer) return false;
    TemplateRenderer.applyRenderModel(document, model);
    const banner = $("skillPreviewBanner");
    if (banner) banner.hidden = false;
    return true;
  }

  function activeTemplateProfile() {
    if (!Template) return null;
    if (!TemplateStore) return Template.builtInTemplate();
    const store = loadTemplateStore();
    if (!TemplateSelection) return TemplateStore.defaultTemplate(store);
    return TemplateSelection.resolveActiveTemplate(
      store,
      TemplateSelection.readEnvelope(templateStorage()),
      draft.meta.quoteNo
    );
  }

  /* 미리보기 authority: 선택된 내 견적서의 승인 profile 이 있으면 그것을 쓴다.
     없으면 기존 template selection 으로 fallback. advanced template-management UI 는
     activeTemplateProfile 을 그대로 쓰므로 이 override 에 영향받지 않는다. */
  function renderTemplateAuthority() {
    return activeSkillProfile() || activeTemplateProfile();
  }

  /* 미리보기는 승인된 양식만 대상으로 한다(승인 경계 우회 금지). */
  function previewTemplateProfile() {
    if (!TemplateStore || !templateUiState.previewTemplateId) return null;
    const candidate = TemplateStore.getTemplate(loadTemplateStore(), templateUiState.previewTemplateId);
    return candidate && candidate.approved ? candidate : null;
  }

  function templateRows() {
    if (!TemplateUi || !TemplateSelection) return [];
    return TemplateUi.buildRows(TemplateSelection.listForManagement(loadTemplateStore()), {
      activeTemplateId: (activeTemplateProfile() || {}).id || null,
      previewTemplateId: templateUiState.previewTemplateId,
      renamingTemplateId: templateUiState.renamingTemplateId
    });
  }

  function renderTemplateUi() {
    if (!TemplateUi || !TemplateStore || !TemplateSelection) return;
    const store = loadTemplateStore();
    const templates = TemplateSelection.listForManagement(store);
    const active = activeTemplateProfile();
    const select = $("templateSelect");
    const listHost = $("templateList");
    const statusHost = $("templateStatus");

    if (select) {
      const options = TemplateUi.buildOptions(templates, active ? active.id : null);
      select.innerHTML = TemplateUi.renderOptionsMarkup(options);
      select.disabled = options.filter(function (option) { return !option.disabled; }).length <= 1;
    }
    if (listHost) {
      listHost.innerHTML = TemplateUi.renderRowsMarkup(templateRows(), {
        previewTemplateId: templateUiState.previewTemplateId
      });
    }
    if (statusHost) {
      statusHost.textContent = TemplateUi.buildStatusText(active, {
        previewTemplateId: templateUiState.previewTemplateId
      });
    }
    renderClonerUi();
  }

  const TEMPLATE_RESULT_MESSAGES = {
    template_not_approved: "승인되지 않은 양식은 적용할 수 없습니다.",
    builtin_template_immutable: "기본 견적서는 삭제하거나 이름을 바꿀 수 없습니다.",
    template_limit_reached: "저장할 수 있는 양식 수를 초과했습니다.",
    delete_cancelled: "",
    template_not_found: "양식을 찾지 못했습니다.",
    invalid_template_name: "양식 이름을 입력한 뒤 저장해 주세요.",
    selection_storage_failed: "선택한 양식을 저장하지 못했습니다.",
    template_storage_failed: "양식을 저장하지 못했습니다.",
    private_asset_requires_account_skill: "로고·도장은 로그인 계정의 내 견적서에서만 사용할 수 있습니다.",
    slot_rendering_not_supported: "이번 단계에서는 로고·도장 슬롯을 저장할 수 없습니다."
  };

  function applyTemplateResult(result, successMessage) {
    if (!result || !result.ok) {
      const message = result ? TEMPLATE_RESULT_MESSAGES[result.code] : null;
      if (message) toast(message, 3200);
      return false;
    }
    /* 성공한 적용은 미리보기를 반드시 종료한다 — 배너가 남지 않아야 한다. */
    const nextState = TemplateUi.resolveUiStateAfterApply(templateUiState, true);
    templateUiState.previewTemplateId = nextState.previewTemplateId;
    templateUiState.renamingTemplateId = nextState.renamingTemplateId;
    if (successMessage) toast(successMessage);
    renderTemplateUi();
    render();
    return true;
  }

  const TEMPLATE_ACTIONS = {
    select: function (id) {
      const result = TemplateSelection.selectTemplate(templateStorage(), draft.meta.quoteNo, id);
      return applyTemplateResult(result, "이 견적에 사용할 양식을 변경했습니다.");
    },
    default: function (id) {
      return applyTemplateResult(TemplateSelection.setDefaultTemplate(templateStorage(), id), "앞으로 새 견적에 쓸 기본 양식으로 설정했습니다.");
    },
    duplicate: function (id) {
      return applyTemplateResult(TemplateSelection.duplicateTemplate(templateStorage(), id), "양식을 복제했습니다. 승인 후 사용할 수 있습니다.");
    },
    remove: function (id) {
      const result = TemplateSelection.deleteTemplate(templateStorage(), id, {
        confirm: function (template) {
          return window.confirm('"' + template.name + '" 양식을 삭제할까요? 이 브라우저에서만 삭제됩니다.');
        }
      });
      if (result && result.code === "delete_cancelled") return false;
      return applyTemplateResult(result, "양식을 삭제했습니다.");
    },
    preview: function (id) {
      const candidate = TemplateStore.getTemplate(loadTemplateStore(), id);
      if (!candidate || !candidate.approved) {
        toast("승인된 양식만 미리볼 수 있습니다.", 3200);
        return false;
      }
      templateUiState.previewTemplateId = id;
      renderTemplateUi();
      render();
      return true;
    },
    "preview-apply": function (id) { return TEMPLATE_ACTIONS.select(id); },
    "preview-cancel": function () {
      templateUiState.previewTemplateId = null;
      renderTemplateUi();
      render();
      return true;
    },
    rename: function (id) {
      templateUiState.renamingTemplateId = id;
      renderTemplateUi();
      const input = document.querySelector('#templateList [data-role="rename-input"]');
      if (input) { input.focus(); input.select(); }
      return true;
    },
    "rename-cancel": function () {
      templateUiState.renamingTemplateId = null;
      renderTemplateUi();
      return true;
    },
    "rename-save": function (id) {
      const input = document.querySelector('#templateList [data-role="rename-input"]');
      return applyTemplateResult(
        TemplateSelection.renameTemplate(templateStorage(), id, input ? input.value : ""),
        "양식 이름을 변경했습니다."
      );
    }
  };

  /* 템플릿은 표현·배치만 소유한다. 화면에 보이는 금액·세금·유효일은 모두 QuoteCore 파생값이다.
     입력 폼의 업무 데이터는 양식과 무관하게 그대로 유지된다. */
  function render() {
    const banner = $("skillPreviewBanner");
    if (banner) banner.hidden = true;
    const previewProfile = previewTemplateProfile();
    const authority = previewProfile || renderTemplateAuthority();
    const serverSkillActive = Boolean(
      !previewProfile &&
      skillUiState.serverSkill &&
      skillUiState.serverSkill.id === skillUiState.activeSkillId
    );
    const model = TemplateRenderer.buildRenderModel(
      draft,
      authority,
      {
        taxReviewRequired,
        slotSources: serverSkillActive ? skillUiState.serverSlotSources : {}
      }
    );
    if (model) TemplateRenderer.applyRenderModel(document, model);

    /* 입력 폼의 금액 셀은 견적서 render projection 과 별개로 QuoteCore 파생값을 그대로 쓴다. */
    const totals = Core.computeDraftTotals(draft);
    document.querySelectorAll("#items .item-row").forEach((row, i) => {
      const cell = row.querySelector(".amount-value");
      if (cell && totals.amounts[i] !== undefined) cell.textContent = Core.formatMoney(totals.amounts[i]);
    });

    saveDraft();
  }

  /* ── 발신자 프리셋 ── */

  const sampleSender = {
    company: "샘플 공급사",
    rep: "대표자명",
    bizNo: "000-00-00000",
    address: "",
    phone: "000-0000-0000",
    email: "hello@example.com"
  };

  function loadSavedSender() {
    try {
      const saved = JSON.parse(localStorage.getItem(Core.SENDER_STORAGE_KEY) || "null");
      return saved && typeof saved === "object" ? saved : null;
    } catch (err) {
      return null;
    }
  }

  $("senderPreset").addEventListener("change", () => {
    if ($("senderPreset").value === "sample") {
      Object.assign(draft.sender, sampleSender, { presetId: "sample" });
    } else {
      const saved = loadSavedSender();
      Object.assign(draft.sender, saved || {
        company: "", rep: "", bizNo: "", address: "", phone: "", email: ""
      }, { presetId: "custom" });
    }
    fillInputsFromDraft();
    render();
  });

  $("saveSender").addEventListener("click", () => {
    draft.sender.presetId = "custom";
    const sender = {
      company: draft.sender.company.trim(),
      rep: draft.sender.rep.trim(),
      bizNo: draft.sender.bizNo.trim(),
      address: draft.sender.address.trim(),
      phone: draft.sender.phone.trim(),
      email: draft.sender.email.trim()
    };
    try {
      localStorage.setItem(Core.SENDER_STORAGE_KEY, JSON.stringify(sender));
    } catch (err) {
      /* 저장 실패 시에도 데모 진행 가능 */
    }
    $("senderPreset").value = "custom";
    render();
    toast("이 브라우저에 발신자를 저장했습니다.");
  });

  /* ── 새 견적 (사용자 확인 후 현재 draft 초기화) ── */

  $("newQuote").addEventListener("click", () => {
    if (!window.confirm("현재 입력한 견적 내용을 모두 지우고 새로 시작할까요?")) return;
    const next = createBlankNextDraft();
    if (!next) {
      toast("새 견적을 시작하지 못했습니다.");
      return;
    }
    draft = next;
    taxReviewRequired = false;
    persistTaxReviewRequired(false);
    itemSeq = 1;
    renderItems();
    fillInputsFromDraft();
    renderTaxReviewState();
    render();
    toast("보내는 사람 정보는 유지하고 새 고객 견적을 시작합니다.");
  });

  /* ── 인쇄: 브라우저 머리글/바닥글은 코드로 끌 수 없어 저장 전 짧게 안내 ── */

  $("printPdf").addEventListener("click", () => {
    const failure = printReadinessFailure();
    if (failure) {
      toast(failure.message, 4200);
      if (failure.code === "tax_review") focusTaxReview();
      else focusReadinessTarget(failure.code);
      return;
    }

    render();
    toast("PDF 저장 시 인쇄 설정에서 '머리글과 바닥글'을 해제하면 견적서만 깔끔하게 저장됩니다.", 5000);
    setTimeout(() => window.print(), 600);
  });

  $("emailFuture").addEventListener("click", () => {
    toast("이메일 전송은 다음 단계에서 Gmail/메일 연동으로 붙입니다.");
  });

  $("saveHistory").addEventListener("click", () => {
    const result = saveCurrentToHistory();
    if (!result.ok) toast("최근 견적 저장에 실패했습니다.");
  });

  $("resetLocalData").addEventListener("click", resetBrowserLocalData);

  const settingsPanel = $("settingsPanel");
  $("settingsButton").addEventListener("click", () => {
    if (settingsPanel) settingsPanel.hidden = !settingsPanel.hidden;
  });
  $("settingsClose").addEventListener("click", () => {
    if (settingsPanel) settingsPanel.hidden = true;
  });

  /* ── 모드 전환 (upload/chat은 의도된 future affordance) ── */

  document.querySelectorAll(".mode").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".mode").forEach((b) => b.classList.remove("active"));
      button.classList.add("active");
      if (button.dataset.mode === "manual") {
        $("futureNote").className = "future-note";
        $("futureNote").textContent = "";
        return;
      }
      if (button.dataset.mode === "upload") {
        document.querySelectorAll(".mode").forEach((b) => b.classList.remove("active"));
        document.querySelector('.mode[data-mode="manual"]').classList.add("active");
        $("futureNote").className = "future-note";
        $("futureNote").textContent = "";
        document.dispatchEvent(new CustomEvent("b66:open-file-intake"));
        return;
      }
      document.querySelectorAll(".mode").forEach((b) => b.classList.remove("active"));
      document.querySelector('.mode[data-mode="manual"]').classList.add("active");
      $("futureNote").className = "future-note";
      $("futureNote").textContent = "";
      document.dispatchEvent(new CustomEvent("b66:open-easy-chat"));
    });
  });

  /* ── 양식 선택/관리 이벤트 (UI 는 얇게, 판단은 selection 계층이 담당) ── */

  $("templateSelect").addEventListener("change", (event) => {
    const id = event.target.value;
    if (!id) return;
    if (!TEMPLATE_ACTIONS.select(id)) renderTemplateUi();
  });

  $("templateManageToggle").addEventListener("click", () => {
    templateUiState.manageOpen = !templateUiState.manageOpen;
    $("templateManagePanel").hidden = !templateUiState.manageOpen;
    $("templateManageToggle").setAttribute("aria-expanded", String(templateUiState.manageOpen));
    renderTemplateUi();
  });

  $("templateList").addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button || button.disabled) return;
    const action = TEMPLATE_ACTIONS[button.dataset.action];
    if (!action) return;
    action(button.dataset.templateId);
  });

  $("templateList").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const input = event.target.closest('[data-role="rename-input"]');
    if (!input) return;
    event.preventDefault();
    TEMPLATE_ACTIONS["rename-save"](input.dataset.templateId);
  });

  $("templateCreate").addEventListener("click", () => {
    const active = activeTemplateProfile();
    if (!active) return;
    templateUiState.manageOpen = true;
    $("templateManagePanel").hidden = false;
    $("templateManageToggle").setAttribute("aria-expanded", "true");
    applyTemplateResult(
      TemplateSelection.createCandidate(templateStorage(), {
        sourceTemplateId: active.id,
        quoteNo: draft.meta.quoteNo
      }),
      "새 양식을 만들었습니다. 승인 후 사용할 수 있습니다."
    );
  });

  /* #3184 승인/본뜨기 흐름의 entry point — 이번 이슈에서는 진입점만 둔다. */
  $("templateClone").addEventListener("click", () => {
    templateUiState.manageOpen = true;
    $("templateManagePanel").hidden = false;
    $("templateManageToggle").setAttribute("aria-expanded", "true");
    $("templateCloneFile").click();
  });

  const TEMPLATE_CLONE_MESSAGES = {
    unsupported_candidate_field: "지원하지 않는 후보 필드가 있어 가져올 수 없습니다.",
    invalid_candidate_content: "후보 양식 내용이 올바르지 않습니다.",
    invalid_candidate_schema: "지원하지 않는 후보 형식입니다.",
    invalid_candidate_review: "검토 정보가 올바르지 않습니다.",
    invalid_candidate_confidence: "신뢰도 값이 범위를 벗어났습니다.",
    invalid_candidate_provenance: "출처 정보가 올바르지 않습니다.",
    invalid_candidate_name: "양식 이름을 입력해 주세요.",
    storage_required_for_approval_invalidation: "저장소를 사용할 수 없어 기존 승인을 무효화하지 못했습니다.",
    forbidden_candidate_field: "허용되지 않는 필드가 포함되어 있습니다.",
    candidate_changed_after_review: "검토 후 내용이 바뀌어 다시 확인해야 합니다.",
    session_not_reviewable: "검토 중인 후보가 없습니다.",
    session_not_editable: "지금은 후보를 수정할 수 없습니다.",
    template_not_approved: "승인되지 않은 양식은 적용할 수 없습니다.",
    template_limit_reached: "저장할 수 있는 양식 수를 초과했습니다.",
    private_asset_requires_account_skill: "로고·도장은 로그인 계정의 내 견적서에서만 사용할 수 있습니다.",
    slot_rendering_not_supported: "이번 단계에서는 로고·도장 슬롯을 저장할 수 없습니다.",
    legacy_hwp_unsupported: "구형 HWP 파일은 지원하지 않습니다. HWPX로 변환해 주세요.",
    unsupported_file_type: "지원하지 않는 파일 형식입니다.",
    invalid_file_size: "파일 크기가 허용 범위를 벗어났습니다.",
    empty_file: "빈 파일은 사용할 수 없습니다.",
    invalid_file: "파일을 확인할 수 없습니다.",
    invalid_file_name: "파일 이름을 확인할 수 없습니다.",
    media_extension_mismatch: "파일 형식과 확장자가 일치하지 않습니다.",
    preflight_failed: "파일 사전 검증에 실패했습니다."
  };

  function cloneMessage(code) {
    return TEMPLATE_CLONE_MESSAGES[code] || "본뜨기를 진행할 수 없습니다.";
  }

  function renderClonerUi() {
    if (!TemplateUi || !TemplateCloner) return;
    const panel = $("templateClonerPanel");
    if (!panel) return;

    const started = Boolean(clonerSession);
    panel.hidden = !(templateUiState.manageOpen && started);
    if (!started) return;

    const statusHost = $("templateClonerStatus");
    if (statusHost) statusHost.textContent = TemplateUi.buildClonerStatusText(TemplateCloner, clonerSession);

    const reviewHost = $("templateReview");
    const reviewModel = clonerSession.candidate && TemplateCandidate
      ? TemplateCandidate.buildReviewModel(clonerSession.candidate)
      : null;
    if (reviewHost) {
      reviewHost.hidden = !reviewModel;
      reviewHost.innerHTML = reviewModel
        ? TemplateUi.renderReviewMarkup(reviewModel, {
          progress: TemplateCloner.buildProgress(clonerSession),
          approved: clonerSession.status === TemplateCloner.STATUS_APPROVED
        })
        : "";
    }

    const reviewable = clonerSession.status === TemplateCloner.STATUS_REVIEWING;
    const approveButton = $("templateApprove");
    const cancelButton = $("templateReviewCancel");
    if (approveButton) {
      approveButton.hidden = !reviewable;
      approveButton.disabled = !reviewable;
    }
    if (cancelButton) cancelButton.hidden = !started;
  }

  function applyClonerResult(result, successMessage) {
    if (!result) return false;
    clonerSession = result.session || clonerSession;
    renderClonerUi();
    if (!result.ok) {
      toast(cloneMessage(result.code), 4200);
      return false;
    }
    if (successMessage) toast(successMessage);
    return true;
  }

  function startClonerFromFile(file) {
    if (!TemplateCloner) return false;
    const preflight = FileIntake
      ? FileIntake.classifyFile(file)
      : { ok: false, error: "preflight_failed" };
    const session = clonerSession || TemplateCloner.createSession({});
    const result = TemplateCloner.startFromFile(session, preflight);
    applyClonerResult(result);
    if (result.ok) {
      toast("파일 검증을 마쳤습니다. 문서 분석기는 아직 연결되지 않았습니다.", 4200);
    }
    return result.ok;
  }

  function injectClonerCandidate(payload) {
    if (!TemplateCloner) return { ok: false, code: "cloner_unavailable" };
    const session = (clonerSession && clonerSession.status !== TemplateCloner.STATUS_APPROVED)
      ? clonerSession
      : TemplateCloner.createSession({});
    const result = TemplateCloner.startFromCandidate(session, payload);
    applyClonerResult(result);
    return result;
  }

  function approveClonerCandidate() {
    if (!TemplateCloner || !clonerSession) return { ok: false, code: "session_missing" };
    const result = TemplateCloner.approveCandidate(clonerSession, templateStorage(), {});
    if (!result.ok) {
      applyClonerResult(result);
      return result;
    }
    clonerSession = result.session;
    templateUiState.previewTemplateId = null;
    renderTemplateUi();
    render();
    toast("양식을 승인해 저장했습니다. 이제 이 견적에 적용할 수 있습니다.", 3600);
    return result;
  }

  function cancelClonerSession() {
    if (!TemplateCloner || !clonerSession) return { ok: false, code: "session_missing" };
    const result = TemplateCloner.cancelSession(clonerSession);
    clonerSession = result.session;
    renderClonerUi();
    toast("본뜨기를 취소했습니다. 저장된 것은 없습니다.", 3000);
    return result;
  }

  $("templateCloneFile").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    event.target.value = "";
    if (!file) return;
    startClonerFromFile(file);
  });

  $("templateApprove").addEventListener("click", () => { approveClonerCandidate(); });
  $("templateReviewCancel").addEventListener("click", () => { cancelClonerSession(); });

  $("templateReview").addEventListener("input", (event) => {
    const input = event.target.closest('[data-role="candidate-name"]');
    if (!input || !TemplateCloner || !clonerSession) return;
    const result = TemplateCloner.editCandidate(clonerSession, { name: input.value }, { storage: templateStorage() });
    if (!result.ok) toast(cloneMessage(result.code), 3600);
    clonerSession = result.session || clonerSession;
    renderClonerUi();
  });

  window.B66QuoteTemplateClonerBridge = Object.freeze({
    createSession: () => { clonerSession = TemplateCloner.createSession({}); renderClonerUi(); return clonerSession; },
    injectCandidate: (payload) => injectClonerCandidate(payload),
    editCandidate: (patch) => {
      if (!clonerSession) return { ok: false, code: "session_missing" };
      const result = TemplateCloner.editCandidate(clonerSession, patch || {}, { storage: templateStorage() });
      clonerSession = result.session || clonerSession;
      renderClonerUi();
      render();
      return result;
    },
    approve: () => approveClonerCandidate(),
    cancel: () => cancelClonerSession(),
    analyzer: () => (TemplateCandidate ? TemplateCandidate.analyzerBoundary() : null),
    state: () => clonerSession,
    review: () => (clonerSession && clonerSession.candidate && TemplateCandidate
      ? TemplateCandidate.buildReviewModel(clonerSession.candidate)
      : null),
    startFromFile: (preflight) => {
      const session = clonerSession || TemplateCloner.createSession({});
      const result = TemplateCloner.startFromFile(session, preflight);
      applyClonerResult(result);
      return result;
    }
  });

  window.B66QuoteExtractionBridge = Object.freeze({
    validate: validateExtractionResult,
    apply: applyExtractionResult,
    getLastReview: getLastExtractionReview
  });

  window.B66QuoteAppBridge = Object.freeze({
    getDraft: () => cloneDraft(draft),
    replaceDraft,
    createFreshDraft,
    createBlankNextDraft,
    copyHistoryAsNew,
    saveCurrentToHistory,
    resetBrowserLocalData,
    getHistoryEnvelope: () => {
      const envelope = loadHistoryEnvelope();
      return envelope ? cloneDraft(envelope) : null;
    },
    focusTaxReview,
    toast
  });

  window.B66QuoteTemplateBridge = Object.freeze({
    list: () => (TemplateSelection ? TemplateSelection.listForManagement(loadTemplateStore()) : []),
    activeId: () => (activeTemplateProfile() || {}).id || null,
    selectedId: currentTemplateId,
    select: (id) => TemplateSelection.selectTemplate(templateStorage(), draft.meta.quoteNo, id),
    setDefault: (id) => TemplateSelection.setDefaultTemplate(templateStorage(), id),
    rename: (id, name) => TemplateSelection.renameTemplate(templateStorage(), id, name),
    duplicate: (id) => TemplateSelection.duplicateTemplate(templateStorage(), id),
    remove: (id, confirmFn) => TemplateSelection.deleteTemplate(templateStorage(), id, { confirm: confirmFn }),
    candidate: (options) => TemplateSelection.createCandidate(templateStorage(), options || {}),
    preview: (id) => TEMPLATE_ACTIONS.preview(id),
    cancelPreview: () => TEMPLATE_ACTIONS["preview-cancel"](),
    refresh: () => { renderTemplateUi(); render(); },
    state: () => Object.assign({}, templateUiState)
  });

  /* ── 초기화 ── */

  renderItems();
  fillInputsFromDraft();
  bindFields();
  $("addItem").addEventListener("click", addItem);
  renderTaxReviewState();
  renderTemplateUi();
  if (SkillUi && typeof SkillUi.bindSkillSection === "function" && typeof localStorage !== "undefined") {
    skillUiApi = SkillUi.bindSkillSection(document, {
      storage: localStorage,
      fetch: (url, options) => window.fetch(url, options),
      getDraftSnapshot: () => cloneDraft(draft),
      applySkillToForm,
      renderMain: render,
      renderPreviewModel,
      toast,
      confirm: (message) => window.confirm(message),
      focusMain: () => {
        const node = $("recipientCompany");
        if (node) node.focus();
      }
    });
  }
  window.B66QuoteSkillBridge = Object.freeze({
    activeSkillId: () => skillUiState.activeSkillId,
    serverSkillId: () => (skillUiState.serverSkill ? skillUiState.serverSkill.id : null),
    serverSlotSourceKeys: () => Object.keys(skillUiState.serverSlotSources || {}).sort(),
    applySkill: applySkillToForm,
    setServerSkill,
    clearServerSkill,
    refresh: () => {
      if (skillUiApi) skillUiApi.refresh();
      render();
    }
  });
  render();
})();