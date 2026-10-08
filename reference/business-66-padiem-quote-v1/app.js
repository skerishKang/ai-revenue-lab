/* B66 · Quote Beta — app.js (UI 레이어)
   상태는 QuoteDraft 하나(quote-core.js)로 관리하고 화면은 항상 draft에서 파생.
   draft는 localStorage에 자동 저장되며, 복원 실패 시 Production용 빈 초안으로 fallback. */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const Core = window.QuoteCore;
  const Extraction = window.QuoteExtraction || null;
  const History = window.QuoteHistory || null;
  const Template = window.QuoteTemplate || null;
  const CgiTemplateV2 = window.B66CgiTemplateV2 || null;
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
  const AccountScope = window.QuoteAccountScope || null;
  const ServerHistory = window.B66QuoteHistoryServer || null;
  const TAX_REVIEW_STORAGE_KEY = "quoteBeta.taxReview.v1";
  const TAX_REVIEW_SCHEMA_VERSION = 1;

  /* ── 최근 견적 server authority(#3405 Slice B) ──
     signed-in 동안 최근 견적 authority 는 서버다. browser local
     quoteBeta.history.v1 은 offline convenience cache 로만 유지되며,
     서버 실패가 localStorage 로 조용히 대체되는 일은 없다.

     계정 사실(sign-in)과 client 가용성은 분리한다:
       SIGNED_IN + CLIENT_AVAILABLE -> server
       SIGNED_IN + CLIENT_MISSING   -> bounded ERROR (local fallback 금지)
       SIGNED_OUT                   -> bounded local/offline history
     client 부재로 signed-in authority 가 local 로 내려가면 안 된다. */
  const HISTORY_CLIENT_UNAVAILABLE = "history_client_unavailable";
  let serverHistorySignedIn = false;
  let serverSaveInFlight = false;
  let serverQuoteNoCandidates = [];

  /* canonical #3480 projection 이 확정한 계정 사실만 사용한다 */
  function serverHistoryRequired() {
    return serverHistorySignedIn === true;
  }

  /* server client 모듈과 그 계약 함수의 존재 여부만 본다 */
  function serverHistoryAvailable() {
    return Boolean(ServerHistory && AccountScope &&
      typeof ServerHistory.listQuotes === "function" &&
      typeof ServerHistory.getQuote === "function" &&
      typeof ServerHistory.saveQuote === "function" &&
      typeof ServerHistory.deleteQuote === "function" &&
      typeof ServerHistory.draftToHistorySnapshot === "function" &&
      typeof ServerHistory.historySnapshotToDraft === "function");
  }

  function serverHistoryActive() {
    return serverHistoryRequired() && serverHistoryAvailable();
  }

  /* ── 계정 경계(#3480) ──
     브라우저 로컬 private 상태는 canonical 인증 projection 이 소유권을 확정한 뒤에만
     읽는다/쓴다. storage 부재·marker 손상·signed-out 은 모두 fail closed 다. */

  const PRIVATE_STORAGE_KEYS = AccountScope
    ? AccountScope.privateKeys({
        Core,
        History,
        taxReviewKey: TAX_REVIEW_STORAGE_KEY,
        TemplateStore,
        TemplateSelection,
        SkillStore
      })
    : [
        Core.DRAFT_STORAGE_KEY,
        Core.SENDER_STORAGE_KEY,
        History && History.HISTORY_STORAGE_KEY,
        History && History.SEQUENCE_STORAGE_KEY,
        TAX_REVIEW_STORAGE_KEY,
        TemplateStore && TemplateStore.TEMPLATE_STORAGE_KEY,
        TemplateSelection && TemplateSelection.SELECTION_STORAGE_KEY,
        SkillStore && SkillStore.STORAGE_KEY
      ].filter(Boolean);

  function localStorageRef() {
    try {
      return typeof localStorage === "undefined" ? null : localStorage;
    } catch (err) {
      return null;
    }
  }

  /* canonical owner 가 확정되기 전에는 어떤 private key 도 읽지 않는다. */
  function privateStateReadable() {
    return AccountScope ? AccountScope.privateStateReadable() === true : false;
  }

  function readPrivateItem(key) {
    if (!privateStateReadable()) return null;
    const storage = localStorageRef();
    if (!storage) return null;
    try {
      const raw = storage.getItem(key);
      return raw === null || raw === undefined ? null : raw;
    } catch (err) {
      return null;
    }
  }

  function writePrivateItem(key, value) {
    if (!privateStateReadable()) return false;
    const storage = localStorageRef();
    if (!storage) return false;
    try {
      storage.setItem(key, value);
      return true;
    } catch (err) {
      return false;
    }
  }

  function removePrivateItem(key) {
    const storage = localStorageRef();
    if (!storage) return false;
    try {
      storage.removeItem(key);
      return true;
    } catch (err) {
      return false;
    }
  }

  /* ── 상태: QuoteDraft ── */

  let draft = loadDraft() || Core.createProductionDraft();
  let lastExtractionReview = null;
  let taxReviewRequired = loadTaxReviewRequired(draft);
  let suppressNextDraftSave = false;
  let transientPublicTemplateSelection = null;
  let clonerSession = null;
  let itemSeq = draft.items.reduce((max, it) => {
    const n = parseInt(String(it.id).replace(/^item-/, ""), 10);
    return Number.isFinite(n) ? Math.max(max, n) : max;
  }, 0);

  function nextItemId() {
    itemSeq += 1;
    return "item-" + itemSeq;
  }

  function isUntouchedLegacyDemoDraft(value) {
    if (!value) return false;
    const demo = Core.createDefaultDraft();
    return (
      value.meta && value.meta.source === "manual" &&
      value.meta.validDays === demo.meta.validDays &&
      JSON.stringify(value.sender) === JSON.stringify(demo.sender) &&
      JSON.stringify(value.recipient) === JSON.stringify(demo.recipient) &&
      JSON.stringify(value.items) === JSON.stringify(demo.items) &&
      value.tax && value.tax.mode === demo.tax.mode &&
      value.memo === demo.memo &&
      !value.calculationPolicy &&
      !value.detailGroups &&
      !(value.meta && value.meta.projectName)
    );
  }

  function loadDraft() {
    try {
      const normalized = Core.normalizeDraft(JSON.parse(readPrivateItem(Core.DRAFT_STORAGE_KEY) || "null"));
      /* Old untouched demo drafts are not authoritative user data. */
      return isUntouchedLegacyDemoDraft(normalized) ? null : normalized;
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
      const state = normalizeTaxReviewState(JSON.parse(readPrivateItem(TAX_REVIEW_STORAGE_KEY) || "null"));
      const quoteNo = String(activeDraft && activeDraft.meta && activeDraft.meta.quoteNo || "").trim();
      return Boolean(state && quoteNo && state.quoteNo === quoteNo);
    } catch (err) {
      return false;
    }
  }

  function persistTaxReviewRequired(required) {
    try {
      if (!required) {
        removePrivateItem(TAX_REVIEW_STORAGE_KEY);
        return true;
      }
      const quoteNo = String(draft && draft.meta && draft.meta.quoteNo || "").trim();
      if (!quoteNo) {
        removePrivateItem(TAX_REVIEW_STORAGE_KEY);
        return false;
      }
      return writePrivateItem(TAX_REVIEW_STORAGE_KEY, JSON.stringify({
        schemaVersion: TAX_REVIEW_SCHEMA_VERSION,
        quoteNo,
        required: true
      }));
    } catch (err) {
      return false;
    }
  }

  function saveDraft() {
    if (suppressNextDraftSave) {
      suppressNextDraftSave = false;
      return;
    }
    /* 저장 실패는 현재 브라우저 세션 진행을 막지 않음 */
    writePrivateItem(Core.DRAFT_STORAGE_KEY, JSON.stringify(draft));
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
      return History.normalizeEnvelope(JSON.parse(readPrivateItem(History.HISTORY_STORAGE_KEY) || "null"));
    } catch (err) {
      return History.normalizeEnvelope(null);
    }
  }

  function loadQuoteNoSequence() {
    if (!History) return null;
    try {
      return History.normalizeSequenceState(
        JSON.parse(readPrivateItem(History.SEQUENCE_STORAGE_KEY) || "null")
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
    /* server history 의 견적번호도 오늘 번호 중복 방지 후보로 반영한다.
       후보는 반드시 QuoteCore 가 정규화할 수 있는 형태여야 한다
       (allocateQuoteNo 는 후보마다 Core.normalizeDraft 를 거치므로
       schemaVersion 없는 최소형은 조용히 버려진다). 그래서 서버 스냅샷
       경계(historySnapshotToDraft)를 거쳐 오늘 번호만 후보로 남긴다. */
    serverQuoteNoCandidates.forEach((candidate) => candidates.push(candidate));
    return candidates;
  }

  function allocateFreshQuoteNo(now) {
    if (!History) return Core.createProductionDraft().meta.quoteNo;
    const allocation = History.allocateQuoteNo(
      loadQuoteNoSequence(),
      quoteNoCandidates(),
      now instanceof Date ? now : new Date()
    );
    /* 번호는 history/draft와 대조해 계산되므로 sequence 저장 실패만으로 진행을 막지 않음 */
    writePrivateItem(History.SEQUENCE_STORAGE_KEY, JSON.stringify(allocation.state));
    return allocation.quoteNo;
  }

  function createFreshDraft(source, now) {
    const dt = now instanceof Date ? now : new Date();
    const fresh = Core.createProductionDraft();
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

  async function saveCurrentToHistory() {
    if (!History) return { ok: false, error: "history_unavailable" };
    if (serverHistoryRequired()) {
      if (!serverHistoryAvailable()) {
        /* signed-in + client 부재: server authority 실패다. local 쓰기 0. */
        return { ok: false, error: HISTORY_CLIENT_UNAVAILABLE, authority: "server" };
      }
      /* signed-in: 서버가 authority 다. 서버 실패 시 local 쓰기로 대체하지
         않는다(NO_SILENT_LOCAL_FALLBACK). 성공 시에만 local cache 를 갱신한다. */
      if (serverSaveInFlight) return { ok: false, error: "save_in_progress", authority: "server" };
      serverSaveInFlight = true;
      try {
        const snapshot = ServerHistory.draftToHistorySnapshot(draft);
        if (!snapshot) return { ok: false, error: "history_unavailable", authority: "server" };
        const quoteNo = String(draft.meta.quoteNo || "").trim();
        const existing = await ServerHistory.listQuotes();
        const existingIds = existing.ok
          ? existing.quotes
              .filter((row) => row.quoteNo && quoteNo && row.quoteNo === quoteNo)
              .map((row) => row.quoteHistoryId)
              .slice(0, 5)
          : [];
        const saved = await ServerHistory.saveQuote(snapshot);
        if (!saved.ok) {
          return { ok: false, error: saved.code || "history_save_failed", authority: "server" };
        }
        /* 같은 견적번호의 이전 기록은 최신 저장으로 대체한다(local upsert 계약과
           동일한 의미). POST 가 먼저 성공한 뒤라서 실패해도 중복만 남는다. */
        let replaced = existingIds.length > 0;
        for (const oldId of existingIds) {
          if (oldId === saved.quote.quoteHistoryId) continue;
          await ServerHistory.deleteQuote(oldId);
        }
        const envelope = History.upsertEntryByQuoteNo(loadHistoryEnvelope(), draft, {
          id: saved.quote.quoteHistoryId
        });
        writePrivateItem(History.HISTORY_STORAGE_KEY, JSON.stringify(envelope));
        toast(replaced
          ? "같은 견적번호의 최근 견적을 최신 내용으로 업데이트했습니다."
          : "이 견적을 최근 견적에 저장했습니다.");
        window.dispatchEvent(new CustomEvent("b66:history-changed"));
        return { ok: true, authority: "server", updated: replaced, envelope: cloneDraft(envelope) };
      } finally {
        serverSaveInFlight = false;
      }
    }
    const before = loadHistoryEnvelope();
    const quoteNo = String(draft.meta.quoteNo || "").trim();
    const existed = Boolean(before && before.entries.some((entry) =>
      String(entry.draft.meta.quoteNo || "").trim() === quoteNo
    ));
    const envelope = History.upsertEntryByQuoteNo(before, draft);
    if (!writePrivateItem(History.HISTORY_STORAGE_KEY, JSON.stringify(envelope))) {
      return { ok: false, error: "history_storage_failed" };
    }
    toast(existed
      ? "같은 견적번호의 최근 견적을 최신 내용으로 업데이트했습니다."
      : "이 견적을 최근 견적에 저장했습니다.");
    window.dispatchEvent(new CustomEvent("b66:history-changed"));
    return { ok: true, updated: existed, envelope: cloneDraft(envelope) };
  }

  /* signed-in 최근 견적 목록: 서버 authority 만 돌려준다. 서버 실패는
     ok=false 로 bounded error state 를 유도할 뿐, local envelope 을
     대신 돌려주지 않는다. */
  async function listRecentQuotes() {
    if (!History) return { ok: false, authority: "local", error: "history_unavailable" };
    if (!serverHistoryRequired()) {
      return { ok: true, authority: "local", envelope: loadHistoryEnvelope() };
    }
    if (!serverHistoryAvailable()) {
      /* signed-in 인데 server client 가 없다: local 로 내려가지 않고 bounded error */
      serverQuoteNoCandidates = [];
      return { ok: false, authority: "server", error: HISTORY_CLIENT_UNAVAILABLE };
    }
    const result = await ServerHistory.listQuotes();
    if (!result.ok) {
      serverQuoteNoCandidates = [];
      return { ok: false, authority: "server", error: result.code || "history_read_failed" };
    }
    serverQuoteNoCandidates = result.quotes
      .filter((row) => row.quoteNo)
      .map((row) => ServerHistory.historySnapshotToDraft({
        schema: ServerHistory.SNAPSHOT_SCHEMA,
        quotationNo: row.quoteNo,
        issueDate: row.issueDate
      }))
      .filter(Boolean);
    const hydrated = await Promise.all(result.quotes.map(async (row) => {
      const detail = await ServerHistory.getQuote(row.quoteHistoryId);
      if (!detail.ok) return null;
      const restored = ServerHistory.historySnapshotToDraft(detail.quote.snapshot);
      if (!restored) return null;
      return {
        id: row.quoteHistoryId,
        savedAt: row.updatedAt || row.createdAt,
        draft: restored,
        totalsAuthority: detail.quote.totalsAuthority,
        quoteCoreRecalculationRequired: detail.quote.quoteCoreRecalculationRequired
      };
    }));
    const entries = hydrated.filter(Boolean);
    const envelope = History.normalizeEnvelope({
      schemaVersion: History.HISTORY_SCHEMA_VERSION,
      entries
    });
    return { ok: true, authority: "server", envelope, requested: result.quotes.length };
  }

  /* signed-in 삭제는 서버 성공 후에만 UI 에 반영된다(NO_OPTIMISTIC_DELETE).
     실패하면 행을 그대로 유지하고 bounded error 로 돌아온다. */
  async function deleteRecentQuote(quoteHistoryId) {
    if (!serverHistoryRequired()) {
      return { ok: false, authority: "local", error: "history_unavailable" };
    }
    if (!serverHistoryAvailable()) {
      /* signed-in + client 부재: server authority 실패다. local 삭제 0. */
      return { ok: false, authority: "server", error: HISTORY_CLIENT_UNAVAILABLE };
    }
    const result = await ServerHistory.deleteQuote(quoteHistoryId);
    if (!result.ok) {
      return { ok: false, authority: "server", error: result.code || "history_delete_failed" };
    }
    const envelope = History.deleteEntry(loadHistoryEnvelope(), quoteHistoryId);
    writePrivateItem(History.HISTORY_STORAGE_KEY, JSON.stringify(envelope));
    window.dispatchEvent(new CustomEvent("b66:history-changed"));
    return { ok: true, authority: "server", deleted: quoteHistoryId };
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

    /* 계정 결합(owner marker)은 계정 경계 authority 이므로 남기고 private 데이터만 지운다. */
    const storage = localStorageRef();
    if (!storage) {
      toast("브라우저 저장 데이터를 지우지 못했습니다.");
      return false;
    }

    try {
      if (AccountScope) AccountScope.removePrivateKeys(storage, PRIVATE_STORAGE_KEYS);
      else PRIVATE_STORAGE_KEYS.forEach((key) => storage.removeItem(key));
    } catch (err) {
      toast("브라우저 저장 데이터를 지우지 못했습니다.");
      return false;
    }

    clearTransientPublicTemplateSelection();

    /* 초기화 후에도 데모 사업 정보가 Production에 재등장하지 않는다 (#3479). */
    draft = Core.createProductionDraft();
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
    ["senderContactPerson", "sender", "contactPerson"],
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
        JSON.parse(readPrivateItem(TemplateStore.TEMPLATE_STORAGE_KEY) || "null")
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

  function transientPublicTemplateId() {
    if (privateStateReadable() || !transientPublicTemplateSelection) return null;
    const quoteNo = String(draft.meta.quoteNo || "");
    return transientPublicTemplateSelection.quoteNo === quoteNo
      ? transientPublicTemplateSelection.templateId
      : null;
  }

  function setTransientPublicTemplateSelection(templateId) {
    transientPublicTemplateSelection = {
      quoteNo: String(draft.meta.quoteNo || ""),
      templateId
    };
  }

  function clearTransientPublicTemplateSelection() {
    transientPublicTemplateSelection = null;
  }

  function templateStorage() {
    /* 계정 owner 가 확정되지 않았으면 선택/양식 브라우저 저장소를 읽거나 쓰지 않는다. */
    return privateStateReadable() ? localStorageRef() : null;
  }

  /* 외부 storage 를 받는 모듈(Selection/Store/SkillUi)에 주는 owner 게이트. */
  function ownerGatedStorage() {
    const storage = localStorageRef();
    if (!storage) return null;
    return {
      getItem(key) {
        if (!privateStateReadable()) return null;
        return storage.getItem(key);
      },
      setItem(key, value) {
        if (!privateStateReadable()) return;
        storage.setItem(key, value);
      },
      removeItem(key) {
        storage.removeItem(key);
      }
    };
  }

  function currentTemplateId() {
    if (!TemplateSelection) return null;
    const transientId = transientPublicTemplateId();
    if (transientId) return transientId;
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
        skill = SkillStore.getSkill(SkillStore.readStore(ownerGatedStorage()), skillUiState.activeSkillId);
      }
      if (!skill || skill.approved !== true) return null;
      const profile = Template.normalizeTemplate(skill.internalTemplate);
      return profile && Template.isApprovedProfile(profile) ? profile : null;
    } catch (err) {
      return null;
    }
  }

  function applySkillToForm(skill) {
    // The authenticated CGI Saved Quote Skill is solely owned by the server
    // bridge. A local skill section refresh/selection must not clear or replace
    // it during Guided/free-form drafting. The explicit account lifecycle
    // clearServerSkill() remains the only way to remove its authority.
    if (skillUiState.serverSkill &&
        skillUiState.serverSkill.id === skillUiState.activeSkillId &&
        window.B66BrowserPdf &&
        window.B66BrowserPdf.isCgiSkill(skillUiState.activeSkillId)) {
      return true;
    }
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
    renderTemplateUi();
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
    renderTemplateUi();
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

  function cgiTemplateEligibleSkill() {
    const skill = skillUiState.serverSkill;
    if (!skill || !CgiTemplateV2) return null;
    const name = typeof skill.name === "string" ? skill.name : "";
    const provenanceName = skill.provenance && typeof skill.provenance.sourceName === "string"
      ? skill.provenance.sourceName
      : "";
    return /(?:시지아이|cgi)/i.test(name + " " + provenanceName) ? skill : null;
  }

  function cgiTemplateProfile() {
    const skill = cgiTemplateEligibleSkill();
    if (!skill || !Template || !CgiTemplateV2) return null;
    const internal = skill.internalTemplate && typeof skill.internalTemplate === "object"
      ? skill.internalTemplate
      : {};
    const content = internal.content && typeof internal.content === "object"
      ? internal.content
      : {};
    const cgi = content.cgiV2 && typeof content.cgiV2 === "object" ? content.cgiV2 : {};
    const slots = content.slots && typeof content.slots === "object" ? content.slots : {};
    return CgiTemplateV2.approvedProfile({
      approvedBy: "product-owner",
      approvedAt: "2026-10-06T00:00:00.000Z",
      approvalRef: "github:pr-3567",
      privatePresentation: {
        fax: typeof cgi.fax === "string" ? cgi.fax : "",
        bank: typeof cgi.bank === "string" ? cgi.bank : ""
      },
      slotRefs: {
        logo: typeof slots.logo === "string" ? slots.logo : "",
        stamp: typeof slots.stamp === "string" ? slots.stamp : ""
      }
    });
  }

  function explicitTemplateProfile() {
    if (!TemplateSelection) return null;
    const id = currentTemplateId();
    if (!id) return null;
    if (CgiTemplateV2 && id === CgiTemplateV2.TEMPLATE_ID) {
      return cgiTemplateProfile();
    }
    if (!TemplateStore) return null;
    const candidate = TemplateStore.getTemplate(loadTemplateStore(), id);
    return candidate && candidate.approved ? candidate : null;
  }

  function activeTemplateProfile() {
    if (!Template) return null;
    const explicit = explicitTemplateProfile();
    if (explicit) return explicit;
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
    return explicitTemplateProfile() || activeSkillProfile() || activeTemplateProfile();
  }

  /* 미리보기는 승인된 양식만 대상으로 한다(승인 경계 우회 금지). */
  function previewTemplateProfile() {
    if (!TemplateStore || !templateUiState.previewTemplateId) return null;
    const candidate = TemplateStore.getTemplate(loadTemplateStore(), templateUiState.previewTemplateId);
    return candidate && candidate.approved ? candidate : null;
  }

  function templateManagementEntries() {
    if (!TemplateSelection) return [];
    const entries = TemplateSelection.listForManagement(loadTemplateStore()).slice();
    const cgi = cgiTemplateProfile();
    if (cgi) {
      entries.push({
        id: cgi.id,
        name: cgi.name,
        builtin: false,
        approved: true,
        approvalBasis: cgi.approvalBasis,
        isDefault: false,
        fingerprint: cgi.fingerprint,
        selectable: true,
        canRename: false,
        canDuplicate: false,
        canDelete: false,
        canSetDefault: false,
        canApprove: false
      });
    }
    return entries;
  }

  function templateRows() {
    if (!TemplateUi || !TemplateSelection) return [];
    return TemplateUi.buildRows(templateManagementEntries(), {
      activeTemplateId: (activeTemplateProfile() || {}).id || null,
      previewTemplateId: templateUiState.previewTemplateId,
      renamingTemplateId: templateUiState.renamingTemplateId
    });
  }

  function renderTemplateUi() {
    if (!TemplateUi || !TemplateStore || !TemplateSelection) return;
    const store = loadTemplateStore();
    const templates = templateManagementEntries();
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
      if (CgiTemplateV2 && id === CgiTemplateV2.TEMPLATE_ID) {
        if (!cgiTemplateProfile()) return applyTemplateResult({ ok: false, code: "template_not_approved" });
        if (!privateStateReadable()) {
          setTransientPublicTemplateSelection(id);
          return applyTemplateResult({ ok: true, code: "selected" });
        }
        const storage = templateStorage();
        const envelope = TemplateSelection.setSelection(
          TemplateSelection.readEnvelope(storage),
          draft.meta.quoteNo,
          id
        );
        if (!envelope || !TemplateSelection.writeEnvelope(storage, envelope)) {
          return applyTemplateResult({ ok: false, code: "selection_storage_failed" });
        }
        return applyTemplateResult({ ok: true, code: "selected" }, "이 견적에 CGI 양식을 적용했습니다.");
      }
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
    const serverSkillActive = Boolean(
      !previewProfile &&
      skillUiState.serverSkill &&
      skillUiState.serverSkill.id === skillUiState.activeSkillId
    );
    const ownerCgi = Boolean(serverSkillActive && window.B66BrowserPdf &&
      window.B66BrowserPdf.isCgiSkill(skillUiState.activeSkillId));
    // Certified CGI source authority is the owner-assigned approved skill, not
    // an unrelated previously selected generic/template-management profile.
    const cgiProfile = ownerCgi ? activeSkillProfile() : null;
    const authority = ownerCgi ? cgiProfile : (previewProfile || renderTemplateAuthority());
    const model = TemplateRenderer.buildRenderModel(
      draft,
      authority,
      {
        taxReviewRequired,
        slotSources: serverSkillActive ? skillUiState.serverSlotSources : {},
        certifiedPreviewBaseUrl: serverSkillActive &&
            window.B66QuoteRuntimeBridge &&
            typeof window.B66QuoteRuntimeBridge.certifiedPreviewBaseUrl === "function"
          ? window.B66QuoteRuntimeBridge.certifiedPreviewBaseUrl(skillUiState.activeSkillId)
          : ""
      }
    );
    // An assigned CGI may carry the earlier generic layout variant. The
    // approved saved skill still owns every fact and its fingerprint; only the
    // exact certified CGI presentation is selected for the browser preview.
    const certifiedModel = ownerCgi && model && cgiProfile
      ? window.B66BrowserPdf.certifiedPreviewModel(model, skillUiState.activeSkillId,
          cgiProfile.fingerprint)
      : model;
    if (certifiedModel) TemplateRenderer.applyRenderModel(document, certifiedModel);

    /* 입력 폼의 금액 셀은 견적서 render projection 과 별개로 QuoteCore 파생값을 그대로 쓴다. */
    const totals = Core.computeDraftTotals(draft);
    if (totals) {
      document.querySelectorAll("#items .item-row").forEach((row, i) => {
        const cell = row.querySelector(".amount-value");
        if (cell && totals.amounts[i] !== undefined) cell.textContent = Core.formatMoney(totals.amounts[i]);
      });
    }

    saveDraft();
  }

  /* ── 발신자 프리셋 ── */

  const sampleSender = {
    company: "샘플 공급사",
    rep: "대표자명",
    contactPerson: "",
    bizNo: "000-00-00000",
    address: "",
    phone: "000-0000-0000",
    email: "hello@example.com"
  };

  function loadSavedSender() {
    try {
      const saved = JSON.parse(readPrivateItem(Core.SENDER_STORAGE_KEY) || "null");
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
        company: "", rep: "", contactPerson: "", bizNo: "", address: "", phone: "", email: ""
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
      contactPerson: draft.sender.contactPerson.trim(),
      bizNo: draft.sender.bizNo.trim(),
      address: draft.sender.address.trim(),
      phone: draft.sender.phone.trim(),
      email: draft.sender.email.trim()
    };
    writePrivateItem(Core.SENDER_STORAGE_KEY, JSON.stringify(sender));
    $("senderPreset").value = "custom";
    render();
    toast("이 브라우저에 발신자를 저장했습니다.");
  });

  /* ── 새 견적 (사용자 확인 후 현재 draft 초기화) ── */

  $("newQuote").addEventListener("click", () => {
    if (!window.confirm("현재 입력한 견적 내용을 모두 지우고 새로 시작할까요?")) return;
    const previousQuoteNo = String(draft.meta.quoteNo || "");
    const next = createBlankNextDraft();
    if (!next) {
      toast("새 견적을 시작하지 못했습니다.");
      return;
    }
    clearTransientPublicTemplateSelection();
    if (TemplateSelection) {
      const storage = templateStorage();
      let envelope = TemplateSelection.removeSelection(
        TemplateSelection.readEnvelope(storage),
        previousQuoteNo
      );
      envelope = TemplateSelection.removeSelection(envelope, next.meta.quoteNo);
      TemplateSelection.writeEnvelope(storage, envelope);
    }
    draft = next;
    templateUiState.previewTemplateId = null;
    templateUiState.renamingTemplateId = null;
    taxReviewRequired = false;
    persistTaxReviewRequired(false);
    itemSeq = 1;
    renderItems();
    fillInputsFromDraft();
    renderTaxReviewState();
    renderTemplateUi();
    render();
    toast("보내는 사람 정보는 유지하고 새 고객 견적을 시작합니다.");
  });

  /* ── PDF: 배정된 Saved Skill 의 인증 renderer 를 통해 다운로드한다 ── */

  let pdfDownloadPending = false;
  $("printPdf").addEventListener("click", async () => {
    if (pdfDownloadPending) return;
    const failure = printReadinessFailure();
    if (failure) {
      toast(failure.message, 4200);
      if (failure.code === "tax_review") focusTaxReview();
      else focusReadinessTarget(failure.code);
      return;
    }

    const bridge = window.B66QuoteRuntimeBridge;
    if (!bridge || typeof bridge.downloadPdf !== "function" || !TemplateRenderer ||
        typeof TemplateRenderer.buildCertifiedPdfRenderModel !== "function") {
      toast("PDF 다운로드 연결을 확인해 주세요.", 4200);
      return;
    }
    const model = TemplateRenderer.buildCertifiedPdfRenderModel(draft, activeSkillProfile(), {
      taxReviewRequired: taxReviewRequired
    });
    if (!model) {
      toast("배정된 양식과 PDF로 저장할 수 있는 견적 내용을 확인해 주세요.", 4200);
      return;
    }
    const button = $("printPdf");
    pdfDownloadPending = true;
    button.disabled = true;
    try {
      const certifiedBrowserPdf = window.B66BrowserPdf &&
        window.B66BrowserPdf.isCgiSkill(skillUiState.activeSkillId);
      const profile = activeSkillProfile();
      const previewModel = certifiedBrowserPdf && profile && skillUiState.serverSkill &&
          skillUiState.serverSkill.id === skillUiState.activeSkillId
        ? window.B66BrowserPdf.certifiedPreviewModel(
            TemplateRenderer.buildRenderModel(draft, profile, {
              taxReviewRequired,
              slotSources: skillUiState.serverSlotSources,
              certifiedPreviewBaseUrl: bridge.certifiedPreviewBaseUrl(skillUiState.activeSkillId)
            }),
            skillUiState.activeSkillId, profile.fingerprint)
        : null;
      const result = await bridge.downloadPdf(model, previewModel);
      if (result && result.ok === true) toast("PDF 견적서를 다운로드했습니다.");
      else toast(result && result.message ? result.message : "PDF 다운로드에 실패했습니다. 잠시 후 다시 시도해 주세요.", 4200);
    } catch (_) {
      toast("PDF 다운로드에 실패했습니다. 잠시 후 다시 시도해 주세요.", 4200);
    } finally {
      pdfDownloadPending = false;
      button.disabled = false;
    }
  });

  /* ── Excel 내보내기: 현재 확정된 QuoteDraft 를 그대로 포맷 어댑터에 넘긴다 ──
     계산 authority 는 QuoteCore 하나이며, exporter 는 값을 재계산하지 않는다. */
  $("xlsxDownload").addEventListener("click", () => {
    const exporter = window.B66XlsxExport;
    if (!exporter || typeof exporter.buildWorkbook !== "function") {
      toast("Excel 내보내기를 준비하지 못했습니다.");
      return;
    }
    try {
      const bytes = exporter.buildWorkbook(draft);
      const blob = new Blob([bytes], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = exporter.suggestFileName(draft);
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
      toast("Excel 파일을 내려받습니다.");
    } catch (err) {
      toast("Excel 파일을 만들지 못했습니다. 견적 내용을 확인해 주세요.", 4200);
    }
  });

  $("emailFuture").addEventListener("click", () => {
    toast("이메일 전송은 다음 단계에서 Gmail/메일 연동으로 붙입니다.");
  });

  $("saveHistory").addEventListener("click", async () => {
    const result = await saveCurrentToHistory();
    if (!result.ok && result.error !== "save_in_progress") {
      toast("최근 견적 저장에 실패했습니다.");
    }
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

  /* ── 계정 경계 적용(#3480) ──
   canonical owner 가 확정된 뒤에만 저장된 private 상태를 화면으로 올린다.
   signed-out / owner 미확정 / 이 계정 것이 아닌 격리 상태에서는 진행 중 private
   projection 을 버린다. 격리 시 이미 디스크에서 제거되므로 같은 계정 재로그인은
   새 상태에서 시작한다. */

  const QUARANTINE_ACTIONS = AccountScope
    ? [
        AccountScope.SCOPE_ACTIONS.QUARANTINED_FOREIGN_OWNER,
        AccountScope.SCOPE_ACTIONS.QUARANTINED_MALFORMED_OWNER
      ]
    : [];

  function itemSeqFromDraft(value) {
    return value.items.reduce((max, it) => {
      const n = parseInt(String(it.id).replace(/^(?:item-|extracted-item-)/, ""), 10);
      return Number.isFinite(n) ? Math.max(max, n) : max;
    }, 0);
  }

  function discardPrivateProjection() {
    /* 이 브라우저 저장소 상태는 유지되지만 메모리/화면의 private 사본만 버린다. */
    draft = Core.createProductionDraft();
    lastExtractionReview = null;
    taxReviewRequired = false;
    suppressNextDraftSave = true;
    skillUiState.serverSkill = null;
    skillUiState.serverSlotSources = {};
    skillUiState.activeSkillId = null;
    templateUiState.previewTemplateId = null;
    templateUiState.renamingTemplateId = null;
    clonerSession = null;
    itemSeq = draft.items.length;
  }

  function restorePrivateProjection() {
    const restored = loadDraft();
    if (!restored) return;
    draft = restored;
    taxReviewRequired = loadTaxReviewRequired(draft);
    itemSeq = itemSeqFromDraft(draft);
  }

  function applyAccountScopeDetail(detail) {
    /* server authority 는 계정 projection 이 바뀔 때마다 재확정한다.
       후보 캐시도 비워 이전 계정의 견적번호가 다음 계정에 새지 않는다. */
    serverHistorySignedIn = Boolean(detail && detail.authenticated === true);
    serverQuoteNoCandidates = [];
    const action = detail && detail.action ? detail.action : null;
    const readable = Boolean(detail && detail.privateStateReadable);
    if (detail && detail.authenticated === true) clearTransientPublicTemplateSelection();
    if (!readable || QUARANTINE_ACTIONS.indexOf(action) !== -1) {
      discardPrivateProjection();
    } else if (!History || !History.isMeaningfulDraft(draft)) {
      /* 사용자가 이미 입력 중이면 자동 복원으로 덮어쓰지 않는다. */
      restorePrivateProjection();
    }
    renderItems();
    fillInputsFromDraft();
    renderTaxReviewState();
    renderTemplateUi();
    render();
    if (skillUiApi && typeof skillUiApi.refresh === "function") skillUiApi.refresh();
    window.dispatchEvent(new CustomEvent("b66:history-changed"));
  }

  document.addEventListener("b66:account-scope-changed", (event) => {
    applyAccountScopeDetail(event.detail);
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
    privateStateReadable: () => privateStateReadable(),
    applyOwnerScope: (projection) => {
      const storage = localStorageRef();
      if (!AccountScope) {
        const denied = { authenticated: false, privateStateReadable: false, action: null };
        document.dispatchEvent(new CustomEvent("b66:account-scope-changed", { detail: denied }));
        return denied;
      }
      const result = AccountScope.applyAccountScope(storage, projection, PRIVATE_STORAGE_KEYS);
      document.dispatchEvent(new CustomEvent("b66:account-scope-changed", {
        detail: {
          authenticated: result.authenticated === true,
          privateStateReadable: result.privateStateReadable === true,
          action: result.action || null
        }
      }));
      return result;
    },
    getHistoryEnvelope: () => {
      const envelope = loadHistoryEnvelope();
      return envelope ? cloneDraft(envelope) : null;
    },
    writeHistoryEnvelope: (envelope) => {
      if (!History) return false;
      return writePrivateItem(
        History.HISTORY_STORAGE_KEY,
        JSON.stringify(History.normalizeEnvelope(envelope))
      );
    },
    listRecentQuotes,
    deleteRecentQuote,
    recentListAuthority: () => (serverHistoryRequired() ? "server" : "local"),
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
      storage: ownerGatedStorage(),
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
