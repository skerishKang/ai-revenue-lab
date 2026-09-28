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
  const TAX_REVIEW_STORAGE_KEY = "quoteBeta.taxReview.v1";
  const TAX_REVIEW_SCHEMA_VERSION = 1;

  /* ── 상태: QuoteDraft ── */

  let draft = loadDraft() || Core.createDefaultDraft();
  let lastExtractionReview = null;
  let taxReviewRequired = loadTaxReviewRequired(draft);
  let suppressNextDraftSave = false;
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

    renderItems();
    fillInputsFromDraft();
    renderTaxReviewState();
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

  function buildItemRow(item, index) {
    const row = document.createElement("div");
    row.className = "item-row";
    row.innerHTML = `
      <input class="item-name" aria-label="품목명" value="${escapeHtml(item.name)}" placeholder="품목명">
      <div class="item-cell qty">
        <span class="cell-label">수량</span>
        <input class="item-qty" aria-label="수량" type="text" inputmode="decimal" value="${escapeHtml(Core.formatInputNumber(item.qty))}">
      </div>
      <div class="item-cell price">
        <span class="cell-label">단가</span>
        <input class="item-price" aria-label="단가" type="text" inputmode="numeric" value="${escapeHtml(Core.formatInputNumber(item.unitPrice))}">
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
      draft.items[index].unitPrice = Core.parseMoney(e.target.value);
      render();
    });
    row.querySelector(".item-price").addEventListener("change", (e) => {
      e.target.value = Core.formatInputNumber(Core.parseMoney(e.target.value));
    });
    row.querySelector(".remove-item").addEventListener("click", () => removeItem(index));
    return row;
  }

  function renderItems() {
    const host = $("items");
    host.innerHTML = "";
    draft.items.forEach((item, index) => host.appendChild(buildItemRow(item, index)));
  }

  function addItem() {
    draft.items.push({ id: nextItemId(), name: "", qty: 1, unitPrice: 0 });
    renderItems();
    render();
    const rows = $("items").querySelectorAll(".item-row");
    rows[rows.length - 1].querySelector(".item-name").focus();
  }

  function removeItem(index) {
    if (draft.items.length === 1) {
      draft.items[0] = { id: draft.items[0].id, name: "", qty: 1, unitPrice: 0 };
    } else {
      draft.items.splice(index, 1);
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

  function activeTemplateProfile() {
    if (!Template) return null;
    if (!TemplateStore) return Template.builtInTemplate();
    return TemplateStore.defaultTemplate(loadTemplateStore());
  }

  /* 템플릿은 표현·배치만 소유한다. 화면에 보이는 금액·세금·유효일은 모두 QuoteCore 파생값이다. */
  function render() {
    const model = TemplateRenderer.buildRenderModel(draft, activeTemplateProfile(), {
      taxReviewRequired
    });
    if (model) TemplateRenderer.applyRenderModel(document, model);

    /* 입력 폼의 금액 셀은 견적서 render projection 과 별개로 QuoteCore 파생값을 그대로 쓴다. */
    const totals = Core.computeTotals(draft.items, draft.tax.mode);
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
      $("futureNote").className = "future-note show";
      $("futureNote").textContent = "자연어 채팅 → QuoteDraft 자동 입력은 다음 단계에서 연결합니다. 금액 계산은 AI가 아니라 현재와 같은 결정적 계산 코드가 담당합니다.";
    });
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

  /* ── 초기화 ── */

  renderItems();
  fillInputsFromDraft();
  bindFields();
  $("addItem").addEventListener("click", addItem);
  renderTaxReviewState();
  render();
})();
