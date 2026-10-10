/* B66 · Quote Beta — Easy Mode
   Deterministic guided flow + browser-local resume/history.
   No model/provider/network call is made here. */

(() => {
  "use strict";

  const Core = window.QuoteCore;
  const History = window.QuoteHistory;
  const FileIntake = window.B66FileIntake;
  const App = window.B66QuoteAppBridge;
  const AccountScope = window.QuoteAccountScope || null;

  if (!Core || !History || !FileIntake || !App) return;

  const $ = (id) => document.getElementById(id);
  const easyView = $("easyView");
  const directView = $("directView");
  const easyEmpty = $("easyEmpty");
  const messageList = $("easyMessageList");
  const historyPanel = $("easyHistoryPanel");
  const chipRow = $("easyChipRow");
  const composer = $("easyComposer");
  const sendButton = $("easySend");
  const fileInput = $("easyFileInput");

  let inputHandler = null;
  let guided = null;
  let guidedSnapshot = null;
  let accountSignedIn = false;
  let selectedFile = null;
  let lastEasyView = "home";
  let restoringProductHistory = false;
  let interpretationInFlight = false;
  let accountScopeRevision = 0;
  const PRODUCT_HISTORY_KEY = "b66View";

  const QUARANTINE_ACTIONS = AccountScope
    ? [
        AccountScope.SCOPE_ACTIONS.QUARANTINED_FOREIGN_OWNER,
        AccountScope.SCOPE_ACTIONS.QUARANTINED_MALFORMED_OWNER
      ]
    : [];

  function quarantineAction(action) {
    return QUARANTINE_ACTIONS.indexOf(action) !== -1;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function safeText(value, max) {
    return String(value == null ? "" : value).trim().slice(0, max || 2000);
  }

  function recordProductState(view, options) {
    if (restoringProductHistory || !window.history) return;
    const opts = options || {};
    const currentState = Object.assign({}, window.history.state || {});
    const current = currentState[PRODUCT_HISTORY_KEY];
    if (!opts.replace && current === view) return;

    const write = (method, nextView) => {
      if (typeof window.history[method] !== "function") return;
      const nextState = Object.assign({}, window.history.state || {});
      nextState[PRODUCT_HISTORY_KEY] = nextView;
      window.history[method](nextState, "", window.location.href);
    };

    if (opts.replace) {
      write("replaceState", view);
      return;
    }

    if (view === "home" && current && current !== "home") {
      if (typeof window.history.back === "function") window.history.back();
      return;
    }

    if (view !== "home" && current && current !== "home") {
      write("replaceState", view);
      return;
    }

    write("pushState", view);
  }

  function readHistory() {
    /* 계정 owner 게이트는 app.js(단일 브라우저 저장소 authority)가 통과시킨다 (#3480). */
    const envelope = App.getHistoryEnvelope();
    return envelope || History.normalizeEnvelope(null);
  }

  /* 최근 견적 읽기는 authority-aware 다(#3405 Slice B). signed-in 동안에는
     app.js 가 서버 목록을 돌려주고, 서버 실패는 local envelope 로 대체되지
     않는다. bridge 가 아직 없으면 기존 local 경로를 유지한다. */
  function readRecentHistory() {
    if (App && typeof App.listRecentQuotes === "function") {
      return App.listRecentQuotes().catch(() => (
        { ok: false, authority: "server", error: "history_read_failed" }
      ));
    }
    return Promise.resolve({ ok: true, authority: "local", envelope: readHistory() });
  }

  function serverAuthorityRecent() {
    return Boolean(App && typeof App.recentListAuthority === "function" &&
      App.recentListAuthority() === "server");
  }

  function writeHistory(envelope) {
    if (App.writeHistoryEnvelope(envelope)) {
      window.dispatchEvent(new CustomEvent("b66:history-changed"));
      return true;
    }
    App.toast("로그인한 계정의 최근 견적에만 저장할 수 있습니다.");
    return false;
  }

  function setWorkspaceMode(mode, options) {
    const easy = mode === "easy";
    easyView.hidden = !easy;
    directView.hidden = easy;
    $("easyModeButton").classList.toggle("active", easy);
    $("directModeButton").classList.toggle("active", !easy);
    $("easyModeButton").setAttribute("aria-pressed", String(easy));
    $("directModeButton").setAttribute("aria-pressed", String(!easy));
    if (!easy) window.scrollTo({ top: 0, behavior: "smooth" });
    if (!options || options.history !== false) {
      recordProductState(easy ? lastEasyView : "direct");
    }
  }

  function clearConversation() {
    messageList.innerHTML = "";
    historyPanel.innerHTML = "";
    historyPanel.hidden = true;
    chipRow.innerHTML = "";
    inputHandler = null;
  }

  function showHome(options) {
    clearConversation();
    snapshotGuidedConversation();
    /* Home 에서 명시적으로 새 견적을 시작하면 진행 중이던 문맥을 버린다. */
    if (!options || options.history !== false) {
      const bridge = window.B66QuoteRuntimeBridge;
      if (bridge && typeof bridge.clearPending === "function") bridge.clearPending();
    }
    selectedFile = null;
    lastEasyView = "home";
    if (!options || options.history !== false) recordProductState("home");
    easyEmpty.hidden = false;
    composer.value = "";
    composer.placeholder = "견적 내용을 한 문장으로 편하게 적어 보세요";
    $("easyComposerNote").textContent =
      "보내면 CGI 기본 견적서로 바로 만들어 드립니다. 단계별로 답하려면 '질문받으며 만들기'를 선택하세요.";
    inputHandler = (text) => startHomeInterpretation(text);
    composer.disabled = false;
    sendButton.disabled = false;
    refreshStarters();
  }

  function startConversation() {
    easyEmpty.hidden = true;
    messageList.innerHTML = "";
    historyPanel.innerHTML = "";
    historyPanel.hidden = true;
    chipRow.innerHTML = "";
    composer.value = "";
  }

  function addMessage(role, text) {
    const article = document.createElement("article");
    article.className = "easy-message " + (role === "user" ? "easy-user-message" : "easy-assistant-message");

    if (role === "assistant") {
      const avatar = document.createElement("div");
      avatar.className = "easy-message-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = "견";

      const body = document.createElement("div");
      body.className = "easy-message-body";
      const meta = document.createElement("div");
      meta.className = "easy-message-meta";
      meta.textContent = "견적 도우미";
      const content = document.createElement("div");
      content.className = "easy-message-content";
      content.textContent = text;
      body.append(meta, content);
      article.append(avatar, body);
    } else {
      const bubble = document.createElement("div");
      bubble.className = "easy-message-bubble";
      bubble.textContent = text;
      article.appendChild(bubble);
    }

    messageList.appendChild(article);
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return article;
  }

  function setChips(chips) {
    chipRow.innerHTML = "";
    (chips || []).forEach((chip) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "easy-chip";
      button.textContent = chip.label;
      button.addEventListener("click", () => chip.action());
      chipRow.appendChild(button);
    });
  }

  function setInput(handler, placeholder) {
    inputHandler = handler;
    composer.disabled = false;
    sendButton.disabled = false;
    composer.placeholder = placeholder || "답변을 입력하세요";
    setTimeout(() => composer.focus(), 0);
  }

  function disableInput(note) {
    inputHandler = null;
    composer.disabled = true;
    sendButton.disabled = true;
    if (note) $("easyComposerNote").textContent = note;
  }

  function submitComposer() {
    const text = safeText(composer.value);
    if (!text || !inputHandler) return;
    composer.value = "";
    inputHandler(text);
  }

  function refreshStarters() {
    const activeDraft = App.getDraft();
    $("resumeDraftStarter").hidden = !History.isMeaningfulDraft(activeDraft);
    /* server authority 동안에는 local cache 가 비어 있어도 최근 견적에
       접근할 수 있어야 한다(서버 목록이 authority). */
    $("recentQuoteStarter").hidden = serverAuthorityRecent()
      ? false
      : readHistory().entries.length === 0;

    let hint = document.getElementById("easyResumeHint");
    if (accountSignedIn) {
      if (History.isMeaningfulDraft(activeDraft)) {
        if (!hint) {
          hint = document.createElement("div");
          hint.id = "easyResumeHint";
          hint.className = "easy-resume-hint";
          $("easyStarterGrid").before(hint);
        }
        hint.textContent = "이전에 작성하던 견적이 있습니다. 이어서 진행할 수 있어요.";
      } else if (hint) {
        hint.remove();
      }
    } else {
      if (!hint) {
        hint = document.createElement("div");
        hint.id = "easyResumeHint";
        hint.className = "easy-resume-hint";
        $("easyStarterGrid").before(hint);
      }
      hint.textContent = "로그인하면 견적을 이어서 진행할 수 있습니다.";
    }
  }

  /* ── CGI primary runtime (#3478) ──
     Home 한 문장과 Free-form, Guided 최종 작성은 모두 하나의 runtime authority
     (인증된 assigned Saved Quote Skill + CompanyProfile)를 거친다.
     준비되지 않으면 demo/blank authority 로 진행하지 않고 정직하게 안내한다. */

  function runtimeNotReadyMessage(readiness) {
    if (!readiness || !readiness.authenticated) {
      return "로그인 후 CGI 기본 견적서가 준비되면 바로 만들 수 있습니다. 먼저 로그인해 주세요.";
    }
    if (!readiness.skillReady) {
      return "배정된 CGI 기본 견적서가 아직 준비되지 않았습니다. 로그인 상태를 확인해 주세요.";
    }
    return "회사 정보(CompanyProfile)를 아직 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
  }

  function startHomeInterpretation(text) {
    runPrimaryInterpretation(text);
  }

  function submitFreeFormText(raw) {
    runPrimaryInterpretation(raw);
  }

  function runPrimaryInterpretation(rawText) {
    // A second click/Enter must not launch a second B14 interpretation attempt.
    if (interpretationInFlight) return;
    const text = safeText(rawText, 4000);
    if (!text) return;
    const bridge = window.B66QuoteRuntimeBridge;
    const readiness = bridge && typeof bridge.readiness === "function" ? bridge.readiness() : null;
    if (!readiness || !readiness.ready) {
      addMessage("assistant", runtimeNotReadyMessage(readiness));
      return;
    }
    const requestScopeRevision = accountScopeRevision;
    interpretationInFlight = true;
    addMessage("user", text);
    const processingMessage = addMessage("assistant", "CGI 기본 견적서로 작성하고 있습니다…");
    disableInput("견적을 만드는 동안에는 입력을 잠시 멈춥니다.");
    Promise.resolve().then(() => {
      // Closing/switching the owner before the dispatch microtask must cancel the call.
      if (requestScopeRevision !== accountScopeRevision) return null;
      return bridge.interpret(text);
    }).then((result) => {
      // Results from a signed-out/quarantined owner must never update the next account.
      if (requestScopeRevision !== accountScopeRevision) return;
      if (!result || result.ok !== true || !result.draft) {
        /* 정보가 부족하면 무엇이 없는지 한 가지만 되묻고 같은 견적을 이어간다.
           Guided 로 강제 전환하지 않는다 (#3391). */
        if (result && (result.code === "incomplete_request" || result.code === "needs_clarification")) {
          addMessage("assistant", typeof result.question === "string" && result.question.trim()
            ? result.question
            : "견적에 필요한 값을 조금 더 알려 주세요.");
          setInput(submitFreeFormText, result.code === "needs_clarification"
            ? "견적 내용을 다시 적어 주세요"
            : "답변을 적어 주세요");
          return;
        }
        const detail = result && bridge && typeof bridge.errorText === "function"
          ? bridge.errorText(result.code)
          : "견적 요청을 해석하지 못했습니다.";
        addMessage("assistant", detail);
        setChips([
          { label: "질문받으며 만들기", action: startGuidedIfReady },
          { label: "처음으로", action: showHome }
        ]);
        // A model outage during a missing-field follow-up does not erase the
        // pending quote. Don't tell the customer to retype their whole request.
        const pending = bridge && typeof bridge.pendingQuote === "function"
          ? bridge.pendingQuote() : null;
        setInput(submitFreeFormText, pending
          ? "방금 답변을 다시 적어 주세요"
          : "다시 한 문장으로 적어 주세요");
        return;
      }
      const replace = App.replaceDraft(result.draft, {});
      if (!replace || replace.ok !== true) {
        addMessage("assistant", "생성된 견적을 화면에 반영하지 못했습니다. 다시 시도해 주세요.");
        setInput(submitFreeFormText, "다시 한 문장으로 적어 주세요");
        return;
      }
      addResultReview(result.draft, false);
    }).catch(() => {
      if (requestScopeRevision !== accountScopeRevision) return;
      addMessage("assistant", "해석 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.");
      setInput(submitFreeFormText, "다시 한 문장으로 적어 주세요");
    }).finally(() => {
      // Keep only the completed result, the missing-field question, or the
      // failure notice. A stale "작성하고 있습니다" misleads customers.
      processingMessage.remove();
      if (requestScopeRevision === accountScopeRevision) interpretationInFlight = false;
    });
  }

  function addResultReview(draft, taxUnknown) {
    const totals = Core.computeDraftTotals(draft);
    const effectiveItems = totals && Array.isArray(totals.effectiveItems)
      ? totals.effectiveItems
      : draft.items;
    const itemLines = draft.items.map((item, index) =>
      "- " + item.name + " " + Core.formatInputNumber(item.qty) + " × " +
      Core.formatMoney(effectiveItems[index].unitPrice)
    ).join("\n");
    const taxLine = taxUnknown
      ? "부가세: 확인 필요 (견적서 확인 화면에서 선택해 주세요)"
      : "합계: " + Core.formatMoney(totals.grand) + " (" + Core.TAX_LABELS[draft.tax.mode] + ")";
    addMessage(
      "assistant",
      "견적이 준비되었습니다.\n\n받는 곳: " +
      (draft.recipient.company || "미입력") +
      (draft.recipient.person ? " · " + draft.recipient.person : "") +
      "\n\n" + itemLines +
      "\n\n" + taxLine +
      "\n\n아래에서 견적서를 열어 PDF로 저장하거나 인쇄할 수 있습니다."
    );
    setChips([
      {
        label: "견적서 확인하기",
        action: () => {
          setWorkspaceMode("direct");
          if (taxUnknown) setTimeout(() => App.focusTaxReview(), 0);
        }
      },
      { label: "처음으로", action: showHome }
    ]);
    disableInput("새 견적은 처음으로 돌아가서 시작할 수 있습니다.");
  }

  function startGuidedIfReady() {
    const bridge = window.B66QuoteRuntimeBridge;
    const readiness = bridge && typeof bridge.readiness === "function" ? bridge.readiness() : null;
    if (!readiness || !readiness.ready) {
      startConversation();
      addMessage("assistant", runtimeNotReadyMessage(readiness));
      setChips([{ label: "처음으로", action: showHome }]);
      disableInput("로그인과 CGI 기본 견적서 준비가 끝나면 시작할 수 있습니다.");
      return;
    }
    startGuided();
  }

  function finishGuidedWithRuntime() {
    if (!guided) return;
    const bridge = window.B66QuoteRuntimeBridge;
    const readiness = bridge && typeof bridge.readiness === "function" ? bridge.readiness() : null;
    if (!readiness || !readiness.ready) {
      addMessage("assistant", runtimeNotReadyMessage(readiness));
      return;
    }
    const taxUnknown = guided.taxUnknown;
    const processingMessage = addMessage("assistant", "CGI 기본 견적서로 작성하고 있습니다…");
    const facts = {
      recipient: guided.draft.recipient,
      items: guided.draft.items.map((item) => ({
        name: item.name, qty: item.qty, unitPrice: item.unitPrice
      })),
      taxMode: guided.draft.tax.mode,
      memo: guided.draft.memo,
      quoteNo: guided.draft.meta.quoteNo,
      issueDate: guided.draft.meta.issueDate
    };
    Promise.resolve(bridge.buildFromFacts(facts)).then((result) => {
      if (!result || result.ok !== true || !result.draft) {
        const detail = result && bridge && typeof bridge.errorText === "function"
          ? bridge.errorText(result.code)
          : "견적을 만들지 못했습니다.";
        addMessage("assistant", detail + " 내용을 확인하고 다시 시도해 주세요.");
        return;
      }
      const replace = App.replaceDraft(result.draft, {
        requireTaxReview: taxUnknown,
        toast: taxUnknown
          ? "견적을 만들었습니다. 부가세 방식을 확인해 주세요."
          : "견적을 만들었습니다."
      });
      if (!replace || replace.ok !== true) {
        addMessage("assistant", "생성된 견적을 화면에 반영하지 못했습니다. 다시 시도해 주세요.");
        return;
      }
      addResultReview(result.draft, taxUnknown);
    }).catch(() => {
      addMessage("assistant", "견적 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    }).finally(() => {
      processingMessage.remove();
    });
  }

  function showRecentHistory(options) {
    lastEasyView = "recent";
    if (!options || options.history !== false) recordProductState("recent");
    startConversation();
    addMessage("assistant", "최근 견적을 불러오는 중...");
    renderHistoryPending();
    setChips([
      { label: "질문받으며 새로 만들기", action: startGuided },
      { label: "처음으로", action: showHome }
    ]);
    setInput(() => {}, "최근 견적은 아래 버튼으로 선택하세요");
    composer.disabled = true;
    sendButton.disabled = true;
    readRecentHistory().then((result) => {
      if (lastEasyView !== "recent") return;
      addMessage("assistant", recentHistoryIntroText(result));
      renderHistory(result);
    });
  }

  function recentHistoryIntroText(result) {
    if (!result || result.ok !== true) {
      return "최근 견적을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
    }
    return result.authority === "server"
      ? "계정에 저장된 최근 견적입니다. 불러오거나 복사해서 새 견적으로 사용할 수 있어요."
      : "이 브라우저에 저장한 최근 견적입니다. 불러오거나 복사해서 새 견적으로 사용할 수 있어요.";
  }

  function renderHistoryPending() {
    historyPanel.innerHTML = "";
    historyPanel.hidden = false;
    const pending = document.createElement("p");
    pending.className = "easy-history-empty";
    pending.textContent = "최근 견적을 불러오는 중...";
    historyPanel.appendChild(pending);
  }

  /* 최근 견적 실패 화면: 서버 실패를 local 기록으로 대체하지 않고 bounded
     error 상태만 보여준다(NO_SILENT_LOCAL_FALLBACK). */
  function renderHistoryError() {
    historyPanel.innerHTML = "";
    historyPanel.hidden = false;
    const error = document.createElement("p");
    error.className = "easy-history-empty";
    error.textContent = "최근 견적을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "다시 시도";
    retry.addEventListener("click", () => {
      if (lastEasyView !== "recent") return;
      renderHistoryPending();
      readRecentHistory().then((result) => {
        if (lastEasyView !== "recent") return;
        renderHistory(result);
      });
    });
    historyPanel.append(error, retry);
  }

  function renderHistory(result) {
    const outcome = result || { ok: true, authority: "local", envelope: readHistory() };
    historyPanel.innerHTML = "";
    historyPanel.hidden = false;

    if (outcome.ok !== true) {
      renderHistoryError();
      return;
    }

    const envelope = outcome.envelope || History.normalizeEnvelope(null);
    const metadata = History.listMetadata(envelope);

    if (metadata.length === 0) {
      const empty = document.createElement("p");
      empty.className = "easy-history-empty";
      empty.textContent = "아직 저장한 견적이 없습니다.";
      historyPanel.appendChild(empty);
      return;
    }

    metadata.forEach((meta) => {
      const entry = History.getEntry(envelope, meta.id);
      if (!entry) return;

      const card = document.createElement("article");
      card.className = "easy-history-card";

      const info = document.createElement("div");
      info.className = "easy-history-info";
      const title = document.createElement("strong");
      title.textContent = meta.recipientCompany || "받는 사람 미정";
      const sub = document.createElement("span");
      const person = meta.recipientPerson ? " · " + meta.recipientPerson : "";
      sub.textContent = (meta.issueDate || "날짜 미정") + person + " · " + meta.itemCount + "개 품목";
      const amount = document.createElement("span");
      amount.className = "easy-history-amount";
      amount.textContent = Core.formatMoney(meta.grand) + " · " + (meta.quoteNo || "견적번호 없음");
      info.append(title, sub, amount);

      const actions = document.createElement("div");
      actions.className = "easy-history-actions";

      const load = document.createElement("button");
      load.type = "button";
      load.textContent = "불러오기";
      load.addEventListener("click", () => {
        const current = App.getDraft();
        if (History.isMeaningfulDraft(current) &&
            !window.confirm("현재 작성 중인 견적을 바꾸고 이 견적을 불러올까요?")) return;
        const result = App.replaceDraft(entry.draft, { toast: "최근 견적을 불러왔습니다." });
        if (result.ok) setWorkspaceMode("direct");
      });

      const copy = document.createElement("button");
      copy.type = "button";
      copy.textContent = "복사해서 새 견적";
      copy.addEventListener("click", () => {
        const current = App.getDraft();
        if (History.isMeaningfulDraft(current) &&
            !window.confirm("현재 작성 중인 견적을 바꾸고 복사본으로 새 견적을 시작할까요?")) return;
        const next = App.copyHistoryAsNew(entry);
        if (!next) return;
        const result = App.replaceDraft(next, { toast: "최근 견적을 복사해 새 견적으로 열었습니다." });
        if (result.ok) setWorkspaceMode("direct");
      });

      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "danger";
      remove.textContent = "삭제";
      remove.addEventListener("click", () => {
        if (outcome.authority === "server") {
          deleteServerHistoryEntry(meta.id);
          return;
        }
        if (!window.confirm("이 최근 견적을 이 브라우저에서 삭제할까요?")) return;
        if (writeHistory(History.deleteEntry(readHistory(), meta.id))) {
          renderHistory();
          refreshStarters();
        }
      });

      actions.append(load, copy, remove);
      card.append(info, actions);
      historyPanel.appendChild(card);
    });
  }

  /* server row 삭제: 명시적 확인 후 서버 성공에만 목록을 다시 읽어
     반영한다. 실패 시 행은 그대로 유지된다(NO_OPTIMISTIC_DELETE). */
  function deleteServerHistoryEntry(entryId) {
    if (!window.confirm("이 최근 견적을 계정에서 삭제할까요?")) return;
    const deletion = App && typeof App.deleteRecentQuote === "function"
      ? App.deleteRecentQuote(entryId)
      : Promise.resolve({ ok: false, authority: "server", error: "history_unavailable" });
    deletion.then((result) => {
      if (!result || result.ok !== true) {
        App.toast("최근 견적 삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        return;
      }
      refreshRecentHistory();
      refreshStarters();
    }).catch(() => {
      App.toast("최근 견적 삭제에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    });
  }

  function refreshRecentHistory() {
    if (lastEasyView !== "recent") return;
    renderHistoryPending();
    readRecentHistory().then((result) => {
      if (lastEasyView !== "recent") return;
      renderHistory(result);
    });
  }

  function parseNumberAnswer(text, allowZero) {
    const compact = safeText(text)
      .replace(/원$/u, "")
      .replace(/개$/u, "")
      .replace(/[,\s]/g, "");
    if (!/^\d+(\.\d+)?$/.test(compact)) return null;
    const value = Number(compact);
    if (!Number.isFinite(value)) return null;
    if (allowZero ? value < 0 : value <= 0) return null;
    return value;
  }

  function guidedDraft() {
    const current = App.getDraft();
    const fresh = App.createFreshDraft("guided");
    fresh.sender = clone(current.sender);
    if (current.calculationPolicy) fresh.calculationPolicy = clone(current.calculationPolicy);
    fresh.recipient = { company: "", person: "", address: "", email: "" };
    fresh.items = [];
    fresh.memo = "";
    return fresh;
  }

  /* 진행 중인 guided 대화는 화면 전환으로 버려지지 않고 스냅샷 한 슬롯으로만 보존한다(bounded).
     브라우저 Back/Forward 복원은 App draft 대신 이 guided 상태를 이어 쓴다. */
  function snapshotGuidedConversation() {
    if (!guided) {
      guidedSnapshot = null;
      return;
    }
    guidedSnapshot = {
      step: guided.step,
      draft: clone(guided.draft),
      currentItem: guided.currentItem,
      taxUnknown: guided.taxUnknown
    };
    guided = null;
  }

  /* guided 히스토리 항목에 세션 상태(대화/스냅샷)가 없으면 복원할 대상이 없다(재시작 등).
     App draft 는 이전/다른 견적일 수 있으므로 guided 로 가져오지 않고, 새 초안·견적번호도
     발급하지 않는다 — Home 으로 귀결시키고 새 견적은 명시적 시작에서만 발급한다. */
  function restoreGuidedWithoutState() {
    App.toast("진행 중이던 견적 상태를 복원할 수 없습니다. 새 견적 만들기를 다시 시작해 주세요.");
    showHome({ history: false });
    guidedSnapshot = null;
  }

  function resumeGuidedConversation(state) {
    startConversation();
    guided = {
      step: state.step,
      draft: clone(state.draft),
      currentItem: state.currentItem,
      taxUnknown: state.taxUnknown
    };
    guidedSnapshot = null;
    lastEasyView = "guided";
    addMessage("assistant", "이전에 진행 중이던 견적 만들기를 이어서 진행합니다.");
    rebindGuidedStep();
  }

  /* 스냅샷 복원은 대기 중인 질문만 다시 묶는다. 이미 답한 값은 guided.draft 에 그대로 있다. */
  function rebindGuidedStep() {
    switch (guided.step) {
      case "recipientCompany":
        addMessage("assistant", "누구에게 보내는 견적인가요? 업체명이나 받는 분 이름을 입력해 주세요.");
        setChips([{ label: "직접 입력으로 전환", action: () => setWorkspaceMode("direct") }]);
        setInput(processGuidedInput, "예: 홍길동건설");
        break;
      case "recipientPerson": askRecipientPerson(); break;
      case "itemName": askItemName(); break;
      case "qty": askQty(); break;
      case "price": askPrice(); break;
      case "moreItems": askMoreItems(); break;
      case "tax": askTax(); break;
      case "memo": askMemo(); break;
      case "senderChoice": askSender(); break;
      case "senderCompany":
        addMessage("assistant", "보내는 사람의 상호를 입력해 주세요. 나머지 정보는 확인 화면에서 채울 수 있어요.");
        setChips([]);
        setInput(processGuidedInput, "예: 테스트상사");
        break;
      case "summary": showGuidedSummary(); break;
      default: restoreGuidedWithoutState();
    }
  }

  function startGuided(referenceText, options) {
    const reference = typeof referenceText === "string"
      ? safeText(referenceText, 8000)
      : "";
    lastEasyView = "guided";
    if (!options || options.history !== false) recordProductState("guided");
    startConversation();
    /* 새 대화 시작은 보존된 스냅샷을 대체한다 — 복원 경로는 startGuided 를 거치지 않는다. */
    guidedSnapshot = null;
    /* Guided 로 명시적으로 새 견적을 시작하면 free-form 진행 문맥도 버린다. */
    if (!options || options.history !== false) {
      const bridge = window.B66QuoteRuntimeBridge;
      if (bridge && typeof bridge.clearPending === "function") bridge.clearPending();
    }
    guided = {
      step: "recipientCompany",
      draft: guidedDraft(),
      currentItem: -1,
      taxUnknown: false
    };
    if (reference) {
      addMessage("user", reference);
      addMessage(
        "assistant",
        "적어주신 내용은 참고용으로 그대로 남겨둘게요. 아직 자동 해석은 하지 않으므로 필요한 값은 하나씩 확인합니다. 먼저 누구에게 보내는 견적인가요?"
      );
    } else {
      addMessage("assistant", "새 견적을 같이 만들어볼게요. 누구에게 보내는 견적인가요? 업체명이나 받는 분 이름을 입력해 주세요.");
    }
    setChips([{ label: "직접 입력으로 전환", action: () => setWorkspaceMode("direct") }]);
    setInput(processGuidedInput, "예: 홍길동건설");
    $("easyComposerNote").textContent = reference
      ? "작성한 원문은 참고용으로만 표시하며 QuoteDraft에 자동 반영하지 않습니다."
      : "필요한 내용만 하나씩 묻습니다. 이 흐름은 AI 없이 동작합니다.";
  }

  function askRecipientPerson() {
    guided.step = "recipientPerson";
    addMessage("assistant", "담당자 이름이 있나요?");
    setChips([
      { label: "담당자 없음", action: () => processGuidedInput("없음") }
    ]);
    setInput(processGuidedInput, "예: 김대리");
  }

  function askItemName() {
    guided.step = "itemName";
    addMessage("assistant", "무엇을 견적할까요? 첫 번째 품목명을 적어 주세요.");
    setChips([]);
    setInput(processGuidedInput, "예: 홈페이지 제작");
  }

  function askQty() {
    guided.step = "qty";
    addMessage("assistant", "수량은 몇 개인가요?");
    setChips([1, 2, 3, 10].map((n) => ({
      label: String(n),
      action: () => processGuidedInput(String(n))
    })));
    setInput(processGuidedInput, "예: 1");
  }

  function askPrice() {
    guided.step = "price";
    addMessage("assistant", "개당 단가는 얼마인가요? 1,500,000 또는 150만원처럼 입력할 수 있어요.");
    setChips([]);
    setInput(processGuidedInput, "예: 1,500,000 또는 150만원");
  }

  function guidedItemLimit() {
    const bridge = window.B66QuoteRuntimeBridge;
    return bridge && typeof bridge.supportedItemRows === "function" ? bridge.supportedItemRows() : null;
  }

  function askMoreItems() {
    guided.step = "moreItems";
    const limit = guidedItemLimit();
    if (Number.isInteger(limit) && limit > 0 && guided.draft.items.length >= limit) {
      addMessage("assistant", "CGI 기본 견적서는 품목을 최대 " + limit + "개까지 지원합니다. 다음으로 진행해 주세요.");
      setChips([{ label: "다음으로", action: () => processGuidedInput("다음") }]);
      setInput(processGuidedInput, "다음");
      return;
    }
    addMessage("assistant", "다른 품목도 추가할까요?");
    setChips([
      { label: "품목 추가", action: () => processGuidedInput("추가") },
      { label: "다음으로", action: () => processGuidedInput("다음") }
    ]);
    setInput(processGuidedInput, "'추가' 또는 '다음'이라고 입력해도 됩니다");
  }

  function askTax() {
    guided.step = "tax";
    addMessage("assistant", "부가세는 어떻게 할까요?");
    setChips([
      { label: "별도", action: () => processGuidedInput("별도") },
      { label: "포함", action: () => processGuidedInput("포함") },
      { label: "면세", action: () => processGuidedInput("면세") },
      { label: "잘 모르겠어요", action: () => processGuidedInput("잘 모르겠어요") }
    ]);
    setInput(processGuidedInput, "별도 / 포함 / 면세 / 잘 모르겠어요");
  }

  function askMemo() {
    guided.step = "memo";
    addMessage("assistant", "납기나 결제 조건처럼 덧붙일 내용이 있나요?");
    setChips([{ label: "없음", action: () => processGuidedInput("없음") }]);
    setInput(processGuidedInput, "예: 다음 달 10일까지 납품");
  }

  /* #4076 CGI MVP: the approved server CompanyProfile, not a typed guided
     sender override, owns the sender identity on the final quotation. */
  function approvedRuntimeSender() {
    const bridge = window.B66QuoteRuntimeBridge;
    const ready = bridge && typeof bridge.readiness === "function" ? bridge.readiness() : null;
    const profile = ready && ready.ready && typeof bridge.getCompanyProfile === "function"
      ? bridge.getCompanyProfile() : null;
    return safeText(profile && profile.company);
  }

  function askSender() {
    guided.step = "senderChoice";
    const approved = approvedRuntimeSender();
    if (approved) {
      guided.draft.sender.company = approved;
      addMessage("assistant", "보내는 사람은 내 회사 정보에 등록된 '" + approved + "'로 적용됩니다. 변경하려면 설정의 '내 회사'에서 수정해 주세요.");
      setChips([{ label: "다음으로", action: () => processGuidedInput("현재") }]);
      setInput(processGuidedInput, "다음으로");
      return;
    }
    const company = safeText(guided.draft.sender.company) || "미입력";
    addMessage("assistant", "보내는 사람은 현재 '" + company + "'로 되어 있어요. 이 정보를 사용할까요?");
    setChips([
      { label: "현재 정보 사용", action: () => processGuidedInput("현재") },
      { label: "상호 입력", action: () => processGuidedInput("상호 입력") },
      { label: "직접 입력에서 확인", action: () => processGuidedInput("직접 확인") }
    ]);
    setInput(processGuidedInput, "현재 / 상호 입력 / 직접 확인");
  }

  function showGuidedSummary() {
    guided.step = "summary";
    const totals = Core.computeDraftTotals(guided.draft);
    const effectiveItems = totals && Array.isArray(totals.effectiveItems)
      ? totals.effectiveItems
      : guided.draft.items;
    const itemLines = guided.draft.items.map((item, index) =>
      (index + 1) + ". " + item.name + " · " +
      Core.formatInputNumber(item.qty) + " × " + Core.formatMoney(effectiveItems[index].unitPrice)
    ).join("\n");
    const taxLine = guided.taxUnknown
      ? "부가세: 확인 필요 (직접 입력 화면에서 선택해 주세요)"
      : "부가세: " + Core.TAX_LABELS[guided.draft.tax.mode];
    const amountLine = guided.taxUnknown
      ? "품목 합계(세금 확인 전): " + Core.formatMoney(totals.subtotal) +
        "\n최종 합계는 부가세 방식을 선택한 뒤 확정됩니다."
      : "합계: " + Core.formatMoney(totals.grand);

    addMessage(
      "assistant",
      "이렇게 준비했어요.\n\n보내는 곳: " +
      (guided.draft.sender.company || "미입력") +
      "\n받는 곳: " + (guided.draft.recipient.company || "미입력") +
      (guided.draft.recipient.person ? " · " + guided.draft.recipient.person : "") +
      "\n\n" + itemLines +
      "\n\n" + taxLine +
      "\n" + amountLine +
      "\n\n확인 화면에서 모든 내용을 다시 수정할 수 있습니다."
    );

    setChips([
      { label: "견적서 만들기", action: finishGuidedWithRuntime },
      { label: "처음부터 다시", action: startGuided },
      { label: "최근 견적 보기", action: showRecentHistory }
    ]);
    disableInput("견적서 만들기를 누르면 CGI 기본 견적서로 최종 작성됩니다.");
  }

  function processGuidedInput(raw) {
    if (!guided) return;
    const text = safeText(raw);
    if (!text) return;
    addMessage("user", text);

    switch (guided.step) {
      case "recipientCompany":
        guided.draft.recipient.company = text;
        askRecipientPerson();
        break;

      case "recipientPerson":
        guided.draft.recipient.person = /^(없음|없어요|없습니다)$/u.test(text) ? "" : text;
        askItemName();
        break;

      case "itemName":
        guided.draft.items.push({ id: "item-" + (guided.draft.items.length + 1), name: text });
        guided.currentItem = guided.draft.items.length - 1;
        askQty();
        break;

      case "qty": {
        const qty = parseNumberAnswer(text, false);
        if (qty === null) {
          addMessage("assistant", "수량은 0보다 큰 숫자로 입력해 주세요. 예: 1 또는 2");
          askQty();
          return;
        }
        guided.draft.items[guided.currentItem].qty = qty;
        askPrice();
        break;
      }

      case "price": {
        const price = Core.parseKoreanMoney(text);
        if (price === null) {
          addMessage("assistant", "단가는 1,500,000 또는 150만원처럼 입력해 주세요. 복합 단위는 추측하지 않습니다.");
          askPrice();
          return;
        }
        guided.draft.items[guided.currentItem].unitPrice = price;
        askMoreItems();
        break;
      }

      case "moreItems":
        if (/추가|더|예|네/u.test(text)) {
          const limit = guidedItemLimit();
          if (Number.isInteger(limit) && limit > 0 && guided.draft.items.length >= limit) { askMoreItems(); return; }
          addMessage("assistant", "좋아요. 추가할 품목명을 적어 주세요.");
          guided.step = "itemName";
          setChips([]);
          setInput(processGuidedInput, "추가 품목명");
        } else if (/다음|없|아니|완료/u.test(text)) {
          askTax();
        } else {
          addMessage("assistant", "'품목 추가' 또는 '다음으로'를 선택해 주세요.");
          askMoreItems();
        }
        break;

      case "tax":
        if (/면세/u.test(text)) {
          guided.draft.tax.mode = Core.TAX_MODES.EXEMPT;
          guided.taxUnknown = false;
        } else if (/포함/u.test(text)) {
          guided.draft.tax.mode = Core.TAX_MODES.INCLUSIVE;
          guided.taxUnknown = false;
        } else if (/별도/u.test(text)) {
          guided.draft.tax.mode = Core.TAX_MODES.EXCLUSIVE;
          guided.taxUnknown = false;
        } else if (/모르|확인/u.test(text)) {
          guided.draft.tax.mode = Core.TAX_MODES.EXCLUSIVE;
          guided.taxUnknown = true;
        } else {
          addMessage("assistant", "별도, 포함, 면세 중 하나를 고르거나 '잘 모르겠어요'를 선택해 주세요.");
          askTax();
          return;
        }
        askMemo();
        break;

      case "memo":
        guided.draft.memo = /^(없음|없어요|없습니다)$/u.test(text) ? "" : text;
        askSender();
        break;

      case "senderChoice": {
        const approved = approvedRuntimeSender();
        if (approved) {
          // Never display a user-entered sender that will be ignored by the
          // approved CGI Saved Skill when the real PDF is produced.
          guided.draft.sender.company = approved;
          if (/상호|수정|변경/u.test(text)) {
            addMessage("assistant", "회사명은 설정의 '내 회사'에서 변경해 주세요. 이번 견적은 승인된 회사 정보로 작성됩니다.");
          }
          showGuidedSummary();
          break;
        }
        if (/상호/u.test(text)) {
          guided.step = "senderCompany";
          addMessage("assistant", "보내는 사람의 상호를 입력해 주세요. 나머지 정보는 확인 화면에서 채울 수 있어요.");
          setChips([]);
          setInput(processGuidedInput, "예: 테스트상사");
        } else if (/현재/u.test(text)) {
          showGuidedSummary();
        } else if (/직접|확인/u.test(text)) {
          showGuidedSummary();
        } else {
          addMessage("assistant", "'현재 정보 사용', '상호 입력', '직접 입력에서 확인' 중 하나를 선택해 주세요.");
          askSender();
        }
        break;
      }

      case "senderCompany":
        guided.draft.sender.company = text;
        guided.draft.sender.presetId = "custom";
        showGuidedSummary();
        break;

      default:
        break;
    }
  }

  function startFreeChat(options) {
    lastEasyView = "free-form";
    if (!options || options.history !== false) recordProductState("free-form");
    startConversation();
    snapshotGuidedConversation();
    addMessage(
      "assistant",
      "견적 내용을 한 문장으로 적어 주세요. CGI 기본 견적서 양식과 회사 정보가 자동으로 적용됩니다."
    );
    setChips([
      { label: "질문받으며 만들기", action: startGuidedIfReady },
      { label: "처음으로", action: showHome }
    ]);
    setInput(submitFreeFormText, "예: 대한건설에 배관 100미터, 미터당 18000원, 부가세 별도");
    $("easyComposerNote").textContent = "보내면 CGI 기본 견적서로 바로 만들어 드립니다.";
  }

  function openFileChooser() {
    fileInput.value = "";
    fileInput.click();
  }

  function renderSelectedFile(file, info) {
    startConversation();
    selectedFile = file;

    addMessage(
      "assistant",
      "파일을 안전하게 선택했습니다. 아직 서버 자동 분석은 연결하지 않았기 때문에 이 파일은 외부로 전송되지 않습니다."
    );

    historyPanel.innerHTML = "";
    historyPanel.hidden = false;

    const card = document.createElement("article");
    card.className = "easy-file-card";

    const icon = document.createElement("div");
    icon.className = "easy-file-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = info.category === "image" ? "IMG" : "DOC";

    const details = document.createElement("div");
    details.className = "easy-file-info";

    const name = document.createElement("strong");
    name.textContent = info.name;

    const meta = document.createElement("span");
    meta.textContent = info.label + " · " + info.displaySize;

    const route = document.createElement("p");
    route.textContent = info.pathHint;

    const privacy = document.createElement("small");
    privacy.textContent = "현재 단계: 브라우저에서 형식·크기만 확인 · 업로드 0건 · 파일 내용 저장 0건";

    details.append(name, meta, route, privacy);

    const actions = document.createElement("div");
    actions.className = "easy-file-actions";

    const use = document.createElement("button");
    use.type = "button";
    use.className = "primary";
    use.textContent = "이 파일로 견적 만들기";
    use.addEventListener("click", () => {
      addMessage(
        "assistant",
        "파일 선택과 안전 검증은 완료됐습니다. 자동 분석 서버는 아직 활성화 전이라 업로드·OCR·AI 처리는 시작하지 않았습니다. 모델과 서버 경로가 연결되면 이 단계에서 견적 초안을 만들게 됩니다."
      );
      setChips([
        { label: "다른 파일 선택", action: openFileChooser },
        { label: "질문받으며 만들기", action: startGuided },
        { label: "직접 입력", action: () => setWorkspaceMode("direct") },
        { label: "처음으로", action: showHome }
      ]);
      disableInput("선택한 파일은 이 페이지 메모리에만 있고 외부로 전송되지 않았습니다.");
    });

    const another = document.createElement("button");
    another.type = "button";
    another.textContent = "다른 파일 선택";
    another.addEventListener("click", openFileChooser);

    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "취소";
    cancel.addEventListener("click", showHome);

    actions.append(use, another, cancel);
    card.append(icon, details, actions);
    historyPanel.appendChild(card);

    setChips([
      { label: "다른 파일 선택", action: openFileChooser },
      { label: "직접 입력", action: () => setWorkspaceMode("direct") },
      { label: "처음으로", action: showHome }
    ]);
    disableInput("지원: PDF·DOCX·PPTX·XLSX·HWPX 2 MB 이하 / JPG·PNG·WebP 4 MB 이하");
  }

  function handleFileSelection() {
    const file = fileInput.files && fileInput.files[0];
    if (!file) return;

    const result = FileIntake.classifyFile(file);
    if (!result.ok) {
      startConversation();
      selectedFile = null;
      addMessage("assistant", FileIntake.errorMessage(result));
      setChips([
        { label: "다른 파일 선택", action: openFileChooser },
        { label: "처음으로", action: showHome }
      ]);
      disableInput("파일은 외부로 전송되지 않았습니다.");
      return;
    }

    renderSelectedFile(file, result.value);
  }

  function startFileIntake(options) {
    lastEasyView = "file";
    if (!options || options.history !== false) recordProductState("file");
    startConversation();
    selectedFile = null;
    addMessage(
      "assistant",
      "견적서 파일을 선택해 주세요. PDF·DOCX·PPTX·XLSX·HWPX는 2 MB 이하, JPG·PNG·WebP 이미지는 4 MB 이하를 지원합니다. 기존 HWP(.hwp)는 아직 지원하지 않습니다."
    );
    setChips([
      { label: "파일 선택", action: openFileChooser },
      { label: "질문받으며 만들기", action: startGuided },
      { label: "직접 입력", action: () => setWorkspaceMode("direct") },
      { label: "처음으로", action: showHome }
    ]);
    disableInput("파일 선택 단계는 로컬 preflight만 수행하며 네트워크 업로드는 하지 않습니다.");
    if (!options || options.openChooser !== false) openFileChooser();
  }

  function restoreProductState(view) {
    restoringProductHistory = true;
    try {
      if (view === "direct") {
        setWorkspaceMode("direct", { history: false });
        return;
      }

      setWorkspaceMode("easy", { history: false });
      if (view === "home") {
        showHome({ history: false });
      } else if (lastEasyView === view) {
        return;
      } else if (view === "recent") {
        showRecentHistory({ history: false });
      } else if (view === "free-form") {
        startFreeChat({ history: false });
      } else if (view === "file") {
        startFileIntake({ history: false, openChooser: false });
      } else if (view === "guided") {
        /* popstate 복원은 진행 중이던 guided 상태를 이어 쓴다 — App draft 로 대체하거나
           새 견적번호를 발급하지 않는다. 세션 상태가 없으면 안전하게 Home 으로 귀결한다. */
        if (guided) {
          resumeGuidedConversation(guided);
        } else if (guidedSnapshot) {
          resumeGuidedConversation(guidedSnapshot);
        } else {
          restoreGuidedWithoutState();
        }
      } else {
        showHome({ history: false });
      }
    } finally {
      restoringProductHistory = false;
    }
  }

  $("easyModeButton").addEventListener("click", () => setWorkspaceMode("easy"));
  $("directModeButton").addEventListener("click", () => setWorkspaceMode("direct"));
  $("directStarter").addEventListener("click", () => setWorkspaceMode("direct"));
  $("resumeDraftStarter").addEventListener("click", () => {
    App.toast("중단했던 견적을 이어서 엽니다.");
    setWorkspaceMode("direct");
  });
  $("recentQuoteStarter").addEventListener("click", showRecentHistory);
  $("guidedStarter").addEventListener("click", startGuidedIfReady);
  $("freeChatStarter").addEventListener("click", startFreeChat);
  $("fileStarter").addEventListener("click", startFileIntake);
  fileInput.addEventListener("change", handleFileSelection);

  sendButton.addEventListener("click", submitComposer);
  composer.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitComposer();
    }
  });
  composer.addEventListener("input", () => {
    composer.style.height = "auto";
    composer.style.height = Math.min(composer.scrollHeight, 160) + "px";
  });

  document.addEventListener("b66:account-scope-changed", (event) => {
    const detail = event.detail || {};
    const discarded = detail.privateStateReadable !== true || quarantineAction(detail.action);
    if (!discarded) {
      refreshStarters();
      return;
    }
    // In-flight interpretation belongs to the old owner and cannot complete into this scope.
    accountScopeRevision += 1;
    interpretationInFlight = false;
    /* 계정 경계가 바뀌면 private 텍스트/답변/진행 중 문맥을 화면에서도
       모두 지운다 (#3480, #3536). 응답이 늦게 와도 revision guard 가 폐기한다. */
    guided = null;
    guidedSnapshot = null;
    selectedFile = null;
    setWorkspaceMode("easy", { history: false });
    showHome({ history: false });
  });

  document.addEventListener("b66:auth-changed", (event) => {
    accountSignedIn = Boolean(event.detail && event.detail.authenticated);
    refreshStarters();
  });
  window.addEventListener("b66:history-changed", refreshStarters);
  window.addEventListener("b66:local-data-reset", () => {
    fileInput.value = "";
    setWorkspaceMode("easy", { history: false });
    showHome();
    /* 브라우저 로컬 데이터를 지웠으면 보존된 guided 스냅샷도 함께 폐기한다. */
    guidedSnapshot = null;
  });
  document.addEventListener("b66:open-file-intake", () => {
    setWorkspaceMode("easy", { history: false });
    startFileIntake();
  });

  document.addEventListener("b66:open-recent-quotes", () => {
    setWorkspaceMode("easy", { history: false });
    showRecentHistory();
  });

  document.addEventListener("b66:open-easy-chat", () => {
    setWorkspaceMode("easy");
  });

  window.addEventListener("popstate", (event) => {
    const view = event.state && event.state[PRODUCT_HISTORY_KEY];
    if (typeof view === "string" && view) restoreProductState(view);
  });

  setWorkspaceMode("easy", { history: false });
  showHome({ history: false });
  recordProductState("home", { replace: true });
})();