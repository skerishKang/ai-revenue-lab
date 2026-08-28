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
  const attachmentFileInput = document.getElementById("attachmentFileInput");
  const attachmentButton = document.getElementById("attachmentButton");
  const attachmentTray = document.getElementById("attachmentTray");
  const attachmentThumb = document.getElementById("attachmentThumb");
  const attachmentKind = document.getElementById("attachmentKind");
  const attachmentName = document.getElementById("attachmentName");
  const attachmentSize = document.getElementById("attachmentSize");
  const removeAttachment = document.getElementById("removeAttachment");
  const documentStarterButton = document.getElementById("documentStarterButton");
  const runtimeNote = document.getElementById("runtimeNote");
  const loginButton = document.getElementById("loginButton");
  const accountName = document.getElementById("accountName");
  const historySection = document.getElementById("historySection");
  const historyList = document.getElementById("historyList");
  const historyEmpty = document.getElementById("historyEmpty");
  const projectsNavButton = document.getElementById("projectsNavButton");
  const projectsBadge = document.getElementById("projectsBadge");
  const projectsSection = document.getElementById("projectsSection");
  const projectsList = document.getElementById("projectsList");
  const projectsEmpty = document.getElementById("projectsEmpty");
  const projectCreateButton = document.getElementById("projectCreateButton");
  const projectBanner = document.getElementById("projectBanner");
  const activeProjectName = document.getElementById("activeProjectName");
  const activeProjectFiles = document.getElementById("activeProjectFiles");
  const editProjectButton = document.getElementById("editProjectButton");
  const exitProjectButton = document.getElementById("exitProjectButton");
  const projectDialog = document.getElementById("projectDialog");
  const projectForm = document.getElementById("projectForm");
  const projectDialogTitle = document.getElementById("projectDialogTitle");
  const projectDialogClose = document.getElementById("projectDialogClose");
  const projectDialogCancel = document.getElementById("projectDialogCancel");
  const projectNameInput = document.getElementById("projectNameInput");
  const projectInstructionsInput = document.getElementById("projectInstructionsInput");
  const projectFormError = document.getElementById("projectFormError");
  const projectSaveButton = document.getElementById("projectSaveButton");
  const projectFilesPanel = document.getElementById("projectFilesPanel");
  const projectFileInput = document.getElementById("projectFileInput");
  const projectFilesList = document.getElementById("projectFilesList");
  const projectFilesEmpty = document.getElementById("projectFilesEmpty");

  const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
  const MAX_DOCUMENT_BYTES = 96 * 1024;
  const MAX_DOCUMENT_CHARS = 40000;
  const ALLOWED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
  const ALLOWED_DOCUMENT_TYPES = new Set(["text/plain", "text/markdown", "text/csv", "application/json"]);
  const DOCUMENT_EXTENSION_TYPES = new Map([
    [".txt", "text/plain"],
    [".md", "text/markdown"],
    [".markdown", "text/markdown"],
    [".csv", "text/csv"],
    [".json", "application/json"],
  ]);
  const DEFAULT_NOTE = "사진과 TXT·Markdown·CSV·JSON 문서 한 개를 첨부할 수 있습니다. PDF·Office 문서는 아직 지원하지 않습니다.";

  let messages = [];
  let inFlight = false;
  let activeRequestController = null;
  let conversationEpoch = 0;
  let conversationSkill = "auto";
  let selectedAttachment = null;
  let conversationId = null;
  let authState = { ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false };
  let projects = [];
  let projectsReady = false;
  let activeProject = null;
  let activeProjectFileCount = 0;
  let editingProjectId = null;
  let dialogProjectFiles = [];

  function idleNote() {
    return activeProject ? `‘${activeProject.name}’ 프로젝트의 지침과 저장 파일을 이 대화에 적용합니다.` : DEFAULT_NOTE;
  }
  function setNote(text, state = "normal") {
    runtimeNote.textContent = text;
    runtimeNote.dataset.state = state;
  }
  function updateComposer() {
    sendButton.disabled = inFlight || input.value.trim().length === 0;
    input.disabled = inFlight;
    attachmentButton.disabled = inFlight;
    removeAttachment.disabled = inFlight;
    editProjectButton.disabled = inFlight;
    exitProjectButton.disabled = inFlight;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  }
  function showConversation() {
    emptyState.hidden = true;
    messageList.hidden = false;
    shell.dataset.state = "chat";
  }
  function addUserMessage(text, attachment) {
    const fragment = document.getElementById("userMessageTemplate").content.cloneNode(true);
    const bubble = fragment.querySelector(".message-bubble");
    bubble.textContent = text;
    if (attachment) {
      const meta = document.createElement("span");
      meta.className = "message-attachment-meta";
      const label = attachment.type === "image" ? "사진" : "문서";
      meta.textContent = `${label} · ${attachment.name} · ${formatBytes(attachment.byteSize)}`;
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
    const typing = document.createElement("span");
    typing.className = "typing";
    typing.setAttribute("aria-label", "답변 준비 중");
    typing.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    content.appendChild(typing);
  }
  function renderStoredAssistant(text) {
    const article = addAssistantShell("저장된 대화");
    const content = article.querySelector(".assistant-content");
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    content.appendChild(paragraph);
  }
  function renderAnswer(article, result) {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.textContent = result.answer;
    content.appendChild(paragraph);
    if (Number.isInteger(result.project_files_used) && result.project_files_used > 0) {
      const used = document.createElement("small");
      used.className = "reference-note";
      used.textContent = `프로젝트 파일 ${result.project_files_used}개를 참고했습니다.`;
      content.appendChild(used);
    }
    const skillTitle = result.skill && result.skill.id !== "auto" && typeof result.skill.title === "string" ? result.skill.title : "";
    const runtimeLabel = result.runtime === "mock" ? "모의 응답 · 실제 모델 호출 없음" : "AI 응답";
    article.querySelector("[data-runtime-label]").textContent = skillTitle ? `${runtimeLabel} · ${skillTitle}` : runtimeLabel;
    if (result.runtime === "b14" && result.route && (result.route.model || result.route.provider)) {
      const details = document.createElement("details");
      details.className = "route-details";
      const summary = document.createElement("summary");
      summary.textContent = "어떤 AI가 답했나요?";
      const meta = document.createElement("p");
      const pieces = [];
      if (result.route.provider) pieces.push(`제공 경로: ${result.route.provider}`);
      if (result.route.model) pieces.push(`모델: ${result.route.model}`);
      meta.textContent = pieces.join(" · ");
      details.append(summary, meta);
      content.appendChild(details);
    }
  }
  function buildRetryBox(message, article, retryMessages, retrySkill, retryAttachment, retryContext) {
    const box = document.createElement("div");
    box.className = "error-box";
    const strong = document.createElement("strong");
    strong.textContent = "답변을 불러오지 못했습니다.";
    const p = document.createElement("p");
    p.textContent = message || "잠시 후 다시 시도해 주세요.";
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "retry-button";
    retry.textContent = "다시 시도";
    retry.addEventListener("click", async () => {
      article.remove();
      conversationId = retryContext.conversationId;
      activeProject = retryContext.project;
      renderProjectState();
      const success = await requestAnswer(retryMessages, retrySkill, retryAttachment, retryContext);
      if (success && selectedAttachment === retryAttachment) clearAttachment();
    }, { once: true });
    box.append(strong, p, retry);
    return box;
  }
  function revealErrorState(article) {
    article.scrollIntoView({ block: "center", behavior: "auto" });
  }
  function renderError(article, message, retryMessages, retrySkill, retryAttachment, retryContext) {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    article.querySelector("[data-runtime-label]").textContent = "연결 오류";
    content.appendChild(buildRetryBox(message, article, retryMessages, retrySkill, retryAttachment, retryContext));
    revealErrorState(article);
  }
  function renderStreamError(article, message, retryMessages, retrySkill, retryContext) {
    const content = article.querySelector(".assistant-content");
    const typing = content.querySelector(".typing");
    if (typing) typing.remove();
    article.querySelector("[data-runtime-label]").textContent = "연결 오류";
    content.appendChild(buildRetryBox(message, article, retryMessages, retrySkill, null, retryContext));
    revealErrorState(article);
  }

  function parseSseFrame(frame) {
    const lines = frame.replace(/\r\n/g, "\n").split("\n");
    let event = "message";
    const dataLines = [];
    lines.forEach((line) => {
      if (!line || line.startsWith(":")) return;
      const separator = line.indexOf(":");
      const field = separator >= 0 ? line.slice(0, separator) : line;
      let value = separator >= 0 ? line.slice(separator + 1) : "";
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      if (field === "data") dataLines.push(value);
    });
    if (!dataLines.length) return null;
    return { event, data: dataLines.join("\n") };
  }
  async function readSseEvents(response, onEvent) {
    if (!response.body || typeof response.body.getReader !== "function") throw new Error("스트리밍 응답을 읽을 수 없습니다.");
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let reachedEof = false;
    let stoppedEarly = false;
    try {
      while (true) {
        const item = await reader.read();
        if (item.done) {
          reachedEof = true;
          break;
        }
        buffer += decoder.decode(item.value, { stream: true });
        while (true) {
          const boundary = buffer.match(/\r?\n\r?\n/);
          if (!boundary || boundary.index === undefined) break;
          const frameText = buffer.slice(0, boundary.index);
          buffer = buffer.slice(boundary.index + boundary[0].length);
          const frame = parseSseFrame(frameText);
          if (frame && await onEvent(frame)) {
            stoppedEarly = true;
            return;
          }
        }
      }
      buffer += decoder.decode();
      if (buffer.trim()) throw new Error("AI 스트리밍 응답이 완전히 끝나지 않았습니다.");
    } finally {
      if (!reachedEof || stoppedEarly) {
        try { await reader.cancel(); } catch (_) { /* no-op */ }
      }
      reader.releaseLock();
    }
  }

  function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  function extensionOf(name) {
    const lower = String(name || "").toLowerCase();
    const index = lower.lastIndexOf(".");
    return index >= 0 ? lower.slice(index) : "";
  }
  function documentMediaType(file) {
    if (ALLOWED_DOCUMENT_TYPES.has(file.type)) return file.type;
    return DOCUMENT_EXTENSION_TYPES.get(extensionOf(file.name)) || null;
  }
  function clearAttachment() {
    if (selectedAttachment && selectedAttachment.previewUrl) URL.revokeObjectURL(selectedAttachment.previewUrl);
    selectedAttachment = null;
    attachmentFileInput.value = "";
    attachmentThumb.removeAttribute("src");
    attachmentThumb.hidden = true;
    attachmentKind.hidden = true;
    attachmentName.textContent = "";
    attachmentSize.textContent = "";
    attachmentTray.hidden = true;
    setNote(idleNote());
    updateComposer();
  }
  function renderSelectedAttachment() {
    if (!selectedAttachment) {
      attachmentTray.hidden = true;
      return;
    }
    if (selectedAttachment.type === "image") {
      attachmentThumb.src = selectedAttachment.previewUrl;
      attachmentThumb.hidden = false;
      attachmentKind.hidden = true;
      setNote("선택한 사진은 이 질문과 함께 한 번만 전송됩니다.");
    } else {
      attachmentThumb.removeAttribute("src");
      attachmentThumb.hidden = true;
      attachmentKind.hidden = false;
      attachmentKind.textContent = extensionOf(selectedAttachment.name).replace(".", "").toUpperCase() || "DOC";
      setNote("선택한 문서는 이 질문의 참고 자료로만 사용되며 대화 기록에 파일 내용이 저장되지 않습니다.");
    }
    attachmentName.textContent = selectedAttachment.name;
    attachmentSize.textContent = formatBytes(selectedAttachment.byteSize);
    attachmentTray.hidden = false;
  }
  function readAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(reader.result), { once: true });
      reader.addEventListener("error", () => reject(new Error("사진을 읽지 못했습니다.")), { once: true });
      reader.readAsDataURL(file);
    });
  }
  function readAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(reader.result), { once: true });
      reader.addEventListener("error", () => reject(new Error("문서를 읽지 못했습니다.")), { once: true });
      reader.readAsText(file, "UTF-8");
    });
  }
  async function readDocumentFile(file) {
    const mediaType = documentMediaType(file);
    if (!mediaType) throw new Error("현재는 TXT, Markdown, CSV, JSON 문서만 지원합니다. PDF·Office 문서는 아직 지원하지 않습니다.");
    if (file.size < 1 || file.size > MAX_DOCUMENT_BYTES) throw new Error("텍스트 문서는 96 KiB 이하만 첨부할 수 있습니다.");
    const raw = await readAsText(file);
    if (typeof raw !== "string") throw new Error("문서를 읽지 못했습니다.");
    const text = raw.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (!text.trim()) throw new Error("빈 문서는 첨부할 수 없습니다.");
    if (text.length > MAX_DOCUMENT_CHARS) throw new Error("문서는 40,000자 이하만 첨부할 수 있습니다.");
    if (text.includes("\u0000")) throw new Error("바이너리 파일은 텍스트 문서로 첨부할 수 없습니다.");
    return { type: "document", name: file.name || "document.txt", mediaType, text, byteSize: file.size };
  }
  async function selectImage(file) {
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) throw new Error("JPEG, PNG, WebP 사진만 첨부할 수 있습니다.");
    if (file.size < 1 || file.size > MAX_IMAGE_BYTES) throw new Error("사진은 4 MiB 이하만 첨부할 수 있습니다.");
    const dataUrl = await readAsDataUrl(file);
    const expectedPrefix = `data:${file.type};base64,`;
    if (typeof dataUrl !== "string" || !dataUrl.startsWith(expectedPrefix)) throw new Error("사진 형식을 확인할 수 없습니다.");
    const base64 = dataUrl.slice(expectedPrefix.length);
    if (!base64) throw new Error("사진 데이터가 비어 있습니다.");
    return { type: "image", name: file.name || "image", mediaType: file.type, base64, byteSize: file.size, previewUrl: URL.createObjectURL(file) };
  }
  async function selectAttachment(file) {
    if (!file) return;
    try {
      const next = ALLOWED_IMAGE_TYPES.has(file.type) ? await selectImage(file) : await readDocumentFile(file);
      if (selectedAttachment && selectedAttachment.previewUrl) URL.revokeObjectURL(selectedAttachment.previewUrl);
      selectedAttachment = next;
      renderSelectedAttachment();
    } catch (error) {
      attachmentFileInput.value = "";
      setNote(error instanceof Error ? error.message : "파일을 읽지 못했습니다.", "error");
    }
  }
  function attachmentPayload(attachment) {
    if (!attachment) return undefined;
    if (attachment.type === "image") {
      return [{ type: "image", name: attachment.name, media_type: attachment.mediaType, base64: attachment.base64 }];
    }
    return [{ type: "document", name: attachment.name, media_type: attachment.mediaType, text: attachment.text }];
  }

  function clearHistoryUI() {
    historyList.replaceChildren();
    historySection.hidden = true;
    historyEmpty.hidden = true;
  }
  function clearProjectsUI() {
    projects = [];
    projectsReady = false;
    activeProject = null;
    activeProjectFileCount = 0;
    projectsList.replaceChildren();
    projectsSection.hidden = true;
    projectsEmpty.hidden = true;
    projectsNavButton.disabled = true;
    projectsNavButton.setAttribute("aria-disabled", "true");
    projectsBadge.textContent = authState.authenticated ? "설정 필요" : "로그인 후";
    renderProjectState();
  }
  function renderProjectState() {
    projectBanner.hidden = !activeProject;
    activeProjectName.textContent = activeProject ? activeProject.name : "";
    activeProjectFiles.hidden = !activeProject || activeProjectFileCount < 1;
    activeProjectFiles.textContent = activeProjectFileCount > 0 ? `파일 ${activeProjectFileCount}개` : "";
    projectsList.querySelectorAll(".project-item").forEach((button) => {
      button.setAttribute("aria-current", activeProject && button.dataset.projectId === activeProject.id ? "true" : "false");
    });
    if (!selectedAttachment) setNote(idleNote());
  }
  function renderProjects() {
    projectsList.replaceChildren();
    projectsSection.hidden = !projectsReady;
    projectsEmpty.hidden = !projectsReady || projects.length !== 0;
    projects.forEach((project) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "recent-item project-item";
      button.dataset.projectId = project.id;
      button.textContent = project.name;
      button.setAttribute("aria-current", activeProject && activeProject.id === project.id ? "true" : "false");
      button.addEventListener("click", () => selectProject(project));
      projectsList.appendChild(button);
    });
    projectsBadge.textContent = projects.length ? String(projects.length) : "새로 만들기";
  }
  async function loadProjects() {
    if (!authState.authenticated || !authState.history_ready) {
      clearProjectsUI();
      return false;
    }
    projectsNavButton.disabled = true;
    projectsNavButton.setAttribute("aria-disabled", "true");
    projectsBadge.textContent = "확인 중";
    try {
      const response = await fetch("/api/projects", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !Array.isArray(data.projects)) throw new Error("projects unavailable");
      projects = data.projects.filter((item) => item && typeof item.id === "string" && typeof item.name === "string");
      projectsReady = true;
      projectsNavButton.disabled = false;
      projectsNavButton.setAttribute("aria-disabled", "false");
      if (activeProject) activeProject = projects.find((item) => item.id === activeProject.id) || activeProject;
      renderProjects();
      return true;
    } catch (_) {
      clearProjectsUI();
      return false;
    }
  }
  function projectById(id) {
    return projects.find((project) => project.id === id) || null;
  }
  async function ensureProject(id) {
    if (!id) return null;
    const known = projectById(id);
    if (known) return known;
    if (!authState.authenticated || !projectsReady) return null;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.project || typeof data.project.id !== "string") return null;
      projects.unshift(data.project);
      renderProjects();
      return data.project;
    } catch (_) {
      return null;
    }
  }

  async function fetchProjectFiles(projectId) {
    if (!authState.authenticated || !authState.project_files_ready || !projectId) return [];
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/files`, { headers: { "Accept": "application/json" }, cache: "no-store" });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || !Array.isArray(data.files)) throw new Error("프로젝트 파일을 불러오지 못했습니다.");
    return data.files.filter((item) => item && typeof item.id === "string" && typeof item.name === "string");
  }
  async function refreshActiveProjectFileCount() {
    if (!activeProject || !authState.project_files_ready) {
      activeProjectFileCount = 0;
      renderProjectState();
      return;
    }
    try {
      const files = await fetchProjectFiles(activeProject.id);
      activeProjectFileCount = files.length;
    } catch (_) {
      activeProjectFileCount = 0;
    }
    renderProjectState();
  }
  function renderProjectFiles() {
    projectFilesList.replaceChildren();
    projectFilesEmpty.hidden = dialogProjectFiles.length !== 0;
    dialogProjectFiles.forEach((file) => {
      const row = document.createElement("div");
      row.className = "project-file-row";
      const copy = document.createElement("div");
      const strong = document.createElement("strong");
      strong.textContent = file.name;
      const small = document.createElement("small");
      small.textContent = `${file.media_type} · ${Number(file.content_chars || 0).toLocaleString()}자`;
      copy.append(strong, small);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "삭제";
      remove.addEventListener("click", () => deleteProjectFile(file.id, file.name));
      row.append(copy, remove);
      projectFilesList.appendChild(row);
    });
  }
  async function loadProjectFilesForDialog(projectId) {
    if (!projectId || !authState.project_files_ready) {
      dialogProjectFiles = [];
      renderProjectFiles();
      return;
    }
    try {
      dialogProjectFiles = await fetchProjectFiles(projectId);
      renderProjectFiles();
      if (activeProject && activeProject.id === projectId) {
        activeProjectFileCount = dialogProjectFiles.length;
        renderProjectState();
      }
    } catch (error) {
      projectFormError.textContent = error instanceof Error ? error.message : "프로젝트 파일을 불러오지 못했습니다.";
      projectFormError.hidden = false;
    }
  }
  async function addProjectFile(file) {
    if (!file || !editingProjectId || !authState.project_files_ready) return;
    projectFileInput.value = "";
    try {
      const documentFile = await readDocumentFile(file);
      const response = await fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.file) {
        const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "프로젝트 파일을 저장하지 못했습니다.";
        throw new Error(message);
      }
      await loadProjectFilesForDialog(editingProjectId);
    } catch (error) {
      projectFormError.textContent = error instanceof Error ? error.message : "프로젝트 파일을 저장하지 못했습니다.";
      projectFormError.hidden = false;
    }
  }
  async function deleteProjectFile(fileId, name) {
    if (!editingProjectId || !authState.project_files_ready) return;
    const confirmed = window.confirm(`‘${name}’ 파일을 프로젝트에서 삭제할까요?`);
    if (!confirmed) return;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files/${encodeURIComponent(fileId)}`, { method: "DELETE" });
      if (!response.ok) throw new Error("프로젝트 파일을 삭제하지 못했습니다.");
      await loadProjectFilesForDialog(editingProjectId);
    } catch (error) {
      projectFormError.textContent = error instanceof Error ? error.message : "프로젝트 파일을 삭제하지 못했습니다.";
      projectFormError.hidden = false;
    }
  }

  function resetConversation(preserveProject = true) {
    conversationEpoch += 1;
    if (activeRequestController) {
      activeRequestController.abort();
      activeRequestController = null;
    }
    inFlight = false;
    messages = [];
    conversationSkill = "auto";
    conversationId = null;
    if (!preserveProject) {
      activeProject = null;
      activeProjectFileCount = 0;
    }
    clearAttachment();
    messageList.replaceChildren();
    messageList.hidden = true;
    emptyState.hidden = false;
    shell.dataset.state = "home";
    input.value = "";
    renderProjectState();
    updateComposer();
    closeSidebar();
    input.focus();
  }
  function selectProject(project) {
    if (!projectsReady || !project || inFlight) return;
    activeProject = project;
    activeProjectFileCount = 0;
    resetConversation(true);
    refreshActiveProjectFileCount();
  }
  function exitProject() {
    if (inFlight) return;
    activeProject = null;
    activeProjectFileCount = 0;
    resetConversation(false);
  }
  function openProjectDialog(project = null) {
    if (!projectsReady || !authState.authenticated || inFlight) return;
    editingProjectId = project ? project.id : null;
    projectDialogTitle.textContent = project ? "프로젝트 지침·파일" : "새 프로젝트";
    projectNameInput.value = project ? project.name : "";
    projectInstructionsInput.value = project && typeof project.instructions === "string" ? project.instructions : "";
    projectFormError.textContent = "";
    projectFormError.hidden = true;
    projectSaveButton.disabled = false;
    projectFilesPanel.hidden = !(project && authState.project_files_ready);
    dialogProjectFiles = [];
    renderProjectFiles();
    projectDialog.showModal();
    if (project && authState.project_files_ready) loadProjectFilesForDialog(project.id);
    projectNameInput.focus();
  }
  function closeProjectDialog() {
    if (projectDialog.open) projectDialog.close();
    editingProjectId = null;
    dialogProjectFiles = [];
    projectFileInput.value = "";
    projectFormError.textContent = "";
    projectFormError.hidden = true;
  }
  async function saveProject(event) {
    event.preventDefault();
    if (!projectsReady || !authState.authenticated) return;
    const name = projectNameInput.value.trim();
    const instructions = projectInstructionsInput.value.trim();
    if (!name) {
      projectFormError.textContent = "프로젝트 이름을 입력해 주세요.";
      projectFormError.hidden = false;
      return;
    }
    projectSaveButton.disabled = true;
    projectFormError.hidden = true;
    try {
      const editing = Boolean(editingProjectId);
      const url = editing ? `/api/projects/${encodeURIComponent(editingProjectId)}` : "/api/projects";
      const response = await fetch(url, {
        method: editing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ name, instructions }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.project) {
        const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "프로젝트를 저장하지 못했습니다.";
        throw new Error(message);
      }
      const saved = data.project;
      const index = projects.findIndex((item) => item.id === saved.id);
      if (index >= 0) projects[index] = saved; else projects.unshift(saved);
      if (activeProject && activeProject.id === saved.id) activeProject = saved;
      renderProjects();
      renderProjectState();
      closeProjectDialog();
      if (!editing) selectProject(saved);
    } catch (error) {
      projectFormError.textContent = error instanceof Error ? error.message : "프로젝트를 저장하지 못했습니다.";
      projectFormError.hidden = false;
      projectSaveButton.disabled = false;
    }
  }

  function applyAuthState(data) {
    authState = data && typeof data === "object" ? data : { ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false };
    const ready = authState.ready === true;
    const authenticated = ready && authState.authenticated === true;
    loginButton.disabled = !ready;
    loginButton.setAttribute("aria-disabled", ready ? "false" : "true");
    if (!ready) {
      loginButton.textContent = "로그인";
      loginButton.title = "로그인 기능이 설정되지 않았습니다";
      accountName.hidden = true;
      accountName.textContent = "";
      clearHistoryUI();
      clearProjectsUI();
      return;
    }
    if (authenticated) {
      loginButton.textContent = "로그아웃";
      loginButton.title = "현재 계정에서 로그아웃합니다";
      const name = authState.user && typeof authState.user.name === "string" ? authState.user.name : "";
      accountName.textContent = name;
      accountName.hidden = !name;
      historySection.hidden = false;
      projectsBadge.textContent = "확인 중";
    } else {
      loginButton.textContent = "로그인";
      loginButton.title = "Google 계정으로 로그인합니다";
      accountName.hidden = true;
      accountName.textContent = "";
      clearHistoryUI();
      clearProjectsUI();
    }
  }
  async function loadRecentConversations() {
    if (!authState.authenticated || !authState.history_ready) {
      clearHistoryUI();
      return;
    }
    try {
      const response = await fetch("/api/conversations", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !Array.isArray(data.conversations)) throw new Error("history unavailable");
      historyList.replaceChildren();
      historySection.hidden = false;
      historyEmpty.hidden = data.conversations.length !== 0;
      data.conversations.forEach((conversation) => {
        if (!conversation || typeof conversation.id !== "string" || typeof conversation.title !== "string") return;
        const row = document.createElement("div");
        row.className = "history-row";
        const button = document.createElement("button");
        button.type = "button";
        button.className = "recent-item history-item";
        button.textContent = conversation.title;
        button.addEventListener("click", () => openSavedConversation(conversation.id));
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "history-delete";
        remove.textContent = "삭제";
        remove.setAttribute("aria-label", `‘${conversation.title}’ 대화 삭제`);
        remove.addEventListener("click", () => deleteConversation(conversation.id, conversation.title));
        row.append(button, remove);
        historyList.appendChild(row);
      });
    } catch (_) {
      clearHistoryUI();
    }
  }
  async function deleteConversation(id, title) {
    if (!authState.authenticated || inFlight) return;
    const confirmed = window.confirm(`‘${title}’ 대화를 삭제할까요?\n삭제한 대화는 되돌릴 수 없습니다.`);
    if (!confirmed) return;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.deleted !== true || data.conversation_id !== id) {
        const message = data && data.error && typeof data.error.message === "string"
          ? data.error.message
          : "대화를 삭제하지 못했습니다.";
        throw new Error(message);
      }
      const deletedActiveConversation = conversationId === id;
      if (deletedActiveConversation) resetConversation(true);
      await loadRecentConversations();
      if (!deletedActiveConversation) setNote(idleNote());
    } catch (error) {
      setNote(error instanceof Error ? error.message : "대화를 삭제하지 못했습니다.", "error");
    }
  }
  async function loadAuthStatus() {
    try {
      const response = await fetch("/api/auth/status", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data) throw new Error("auth status unavailable");
      applyAuthState(data);
      if (authState.authenticated) {
        await loadProjects();
        await loadRecentConversations();
      }
    } catch (_) {
      applyAuthState({ ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false });
    }
  }
  async function openSavedConversation(id) {
    if (!authState.authenticated || inFlight) return;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.conversation || !Array.isArray(data.conversation.messages)) throw new Error("저장된 대화를 불러오지 못했습니다.");
      const savedProjectId = typeof data.conversation.project_id === "string" ? data.conversation.project_id : null;
      const restoredProject = savedProjectId ? await ensureProject(savedProjectId) : null;
      if (savedProjectId && !restoredProject) throw new Error("이 대화의 프로젝트를 불러오지 못했습니다.");
      clearAttachment();
      messageList.replaceChildren();
      messages = [];
      conversationSkill = "auto";
      conversationId = data.conversation.id;
      activeProject = restoredProject;
      activeProjectFileCount = 0;
      renderProjectState();
      if (activeProject) refreshActiveProjectFileCount();
      showConversation();
      data.conversation.messages.forEach((item) => {
        if (!item || typeof item.content !== "string") return;
        if (item.role === "user") addUserMessage(item.content, null);
        if (item.role === "assistant") renderStoredAssistant(item.content);
        if (item.role === "user" || item.role === "assistant") messages.push({ role: item.role, content: item.content });
      });
      messages = messages.slice(-20);
      closeSidebar();
      input.focus();
    } catch (error) {
      setNote(error instanceof Error ? error.message : "저장된 대화를 불러오지 못했습니다.", "error");
    }
  }

  async function requestCompletedAnswer(article, payload, outboundMessages, attachment, contextSnapshot, signal) {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data || typeof data.answer !== "string") {
      const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.";
      throw new Error(message);
    }
    renderAnswer(article, data);
    messages = outboundMessages.concat([{ role: "assistant", content: data.answer }]).slice(-20);
    if (typeof data.conversation_id === "string") conversationId = data.conversation_id;
    if (typeof data.project_id === "string") {
      const resolvedProject = projectById(data.project_id) || contextSnapshot.project;
      if (resolvedProject) activeProject = resolvedProject;
    }
    renderProjectState();
    if (authState.authenticated) {
      loadRecentConversations();
      if (projectsReady) loadProjects();
    }
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return true;
  }

  function applyStreamDone(article, data, answer, outboundMessages, contextSnapshot) {
    messages = outboundMessages.concat([{ role: "assistant", content: answer }]).slice(-20);
    if (typeof data.conversation_id === "string") conversationId = data.conversation_id;
    if (typeof data.project_id === "string") {
      const snapshotProject = contextSnapshot.project && contextSnapshot.project.id === data.project_id ? contextSnapshot.project : null;
      const boundedProject = data.project && data.project.id === data.project_id && typeof data.project.name === "string" ? data.project : null;
      const resolvedProject = projectById(data.project_id) || snapshotProject || boundedProject;
      if (resolvedProject) activeProject = resolvedProject;
    }
    if (Number.isInteger(data.project_files_used) && data.project_files_used > 0) {
      const used = document.createElement("small");
      used.className = "reference-note";
      used.textContent = `프로젝트 파일 ${data.project_files_used}개를 참고했습니다.`;
      article.querySelector(".assistant-content").appendChild(used);
    }
    renderProjectState();
    if (authState.authenticated) {
      loadRecentConversations();
      if (projectsReady) loadProjects();
    }
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function requestStreamingAnswer(article, payload, outboundMessages, skill, contextSnapshot, signal) {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify(payload),
      signal,
    });
    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    if (!response.ok || !contentType.startsWith("text/event-stream")) {
      const data = await response.json().catch(() => null);
      const message = data && data.error && typeof data.error.message === "string"
        ? data.error.message
        : "AI 연결이 잠시 불안정합니다. 다시 시도해 주세요.";
      throw new Error(message);
    }

    let answer = "";
    let paragraph = null;
    let done = false;
    let terminalError = false;
    try {
      await readSseEvents(response, async (frame) => {
        if (!["delta", "done", "error"].includes(frame.event)) return false;
        let data;
        try {
          data = JSON.parse(frame.data);
        } catch (_) {
          throw new Error("AI 스트리밍 응답 형식을 확인할 수 없습니다.");
        }
        if (frame.event === "delta") {
          if (!data || typeof data.delta !== "string") throw new Error("AI 스트리밍 응답 형식을 확인할 수 없습니다.");
          if (!data.delta) return false;
          if (!paragraph) {
            const content = article.querySelector(".assistant-content");
            content.replaceChildren();
            paragraph = document.createElement("p");
            content.appendChild(paragraph);
            article.querySelector("[data-runtime-label]").textContent = "AI 응답";
          }
          answer += data.delta;
          paragraph.textContent = answer;
          return false;
        }
        if (frame.event === "error") {
          const message = data && data.error && typeof data.error.message === "string"
            ? data.error.message
            : "스트리밍 답변을 계속하지 못했습니다. 다시 시도해 주세요.";
          if (!paragraph) throw new Error(message);
          terminalError = true;
          renderStreamError(article, message, outboundMessages, skill, contextSnapshot);
          return true;
        }
        if (!data || data.done !== true || !paragraph || !answer) throw new Error("AI 스트리밍 응답이 정상적으로 완료되지 않았습니다.");
        if (done) throw new Error("AI 스트리밍 완료 신호가 중복되었습니다.");
        done = true;
        applyStreamDone(article, data, answer, outboundMessages, contextSnapshot);
        return true;
      });
      if (done) return true;
      if (terminalError) return false;
      throw new Error("AI 스트리밍 응답이 완료되지 않았습니다. 다시 시도해 주세요.");
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      if (paragraph) {
        renderStreamError(article, error instanceof Error ? error.message : "스트리밍 답변을 계속하지 못했습니다. 다시 시도해 주세요.", outboundMessages, skill, contextSnapshot);
        return false;
      }
      throw error;
    }
  }

  async function requestAnswer(outboundMessages, skill, attachment, contextSnapshot) {
    if (inFlight) return false;
    inFlight = true;
    const requestEpoch = conversationEpoch;
    const controller = new AbortController();
    activeRequestController = controller;
    updateComposer();
    const article = addAssistantShell("답변 준비 중");
    renderTyping(article);
    try {
      const payload = { messages: outboundMessages, mode: "auto", skill };
      const attachments = attachmentPayload(attachment);
      if (attachments) payload.attachments = attachments;
      if (contextSnapshot.conversationId) payload.conversation_id = contextSnapshot.conversationId;
      if (contextSnapshot.project) payload.project_id = contextSnapshot.project.id;
      if (attachments) {
        return await requestCompletedAnswer(article, payload, outboundMessages, attachment, contextSnapshot, controller.signal);
      }
      return await requestStreamingAnswer(article, payload, outboundMessages, skill, contextSnapshot, controller.signal);
    } catch (error) {
      if ((error && error.name === "AbortError") || requestEpoch !== conversationEpoch) return false;
      renderError(article, error instanceof Error ? error.message : "다시 시도해 주세요.", outboundMessages, skill, attachment, contextSnapshot);
      return false;
    } finally {
      if (activeRequestController === controller) {
        activeRequestController = null;
        inFlight = false;
        updateComposer();
        input.focus();
      }
    }
  }
  async function submitPrompt(text, selectedSkill) {
    const prompt = text.trim();
    if (!prompt || inFlight) return;
    if (selectedSkill) conversationSkill = selectedSkill;
    const attachmentSnapshot = selectedAttachment;
    const contextSnapshot = { conversationId, project: activeProject };
    showConversation();
    addUserMessage(prompt, attachmentSnapshot);
    input.value = "";
    const outbound = messages.concat([{ role: "user", content: prompt }]).slice(-20);
    const success = await requestAnswer(outbound, conversationSkill, attachmentSnapshot, contextSnapshot);
    if (success && selectedAttachment === attachmentSnapshot) clearAttachment();
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

  input.addEventListener("input", updateComposer);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sendButton.disabled) form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => { event.preventDefault(); submitPrompt(input.value); });
  attachmentButton.addEventListener("click", () => { if (!inFlight) attachmentFileInput.click(); });
  documentStarterButton.addEventListener("click", () => { if (!inFlight) attachmentFileInput.click(); });
  attachmentFileInput.addEventListener("change", () => {
    const [file] = attachmentFileInput.files || [];
    selectAttachment(file);
  });
  removeAttachment.addEventListener("click", clearAttachment);
  projectsNavButton.addEventListener("click", () => {
    if (!projectsReady) return;
    if (projects.length === 0) openProjectDialog();
    else projectsSection.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
  projectCreateButton.addEventListener("click", () => openProjectDialog());
  editProjectButton.addEventListener("click", () => { if (activeProject) openProjectDialog(activeProject); });
  exitProjectButton.addEventListener("click", exitProject);
  projectDialogClose.addEventListener("click", closeProjectDialog);
  projectDialogCancel.addEventListener("click", closeProjectDialog);
  projectForm.addEventListener("submit", saveProject);
  projectFileInput.addEventListener("change", () => {
    const [file] = projectFileInput.files || [];
    addProjectFile(file);
  });
  projectDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeProjectDialog();
  });
  loginButton.addEventListener("click", async () => {
    if (!authState.ready) return;
    if (!authState.authenticated) {
      window.location.assign("/auth/google/start");
      return;
    }
    try {
      await fetch("/api/auth/logout", { method: "POST", headers: { "Accept": "application/json" } });
    } finally {
      resetConversation(false);
      clearProjectsUI();
      await loadAuthStatus();
    }
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
    submitPrompt(button.dataset.prompt || "", button.dataset.skill || "auto");
    closeSidebar();
  }));
  newChatButton.addEventListener("click", () => resetConversation(true));
  mobileMenu.addEventListener("click", openSidebar);
  mobileClose.addEventListener("click", closeSidebar);
  sidebarScrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && shell.classList.contains("sidebar-open")) closeSidebar();
  });

  setNote(DEFAULT_NOTE);
  renderProjectState();
  updateComposer();
  loadAuthStatus();
})();