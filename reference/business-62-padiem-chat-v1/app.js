(() => {
  "use strict";

  const shell = document.querySelector(".app-shell");
  const emptyState = document.getElementById("emptyState");
  const messageList = document.getElementById("messageList");
  const form = document.getElementById("composerForm");
  const input = document.getElementById("messageInput");
  const sendButton = document.getElementById("sendButton");
  const attachButton = document.getElementById("attachButton");
  const searchButton = document.getElementById("searchButton");
  const attachmentChip = document.getElementById("attachmentChip");
  const removeAttachment = document.getElementById("removeAttachment");
  const newChatButton = document.getElementById("newChatButton");
  const mobileMenu = document.getElementById("mobileMenu");
  const mobileClose = document.getElementById("mobileClose");
  const sidebarScrim = document.getElementById("sidebarScrim");

  let searchMode = false;
  let hasAttachment = false;

  const demoAnswers = {
    default: [
      "좋습니다. 이 화면에서는 실제 AI 대신 UX 검토용 데모 응답을 보여드리고 있습니다.",
      "실제 연결 단계에서는 질문의 난이도와 필요한 기능을 보고 적절한 모델을 자동으로 선택하도록 설계할 예정입니다. 일반 사용자는 모델 이름을 몰라도 됩니다."
    ],
    easy: [
      "AI는 아주 쉽게 말하면, 사람이 물어본 말을 읽고 그다음에 가장 도움이 될 만한 말을 만들어 주는 컴퓨터 도우미입니다.",
      "예를 들어 ‘김치찌개 어떻게 끓여?’라고 물으면 요리 순서를 알려주고, 어려운 문서를 올리면 중요한 내용만 쉽게 풀어줄 수 있습니다. 다만 틀릴 때도 있으니 중요한 내용은 출처나 원문을 함께 확인하는 것이 좋습니다."
    ],
    travel: [
      "가족 여행이라면 이동을 너무 빡빡하게 잡지 않는 것이 좋습니다. 첫날은 도착과 숙소 주변, 둘째 날은 대표 관광지, 셋째 날은 식사와 산책 중심으로 구성하면 부담이 적습니다.",
      "실제 서비스에서는 지역, 이동수단, 연령대, 예산을 이어서 물어보고 일정표 형태로 정리할 수 있습니다."
    ],
    document: [
      "파일이 준비된 것으로 가정한 데모 상태입니다. 실제 연결 후에는 문서의 핵심 주장, 중요한 날짜·수치, 해야 할 일, 확인이 필요한 부분을 구분해 정리하는 흐름을 제공합니다.",
      "지금 첨부된 파일 표시는 UI 검토용 예시이며 실제 파일이 업로드되지는 않았습니다."
    ]
  };

  function updateSendState() {
    sendButton.disabled = input.value.trim().length === 0;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  }

  function setSearchMode(value) {
    searchMode = Boolean(value);
    searchButton.setAttribute("aria-pressed", String(searchMode));
  }

  function setAttachment(value) {
    hasAttachment = Boolean(value);
    attachmentChip.hidden = !hasAttachment;
  }

  function resetChat() {
    emptyState.hidden = false;
    messageList.hidden = true;
    messageList.replaceChildren();
    input.value = "";
    setSearchMode(false);
    setAttachment(false);
    shell.dataset.state = "home";
    updateSendState();
    input.focus();
  }

  function addUserMessage(text) {
    const fragment = document.getElementById("userMessageTemplate").content.cloneNode(true);
    fragment.querySelector(".message-bubble").textContent = text;
    messageList.appendChild(fragment);
  }

  function assistantShell() {
    const fragment = document.getElementById("assistantMessageTemplate").content.cloneNode(true);
    const article = fragment.querySelector(".assistant-message");
    messageList.appendChild(fragment);
    return article;
  }

  function addTyping() {
    const article = assistantShell();
    const content = article.querySelector(".assistant-content");
    content.innerHTML = '<span class="typing" aria-label="답변 준비 중"><i></i><i></i><i></i></span>';
    return article;
  }

  function pickAnswer(prompt) {
    if (hasAttachment || /문서|파일|요약/.test(prompt)) return demoAnswers.document;
    if (/부모|쉽게|AI/.test(prompt)) return demoAnswers.easy;
    if (/여행|제주|주말/.test(prompt)) return demoAnswers.travel;
    return demoAnswers.default;
  }

  function renderSearchAnswer(content) {
    content.innerHTML = `
      <p><strong>웹 검색 데모 상태</strong>입니다. 실제 서비스에서는 최신 웹 정보를 확인한 뒤 답변 문장과 출처를 연결합니다.</p>
      <p>지금은 네트워크 호출을 하지 않으며 아래 카드는 출처 UI의 모양과 읽기 흐름만 검토하기 위한 예시입니다.</p>
      <div class="source-list" aria-label="예시 출처">
        <div class="source-card"><span class="source-index">1</span><span><strong>공식 출처 예시</strong><small>example.com · 실제 검색 결과 아님</small></span></div>
        <div class="source-card"><span class="source-index">2</span><span><strong>보조 출처 예시</strong><small>example.org · 실제 검색 결과 아님</small></span></div>
      </div>`;
  }

  function renderNormalAnswer(content, prompt) {
    const answer = pickAnswer(prompt);
    content.innerHTML = answer.map((paragraph) => `<p>${escapeHtml(paragraph)}</p>`).join("");
  }

  function renderError(content) {
    content.innerHTML = `
      <div class="error-box">
        <strong>답변을 불러오지 못했습니다.</strong>
        <p>잠시 후 다시 시도해 주세요. 실제 서비스에서는 실패 원인에 따라 자동 재시도나 다른 모델 경로를 사용할 수 있습니다.</p>
        <button class="retry-button" type="button">다시 시도</button>
      </div>`;
    content.querySelector(".retry-button").addEventListener("click", () => {
      content.innerHTML = "";
      renderNormalAnswer(content, "일반 질문");
      shell.dataset.state = "chat";
    }, { once: true });
  }

  function escapeHtml(value) {
    return value.replace(/[&<>'\"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '\"': "&quot;" })[char]);
  }

  function showConversation() {
    emptyState.hidden = true;
    messageList.hidden = false;
  }

  function submitPrompt(prompt, forcedState) {
    const text = prompt.trim();
    if (!text) return;

    showConversation();
    addUserMessage(text);
    input.value = "";
    updateSendState();

    const typingArticle = addTyping();
    const content = typingArticle.querySelector(".assistant-content");
    const targetState = forcedState || (searchMode ? "search" : "chat");
    shell.dataset.state = targetState;

    const complete = () => {
      if (targetState === "search") renderSearchAnswer(content);
      else if (targetState === "error") renderError(content);
      else renderNormalAnswer(content, text);
      typingArticle.scrollIntoView({ block: "nearest", behavior: "smooth" });
    };

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) complete();
    else window.setTimeout(complete, 420);
  }

  function closeSidebar() {
    shell.classList.remove("sidebar-open");
    mobileMenu.setAttribute("aria-expanded", "false");
    sidebarScrim.hidden = true;
  }

  function openSidebar() {
    shell.classList.add("sidebar-open");
    mobileMenu.setAttribute("aria-expanded", "true");
    sidebarScrim.hidden = false;
    mobileClose.focus();
  }

  input.addEventListener("input", updateSendState);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sendButton.disabled) form.requestSubmit();
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitPrompt(input.value);
  });

  attachButton.addEventListener("click", () => {
    setAttachment(true);
    shell.dataset.state = "attachment";
    input.focus();
  });
  removeAttachment.addEventListener("click", () => setAttachment(false));
  searchButton.addEventListener("click", () => {
    setSearchMode(!searchMode);
    input.focus();
  });
  newChatButton.addEventListener("click", () => {
    resetChat();
    closeSidebar();
  });

  document.querySelectorAll("[data-demo-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      const prompt = button.dataset.demoPrompt || "";
      if (button.dataset.search === "true") setSearchMode(true);
      if (button.dataset.needsAttachment === "true") setAttachment(true);
      submitPrompt(prompt, button.dataset.search === "true" ? "search" : undefined);
      closeSidebar();
    });
  });

  document.querySelector('[data-action="focus-search"]').addEventListener("click", () => {
    setSearchMode(true);
    input.focus();
    closeSidebar();
  });

  mobileMenu.addEventListener("click", openSidebar);
  mobileClose.addEventListener("click", closeSidebar);
  sidebarScrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && shell.classList.contains("sidebar-open")) closeSidebar();
  });

  function loadReviewState() {
    const state = new URLSearchParams(window.location.search).get("state");
    if (!state || state === "home") return;
    if (state === "attachment") {
      setAttachment(true);
      shell.dataset.state = "attachment";
      return;
    }
    if (state === "chat") submitPrompt("부모님께 AI를 아주 쉽게 설명해줘", "chat");
    if (state === "search") {
      setSearchMode(true);
      submitPrompt("오늘 중요한 AI 뉴스를 찾아줘", "search");
    }
    if (state === "error") submitPrompt("오류 상태를 보여줘", "error");
  }

  updateSendState();
  loadReviewState();
})();
