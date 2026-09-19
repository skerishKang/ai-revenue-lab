(() => {
  "use strict";
  const shell = document.querySelector(".app-shell");
  const emptyState = document.getElementById("emptyState");
  const messageList = document.getElementById("messageList");
  const form = document.getElementById("composerForm");
  const input = document.getElementById("messageInput");
  const sendButton = document.getElementById("sendButton");
  const cancelStreamButton = document.getElementById("cancelStreamButton");
  const newChatButton = document.getElementById("newChatButton");
  const mobileMenu = document.getElementById("mobileMenu");
  const mobileClose = document.getElementById("mobileClose");
  const sidebarScrim = document.getElementById("sidebarScrim");
  const settingsButton = document.getElementById("settingsButton");
  const settingsDialog = document.getElementById("settingsDialog");
  const settingsCloseButton = document.getElementById("settingsCloseButton");
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
  const authDialog = document.getElementById("authDialog");
  const authDialogClose = document.getElementById("authDialogClose");
  const googleLoginButton = document.getElementById("googleLoginButton");
  const authDivider = document.getElementById("authDivider");
  const passwordLoginForm = document.getElementById("passwordLoginForm");
  const passwordLoginIdentifier = document.getElementById("passwordLoginIdentifier");
  const passwordLoginPassword = document.getElementById("passwordLoginPassword");
  const passwordLoginError = document.getElementById("passwordLoginError");
  const passwordLoginSubmit = document.getElementById("passwordLoginSubmit");
  const passwordRegisterSection = document.getElementById("passwordRegisterSection");
  const passwordRegisterForm = document.getElementById("passwordRegisterForm");
  const passwordRegisterUsername = document.getElementById("passwordRegisterUsername");
  const passwordRegisterEmail = document.getElementById("passwordRegisterEmail");
  const passwordRegisterName = document.getElementById("passwordRegisterName");
  const passwordRegisterPassword = document.getElementById("passwordRegisterPassword");
  const passwordRegisterError = document.getElementById("passwordRegisterError");
  const passwordRegisterSubmit = document.getElementById("passwordRegisterSubmit");
  const accountName = document.getElementById("accountName");
  const accountContainer = document.querySelector(".sidebar-account");
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
  const projectFormActions = projectForm.querySelector(".project-form-actions");
  const projectDeleteButton = document.createElement("button");
  projectDeleteButton.id = "projectDeleteButton";
  projectDeleteButton.type = "button";
  projectDeleteButton.className = "project-danger";
  projectDeleteButton.textContent = uiT("project-delete");
  projectDeleteButton.hidden = true;
  projectDeleteButton.setAttribute("aria-label", uiT("project-delete-aria"));
  projectFormActions.prepend(projectDeleteButton);
  const projectFilesPanel = document.getElementById("projectFilesPanel");
  const projectFileInput = document.getElementById("projectFileInput");
  const projectFilesList = document.getElementById("projectFilesList");
  const projectFilesEmpty = document.getElementById("projectFilesEmpty");
  const projectFileStatus = document.getElementById("projectFileStatus");
  const chatTransport = window.PadiemChatTransport;
  const conversationState = window.PadiemChatConversationState;
  const MESSAGE_LIFECYCLE = window.PadiemChatLifecycle.states;
  const attachmentCapabilities = window.PadiemAttachmentCapabilities;
  const binaryDocuments = window.PadiemBinaryDocuments;

  const PROJECT_BINARY_EXTENSION_MEDIA = new Map([
    [".pdf", "application/pdf"],
    [".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"],
  ]);

  const MAX_IMAGE_BYTES = attachmentCapabilities.limits.imageBytes;
  const MAX_DOCUMENT_BYTES = attachmentCapabilities.limits.textBytes;
  const MAX_DOCUMENT_CHARS = attachmentCapabilities.limits.textChars;
  const ALLOWED_IMAGE_TYPES = new Set(attachmentCapabilities.images.flatMap((format) => format.mediaTypes));
  const ALLOWED_DOCUMENT_TYPES = new Set(attachmentCapabilities.textDocuments.flatMap((format) => format.mediaTypes));
  const DOCUMENT_EXTENSION_TYPES = new Map(
    attachmentCapabilities.textDocuments.flatMap((format) => format.extensions.map((extension) => [extension, format.mediaTypes[0]]))
  );

  let inFlight = false;
  let activeRequestController = null;
  let activeRequestArticle = null;
  let activeRequestCancelReason = null;
  let conversationEpoch = 0;
  let selectedAttachment = null;
  let authState = { ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false };
  let projects = [];
  let projectsReady = false;
  let activeProject = null;
  let activeProjectFileCount = 0;
  let editingProjectId = null;
  let dialogProjectFiles = [];


  function uiT(key, variables = null) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const value = window.__padiemLocale.text(key, variables);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return key;
  }
  function attachmentCopy() {
    return attachmentCapabilities.copy(document.documentElement.lang);
  }
  function idleNote() {
    return activeProject ? uiT("active-project-note", { name: activeProject.name }) : attachmentCopy().idleNote;
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
    cancelStreamButton.hidden = !inFlight;
    cancelStreamButton.disabled = !inFlight;
    cancelStreamButton.setAttribute("aria-disabled", inFlight ? "false" : "true");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  }
  function lifecycleForError(error) {
    return error && error.code === "upstream_timeout" ? MESSAGE_LIFECYCLE.TIMED_OUT : MESSAGE_LIFECYCLE.FAILED;
  }
  function setNavActive() {
    const state = shell.dataset.state;
    const workspace = document.getElementById("clawWorkspace");
    if (workspace) workspace.hidden = state !== "claw";
    const modeBar = document.getElementById("clawManualForm");
    if (modeBar) modeBar.hidden = !(state === "claw" && workspace && workspace.dataset.view === "manual");
    syncComposerForClaw(state === "claw");
    const chatNav = document.getElementById("newChatButton");
    const clawNav = document.getElementById("clawNavButton");
    const tasksNav = document.getElementById("tasksNavButton");
    const alertsNav = document.getElementById("alertsNavButton");
    const inboxKind = workspace && workspace.dataset.view === "inbox" ? workspace.dataset.inboxKind : "";
    if (chatNav) chatNav.setAttribute("aria-current", state === "claw" ? "false" : "page");
    if (clawNav) clawNav.setAttribute("aria-current", state === "claw" && !inboxKind ? "page" : "false");
    if (tasksNav) tasksNav.setAttribute("aria-current", state === "claw" && inboxKind === "tasks" ? "page" : "false");
    if (alertsNav) alertsNav.setAttribute("aria-current", state === "claw" && inboxKind === "alerts" ? "page" : "false");
  }
  function showConversation() {
    emptyState.hidden = true;
    messageList.hidden = false;
    shell.dataset.state = "chat";
    setNavActive();
  }
  function addUserMessage(text, attachment) {
    const fragment = document.getElementById("userMessageTemplate").content.cloneNode(true);
    const bubble = fragment.querySelector(".message-bubble");
    bubble.textContent = text;
    if (attachment) {
      const meta = document.createElement("span");
      meta.className = "message-attachment-meta";
      const label = attachment.type === "image" ? uiT("attachment-photo") : uiT("attachment-document");
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
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.STREAMING);
    return article;
  }
  function renderTyping(article) {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const typing = document.createElement("span");
    typing.className = "typing";
    typing.setAttribute("aria-label", uiT("answer-preparing"));
    typing.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
    content.appendChild(typing);
  }
  function renderStoredAssistant(text) {
    const article = addAssistantShell(uiT("stored-conversation"));
    const content = article.querySelector(".assistant-content");
    const paragraph = document.createElement("p");
    paragraph.textContent = text;
    content.appendChild(paragraph);
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED);
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
      used.textContent = uiT("project-files-used", { count: result.project_files_used });
      content.appendChild(used);
    }
    const skillTitle = result.skill && result.skill.id !== "auto" && typeof result.skill.title === "string" ? result.skill.title : "";
    const runtimeLabel = result.runtime === "mock" ? uiT("mock-response") : uiT("ai-response");
    article.querySelector("[data-runtime-label]").textContent = skillTitle ? `${runtimeLabel} · ${skillTitle}` : runtimeLabel;
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED);
  }
  function buildRetryBox(message, article, retryMessages, retrySkill, retryAttachment, retryContext, actionLabel = uiT("retry")) {
    const box = document.createElement("div");
    box.className = "error-box";
    const strong = document.createElement("strong");
    strong.textContent = uiT("answer-load-failed");
    const p = document.createElement("p");
    p.textContent = message || uiT("try-again");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "retry-button";
    retry.textContent = actionLabel;
    retry.addEventListener("click", async () => {
      article.remove();
      conversationState.setConversationId(retryContext.conversationId);
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
  function renderError(article, message, retryMessages, retrySkill, retryAttachment, retryContext, lifecycle = MESSAGE_LIFECYCLE.FAILED) {
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    article.querySelector("[data-runtime-label]").textContent = lifecycle === MESSAGE_LIFECYCLE.TIMED_OUT ? uiT("timeout") : uiT("connection-error");
    content.appendChild(buildRetryBox(message, article, retryMessages, retrySkill, retryAttachment, retryContext));
    PadiemChatLifecycle.set(article, lifecycle);
    revealErrorState(article);
  }
  function renderStreamError(article, message, retryMessages, retrySkill, retryContext, lifecycle = MESSAGE_LIFECYCLE.FAILED) {
    const content = article.querySelector(".assistant-content");
    const typing = content.querySelector(".typing");
    if (typing) typing.remove();
    article.querySelector("[data-runtime-label]").textContent = lifecycle === MESSAGE_LIFECYCLE.TIMED_OUT ? uiT("timeout") : uiT("connection-error");
    content.appendChild(buildRetryBox(message, article, retryMessages, retrySkill, null, retryContext));
    PadiemChatLifecycle.set(article, lifecycle);
    revealErrorState(article);
  }
  function renderCancelled(article, retryMessages, retrySkill, retryContext) {
    const content = article.querySelector(".assistant-content");
    const typing = content.querySelector(".typing");
    if (typing) typing.remove();
    article.querySelector("[data-runtime-label]").textContent = uiT("generation-cancelled");
    content.appendChild(buildRetryBox(uiT("generation-cancelled-copy"), article, retryMessages, retrySkill, null, retryContext, uiT("regenerate")));
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.CANCELLED);
    revealErrorState(article);
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
      setNote(uiT("attachment-image-note"));
    } else {
      attachmentThumb.removeAttribute("src");
      attachmentThumb.hidden = true;
      attachmentKind.hidden = false;
      attachmentKind.textContent = extensionOf(selectedAttachment.name).replace(".", "").toUpperCase() || "DOC";
      setNote(uiT("attachment-document-note"));
    }
    attachmentName.textContent = selectedAttachment.name;
    attachmentSize.textContent = formatBytes(selectedAttachment.byteSize);
    attachmentTray.hidden = false;
  }
  function readAsDataUrl(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(reader.result), { once: true });
      reader.addEventListener("error", () => reject(new Error(uiT("image-read-failed"))), { once: true });
      reader.readAsDataURL(file);
    });
  }
  function readAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(reader.result), { once: true });
      reader.addEventListener("error", () => reject(new Error(uiT("document-read-failed"))), { once: true });
      reader.readAsText(file, "UTF-8");
    });
  }
  async function readDocumentFile(file) {
    const mediaType = documentMediaType(file);
    if (!mediaType) throw new Error(attachmentCopy().unsupportedFormat);
    if (file.size < 1 || file.size > MAX_DOCUMENT_BYTES) throw new Error(attachmentCopy().textTooLarge);
    const raw = await readAsText(file);
    if (typeof raw !== "string") throw new Error(uiT("document-read-failed"));
    const text = raw.replace(/^\uFEFF/, "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    if (!text.trim()) throw new Error(uiT("empty-document"));
    if (text.length > MAX_DOCUMENT_CHARS) throw new Error(attachmentCopy().textTooLong);
    if (text.includes("\u0000")) throw new Error(uiT("binary-document"));
    return { type: "document", name: file.name || "document.txt", mediaType, text, byteSize: file.size };
  }
  async function selectImage(file) {
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) throw new Error(attachmentCopy().unsupportedFormat);
    if (file.size < 1 || file.size > MAX_IMAGE_BYTES) throw new Error(attachmentCopy().imageTooLarge);
    const dataUrl = await readAsDataUrl(file);
    const expectedPrefix = `data:${file.type};base64,`;
    if (typeof dataUrl !== "string" || !dataUrl.startsWith(expectedPrefix)) throw new Error(uiT("image-format-invalid"));
    const base64 = dataUrl.slice(expectedPrefix.length);
    if (!base64) throw new Error(uiT("image-data-empty"));
    return { type: "image", name: file.name || "image", mediaType: file.type, base64, byteSize: file.size, previewUrl: URL.createObjectURL(file) };
  }
  async function selectAttachment(file) {
    if (!file) return;
    try {
      let next;
      if (ALLOWED_IMAGE_TYPES.has(file.type)) next = await selectImage(file);
      else if (binaryDocuments && typeof binaryDocuments.canRead === "function" && binaryDocuments.canRead(file)) next = await binaryDocuments.read(file);
      else next = await readDocumentFile(file);
      if (selectedAttachment && selectedAttachment.previewUrl) URL.revokeObjectURL(selectedAttachment.previewUrl);
      selectedAttachment = next;
      renderSelectedAttachment();
    } catch (error) {
      attachmentFileInput.value = "";
      setNote(error instanceof Error ? error.message : uiT("file-read-failed"), "error");
    }
  }
  function attachmentPayload(attachment) {
    if (!attachment) return undefined;
    if (attachment.type === "image") {
      return [{ type: "image", name: attachment.name, media_type: attachment.mediaType, base64: attachment.base64 }];
    }
    if (typeof attachment.base64 === "string" && attachment.base64) {
      return [{ type: "document", name: attachment.name, media_type: attachment.mediaType, base64: attachment.base64 }];
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
    projectsBadge.textContent = authState.authenticated ? uiT("setup-needed") : uiT("login-after");
    renderProjectState();
  }
  function renderProjectState() {
    projectBanner.hidden = !activeProject;
    activeProjectName.textContent = activeProject ? activeProject.name : "";
    activeProjectFiles.hidden = !activeProject || activeProjectFileCount < 1;
    activeProjectFiles.textContent = activeProjectFileCount > 0 ? uiT("project-files-count", { count: activeProjectFileCount }) : "";
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
      const row = document.createElement("div");
      row.className = "project-row";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "recent-item project-item";
      button.dataset.projectId = project.id;
      button.textContent = project.name;
      button.setAttribute("aria-current", activeProject && activeProject.id === project.id ? "true" : "false");
      button.addEventListener("click", () => selectProject(project));
      const manage = document.createElement("button");
      manage.type = "button";
      manage.className = "project-manage";
      manage.textContent = uiT("manage");
      manage.setAttribute("aria-label", uiT("project-manage-aria", { name: project.name }));
      manage.addEventListener("click", () => openProjectDialog(project));
      row.append(button, manage);
      projectsList.appendChild(row);
    });
    projectsBadge.textContent = projects.length ? String(projects.length) : uiT("create-new");
  }
  async function loadProjects() {
    if (!authState.authenticated || !authState.history_ready) {
      clearProjectsUI();
      return false;
    }
    projectsNavButton.disabled = true;
    projectsNavButton.setAttribute("aria-disabled", "true");
    projectsBadge.textContent = uiT("checking");
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
    if (!response.ok || !data || !Array.isArray(data.files)) throw new Error(uiT("project-files-load-failed"));
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
      small.textContent = `${file.media_type} · ${uiT("character-count", { count: Number(file.content_chars || 0).toLocaleString() })}`;
      copy.append(strong, small);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = uiT("delete");
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
      projectFormError.textContent = error instanceof Error ? error.message : uiT("project-files-load-failed");
      projectFormError.hidden = false;
    }
  }
  function projectBinaryMediaType(file) {
    // Project-scoped subset preflight: PDF/DOCX only (the server allow-lists exactly these two
    // binaries). Extension-driven to mirror document-binary.js canRead/canonicalMediaType, which
    // are themselves extension-canonical. Everything else — PPTX/XLSX and unsupported text types —
    // falls through to the text path and is rejected there BEFORE any request is made.
    return PROJECT_BINARY_EXTENSION_MEDIA.get(extensionOf(file && file.name)) || null;
  }
  let projectFileBusy = false;
  function setProjectFileBusy(busy) {
    projectFileBusy = busy;
    if (busy) {
      projectFilesPanel.setAttribute("aria-busy", "true");
      projectFileInput.setAttribute("aria-disabled", "true");
      if (projectFileStatus) { projectFileStatus.textContent = uiT("document-saving"); projectFileStatus.hidden = false; }
    } else {
      projectFilesPanel.removeAttribute("aria-busy");
      projectFileInput.removeAttribute("aria-disabled");
      if (projectFileStatus) { projectFileStatus.hidden = true; projectFileStatus.textContent = ""; }
    }
  }
  async function addProjectFile(file) {
    if (!file || !editingProjectId || !authState.project_files_ready) return;
    projectFileInput.value = "";
    if (projectFileBusy) return;
    // Clear any stale error so a successful retry never leaves the old message up.
    projectFormError.hidden = true;
    projectFormError.textContent = "";
    setProjectFileBusy(true);
    try {
      const projectBinary = projectBinaryMediaType(file);
      let payload;
      if (projectBinary && binaryDocuments && typeof binaryDocuments.read === "function") {
        const documentFile = await binaryDocuments.read(file);
        payload = { name: documentFile.name, media_type: documentFile.mediaType, base64: documentFile.base64 };
      } else if (projectBinary) {
        throw new Error(attachmentCopy().unsupportedFormat);
      } else {
        const documentFile = await readDocumentFile(file);
        payload = { name: documentFile.name, media_type: documentFile.mediaType, text: documentFile.text };
      }
      const response = await fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.file) {
        const message = data && data.error && typeof data.error.message === "string" ? data.error.message : uiT("project-file-save-failed");
        throw new Error(message);
      }
      await loadProjectFilesForDialog(editingProjectId);
    } catch (error) {
      projectFormError.textContent = error instanceof Error ? error.message : uiT("project-file-save-failed");
      projectFormError.hidden = false;
    } finally {
      setProjectFileBusy(false);
    }
  }
  async function deleteProjectFile(fileId, name) {
    if (!editingProjectId || !authState.project_files_ready) return;
    const confirmed = await window.PadiemConfirmDialog.confirm({
      title: uiT("project-file-delete-title"),
      message: uiT("project-file-delete-message", { name }),
      cancelLabel: uiT("cancel"),
      confirmLabel: uiT("delete"),
    });
    if (!confirmed) return;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(editingProjectId)}/files/${encodeURIComponent(fileId)}`, { method: "DELETE" });
      if (!response.ok) throw new Error(uiT("project-file-delete-failed"));
      await loadProjectFilesForDialog(editingProjectId);
    } catch (error) {
      projectFormError.textContent = error instanceof Error ? error.message : uiT("project-file-delete-failed");
      projectFormError.hidden = false;
    }
  }

  function resetConversation(preserveProject = true) {
    conversationEpoch += 1;
    if (activeRequestController) {
      activeRequestCancelReason = "conversation_reset";
      activeRequestController.abort();
      activeRequestController = null;
      activeRequestArticle = null;
    }
    inFlight = false;
    conversationState.reset();
    if (!preserveProject) {
      activeProject = null;
      activeProjectFileCount = 0;
    }
    clearAttachment();
    messageList.replaceChildren();
    messageList.hidden = true;
    emptyState.hidden = false;
    shell.dataset.state = "home";
    setNavActive();
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
    projectDialogTitle.textContent = project ? uiT("project-edit-title") : uiT("project-new");
    projectNameInput.value = project ? project.name : "";
    projectInstructionsInput.value = project && typeof project.instructions === "string" ? project.instructions : "";
    projectFormError.textContent = "";
    projectFormError.hidden = true;
    projectSaveButton.disabled = false;
    projectDeleteButton.hidden = !project;
    projectDeleteButton.disabled = false;
    projectFilesPanel.hidden = !(project && authState.project_files_ready);
    dialogProjectFiles = [];
    renderProjectFiles();
    projectDialog.showModal();
    if (project && authState.project_files_ready) loadProjectFilesForDialog(project.id);
    projectNameInput.focus();
  }
  function closeProjectDialog() {
    if (projectDialog.open && typeof projectDialog.close === "function") projectDialog.close();
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
      projectFormError.textContent = uiT("project-name-required");
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
        const message = data && data.error && typeof data.error.message === "string" ? data.error.message : uiT("project-save-failed");
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
      projectFormError.textContent = error instanceof Error ? error.message : uiT("project-save-failed");
      projectFormError.hidden = false;
      projectSaveButton.disabled = false;
    }
  }

  async function deleteProject() {
    if (!editingProjectId || !projectsReady || !authState.authenticated || inFlight) return;
    const project = projectById(editingProjectId);
    if (!project) return;
    const confirmed = await window.PadiemConfirmDialog.confirm({
      title: uiT("project-delete-title"),
      message: uiT("project-delete-message", { name: project.name }),
      cancelLabel: uiT("cancel"),
      confirmLabel: uiT("delete"),
    });
    if (!confirmed) return;
    const deletingId = editingProjectId;
    const deletingActiveProject = Boolean(activeProject && activeProject.id === deletingId);
    projectDeleteButton.disabled = true;
    projectSaveButton.disabled = true;
    projectFormError.hidden = true;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(deletingId)}`, {
        method: "DELETE",
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.deleted !== true || data.project_id !== deletingId) {
        const message = data && data.error && typeof data.error.message === "string"
          ? data.error.message
          : uiT("project-delete-failed");
        throw new Error(message);
      }
      projects = projects.filter((item) => item.id !== deletingId);
      if (deletingActiveProject) {
        activeProject = null;
        activeProjectFileCount = 0;
      }
      renderProjects();
      renderProjectState();
      closeProjectDialog();
      await loadProjects();
      if (deletingActiveProject) {
        renderProjectState();
        setNote(idleNote());
      }
      input.focus();
    } catch (error) {
      projectFormError.textContent = error instanceof Error ? error.message : uiT("project-delete-failed");
      projectFormError.hidden = false;
      projectDeleteButton.disabled = false;
      projectSaveButton.disabled = false;
    }
  }

  function applyAuthState(data) {
    authState = data && typeof data === "object" ? data : { ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false };
    const ready = authState.ready === true;
    const authenticated = ready && authState.authenticated === true;
    const inboxNavButtons = [
      document.getElementById("tasksNavButton"),
      document.getElementById("alertsNavButton"),
    ].filter(Boolean);
    inboxNavButtons.forEach((button) => {
      button.disabled = !authenticated;
      button.setAttribute("aria-disabled", authenticated ? "false" : "true");
    });
    if (!authenticated) {
      const inbox = document.getElementById("clawInbox");
      const inboxList = document.getElementById("clawInboxList");
      const workspace = document.getElementById("clawWorkspace");
      const runHistory = document.getElementById("clawRunHistory");
      const runHistoryList = document.getElementById("clawRunHistoryList");
      const runHistoryError = document.getElementById("clawRunHistoryError");
      if (inbox) inbox.hidden = true;
      if (inboxList) inboxList.replaceChildren();
      if (runHistory) runHistory.hidden = true;
      if (runHistoryList) runHistoryList.replaceChildren();
      if (runHistoryError) {
        runHistoryError.hidden = true;
        runHistoryError.textContent = "";
        runHistoryError.removeAttribute("data-state");
      }
      if (workspace) {
        delete workspace.dataset.inboxKind;
        if (workspace.dataset.view === "inbox") workspace.dataset.view = "manual";
      }
    }
    const sessionState = !ready
      ? "unavailable"
      : authenticated
        ? "signed_in"
        : authState.session_state === "expired"
          ? "expired"
          : "guest";

    if (accountContainer) {
      accountContainer.dataset.accountState = sessionState;
      accountContainer.hidden = sessionState === "unavailable";
    }
    loginButton.hidden = sessionState === "unavailable";
    loginButton.disabled = !ready;
    syncAuthDialogMethods();
    loginButton.setAttribute("aria-disabled", ready ? "false" : "true");

    if (sessionState === "unavailable") {
      loginButton.textContent = uiT("login");
      loginButton.title = uiT("login-unavailable-title");
      accountName.hidden = true;
      accountName.textContent = "";
      clearHistoryUI();
      clearProjectsUI();
      return;
    }

    if (sessionState === "signed_in") {
      loginButton.textContent = uiT("logout");
      loginButton.title = uiT("logout-title");
      const name = authState.user && typeof authState.user.name === "string" ? authState.user.name.trim() : "";
      accountName.textContent = name || uiT("signed-in");
      accountName.hidden = false;
      historySection.hidden = false;
      projectsBadge.textContent = uiT("checking");
      return;
    }

    if (sessionState === "expired") {
      loginButton.textContent = uiT("sign-in-again");
      loginButton.title = uiT("expired-title");
      accountName.textContent = uiT("session-expired");
      accountName.hidden = false;
      clearHistoryUI();
      clearProjectsUI();
      return;
    }

    loginButton.textContent = uiT("login");
    loginButton.title = uiT("login-title");
    accountName.textContent = uiT("guest");
    accountName.hidden = false;
    clearHistoryUI();
    clearProjectsUI();
  }
  function authMethodEnabled(name) {
    return Boolean(authState && authState.methods && authState.methods[name] === true);
  }

  function setAuthFormError(node, message = "") {
    if (!node) return;
    node.textContent = message;
    node.hidden = !message;
  }

  function syncAuthDialogMethods() {
    if (!authDialog) return;
    const googleEnabled = authMethodEnabled("google");
    const passwordEnabled = authMethodEnabled("password");
    if (googleLoginButton) googleLoginButton.hidden = !googleEnabled;
    if (authDivider) authDivider.hidden = !(googleEnabled && passwordEnabled);
    if (passwordLoginForm) passwordLoginForm.hidden = !passwordEnabled;
    if (passwordRegisterSection) passwordRegisterSection.hidden = !passwordEnabled;
  }

  function openAuthDialog() {
    if (!authDialog) {
      if (authMethodEnabled("google")) window.location.assign("/auth/google/start");
      return;
    }
    syncAuthDialogMethods();
    setAuthFormError(passwordLoginError);
    setAuthFormError(passwordRegisterError);
    if (typeof authDialog.showModal === "function") {
      authDialog.showModal();
    } else {
      authDialog.setAttribute("open", "");
    }
    if (authMethodEnabled("password") && passwordLoginIdentifier) passwordLoginIdentifier.focus();
  }

  function closeAuthDialog() {
    if (!authDialog) return;
    if (typeof authDialog.close === "function") authDialog.close();
    else authDialog.removeAttribute("open");
  }

  async function passwordAuthRequest(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    let data = null;
    try {
      data = await response.json();
    } catch (_) {}
    if (!response.ok) {
      const message = data && data.error && typeof data.error.message === "string"
        ? data.error.message
        : uiT("auth-error-generic");
      const error = new Error(message);
      error.code = data && data.error && typeof data.error.code === "string" ? data.error.code : "auth_error";
      throw error;
    }
    return data;
  }

  async function submitPasswordLogin(event) {
    event.preventDefault();
    if (!authMethodEnabled("password") || !passwordLoginForm) return;
    setAuthFormError(passwordLoginError);
    passwordLoginSubmit.disabled = true;
    try {
      await passwordAuthRequest("/api/auth/password/login", {
        identifier: passwordLoginIdentifier.value,
        password: passwordLoginPassword.value,
      });
      passwordLoginPassword.value = "";
      closeAuthDialog();
      await loadAuthStatus();
    } catch (error) {
      setAuthFormError(
        passwordLoginError,
        error instanceof Error ? error.message : uiT("auth-error-generic"),
      );
    } finally {
      passwordLoginSubmit.disabled = false;
    }
  }

  async function submitPasswordRegister(event) {
    event.preventDefault();
    if (!authMethodEnabled("password") || !passwordRegisterForm) return;
    setAuthFormError(passwordRegisterError);
    passwordRegisterSubmit.disabled = true;
    try {
      await passwordAuthRequest("/api/auth/password/register", {
        username: passwordRegisterUsername.value,
        email: passwordRegisterEmail.value,
        name: passwordRegisterName.value,
        password: passwordRegisterPassword.value,
      });
      passwordRegisterPassword.value = "";
      closeAuthDialog();
      await loadAuthStatus();
    } catch (error) {
      setAuthFormError(
        passwordRegisterError,
        error instanceof Error ? error.message : uiT("auth-error-generic"),
      );
    } finally {
      passwordRegisterSubmit.disabled = false;
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
        remove.textContent = uiT("delete");
        remove.setAttribute("aria-label", uiT("conversation-delete-aria", { title: conversation.title }));
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
    const confirmed = await window.PadiemConfirmDialog.confirm({
      title: uiT("conversation-delete-title"),
      message: uiT("conversation-delete-message", { title }),
      cancelLabel: uiT("cancel"),
      confirmLabel: uiT("delete"),
    });
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
          : uiT("conversation-delete-failed");
        throw new Error(message);
      }
      const deletedActiveConversation = conversationState.getConversationId() === id;
      if (deletedActiveConversation) resetConversation(true);
      await loadRecentConversations();
      if (deletedActiveConversation) {
        input.focus();
      } else {
        setNote(idleNote());
      }
    } catch (error) {
      setNote(error instanceof Error ? error.message : uiT("conversation-delete-failed"), "error");
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
      syncApprovedMemoryVisibility();
      syncClawRunHistoryVisibility();
    } catch (_) {
      applyAuthState({ ready: false, authenticated: false, user: null, history_ready: false, project_files_ready: false });
    }
  }
  async function openSavedConversation(id) {
    if (!authState.authenticated || inFlight) return;
    try {
      const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.conversation || !Array.isArray(data.conversation.messages)) throw new Error(uiT("conversation-load-failed"));
      const savedProjectId = typeof data.conversation.project_id === "string" ? data.conversation.project_id : null;
      const restoredProject = savedProjectId ? await ensureProject(savedProjectId) : null;
      if (savedProjectId && !restoredProject) throw new Error(uiT("conversation-project-load-failed"));
      clearAttachment();
      messageList.replaceChildren();
      conversationState.reset();
      conversationState.setConversationId(data.conversation.id);
      activeProject = restoredProject;
      activeProjectFileCount = 0;
      renderProjectState();
      if (activeProject) refreshActiveProjectFileCount();
      showConversation();
      data.conversation.messages.forEach((item) => {
        if (!item || typeof item.content !== "string") return;
        if (item.role === "user") addUserMessage(item.content, null);
        if (item.role === "assistant") renderStoredAssistant(item.content);
        if (item.role === "user" || item.role === "assistant") conversationState.appendMessage({ role: item.role, content: item.content });
      });
      closeSidebar();
      input.focus();
    } catch (error) {
      setNote(error instanceof Error ? error.message : uiT("conversation-load-failed"), "error");
    }
  }

  async function requestCompletedAnswer(article, payload, outboundMessages, attachment, contextSnapshot, signal) {
    const data = await chatTransport.requestCompleted(payload, signal);
    renderAnswer(article, data);
    conversationState.commitAssistant(outboundMessages, data.answer);
    if (typeof data.conversation_id === "string") conversationState.setConversationId(data.conversation_id);
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
    conversationState.commitAssistant(outboundMessages, answer);
    if (typeof data.conversation_id === "string") conversationState.setConversationId(data.conversation_id);
    if (typeof data.project_id === "string") {
      const snapshotProject = contextSnapshot.project && contextSnapshot.project.id === data.project_id ? contextSnapshot.project : null;
      const boundedProject = data.project && data.project.id === data.project_id && typeof data.project.name === "string" ? data.project : null;
      const resolvedProject = projectById(data.project_id) || snapshotProject || boundedProject;
      if (resolvedProject) activeProject = resolvedProject;
    }
    if (Number.isInteger(data.project_files_used) && data.project_files_used > 0) {
      const used = document.createElement("small");
      used.className = "reference-note";
      used.textContent = uiT("project-files-used", { count: data.project_files_used });
      article.querySelector(".assistant-content").appendChild(used);
    }
    renderProjectState();
    if (authState.authenticated) {
      loadRecentConversations();
      if (projectsReady) loadProjects();
    }
    PadiemChatLifecycle.set(article, MESSAGE_LIFECYCLE.COMPLETED);
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function requestStreamingAnswer(article, payload, outboundMessages, skill, contextSnapshot, signal) {
    const response = await chatTransport.requestStreaming(payload, signal);

    let answer = "";
    let paragraph = null;
    let done = false;
    let terminalError = false;
    try {
      await chatTransport.readSseEvents(response, async (frame) => {
        if (!["delta", "done", "error"].includes(frame.event)) return false;
        let data;
        try {
          data = JSON.parse(frame.data);
        } catch (_) {
          throw new Error(uiT("stream-format-invalid"));
        }
        if (frame.event === "delta") {
          if (!data || typeof data.delta !== "string") throw new Error(uiT("stream-format-invalid"));
          if (!data.delta) return false;
          if (!paragraph) {
            const content = article.querySelector(".assistant-content");
            content.replaceChildren();
            paragraph = document.createElement("p");
            content.appendChild(paragraph);
            article.querySelector("[data-runtime-label]").textContent = uiT("ai-response");
          }
          answer += data.delta;
          paragraph.textContent = answer;
          return false;
        }
        if (frame.event === "error") {
          const message = data && data.error && typeof data.error.message === "string"
            ? data.error.message
            : uiT("stream-continue-failed");
          if (!paragraph) throw chatTransport.errorFor(data, message);
          terminalError = true;
          renderStreamError(article, message, outboundMessages, skill, contextSnapshot, lifecycleForError(chatTransport.errorFor(data, message)));
          return true;
        }
        if (!data || data.done !== true || !paragraph || !answer) throw new Error(uiT("stream-complete-invalid"));
        if (done) throw new Error(uiT("stream-done-duplicate"));
        done = true;
        applyStreamDone(article, data, answer, outboundMessages, contextSnapshot);
        return true;
      });
      if (done) return true;
      if (terminalError) return false;
      throw new Error(uiT("stream-incomplete"));
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      if (paragraph) {
        renderStreamError(article, error instanceof Error ? error.message : uiT("stream-continue-failed"), outboundMessages, skill, contextSnapshot);
        return false;
      }
      throw error;
    }
  }

  function cancelActiveStream() {
    if (!inFlight || !activeRequestController || !activeRequestArticle) return;
    activeRequestCancelReason = "user_cancel";
    activeRequestController.abort();
    setNote(uiT("answer-cancelled-note"), "error");
  }

  function selectedProductTier() {
    const tier = window.PadiemTierSelection?.get?.();
    return "plus";
  }

  async function requestAnswer(outboundMessages, skill, attachment, contextSnapshot) {
    if (inFlight) return false;
    inFlight = true;
    activeRequestCancelReason = null;
    const requestEpoch = conversationEpoch;
    const controller = new AbortController();
    activeRequestController = controller;
    updateComposer();
    const article = addAssistantShell(uiT("answer-preparing"));
    activeRequestArticle = article;
    renderTyping(article);
    try {
      const payload = { messages: outboundMessages, mode: "auto", tier: selectedProductTier(), skill };
      const attachments = attachmentPayload(attachment);
      if (attachments) payload.attachments = attachments;
      if (contextSnapshot.conversationId) payload.conversation_id = contextSnapshot.conversationId;
      if (contextSnapshot.project) payload.project_id = contextSnapshot.project.id;
      if (attachments) {
        return await requestCompletedAnswer(article, payload, outboundMessages, attachment, contextSnapshot, controller.signal);
      }
      return await requestStreamingAnswer(article, payload, outboundMessages, skill, contextSnapshot, controller.signal);
    } catch (error) {
      if (error && error.name === "AbortError") {
        if (activeRequestCancelReason === "user_cancel" && requestEpoch === conversationEpoch) {
          renderCancelled(article, outboundMessages, skill, contextSnapshot);
        }
        return false;
      }
      if (requestEpoch !== conversationEpoch) return false;
      renderError(
        article,
        error instanceof Error ? error.message : uiT("try-again"),
        outboundMessages,
        skill,
        attachment,
        contextSnapshot,
        lifecycleForError(error),
      );
      return false;
    } finally {
      if (activeRequestController === controller) {
        activeRequestController = null;
        activeRequestArticle = null;
        activeRequestCancelReason = null;
        inFlight = false;
        updateComposer();
        input.focus();
      }
    }
  }
  async function submitPrompt(text, selectedSkill) {
    const prompt = text.trim();
    if (!prompt || inFlight) return;
    if (selectedSkill) conversationState.setSkill(selectedSkill);
    const attachmentSnapshot = selectedAttachment;
    const contextSnapshot = { conversationId: conversationState.getConversationId(), project: activeProject };
    showConversation();
    addUserMessage(prompt, attachmentSnapshot);
    input.value = "";
    const outbound = conversationState.outboundWithUser(prompt);
    const success = await requestAnswer(outbound, conversationState.getSkill(), attachmentSnapshot, contextSnapshot);
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
  function openSettings() {
    if (typeof settingsDialog.showModal === "function") settingsDialog.showModal();
    else settingsDialog.setAttribute("open", "");
    settingsButton.setAttribute("aria-expanded", "true");
  }
  function closeSettings() {
    if (settingsDialog.open && typeof settingsDialog.close === "function") settingsDialog.close();
    else settingsDialog.removeAttribute("open");
    settingsButton.setAttribute("aria-expanded", "false");
  }

  input.addEventListener("input", updateComposer);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sendButton.disabled) form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    // #2532: in the Claw workspace the composer is the request input; Enter routes to preview.
    if (shell.dataset.state === "claw" && clawManualForm && !clawManualForm.hidden) {
      clawManualForm.requestSubmit();
      return;
    }
    submitPrompt(input.value);
  });
  cancelStreamButton.addEventListener("click", cancelActiveStream);
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
  projectDeleteButton.addEventListener("click", deleteProject);
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
      openAuthDialog();
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
  if (authDialogClose) authDialogClose.addEventListener("click", closeAuthDialog);
  if (authDialog) {
    authDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      closeAuthDialog();
    });
  }
  if (googleLoginButton) {
    googleLoginButton.addEventListener("click", () => {
      if (authMethodEnabled("google")) window.location.assign("/auth/google/start");
    });
  }
  if (passwordLoginForm) passwordLoginForm.addEventListener("submit", submitPasswordLogin);
  if (passwordRegisterForm) passwordRegisterForm.addEventListener("submit", submitPasswordRegister);
  document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
    submitPrompt(button.dataset.prompt || "", button.dataset.skill || "auto");
    closeSidebar();
  }));
  newChatButton.addEventListener("click", () => resetConversation(true));
  settingsButton.addEventListener("click", openSettings);
  settingsDialog.addEventListener("close", () => settingsButton.setAttribute("aria-expanded", "false"));
  settingsDialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeSettings();
  });
  settingsCloseButton.addEventListener("click", closeSettings);
  mobileMenu.addEventListener("click", openSidebar);
  mobileClose.addEventListener("click", closeSidebar);
  sidebarScrim.addEventListener("click", closeSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && shell.classList.contains("sidebar-open")) closeSidebar();
  });
  window.addEventListener("padiem:localechange", () => {
    applyAuthState(authState);
    if (projectsReady) renderProjects();
    renderProjectState();
    if (!selectedAttachment) setNote(idleNote());
    syncComposerForClaw(shell.dataset.state === "claw");
    const activeInboxKind = document.getElementById("clawWorkspace")?.dataset.inboxKind;
    if (activeInboxKind === "tasks" || activeInboxKind === "alerts") loadClawInbox(activeInboxKind);
  });

  // Claw first-class workspace & MVP usability wiring (#2299)
  const clawNavButton = document.getElementById("clawNavButton");
  const tasksNavButton = document.getElementById("tasksNavButton");
  const alertsNavButton = document.getElementById("alertsNavButton");
  const clawWorkspace = document.getElementById("clawWorkspace");
  const clawInbox = document.getElementById("clawInbox");
  const clawInboxTitle = document.getElementById("clawInboxTitle");
  const clawInboxLoading = document.getElementById("clawInboxLoading");
  const clawInboxError = document.getElementById("clawInboxError");
  const clawInboxEmpty = document.getElementById("clawInboxEmpty");
  const clawInboxList = document.getElementById("clawInboxList");
  const clawInboxRetry = document.getElementById("clawInboxRetry");
  const clawManualForm = document.getElementById("clawManualForm");
  const clawChannel = document.getElementById("clawChannel");
  const clawAction = document.getElementById("clawAction");
  const clawSender = document.getElementById("clawSender");
  const clawResultArea = document.getElementById("clawResultArea");
  const clawResultPreview = document.getElementById("clawResultPreview");
  const clawResultCard = document.getElementById("clawResultCard");
  const clawResultEmpty = document.getElementById("clawResultEmpty");
  const clawResultKind = document.getElementById("clawResultKind");
  const clawGenerateBtn = document.getElementById("clawGenerateBtn");
  const clawExecuteButton = document.getElementById("clawExecuteButton");
  const clawResultBadge = document.getElementById("clawResultBadge");
  const clawResultOpen = document.getElementById("clawResultOpen");
  const clawResultDocx = document.getElementById("clawResultDocx");
  const clawStatus = document.getElementById("clawStatus");
  const clawRequestEcho = document.getElementById("clawRequestEcho");
  const clawRequestEchoText = document.getElementById("clawRequestEchoText");
  const clawArtifactMeta = document.getElementById("clawArtifactMeta");
  const clawArtifactName = document.getElementById("clawArtifactName");
  const clawArtifactSize = document.getElementById("clawArtifactSize");
  const clawResultSuccessNote = document.getElementById("clawResultSuccessNote");
  const clawResultHint = document.getElementById("clawResultHint");
  const clawExecuteHint = document.getElementById("clawExecuteHint");

  let clawInFlight = false;
  let clawLastAction = clawAction?.value || "quote";

  const clawFallbackCopy = {
    "claw-result-badge": "Preview",
    "claw-result-badge-run": "Real run",
    "claw-status-preview-running": "Generating preview...",
    "claw-status-execute-running": "Running... please wait a moment.",
    "claw-status-preview-success": "Preview is ready.",
    "claw-status-execute-success": "Done.",
    "claw-error-preview": "Preview could not be loaded. Please try again shortly.",
    "claw-error-empty": "Paste your request before running.",
    "claw-error-too-large": "Request is too long. Please shorten it and try again.",
    "claw-error-invalid": "Please check your input and try again.",
    "claw-error-rate-limited": "Too many requests right now. Please try again shortly.",
    "claw-error-auth-needed": "Please sign in again to continue.",
    "claw-error-auth-unavailable": "This feature isn't available because the workspace sign-in state can't be verified. Please check the workspace configuration.",
    "claw-error-storage": "Could not save the document. Please try again shortly.",
    "claw-error-generic": "Something went wrong. Please try again shortly.",
    "claw-memory-review-title": "Memory save proposal (approval required)",
    "claw-memory-approve": "Approve",
    "claw-memory-reject": "Reject",
    "claw-memory-detail": "Details",
    "claw-memory-close": "Close",
    "claw-memory-type": "Type",
    "claw-memory-name": "Name",
    "claw-memory-note": "Note",
    "claw-memory-channel": "Channel",
    "claw-memory-status": "Status",
    "claw-memory-created": "Created",
    "claw-memory-updated": "Updated",
    "claw-memory-status-approved": "Approved",
    "claw-memory-error-approval": "Explicit approval is required.",
    "claw-memory-error-invalid": "The proposal format is invalid.",
    "claw-memory-error-auth": "Please sign in.",
    "claw-memory-error-unavailable": "Approved memory is unavailable.",
    "claw-memory-error-not-found": "Memory was not found.",
    "claw-memory-error-generic": "Approved memory could not be processed.",
    "claw-runs-title": "Recent runs",
    "claw-runs-empty": "No recent runs.",
    "claw-runs-error": "Could not load run history. Please try again.",
    "claw-runs-download": "Download document again",
    "claw-runs-status-completed": "Completed",
  };

  function clawT(key) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const v = window.__padiemLocale.text(key);
        if (v && v !== key) return v;
      }
    } catch (_) {}
    return clawFallbackCopy[key] || "Unable to update this Claw status. Please try again.";
  }

  function localeOr(key, fallback) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const value = window.__padiemLocale.text(key);
        if (value && value !== key) return value;
      }
    } catch (_) {}
    return fallback;
  }

  function syncComposerForClaw(isClaw) {
    if (!input) return;
    if (isClaw) {
      input.placeholder = localeOr("claw-request-placeholder", "Paste a business request you received by chat, SMS, or email.");
      input.setAttribute("aria-describedby", "clawStatus");
      input.setAttribute("maxlength", "4000");
    } else {
      input.placeholder = localeOr("input", "Ask anything");
      input.removeAttribute("aria-describedby");
      input.removeAttribute("aria-invalid");
      input.setAttribute("maxlength", "8000");
    }
  }

  function setClawStatus(message, state, localeKey) {
    if (!clawStatus) return;
    if (!message) {
      clawStatus.hidden = true;
      clawStatus.textContent = "";
      clawStatus.removeAttribute("data-state");
      input.removeAttribute("aria-invalid");
      return;
    }
    clawStatus.hidden = false;
    clawStatus.textContent = message;
    if (state) clawStatus.dataset.state = state;
    else clawStatus.removeAttribute("data-state");
    if (localeKey) clawStatus.dataset.localeKey = localeKey;
    else delete clawStatus.dataset.localeKey;
    if (state === "error") input.setAttribute("aria-invalid", "true");
    else input.removeAttribute("aria-invalid");
  }

  function setClawAreaState(state) {
    if (clawResultArea) clawResultArea.dataset.clawState = state;
  }

  function setClawButtonsBusy(busy) {
    clawInFlight = busy;
    const busyVal = busy ? "true" : "false";
    if (clawGenerateBtn) {
      clawGenerateBtn.disabled = busy;
      clawGenerateBtn.setAttribute("aria-busy", busyVal);
      clawGenerateBtn.setAttribute("aria-disabled", String(busy));
    }
    if (clawExecuteButton) {
      clawExecuteButton.disabled = busy;
      clawExecuteButton.setAttribute("aria-busy", busyVal);
      clawExecuteButton.setAttribute("aria-disabled", String(busy));
    }
  }

  function clearClawArtifact() {
    if (clawArtifactMeta) clawArtifactMeta.hidden = true;
    if (clawArtifactName) clawArtifactName.textContent = "";
    if (clawArtifactSize) clawArtifactSize.textContent = "";
    if (clawResultSuccessNote) clawResultSuccessNote.hidden = true;
    [clawResultOpen, clawResultDocx].forEach((btn) => {
      if (!btn) return;
      btn.disabled = true;
      btn.setAttribute("aria-disabled", "true");
      btn.classList.remove("is-prominent");
      delete btn.dataset.documentId;
    });
  }

  function formatClawBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderClawArtifactMeta(artifact) {
    if (!artifact || !artifact.document_id) {
      clearClawArtifact();
      return;
    }
    const filename = typeof artifact.filename === "string" && artifact.filename ? artifact.filename : "document.docx";
    const byteLength = typeof artifact.byte_length === "number" ? artifact.byte_length : null;
    if (clawArtifactName) clawArtifactName.textContent = filename;
    if (clawArtifactSize) clawArtifactSize.textContent = byteLength != null ? formatClawBytes(byteLength) : "";
    if (clawArtifactMeta) clawArtifactMeta.hidden = false;
    if (clawResultSuccessNote) clawResultSuccessNote.hidden = false;
    [clawResultOpen, clawResultDocx].forEach((btn) => {
      if (!btn) return;
      btn.disabled = false;
      btn.setAttribute("aria-disabled", "false");
      btn.dataset.documentId = artifact.document_id;
      if (artifact.filename) btn.dataset.filename = artifact.filename;
    });
    if (clawResultDocx) clawResultDocx.classList.add("is-prominent");
  }

  function safeClawErrorMessage(data, response) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const status = response ? response.status : 0;
    if (code === "invalid_content" || code === "content_too_short") return clawT("claw-error-empty");
    if (code === "content_too_long" || code === "body_too_large" || status === 413) return clawT("claw-error-too-large");
    if (code === "invalid_channel" || code === "invalid_action" || code === "unsupported_media_type" || code === "invalid_sender_hint") return clawT("claw-error-invalid");
    if (code === "rate_limited" || status === 429) return clawT("claw-error-rate-limited");
    if (code === "workspace_scope_unavailable" || code === "live_identity_unavailable") return clawT("claw-error-auth-unavailable");
    if (code === "auth_required" || status === 401) return clawT("claw-error-auth-needed");
    if (code === "workspace_storage_unavailable" || code === "artifact_storage_failed" || code === "artifact_generation_failed") return clawT("claw-error-storage");
    if (status === 503 || code === "engine_not_configured" || code === "live_abuse_gate_unavailable") return clawT("claw-error-generic");
    if (code === "engine_execution_failed" || status === 502) return clawT("claw-error-generic");
    return clawT("claw-error-generic");
  }

  async function downloadClawArtifact(documentId, filenameHint) {
    if (!documentId || !/^doc_[A-Za-z0-9]{32}$/.test(String(documentId))) return;
    try {
      const resp = await fetch(`/api/claw/manual-intake/artifact/${encodeURIComponent(documentId)}`, { cache: "no-store" });
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        setClawStatus(safeClawErrorMessage(err, resp), "error");
        setClawAreaState("error");
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filenameHint || "document.docx";
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (_) {
      setClawStatus(clawT("claw-error-generic"), "error");
      setClawAreaState("error");
    }
  }

  function resetClawInboxState() {
    if (clawInboxLoading) clawInboxLoading.hidden = true;
    if (clawInboxError) clawInboxError.hidden = true;
    if (clawInboxEmpty) clawInboxEmpty.hidden = true;
  }

  function setClawInboxLoading() {
    resetClawInboxState();
    if (clawInboxList) clawInboxList.replaceChildren();
    if (clawInboxLoading) {
      clawInboxLoading.hidden = false;
      clawInboxLoading.textContent = uiT("claw-inbox-loading");
    }
  }

  function setClawInboxError() {
    resetClawInboxState();
    if (clawInboxError) {
      clawInboxError.hidden = false;
      clawInboxError.textContent = uiT("claw-inbox-error");
    }
  }

  async function updateClawInboxStatus(kind, itemId, status) {
    try {
      const response = await fetch(`/api/claw/inbox/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`, {
        method: "PATCH",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true) throw new Error("inbox update failed");
      await loadClawInbox(kind);
    } catch (_) {
      setClawInboxError();
      if (clawInboxRetry) clawInboxRetry.focus?.();
    }
  }

  function renderClawInboxItems(kind, items) {
    resetClawInboxState();
    if (!clawInboxList) return;
    clawInboxList.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      if (clawInboxEmpty) {
        clawInboxEmpty.dataset.localeKey = kind === "tasks" ? "claw-inbox-empty-tasks" : "claw-inbox-empty-alerts";
        clawInboxEmpty.textContent = uiT(clawInboxEmpty.dataset.localeKey);
        clawInboxEmpty.hidden = false;
      }
      return;
    }
    items.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const id = kind === "tasks" ? item.task_id : item.alert_id;
      if (typeof id !== "string" || typeof item.title !== "string") return;
      const card = document.createElement("article");
      card.className = "claw-inbox-item";
      card.setAttribute("role", "listitem");

      const copy = document.createElement("div");
      copy.className = "claw-inbox-item-copy";
      const title = document.createElement("strong");
      title.textContent = item.title;
      const meta = document.createElement("span");
      const statusText = uiT(`claw-inbox-status-${String(item.status || "")}`);
      meta.textContent = statusText === `claw-inbox-status-${String(item.status || "")}` ? String(item.status || "") : statusText;
      copy.append(title, meta);

      const action = document.createElement("button");
      action.type = "button";
      action.className = "claw-inbox-status-action";
      let nextStatus = "";
      let actionKey = "";
      if (kind === "tasks") {
        nextStatus = item.status === "open" ? "done" : "open";
        actionKey = item.status === "open" ? "claw-inbox-mark-done" : "claw-inbox-reopen";
      } else {
        nextStatus = item.status === "active" ? "dismissed" : "active";
        actionKey = item.status === "active" ? "claw-inbox-dismiss" : "claw-inbox-restore";
      }
      action.textContent = uiT(actionKey);
      action.addEventListener("click", () => updateClawInboxStatus(kind, id, nextStatus), { once: true });
      card.append(copy, action);
      clawInboxList.appendChild(card);
    });
  }

  async function loadClawInbox(kind) {
    if (!authState.authenticated || !clawInbox) return;
    setClawInboxLoading();
    try {
      const response = await fetch(`/api/claw/inbox/${encodeURIComponent(kind)}?limit=20`, {
        headers: { "Accept": "application/json" },
        cache: "no-store",
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true || !Array.isArray(data.items)) throw new Error("inbox unavailable");
      renderClawInboxItems(kind, data.items);
    } catch (_) {
      setClawInboxError();
    }
  }

  function openClawInbox(kind) {
    if (!clawWorkspace || !clawInbox || !authState.authenticated) return;
    shell.dataset.state = "claw";
    clawWorkspace.dataset.view = "inbox";
    clawWorkspace.dataset.inboxKind = kind;
    clawInbox.hidden = false;
    if (clawManualForm) clawManualForm.hidden = true;
    if (clawResultArea) clawResultArea.hidden = true;
    if (clawInboxTitle) {
      clawInboxTitle.dataset.localeKey = kind === "tasks" ? "claw-inbox-tasks-title" : "claw-inbox-alerts-title";
      clawInboxTitle.textContent = uiT(clawInboxTitle.dataset.localeKey);
    }
    setNavActive();
    closeSidebar();
    syncApprovedMemoryVisibility();
    syncClawRunHistoryVisibility();
    loadClawInbox(kind);
  }

  function openClawWorkspace() {
    if (!clawWorkspace) return;
    shell.dataset.state = "claw";
    clawWorkspace.dataset.view = "manual";
    delete clawWorkspace.dataset.inboxKind;
    if (clawInbox) clawInbox.hidden = true;
    if (clawManualForm) clawManualForm.hidden = false;
    if (clawResultArea) clawResultArea.hidden = false;
    setNavActive();
    input.focus();
    closeSidebar();
    syncApprovedMemoryVisibility();
    syncClawRunHistoryVisibility();
  }

  if (clawNavButton) clawNavButton.addEventListener("click", openClawWorkspace);
  if (tasksNavButton) tasksNavButton.addEventListener("click", () => openClawInbox("tasks"));
  if (alertsNavButton) alertsNavButton.addEventListener("click", () => openClawInbox("alerts"));
  if (clawInboxRetry) clawInboxRetry.addEventListener("click", () => {
    const kind = clawWorkspace?.dataset.inboxKind;
    if (kind === "tasks" || kind === "alerts") loadClawInbox(kind);
  });
  if (clawManualForm) {
    const modeChips = clawManualForm.querySelectorAll(".claw-chip[data-claw-action]");
    modeChips.forEach((chip) => {
      chip.addEventListener("click", () => {
        const action = chip.dataset.clawAction;
        if (clawAction && action) clawAction.value = action;
        modeChips.forEach((other) => {
          other.setAttribute("aria-pressed", other === chip ? "true" : "false");
        });
        clawLastAction = action || null;
        input.focus();
      });
    });
    // Keyboard: chips are buttons so Enter/Space already work; ensure roving focus stays visible.
  }
  setNavActive();

  function revealClawCard(kindText, executed = false) {
    if (clawResultEmpty) clawResultEmpty.hidden = true;
    if (clawResultHint) clawResultHint.hidden = true;
    if (clawResultCard) clawResultCard.hidden = false;
    if (clawResultKind) clawResultKind.textContent = kindText || "";
    if (clawResultBadge) {
      clawResultBadge.dataset.localeKey = executed ? "claw-result-badge-run" : "claw-result-badge";
      clawResultBadge.textContent = clawT(executed ? "claw-result-badge-run" : "claw-result-badge");
    }
  }

  // #2532 (R2): echo the submitted request as a user bubble in the shared
  // conversation so manual Claw reads as one continuous Chat thread. This is
  // the user's own message, never presented as an AI result.
  function renderClawRequestEcho(text) {
    if (!clawRequestEcho || !clawRequestEchoText) return;
    clawRequestEchoText.textContent = text;
    clawRequestEcho.hidden = false;
  }

  // Single artifact handlers: read current dataset at click time (no per-result listener leak).
  if (clawResultDocx) clawResultDocx.addEventListener("click", () => {
    const docId = clawResultDocx.dataset.documentId;
    const fname = clawResultDocx.dataset.filename;
    if (docId && !clawResultDocx.disabled) downloadClawArtifact(docId, fname);
  });
  if (clawResultOpen) clawResultOpen.addEventListener("click", () => {
    const docId = clawResultOpen.dataset.documentId;
    const fname = clawResultOpen.dataset.filename;
    if (docId && !clawResultOpen.disabled) downloadClawArtifact(docId, fname);
  });

  if (clawManualForm) {
    clawManualForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (clawInFlight) return;
      const body = (input.value || "").trim();
      if (!body) {
        if (clawResultCard) clawResultCard.hidden = true;
        clearClawArtifact();
        if (clawResultEmpty) {
          clawResultEmpty.hidden = false;
          clawResultEmpty.textContent = clawT("claw-error-empty");
        }
        if (clawResultHint) clawResultHint.hidden = false;
        setClawStatus(clawT("claw-error-empty"), "error");
        setClawAreaState("error");
        input.focus();
        return;
      }
      if (body.length > 4000) {
        setClawStatus(clawT("claw-error-too-large"), "error");
        setClawAreaState("error");
        return;
      }
      const channelValue = clawChannel?.value || "other";
      const actionValue = clawAction?.value || "quote";
      const channelText = clawChannel?.options[clawChannel.selectedIndex]?.textContent || channelValue;
      const actionText = clawAction?.options[clawAction.selectedIndex]?.textContent || actionValue;
      const senderText = (clawSender?.value || "").trim();

      renderClawRequestEcho(body);
      setClawButtonsBusy(true);
      setClawStatus(clawT("claw-status-preview-running"), "running", "claw-status-preview-running");
      setClawAreaState("submitting");
      if (clawResultCard) clawResultCard.hidden = true;
      clearClawArtifact();
      if (clawResultEmpty) {
        clawResultEmpty.hidden = false;
        clawResultEmpty.textContent = clawT("claw-status-preview-running");
      }

      const renderPreviewError = () => {
        if (clawResultCard) clawResultCard.hidden = true;
        clearClawArtifact();
        if (clawMemoryReview) clawMemoryReview.hidden = true;
        if (clawResultEmpty) {
          clawResultEmpty.hidden = false;
          clawResultEmpty.textContent = clawT("claw-error-preview");
        }
        if (clawResultHint) clawResultHint.hidden = false;
        setClawStatus(clawT("claw-error-preview"), "error", "claw-error-preview");
        setClawAreaState("error");
      };

      try {
        const response = await fetch("/api/claw/manual-intake/preview", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ content: body, channel: channelValue, action: actionValue, sender_hint: senderText || null }),
        });
        if (!response.ok) {
          renderPreviewError();
          return;
        }
        const data = await response.json();
        if (!data || !data.ok || !data.preview || typeof data.preview.result_text !== "string") {
          renderPreviewError();
          return;
        }
        const preview = data.preview;
        revealClawCard(preview.title);
        if (clawResultPreview) clawResultPreview.textContent = preview.result_text;
        clearClawArtifact();
        renderMemoryProposalReview(Array.isArray(preview.memory_proposals) ? preview.memory_proposals : []);
        setClawStatus(clawT("claw-status-preview-success"), "success", "claw-status-preview-success");
        setClawAreaState("success");
        // Move focus to result for screen-reader and keyboard users
        if (clawResultPreview) clawResultPreview.focus?.();
      } catch {
        renderPreviewError();
      } finally {
        setClawButtonsBusy(false);
      }
    });
  }

  // Keep preview/execute hints in sync with locale switches (data-locale-key auto-syncs static text,
  // but status and dynamic card chrome need manual refresh when language toggles).
  window.addEventListener("padiem:localechange", () => {
    if (clawStatus && !clawStatus.hidden && clawStatus.dataset.localeKey) {
      clawStatus.textContent = clawT(clawStatus.dataset.localeKey);
    }
    // Re-apply badge text to current card state if visible
    if (clawResultCard && !clawResultCard.hidden && clawResultBadge) {
      const isExecuted = clawResultBadge.dataset.localeKey === "claw-result-badge-run";
      try { clawResultBadge.textContent = window.__padiemLocale.text(isExecuted ? "claw-result-badge-run" : "claw-result-badge"); } catch (_) {}
    }
  });

  setNote(idleNote());
  renderProjectState();
  updateComposer();
  loadAuthStatus();
  // Initial state
  setClawAreaState("idle");
  clearClawArtifact();

  if (clawExecuteButton) {
    clawExecuteButton.addEventListener("click", async () => {
      if (clawInFlight) return;
      const body = (input.value || "").trim();
      if (!body) {
        clearClawArtifact();
        if (clawResultCard) clawResultCard.hidden = true;
        if (clawResultEmpty) {
          clawResultEmpty.hidden = false;
          clawResultEmpty.textContent = clawT("claw-error-empty");
        }
        setClawStatus(clawT("claw-error-empty"), "error");
        setClawAreaState("error");
        input.focus();
        return;
      }
      if (body.length > 4000) {
        setClawStatus(clawT("claw-error-too-large"), "error");
        setClawAreaState("error");
        return;
      }
      const channelValue = clawChannel?.value || "other";
      const actionValue = clawAction?.value || "quote";
      const senderText = (clawSender?.value || "").trim();

      renderClawRequestEcho(body);
      setClawButtonsBusy(true);
      setClawStatus(clawT("claw-status-execute-running"), "running", "claw-status-execute-running");
      setClawAreaState("submitting");
      if (clawResultCard) clawResultCard.hidden = true;
      clearClawArtifact();
      if (clawResultEmpty) {
        clawResultEmpty.hidden = false;
        clawResultEmpty.textContent = clawT("claw-status-execute-running");
      }

      try {
        const response = await fetch("/api/claw/manual-intake/execute", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({
            content: body,
            channel: channelValue,
            action: actionValue,
            sender_hint: senderText || null,
            tier: selectedProductTier(),
          }),
        });
        const data = await response.json().catch(() => null);
        if (data && data.ok && data.result && typeof data.result.result_text === "string") {
          const result = data.result;
          const safeText = String(result.result_text);
          revealClawCard(result.title, true);
          if (clawResultPreview) clawResultPreview.textContent = safeText;
          if (clawResultEmpty) clawResultEmpty.hidden = true;
          const artifact = result.artifact && typeof result.artifact.document_id === "string" ? result.artifact : null;
          const hasArtifact = !!(artifact && artifact.document_id);
          if (hasArtifact) renderClawArtifactMeta(artifact); else clearClawArtifact();
          setClawStatus(clawT("claw-status-execute-success"), "success", "claw-status-execute-success");
          setClawAreaState("success");
          if (hasArtifact && clawResultDocx) clawResultDocx.focus?.();
          else if (clawResultPreview) clawResultPreview.focus?.();
          return;
        }
        const safeMsg = safeClawErrorMessage(data, response);
        if (clawResultEmpty) {
          clawResultEmpty.hidden = false;
          clawResultEmpty.textContent = safeMsg;
        }
        setClawStatus(safeMsg, "error");
        setClawAreaState("error");
      } catch {
        const fallback = clawT("claw-error-generic");
        if (clawResultEmpty) {
          clawResultEmpty.hidden = false;
          clawResultEmpty.textContent = fallback;
        }
        setClawStatus(fallback, "error");
        setClawAreaState("error");
      } finally {
        setClawButtonsBusy(false);
      }
    });
  }
  // Approved-memory review UI (#2340)
  const clawApprovedMemory = document.getElementById("clawApprovedMemory");
  const clawApprovedRefresh = document.getElementById("clawApprovedRefresh");
  const clawApprovedLoading = document.getElementById("clawApprovedLoading");
  const clawApprovedError = document.getElementById("clawApprovedError");
  const clawApprovedList = document.getElementById("clawApprovedList");
  const clawApprovedEmpty = document.getElementById("clawApprovedEmpty");
  const clawMemoryReview = document.getElementById("clawMemoryReview");

  let approvedMemoryInFlight = false;

  function setApprovedMemoryStatus(message, state) {
    if (!clawApprovedError) return;
    if (!message) {
      clawApprovedError.hidden = true;
      clawApprovedError.textContent = "";
      clawApprovedError.removeAttribute("data-state");
      return;
    }
    clawApprovedError.hidden = false;
    clawApprovedError.textContent = message;
    if (state) clawApprovedError.dataset.state = state;
    else clawApprovedError.removeAttribute("data-state");
  }

  function approvedMemoryErrorMessage(data, response) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const status = response ? response.status : 0;
    if (code === "explicit_approval_required") return clawT("claw-memory-error-approval");
    if (code === "invalid_proposal" || code === "invalid_payload" || code === "forbidden_owner_field") return clawT("claw-memory-error-invalid");
    if (code === "unauthorized" || status === 401) return clawT("claw-memory-error-auth");
    if (code === "approved_memory_unavailable" || code === "approved_memory_write_failed" || code === "approved_memory_read_failed" || status === 503) return clawT("claw-memory-error-unavailable");
    if (code === "approved_memory_not_found" || status === 404) return clawT("claw-memory-error-not-found");
    return clawT("claw-memory-error-generic");
  }

  // Proposal review surface: rendered from preview memory_proposals. Approve is
  // impossible until the user explicitly approves; reject never persists.
  function renderMemoryProposalReview(proposals) {
    if (!clawMemoryReview) return;
    clawMemoryReview.replaceChildren();
    if (!Array.isArray(proposals) || proposals.length === 0) {
      clawMemoryReview.hidden = true;
      return;
    }
    const heading = document.createElement("h3");
    heading.className = "claw-memory-review-title";
    heading.textContent = clawT("claw-memory-review-title");
    clawMemoryReview.appendChild(heading);
    proposals.forEach((proposal) => {
      if (!proposal || typeof proposal !== "object") return;
      const safe = {
        type: typeof proposal.type === "string" ? proposal.type : "",
        name: typeof proposal.name === "string" ? proposal.name : "",
        note: typeof proposal.note === "string" ? proposal.note : "",
        source_channel: typeof proposal.source_channel === "string" ? proposal.source_channel : "",
      };
      const card = document.createElement("div");
      card.className = "claw-memory-proposal";
      const title = document.createElement("strong");
      title.className = "claw-memory-proposal-name";
      title.textContent = safe.name;
      const meta = document.createElement("span");
      meta.className = "claw-memory-proposal-type";
      meta.textContent = safe.type;
      const note = document.createElement("p");
      note.className = "claw-memory-proposal-note";
      note.textContent = safe.note;
      const actions = document.createElement("div");
      actions.className = "claw-memory-proposal-actions";
      const approveBtn = document.createElement("button");
      approveBtn.type = "button";
      approveBtn.className = "claw-memory-approve";
      approveBtn.textContent = clawT("claw-memory-approve");
      approveBtn.addEventListener("click", () => approveProposal(safe));
      const rejectBtn = document.createElement("button");
      rejectBtn.type = "button";
      rejectBtn.className = "claw-memory-reject";
      rejectBtn.textContent = clawT("claw-memory-reject");
      rejectBtn.addEventListener("click", () => rejectProposal(safe));
      actions.append(approveBtn, rejectBtn);
      card.append(title, meta, note, actions);
      clawMemoryReview.appendChild(card);
    });
    clawMemoryReview.hidden = false;
  }

  function proposalBody(proposal) {
    return { type: proposal.type, name: proposal.name, note: proposal.note || null, source_channel: proposal.source_channel || null };
  }

  async function approveProposal(proposal) {
    if (approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    setApprovedMemoryStatus("", "");
    try {
      const response = await fetch("/api/claw/memory/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ approved: true, proposal: proposalBody(proposal) }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true || !data.memory) {
        throw new Error(approvedMemoryErrorMessage(data, response));
      }
      await fetchApprovedMemoryList();
    } catch (error) {
      setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error");
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  async function rejectProposal(proposal) {
    if (approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    setApprovedMemoryStatus("", "");
    try {
      const response = await fetch("/api/claw/memory/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ proposal: proposalBody(proposal) }),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true || data.persisted !== false) {
        throw new Error(approvedMemoryErrorMessage(data, response));
      }
      await fetchApprovedMemoryList();
    } catch (error) {
      setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error");
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  function renderApprovedMemoryCard(memory) {
    const card = document.createElement("div");
    card.className = "claw-approved-card";
    card.dataset.memoryId = memory.memory_id || "";

    const head = document.createElement("div");
    head.className = "claw-approved-card-head";
    const title = document.createElement("strong");
    title.className = "claw-approved-card-title";
    title.textContent = memory.name || "";
    const badge = document.createElement("span");
    badge.className = "claw-approved-card-badge";
    badge.textContent = memory.status === "approved" ? clawT("claw-memory-status-approved") : (memory.status || "");
    head.append(title, badge);

    const meta = document.createElement("div");
    meta.className = "claw-approved-card-meta";
    const memoryTypeKey = `claw-memory-type-${memory.memory_type || ""}`;
    const memoryType = memory.memory_type ? clawT(memoryTypeKey) : "";
    meta.textContent = `${memoryType === memoryTypeKey ? memory.memory_type : memoryType} · ${memory.created_at || ""}`;

    const note = document.createElement("p");
    note.className = "claw-approved-card-note";
    note.textContent = memory.note || "";

    const actions = document.createElement("div");
    actions.className = "claw-approved-card-actions";
    const detailBtn = document.createElement("button");
    detailBtn.type = "button";
    detailBtn.className = "claw-approved-action";
    detailBtn.textContent = clawT("claw-memory-detail");
    detailBtn.addEventListener("click", () => {
      const id = card.dataset.memoryId;
      if (id) loadApprovedMemoryDetail(id);
    });
    actions.appendChild(detailBtn);
    card.append(head, meta, note, actions);
    return card;
  }

  function renderApprovedMemoryDetail(memory) {
    const existing = clawApprovedList?.querySelector(".claw-approved-detail");
    if (existing) existing.remove();
    const detail = document.createElement("div");
    detail.className = "claw-approved-detail";
    const rows = [
      { label: clawT("claw-memory-type"), value: memory.memory_type || "" },
      { label: clawT("claw-memory-name"), value: memory.name || "" },
      { label: clawT("claw-memory-note"), value: memory.note || "" },
      { label: clawT("claw-memory-channel"), value: memory.source_channel || "" },
      { label: clawT("claw-memory-status"), value: memory.status === "approved" ? clawT("claw-memory-status-approved") : (memory.status || "") },
      { label: clawT("claw-memory-created"), value: memory.created_at || "" },
      { label: clawT("claw-memory-updated"), value: memory.updated_at || "" },
    ];
    rows.forEach((row) => {
      const rowEl = document.createElement("div");
      rowEl.className = "claw-approved-detail-row";
      const label = document.createElement("span");
      label.className = "claw-approved-detail-label";
      label.textContent = row.label;
      const value = document.createElement("span");
      value.className = "claw-approved-detail-value";
      value.textContent = row.value;
      rowEl.append(label, value);
      detail.appendChild(rowEl);
    });
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "claw-approved-action";
    closeBtn.textContent = clawT("claw-memory-close");
    closeBtn.addEventListener("click", () => {
      detail.remove();
      loadApprovedMemoryList();
    });
    detail.appendChild(closeBtn);
    clawApprovedList?.appendChild(detail);
  }

  // Unguarded fetch: callers hold the single-flight flag while awaiting this.
  async function fetchApprovedMemoryList() {
    if (!clawApprovedMemory) return;
    setApprovedMemoryStatus("", "");
    if (clawApprovedLoading) clawApprovedLoading.hidden = false;
    if (clawApprovedList) clawApprovedList.hidden = true;
    if (clawApprovedEmpty) clawApprovedEmpty.hidden = true;
    if (clawApprovedList) clawApprovedList.replaceChildren();
    try {
      const response = await fetch("/api/claw/memory", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !Array.isArray(data.memories)) {
        throw new Error(approvedMemoryErrorMessage(data, response));
      }
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      if (clawApprovedList) clawApprovedList.hidden = false;
      if (data.memories.length === 0) {
        if (clawApprovedEmpty) clawApprovedEmpty.hidden = false;
        return;
      }
      data.memories.forEach((memory) => {
        if (!memory || typeof memory.memory_id !== "string") return;
        clawApprovedList?.appendChild(renderApprovedMemoryCard(memory));
      });
    } catch (error) {
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error");
    }
  }

  async function loadApprovedMemoryList() {
    if (approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    try {
      await fetchApprovedMemoryList();
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  async function loadApprovedMemoryDetail(memoryId) {
    if (!clawApprovedMemory || approvedMemoryInFlight) return;
    approvedMemoryInFlight = true;
    setApprovedMemoryStatus("", "");
    if (clawApprovedLoading) clawApprovedLoading.hidden = false;
    if (clawApprovedList) clawApprovedList.hidden = true;
    if (clawApprovedEmpty) clawApprovedEmpty.hidden = true;
    try {
      const response = await fetch(`/api/claw/memory/${encodeURIComponent(memoryId)}`, { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || !data.memory) {
        throw new Error(approvedMemoryErrorMessage(data, response));
      }
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      if (clawApprovedList) clawApprovedList.hidden = false;
      renderApprovedMemoryDetail(data.memory);
    } catch (error) {
      if (clawApprovedLoading) clawApprovedLoading.hidden = true;
      setApprovedMemoryStatus(error instanceof Error ? error.message : clawT("claw-memory-error-generic"), "error");
    } finally {
      approvedMemoryInFlight = false;
    }
  }

  function syncApprovedMemoryVisibility() {
    if (!clawApprovedMemory) return;
    // Owner-authenticated surface only: anonymous Phase A flow is unchanged.
    const show = authState.authenticated === true
      && shell.dataset.state === "claw"
      && clawWorkspace?.dataset.view !== "inbox";
    clawApprovedMemory.hidden = !show;
    if (show) loadApprovedMemoryList();
  }

  if (clawApprovedRefresh) {
    clawApprovedRefresh.addEventListener("click", () => loadApprovedMemoryList());
  }

  // Claw recent-run presentation (#2317 owner-scoped run history route).
  // Presentation only: the browser renders what GET /api/claw/runs already
  // exposes to the signed-in owner and never mints its own run/history truth.
  const clawRunHistory = document.getElementById("clawRunHistory");
  const clawRunHistoryRefresh = document.getElementById("clawRunHistoryRefresh");
  const clawRunHistoryLoading = document.getElementById("clawRunHistoryLoading");
  const clawRunHistoryError = document.getElementById("clawRunHistoryError");
  const clawRunHistoryList = document.getElementById("clawRunHistoryList");
  const clawRunHistoryEmpty = document.getElementById("clawRunHistoryEmpty");

  let clawRunHistoryInFlight = false;

  function setClawRunHistoryStatus(message) {
    if (!clawRunHistoryError) return;
    if (!message) {
      clawRunHistoryError.hidden = true;
      clawRunHistoryError.textContent = "";
      clawRunHistoryError.removeAttribute("data-state");
      return;
    }
    clawRunHistoryError.hidden = false;
    clawRunHistoryError.textContent = message;
    clawRunHistoryError.dataset.state = "error";
  }

  function clawRunHistoryErrorMessage(data, response) {
    const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
    const status = response ? response.status : 0;
    if (code === "unauthorized" || status === 401) return clawT("claw-error-auth-needed");
    return clawT("claw-runs-error");
  }

  // Unknown status tokens stay raw rather than being invented, so presentation
  // can never claim a completion the server did not report.
  function clawRunStatusLabel(status) {
    const raw = String(status || "");
    const key = `claw-runs-status-${raw}`;
    const text = uiT(key);
    return text === key ? raw : text;
  }

  function renderClawRunCard(run) {
    const card = document.createElement("div");
    card.className = "claw-run-card";
    card.dataset.runId = typeof run.run_id === "string" ? run.run_id : "";

    const head = document.createElement("div");
    head.className = "claw-run-card-head";
    const title = document.createElement("strong");
    title.className = "claw-run-card-title";
    title.textContent = typeof run.title === "string" ? run.title : "";
    const badge = document.createElement("span");
    badge.className = "claw-run-card-badge";
    badge.textContent = clawRunStatusLabel(run.status);
    head.append(title, badge);

    const meta = document.createElement("div");
    meta.className = "claw-run-card-meta";
    meta.textContent = [run.channel, run.action, run.created_at]
      .map((value) => (typeof value === "string" ? value : ""))
      .filter(Boolean)
      .join(" · ");

    const summary = document.createElement("p");
    summary.className = "claw-run-card-summary";
    summary.textContent = typeof run.result_summary === "string" ? run.result_summary : "";

    card.append(head, meta, summary);

    const artifact = run.artifact && typeof run.artifact.document_id === "string" ? run.artifact : null;
    if (artifact) {
      const artifactRow = document.createElement("div");
      artifactRow.className = "claw-run-card-artifact";
      const filename = document.createElement("span");
      filename.className = "claw-run-card-filename";
      filename.textContent = typeof artifact.filename === "string" ? artifact.filename : "";
      const downloadBtn = document.createElement("button");
      downloadBtn.type = "button";
      downloadBtn.className = "claw-run-card-download";
      downloadBtn.textContent = clawT("claw-runs-download");
      downloadBtn.addEventListener("click", () => {
        // Reuses the existing bounded artifact route through its single owner.
        if (artifact.document_id) downloadClawArtifact(artifact.document_id, artifact.filename || "");
      });
      artifactRow.append(filename, downloadBtn);
      card.appendChild(artifactRow);
    }
    return card;
  }

  // Unguarded fetch: callers hold the single-flight flag while awaiting this.
  async function fetchClawRunHistory() {
    if (!clawRunHistory) return;
    setClawRunHistoryStatus("");
    if (clawRunHistoryLoading) clawRunHistoryLoading.hidden = false;
    if (clawRunHistoryList) clawRunHistoryList.hidden = true;
    if (clawRunHistoryEmpty) clawRunHistoryEmpty.hidden = true;
    if (clawRunHistoryList) clawRunHistoryList.replaceChildren();
    try {
      const response = await fetch("/api/claw/runs?limit=10", { headers: { "Accept": "application/json" }, cache: "no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || data.ok !== true || !Array.isArray(data.runs)) {
        throw new Error(clawRunHistoryErrorMessage(data, response));
      }
      if (clawRunHistoryLoading) clawRunHistoryLoading.hidden = true;
      if (data.runs.length === 0) {
        // Empty history must not leave an empty list container visible.
        if (clawRunHistoryEmpty) clawRunHistoryEmpty.hidden = false;
        return;
      }
      if (clawRunHistoryList) clawRunHistoryList.hidden = false;
      data.runs.forEach((run) => {
        if (!run || typeof run.run_id !== "string") return;
        clawRunHistoryList?.appendChild(renderClawRunCard(run));
      });
    } catch (error) {
      if (clawRunHistoryLoading) clawRunHistoryLoading.hidden = true;
      setClawRunHistoryStatus(error instanceof Error ? error.message : clawT("claw-runs-error"));
    }
  }

  async function loadClawRunHistory() {
    if (clawRunHistoryInFlight) return;
    clawRunHistoryInFlight = true;
    try {
      await fetchClawRunHistory();
    } finally {
      clawRunHistoryInFlight = false;
    }
  }

  function syncClawRunHistoryVisibility() {
    if (!clawRunHistory) return;
    // Owner-authenticated surface only, and never inside the inbox view.
    const show = authState.authenticated === true
      && shell.dataset.state === "claw"
      && clawWorkspace?.dataset.view !== "inbox";
    clawRunHistory.hidden = !show;
    if (show) loadClawRunHistory();
  }

  if (clawRunHistoryRefresh) {
    clawRunHistoryRefresh.addEventListener("click", () => loadClawRunHistory());
  }
})();
