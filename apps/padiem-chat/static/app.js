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
  const imageFileInput = document.getElementById("imageFileInput");
  const imageAttachButton = document.getElementById("imageAttachButton");
  const attachmentTray = document.getElementById("attachmentTray");
  const attachmentThumb = document.getElementById("attachmentThumb");
  const attachmentName = document.getElementById("attachmentName");
  const attachmentSize = document.getElementById("attachmentSize");
  const removeAttachment = document.getElementById("removeAttachment");
  const runtimeNote = document.getElementById("runtimeNote");
  const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
  const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
  const DEFAULT_NOTE = "일반 질문과 JPEG·PNG·WebP 사진 1장 첨부를 지원합니다. PDF·문서·웹 검색·로그인은 다음 단계에서 지원합니다.";
  let messages = [];
  let inFlight = false;
  let conversationSkill = "auto";
  let selectedAttachment = null;

  function setNote(text, state = "normal") {
    runtimeNote.textContent = text;
    runtimeNote.dataset.state = state;
  }
  function updateComposer() {
    sendButton.disabled = inFlight || input.value.trim().length === 0;
    input.disabled = inFlight;
    imageAttachButton.disabled = inFlight;
    removeAttachment.disabled = inFlight;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  }
  function showConversation() { emptyState.hidden = true; messageList.hidden = false; shell.dataset.state = "chat"; }
  function addUserMessage(text, attachment) {
    const fragment = document.getElementById("userMessageTemplate").content.cloneNode(true);
    const bubble = fragment.querySelector(".message-bubble");
    bubble.textContent = text;
    if (attachment) {
      const meta = document.createElement("span");
      meta.className = "message-attachment-meta";
      meta.textContent = `사진 · ${attachment.name} · ${formatBytes(attachment.byteSize)}`;
      bubble.appendChild(meta);
    }
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
  function renderError(article, message, retryMessages, retrySkill, retryAttachment) {
    const content = article.querySelector(".assistant-content"); content.replaceChildren();
    article.querySelector("[data-runtime-label]").textContent = "연결 오류";
    const box = document.createElement("div"); box.className = "error-box";
    const strong = document.createElement("strong"); strong.textContent = "답변을 불러오지 못했습니다.";
    const p = document.createElement("p"); p.textContent = message || "잠시 후 다시 시도해 주세요.";
    const retry = document.createElement("button"); retry.type = "button"; retry.className = "retry-button"; retry.textContent = "다시 시도";
    retry.addEventListener("click", async () => {
      article.remove();
      const success = await requestAnswer(retryMessages, retrySkill, retryAttachment);
      if (success && selectedAttachment === retryAttachment) clearAttachment();
    }, { once: true });
    box.append(strong, p, retry); content.appendChild(box);
  }
  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function clearAttachment() {
    if (selectedAttachment && selectedAttachment.previewUrl) URL.revokeObjectURL(selectedAttachment.previewUrl);
    selectedAttachment = null;
    imageFileInput.value = "";
    attachmentThumb.removeAttribute("src");
    attachmentName.textContent = "";
    attachmentSize.textContent = "";
    attachmentTray.hidden = true;
    setNote(DEFAULT_NOTE);
    updateComposer();
  }
  function renderSelectedAttachment() {
    if (!selectedAttachment) { attachmentTray.hidden = true; return; }
    attachmentThumb.src = selectedAttachment.previewUrl;
    attachmentName.textContent = selectedAttachment.name;
    attachmentSize.textContent = formatBytes(selectedAttachment.byteSize);
    attachmentTray.hidden = false;
    setNote("선택한 사진은 이 질문과 함께 한 번만 전송됩니다.");
  }
  function readAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(reader.result), { once: true });
      reader.addEventListener("error", () => reject(new Error("사진을 읽지 못했습니다.")), { once: true });
      reader.readAsDataURL(file);
    });
  }
  async function selectImage(file) {
    if (!file) return;
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
      imageFileInput.value = "";
      setNote("JPEG, PNG, WebP 사진만 첨부할 수 있습니다.", "error");
      return;
    }
    if (file.size < 1 || file.size > MAX_IMAGE_BYTES) {
      imageFileInput.value = "";
      setNote("사진은 4 MiB 이하만 첨부할 수 있습니다.", "error");
      return;
    }
    try {
      const dataUrl = await readAsDataUrl(file);
      const expectedPrefix = `data:${file.type};base64,`;
      if (typeof dataUrl !== "string" || !dataUrl.startsWith(expectedPrefix)) throw new Error("사진 형식을 확인할 수 없습니다.");
      const base64 = dataUrl.slice(expectedPrefix.length);
      if (!base64) throw new Error("사진 데이터가 비어 있습니다.");
      if (selectedAttachment && selectedAttachment.previewUrl) URL.revokeObjectURL(selectedAttachment.previewUrl);
      selectedAttachment = {
        type: "image",
        name: file.name || "image",
        mediaType: file.type,
        base64,
        byteSize: file.size,
        previewUrl: URL.createObjectURL(file),
      };
      renderSelectedAttachment();
    } catch (error) {
      imageFileInput.value = "";
      setNote(error instanceof Error ? error.message : "사진을 읽지 못했습니다.", "error");
    }
  }
  function attachmentPayload(attachment) {
    if (!attachment) return undefined;
    return [{
      type: "image",
      name: attachment.name,
      media_type: attachment.mediaType,
      base64: attachment.base64,
    }];
  }
  async function requestAnswer(outboundMessages, skill, attachment) {
    if (inFlight) return false; inFlight = true; updateComposer();
    const article = addAssistantShell("답변 준비 중"); renderTyping(article);
    try {
      const payload = { messages: outboundMessages, mode: "auto", skill };
      const attachments = attachmentPayload(attachment);
      if (attachments) payload.attachments = attachments;
      const response = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || typeof data.answer !== "string") {
        const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.";
        throw new Error(message);
      }
      renderAnswer(article, data);
      messages = outboundMessages.concat([{ role: "assistant", content: data.answer }]).slice(-20);
      article.scrollIntoView({ block: "nearest", behavior: "smooth" });
      return true;
    } catch (error) {
      renderError(article, error instanceof Error ? error.message : "다시 시도해 주세요.", outboundMessages, skill, attachment);
      return false;
    } finally { inFlight = false; updateComposer(); input.focus(); }
  }
  async function submitPrompt(text, selectedSkill) {
    const prompt = text.trim(); if (!prompt || inFlight) return;
    if (selectedSkill) conversationSkill = selectedSkill;
    const attachmentSnapshot = selectedAttachment;
    showConversation(); addUserMessage(prompt, attachmentSnapshot); input.value = "";
    const outbound = messages.concat([{ role: "user", content: prompt }]).slice(-20);
    const success = await requestAnswer(outbound, conversationSkill, attachmentSnapshot);
    if (success && selectedAttachment === attachmentSnapshot) clearAttachment();
  }
  function closeSidebar() { shell.classList.remove("sidebar-open"); mobileMenu.setAttribute("aria-expanded", "false"); sidebarScrim.hidden = true; }
  function resetChat() { messages = []; conversationSkill = "auto"; clearAttachment(); messageList.replaceChildren(); messageList.hidden = true; emptyState.hidden = false; shell.dataset.state = "home"; input.value = ""; updateComposer(); closeSidebar(); input.focus(); }
  function openSidebar() { shell.classList.add("sidebar-open"); mobileMenu.setAttribute("aria-expanded", "true"); sidebarScrim.hidden = false; mobileClose.focus(); }
  input.addEventListener("input", updateComposer);
  input.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); if (!sendButton.disabled) form.requestSubmit(); } });
  form.addEventListener("submit", (event) => { event.preventDefault(); submitPrompt(input.value); });
  imageAttachButton.addEventListener("click", () => { if (!inFlight) imageFileInput.click(); });
  imageFileInput.addEventListener("change", () => { const [file] = imageFileInput.files || []; selectImage(file); });
  removeAttachment.addEventListener("click", clearAttachment);
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { submitPrompt(button.dataset.prompt || "", button.dataset.skill || "auto"); closeSidebar(); }));
  newChatButton.addEventListener("click", resetChat); mobileMenu.addEventListener("click", openSidebar); mobileClose.addEventListener("click", closeSidebar); sidebarScrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && shell.classList.contains("sidebar-open")) closeSidebar(); });
  setNote(DEFAULT_NOTE); updateComposer();
})();
