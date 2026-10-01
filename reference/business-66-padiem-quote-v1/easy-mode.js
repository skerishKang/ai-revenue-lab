/* B66 · Quote Beta — Easy Mode
   Deterministic guided flow + browser-local resume/history.
   No model/provider/network call is made here. */

(() => {
  "use strict";

  const Core = window.QuoteCore;
  const History = window.QuoteHistory;
  const FileIntake = window.B66FileIntake;
  const App = window.B66QuoteAppBridge;

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
  let freeChatPending = "";
  let selectedFile = null;

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function safeText(value, max) {
    return String(value == null ? "" : value).trim().slice(0, max || 2000);
  }

  function readHistory() {
    try {
      return History.normalizeEnvelope(JSON.parse(localStorage.getItem(History.HISTORY_STORAGE_KEY) || "null"));
    } catch (err) {
      return History.normalizeEnvelope(null);
    }
  }

  function writeHistory(envelope) {
    try {
      localStorage.setItem(History.HISTORY_STORAGE_KEY, JSON.stringify(History.normalizeEnvelope(envelope)));
      window.dispatchEvent(new CustomEvent("b66:history-changed"));
      return true;
    } catch (err) {
      App.toast("최근 견적 저장소를 갱신하지 못했습니다.");
      return false;
    }
  }

  function setWorkspaceMode(mode) {
    const easy = mode === "easy";
    easyView.hidden = !easy;
    directView.hidden = easy;
    $("easyModeButton").classList.toggle("active", easy);
    $("directModeButton").classList.toggle("active", !easy);
    $("easyModeButton").setAttribute("aria-pressed", String(easy));
    $("directModeButton").setAttribute("aria-pressed", String(!easy));
    if (!easy) window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function clearConversation() {
    messageList.innerHTML = "";
    historyPanel.innerHTML = "";
    historyPanel.hidden = true;
    chipRow.innerHTML = "";
    inputHandler = null;
  }

  function showHome() {
    clearConversation();
    guided = null;
    freeChatPending = "";
    selectedFile = null;
    easyEmpty.hidden = false;
    composer.value = "";
    composer.placeholder = "필요한 내용을 편하게 입력하세요";
    $("easyComposerNote").textContent =
      "바로 입력해도 질문형이 시작됩니다. 자유 문장 자동 해석은 모델 연결 후 제공됩니다.";
    inputHandler = (text) => startGuided(text);
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
    $("recentQuoteStarter").hidden = readHistory().entries.length === 0;

    let hint = document.getElementById("easyResumeHint");
    if (History.isMeaningfulDraft(activeDraft)) {
      if (!hint) {
        hint = document.createElement("div");
        hint.id = "easyResumeHint";
        hint.className = "easy-resume-hint";
        $("easyStarterGrid").before(hint);
      }
      const company = safeText(activeDraft.recipient.company) || "받는 사람 미정";
      hint.textContent = "지난번 작성하던 견적이 있어요. " + company + " 견적을 이어서 만들 수 있습니다.";
    } else if (hint) {
      hint.remove();
    }
  }

  function showRecentHistory() {
    startConversation();
    addMessage("assistant", "이 브라우저에 저장한 최근 견적입니다. 불러오거나 복사해서 새 견적으로 사용할 수 있어요.");
    renderHistory();
    setChips([
      { label: "질문받으며 새로 만들기", action: startGuided },
      { label: "처음으로", action: showHome }
    ]);
    setInput(() => {}, "최근 견적은 아래 버튼으로 선택하세요");
    composer.disabled = true;
    sendButton.disabled = true;
  }

  function renderHistory() {
    const envelope = readHistory();
    const metadata = History.listMetadata(envelope);
    historyPanel.innerHTML = "";
    historyPanel.hidden = false;

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
    fresh.recipient = { company: "", person: "", address: "", email: "" };
    fresh.items = [];
    fresh.memo = "";
    return fresh;
  }

  function startGuided(referenceText) {
    const reference = typeof referenceText === "string"
      ? safeText(referenceText, 8000)
      : "";
    startConversation();
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

  function askMoreItems() {
    guided.step = "moreItems";
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

  function askSender() {
    guided.step = "senderChoice";
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
    const totals = Core.computeTotals(guided.draft.items, guided.draft.tax.mode);
    const itemLines = guided.draft.items.map((item, index) =>
      (index + 1) + ". " + item.name + " · " +
      Core.formatInputNumber(item.qty) + " × " + Core.formatMoney(item.unitPrice)
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
      "이렇게 준비했어요.\n\n받는 곳: " +
      (guided.draft.recipient.company || "미입력") +
      (guided.draft.recipient.person ? " · " + guided.draft.recipient.person : "") +
      "\n\n" + itemLines +
      "\n\n" + taxLine +
      "\n" + amountLine +
      "\n\n확인 화면에서 모든 내용을 다시 수정할 수 있습니다."
    );

    setChips([
      {
        label: "견적서 확인하기",
        action: () => {
          const result = App.replaceDraft(guided.draft, {
            requireTaxReview: guided.taxUnknown,
            toast: guided.taxUnknown
              ? "견적 초안을 열었습니다. 부가세 방식을 먼저 확인해 주세요."
              : "견적 초안을 열었습니다."
          });
          if (result.ok) {
            setWorkspaceMode("direct");
            if (guided.taxUnknown) {
              setTimeout(() => App.focusTaxReview(), 0);
            }
          }
        }
      },
      { label: "처음부터 다시", action: startGuided },
      { label: "최근 견적 보기", action: showRecentHistory }
    ]);
    disableInput("최종 확인은 기존 직접입력 화면에서 합니다.");
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
        guided.draft.items.push({ id: "item-" + (guided.draft.items.length + 1), name: text, qty: 1, unitPrice: 0 });
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

      case "senderChoice":
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

      case "senderCompany":
        guided.draft.sender.company = text;
        guided.draft.sender.presetId = "custom";
        showGuidedSummary();
        break;

      default:
        break;
    }
  }

  function startFreeChat() {
    startConversation();
    guided = null;
    freeChatPending = "";
    addMessage(
      "assistant",
      "필요한 내용을 한 번에 적어 주세요. 아직 자동 해석 모델은 연결 전이라 내용을 임의로 견적 필드에 넣지는 않습니다. 입력 후 질문형 만들기로 이어갈 수 있어요."
    );
    setChips([
      { label: "질문받으며 만들기", action: startGuided },
      { label: "직접 입력", action: () => setWorkspaceMode("direct") }
    ]);
    setInput((text) => {
      freeChatPending = safeText(text, 8000);
      addMessage("user", freeChatPending);
      addMessage(
        "assistant",
        "내용을 확인했습니다. 현재 버전에서는 이 문장을 AI가 자동 해석하지 않습니다. 질문형으로 이어가면 필요한 값을 하나씩 정확하게 받을 수 있어요."
      );
      setChips([
        { label: "질문받으며 이어가기", action: () => startGuided(freeChatPending) },
        { label: "직접 입력에서 작성", action: () => setWorkspaceMode("direct") },
        { label: "처음으로", action: showHome }
      ]);
      disableInput("자유 문장 자동 해석은 #3143 모델 연결 후 제공됩니다.");
    }, "예: ABC상사 홈페이지 제작 150만원, 유지보수 20만원, 부가세 별도");
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

  function startFileIntake() {
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
    openFileChooser();
  }

  $("easyModeButton").addEventListener("click", () => setWorkspaceMode("easy"));
  $("directModeButton").addEventListener("click", () => setWorkspaceMode("direct"));
  $("directStarter").addEventListener("click", () => setWorkspaceMode("direct"));
  $("resumeDraftStarter").addEventListener("click", () => {
    App.toast("지난번 작성하던 견적을 이어서 엽니다.");
    setWorkspaceMode("direct");
  });
  $("recentQuoteStarter").addEventListener("click", showRecentHistory);
  $("guidedStarter").addEventListener("click", startGuided);
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

  window.addEventListener("b66:history-changed", refreshStarters);
  window.addEventListener("b66:local-data-reset", () => {
    fileInput.value = "";
    setWorkspaceMode("easy");
    showHome();
  });
  document.addEventListener("b66:open-file-intake", () => {
    setWorkspaceMode("easy");
    startFileIntake();
  });

  document.addEventListener("b66:open-easy-chat", () => {
    setWorkspaceMode("easy");
  });

  setWorkspaceMode("easy");
  showHome();
})();
