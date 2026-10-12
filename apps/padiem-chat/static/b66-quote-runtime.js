(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const COPY = {
    ko: {
      launcher: "내 견적서",
      title: "내 견적서 만들기",
      description: "거래처, 품목, 수량, 단가만 편하게 말해 주세요.",
      requestLabel: "견적 요청",
      requestPlaceholder: "예: ABC건설에 배관 20개, 개당 3만원으로 견적서 만들어줘",
      generate: "견적서 만들기",
      close: "닫기",
      selectLabel: "견적서 양식",
      idle: "내용을 입력하면 배정된 견적서 양식으로 바로 만듭니다.",
      working: "견적 내용을 정리하고 있습니다.",
      missing: "거래처와 품목·수량·단가를 조금 더 알려 주세요.",
      companyIdentityMissing: "견적서에 넣을 회사명을 확인해 주세요.",
      companyDefaultsMissing: "회사 기본 유효기간을 확인해 주세요.",
      ready: "견적서가 준비되었습니다. 아래에서 확인하거나 PDF로 저장하세요.",
      failed: "견적서를 만들지 못했습니다. 입력 내용을 확인해 주세요.",
      pcToggle: "내 컴퓨터 · 연결 상태",
      pcHelp: "PADIEM Connect 설치와 같은 계정 로그인 기능은 준비 중입니다. 파일 작업은 별도 승인이 필요합니다.",
      pcRefresh: "상태 새로고침",
      pcLoading: "서버에서 연결 상태를 확인하고 있습니다.",
      pcAuth: "PADIEM 계정에 로그인한 뒤 확인해 주세요.",
      pcUnavailable: "PC 연결 서비스가 아직 준비되지 않았습니다. 연결이 완료됐다고 표시하지 않습니다.",
      pcFailed: "PC 연결 상태를 확인하지 못했습니다.",
      pcEmpty: "현재 계정에 등록된 컴퓨터가 없습니다.",
      pcReady: "확인된 컴퓨터 목록입니다. 이 화면에서는 파일에 접근하거나 작업을 실행하지 않습니다.",
      pcOnline: "온라인 · 작업 승인 필요",
      pcOffline: "오프라인",
      pcRevoked: "연결 해제"
    },
    en: {
      launcher: "My quote",
      title: "Create my quote",
      description: "Tell me the customer, item, quantity, and unit price.",
      requestLabel: "Quote request",
      requestPlaceholder: "Example: Quote 20 pipes at 30,000 each for ABC Construction",
      generate: "Create quote",
      close: "Close",
      selectLabel: "Quote template",
      idle: "Enter the changing values and your assigned template will be used.",
      working: "Preparing the quote values.",
      missing: "Please add the customer and item, quantity, and unit price.",
      companyIdentityMissing: "Please confirm the company name to use on the quote.",
      companyDefaultsMissing: "Please confirm your company's default quote validity period.",
      ready: "Your quote is ready. Review it below or save it as PDF.",
      failed: "The quote could not be created. Check your request and try again.",
      pcToggle: "My computers · connection status",
      pcHelp: "PADIEM Connect installation and same-account sign-in are not ready yet. File operations require separate approval.",
      pcRefresh: "Refresh status",
      pcLoading: "Checking connection status with the server.",
      pcAuth: "Sign in to your PADIEM account first.",
      pcUnavailable: "The PC connection service is not ready. No connection is claimed.",
      pcFailed: "Could not verify PC connection status.",
      pcEmpty: "No computers are registered for this account.",
      pcReady: "Server-confirmed computers. This view cannot read files or execute tasks.",
      pcOnline: "Online · approval required",
      pcOffline: "Offline",
      pcRevoked: "Disconnected"
    }
  };

  let runtime = null;
  let skills = [];
  let modelIds = [];
  let reasoningByModel = {};
  let initialized = false;
  let refreshPromise = null;
  let currentRequestId = null;
  let frameLoadedUrl = "";
  let pcQuerySequence = 0;
  const PC_DIRECTORY_PATH = "/api/claw/local-access/devices";
  const MAX_PC_DIRECTORY_BYTES = 32768;
  const B66_ASSET_ID = /^b66asset_[0-9a-f]{32}$/;
  const PRIVATE_ASSET_MEDIA = new Set(["image/png", "image/jpeg", "image/webp"]);
  const MAX_PRIVATE_ASSET_BYTES = 256 * 1024;

  function copy() {
    return COPY[document.documentElement.lang === "en" ? "en" : "ko"];
  }

  function validRuntime(data) {
    if (!data || data.ok !== true || data.enabled !== true) return null;
    if (typeof data.embed_url !== "string" || typeof data.origin !== "string") return null;
    try {
      const embed = new URL(data.embed_url);
      const origin = new URL(data.origin);
      if (embed.protocol !== "https:" || origin.protocol !== "https:") return null;
      if (embed.origin !== origin.origin || data.origin !== origin.origin) return null;
      if (!embed.pathname.endsWith("/embed.html")) return null;
      // The canonical product permission gate must set this explicitly.
      // Existing B66 runtime-config does not issue it: default stays OFF.
      return Object.freeze({
        embedUrl: embed.href,
        origin: origin.origin,
        pcDirectoryEnabled: data.pc_device_list_enabled === true
      });
    } catch (_) {
      return null;
    }
  }

  function safeSkills(data) {
    if (!data || data.ok !== true || !Array.isArray(data.skills)) return [];
    return data.skills.filter((item) => (
      item && typeof item === "object" &&
      typeof item.saved_skill_id === "string" &&
      /^b66skill_[0-9a-f]{32}$/.test(item.saved_skill_id) &&
      typeof item.skill_name === "string" &&
      item.skill_name.trim()
    )).slice(0, 20);
  }

  function companyProfileForRender(profile) {
    if (profile === null || profile === undefined) {
      return { ok: true, code: "absent", profile: null };
    }
    if (typeof profile !== "object" || Array.isArray(profile)) {
      return { ok: false, code: "invalid", profile: null };
    }
    if (typeof profile.company !== "string" || !profile.company.trim()) {
      return { ok: false, code: "missing_company", profile: null };
    }
    if (!Number.isInteger(profile.defaultValidityDays) || profile.defaultValidityDays < 0 || profile.defaultValidityDays > 3650) {
      return { ok: false, code: "missing_validity", profile: null };
    }
    return {
      ok: true,
      code: "ready",
      profile: {
        company: profile.company,
        representative: profile.representative,
        contactPerson: profile.contactPerson,
        businessNumber: profile.businessNumber,
        address: profile.address,
        phone: profile.phone,
        email: profile.email,
        defaultValidityDays: profile.defaultValidityDays,
        defaultTaxMode: profile.defaultTaxMode
      }
    };
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function ensureUi() {
    if (initialized) return;
    initialized = true;
    const firstNav = document.querySelector(".side-nav");
    if (!firstNav) return;

    const launcher = el("button", "side-item b66-quote-launcher");
    launcher.id = "b66QuoteNavButton";
    launcher.type = "button";
    launcher.hidden = true;
    launcher.setAttribute("aria-haspopup", "dialog");
    launcher.setAttribute("aria-controls", "b66QuoteDialog");
    launcher.setAttribute("aria-expanded", "false");
    const icon = el("span", "side-icon", "₩");
    icon.setAttribute("aria-hidden", "true");
    const label = el("span", "", copy().launcher);
    label.dataset.b66QuoteLauncherLabel = "true";
    launcher.append(icon, label);
    const claw = document.getElementById("clawNavButton");
    firstNav.insertBefore(launcher, claw || null);

    const dialog = document.createElement("dialog");
    dialog.id = "b66QuoteDialog";
    dialog.className = "b66-quote-dialog";
    dialog.setAttribute("aria-labelledby", "b66QuoteDialogTitle");

    const panel = el("section", "b66-quote-panel");
    const header = el("div", "b66-quote-header");
    const headingWrap = el("div");
    const title = el("h2", "", copy().title);
    title.id = "b66QuoteDialogTitle";
    title.dataset.b66QuoteTitle = "true";
    const description = el("p", "", copy().description);
    description.dataset.b66QuoteDescription = "true";
    headingWrap.append(title, description);
    const close = el("button", "b66-quote-close", "×");
    close.id = "b66QuoteClose";
    close.type = "button";
    close.setAttribute("aria-label", copy().close);
    header.append(headingWrap, close);

    // #4428: opt-in READ-ONLY cross-product PC presence. The server's existing
    // owner/workspace-scoped Broker projection is the only source of ONLINE.
    // No installer URL, pairing challenge, PC action or execution authority.
    const pcSection = el("section", "b66-quote-connect");
    pcSection.hidden = true; // No cross-product exposure until server grant exists.
    const pcToggle = el("button", "b66-quote-connect-toggle", copy().pcToggle);
    pcToggle.id = "b66QuotePcToggle";
    pcToggle.type = "button";
    pcToggle.setAttribute("aria-controls", "b66QuotePcPanel");
    pcToggle.setAttribute("aria-expanded", "false");
    const pcPanel = el("div", "b66-quote-connect-panel");
    pcPanel.id = "b66QuotePcPanel";
    pcPanel.hidden = true;
    const pcHelp = el("p", "b66-quote-connect-help", copy().pcHelp);
    pcHelp.id = "b66QuotePcHelp";
    const pcRefresh = el("button", "b66-quote-connect-refresh", copy().pcRefresh);
    pcRefresh.id = "b66QuotePcRefresh";
    pcRefresh.type = "button";
    const pcStatus = el("p", "b66-quote-connect-status", "");
    pcStatus.id = "b66QuotePcStatus";
    pcStatus.setAttribute("role", "status");
    pcStatus.setAttribute("aria-live", "polite");
    const pcList = el("ul", "b66-quote-connect-list");
    pcList.id = "b66QuotePcList";
    pcPanel.append(pcHelp, pcRefresh, pcStatus, pcList);
    pcSection.append(pcToggle, pcPanel);

    const form = el("form", "b66-quote-form");
    form.id = "b66QuoteForm";
    const selectLabel = el("label", "b66-quote-field");
    const selectText = el("span", "", copy().selectLabel);
    selectText.dataset.b66QuoteSelectLabel = "true";
    const select = document.createElement("select");
    select.id = "b66QuoteSkillSelect";
    selectLabel.append(selectText, select);

    const messageLabel = el("label", "b66-quote-field");
    const messageText = el("span", "", copy().requestLabel);
    messageText.dataset.b66QuoteRequestLabel = "true";
    const message = document.createElement("textarea");
    message.id = "b66QuoteRequest";
    message.rows = 4;
    message.autocomplete = "off";
    message.placeholder = copy().requestPlaceholder;
    messageLabel.append(messageText, message);

    const modelLabel = el("label", "b66-quote-field");
    const modelText = el("span", "", "AI model");
    modelText.dataset.b66QuoteModelLabel = "true";
    const modelSelect = document.createElement("select");
    modelSelect.id = "b66QuoteModelSelect";
    modelSelect.required = true;
    modelLabel.append(modelText, modelSelect);

    // #3906: per-model reasoning level. Options come only from
    // /api/b66/quote/models, so the control never offers a level the selected
    // model does not actually support. The provider default is first.
    const reasoningLabel = el("label", "b66-quote-field");
    const reasoningText = el("span", "", document.documentElement.lang === "en"
      ? "Reasoning level" : "추론 수준");
    reasoningText.dataset.b66QuoteReasoningLabel = "true";
    const reasoningSelect = document.createElement("select");
    reasoningSelect.id = "b66QuoteReasoningSelect";
    reasoningLabel.append(reasoningText, reasoningSelect);

    const submit = el("button", "b66-quote-generate", copy().generate);
    submit.id = "b66QuoteGenerate";
    submit.type = "submit";

    const status = el("p", "b66-quote-status", copy().idle);
    status.id = "b66QuoteStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    const frame = document.createElement("iframe");
    frame.id = "b66QuoteFrame";
    frame.className = "b66-quote-frame";
    frame.hidden = true;
    frame.title = copy().title;
    frame.referrerPolicy = "no-referrer";
    frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-modals");

    form.append(selectLabel, modelLabel, reasoningLabel, messageLabel, submit, status);
    panel.append(header, pcSection, form, frame);
    dialog.append(panel);
    document.body.append(dialog);

    launcher.addEventListener("click", () => {
      syncCopy();
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      launcher.setAttribute("aria-expanded", "true");
      message.focus();
    });
    close.addEventListener("click", () => closeDialog());
    pcToggle.addEventListener("click", () => {
      if (!pcPanel.hidden) {
        resetPcDirectory();
        return;
      }
      pcPanel.hidden = false;
      pcToggle.setAttribute("aria-expanded", "true");
      void loadPcDirectory();
    });
    pcRefresh.addEventListener("click", () => { void loadPcDirectory(); });
    dialog.addEventListener("close", () => {
      launcher.setAttribute("aria-expanded", "false");
      resetPcDirectory();
    });
    dialog.addEventListener("cancel", () => {
      launcher.setAttribute("aria-expanded", "false");
      resetPcDirectory();
    });
    form.addEventListener("submit", generate);
    window.addEventListener("message", receiveEmbedMessage);
  }


  function resetPcDirectory() {
    pcQuerySequence += 1; // discard all in-flight responses after account/visibility changes
    const section = document.getElementById("b66QuotePcPanel");
    const toggle = document.getElementById("b66QuotePcToggle");
    const list = document.getElementById("b66QuotePcList");
    const status = document.getElementById("b66QuotePcStatus");
    if (section) section.hidden = true;
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    if (list) list.replaceChildren();
    if (status) status.textContent = "";
  }

  async function loadPcDirectory() {
    const section = document.getElementById("b66QuotePcPanel");
    const list = document.getElementById("b66QuotePcList");
    const status = document.getElementById("b66QuotePcStatus");
    if (!section || section.hidden || !list || !status) return;
    const current = ++pcQuerySequence;
    const isCurrent = () => current === pcQuerySequence && !section.hidden;
    const c = copy();
    list.replaceChildren();
    status.textContent = c.pcLoading;
    const derive = window.PadiemClawLocalHandoff?.deriveDeviceDirectory;
    if (typeof derive !== "function") {
      status.textContent = c.pcUnavailable;
      return;
    }
    try {
      const response = await nativeFetch(PC_DIRECTORY_PATH, {
        method: "GET", credentials: "same-origin", cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      if (!isCurrent()) return;
      if (response.status === 401 || response.status === 403) {
        status.textContent = c.pcAuth;
        return;
      }
      if (response.status === 404 || response.status === 501 ||
          response.status === 503) {
        status.textContent = c.pcUnavailable;
        return;
      }
      if (!response.ok) {
        status.textContent = c.pcFailed;
        return;
      }
      // Bound raw response and reuse the existing closed, read-only Claw
      // projection, never render raw server HTML/credentials or invent ONLINE.
      const raw = await response.text();
      if (!isCurrent()) return;
      if (raw.length > MAX_PC_DIRECTORY_BYTES) throw new Error("pc_directory_oversize");
      const payload = JSON.parse(raw);
      if (!payload || payload.ok !== true || payload.available !== true ||
          payload.ownerScoped !== true) {
        status.textContent = c.pcUnavailable;
        return;
      }
      const directory = derive(payload, null);
      if (!directory || directory.available !== true) {
        status.textContent = c.pcFailed;
        return;
      }
      status.textContent = directory.devices.length ? c.pcReady : c.pcEmpty;
      for (const device of directory.devices) {
        const item = el("li", "b66-quote-connect-item");
        const name = el("strong", "", device.deviceName || device.deviceId);
        const stateKey = device.revoked ? "pcRevoked" :
          device.online ? "pcOnline" : "pcOffline";
        const state = el("span", "b66-quote-connect-state", c[stateKey]);
        state.dataset.state = device.online ? "online" : "offline";
        item.append(name, state);
        list.append(item);
      }
    } catch (_) {
      if (!isCurrent()) return;
      list.replaceChildren();
      status.textContent = c.pcFailed;
    }
  }

  function closeDialog() {
    const dialog = document.getElementById("b66QuoteDialog");
    const launcher = document.getElementById("b66QuoteNavButton");
    if (!dialog) return;
    resetPcDirectory();
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
    if (launcher) launcher.setAttribute("aria-expanded", "false");
  }

  function syncCopy() {
    const c = copy();
    const map = [
      ["[data-b66-quote-launcher-label]", "launcher"],
      ["[data-b66-quote-title]", "title"],
      ["[data-b66-quote-description]", "description"],
      ["[data-b66-quote-select-label]", "selectLabel"],
      ["[data-b66-quote-request-label]", "requestLabel"]
    ];
    map.forEach(([selector, key]) => {
      const node = document.querySelector(selector);
      if (node) node.textContent = c[key];
    });
    const message = document.getElementById("b66QuoteRequest");
    const submit = document.getElementById("b66QuoteGenerate");
    const close = document.getElementById("b66QuoteClose");
    const frame = document.getElementById("b66QuoteFrame");
    if (message) message.placeholder = c.requestPlaceholder;
    if (submit) submit.textContent = c.generate;
    if (close) close.setAttribute("aria-label", c.close);
    if (frame) frame.title = c.title;
    const pcToggle = document.getElementById("b66QuotePcToggle");
    const pcHelp = document.getElementById("b66QuotePcHelp");
    const pcRefresh = document.getElementById("b66QuotePcRefresh");
    if (pcToggle) pcToggle.textContent = c.pcToggle;
    if (pcHelp) pcHelp.textContent = c.pcHelp;
    if (pcRefresh) pcRefresh.textContent = c.pcRefresh;
  }

  function setStatus(text, state) {
    const node = document.getElementById("b66QuoteStatus");
    if (!node) return;
    node.textContent = text;
    node.dataset.state = state || "";
  }

  async function refreshModels() {
    const select = document.getElementById("b66QuoteModelSelect");
    if (!select) return;
    modelIds = [];
    reasoningByModel = {};
    select.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = document.documentElement.lang === "en"
      ? "Select a model" : "\uBAA8\uB378\uC744 \uC120\uD0DD\uD558\uC138\uC694";
    select.append(placeholder);
    select.disabled = true;
    const response = await readJson("/api/b66/quote/models");
    if (!response.response.ok || !response.data || !Array.isArray(response.data.models)) return;
    const safe = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
    response.data.models.forEach((record) => {
      if (!record || typeof record.model_id !== "string" ||
          !safe.test(record.model_id) || typeof record.name !== "string") return;
      const option = document.createElement("option");
      option.value = record.model_id;
      option.textContent = record.name;
      select.append(option);
      modelIds.push(record.model_id);
      // #3906: keep only the levels this exact model advertises.
      reasoningByModel[record.model_id] = Array.isArray(record.reasoning_levels)
        ? record.reasoning_levels.filter((level) => level &&
            typeof level.value === "string" &&
            /^[a-z0-9-]{1,32}$/.test(level.value) &&
            typeof level.label === "string")
        : [];
    });
    const configured = response.data.default_model_id;
    select.value = typeof configured === "string" && modelIds.includes(configured)
      ? configured : "";
    select.disabled = modelIds.length === 0;
    syncReasoningOptions();
    select.addEventListener("change", syncReasoningOptions);
  }

  // #3906: only levels the selected model actually supports are offered, and a
  // model switch re-validates the current choice so an unsupported level can
  // never be submitted. No recommended level is auto-applied.
  function reasoningOptionsForModel(modelId) {
    if (typeof modelId !== "string" || !modelIds.includes(modelId)) return [];
    const levels = reasoningByModel[modelId];
    if (!Array.isArray(levels) || !levels.length) return [];
    return levels;
  }

  function syncReasoningOptions() {
    const modelSelect = document.getElementById("b66QuoteModelSelect");
    const reasoningSelect = document.getElementById("b66QuoteReasoningSelect");
    if (!modelSelect || !reasoningSelect) return;
    const options = reasoningOptionsForModel(modelSelect.value);
    reasoningSelect.replaceChildren();
    options.forEach((level) => {
      const option = document.createElement("option");
      option.value = level.value;
      option.textContent = level.label;
      reasoningSelect.append(option);
    });
    reasoningSelect.value = options.length ? options[0].value : "";
    reasoningSelect.disabled = options.length === 0;
  }

  // #3906: the reasoning choice actually offered for this exact model, or ""
  // when the control has none so the request keeps its pre-#3906 shape.
  function selectedReasoningLevel(modelId) {
    const reasoningSelect = document.getElementById("b66QuoteReasoningSelect");
    if (!reasoningSelect) return "";
    const options = reasoningOptionsForModel(modelId);
    const current = reasoningSelect.value;
    return options.some((level) => level.value === current) ? current : "";
  }

  function populateSkills() {
    const select = document.getElementById("b66QuoteSkillSelect");
    const launcher = document.getElementById("b66QuoteNavButton");
    const pcSection = document.querySelector(".b66-quote-connect");
    if (!select || !launcher) return;
    select.replaceChildren();
    skills.forEach((skill) => {
      const option = document.createElement("option");
      option.value = skill.saved_skill_id;
      option.textContent = skill.skill_name;
      select.append(option);
    });
    launcher.hidden = !(runtime && skills.length > 0);
    launcher.disabled = launcher.hidden;
    launcher.setAttribute("aria-disabled", launcher.hidden ? "true" : "false");
    const pcEnabled = !launcher.hidden && runtime?.pcDirectoryEnabled === true;
    if (pcSection) pcSection.hidden = !pcEnabled;
    if (!pcEnabled) resetPcDirectory();
    if (launcher.hidden) closeDialog();
  }

  async function readJson(url, options) {
    const response = await nativeFetch(url, Object.assign({
      headers: { "Accept": "application/json" },
      cache: "no-store"
    }, options || {}));
    const data = await response.json().catch(() => null);
    return { response, data };
  }

  function declaredAssetRefs(skill) {
    const template = skill && typeof skill === "object" ? skill.internalTemplate : null;
    const content = template && typeof template === "object" ? template.content : null;
    const slots = content && typeof content === "object" ? content.slots : null;
    const refs = {};
    ["logo", "stamp"].forEach((key) => {
      const value = slots && typeof slots[key] === "string" ? slots[key] : "";
      if (value && !B66_ASSET_ID.test(value)) throw new Error("invalid_private_asset_ref");
      if (value) refs[key] = value;
    });
    return refs;
  }

  function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    const parts = [];
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      const chunk = bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length));
      let binary = "";
      for (let i = 0; i < chunk.length; i += 1) binary += String.fromCharCode(chunk[i]);
      parts.push(binary);
    }
    return window.btoa(parts.join(""));
  }

  async function readPrivateAsset(assetId) {
    if (!B66_ASSET_ID.test(assetId || "")) throw new Error("invalid_private_asset_ref");
    const response = await nativeFetch("/api/b66/assets/" + encodeURIComponent(assetId), {
      method: "GET",
      headers: { "Accept": "image/png,image/jpeg,image/webp" },
      cache: "no-store",
      credentials: "same-origin"
    });
    if (!response.ok) throw new Error("private_asset_unavailable");
    const mediaType = String(response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
    if (!PRIVATE_ASSET_MEDIA.has(mediaType)) throw new Error("private_asset_media_invalid");
    const rawLength = Number(response.headers.get("content-length") || "0");
    if (Number.isFinite(rawLength) && rawLength > MAX_PRIVATE_ASSET_BYTES) {
      throw new Error("private_asset_too_large");
    }
    const buffer = await response.arrayBuffer();
    if (!buffer.byteLength || buffer.byteLength > MAX_PRIVATE_ASSET_BYTES) {
      throw new Error("private_asset_too_large");
    }
    return {
      assetId,
      dataUrl: "data:" + mediaType + ";base64," + arrayBufferToBase64(buffer)
    };
  }

  async function loadPrivateAssets(skill) {
    const refs = declaredAssetRefs(skill);
    const assets = {};
    for (const key of ["logo", "stamp"]) {
      if (refs[key]) assets[key] = await readPrivateAsset(refs[key]);
    }
    return assets;
  }

  async function refresh() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      ensureUi();
      try {
        const configResult = await readJson("/api/b66/runtime-config");
        if (!configResult.response.ok) {
          runtime = null;
          skills = [];
          populateSkills();
          return false;
        }
        runtime = validRuntime(configResult.data);
        if (!runtime) {
          skills = [];
          populateSkills();
          return false;
        }
        const listResult = await readJson("/api/b66/saved-skills?limit=20");
        if (!listResult.response.ok) {
          skills = [];
          populateSkills();
          return false;
        }
        skills = safeSkills(listResult.data);
        populateSkills();
        await refreshModels();
        return skills.length > 0;
      } catch (_) {
        runtime = null;
        skills = [];
        populateSkills();
        return false;
      }
    })().finally(() => { refreshPromise = null; });
    return refreshPromise;
  }

  function requestId() {
    return "b66-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
  }

  function waitForFrame(frame, url) {
    if (frameLoadedUrl === url && frame.contentWindow) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => reject(new Error("embed_timeout")), 10000);
      frame.addEventListener("load", () => {
        window.clearTimeout(timer);
        frameLoadedUrl = url;
        resolve();
      }, { once: true });
      frame.src = url;
    });
  }

  async function generate(event) {
    event.preventDefault();
    const c = copy();
    const select = document.getElementById("b66QuoteSkillSelect");
    const message = document.getElementById("b66QuoteRequest");
    const submit = document.getElementById("b66QuoteGenerate");
    const frame = document.getElementById("b66QuoteFrame");
    if (!runtime || !select || !message || !submit || !frame) return;
    const savedSkillId = select.value;
    const modelSelect = document.getElementById("b66QuoteModelSelect");
    const modelId = modelSelect && modelSelect.value;
    const requestText = message.value.trim();
    if (!/^b66skill_[0-9a-f]{32}$/.test(savedSkillId) || !requestText ||
        !modelId || !modelIds.includes(modelId)) {
      setStatus(c.failed, "error");
      return;
    }

    submit.disabled = true;
    frame.hidden = true;
    setStatus(c.working, "working");
    try {
      // #3906: forward the explicit reasoning choice with the exact model. The
      // field is omitted when the control offers none, preserving the
      // pre-#3906 request shape.
      const payload = { saved_skill_id: savedSkillId, message: requestText, model_id: modelId };
      const reasoningLevel = selectedReasoningLevel(modelId);
      if (reasoningLevel) payload.reasoning_level = reasoningLevel;
      const interpreted = await readJson("/api/b66/quote/interpret", {
        method: "POST",
        headers: { "Accept": "application/json", "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (!interpreted.response.ok || !interpreted.data || interpreted.data.ok !== true) {
        throw new Error("interpret_failed");
      }
      const candidate = interpreted.data.candidate;
      if (!candidate || !Array.isArray(candidate.missing)) throw new Error("candidate_invalid");
      if (candidate.missing.length > 0) {
        setStatus(c.missing, "missing");
        return;
      }

      const detail = await readJson("/api/b66/saved-skills/" + encodeURIComponent(savedSkillId));
      const skill = detail.data && detail.data.saved_skill && detail.data.saved_skill.skill;
      if (!detail.response.ok || !skill || typeof skill !== "object") throw new Error("skill_unavailable");

      const profileResult = companyProfileForRender(interpreted.data.company_profile);
      if (!profileResult.ok) {
        setStatus(
          profileResult.code === "missing_company" ? c.companyIdentityMissing : c.companyDefaultsMissing,
          "missing"
        );
        return;
      }
      const assets = await loadPrivateAssets(skill);

      await waitForFrame(frame, runtime.embedUrl);
      const id = requestId();
      currentRequestId = id;
      frame.contentWindow.postMessage({
        type: "b66.embed.render.v1",
        requestId: id,
        skill,
        candidate,
        assets,
        companyProfile: profileResult.profile
      }, runtime.origin);
    } catch (_) {
      currentRequestId = null;
      setStatus(c.failed, "error");
    } finally {
      submit.disabled = false;
    }
  }

  function receiveEmbedMessage(event) {
    if (!runtime) return;
    const frame = document.getElementById("b66QuoteFrame");
    if (!frame || event.source !== frame.contentWindow || event.origin !== runtime.origin) return;
    const data = event.data;
    if (!data || typeof data !== "object" || data.requestId !== currentRequestId) return;
    if (data.type === "b66.embed.rendered.v1" && data.ok === true) {
      currentRequestId = null;
      frame.hidden = false;
      setStatus(copy().ready, "ready");
      return;
    }
    if (data.type === "b66.embed.error.v1") {
      currentRequestId = null;
      frame.hidden = true;
      setStatus(copy().failed, "error");
    }
  }

  window.addEventListener("padiem:capabilitychange", (event) => {
    const auth = event && event.detail && event.detail.auth;
    if (auth && auth.authenticated === true) refresh();
    else {
      resetPcDirectory();
      runtime = null;
      skills = [];
      ensureUi();
      populateSkills();
    }
  });
  for (const eventName of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
    window.addEventListener(eventName, resetPcDirectory);
  }
  window.addEventListener("padiem:localechange", syncCopy);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      ensureUi();
    }, { once: true });
  } else {
    ensureUi();
  }
})();