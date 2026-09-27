/* B66 · Quote Beta — app.js (UI 레이어)
   상태는 QuoteDraft 하나(quote-core.js)로 관리하고 화면은 항상 draft에서 파생.
   draft는 localStorage에 자동 저장되며, 복원 실패 시 기본 데모 상태로 fallback. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const Core = window.QuoteCore;
  const Extraction = window.QuoteExtraction || null;

  /* ── 상태: QuoteDraft ── */

  let draft = loadDraft() || Core.createDefaultDraft();
  let lastExtractionReview = null;
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

  function saveDraft() {
    try {
      localStorage.setItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(draft));
    } catch (err) {
      /* 저장 실패는 데모 진행을 막지 않음 */
    }
  }

  /* ── 공통 유틸 ── */

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  }

  function textOrDash(value) {
    const v = String(value ?? "").trim();
    return v || "-";
  }

  function toast(message, duration) {
    $("toast").textContent = message;
    $("toast").classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => $("toast").classList.remove("show"), duration || 1800);
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
      draft.tax.mode = e.target.value;
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

  /* ── 렌더링: 입력 요약 + 미리보기 + 자동 저장 (금액은 매번 파생) ── */

  function vatSummaryLabel(mode) {
    if (mode === Core.TAX_MODES.INCLUSIVE) return "부가세 (포함가 분리)";
    if (mode === Core.TAX_MODES.EXEMPT) return "부가세 (면세)";
    return "부가세";
  }

  function render() {
    const totals = Core.computeTotals(draft.items, draft.tax.mode);

    $("subtotalText").textContent = Core.formatMoney(totals.supply);
    $("vatText").textContent = Core.formatMoney(totals.vat);
    $("grandText").textContent = Core.formatMoney(totals.grand);

    $("pvQuoteNo").textContent = "견적번호  " + textOrDash(draft.meta.quoteNo);
    $("pvDate").textContent = "견적일  " + textOrDash(draft.meta.issueDate);
    $("pvValidity").textContent = "유효기간  " + draft.meta.validDays + "일";
    const validUntil = Core.computeValidUntil(draft.meta.issueDate, draft.meta.validDays);
    $("pvValidUntil").textContent = "유효일  " + (validUntil || "-");
    $("pvTaxMode").textContent = "세금  " + Core.TAX_LABELS[draft.tax.mode];

    $("pvSenderCompany").textContent = textOrDash(draft.sender.company);
    $("pvSenderRep").textContent = "대표자  " + textOrDash(draft.sender.rep);
    $("pvSenderBizNo").textContent = "사업자번호  " + textOrDash(draft.sender.bizNo);
    $("pvSenderAddress").textContent = textOrDash(draft.sender.address);
    $("pvSenderContact").textContent = [draft.sender.phone.trim(), draft.sender.email.trim()].filter(Boolean).join(" · ") || "-";

    $("pvRecipientCompany").textContent = textOrDash(draft.recipient.company);
    $("pvRecipientPerson").textContent = "담당자  " + textOrDash(draft.recipient.person);
    $("pvRecipientAddress").textContent = textOrDash(draft.recipient.address);
    $("pvRecipientEmail").textContent = draft.recipient.email.trim() || "-";

    $("pvItems").innerHTML = draft.items.map((item, i) => `
      <tr>
        <td class="${item.name ? "" : "empty"}">${escapeHtml(item.name || "품목을 입력하세요")}</td>
        <td>${escapeHtml(Core.formatInputNumber(item.qty))}</td>
        <td>${Core.formatMoney(item.unitPrice)}</td>
        <td>${Core.formatMoney(totals.amounts[i])}</td>
      </tr>`
    ).join("");

    $("pvSubtotal").textContent = Core.formatMoney(totals.supply);
    $("pvVatLabel").textContent = vatSummaryLabel(draft.tax.mode);
    $("pvVat").textContent = Core.formatMoney(totals.vat);
    $("pvGrand").textContent = Core.formatMoney(totals.grand);
    $("pvMemo").textContent = draft.memo.trim() || "비고 없음";

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
    draft = Core.createDefaultDraft();
    renderItems();
    fillInputsFromDraft();
    render();
    toast("새 견적을 시작합니다.");
  });

  /* ── 인쇄: 브라우저 머리글/바닥글은 코드로 끌 수 없어 저장 전 짧게 안내 ── */

  $("printPdf").addEventListener("click", () => {
    render();
    toast("PDF 저장 시 인쇄 설정에서 '머리글과 바닥글'을 해제하면 견적서만 깔끔하게 저장됩니다.", 5000);
    setTimeout(() => window.print(), 600);
  });

  $("emailFuture").addEventListener("click", () => {
    toast("이메일 전송은 다음 단계에서 Gmail/메일 연동으로 붙입니다.");
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
      $("futureNote").className = "future-note show";
      $("futureNote").textContent = button.dataset.mode === "upload"
        ? "파일 업로드 → 견적서 필드 자동 추출은 다음 단계에서 AI/OCR Skill로 연결합니다. 이 데모에서는 파일을 외부로 전송하지 않습니다."
        : "자연어 채팅 → QuoteDraft 자동 입력은 다음 단계에서 연결합니다. 금액 계산은 AI가 아니라 현재와 같은 결정적 계산 코드가 담당합니다.";
    });
  });

  window.B66QuoteExtractionBridge = Object.freeze({
    validate: validateExtractionResult,
    apply: applyExtractionResult,
    getLastReview: getLastExtractionReview
  });

  /* ── 초기화 ── */

  renderItems();
  fillInputsFromDraft();
  bindFields();
  $("addItem").addEventListener("click", addItem);
  render();
})();
