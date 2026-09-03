(() => {
  "use strict";

  const VALID_LOCALES = ["ko", "en"];
  const attachmentCapabilities = window.PadiemAttachmentCapabilities;
  const nativeConfirm = typeof window.confirm === "function" ? window.confirm.bind(window) : null;
  let observer = null;

  const labels = {
    ko: {
      "new-chat": "새 채팅", "search": "검색", "projects": "프로젝트", "saved": "저장한 답변", "recent": "추천 질문",
      "easy": "AI를 쉽게 설명해줘", "trip": "제주도 여행 계획", "dinner": "저녁 메뉴 추천", "close-menu": "메뉴 닫기", "open-menu": "메뉴 열기",
      "mode": "기본 대화", "theme": "테마", "light": "Light", "dark": "Dark", "cinematic": "Cinematic", "home-theme": "Padiem Home", "glass-theme": "Padiem Glass",
      "home-link": "Padiem Home", "settings": "설정", "settings-kicker": "Padiem Chat", "appearance": "APPEARANCE", "language": "LANGUAGE", "language-choice": "언어", "done": "완료",
      "korean": "한국어", "english": "English", "login": "로그인", "logout": "로그아웃", "hello": "안녕하세요.", "ask": "무엇을 도와드릴까요?",
      "copy": "궁금한 것을 평소 말하듯 편하게 물어보세요.", "easy-title": "쉽게 설명해줘", "easy-copy": "어려운 내용도 쉬운 말로",
      "life-title": "생활 도움", "life-copy": "일상 질문과 계획 세우기", "document-title": "문서와 대화",
      "input": "무엇이든 물어보세요", "file": "파일", "web": "웹 검색", "research": "심층 리서치", "footer": "편하게 질문해 보세요",
      "main-menu": "주요 메뉴", "chat-menu": "채팅 메뉴", "account-settings": "계정 및 설정", "home-aria": "Padiem Chat 홈", "home-open": "Padiem Home 열기",
      "coming-soon": "준비 중", "login-after": "로그인 후", "checking": "확인 중", "setup-needed": "설정 필요", "empty": "비어 있음", "create-new": "새로 만들기",
      "projects-empty": "아직 프로젝트가 없습니다.", "history-title": "최근 대화", "history-empty": "저장된 대화가 없습니다.", "outputs-empty": "저장한 답변이 없습니다.",
      "create-project-aria": "새 프로젝트 만들기", "login-unavailable-title": "로그인 기능이 설정되지 않았습니다", "login-title": "Google 계정으로 로그인합니다", "logout-title": "현재 계정에서 로그아웃합니다",
      "settings-close": "설정 닫기", "theme-picker": "테마 선택", "language-picker": "언어 선택", "starter-grid": "추천 질문", "web-starter-title": "웹에서 찾아줘", "web-starter-copy": "웹 검색 · 준비 중",
      "composer": "메시지 작성", "project-banner": "프로젝트", "project-edit": "지침·파일", "project-exit": "나가기", "attachment-preview-alt": "선택한 사진 미리보기", "attachment-remove": "첨부 파일 제거",
      "message-input-label": "메시지 입력", "web-unavailable-title": "웹 검색은 준비 중입니다", "research-unavailable-title": "심층 리서치는 현재 사용할 수 없습니다", "cancel": "취소", "cancel-answer": "답변 생성 취소", "send": "메시지 보내기",
      "project-new": "새 프로젝트", "project-edit-title": "프로젝트 지침·파일", "project-close": "프로젝트 창 닫기", "project-name": "프로젝트 이름", "project-name-placeholder": "예: 제주 가족여행",
      "project-instructions": "프로젝트 지침", "optional": "선택", "project-instructions-placeholder": "예: 부모님과 함께 보는 내용이라 쉬운 한국어로 설명해줘.", "project-instructions-note": "이 지침은 이 프로젝트의 대화에만 적용됩니다.",
      "project-files": "프로젝트 파일", "project-files-limit": "TXT·Markdown·CSV·JSON · 최대 12개", "project-file-add": "＋ 파일 추가", "project-files-empty": "저장된 프로젝트 파일이 없습니다.",
      "project-files-note": "프로젝트 파일 저장은 TXT·Markdown·CSV·JSON만 지원합니다. Composer 첨부와 달리 PDF·DOCX·PPTX·XLSX는 저장하지 않습니다.", "save": "저장", "delete": "삭제", "manage": "관리",
      "saved-output-title": "저장한 답변", "saved-output-close": "저장한 답변 닫기", "title": "제목", "saved-output-content": "저장한 답변 내용", "copy-action": "복사", "download": "다운로드", "save-title": "제목 저장",
      "answer-preparing": "답변 준비 중", "stored-conversation": "저장된 대화", "mock-response": "모의 응답 · 실제 모델 호출 없음", "ai-response": "AI 응답", "route-question": "어떤 AI가 답했나요?",
      "retry": "다시 시도", "retry-failed": "답변을 불러오지 못했습니다.", "retry-later": "잠시 후 다시 시도해 주세요.", "timeout": "응답 시간 초과", "connection-error": "연결 오류", "cancelled": "생성 취소됨", "regenerate": "다시 생성",
      "cancelled-detail": "생성 중인 답변을 취소했습니다. 완성되지 않은 내용은 저장하거나 내보낼 수 없습니다.", "cancelled-note": "답변 생성을 취소했습니다. 완성되지 않은 내용은 저장하거나 내보낼 수 없습니다.",
      "image-once": "선택한 사진은 이 질문과 함께 한 번만 전송됩니다.", "document-once": "선택한 문서는 이 질문의 참고 자료로만 사용되며 대화 기록에 파일 내용이 저장되지 않습니다.",
      "project-delete": "프로젝트 삭제", "project-delete-aria": "현재 프로젝트 삭제", "code": "코드", "table": "표", "csv-download": "CSV 다운로드", "sources": "출처", "sources-aria": "답변 출처",
      "answer-actions": "답변 작업", "copied": "복사됨", "copy-failed": "복사 실패", "saved-state": "저장됨", "save-failed": "저장 실패", "export": "대화 내보내기", "export-aria": "현재 대화를 텍스트 파일로 내보내기",
      "glass-background": "Padiem Glass 배경", "glass-background-selection": "Padiem Glass 배경 선택", "glass-a": "배경 A", "glass-b": "배경 B"
    },
    en: {
      "new-chat": "New chat", "search": "Search", "projects": "Projects", "saved": "Saved answers", "recent": "Suggested questions",
      "easy": "Explain AI simply", "trip": "Plan a Jeju trip", "dinner": "Suggest dinner", "close-menu": "Close menu", "open-menu": "Open menu",
      "mode": "Standard chat", "theme": "Theme", "light": "Light", "dark": "Dark", "cinematic": "Cinematic", "home-theme": "Padiem Home", "glass-theme": "Padiem Glass",
      "home-link": "Padiem Home", "settings": "Settings", "settings-kicker": "Padiem Chat", "appearance": "APPEARANCE", "language": "LANGUAGE", "language-choice": "Language", "done": "Done",
      "korean": "한국어", "english": "English", "login": "Log in", "logout": "Log out", "hello": "Hello.", "ask": "What can I help you with?",
      "copy": "Ask anything in your own words.", "easy-title": "Explain simply", "easy-copy": "Make difficult ideas easy",
      "life-title": "Everyday help", "life-copy": "Questions and planning", "document-title": "Chat with documents",
      "input": "Ask anything", "file": "File", "web": "Web search", "research": "Deep research", "footer": "Ask comfortably",
      "main-menu": "Main menu", "chat-menu": "Chat menu", "account-settings": "Account and settings", "home-aria": "Padiem Chat home", "home-open": "Open Padiem Home",
      "coming-soon": "Coming soon", "login-after": "Log in first", "checking": "Checking", "setup-needed": "Setup needed", "empty": "Empty", "create-new": "Create new",
      "projects-empty": "No projects yet.", "history-title": "Recent conversations", "history-empty": "No saved conversations.", "outputs-empty": "No saved answers.",
      "create-project-aria": "Create a new project", "login-unavailable-title": "Login is not configured", "login-title": "Log in with your Google account", "logout-title": "Log out of the current account",
      "settings-close": "Close settings", "theme-picker": "Theme selection", "language-picker": "Language selection", "starter-grid": "Suggested prompts", "web-starter-title": "Search the web", "web-starter-copy": "Web search · coming soon",
      "composer": "Message composer", "project-banner": "Project", "project-edit": "Instructions & files", "project-exit": "Exit", "attachment-preview-alt": "Selected image preview", "attachment-remove": "Remove attachment",
      "message-input-label": "Message input", "web-unavailable-title": "Web search is coming soon", "research-unavailable-title": "Deep research is currently unavailable", "cancel": "Cancel", "cancel-answer": "Cancel answer generation", "send": "Send message",
      "project-new": "New project", "project-edit-title": "Project instructions & files", "project-close": "Close project dialog", "project-name": "Project name", "project-name-placeholder": "e.g. Jeju family trip",
      "project-instructions": "Project instructions", "optional": "Optional", "project-instructions-placeholder": "e.g. Explain in simple language so my family can follow.", "project-instructions-note": "These instructions apply only to conversations in this project.",
      "project-files": "Project files", "project-files-limit": "TXT · Markdown · CSV · JSON · up to 12", "project-file-add": "+ Add file", "project-files-empty": "No saved project files.",
      "project-files-note": "Project file storage supports TXT, Markdown, CSV, and JSON only. Unlike composer attachments, PDF, DOCX, PPTX, and XLSX are not stored.", "save": "Save", "delete": "Delete", "manage": "Manage",
      "saved-output-title": "Saved answer", "saved-output-close": "Close saved answer", "title": "Title", "saved-output-content": "Saved answer content", "copy-action": "Copy", "download": "Download", "save-title": "Save title",
      "answer-preparing": "Preparing answer", "stored-conversation": "Saved conversation", "mock-response": "Preview response · no live model call", "ai-response": "AI response", "route-question": "Which AI answered?",
      "retry": "Try again", "retry-failed": "Could not load the answer.", "retry-later": "Please try again shortly.", "timeout": "Response timed out", "connection-error": "Connection error", "cancelled": "Generation canceled", "regenerate": "Generate again",
      "cancelled-detail": "Answer generation was canceled. Incomplete content cannot be saved or exported.", "cancelled-note": "Answer generation canceled. Incomplete content cannot be saved or exported.",
      "image-once": "The selected image is sent only once with this question.", "document-once": "The selected document is used only as reference for this question; its contents are not stored in chat history.",
      "project-delete": "Delete project", "project-delete-aria": "Delete current project", "code": "Code", "table": "Table", "csv-download": "Download CSV", "sources": "Sources", "sources-aria": "Answer sources",
      "answer-actions": "Answer actions", "copied": "Copied", "copy-failed": "Copy failed", "saved-state": "Saved", "save-failed": "Save failed", "export": "Export conversation", "export-aria": "Export the current conversation as a text file",
      "glass-background": "Padiem Glass background", "glass-background-selection": "Padiem Glass background selection", "glass-a": "Background A", "glass-b": "Background B"
    }
  };

  const promptCopy = {
    ko: {
      explain: "AI를 아주 쉽게 설명해줘",
      trip: "3박 4일 제주도 가족 여행 계획을 짜줘",
      dinner: "오늘 저녁 메뉴를 세 가지 추천해줘",
      starterExplain: "AI를 처음 쓰는 사람에게 AI가 뭔지 아주 쉽게 설명해줘",
      starterLife: "이번 주말 가족과 집 근처에서 할 만한 일을 추천해줘"
    },
    en: {
      explain: "Explain AI in very simple terms.",
      trip: "Plan a four-day family trip to Jeju.",
      dinner: "Suggest three dinner ideas for tonight.",
      starterExplain: "Explain what AI is in very simple terms for someone using it for the first time.",
      starterLife: "Suggest things my family can do near home this weekend."
    }
  };

  const exactPairs = [
    ["프로젝트 삭제", "Delete project"], ["관리", "Manage"], ["삭제", "Delete"], ["저장", "Save"], ["복사", "Copy"], ["다운로드", "Download"],
    ["답변 준비 중", "Preparing answer"], ["저장된 대화", "Saved conversation"], ["모의 응답 · 실제 모델 호출 없음", "Preview response · no live model call"], ["AI 응답", "AI response"],
    ["어떤 AI가 답했나요?", "Which AI answered?"], ["다시 시도", "Try again"], ["답변을 불러오지 못했습니다.", "Could not load the answer."], ["잠시 후 다시 시도해 주세요.", "Please try again shortly."],
    ["응답 시간 초과", "Response timed out"], ["연결 오류", "Connection error"], ["생성 취소됨", "Generation canceled"], ["다시 생성", "Generate again"],
    ["생성 중인 답변을 취소했습니다. 완성되지 않은 내용은 저장하거나 내보낼 수 없습니다.", "Answer generation was canceled. Incomplete content cannot be saved or exported."],
    ["답변 생성을 취소했습니다. 완성되지 않은 내용은 저장하거나 내보낼 수 없습니다.", "Answer generation canceled. Incomplete content cannot be saved or exported."],
    ["선택한 사진은 이 질문과 함께 한 번만 전송됩니다.", "The selected image is sent only once with this question."],
    ["선택한 문서는 이 질문의 참고 자료로만 사용되며 대화 기록에 파일 내용이 저장되지 않습니다.", "The selected document is used only as reference for this question; its contents are not stored in chat history."],
    ["설정 필요", "Setup needed"], ["로그인 후", "Log in first"], ["확인 중", "Checking"], ["새로 만들기", "Create new"], ["비어 있음", "Empty"],
    ["프로젝트 지침·파일", "Project instructions & files"], ["새 프로젝트", "New project"], ["복사됨", "Copied"], ["복사 실패", "Copy failed"], ["저장됨", "Saved"], ["저장 실패", "Save failed"],
    ["코드", "Code"], ["표", "Table"], ["CSV 다운로드", "Download CSV"], ["출처", "Sources"], ["대화 내보내기", "Export conversation"],
    ["웹 검색 사용 중 · 누르면 해제합니다", "Web search active · click to turn off"], ["다음 질문을 웹에서 찾아 출처와 함께 답합니다", "Search the web for the next question and answer with sources"],
    ["최신 정보 · 출처와 함께", "Current information · with sources"], ["다음 질문에서 사용", "Use for the next question"], ["웹 검색은 현재 사용할 수 없습니다", "Web search is currently unavailable"],
    ["심층 리서치 사용 중 · 누르면 해제합니다", "Deep research active · click to turn off"], ["여러 검색과 출처를 비교해 다음 질문에 답합니다", "Compare multiple searches and sources for the next question"],
    ["심층 리서치는 현재 사용할 수 없습니다", "Deep research is currently unavailable"], ["답변 작업", "Answer actions"]
  ];

  function normalizeLocale(value) {
    return VALID_LOCALES.includes(value) ? value : null;
  }

  function getUrlLocale() {
    try {
      return normalizeLocale(new URLSearchParams(window.location.search).get("lang"));
    } catch (_) {
      return null;
    }
  }

  function getCurrent() {
    return document.documentElement.lang === "en" ? "en" : "ko";
  }

  function text(key, lang = getCurrent(), variables = null) {
    const locale = normalizeLocale(lang) || "ko";
    let value = labels[locale][key] || labels.ko[key] || key;
    if (variables && typeof variables === "object") {
      Object.entries(variables).forEach(([name, replacement]) => {
        value = value.replaceAll(`{${name}}`, String(replacement));
      });
    }
    return value;
  }

  function setText(selector, key, lang) {
    const element = document.querySelector(selector);
    if (element && element.textContent !== text(key, lang)) element.textContent = text(key, lang);
  }

  function setAttribute(selector, attribute, key, lang) {
    const element = document.querySelector(selector);
    if (!element) return;
    const value = text(key, lang);
    if (element.getAttribute(attribute) !== value) element.setAttribute(attribute, value);
  }

  function setPrompt(selector, key, lang) {
    const element = document.querySelector(selector);
    if (!element) return;
    const value = promptCopy[lang][key];
    if (value && element.dataset.prompt !== value) element.dataset.prompt = value;
  }

  function setCombinedHeading(lang) {
    const heading = document.querySelector(".empty-state h1");
    if (!heading) return;
    const first = text("hello", lang);
    const second = text("ask", lang);
    if (heading.dataset.localeRendered === lang && heading.textContent === `${first}${second}`) return;
    const br = document.createElement("br");
    heading.replaceChildren(document.createTextNode(first), br, document.createTextNode(second));
    heading.dataset.localeRendered = lang;
  }

  function applyStaticBindings(lang) {
    const textBindings = [
      ["#newChatButton span:last-child", "new-chat"], [".side-item:nth-child(1) span:nth-child(2)", "search"], ["#projectsNavButton span:nth-child(2)", "projects"], ["#outputsNavButton span:nth-child(2)", "saved"],
      ["#recentTitle", "recent"], [".recent-item:nth-of-type(1)", "easy"], [".recent-item:nth-of-type(2)", "trip"], [".recent-item:nth-of-type(3)", "dinner"], [".model-pill span:last-child", "mode"],
      ["#loginButton", "login"], [".empty-copy", "copy"], [".starter:nth-child(1) strong", "easy-title"], [".starter:nth-child(1) small", "easy-copy"], [".starter:nth-child(2) strong", "life-title"], [".starter:nth-child(2) small", "life-copy"],
      [".starter:nth-child(3) strong", "document-title"], ["#attachmentButton span:last-child", "file"], [".sidebar-footer span:last-child", "footer"], [".side-item:nth-child(1) .mini-badge", "coming-soon"],
      ["#projectsTitle", "projects"], ["#projectsEmpty", "projects-empty"], ["#historyTitle", "history-title"], ["#historyEmpty", "history-empty"], ["#outputsTitle", "saved"], ["#outputsEmpty", "outputs-empty"],
      [".starter:nth-child(4) strong", "web-starter-title"], [".starter:nth-child(4) small", "web-starter-copy"], [".project-banner-copy > span", "project-banner"], ["#editProjectButton", "project-edit"], ["#exitProjectButton", "project-exit"],
      ["#projectDialogTitle", "project-new"], ["label[for='projectNameInput']", "project-name"], ["#projectFilesTitle", "project-files"], [".project-files-heading small", "project-files-limit"], [".project-file-add", "project-file-add"],
      ["#projectFilesEmpty", "project-files-empty"], [".project-files-note", "project-files-note"], ["#projectDialogCancel", "cancel"], ["#projectSaveButton", "save"],
      ["#savedOutputDialogTitle", "saved-output-title"], ["label[for='savedOutputTitleInput']", "title"], ["#savedOutputCopy", "copy-action"], ["#savedOutputDownload", "download"], ["#savedOutputRename", "save-title"], ["#savedOutputDelete", "delete"],
      ["#cancelStreamButton", "cancel"]
    ];
    textBindings.forEach(([selector, key]) => setText(selector, key, lang));

    document.querySelectorAll("[data-locale-key]").forEach((element) => {
      const key = element.dataset.localeKey;
      if (key && element.textContent !== text(key, lang)) element.textContent = text(key, lang);
    });

    setCombinedHeading(lang);
    const input = document.getElementById("messageInput");
    if (input && input.placeholder !== text("input", lang)) input.placeholder = text("input", lang);
    const projectName = document.getElementById("projectNameInput");
    if (projectName) projectName.placeholder = text("project-name-placeholder", lang);
    const projectInstructions = document.getElementById("projectInstructionsInput");
    if (projectInstructions) projectInstructions.placeholder = text("project-instructions-placeholder", lang);

    const instructionLabel = document.querySelector("label[for='projectInstructionsInput']");
    if (instructionLabel) {
      const optional = instructionLabel.querySelector("span") || document.createElement("span");
      instructionLabel.replaceChildren(document.createTextNode(`${text("project-instructions", lang)} `), optional);
      optional.textContent = text("optional", lang);
    }
    setText(".project-form-note", "project-instructions-note", lang);

    [
      ["#sidebar", "aria-label", "main-menu"], ["#mobileClose", "aria-label", "close-menu"], [".brand", "aria-label", "home-aria"], [".home-link", "aria-label", "home-open"], [".side-nav", "aria-label", "chat-menu"],
      ["#projectCreateButton", "aria-label", "create-project-aria"], [".sidebar-bottom", "aria-label", "account-settings"], ["#mobileMenu", "aria-label", "open-menu"], [".model-pill", "aria-label", "mode"], ["#settingsCloseButton", "aria-label", "settings-close"],
      ["#themePicker", "aria-label", "theme-picker"], ["#languagePicker", "aria-label", "language-picker"], [".starter-grid", "aria-label", "starter-grid"], [".composer-wrap", "aria-label", "composer"], ["#attachmentThumb", "alt", "attachment-preview-alt"],
      ["#removeAttachment", "aria-label", "attachment-remove"], ["label[for='messageInput']", "textContent", "message-input-label"], [".composer-tools .tool-button:nth-of-type(2)", "title", "web-unavailable-title"], ["#deepResearchButton", "title", "research-unavailable-title"],
      ["#cancelStreamButton", "aria-label", "cancel-answer"], ["#sendButton", "aria-label", "send"], ["#projectDialogClose", "aria-label", "project-close"], ["#savedOutputClose", "aria-label", "saved-output-close"], ["#savedOutputContent", "aria-label", "saved-output-content"]
    ].forEach(([selector, attribute, key]) => {
      if (attribute === "textContent") setText(selector, key, lang);
      else setAttribute(selector, attribute, key, lang);
    });

    setPrompt(".recent-item:nth-of-type(1)", "explain", lang);
    setPrompt(".recent-item:nth-of-type(2)", "trip", lang);
    setPrompt(".recent-item:nth-of-type(3)", "dinner", lang);
    setPrompt(".starter:nth-child(1)", "starterExplain", lang);
    setPrompt(".starter:nth-child(2)", "starterLife", lang);
  }

  function syncAttachmentCapabilityCopy(lang) {
    if (!attachmentCapabilities) return;
    const capabilityCopy = attachmentCapabilities.copy(lang);
    const documentCopy = document.querySelector(".starter:nth-child(3) small");
    if (documentCopy) documentCopy.textContent = capabilityCopy.documentFormats;
    const attachmentInput = document.getElementById("attachmentFileInput");
    if (attachmentInput) attachmentInput.accept = attachmentCapabilities.accept;
    const attachmentButton = document.getElementById("attachmentButton");
    if (attachmentButton) attachmentButton.title = capabilityCopy.fileButtonTitle;
  }

  function syncGlassCopy(lang) {
    const glassTheme = document.querySelector('[data-theme-value="padiem-glass"]');
    if (glassTheme) glassTheme.textContent = text("glass-theme", lang);
    const label = document.querySelector(".glass-variant-label");
    if (label) label.textContent = text("glass-background", lang);
    const group = document.querySelector(".glass-variant-picker");
    if (group) group.setAttribute("aria-label", text("glass-background-selection", lang));
    const a = document.querySelector('[data-glass-variant-value="female"]');
    const b = document.querySelector('[data-glass-variant-value="male"]');
    if (a) a.textContent = text("glass-a", lang);
    if (b) b.textContent = text("glass-b", lang);
  }

  function exactTranslation(value, lang) {
    const raw = String(value || "").trim();
    for (const [ko, en] of exactPairs) {
      if (raw === ko || raw === en) return lang === "en" ? en : ko;
    }
    return null;
  }

  function translatedRuntimeString(value, lang) {
    const raw = String(value || "");
    const exact = exactTranslation(raw, lang);
    if (exact) return exact;
    let match = raw.match(/^프로젝트 파일 (\d+)개를 참고했습니다\.$|^Used (\d+) project files\.$/);
    if (match) {
      const count = match[1] || match[2];
      return lang === "en" ? `Used ${count} project files.` : `프로젝트 파일 ${count}개를 참고했습니다.`;
    }
    match = raw.match(/^파일 (\d+)개$|^(\d+) files$/);
    if (match) {
      const count = match[1] || match[2];
      return lang === "en" ? `${count} files` : `파일 ${count}개`;
    }
    match = raw.match(/^심층 리서치 · 검색 (\d+)회 · 출처 (\d+)개( · 일부 자료는 가져오지 못했습니다)?$|^Deep research · (\d+) searches · (\d+) sources( · some sources unavailable)?$/);
    if (match) {
      const searches = match[1] || match[4];
      const sources = match[2] || match[5];
      const partial = Boolean(match[3] || match[6]);
      return lang === "en"
        ? `Deep research · ${searches} searches · ${sources} sources${partial ? " · some sources unavailable" : ""}`
        : `심층 리서치 · 검색 ${searches}회 · 출처 ${sources}개${partial ? " · 일부 자료는 가져오지 못했습니다" : ""}`;
    }
    return raw;
  }

  function syncLoginButton(lang) {
    const button = document.getElementById("loginButton");
    if (!button) return;
    const raw = button.textContent.trim();
    if (raw === "로그아웃" || raw === "Log out") button.dataset.authenticated = "true";
    else if (raw === "로그인" || raw === "Log in") button.dataset.authenticated = "false";
    const authenticated = button.dataset.authenticated === "true";
    button.textContent = authenticated ? text("logout", lang) : text("login", lang);
    button.title = button.disabled
      ? text("login-unavailable-title", lang)
      : authenticated ? text("logout-title", lang) : text("login-title", lang);
  }

  function localizeFirstPartyElement(element, lang) {
    if (!(element instanceof Element)) return;
    if (element.id === "loginButton") {
      syncLoginButton(lang);
      return;
    }

    const translationTargets = [
      ".project-manage", ".project-file-row button", ".history-delete", "#projectDeleteButton", ".demo-label[data-runtime-label]", ".route-details summary", ".reference-note",
      ".retry-button", ".error-box strong", ".error-box p", "#runtimeNote", "#projectFormError", ".answer-actions", ".answer-action", ".saved-output-status",
      ".rich-code-header > span", ".rich-code-copy", ".rich-table-actions > span", ".rich-table-download", ".answer-sources-title", ".research-summary", "#conversationExportButton"
    ];
    if (translationTargets.some((selector) => element.matches(selector))) {
      const next = translatedRuntimeString(element.textContent, lang);
      if (next !== element.textContent) element.textContent = next;
    }

    if (element.matches("#projectDeleteButton")) element.setAttribute("aria-label", text("project-delete-aria", lang));
    if (element.matches("#conversationExportButton")) element.setAttribute("aria-label", text("export-aria", lang));
    if (element.matches(".answer-actions")) element.setAttribute("aria-label", text("answer-actions", lang));
    if (element.matches(".answer-sources")) element.setAttribute("aria-label", text("sources-aria", lang));
    if (element.matches(".typing")) element.setAttribute("aria-label", text("answer-preparing", lang));

    if (element.matches(".project-manage") && element.getAttribute("aria-label")) {
      const name = element.closest(".project-row")?.querySelector(".project-item")?.textContent || "";
      if (name) element.setAttribute("aria-label", lang === "en" ? `Manage project ‘${name}’` : `‘${name}’ 프로젝트 관리`);
    }
    if (element.matches(".history-delete") && element.getAttribute("aria-label")) {
      const title = element.closest(".history-row")?.querySelector(".history-item")?.textContent || "";
      if (title) element.setAttribute("aria-label", lang === "en" ? `Delete conversation ‘${title}’` : `‘${title}’ 대화 삭제`);
    }
  }

  function localizeDynamicTree(root, lang) {
    if (!(root instanceof Element)) return;
    localizeFirstPartyElement(root, lang);
    root.querySelectorAll(
      ".project-manage,.project-file-row button,.history-delete,#projectDeleteButton,.demo-label[data-runtime-label],.route-details summary,.reference-note,.retry-button,.error-box strong,.error-box p,#runtimeNote,#projectFormError,.answer-actions,.answer-action,.saved-output-status,.rich-code-header>span,.rich-code-copy,.rich-table-actions>span,.rich-table-download,.answer-sources,.answer-sources-title,.research-summary,#conversationExportButton,.typing"
    ).forEach((element) => localizeFirstPartyElement(element, lang));
  }

  function localizeSelectedAttachmentNote(lang) {
    const tray = document.getElementById("attachmentTray");
    const note = document.getElementById("runtimeNote");
    if (!tray || tray.hidden || !note) return;
    const thumb = document.getElementById("attachmentThumb");
    note.textContent = thumb && !thumb.hidden ? text("image-once", lang) : text("document-once", lang);
  }

  function translateConfirmMessage(message, lang) {
    const raw = String(message || "");
    let match = raw.match(/^‘(.+)’ 파일을 프로젝트에서 삭제할까요\?$|^Remove ‘(.+)’ from this project\?$/);
    if (match) {
      const name = match[1] || match[2];
      return lang === "en" ? `Remove ‘${name}’ from this project?` : `‘${name}’ 파일을 프로젝트에서 삭제할까요?`;
    }
    match = raw.match(/^‘(.+)’ 대화를 삭제할까요\?\n삭제한 대화는 되돌릴 수 없습니다\.$|^Delete conversation ‘(.+)’\?\nThis cannot be undone\.$/);
    if (match) {
      const title = match[1] || match[2];
      return lang === "en" ? `Delete conversation ‘${title}’?\nThis cannot be undone.` : `‘${title}’ 대화를 삭제할까요?\n삭제한 대화는 되돌릴 수 없습니다.`;
    }
    match = raw.match(/^‘(.+)’ 프로젝트를 삭제할까요\?\n프로젝트의 대화는 남지만 프로젝트 연결은 해제됩니다\. 삭제한 프로젝트는 되돌릴 수 없습니다\.$|^Delete project ‘(.+)’\?\nIts conversations remain, but the project link is removed\. This cannot be undone\.$/);
    if (match) {
      const name = match[1] || match[2];
      return lang === "en"
        ? `Delete project ‘${name}’?\nIts conversations remain, but the project link is removed. This cannot be undone.`
        : `‘${name}’ 프로젝트를 삭제할까요?\n프로젝트의 대화는 남지만 프로젝트 연결은 해제됩니다. 삭제한 프로젝트는 되돌릴 수 없습니다.`;
    }
    if (raw === "이 저장한 답변을 삭제할까요? 원래 대화는 삭제되지 않습니다." || raw === "Delete this saved answer? The original conversation will remain.") {
      return lang === "en" ? "Delete this saved answer? The original conversation will remain." : "이 저장한 답변을 삭제할까요? 원래 대화는 삭제되지 않습니다.";
    }
    return raw;
  }

  function installConfirmLocalization() {
    if (!nativeConfirm || window.confirm.__padiemLocalized === true) return;
    const localizedConfirm = (message) => nativeConfirm(translateConfirmMessage(message, getCurrent()));
    localizedConfirm.__padiemLocalized = true;
    window.confirm = localizedConfirm;
  }

  function persistLocale(lang) {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get("lang") === lang) return;
      url.searchParams.set("lang", lang);
      history.replaceState(null, "", url.toString());
    } catch (_) {}
  }

  function apply(lang, persist = false) {
    const locale = normalizeLocale(lang) || "ko";
    document.documentElement.lang = locale;
    if (persist) persistLocale(locale);
    applyStaticBindings(locale);
    syncAttachmentCapabilityCopy(locale);
    syncGlassCopy(locale);
    syncLoginButton(locale);
    localizeDynamicTree(document.body, locale);
    localizeSelectedAttachmentNote(locale);
    document.querySelectorAll("[data-locale-value]").forEach((button) => {
      const active = button.dataset.localeValue === locale;
      button.setAttribute("aria-pressed", String(active));
      if (active) button.setAttribute("aria-current", "true"); else button.removeAttribute("aria-current");
    });
    window.dispatchEvent(new CustomEvent("padiem:localechange", { detail: { lang: locale } }));
    return locale;
  }

  function observeDynamicUi() {
    if (observer || !document.body) return;
    observer = new MutationObserver((mutations) => {
      const lang = getCurrent();
      mutations.forEach((mutation) => {
        if (mutation.type === "characterData") {
          if (mutation.target.parentElement) localizeFirstPartyElement(mutation.target.parentElement, lang);
          return;
        }
        if (mutation.target instanceof Element) localizeFirstPartyElement(mutation.target, lang);
        mutation.addedNodes.forEach((node) => {
          if (node instanceof Element) localizeDynamicTree(node, lang);
          else if (node.parentElement) localizeFirstPartyElement(node.parentElement, lang);
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["title", "aria-label", "disabled"] });
  }

  function init() {
    installConfirmLocalization();
    apply(getUrlLocale() || "ko", false);
    observeDynamicUi();
    document.getElementById("languagePicker")?.addEventListener("click", (event) => {
      const button = event.target.closest("[data-locale-value]");
      const requested = button ? normalizeLocale(button.dataset.localeValue) : null;
      if (requested) apply(requested, true);
    });
    window.addEventListener("popstate", () => apply(getUrlLocale() || "ko", false));
  }

  window.__padiemLocale = {
    VALID: VALID_LOCALES.slice(),
    apply,
    getCurrent,
    getUrlLocale,
    text: (key, variables = null) => text(key, getCurrent(), variables),
    translateRuntime: (value) => translatedRuntimeString(value, getCurrent())
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true }); else init();
})();
