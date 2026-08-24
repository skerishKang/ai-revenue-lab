(() => {
  "use strict";
  const shell = document.querySelector(".app-shell");
  const emptyState = document.getElementById("emptyState");
  const messageList = document.getElementById("messageList");
  const form = document.getElementById("composerForm");
  const input = document.getElementById("messageInput");
  const sendButton = document.getElementById("sendButton");
  const newChatButton = document.getElementById("newChatButton");
  const mobileMenu = document.getElementById("mobileMenu");
  const mobileClose = document.getElementById("mobileClose");
  const sidebarScrim = document.getElementById("sidebarScrim");
  let messages = [];
  let inFlight = false;
  let conversationSkill = "auto";

  function updateComposer() {
    sendButton.disabled = inFlight || input.value.trim().length === 0;
    input.disabled = inFlight;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  }
  function showConversation() { emptyState.hidden = true; messageList.hidden = false; shell.dataset.state = "chat"; }
  function addUserMessage(text) {
    const fragment = document.getElementById("userMessageTemplate").content.cloneNode(true);
    fragment.querySelector(".message-bubble").textContent = text;
    messageList.appendChild(fragment);
  }
  function addAssistantShell(label) {
    const fragment = document.getElementById("assistantMessageTemplate").content.cloneNode(true);
    const article = fragment.querySelector(".assistant-message");
    article.querySelector("[data-runtime-label]").textContent = label;
    messageList.appendChild(fragment);
    return article;
  }
  function renderTyping(article) {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const typing = document.createElement("span"); typing.className = "typing"; typing.setAttribute("aria-label", "답변 준비 중");
    typing.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    content.appendChild(typing);
  }
  function renderAnswer(article, result) {
    const content = article.querySelector(".assistant-content"); content.replaceChildren();
    const paragraph = document.createElement("p"); paragraph.textContent = result.answer; content.appendChild(paragraph);
    const skillTitle = result.skill && result.skill.id !== "auto" && typeof result.skill.title === "string" ? result.skill.title : "";
    const runtimeLabel = result.runtime === "mock" ? "모의 응답 · 실제 모델 호출 없음" : "AI 응답";
    article.querySelector("[data-runtime-label]").textContent = skillTitle ? `${runtimeLabel} · ${skillTitle}` : runtimeLabel;
    if (result.runtime === "b14" && result.route && (result.route.model || result.route.provider)) {
      const details = document.createElement("details"); details.className = "route-details";
      const summary = document.createElement("summary"); summary.textContent = "어떤 AI가 답했나요?";
      const meta = document.createElement("p"); const pieces = [];
      if (result.route.provider) pieces.push(`제공 경로: ${result.route.provider}`);
      if (result.route.model) pieces.push(`모델: ${result.route.model}`);
      meta.textContent = pieces.join(" · "); details.append(summary, meta); content.appendChild(details);
    }
  }
  function renderError(article, message, retryMessages, retrySkill) {
    const content = article.querySelector(".assistant-content"); content.replaceChildren();
    article.querySelector("[data-runtime-label]").textContent = "연결 오류";
    const box = document.createElement("div"); box.className = "error-box";
    const strong = document.createElement("strong"); strong.textContent = "답변을 불러오지 못했습니다.";
    const p = document.createElement("p"); p.textContent = message || "잠시 후 다시 시도해 주세요.";
    const retry = document.createElement("button"); retry.type = "button"; retry.className = "retry-button"; retry.textContent = "다시 시도";
    retry.addEventListener("click", () => { article.remove(); requestAnswer(retryMessages, retrySkill); }, { once: true });
    box.append(strong, p, retry); content.appendChild(box);
  }
  async function requestAnswer(outboundMessages, skill) {
    if (inFlight) return; inFlight = true; updateComposer();
    const article = addAssistantShell("답변 준비 중"); renderTyping(article);
    try {
      const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ messages: outboundMessages, mode: "auto", skill }) });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || typeof data.answer !== "string") {
        const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.";
        throw new Error(message);
      }
      renderAnswer(article, data);
      messages = outboundMessages.concat([{ role: "assistant", content: data.answer }]).slice(-20);
      article.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } catch (error) {
      renderError(article, error instanceof Error ? error.message : "다시 시도해 주세요.", outboundMessages, skill);
    } finally { inFlight = false; updateComposer(); input.focus(); }
  }
  async function submitPrompt(text, selectedSkill) {
    const prompt = text.trim(); if (!prompt || inFlight) return;
    if (selectedSkill) conversationSkill = selectedSkill;
    showConversation(); addUserMessage(prompt); input.value = "";
    const outbound = messages.concat([{ role: "user", content: prompt }]).slice(-20);
    await requestAnswer(outbound, conversationSkill);
  }
  function closeSidebar() { shell.classList.remove("sidebar-open"); mobileMenu.setAttribute("aria-expanded", "false"); sidebarScrim.hidden = true; }
  function resetChat() { messages = []; conversationSkill = "auto"; messageList.replaceChildren(); messageList.hidden = true; emptyState.hidden = false; shell.dataset.state = "home"; input.value = ""; updateComposer(); closeSidebar(); input.focus(); }
  function openSidebar() { shell.classList.add("sidebar-open"); mobileMenu.setAttribute("aria-expanded", "true"); sidebarScrim.hidden = false; mobileClose.focus(); }
  input.addEventListener("input", updateComposer);
  input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); if (!sendButton.disabled) form.requestSubmit(); } });
  form.addEventListener("submit", (event) => { event.preventDefault(); submitPrompt(input.value); });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { submitPrompt(button.dataset.prompt || "", button.dataset.skill || "auto"); closeSidebar(); }));
  newChatButton.addEventListener("click", resetChat); mobileMenu.addEventListener("click", openSidebar); mobileClose.addEventListener("click", closeSidebar); sidebarScrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && shell.classList.contains("sidebar-open")) closeSidebar(); });
  updateComposer();
})();
