(() => {
  "use strict";

  function ready(fn) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
    } else {
      fn();
    }
  }

  // One place for generation-failure copy. The server's own Korean message
  // wins; a bare "HTTP nnn" never reaches the screen — statuses the server
  // did not name resolve here, once, for every util tool.
  const GEN_ERROR_COPY = {
    401: "로그인이 필요합니다. 다시 로그인해 주세요.",
    403: "이 계정에서는 할 수 없는 요청입니다. 로그인 상태를 확인해 주세요.",
    429: "요청이 잠시 많습니다. 조금 뒤에 다시 시도해 주세요.",
    500: "만드는 중 문제가 생겼습니다. 잠시 후 다시 시도해 주세요.",
    502: "서버 연결이 잠시 끊겼습니다. 잠시 후 다시 시도해 주세요.",
    503: "서버가 잠시 과부하 상태입니다. 잠시 후 다시 시도해 주세요.",
    504: "서버 응답이 늦어집니다. 잠시 후 다시 시도해 주세요."
  };
  const GEN_ERROR_FALLBACK = "생성에 실패했습니다. 잠시 후 다시 시도해 주세요.";
  const GEN_OFFLINE_COPY = "인터넷 연결을 확인해 주세요.";
  const GEN_RETRY_LABEL = "다시 시도";

  function generationFailureText(error) {
    const message = error && typeof error.message === "string" ? error.message.trim() : "";
    return "생성 실패: " + (message || GEN_ERROR_FALLBACK);
  }

  // The failure line stays prefixed with 생성 실패: the session-restore code
  // treats drafts that do not start with it as real content.
  function showGenerationFailure(output, retry, error) {
    output.value = generationFailureText(error);
    if (retry) retry.hidden = false;
  }

  function retryButton(id, run) {
    const button = el("button", "util-retry", GEN_RETRY_LABEL);
    button.type = "button";
    button.id = id;
    button.hidden = true;
    button.addEventListener("click", () => {
      button.hidden = true;
      run();
    });
    return button;
  }

  async function apiChat(prompt, util) {
    // Same rule as app.js selectedProductTier(), lines 3039-3040.
    const selected = window.PadiemTierSelection?.get?.();
    const tier = ["free", "plus", "pro", "max", "admin"].includes(selected) ? selected : "free";
    const payload = { messages: [{ role: "user", content: prompt }], mode: "auto", tier };
    if (util) payload.util = util;
    let res;
    try {
      res = await fetch("/api/chat", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (_) {
      throw new Error(GEN_OFFLINE_COPY);
    }
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      const message = data?.error?.message;
      throw new Error(typeof message === "string" && message.trim()
        ? message
        : (GEN_ERROR_COPY[res.status] || GEN_ERROR_FALLBACK));
    }
    const data = await res.json();
    return (data && data.answer) ? data.answer : (data && data.message ? data.message : JSON.stringify(data));
  }

  async function getProjects() {
    const res = await fetch("/api/projects", { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json();
    return (data && data.projects) ? data.projects : [];
  }

  async function ensureProject() {
    const projects = await getProjects();
    if (projects.length) return projects[0].id;
    const res = await fetch("/api/projects", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "유틸 작업" }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.project ? data.project.id : null;
  }

  async function saveProjectFile(pid, name, text, mediaType) {
    const res = await fetch("/api/projects/" + pid + "/files", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      // The server refuses a file whose media type contradicts its
      // extension; callers that store .json payloads must say so.
      body: JSON.stringify({ name: name, media_type: mediaType || "text/plain", text: text }),
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data && data.file ? data.file : null;
  }

  // #5728: photos persist through the SAME project-file channel as text
  // drafts — binary original upload, owner/project scoped, no new limits.
  async function uploadProjectImage(pid, file) {
    const res = await fetch("/api/projects/" + pid + "/files", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Padiem-Filename": encodeURIComponent(file.name),
        "X-Padiem-Media-Type": file.type,
      },
      body: file,
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return data && data.file ? data.file : null;
  }

  async function deleteProjectFile(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId), {
      method: "DELETE",
      credentials: "include",
    });
    return res.ok || res.status === 404;
  }

  async function fetchOriginalDataUrl(pid, fileId) {
    const res = await fetch("/api/projects/" + pid + "/files/" + encodeURIComponent(fileId) + "/original", {
      credentials: "include",
    });
    if (!res.ok) return null;
    const blob = await res.blob();
    return new Promise((resolve) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  }

  async function listProjectFiles(pid) {
    const res = await fetch("/api/projects/" + pid + "/files", { credentials: "include" });
    if (!res.ok) return [];
    const data = await res.json();
    return (data && data.files) ? data.files : [];
  }

  // ── #5895: "내 PC에서 예전 글 가져오기" / "내 PC에 저장" ─────────────────
  // The authoring tools share one browser part. It is loaded on first use (#5895:
  // nothing joins the page or the Worker's cold init until a menu needs it), and the
  // only endpoints it adds are the PC file-exchange routes that already exist.
  const PC_REF_COPY = {
    pick: "내 PC에서 예전 글 가져오기",
    again: "내 PC에서 더 가져오기",
    remove: "빼기",
    preview: "가져온 글",
    unavailable: "PC 파일 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    unreadable: "이 파일은 참고 글로 읽지 못했어요. 글자가 들어 있는 문서를 골라 주세요.",
    hwpEncrypted: "암호가 걸린 한글 파일은 읽을 수 없어요.",
    hwpDistributable: "배포용으로 저장된 한글 파일은 읽을 수 없어요.",
    laneDown: "파일 읽기 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    noPc: "PC를 연결하면 예전 글을 가져올 수 있습니다.",
    connect: "이 PC 연결",
    save: "내 PC에 저장",
    saveUnavailable: "PC에 저장할 창을 열지 못했습니다. 잠시 후 다시 시도해 주세요.",
    saved: "내 PC에 저장했습니다.",
  };

  let pcExchangeLoading = null;

  function loadPcExchange() {
    if (window.PadiemPcFileExchange) return Promise.resolve(window.PadiemPcFileExchange);
    if (pcExchangeLoading) return pcExchangeLoading;
    pcExchangeLoading = new Promise((resolve, reject) => {
      const head = document.head || document.body;
      if (head && !document.querySelector('link[href="./pc-file-exchange.css"]')) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = "./pc-file-exchange.css";
        head.appendChild(css);
      }
      const script = document.createElement("script");
      script.src = "./pc-file-exchange.js";
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
      const res = await fetch("/api/pc/pairings", { credentials: "include", cache: "no-store" });
      if (!res.ok) return null;
      const body = await res.json().catch(() => null);
      const links = body && Array.isArray(body.links) ? body.links : [];
      return links.some((link) => link && link.state === "active");
    } catch (_) {
      return null;
    }
  }

  // The existing Connectors surface owns the computer card: no second pairing screen.
  function openPcConnect() {
    const opener = document.getElementById("connectorsNavButton");
    if (!opener) return;
    opener.click();
    const card = document.getElementById("connectorComputerCard");
    if (!card) return;
    if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
    if (typeof card.focus === "function") card.focus({ preventScroll: true });
    if (typeof card.scrollIntoView === "function") card.scrollIntoView({ block: "nearest" });
  }

  async function pcReferenceEntry(picked) {
    if (!picked) return null;
    if (typeof picked.content === "string" && picked.content.trim()) {
      return { name: picked.name || "가져온 글", text: picked.content };
    }
    if (!picked.fileId) return null;
    try {
      const res = await fetch("/api/pc/reference", {
        method: "POST",
        credentials: "include",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: picked.fileId }),
      });
      if (!res.ok) {
        // #5895: the refusals the lane and the Worker answer by code, said out
        // loud — a sealed or distributed 한글 file is not a broken picker.
        const refused = await res.json().catch(() => null);
        const code = refused && refused.error && typeof refused.error.code === "string"
          ? refused.error.code : "";
        if (code === "hwp_encrypted") return { error: PC_REF_COPY.hwpEncrypted };
        if (code === "hwp_distributable") return { error: PC_REF_COPY.hwpDistributable };
        if (code === "file_lane_unavailable") return { error: PC_REF_COPY.laneDown };
        return null;
      }
      const body = await res.json().catch(() => null);
      if (!body || body.ok !== true || typeof body.text !== "string" || !body.text.trim()) return null;
      return {
        name: typeof body.name === "string" && body.name ? body.name : (picked.name || "가져온 글"),
        text: body.text,
      };
    } catch (_) {
      return null;
    }
  }

  // One section per tool: the pick button, the files the owner chose with their
  // preview, and — when no PC is linked — the one-line notice instead.
  function createPcReferenceSection() {
    const box = el("div", "util-pc-ref");
    const pick = el("button", "util-pc-ref-pick", PC_REF_COPY.pick);
    pick.type = "button";
    const note = el("p", "util-pc-ref-note", "");
    note.hidden = true;
    const status = el("p", "util-pc-ref-status", "");
    status.hidden = true;
    const list = el("ul", "util-pc-ref-list");
    list.hidden = true;
    box.append(pick, note, list, status);
    const files = [];

    function say(text) {
      status.textContent = text || "";
      status.hidden = !text;
    }

    function render() {
      list.replaceChildren();
      files.forEach((file, index) => {
        const item = el("li", "util-pc-ref-item");
        const head = el("div", "util-pc-ref-head");
        head.append(el("strong", "util-pc-ref-name", file.name));
        head.append(el("span", "util-pc-ref-chars", file.text.length.toLocaleString("ko-KR") + "자"));
        const drop = el("button", "util-pc-ref-remove", PC_REF_COPY.remove);
        drop.type = "button";
        drop.addEventListener("click", () => {
          files.splice(index, 1);
          render();
        });
        head.append(drop);
        const preview = el("pre", "util-pc-ref-preview", file.text);
        item.append(head, preview);
        list.append(item);
      });
      list.hidden = files.length === 0;
      pick.textContent = files.length ? PC_REF_COPY.again : PC_REF_COPY.pick;
    }

    async function addPicked(picked) {
      say("");
      const entry = await pcReferenceEntry(picked);
      if (entry && typeof entry.error === "string") {
        say(entry.error);
        return;
      }
      if (!entry) {
        say(PC_REF_COPY.unreadable);
        return;
      }
      files.push(entry);
      render();
    }

    pick.addEventListener("click", async () => {
      say("");
      let component;
      try {
        component = await loadPcExchange();
      } catch (_) {
        component = null;
      }
      if (!component || typeof component.open !== "function") {
        say(PC_REF_COPY.unavailable);
        return;
      }
      component.open({ onSelect: (picked) => { void addPicked(picked); } });
    });

    // The check runs when the screen is first shown, not when the module loads:
    // a page that never opens this tool asks the PC directory nothing at all.
    let checked = false;
    function check() {
      if (checked) return;
      checked = true;
      void pcLinked().then((linked) => {
        if (linked !== false) return;
        pick.hidden = true;
        note.textContent = PC_REF_COPY.noPc + " ";
        const connect = el("button", "util-pc-ref-connect", PC_REF_COPY.connect);
        connect.type = "button";
        connect.addEventListener("click", openPcConnect);
        note.appendChild(connect);
        note.hidden = false;
      });
    }

    return {
      box,
      files,
      check,
      read() {
        const lineBreak = String.fromCharCode(10);
        return files
          .map((file, index) => "[참고 글 " + (index + 1) + ": " + file.name + "]" + lineBreak + file.text)
          .join(lineBreak + lineBreak);
      },
    };
  }

  function pcSaveFileName(base) {
    const title = String(base || "").trim().replace(/[\/:*?"<>|]+/g, " ").trim() || "글";
    const now = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    const day = now.getFullYear() + "-" + pad(now.getMonth() + 1) + "-" + pad(now.getDate());
    return title + "_" + day + ".txt";
  }

  async function saveTextToPc(text, baseName) {
    const content = String(text || "").trim();
    if (!content) return;
    let component;
    try {
      component = await loadPcExchange();
    } catch (_) {
      component = null;
    }
    if (!component || typeof component.open !== "function") {
      alert(PC_REF_COPY.saveUnavailable);
      return;
    }
    component.open({
      mode: "save",
      content,
      fileName: pcSaveFileName(baseName),
      onSave: () => {},
    });
  }

  function downloadText(text, filename) {
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  ready(() => {
    const utilNav = document.getElementById("utilNavButton");
    const utilView = document.getElementById("utilView");
    if (!utilNav || !utilView) return;

    const speechForm = document.getElementById("utilSpeechForm");
    const speechResult = document.getElementById("utilSpeechResult");
    const speechOutput = document.getElementById("utilSpeechOutput");
    const copyBtn = document.getElementById("utilSpeechCopy");
    const downloadBtn = document.getElementById("utilSpeechDownload");
    // #5727: the save action lives in the form area next to 초안 생성 (index.html
    // markup) and stays disabled until a draft exists — it never claims a save
    // that did not happen.
    const saveBtn = document.getElementById("utilSpeechSave");
    const speechPc = createPcReferenceSection();
    const speechPcMount = document.getElementById("utilSpeechPcRef");
    if (speechPcMount) speechPcMount.appendChild(speechPc.box);
    // #5895 beta UX: a failed draft comes back with its own 다시 시도 instead of
    // leaving the owner to find the form button again.
    const speechActions = document.querySelector("#utilSpeechResult .util-actions");
    const speechRetry = retryButton("utilSpeechRetry", () => { if (speechForm) generateSpeech(speechForm); });
    if (speechActions) speechActions.appendChild(speechRetry);
    const utilTitleEl = document.getElementById("utilTitle");
    const utilKickerEl = document.getElementById("utilKicker");
    const utilTaglineEl = document.getElementById("utilTagline");
    const tabs = document.querySelectorAll(".util-tab");
    const panels = {
      speech: document.getElementById("utilSpeechPanel"),
      sns: document.getElementById("utilSnsPanel"),
      meeting: document.getElementById("utilMeetingPanel"),
      pdfmd: document.getElementById("utilPdfmdPanel"),
    };

    let lastPayload = null;
    let currentPid = null;
    // #5895: the SNS panel is built on first open, so its PC section is handed back
    // to the tab handler that knows when the panel is actually on screen.
    let snsPcRef = null;

    // #5608 follow-up: the sidebar Util entry expands into its four tools. The
    // submenu rows and the (hidden) in-page tabs drive the same switch, so the
    // panels, lazy builders and saved state keep their single owner here.
    const utilSubmenu = document.getElementById("utilSubmenu");
    const utilSubmenuItems = utilSubmenu
      ? Array.from(utilSubmenu.querySelectorAll(".util-submenu-item"))
      : [];

    // #5608: the util page is its own shell state. The sibling views are gated
    // by CSS (util-menu.css), so entering the state is enough and navigating to
    // any other view restores them -- no per-view cleanup needed here.
    function showUtil() {
      const shell = document.querySelector(".app-shell");
      if (shell) shell.dataset.state = "util";
      utilView.hidden = false;
      utilNav.setAttribute("aria-current", "page");
    }

    function setUtilSubmenuOpen(open) {
      if (!utilSubmenu) return;
      utilSubmenu.hidden = !open;
      utilNav.setAttribute("aria-expanded", open ? "true" : "false");
      const chevron = utilNav.querySelector(".side-chevron");
      if (chevron) chevron.textContent = open ? "⌄" : "›";
    }

    function markActiveUtilSubmenuItem(key) {
      if (!utilSubmenu) return;
      utilSubmenuItems.forEach((item) => {
        const active = key != null && item.dataset.util === key;
        item.classList.toggle("active", active);
        item.setAttribute("aria-current", active ? "true" : "false");
      });
    }

    function closeMobileSidebar() {
      const shell = document.querySelector(".app-shell");
      if (!shell || !shell.classList.contains("sidebar-open")) return;
      shell.classList.remove("sidebar-open");
      const menu = document.getElementById("mobileMenu");
      if (menu) menu.setAttribute("aria-expanded", "false");
      const scrim = document.getElementById("sidebarScrim");
      if (scrim) scrim.hidden = true;
    }

    utilNav.addEventListener("click", () => {
      showUtil();
      if (utilSubmenu) setUtilSubmenuOpen(utilSubmenu.hidden);
    });
    utilSubmenuItems.forEach((item) => {
      item.addEventListener("click", () => {
        showUtil();
        setUtilSubmenuOpen(true);
        markActiveUtilSubmenuItem(item.dataset.util);
        const tab = Array.prototype.find.call(
          tabs, (t) => t.dataset.util === item.dataset.util
        );
        if (tab) activateUtilTab(tab);
        closeMobileSidebar();
      });
    });
    markActiveUtilSubmenuItem("speech");
    // Leaving the util view (any other nav) must not leave a stale highlight
    // on a submenu row. app.js owns aria-current on the parent, so watching
    // that one attribute covers every navigation path.
    if (utilSubmenu && typeof MutationObserver === "function") {
      new MutationObserver(() => {
        if (utilNav.getAttribute("aria-current") === "false") {
          markActiveUtilSubmenuItem(null);
        }
      }).observe(utilNav, { attributes: true, attributeFilter: ["aria-current"] });
    }
    function activateUtilTab(tab) {
      tabs.forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const key = tab.dataset.util;
      Object.keys(panels).forEach((k) => { if (panels[k]) panels[k].hidden = k !== key; });
      // #5727: the page title names the actual tool, the shared standalone
      // header hierarchy (kicker → task title → tagline) stays untouched.
      if (utilTitleEl && tab.textContent.trim()) utilTitleEl.textContent = tab.textContent.trim();
      // #5799: the kicker and tagline follow the active tool the same way.
      // Only the speech template carries its own values so far; the other
      // tools keep the shared defaults until their own pass.
      if (utilKickerEl) utilKickerEl.textContent = tab.dataset.kicker || "Padiem Util";
      if (utilTaglineEl) utilTaglineEl.textContent = tab.dataset.tagline || "AI 홍보·기록 비서";
      if (key === "speech") speechPc.check();
      if (key === "sns") {
        if (!panels.sns.dataset.loaded) buildSns();
        snsPcRef.check();
      }
      if (key === "meeting" && !panels.meeting.dataset.loaded) buildMeeting();
      // #5731: re-entering the speech tool must show the past speeches the
      // account already stored — the list can't only exist after a save.
      if (key === "speech" && !panels.speech.dataset.speechListLoaded) {
        panels.speech.dataset.speechListLoaded = "1";
        refreshSpeechList();
      }
      if (key === "pdfmd" && !panels.pdfmd.dataset.loaded) {
        panels.pdfmd.dataset.loaded = "1";
        if (typeof window.initPdfMdUtility === "function") window.initPdfMdUtility(panels.pdfmd);
      }
    }
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => activateUtilTab(tab));
    });

    // Speech
    function buildPrompt(form) {
      const d = new FormData(form);
      const event = (d.get("event") || "").trim();
      const date = (d.get("date") || "").trim();
      const place = (d.get("place") || "").trim();
      const nature = (d.get("nature") || "").trim();
      const audience = (d.get("audience") || "").trim();
      const author = (d.get("author") || "").trim();
      const message = (d.get("message") || "").trim();
      const emphasis = (d.get("emphasis") || "").trim();
      const length = d.get("length") || "medium";
      const tone = d.get("tone") || "formal";
      const style = (d.get("style") || "").trim();
      const lengthMap = { short: "짧게(300자 내외)", medium: "보통(600자 내외)", long: "길게(1000자 내외)" };
      const toneMap = { formal: "공식적이고 격식 있는", warm: "따뜻하고 친근한", concise: "간결하고 명료한" };
      let prompt = "다음 행사 정보를 바탕으로 축사/인사말 초안을 작성해 주세요.\n\n";
      prompt += `행사명: ${event}\n`;
      if (date) prompt += `행사 날짜: ${date}\n`;
      if (place) prompt += `장소: ${place}\n`;
      if (nature) prompt += `행사 성격: ${nature}\n`;
      if (audience) prompt += `참석 대상: ${audience}\n`;
      if (author) prompt += `작성자/직책: ${author}\n`;
      if (message) prompt += `주요 메시지: ${message}\n`;
      if (emphasis) prompt += `강조 내용: ${emphasis}\n`;
      prompt += `분량: ${lengthMap[length] || "보통"}\n`;
      prompt += `말투: ${toneMap[tone] || "공식적"}\n`;
      if (style) prompt += `\n아래는 사용자의 기존 축사/인사말 샘플입니다. 이 문체와 어휘, 표현 특성을 반영하여 작성해 주세요:\n---\n${style}\n---\n`;
      const references = speechPc.read();
      if (references) prompt += `\n아래는 사용자의 PC에서 가져온 예전 글입니다. 문체와 어휘, 글의 구성을 참고하되 그대로 옮기지 마세요:\n---\n${references}\n---\n`;
      prompt += "\n축사 초안을 작성해 주세요. 행사 성격에 맞는 공식 축사 형식으로 작성하고, 인사말과 마무리 인사를 포함해 주세요.";
      return prompt;
    }

    async function generateSpeech(form) {
      const prompt = buildPrompt(form);
      lastPayload = prompt;
      speechResult.hidden = false;
      speechOutput.value = "생성 중...";
      try {
        speechOutput.value = await apiChat(prompt, "speech");
      } catch (e) {
        showGenerationFailure(speechOutput, speechRetry, e);
      }
      // #5727: saving is a form-area action; the click handler's empty guard
      // keeps an unused save from claiming anything.
    }
    if (speechForm) {
      speechForm.addEventListener("submit", (e) => { e.preventDefault(); generateSpeech(speechForm); });
    }
    if (copyBtn) copyBtn.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(speechOutput.value); copyBtn.textContent = "복사됨"; setTimeout(() => { copyBtn.textContent = "복사"; }, 1500); } catch (_) {}
    });
    if (downloadBtn) downloadBtn.addEventListener("click", () => { downloadText(speechOutput.value, "speech.txt"); });
    const speechPcSave = document.getElementById("utilSpeechPcSave");
    if (speechPcSave) speechPcSave.addEventListener("click", () => {
      const eventName = String(document.querySelector("#utilSpeechForm [name=event]")?.value || "축사").trim();
      void saveTextToPc(speechOutput.value, eventName || "축사");
    });

    if (saveBtn) saveBtn.addEventListener("click", async () => {
      const text = speechOutput.value.trim();
      if (!text) return;
      if (!currentPid) currentPid = await ensureProject();
      if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
      const name = (document.querySelector("#utilSpeechForm [name=event]")?.value || "축사").trim() + ".txt";
      const file = await saveProjectFile(currentPid, name, text);
      if (file) {
        saveBtn.textContent = "저장됨";
        setTimeout(() => { saveBtn.textContent = "저장"; }, 1500);
        await refreshSpeechList();
      } else {
        alert("저장 실패");
      }
    });

    const savedList = document.createElement("div");
    savedList.id = "utilSpeechSaved";
    savedList.className = "util-saved-list";
    if (speechResult) speechResult.appendChild(savedList);

    async function refreshSpeechList() {
      if (!currentPid) currentPid = await ensureProject();
      if (!currentPid) return;
      const files = await listProjectFiles(currentPid);
      const speechFiles = files.filter((f) => (f.name || "").endsWith(".txt"));
      savedList.replaceChildren();
      if (!speechFiles.length) {
        const p = el("p", "util-empty", "저장된 축사가 없습니다.");
        savedList.appendChild(p);
        return;
      }
      const ul = document.createElement("ul");
      speechFiles.forEach((f) => {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
        btn.addEventListener("click", async () => {
          const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
          if (res.ok) {
            const data = await res.json();
            const content = data && data.file && (data.file.content || data.file.text);
            if (typeof content === "string") {
              speechOutput.value = content;
              speechResult.hidden = false;
            } else {
              alert("저장된 축사의 본문을 읽을 수 없습니다.");
            }
          } else {
            alert("저장된 축사를 열지 못했습니다.");
          }
        });
        li.appendChild(btn);
        // #5731: a stored speech can be picked as the style reference — the
        // same owner/project file the list already reads fills the style
        // sample textarea, so the next generation carries it as the sample.
        const useAsRef = document.createElement("button");
        useAsRef.type = "button";
        useAsRef.className = "util-speech-use-ref";
        useAsRef.dataset.fileId = f.id;
        useAsRef.textContent = "참고로 선택";
        useAsRef.addEventListener("click", async () => {
          const styleField = document.querySelector('#utilSpeechForm [name=style]');
          if (!styleField) { alert("참고 원고 필드를 찾을 수 없습니다."); return; }
          const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
          if (!res.ok) { alert("참고 원고를 불러오지 못했습니다."); return; }
          const data = await res.json().catch(() => null);
          const content = data && data.file && (data.file.content || data.file.text);
          if (typeof content !== "string" || !content.trim()) { alert("참고 원고의 본문을 읽을 수 없습니다."); return; }
          styleField.value = content;
        });
        li.appendChild(useAsRef);
        ul.appendChild(li);
      });
      savedList.appendChild(ul);
    }

    // SNS builder
    function buildSns() {
      const panel = panels.sns;
      if (!panel || panel.dataset.loaded) return;
      panel.dataset.loaded = "1";
      const form = el("form", "util-form");
      form.id = "utilSnsForm";
      // 참고 글: the PC reference leads the form in its own titled section —
      // the speech tool's fieldset language — instead of floating between the
      // two-lane grid's field cells.
      const refSection = el("fieldset", "util-fieldset");
      refSection.id = "utilSnsRef";
      refSection.appendChild(el("legend", null, "참고 글"));
      const snsPc = createPcReferenceSection();
      snsPcRef = snsPc;
      refSection.appendChild(snsPc.box);
      form.appendChild(refSection);
      // fields
      const fields = [
        ["event", "행사명", "text", true],
        ["whenwhere", "날짜·장소", "text", false],
        ["content", "주요 내용", "textarea", true],
        ["memo", "메모", "textarea", false],
        ["audience", "대상 독자", "text", false],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        if (type === "textarea") {
          const ta = document.createElement("textarea");
          ta.name = name; ta.rows = (name === "content" ? 3 : 2);
          if (req) ta.required = true;
          l.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.name = name; inp.type = "text";
          if (req) inp.required = true;
          l.appendChild(inp);
        }
        form.appendChild(l);
      });
      const toneLabel = el("label", null, "문체 ");
      const toneSel = document.createElement("select");
      toneSel.name = "tone";
      [["casual", "캐주얼"], ["professional", "전문적"], ["emotional", "감성적"]].forEach(([v, t]) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = t;
        if (v === "professional") o.selected = true;
        toneSel.appendChild(o);
      });
      toneLabel.appendChild(toneSel);
      form.appendChild(toneLabel);

      const tabDiv = el("div", "util-sns-tabs");
      const tabNames = { blog: "블로그", facebook: "페이스북", instagram: "인스타그램" };
      let platform = "blog";
      Object.keys(tabNames).forEach((key) => {
        const b = el("button", "util-sns-tab" + (key === "blog" ? " active" : ""), tabNames[key]);
        b.type = "button";
        b.dataset.platform = key;
        b.addEventListener("click", () => {
          tabDiv.querySelectorAll(".util-sns-tab").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          platform = key;
          title.textContent = tabNames[key] + " 게시글";
          renderPhotoList();
          renderPreview();
        });
        tabDiv.appendChild(b);
      });
      form.appendChild(tabDiv);

      // #5728: photo composition replaces the old direct photo-URL field.
      // Photos are picked locally (multiple, image/*), previewed as
      // thumbnails, removable and re-orderable. Blog places each photo
      // between chosen paragraphs; facebook/instagram treat them as separate
      // post media. Photos survive platform switches, stay in this session
      // (no upload claim), and no automatic publishing is implied.
      const photos = [];
      let photoSeq = 0;
      const photoBox = el("div", "util-photos");
      photoBox.id = "utilSnsPhotoBox";
      const photoHead = el("div", "util-photos-head");
      const photoTitle = el("span", "util-photos-title", "사진");
      const photoAdd = el("button", "util-photo-add", "사진 추가");
      photoAdd.type = "button"; photoAdd.id = "utilSnsPhotoAdd";
      const photoInput = document.createElement("input");
      photoInput.type = "file"; photoInput.accept = "image/*";
      photoInput.multiple = true; photoInput.hidden = true; photoInput.id = "utilSnsPhotoInput";
      const photoCount = el("span", "util-photos-count", "0장");
      photoCount.id = "utilSnsPhotoCount";
      photoHead.append(photoTitle, photoAdd, photoInput, photoCount);
      const photoList = el("ul", "util-photo-list");
      photoList.id = "utilSnsPhotoList";
      const photoNote = el("p", "util-photo-note");
      photoNote.id = "utilSnsPhotoNote";
      photoBox.append(photoHead, photoList, photoNote);
      form.appendChild(photoBox);

      function photoNoteText() {
        if (platform === "blog") return "블로그는 각 사진을 본문 문단 사이에 삽입합니다. 미리보기에서 위치를 확인하세요.";
        if (platform === "instagram") return "인스타그램은 사진을 별도 미디어로 첨부합니다(이미지 중심 미리보기).";
        return "페이스북은 사진을 본문과 구분된 게시물 미디어로 첨부합니다.";
      }

      function readPhotoFile(file) {
        return new Promise((resolve) => {
          const reader = new FileReader();
          reader.onload = () => resolve({ id: ++photoSeq, name: file.name, dataUrl: String(reader.result || ""), position: "auto" });
          reader.onerror = () => resolve(null);
          reader.readAsDataURL(file);
        });
      }

      // #5728: the roster is one small JSON file that carries the whole
      // persisted composition — the photo order, the blog insertion
      // positions, the saved draft text and the platform it was written
      // for. The photo originals themselves are already stored (each add
      // uploaded them). Rewrites replace the previous roster in place, so a
      // stale roster can never resurrect a photo the owner deleted.
      const PHOTO_ROSTER_NAME = "SNS 사진 구성.json";
      // The last explicitly saved draft rides every roster rewrite, so a
      // later photo change never silently drops the saved text.
      let lastSavedDraft = null;
      // Roster writes serialize: two changes landing together must never
      // leave two roster files behind (an older one would win a name lookup
      // and silently revert the newer order or position).
      let rosterWriteChain = Promise.resolve();
      function writePhotoRoster(pid, savedDraft) {
        if (!pid) return;
        const carriedDraft = savedDraft === undefined ? lastSavedDraft : savedDraft;
        rosterWriteChain = rosterWriteChain.then(async () => {
          const roster = { version: 2, photos: photos
            .map((p) => ({ fileId: String(p.id), name: p.name, position: p.position })) };
          // #5728: the saved draft rides with the roster so re-entry
          // restores the text too; the last explicit 저장 wins.
          if (carriedDraft && carriedDraft.text) {
            roster.draft = { text: carriedDraft.text, platform: carriedDraft.platform || platform };
          }
          const existing = await listProjectFiles(pid);
          const previous = existing.find((f) => f.name === PHOTO_ROSTER_NAME);
          if (previous) await deleteProjectFile(pid, previous.id);
          await saveProjectFile(pid, PHOTO_ROSTER_NAME, JSON.stringify(roster), "application/json");
        }).catch(() => { /* the composition keeps working; the roster stays last-known */ });
        return rosterWriteChain;
      }

      function renderPhotoList() {
        photoCount.textContent = photos.length + "장";
        photoNote.textContent = photoNoteText();
        photoList.replaceChildren();
        photos.forEach((item, index) => {
          const li = el("li", "util-photo-item");
          const img = document.createElement("img");
          img.className = "util-photo-thumb"; img.src = item.dataUrl; img.alt = item.name;
          const nameSpan = el("span", "util-photo-name", item.name);
          const controls = el("div", "util-photo-controls");
          if (platform === "blog") {
            const posLabel = el("label", "util-photo-pos", "삽입 위치 ");
            const sel = document.createElement("select");
            sel.className = "util-photo-pos-select";
            sel.dataset.photoId = String(item.id);
            const opts = [["auto", "자동"], ["0", "맨 앞"], ["end", "문단 끝"]];
            opts.forEach(([v, t]) => { const o = document.createElement("option"); o.value = v; o.textContent = t; sel.appendChild(o); });
            sel.value = item.position;
            sel.addEventListener("change", () => { item.position = sel.value; renderPreview(); writePhotoRoster(currentPid); });
            posLabel.appendChild(sel);
            controls.appendChild(posLabel);
          }
          const up = el("button", "util-photo-move", "↑"); up.type = "button"; up.dataset.move = "-1"; up.dataset.photoId = String(item.id);
          const down = el("button", "util-photo-move", "↓"); down.type = "button"; down.dataset.move = "1"; down.dataset.photoId = String(item.id);
          const del = el("button", "util-photo-remove", "삭제"); del.type = "button"; del.dataset.photoId = String(item.id); del.dataset.action = "remove";
          controls.append(up, down, del);
          li.append(img, nameSpan, controls);
          photoList.appendChild(li);
        });
      }

      photoList.addEventListener("click", async (ev) => {
        const target = ev.target;
        if (!target || !target.dataset) return;
        // Stored photos carry server ids like "file_<hex>"; local-only rows
        // carry numeric ids. Compare as strings so both resolve.
        const id = String(target.dataset.photoId);
        const index = photos.findIndex((p) => String(p.id) === id);
        if (index < 0) return;
        if (target.dataset.move) {
          const to = index + Number(target.dataset.move);
          if (to < 0 || to >= photos.length) return;
          const [moved] = photos.splice(index, 1);
          photos.splice(to, 0, moved);
        } else if (target.dataset.action === "remove") {
          if (photos[index].id && currentPid) {
            const gone = await deleteProjectFile(currentPid, photos[index].id);
            if (!gone) { alert("사진 삭제 실패: " + photos[index].name); return; }
          }
          photos.splice(index, 1);
        } else {
          return;
        }
        renderPhotoList();
        renderPreview();
        // #5728: every durable composition change (reorder and removal here,
        // insertion positions on the selects) rewrites the roster file, so
        // the order and the blog insertion positions outlive the session.
        writePhotoRoster(currentPid);
      });

      // #5728: one upload pipeline serves both pickers. A photo joins the
      // composition only once the project-file upload succeeded — the
      // thumbnail and the stored original are the same bytes, and a failed
      // upload never looks "saved". Failures land in one Korean row with its
      // own retry, never in an alert that vanishes with the keyboard away.
      let pendingFailedPhotos = [];

      // #5728: big camera photos are shrunk in the browser before upload.
      // The Cloudflare Worker caps a request body at 128 MB and the free
      // plan's CPU allowance per request is measured in milliseconds, so
      // re-encoding a 20 MB original server-side is neither possible nor
      // needed — the browser that holds the file can do it. A browser
      // without the decode APIs uploads the original unchanged.
      const PHOTO_SHRINK_TRIGGER_BYTES = 4 * 1024 * 1024;
      const PHOTO_MAX_EDGE = 2048;

      async function shrinkPhotoFile(file) {
        if (!file || !(Number(file.size) > PHOTO_SHRINK_TRIGGER_BYTES)) return file;
        if (typeof createImageBitmap !== "function") return file;
        try {
          const bitmap = await createImageBitmap(file);
          const scale = Math.min(1, PHOTO_MAX_EDGE / Math.max(bitmap.width, bitmap.height));
          if (scale >= 1) {
            if (typeof bitmap.close === "function") bitmap.close();
            return file;
          }
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(bitmap.width * scale));
          canvas.height = Math.max(1, Math.round(bitmap.height * scale));
          const ctx = canvas.getContext("2d");
          ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
          if (typeof bitmap.close === "function") bitmap.close();
          const blob = await new Promise((resolve) => {
            if (typeof canvas.toBlob === "function") canvas.toBlob((b) => resolve(b), "image/jpeg", 0.85);
            else resolve(null);
          });
          if (!blob) return file;
          const base = String(file.name || "photo").replace(/\.[^.]+$/, "");
          return new File([blob], base + ".jpg", { type: "image/jpeg" });
        } catch (_) {
          return file;
        }
      }

      function photoImageType(name) {
        const lower = String(name || "").toLowerCase();
        if (lower.endsWith(".png")) return "image/png";
        if (lower.endsWith(".webp")) return "image/webp";
        return "image/jpeg";
      }

      function renderPhotoUploadFailure() {
        photoBox.querySelectorAll(".util-photo-upload-failed").forEach((n) => n.remove());
        if (!pendingFailedPhotos.length) return;
        const row = el("div", "util-photo-upload-failed");
        const text = el("span", "util-photo-upload-failed-text",
          "사진 " + pendingFailedPhotos.length + "장을 올리지 못했어요");
        const retry = el("button", "util-photo-upload-retry", "다시 시도");
        retry.type = "button";
        retry.id = "utilSnsPhotoRetry";
        retry.addEventListener("click", () => {
          void addPhotoFiles(pendingFailedPhotos.slice());
        });
        row.append(text, retry);
        photoBox.appendChild(row);
      }

      async function addPhotoFiles(files) {
        const failed = [];
        for (const file of files) {
          if (!file || String(file.type || "").indexOf("image/") !== 0) continue;
          if (!currentPid) currentPid = await ensureProject();
          if (!currentPid) { failed.push(file); continue; }
          const prepared = await shrinkPhotoFile(file);
          const stored = await uploadProjectImage(currentPid, prepared);
          if (!stored) { failed.push(file); continue; }
          const item = await readPhotoFile(prepared);
          if (item) { item.id = stored.id; photos.push(item); }
        }
        pendingFailedPhotos = failed;
        renderPhotoUploadFailure();
        photoInput.value = "";
        renderPhotoList();
        renderPreview();
        // An added photo is part of the durable composition as soon as its
        // upload landed — the roster records it right away.
        if (!failed.length) writePhotoRoster(currentPid);
      }

      photoAdd.addEventListener("click", async () => {
        // The shared 가져오기 dialog browses the linked PC; a machine with no
        // linked PC (a phone included) keeps the local file picker.
        let linked = null;
        try { linked = await pcLinked(); } catch (_) { linked = null; }
        if (linked === false) { photoInput.click(); return; }
        let component;
        try { component = await loadPcExchange(); } catch (_) { component = null; }
        if (!component || typeof component.open !== "function") { photoInput.click(); return; }
        component.open({
          mode: "import",
          onSelect: (picked) => { void importPickedPhoto(picked); },
        });
      });

      async function importPickedPhoto(picked) {
        if (!picked || !picked.fileId) return;
        const name = picked.name || "사진.jpg";
        let blob = null;
        try {
          const res = await fetch(
            "/api/pc/file?dispatch_id=" + encodeURIComponent(picked.fileId),
            { credentials: "include", cache: "no-store" },
          );
          if (!res.ok) throw new Error("http_" + res.status);
          blob = await res.blob();
          const bytes = await blob.arrayBuffer();
          await addPhotoFiles([new File([bytes], name, { type: photoImageType(name) })]);
        } catch (_) {
          pendingFailedPhotos = [{ name: name, type: photoImageType(name), size: Number(blob && blob.size) || 0 }];
          renderPhotoUploadFailure();
        }
      }

      photoInput.addEventListener("change", () => {
        void addPhotoFiles(Array.from(photoInput.files || []));
      });

      function blogParagraphs(text) {
        return String(text || "").split(new RegExp("\\n\\s*\\n")).filter((p) => p.trim());
      }

      function interleaveBlog(text) {
        const parts = blogParagraphs(text);
        if (!photos.length) return parts.map((p) => ({ type: "text", value: p }));
        const out = [];
        if (photos.some((p) => p.position === "0")) {
          photos.filter((p) => p.position === "0").forEach((p) => out.push({ type: "photo", value: p }));
        }
        parts.forEach((para, i) => {
          out.push({ type: "text", value: para });
          photos.forEach((p) => {
            if (p.position === "auto") { if (i === Math.min(photos.indexOf(p), Math.max(parts.length - 1, 0))) out.push({ type: "photo", value: p }); }
            else if (p.position === "end") { if (i === parts.length - 1) out.push({ type: "photo", value: p }); }
            else if (String(i + 1) === String(p.position)) { out.push({ type: "photo", value: p }); }
          });
        });
        return out;
      }

      function renderPreview() {
        const box = document.getElementById("utilSnsPreview");
        if (!box || box.hidden) return;
        box.replaceChildren();
        const text = output.value || "";
        if (platform === "blog") {
          interleaveBlog(text).forEach((seg) => {
            if (seg.type === "text") { const p = el("p", "util-preview-para", seg.value); box.appendChild(p); }
            else { const im = document.createElement("img"); im.className = "util-preview-photo"; im.src = seg.value.dataUrl; im.alt = seg.value.name; box.appendChild(im); }
          });
        } else {
          if (text.trim()) { const p = el("p", "util-preview-para", text); box.appendChild(p); }
          const grid = el("div", "util-sns-media-grid" + (platform === "instagram" ? " insta" : ""));
          photos.forEach((ph) => { const im = document.createElement("img"); im.src = ph.dataUrl; im.alt = ph.name; grid.appendChild(im); });
          box.appendChild(grid);
        }
        const note = el("p", "util-photo-note", "미리보기는 초안 구성 확인용입니다. 실제 SNS 자동 게시 기능이 아닙니다.");
        box.appendChild(note);
      }

      renderPhotoList();

      // #5727: the form owns 생성+저장; the result area keeps 복사+다운로드 only.
      const formActions = el("div", "util-form-actions");
      const submitBtn = el("button", "util-generate", "생성");
      submitBtn.type = "submit";
      const formSaveB = el("button", "util-save", "저장");
      formSaveB.type = "button"; formSaveB.id = "utilSnsSave";
      formActions.append(submitBtn, formSaveB);
      form.appendChild(formActions);

      const result = el("div", "util-result");
      result.id = "utilSnsResult";
      result.hidden = true;
      const h3 = el("h3", null, "블로그 게시글");
      h3.id = "utilSnsTitle";
      const output = document.createElement("textarea");
      output.id = "utilSnsOutput";
      output.rows = 12;
      const previewBox = el("div", "util-sns-preview");
      previewBox.id = "utilSnsPreview";
      previewBox.hidden = true;
      const actions = el("div", "util-actions");
      const copyB = el("button", null, "복사"); copyB.type = "button"; copyB.id = "utilSnsCopy";
      const dlB = el("button", null, "TXT 다운로드"); dlB.type = "button"; dlB.id = "utilSnsDownload";
      const pcSaveB = el("button", "util-save", PC_REF_COPY.save);
      pcSaveB.type = "button"; pcSaveB.id = "utilSnsPcSave";
      const snsRetry = retryButton("utilSnsRetry", () => { void gen(); });
      actions.append(copyB, dlB, pcSaveB, snsRetry);
      result.append(h3, output, previewBox, actions);

      panel.replaceChildren(form, result);
      const title = h3;

      // #5728: re-entry restores the persisted composition ONCE, at build
      // time — before any interaction with the photo list. The stored image
      // files are the originals; when the roster file exists it fixes the
      // order and the blog insertion positions, and photos it does not
      // mention still surface after it so nothing the owner stored vanishes.
      // A roster that carries a saved draft (version 2) also restores the
      // draft text and switches to the platform it was saved under.
      (async () => {
        try {
          if (!currentPid) currentPid = await ensureProject();
          if (!currentPid) return;
          const files = await listProjectFiles(currentPid);
          const imageFiles = files.filter((f) => f.media_type === "image/png"
            || f.media_type === "image/jpeg" || f.media_type === "image/webp");
          let order = null;
          let savedDraft = null;
          const rosterFile = files.find((f) => f.name === PHOTO_ROSTER_NAME);
          if (rosterFile) {
            const detailRes = await fetch("/api/projects/" + currentPid + "/files/" + encodeURIComponent(rosterFile.id), { credentials: "include" });
            if (detailRes.ok) {
              const detail = await detailRes.json().catch(() => null);
              try {
                const roster = JSON.parse(String((detail && detail.file && detail.file.content) || ""));
                if (roster && Array.isArray(roster.photos)) order = roster.photos;
                // A saved draft is part of the same roster record; a v1
                // roster (photos only) leaves the draft area untouched.
                if (roster && roster.draft && typeof roster.draft.text === "string" && roster.draft.text.trim()) {
                  savedDraft = roster.draft;
                }
              } catch (_) { /* unreadable roster falls back to the stored order */ }
            }
          }
          if (savedDraft) {
            // The draft comes back with the platform it was written for;
            // photos restore after this so the preview is coherent. It also
            // rides future roster rewrites, so a later photo change never
            // silently drops the saved text.
            lastSavedDraft = savedDraft;
            result.hidden = false;
            output.value = savedDraft.text;
            if (previewBox) { previewBox.hidden = false; }
            if (savedDraft.platform && savedDraft.platform !== platform) {
              const targetTab = Array.from(tabDiv.querySelectorAll(".util-sns-tab")).find((t) => t.dataset.platform === savedDraft.platform);
              if (targetTab) targetTab.click();
              else { platform = savedDraft.platform; title.textContent = ({ blog: "블로그", facebook: "페이스북", instagram: "인스타그램" })[savedDraft.platform] + " 게시글"; }
            }
          }
          if (photos.length || !imageFiles.length) {
            if (savedDraft) renderPreview();
            return;
          }
          const ordered = [];
          if (order && order.length) {
            order.forEach((entry) => {
              const meta = imageFiles.find((f) => f.id === (entry && entry.fileId));
              if (meta) ordered.push({ meta: meta, position: entry && typeof entry.position === "string" && entry.position ? entry.position : "auto" });
            });
            imageFiles.forEach((meta) => {
              if (!ordered.some((o) => o.meta.id === meta.id)) ordered.push({ meta: meta, position: "auto" });
            });
          } else {
            imageFiles.forEach((meta) => ordered.push({ meta: meta, position: "auto" }));
          }
          for (const entry of ordered) {
            const dataUrl = await fetchOriginalDataUrl(currentPid, entry.meta.id);
            if (!dataUrl) continue;
            photos.push({ id: entry.meta.id, name: entry.meta.name, dataUrl: dataUrl, position: entry.position });
          }
          renderPhotoList();
          renderPreview();
        } catch (_) { /* restore is best effort; an empty composition stays honest */ }
      })();

      async function gen() {
        const d = new FormData(form);
        const event = (d.get("event") || "").trim();
        const whenwhere = (d.get("whenwhere") || "").trim();
        const content = (d.get("content") || "").trim();
        const photo = (d.get("photo") || "").trim();
        const memo = (d.get("memo") || "").trim();
        const audience = (d.get("audience") || "").trim();
        const tone = d.get("tone") || "professional";
        const toneMap = { casual: "캐주얼하고 친근한", professional: "전문적이고 신뢰감 있는", emotional: "감성적이고 따뜻한" };
        const platformGuide = {
          blog: "블로그 게시글: 800-1200자, 제목 포함, 소제목 구분, 상세한 설명",
          facebook: "페이스북 게시글: 300-500자, 친근한 톤, 이모지 적절히, 해시태그 3-5개",
          instagram: "인스타그램 게시글: 150-300자, 짧고 임팩트 있는, 해시태그 10-15개, 이모지 풍부",
        };
        let prompt = `다음 행사 정보를 바탕으로 ${platformGuide[platform]}을 작성해 주세요.\n\n`;
        prompt += `행사명: ${event}\n`;
        if (whenwhere) prompt += `날짜·장소: ${whenwhere}\n`;
        prompt += `주요 내용: ${content}\n`;
        if (photos.length) {
          const names = photos.map((ph) => ph.name).join(", ");
          prompt += `첨부 사진: ${photos.length}장 (${names})\n`;
          prompt += platform === "blog"
            ? "사진은 본문 문단 사이에 삽입됩니다. 각 사진이 어느 내용과 이어지는지 참고해서 문단을 구성해 주세요.\n"
            : "사진은 본문과 구분된 게시물 미디어로 첨부됩니다. 본문에 이미지 위치 설명은 넣지 마세요.\n";
        }
        if (memo) prompt += `메모: ${memo}\n`;
        if (audience) prompt += `대상 독자: ${audience}\n`;
        prompt += `문체: ${toneMap[tone]}\n`;
        const references = snsPc.read();
        if (references) {
          prompt += `아래는 사용자의 PC에서 가져온 예전 글입니다. 문체와 어휘, 글의 구성을 참고하되 그대로 옮기지 마세요:\n---\n${references}\n---\n`;
        }
        prompt += "\n제목, 본문, 해시태그를 구분하여 작성해 주세요.";
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(prompt, "sns"); }
        catch (e) { showGenerationFailure(output, snsRetry, e); }
        if (previewBox) { previewBox.hidden = false; renderPreview(); }
      }
      form.addEventListener("submit", (e) => { e.preventDefault(); gen(); });
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      dlB.addEventListener("click", () => { downloadText(output.value, "sns-" + platform + ".txt"); });
      pcSaveB.addEventListener("click", () => {
        const eventName = String(document.querySelector("#utilSnsForm [name=event]")?.value || "SNS").trim();
        void saveTextToPc(output.value, eventName || "SNS");
      });
      formSaveB.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text) return;
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const name = (h3.textContent || "sns").trim() + ".txt";
        const file = await saveProjectFile(currentPid, name, text);
        if (file) {
          formSaveB.textContent = "저장됨";
          setTimeout(() => { formSaveB.textContent = "저장"; }, 1500);
          // #5728: the saved draft rides in the roster so re-entry restores
          // the text and its platform, not only the photos.
          lastSavedDraft = { text: text, platform: platform };
          writePhotoRoster(currentPid, lastSavedDraft);
        } else {
          alert("저장 실패");
        }
      });

    }

    // Meeting builder
    function buildMeeting() {
      const panel = panels.meeting;
      if (!panel || panel.dataset.loaded) return;
      panel.dataset.loaded = "1";
      // #5608: activity books persist under their own name rule so the
      // meeting record list and the book list stay two separate data flows
      // over the same project-file store.
      const BOOK_PREFIX = "활동집 - ";
      const form = el("form", "util-form");
      form.id = "utilMeetingForm";
      const fields = [
        ["title", "회의명", "text", true],
        ["when", "회의 일시", "datetime-local", false],
        ["attendees", "참석자", "text", false],
        ["content", "회의 내용", "textarea", true],
      ];
      fields.forEach(([name, label, type, req]) => {
        const l = el("label", null, label + " ");
        if (type === "textarea") {
          const ta = document.createElement("textarea");
          ta.name = name; ta.rows = (name === "content" ? 6 : 2);
          if (req) ta.required = true;
          l.appendChild(ta);
        } else {
          const inp = document.createElement("input");
          inp.name = name; inp.type = type;
          if (req) inp.required = true;
          l.appendChild(inp);
        }
        form.appendChild(l);
      });
      // #5727: the form owns 생성+저장; the result area keeps 복사+다운로드 only.
      const formActions = el("div", "util-form-actions");
      const submitBtn = el("button", "util-generate", "요약 생성");
      submitBtn.type = "submit";
      const formSaveB = el("button", "util-save", "저장");
      formSaveB.type = "button"; formSaveB.id = "utilMeetingSave";
      formActions.append(submitBtn, formSaveB);
      form.appendChild(formActions);

      const result = el("div", "util-result");
      result.id = "utilMeetingResult";
      result.hidden = true;
      const h3 = el("h3", null, "회의 요약");
      const output = document.createElement("textarea");
      output.id = "utilMeetingOutput";
      output.rows = 12;
      const actions = el("div", "util-actions");
      const copyB = el("button", null, "복사"); copyB.type = "button"; copyB.id = "utilMeetingCopy";
      const dlB = el("button", null, "TXT 다운로드"); dlB.type = "button"; dlB.id = "utilMeetingDownload";
      const meetingRetry = retryButton("utilMeetingRetry", () => { void gen(); });
      actions.append(copyB, dlB, meetingRetry);
      result.append(h3, output, actions);

      const archive = el("div", "util-archive");
      archive.id = "utilMeetingArchive";
      const archiveH = el("h3", null, "활동 기록");
      const archiveEmpty = el("p", "util-empty", "저장된 회의 기록이 없습니다.");
      archive.append(archiveH, archiveEmpty);

      panel.replaceChildren(form, result, archive);

      async function gen() {
        const d = new FormData(form);
        const title = (d.get("title") || "").trim();
        const when = (d.get("when") || "").trim();
        const attendees = (d.get("attendees") || "").trim();
        const content = (d.get("content") || "").trim();
        let prompt = "다음 회의 내용을 정리해 주세요.\n\n";
        prompt += `회의명: ${title}\n`;
        if (when) prompt += `회의 일시: ${when}\n`;
        if (attendees) prompt += `참석자: ${attendees}\n`;
        prompt += `회의 내용:\n${content}\n\n`;
        prompt += "다음 항목으로 정리해 주세요:\n1. 회의 요약 (3-5문장)\n2. 주요 논의사항 (bullet)\n3. 결정사항 (bullet)\n4. 후속 업무 (담당자/일정이 원문에 있으면 포함)\n5. 미해결 사항";
        result.hidden = false;
        output.value = "생성 중...";
        try { output.value = await apiChat(prompt, "meeting"); }
        catch (e) { showGenerationFailure(output, meetingRetry, e); }
      }
      form.addEventListener("submit", (e) => { e.preventDefault(); gen(); });
      copyB.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(output.value); copyB.textContent = "복사됨"; setTimeout(() => { copyB.textContent = "복사"; }, 1500); } catch (_) {}
      });
      formSaveB.addEventListener("click", async () => {
        const text = output.value.trim();
        if (!text) return;
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
        const name = (form.querySelector("[name=title]")?.value || "회의").trim() + ".txt";
        const file = await saveProjectFile(currentPid, name, text);
        if (file) {
          formSaveB.textContent = "저장됨";
          setTimeout(() => { formSaveB.textContent = "저장"; }, 1500);
          await refreshArchive(archive);
        } else {
          alert("저장 실패");
        }
      });
      dlB.addEventListener("click", () => { downloadText(output.value, "meeting.txt"); });

      async function refreshArchive(arc) {
        if (!currentPid) currentPid = await ensureProject();
        if (!currentPid) return;
        const files = await listProjectFiles(currentPid);
        // #5608/#5783: every .txt in the project is a stored record — speech
        // drafts included. The builder only consumes what the user checks, so
        // nothing unselected can reach the AI prompt (no cross-record bleed).
        const meetingFiles = files.filter((f) => (f.name || "").endsWith(".txt"));
        // #5608: activity books persist under the activity-book name rule;
        // they surface in their own section, not as raw meeting records.
        const bookFiles = meetingFiles.filter((f) => (f.name || "").startsWith(BOOK_PREFIX));
        arc.replaceChildren();
        const h = el("h3", null, "활동 기록");
        arc.appendChild(h);
        if (!meetingFiles.length) {
          const p = el("p", "util-empty", "저장된 회의 기록이 없습니다.");
          arc.appendChild(p);
          return;
        }
        const bookBtn = el("button", "util-generate", "선택 기록으로 책/활동집 초안 생성");
        bookBtn.type = "button";
        bookBtn.id = "utilBookGenerate";
        bookBtn.style.marginBottom = "8px";
        arc.appendChild(bookBtn);

        // #5608: the record order here is the book order. The up/down moves
        // re-arrange this list itself, so what the user sees is exactly the
        // sequence the book builder reads.
        let order = meetingFiles.slice();
        const ul = document.createElement("ul");
        function renderRows() {
          ul.replaceChildren();
          order.forEach((f, index) => {
            const li = document.createElement("li");
            li.style.display = "flex";
            li.style.alignItems = "center";
            li.style.gap = "8px";
            const cb = document.createElement("input");
            cb.type = "checkbox";
            cb.value = f.id;
            cb.className = "util-book-check";
            cb.setAttribute("aria-label", f.name + " 책/활동집에 포함");
            li.appendChild(cb);
            const btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
            btn.style.flex = "1";
            btn.addEventListener("click", async () => {
              const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
              if (res.ok) {
                const data = await res.json();
                const out = document.getElementById("utilMeetingOutput");
                const content = data && data.file && (data.file.content || data.file.text);
                if (out && typeof content === "string") {
                  out.value = content;
                  result.hidden = false;
                } else {
                  alert("저장된 회의 기록의 본문을 읽을 수 없습니다.");
                }
              } else {
                alert("저장된 회의 기록을 열지 못했습니다.");
              }
            });
            li.appendChild(btn);
            const up = document.createElement("button");
            up.type = "button";
            up.className = "util-record-move";
            up.dataset.move = "-1";
            up.dataset.fileName = f.name;
            up.textContent = "↑";
            up.disabled = index === 0;
            up.addEventListener("click", () => {
              const to = index - 1;
              if (to < 0) return;
              const [moved] = order.splice(index, 1);
              order.splice(to, 0, moved);
              renderRows();
            });
            const down = document.createElement("button");
            down.type = "button";
            down.className = "util-record-move";
            down.dataset.move = "1";
            down.dataset.fileName = f.name;
            down.textContent = "↓";
            down.disabled = index === order.length - 1;
            down.addEventListener("click", () => {
              const to = index + 1;
              if (to >= order.length) return;
              const [moved] = order.splice(index, 1);
              order.splice(to, 0, moved);
              renderRows();
            });
            li.appendChild(up);
            li.appendChild(down);
            ul.appendChild(li);
          });
        }
        renderRows();
        arc.appendChild(ul);

        const bookResult = el("div", "util-result");
        bookResult.id = "utilBookResult";
        bookResult.hidden = true;
        const bookH = el("h3", null, "책/활동집 초안");
        const bookOutput = document.createElement("textarea");
        bookOutput.id = "utilBookOutput";
        bookOutput.rows = 16;
        // #5727: result actions are copy/download only; regenerating the
        // book draft is re-pressing the generate button in the selection area.
        const bookRetry = retryButton("utilBookRetry", () => bookBtn.click());
        const bookActions = el("div", "util-actions");
        const bookCopy = el("button", null, "복사"); bookCopy.type = "button";
        const bookDl = el("button", null, "TXT 다운로드"); bookDl.type = "button";
        // #5608: the book draft is a product, not scratch — it persists
        // through the same project-file channel under its own name rule, so
        // re-entering the tool restores and re-edits it.
        const bookSave = el("button", "util-save", "활동집 저장"); bookSave.type = "button"; bookSave.id = "utilBookSave";
        bookActions.append(bookCopy, bookDl, bookSave, bookRetry);
        bookResult.append(bookH, bookOutput, bookActions);
        arc.appendChild(bookResult);

        bookBtn.addEventListener("click", async () => {
          const checked = Array.from(document.querySelectorAll(".util-book-check:checked"));
          if (!checked.length) { alert("선택된 기록이 없습니다."); return; }
          // #5608: the book reads the records in the order the list shows —
          // the same sequence the up/down moves arrange. Only the checked
          // records enter the prompt: nothing unselected can bleed in.
          const checkedIds = new Set(checked.map((cb) => cb.value));
          const ordered = order.filter((f) => checkedIds.has(f.id));
          bookResult.hidden = false;
          bookOutput.value = "선택한 회의 기록을 불러오는 중...";
          try {
            const contents = [];
            for (const file of ordered) {
              const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(file.id), { credentials: "include" });
              if (!res.ok) throw new Error("선택한 회의 기록을 불러오지 못했습니다: " + file.name);
              const data = await res.json();
              if (!data || !data.file || typeof data.file.content !== "string" || !data.file.content.trim()) {
                throw new Error("선택한 회의 기록의 본문이 비어 있거나 올바르지 않습니다: " + file.name);
              }
              contents.push("[기록: " + data.file.name + "]\n" + data.file.content);
            }
            let prompt = "다음은 사용자가 선택한 활동 기록 본문입니다. 각 기록의 이름을 출처로 유지하세요.\n\n";
            prompt += contents.join("\n\n") + "\n\n";
            prompt += "위 기록을 바탕으로 다음을 생성해 주세요:\n";
            prompt += "1. 책/활동집 제목 후보 3개\n";
            prompt += "2. 목차 (5-8장)\n";
            prompt += "3. 각 장별 원고 초안 (200-400자)\n";
            prompt += "4. 마무리 인사\n\n";
            prompt += "주의: 원본 기록에 없는 사건, 날짜, 발언을 사실처럼 추가하지 마세요. 근거가 있는 내용과 제안/해석을 구분하세요. 각 장 끝에 근거가 된 기록 파일명을 표시하세요.";
            bookOutput.value = "생성 중...";
            bookOutput.value = await apiChat(prompt, "meeting");
          } catch (e) {
            showGenerationFailure(bookOutput, bookRetry, e);
          }
        });

        bookCopy.addEventListener("click", async () => {
          try { await navigator.clipboard.writeText(bookOutput.value); bookCopy.textContent = "복사됨"; setTimeout(() => { bookCopy.textContent = "복사"; }, 1500); } catch (_) {}
        });
        bookDl.addEventListener("click", () => { downloadText(bookOutput.value, "book-draft.txt"); });

        // #5608: saving the book uses its own name rule so books never mix
        // with meeting records in the list — the book section reads only
        // names starting with BOOK_PREFIX. The title comes from the draft's
        // first line (what the user edited); fallback keeps a safe name.
        bookSave.addEventListener("click", async () => {
          const text = bookOutput.value.trim();
          if (!text) return;
          if (!currentPid) currentPid = await ensureProject();
          if (!currentPid) { alert("프로젝트를 찾을 수 없습니다."); return; }
          const firstLine = text.split("\n", 1)[0].replace(/^[0-9]+\.\s*/, "").trim();
          const safe = firstLine.replace(/[\\/:*?"<>|]/g, "").replace(/\.*$/, "").slice(0, 40).trim();
          const name = BOOK_PREFIX + (safe || "제목 미정") + ".txt";
          const file = await saveProjectFile(currentPid, name, text);
          if (file) {
            bookSave.textContent = "저장됨";
            setTimeout(() => { bookSave.textContent = "활동집 저장"; }, 1500);
            await refreshArchive(arc);
          } else {
            alert("활동집 저장 실패");
          }
        });

        // Stored books reopen into the editor for editing and re-saving.
        if (bookFiles.length) {
          const bookSec = el("div", null);
          const bookSecH = el("h3", null, "저장된 활동집");
          bookSec.appendChild(bookSecH);
          const bookUl = document.createElement("ul");
          bookFiles.forEach((f) => {
            const li = document.createElement("li");
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "util-book-open";
            btn.textContent = f.name + " (" + (f.content_chars || 0) + "자)";
            btn.addEventListener("click", async () => {
              const res = await fetch("/api/projects/" + encodeURIComponent(currentPid) + "/files/" + encodeURIComponent(f.id), { credentials: "include" });
              if (res.ok) {
                const data = await res.json();
                const content = data && data.file && (data.file.content || data.file.text);
                if (typeof content === "string") {
                  bookOutput.value = content;
                  bookResult.hidden = false;
                } else {
                  alert("저장된 활동집의 본문을 읽을 수 없습니다.");
                }
              } else {
                alert("저장된 활동집을 열지 못했습니다.");
              }
            });
            li.appendChild(btn);
            bookUl.appendChild(li);
          });
          bookSec.appendChild(bookUl);
          arc.appendChild(bookSec);
        }
      }
      refreshArchive(archive);
    }
  });
})();
