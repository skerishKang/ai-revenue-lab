/*
 * #7460 / #7461 / #7173 PR2 · Util tools inside the Util app (#util/speech,
 * #util/sns, #util/meeting).
 *
 * File boundary: screens live here (+ util-tools.css); field schemas come from
 * window.PadiemUtilManifest (util-manifest.js); conversational intake lives in
 * window.PadiemUtilChatMode (util-chat-mode.js); prompt shapes & stream calls
 * live in util-tools-contract.js. app.js gains nothing (R5 #7216).
 *
 * #7461 PR1 enables Form ↔ Conversation mode on "speech" (축사·인사말) first;
 * the remaining tools share the same PadiemUtilChatMode seam for the next PR.
 */
(() => {
  "use strict";

  const TOOL_KEYS = Object.freeze(["speech", "sns", "meeting"]);
  const CHAT_MODE_TOOLS = Object.freeze(["speech", "sns", "meeting"]);

  const T = Object.freeze({
    ko: Object.freeze({
      loginRequired: "로그인 후 이용할 수 있습니다.",
      loginUnknown: "로그인 상태를 확인하는 중입니다.",
      login: "로그인",
      required: "필수 항목을 입력해 주세요.",
      generating: "생성 중…",
      result: "생성 결과",
      emptyResult: "왼쪽 입력 칸을 채우고 생성을 누르면 여기에 초안이 표시됩니다.",
      copy: "복사",
      copied: "복사됨",
      copyFailed: "복사하지 못했습니다.",
      regenerate: "다시 만들기",
      saveLibrary: "라이브러리에 저장",
      savingLibrary: "저장 중…",
      savedLibrary: "라이브러리에 저장했습니다.",
      saveFailed: "문서를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      refineChat: "대화로 다듬기",
      more: "더 자세히 (날짜·장소·메시지·말투)",
      speechGenerate: "초안 생성",
      snsGenerate: "게시글 생성",
      meetingGenerate: "요약 생성",
      meetingResult: "회의 요약",
      platformGroup: "게시할 곳",
      pcImport: "내 PC에서 가져오기",
      pcImportNote: "컴퓨터를 연결하면 내 PC의 문서를 가져올 수 있습니다.",
      pcImportConnect: "컴퓨터 연결하기",
      pcImportUnsupported: "텍스트로 읽을 수 있는 파일만 가져올 수 있습니다(.txt, .md, .docx, .hwpx).",
      pcImportFailed: "PC에서 파일을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.",
      pcImportReplace: "이미 입력한 내용이 있습니다. PC에서 가져온 내용으로 바꿀까요?",
    }),
    en: Object.freeze({
      loginRequired: "Sign in to use this tool.",
      loginUnknown: "Checking your sign-in state.",
      login: "Sign in",
      required: "Fill in the required fields.",
      generating: "Generating…",
      result: "Result",
      emptyResult: "Fill in the fields and generate to see the draft here.",
      copy: "Copy",
      copied: "Copied",
      copyFailed: "Couldn’t copy.",
      regenerate: "Generate again",
      saveLibrary: "Save to library",
      savingLibrary: "Saving…",
      savedLibrary: "Saved to your library.",
      saveFailed: "We couldn’t save the document. Please try again in a moment.",
      refineChat: "Refine in chat",
      more: "More (date, place, message, tone)",
      speechGenerate: "Draft the address",
      snsGenerate: "Draft the post",
      meetingGenerate: "Summarize the meeting",
      meetingResult: "Meeting summary",
      platformGroup: "Where it goes",
      pcImport: "Import from my PC",
      pcImportNote: "Connect your computer to bring a document from your PC.",
      pcImportConnect: "Connect computer",
      pcImportUnsupported: "Only text-readable files can be imported (.txt, .md, .docx, .hwpx).",
      pcImportFailed: "We couldn’t read the file from your PC. Please try again in a moment.",
      pcImportReplace: "This field already has content. Replace it with the text from your PC?",
    }),
  });

  function lang() {
    return document.documentElement && document.documentElement.lang === "en" ? "en" : "ko";
  }

  function t(key) {
    const table = T[lang()] || T.ko;
    return table[key] !== undefined ? table[key] : T.ko[key];
  }

  function localized(entry) {
    if (!entry) return "";
    if (typeof entry === "string") return entry;
    return entry[lang()] || entry.ko || "";
  }

  // Live copy comes from the Chat locale table (KR/EN); this module's own table
  // keeps the surface readable when locale.js is not loaded (tests, harness).
  function localeText(key, fallback) {
    try {
      if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
        const value = window.__padiemLocale.text(key);
        if (value && value !== key) return value;
      }
    } catch (_) { /* the table is optional for a standalone mount */ }
    return fallback;
  }

  // Locale keys are the shipped table entries; the table below is the fallback.
  const LIBRARY_COPY = Object.freeze({
    save: () => localeText("util-library-save", t("saveLibrary")),
    saving: () => localeText("util-library-saving", t("savingLibrary")),
    saved: () => localeText("util-library-saved", t("savedLibrary")),
    failed: () => localeText("util-library-save-failed", t("saveFailed")),
  });

  const PC_COPY = Object.freeze({
    pick: () => localeText("util-pc-import", t("pcImport")),
    note: () => localeText("util-pc-import-note", t("pcImportNote")),
    connect: () => localeText("util-pc-import-connect", t("pcImportConnect")),
    unsupported: () => localeText("util-pc-import-unsupported", t("pcImportUnsupported")),
    failed: () => localeText("util-pc-import-failed", t("pcImportFailed")),
    replace: () => localeText("util-pc-import-replace", t("pcImportReplace")),
  });

  const PC_EXCHANGE_SCRIPT = "./pc-file-exchange.js";
  const PC_EXCHANGE_CSS = "./pc-file-exchange.css";
  const PC_REFERENCE = "/api/pc/reference";
  const PC_IMPORT_ACCEPT = Object.freeze([".txt", ".md", ".docx", ".hwpx"]);
  let pcExchangeLoading = null;

  function loadPcExchange() {
    if (window.PadiemPcFileExchange) return Promise.resolve(window.PadiemPcFileExchange);
    if (pcExchangeLoading) return pcExchangeLoading;
    pcExchangeLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      if (head && !document.querySelector('link[href="./pc-file-exchange.css"]')) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = PC_EXCHANGE_CSS;
        head.appendChild(css);
      }
      const script = document.createElement("script");
      script.src = PC_EXCHANGE_SCRIPT;
      script.addEventListener("load", () => {
        if (window.PadiemPcFileExchange) resolve(window.PadiemPcFileExchange);
        else reject(new Error("pc-exchange-unavailable"));
      }, { once: true });
      script.addEventListener("error", () => reject(new Error("pc-exchange-unavailable")), { once: true });
      head.appendChild(script);
    });
    return pcExchangeLoading;
  }

  async function pcLinked() {
    try {
      if (window.PadiemAuthGate && typeof window.PadiemAuthGate.authenticated === "function"
          && window.PadiemAuthGate.authenticated() === false) return null;
    } catch (_) {}
    try {
      const res = await window.fetch("/api/pc/pairings", { credentials: "include", cache: "no-store" });
      if (!res || !res.ok) return null;
      const body = await res.json().catch(() => null);
      const links = body && Array.isArray(body.links) ? body.links : [];
      return links.some((link) => link && link.state === "active");
    } catch (_) {
      return null;
    }
  }

  function openPcConnect() {
    const opener = document.getElementById("connectorsNavButton");
    if (opener) opener.click();
    const card = document.getElementById("connectorComputerCard");
    if (!card) return;
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
    if (typeof card.focus === "function") card.focus({ preventScroll: true });
    if (typeof card.scrollIntoView === "function") card.scrollIntoView({ block: "nearest" });
  }

  function pcSuffix(name) {
    const value = String(name || "");
    const dot = value.lastIndexOf(".");
    return dot < 0 ? "" : value.slice(dot).toLowerCase();
  }

  function pcAccepted(name) {
    return PC_IMPORT_ACCEPT.indexOf(pcSuffix(name)) >= 0;
  }

  async function readPcText(picked) {
    let res;
    try {
      res = await window.fetch(PC_REFERENCE, {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ file_id: picked.fileId }),
      });
    } catch (_) {
      return { ok: false, message: PC_COPY.failed() };
    }
    const body = await res.json().catch(() => null);
    if (!res.ok || !body || body.ok !== true || typeof body.text !== "string") {
      const code = body && body.error && body.error.code;
      return {
        ok: false,
        message: code === "legacy_hwp_unsupported" ? PC_COPY.unsupported() : PC_COPY.failed(),
      };
    }
    return { ok: true, text: body.text, name: body.name || picked.name };
  }

  async function pickPcText() {
    if (await pcLinked() !== true) return { needPc: true };
    let component;
    try {
      component = await loadPcExchange();
    } catch (_) {
      component = null;
    }
    if (!component || typeof component.open !== "function") return { needPc: true };
    return new Promise((resolve) => {
      component.open({
        mode: "import",
        accept: PC_IMPORT_ACCEPT.slice(),
        onSelect: (picked) => {
          void (async () => {
            if (!picked || typeof picked.fileId !== "string" || !picked.fileId) {
              resolve({ ok: false, message: PC_COPY.failed() });
              return;
            }
            if (!pcAccepted(picked.name)) {
              resolve({ ok: false, message: PC_COPY.unsupported() });
              return;
            }
            resolve(await readPcText(picked));
          })();
        },
      });
    });
  }

  function toolName(toolId) {
    const reg = window.PadiemUtilManifest;
    const tool = reg && typeof reg.getTool === "function" ? reg.getTool(toolId) : null;
    return localized(tool && tool.name) || String(toolId || "");
  }

  // ── 라이브러리에 저장 (#7501) ──────────────────────────────────────────
  // No second store and no second API: the owner-scoped project-file path the
  // Chat library already reads is the only sink — POST /api/projects/{pid}/files
  // writes the row the Library lists through /api/project-files. These three
  // tools keep ONE home: the Chat util's own pinned project "유틸". The council
  // app is a different site and pins its own project
  // (apps/padiem-council-apps/static/council-app.js, COUNCIL_PROJECT_NAME), so a
  // Chat util result must never surface as that project in a Chat user's
  // project list (#7501 후속). The Library groups the rows by doc_kind. A
  // failed project read is not "there are no projects", so no create follows it.
  const LIBRARY_PROJECT_NAME = "유틸";

  const libraryProject = (() => {
    let currentPid = null;
    let pending = null;
    async function resolve() {
      let list;
      try { list = await window.fetch("/api/projects", { credentials: "include" }); } catch (_) { return null; }
      if (!list || !list.ok) return null;
      const data = await list.json().catch(() => null);
      const projects = data && Array.isArray(data.projects) ? data.projects : null;
      if (projects === null) return null;
      const pinned = projects.find((p) => p && p.name === LIBRARY_PROJECT_NAME);
      if (pinned && pinned.id) return pinned.id;
      let created;
      try {
        created = await window.fetch("/api/projects", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: LIBRARY_PROJECT_NAME }),
        });
      } catch (_) { return null; }
      if (!created || !created.ok) return null;
      const payload = await created.json().catch(() => null);
      return payload && payload.project && payload.project.id ? payload.project.id : null;
    }
    return {
      ensure() {
        if (currentPid) return Promise.resolve(currentPid);
        // One shared promise: opening two tool screens must not race two reads
        // (or two creates) for the same project.
        if (!pending) {
          pending = resolve().then(
            (pid) => { currentPid = pid || null; if (!pid) pending = null; return pid; },
            () => { pending = null; return null; },
          );
        }
        return pending;
      },
    };
  })();

  function pad2(value) { return String(value).padStart(2, "0"); }

  // 제목 = 도구 이름 + 날짜. 확장자는 기존 저장 경로가 받는 .txt 그대로다.
  function libraryTitle(toolId) {
    const now = new Date();
    const stamp = now.getFullYear() + "-" + pad2(now.getMonth() + 1) + "-" + pad2(now.getDate());
    return toolName(toolId) + " " + stamp;
  }

  async function postLibraryFile(pid, name, text, docKind) {
    let res;
    try {
      res = await window.fetch("/api/projects/" + encodeURIComponent(pid) + "/files", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name, media_type: "text/plain", text: text, doc_kind: docKind }),
      });
    } catch (_) {
      return { failure: { status: 0 } };
    }
    if (res.status === 409) return { conflict: true };
    if (!res.ok) return { failure: { status: res.status } };
    const data = await res.json().catch(() => null);
    return data && data.file ? { file: data.file } : { failure: { status: res.status } };
  }

  // 같은 날 같은 도구로 한 번 더 저장하면 이름이 겹친다. 기존 행을 덮어쓰지
  // 않고 번호를 붙인 새 이름으로 저장한다(기존 저장 경로의 409 규칙 그대로).
  async function saveToLibrary(toolId, text) {
    const pid = await libraryProject.ensure();
    if (!pid) return { failure: { status: 0 } };
    const base = libraryTitle(toolId);
    let outcome = await postLibraryFile(pid, base + ".txt", text, toolId);
    for (let n = 2; outcome.conflict && n <= 9; n += 1) {
      outcome = await postLibraryFile(pid, base + " (" + n + ").txt", text, toolId);
    }
    return outcome.conflict ? { failure: { status: 409 } } : outcome;
  }

  function contract() { return window.PadiemUtilContract || null; }

  function schemaFor(toolId) {
    const reg = window.PadiemUtilManifest;
    const tool = reg && typeof reg.getTool === "function" ? reg.getTool(toolId) : null;
    return (tool && Array.isArray(tool.fields)) ? tool.fields : [];
  }

  function requiredKeysFor(toolId) {
    return schemaFor(toolId).filter((f) => f.required).map((f) => f.key);
  }

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderAnswer(host, value) {
    host.setAttribute("data-empty", "false");
    const markdown = window.PadiemUtilMarkdown;
    if (markdown && typeof markdown.render === "function") {
      markdown.render(host, value);
      return;
    }
    host.textContent = value;
  }

  function paintEmptyResult(host) {
    host.setAttribute("data-empty", "true");
    host.replaceChildren(element("p", "util-result-empty", t("emptyResult")));
  }

  function plainAnswer(value) {
    const markdown = window.PadiemUtilMarkdown;
    return markdown && typeof markdown.plain === "function"
      ? markdown.plain(value)
      : String(value == null ? "" : value);
  }

  function authSession() {
    try {
      if (window.PadiemAuthSession && typeof window.PadiemAuthSession.get === "function") {
        const session = window.PadiemAuthSession.get();
        return session && typeof session === "object" ? session : null;
      }
    } catch (_) { /* unreadable session treated as unknown */ }
    return null;
  }

  function loginGate(known) {
    const gate = element("div", "util-gate");
    gate.appendChild(element("p", "util-gate-text", known ? t("loginRequired") : t("loginUnknown")));
    const login = element("button", "util-gate-login", t("login"));
    login.type = "button";
    login.setAttribute("data-util-login", "");
    login.addEventListener("click", () => {
      const button = document.getElementById("loginButton");
      if (button && typeof button.click === "function") button.click();
    });
    gate.appendChild(login);
    return gate;
  }

  function buildFieldNode(spec, state) {
    if (spec.type === "choice") {
      const tabs = element("div", "util-platform-tabs");
      tabs.setAttribute("role", "group");
      tabs.setAttribute("aria-label", localized(spec.label) || t("platformGroup"));
      const holder = element("div", "util-field util-field-tabs");
      const options = Array.isArray(spec.options) && spec.options.length
        ? spec.options
        : Object.keys(contract().PLATFORM_TITLE).map((key) => ({ value: key, label: contract().PLATFORM_TITLE[key] }));
      options.forEach((opt) => {
        const key = opt.value;
        const button = element("button", "util-platform-tab", localized(opt.label) || contract().PLATFORM_TITLE[key] || key);
        button.type = "button";
        button.setAttribute("data-platform", key);
        button.setAttribute("aria-pressed", key === state.platform ? "true" : "false");
        button.addEventListener("click", () => {
          state.platform = key;
          Array.prototype.forEach.call(tabs.querySelectorAll("[data-platform]"), (node) => {
            node.setAttribute("aria-pressed", node.getAttribute("data-platform") === key ? "true" : "false");
          });
          if (state.onPlatform) state.onPlatform(key);
        });
        tabs.appendChild(button);
      });
      holder.appendChild(tabs);
      return holder;
    }

    const field = element("div", "util-field");
    const head = element("div", "util-field-head");
    const labelText = element("label", "util-field-label", localized(spec.label));
    head.appendChild(labelText);
    if (state && state.importFieldKey === spec.key && typeof state.onImport === "function") {
      const pcPick = element("button", "util-pc-import", state.importLabel || "");
      pcPick.type = "button";
      pcPick.setAttribute("data-util-pc-import", spec.key);
      pcPick.addEventListener("click", (event) => {
        if (event && typeof event.preventDefault === "function") event.preventDefault();
        if (event && typeof event.stopPropagation === "function") event.stopPropagation();
        state.onImport();
      });
      head.appendChild(pcPick);
    }
    field.appendChild(head);
    let input;
    if (spec.type === "textarea") {
      input = element("textarea", "util-input");
      input.rows = spec.rows || 3;
    } else if (spec.type === "select") {
      input = element("select", "util-input");
      (spec.options || []).forEach((opt) => {
        const option = element("option", null, localized(opt.label));
        option.value = opt.value;
        option.selected = opt.value === spec.defaultValue;
        input.appendChild(option);
      });
      if (spec.defaultValue) input.value = spec.defaultValue;
    } else {
      input = element("input", "util-input");
      input.type = spec.type || "text";
    }
    input.name = spec.key;
    input.id = "utilToolField-" + spec.key;
    labelText.setAttribute("for", input.id);
    if (spec.required) {
      input.required = true;
      input.setAttribute("aria-invalid", "false");
      input.addEventListener("input", () => {
        if (String(input.value || "").trim()) input.setAttribute("aria-invalid", "false");
      });
    }
    const ph = localized(spec.placeholder);
    if (ph) input.placeholder = ph;
    field.appendChild(input);
    return field;
  }

  function buildFormFields(toolId, form, state) {
    const fields = schemaFor(toolId);
    fields.filter((f) => !f.advanced).forEach((spec) => form.appendChild(buildFieldNode(spec, state)));
    const advancedFields = fields.filter((f) => f.advanced);
    if (advancedFields.length) {
      const more = element("details", "util-more");
      more.appendChild(element("summary", "util-more-summary", t("more")));
      const body = element("div", "util-more-body");
      advancedFields.forEach((spec) => body.appendChild(buildFieldNode(spec, state)));
      more.appendChild(body);
      form.appendChild(more);
    }
  }

  function readValues(form, state) {
    const values = {};
    Array.prototype.forEach.call(form.querySelectorAll("[name]"), (input) => {
      values[input.name] = typeof input.value === "string" ? input.value.trim() : "";
    });
    if (state && state.platform && values.platform === undefined && form.querySelector("[data-platform]")) {
      values.platform = state.platform;
    }
    return values;
  }

  function writeValues(form, state, incoming) {
    if (!incoming || typeof incoming !== "object") return;
    Array.prototype.forEach.call(form.querySelectorAll("[name]"), (input) => {
      if (!Object.prototype.hasOwnProperty.call(incoming, input.name)) return;
      const next = String(incoming[input.name] == null ? "" : incoming[input.name]);
      input.value = next;
      if (input.tagName === "SELECT" && Array.isArray(input.children)) {
        input.children.forEach((opt) => { opt.selected = opt.value === next; });
      }
      if (next.trim()) input.setAttribute("aria-invalid", "false");
    });
    if (state && incoming.platform) {
      state.platform = incoming.platform;
      Array.prototype.forEach.call(form.querySelectorAll("[data-platform]"), (node) => {
        node.setAttribute("aria-pressed", node.getAttribute("data-platform") === incoming.platform ? "true" : "false");
      });
      if (state.onPlatform) state.onPlatform(incoming.platform);
    }
  }

  function generateLabel(toolId) {
    if (toolId === "speech") return t("speechGenerate");
    return toolId === "sns" ? t("snsGenerate") : t("meetingGenerate");
  }

  function buildScreen(toolId, initialMode) {
    const manifest = window.PadiemUtilManifest;
    const importField = manifest && typeof manifest.pcImportField === "function"
      ? manifest.pcImportField(toolId) : null;
    const state = {
      platform: "blog",
      onPlatform: null,
      importFieldKey: importField ? importField.key : "",
      importLabel: PC_COPY.pick(),
      onImport: () => { void importFromPc(); },
    };
    const chatApi = window.PadiemUtilChatMode;
    const hasChatMode = Boolean(
      CHAT_MODE_TOOLS.indexOf(toolId) >= 0
      && chatApi
      && typeof chatApi.create === "function"
      && typeof chatApi.buildModeSwitch === "function"
    );

    const wrap = element("div", "util-tool-form util-tool-workbench");
    wrap.setAttribute("data-util-form", toolId);

    const inputPane = element("div", "util-pane-input");
    inputPane.setAttribute("data-util-pane", "input");

    const form = element("form", "util-form");
    form.id = "utilToolForm-" + toolId;
    form.noValidate = true;
    buildFormFields(toolId, form, state);

    const actions = element("div", "util-form-actions");
    const primary = element("button", "util-generate", generateLabel(toolId));
    primary.type = "submit";
    primary.id = "utilGenerate-" + toolId;
    actions.appendChild(primary);
    form.appendChild(actions);

    const pcNote = element("p", "util-pc-note");
    pcNote.hidden = true;
    const pcNoteText = element("span", null, PC_COPY.note());
    const pcConnect = element("button", "util-pc-connect", PC_COPY.connect());
    pcConnect.type = "button";
    pcConnect.addEventListener("click", () => { openPcConnect(); });
    pcNote.appendChild(pcNoteText);
    pcNote.appendChild(pcConnect);
    if (importField) form.appendChild(pcNote);

    const status = element("p", "util-status");
    status.id = "utilStatus-" + toolId;
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.hidden = true;

    const resultPane = element("div", "util-pane-result");
    resultPane.setAttribute("data-util-pane", "result");

    const result = element("section", "util-result");
    result.id = "utilResult-" + toolId;
    result.hidden = false;
    const resultTitle = element("h4", "util-result-title",
      toolId === "meeting" ? t("meetingResult") : t("result"));
    const output = element("div", "util-result-output");
    output.id = "utilOutput-" + toolId;
    output.setAttribute("role", "region");
    output.setAttribute("aria-label", t("result"));
    output.setAttribute("tabindex", "0");
    paintEmptyResult(output);

    const resultActions = element("div", "util-result-actions");
    const copyBtn = element("button", "util-result-button", t("copy"));
    copyBtn.type = "button";
    copyBtn.disabled = true;
    copyBtn.setAttribute("data-util-copy", "");
    const saveBtn = element("button", "util-result-button", LIBRARY_COPY.save());
    saveBtn.type = "button";
    saveBtn.disabled = true;
    saveBtn.setAttribute("data-util-save-library", "");
    const againBtn = element("button", "util-result-button util-result-generate", t("regenerate"));
    againBtn.type = "button";
    againBtn.disabled = true;
    againBtn.setAttribute("data-util-regenerate", "");
    resultActions.appendChild(copyBtn);
    resultActions.appendChild(saveBtn);
    resultActions.appendChild(againBtn);

    let refineBtn = null;
    if (hasChatMode) {
      refineBtn = element("button", "util-result-button", t("refineChat"));
      refineBtn.type = "button";
      refineBtn.disabled = true;
      refineBtn.setAttribute("data-util-refine-chat", "");
      resultActions.appendChild(refineBtn);
    }

    result.appendChild(resultTitle);
    result.appendChild(output);
    result.appendChild(resultActions);
    resultPane.appendChild(result);

    function setStatus(text, tone) {
      status.textContent = text || "";
      status.hidden = !text;
      status.setAttribute("data-tone", tone || "info");
    }

    function showPcNote() {
      pcNoteText.textContent = PC_COPY.note();
      pcNote.hidden = false;
      if (typeof pcNote.scrollIntoView === "function") {
        try { pcNote.scrollIntoView({ block: "nearest" }); } catch (_) {}
      }
      if (typeof pcConnect.focus === "function") {
        try { pcConnect.focus({ preventScroll: true }); } catch (_) {}
      }
    }

    async function fillImportedText(input, outcome) {
      const current = String(input.value || "");
      if (current.trim() && current !== outcome.text) {
        const proceed = typeof window.confirm === "function" ? window.confirm(PC_COPY.replace()) : false;
        if (!proceed) return;
      }
      input.value = outcome.text;
      input.setAttribute("aria-invalid", "false");
      if (typeof input.dispatchEvent === "function" && typeof window.Event === "function") {
        input.dispatchEvent(new window.Event("input", { bubbles: true }));
      }
      pcNote.hidden = true;
      setStatus("", null);
    }

    async function importFromPc() {
      if (!importField) return;
      const input = form.querySelector("#utilToolField-" + importField.key);
      if (!input) return;
      const outcome = await pickPcText();
      if (outcome.needPc) { showPcNote(); return; }
      if (!outcome.ok) { setStatus(outcome.message, "error"); return; }
      await fillImportedText(input, outcome);
    }

    let busy = false;
    let lastAnswer = "";

    // 결과가 비어 있으면 저장도 비활성(복사·다시 만들기와 같은 규칙).
    function refreshSaveEnabled() {
      saveBtn.disabled = busy || !String(lastAnswer || "").trim();
    }

    async function runGeneration(overrideValues, refinementNote) {
      if (busy) return false;
      if (overrideValues) writeValues(form, state, overrideValues);
      const values = readValues(form, state);
      const missing = requiredKeysFor(toolId).filter((name) => !String(values[name] || "").trim());
      if (missing.length) {
        missing.forEach((name) => {
          const el = form.querySelector("#utilToolField-" + name);
          if (el) el.setAttribute("aria-invalid", "true");
        });
        setStatus(t("required"), "error");
        const first = form.querySelector("#utilToolField-" + missing[0]);
        if (first && typeof first.focus === "function") first.focus();
        return false;
      }
      let prompt = toolId === "sns"
        ? contract().PROMPTS.sns(values, state.platform)
        : contract().PROMPTS[toolId](values);
      if (refinementNote) {
        prompt += "\n\n추가 다듬기 요청: " + String(refinementNote).trim();
      }
      busy = true;
      primary.disabled = true;
      copyBtn.disabled = true;
      againBtn.disabled = true;
      refreshSaveEnabled();
      if (refineBtn) refineBtn.disabled = true;
      setStatus(t("generating"), "busy");
      result.hidden = false;
      const previousAnswer = lastAnswer;
      lastAnswer = "";
      output.setAttribute("data-empty", "false");
      output.replaceChildren();
      try {
        const answer = await contract().apiChat(prompt, toolId, (partial) => {
          lastAnswer = partial;
          renderAnswer(output, partial);
        });
        lastAnswer = answer;
        renderAnswer(output, answer);
        result.hidden = false;
        setStatus("", null);
        return true;
      } catch (err) {
        setStatus(contract().errorMessage(err), "error");
        if (!String(lastAnswer || "").trim()) {
          if (String(previousAnswer || "").trim()) {
            lastAnswer = previousAnswer;
            renderAnswer(output, previousAnswer);
          } else {
            paintEmptyResult(output);
          }
        }
        return false;
      } finally {
        busy = false;
        primary.disabled = false;
        const hasAnswer = Boolean(String(lastAnswer || "").trim());
        copyBtn.disabled = !hasAnswer;
        againBtn.disabled = !hasAnswer;
        refreshSaveEnabled();
        if (refineBtn) refineBtn.disabled = !hasAnswer;
      }
    }

    let modeSwitch = null;
    let chatIntake = null;
    function setMode(nextMode, focusChat) {
      if (!chatIntake || !modeSwitch) return;
      const toChat = nextMode === "chat";
      wrap.setAttribute("data-active-mode", toChat ? "chat" : "form");
      modeSwitch.setActive(toChat ? "chat" : "form");
      if (toChat) {
        setStatus("", null);
        form.hidden = true;
        chatIntake.root.hidden = false;
        chatIntake.enter({ focusInput: Boolean(focusChat) });
      } else {
        writeValues(form, state, chatIntake.getValues());
        chatIntake.root.hidden = true;
        form.hidden = false;
      }
    }

    if (hasChatMode) {
      chatIntake = chatApi.create({
        toolId: toolId,
        getValues: () => readValues(form, state),
        setValues: (vals) => writeValues(form, state, vals),
        hasDraft: () => Boolean(String(lastAnswer || "").trim()),
        onGenerate: (vals, note) => runGeneration(vals, note),
        onSwitchToForm: () => setMode("form", false),
        pcImport: importField ? {
          fieldKey: importField.key,
          label: PC_COPY.pick(),
          note: PC_COPY.note(),
          connect: PC_COPY.connect(),
          confirmReplace: PC_COPY.replace(),
          failed: PC_COPY.failed(),
          run: () => pickPcText(),
          onConnect: () => { openPcConnect(); },
        } : null,
      });
      if (chatIntake) {
        const startMode = initialMode === "chat" ? "chat" : "form";
        modeSwitch = chatApi.buildModeSwitch(startMode, (picked) => setMode(picked, picked === "chat"));
        inputPane.appendChild(modeSwitch.root);
        inputPane.appendChild(form);
        inputPane.appendChild(chatIntake.root);
        inputPane.appendChild(status);
        setMode(startMode, false);
      }
    }
    if (!chatIntake) {
      inputPane.appendChild(form);
      inputPane.appendChild(status);
    }

    refreshSaveEnabled();

    wrap.appendChild(inputPane);
    wrap.appendChild(resultPane);

    form.addEventListener("submit", (event) => {
      if (event && typeof event.preventDefault === "function") event.preventDefault();
      void runGeneration(null, "");
    });
    againBtn.addEventListener("click", () => { void runGeneration(null, ""); });
    if (refineBtn) {
      refineBtn.addEventListener("click", () => { setMode("chat", true); });
    }
    saveBtn.addEventListener("click", async () => {
      const text = plainAnswer(lastAnswer).trim();
      if (!text || saveBtn.disabled) return;
      const originalLabel = LIBRARY_COPY.save();
      saveBtn.disabled = true;
      saveBtn.textContent = LIBRARY_COPY.saving();
      const outcome = await saveToLibrary(toolId, text);
      saveBtn.textContent = originalLabel;
      refreshSaveEnabled();
      if (outcome.file) {
        setStatus(LIBRARY_COPY.saved(), "info");
      } else {
        setStatus(LIBRARY_COPY.failed(), "error");
      }
    });
    copyBtn.addEventListener("click", () => {
      const text = plainAnswer(lastAnswer).trim();
      if (!text) return;
      const copier = window.PadiemAnswerCopy && typeof window.PadiemAnswerCopy.copyText === "function"
        ? window.PadiemAnswerCopy.copyText
        : null;
      const done = (ok) => setStatus(ok ? t("copied") : t("copyFailed"), ok ? "info" : "error");
      if (copier) {
        Promise.resolve(copier(text)).then(done, () => done(false));
        return;
      }
      const nav = typeof navigator !== "undefined" ? navigator : null;
      if (nav && nav.clipboard && typeof nav.clipboard.writeText === "function") {
        Promise.resolve(nav.clipboard.writeText(text)).then(() => done(true), () => done(false));
        return;
      }
      done(false);
    });
    if (toolId === "sns") {
      state.onPlatform = (key) => {
        resultTitle.textContent = t("result") + " · " + contract().PLATFORM_TITLE[key];
      };
      resultTitle.textContent = t("result") + " · " + contract().PLATFORM_TITLE.blog;
    }
    return wrap;
  }

  let current = null;

  function mount(toolId, host) {
    const key = String(toolId || "");
    if (TOOL_KEYS.indexOf(key) < 0 || !host || typeof host.appendChild !== "function") return false;
    if (!contract()) return false;
    host.setAttribute("data-util-mounted", "form");
    const session = authSession();
    if (session && session.authenticated !== true) {
      host.appendChild(loginGate(true));
      current = { toolId: key, host: host };
      return true;
    }
    if (session === null) {
      host.appendChild(loginGate(false));
      current = { toolId: key, host: host };
      return true;
    }
    const initMode = host.getAttribute && host.getAttribute("data-util-initial-mode") === "chat" ? "chat" : "form";
    host.appendChild(buildScreen(key, initMode));
    current = { toolId: key, host: host };
    return true;
  }

  function remount() {
    if (!current || !current.host) return;
    const host = current.host;
    if (host.isConnected === false) return;
    if (typeof host.replaceChildren !== "function") return;
    host.replaceChildren();
    mount(current.toolId, host);
  }

  window.addEventListener("padiem:auth-state", remount);

  window.PadiemUtilTools = Object.freeze({
    TOOL_KEYS: TOOL_KEYS,
    CHAT_MODE_TOOLS: CHAT_MODE_TOOLS,
    mount: mount,
  });
})();
