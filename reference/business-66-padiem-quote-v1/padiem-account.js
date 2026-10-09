(() => {
  "use strict";

  const API = "/api/padiem";
  const B66_ASSET_ID = /^b66asset_[0-9a-f]{32}$/;
  const PRIVATE_ASSET_MEDIA = new Set(["image/png", "image/jpeg", "image/webp"]);
  const MAX_PRIVATE_ASSET_BYTES = 256 * 1024;
  const state = {
    authenticated: false,
    user: null,
    skills: [],
    quoteModels: [],
    quoteReasoningByModel: {},
    loadedSkill: null,
    companyProfile: null,
    companyProfileLoaded: false,
    pendingQuote: null,
    methods: { google: false, password: false }
  };

  const byId = (id) => document.getElementById(id);

  function safeMessage(data, fallback) {
    const message = data && data.error && data.error.message;
    return typeof message === "string" && message.trim() ? message.trim() : fallback;
  }

  function accountName(user) {
    if (!user || typeof user !== "object") return "내 계정";
    for (const key of ["name", "display_name", "email", "username"]) {
      if (typeof user[key] === "string" && user[key].trim()) return user[key].trim();
    }
    return "내 계정";
  }

  async function api(path, options) {
    const opts = Object.assign({
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    }, options || {});
    opts.headers = Object.assign({ "Accept": "application/json" }, (options && options.headers) || {});
    const response = await window.fetch(API + path, opts);
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
    const chunks = [];
    const chunkSize = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunkSize) {
      const chunk = bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length));
      let binary = "";
      for (let i = 0; i < chunk.length; i += 1) binary += String.fromCharCode(chunk[i]);
      chunks.push(binary);
    }
    return window.btoa(chunks.join(""));
  }

  async function readPrivateAsset(assetId) {
    if (!B66_ASSET_ID.test(assetId || "")) throw new Error("invalid_private_asset_ref");
    const response = await window.fetch(API + "/b66/assets/" + encodeURIComponent(assetId), {
      method: "GET",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Accept": "image/png,image/jpeg,image/webp" }
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
    const sources = {};
    for (const key of ["logo", "stamp"]) {
      if (refs[key]) sources[key] = await readPrivateAsset(refs[key]);
    }
    return sources;
  }

  function setQuoteStatus(message, kind) {
    const node = byId("padiemQuoteStatus");
    if (!node) return;
    node.textContent = message || "";
    node.dataset.state = kind || "";
  }

  function setAuthError(message) {
    const node = byId("padiemAuthError");
    if (node) node.textContent = message || "";
  }

  /* /auth/status 이 실제로 허용한 로그인 메서드만 노출한다. 기본은 숨김/비활성이다. */
  function applyAuthMethods(payload) {
    const methods = payload && typeof payload === "object" ? payload.methods : null;
    state.methods = {
      google: Boolean(methods && methods.google === true),
      password: Boolean(methods && methods.password === true)
    };
    const form = byId("padiemLoginForm");
    const divider = byId("padiemAuthDivider");
    const submit = byId("padiemLoginSubmit");
    if (form) form.hidden = !state.methods.password;
    if (divider) divider.hidden = !state.methods.password;
    if (submit) submit.disabled = !state.methods.password;
    return state.methods.password;
  }

  function passwordLoginAvailable() {
    return state.methods.password === true;
  }

  function clearServerSkill() {
    state.loadedSkill = null;
    const bridge = window.B66QuoteSkillBridge;
    if (bridge && typeof bridge.clearServerSkill === "function") {
      bridge.clearServerSkill();
    }
  }

  function renderSignedOut() {
    state.authenticated = false;
    state.user = null;
    state.skills = [];
    state.quoteModels = [];
    state.quoteReasoningByModel = {};
    const modelSelect = byId("padiemQuoteModelSelect");
    if (modelSelect) modelSelect.replaceChildren();
    const reasoningSelect = byId("padiemQuoteReasoningSelect");
    if (reasoningSelect) {
      reasoningSelect.replaceChildren();
      reasoningSelect.disabled = true;
    }
    state.companyProfile = null;
    state.companyProfileLoaded = false;
    clearPendingQuote();
    clearServerSkill();
    const button = byId("padiemAccountButton");
    const panel = byId("padiemAccountPanel");
    const select = byId("padiemSavedSkillSelect");
    if (button) button.textContent = "로그인";
    if (panel) panel.hidden = true;
    if (select) select.replaceChildren();
    const settingsButton = byId("settingsButton");
    if (settingsButton) settingsButton.hidden = true;
    const settingsPanelOut = byId("settingsPanel");
    if (settingsPanelOut) settingsPanelOut.hidden = true;
    document.dispatchEvent(new CustomEvent("b66:auth-changed", { detail: { authenticated: false } }));
    document.dispatchEvent(new CustomEvent("b66:runtime-changed", { detail: runtimeReadiness() }));
  }

  function renderSignedIn() {
    const button = byId("padiemAccountButton");
    const panel = byId("padiemAccountPanel");
    const label = byId("padiemAccountLabel");
    if (button) button.textContent = accountName(state.user);
    if (label) label.textContent = accountName(state.user) + " · 내 견적서";
    if (panel) panel.hidden = false;
    const settingsButton = byId("settingsButton");
    if (settingsButton) settingsButton.hidden = false;
    document.dispatchEvent(new CustomEvent("b66:auth-changed", { detail: { authenticated: true } }));
  }

  function openAuthDialog() {
    const dialog = byId("padiemAuthDialog");
    setAuthError("");
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    if (!passwordLoginAvailable()) return;
    const identifier = byId("padiemLoginIdentifier");
    if (identifier) identifier.focus();
  }

  function closeAuthDialog() {
    const dialog = byId("padiemAuthDialog");
    if (!dialog) return;
    if (typeof dialog.close === "function" && dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  async function loadSkill(savedSkillId) {
    if (!/^b66skill_[0-9a-f]{32}$/.test(savedSkillId || "")) {
      clearServerSkill();
      setQuoteStatus("내 견적서 선택을 확인해 주세요.", "error");
      return false;
    }
    const result = await api("/b66/saved-skills/" + encodeURIComponent(savedSkillId));
    const row = result.data && result.data.saved_skill;
    const semantic = window.SavedQuoteSkill;
    const rawSkill = row && row.skill;
    const skill = semantic && typeof semantic.normalizeSkill === "function"
      ? semantic.normalizeSkill(rawSkill)
      : null;
    if (
      !result.response.ok ||
      !row ||
      row.saved_skill_id !== savedSkillId ||
      !skill ||
      skill.approved !== true ||
      skill.fingerprint !== row.skill_fingerprint
    ) {
      clearServerSkill();
      setQuoteStatus("배정된 내 견적서를 확인하지 못했습니다.", "error");
      return false;
    }
    let slotSources;
    try {
      slotSources = await loadPrivateAssets(skill);
    } catch (_) {
      clearServerSkill();
      setQuoteStatus("내 견적서의 로고·도장 자산을 불러오지 못했습니다.", "error");
      return false;
    }
    state.loadedSkill = {
      savedSkillId: row.saved_skill_id,
      fingerprint: row.skill_fingerprint,
      skill,
      slotSources
    };
    /* Skill 이 바뀌면 진행 중이던 견적의 문맥은 새 Skill 로 이어질 수 없다. */
    clearPendingQuote();
    const bridge = window.B66QuoteSkillBridge;
    if (!bridge || typeof bridge.setServerSkill !== "function" || !bridge.setServerSkill(skill, slotSources, savedSkillId)) {
      clearServerSkill();
      setQuoteStatus("내 견적서 렌더러를 준비하지 못했습니다.", "error");
      return false;
    }
    setQuoteStatus("배정된 양식을 불러왔습니다. 거래처·품목·수량·단가를 한 문장으로 입력해 주세요.", "ready");
    return true;
  }

  async function loadQuoteModels() {
    const select = byId("padiemQuoteModelSelect");
    if (!select) return;
    state.quoteModels = [];
    select.replaceChildren();
    select.addEventListener("change", syncReasoningOptions);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "\uBAA8\uB378\uC744 \uC120\uD0DD\uD558\uC138\uC694";
    select.append(placeholder);
    select.disabled = true;
    try {
      const result = await api("/b66/quote/models");
      if (!result.response.ok || !result.data || result.data.ok !== true ||
          !Array.isArray(result.data.models)) return;
      const safeId = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$/;
      const records = result.data.models.filter((row) =>
        row && typeof row.model_id === "string" && safeId.test(row.model_id) &&
        typeof row.name === "string"
      );
      records.forEach((row) => {
        const option = document.createElement("option");
        option.value = row.model_id;
        option.textContent = row.name;
        select.append(option);
      });
      state.quoteModels = records.map((row) => row.model_id);
      state.quoteReasoningByModel = {};
      records.forEach((row) => {
        state.quoteReasoningByModel[row.model_id] = Array.isArray(row.reasoning_levels)
          ? row.reasoning_levels.filter((level) => level &&
              typeof level.value === "string" && /^[a-z0-9-]{1,32}$/.test(level.value) &&
              typeof level.label === "string")
          : [];
      });
      const configured = result.data.default_model_id;
      select.value = typeof configured === "string" && state.quoteModels.includes(configured)
        ? configured : "";
      select.disabled = records.length === 0;
      syncReasoningOptions();
    } catch (_) {
      select.disabled = true;
      state.quoteReasoningByModel = {};
      syncReasoningOptions();
    }
  }

  /* #3906: the reasoning control only ever offers the levels the selected model
     actually supports. Switching models re-validates the current choice, so a
     level that the new model does not support can never be submitted. The
     provider default is always first and is the initial choice; no recommended
     level is auto-applied and nothing is persisted per user. */
  function reasoningOptionsForModel(modelId) {
    if (typeof modelId !== "string" || !state.quoteModels.includes(modelId)) return [];
    const levels = state.quoteReasoningByModel[modelId];
    if (!Array.isArray(levels) || !levels.length) return [];
    const fallback = [{ value: "default", label: "\uAE30\uBCF8(\uC81C\uACF5\uC790 \uAE30\uBCF8\uAC12)" }];
    const allowed = /^[a-z0-9-]{1,32}$/;
    const valid = levels.filter((level) => level &&
      typeof level.value === "string" && allowed.test(level.value) &&
      typeof level.label === "string" && level.label.length <= 80);
    if (!valid.length) return fallback;
    return valid.slice().sort((a, b) => (a.value === "default" ? -1 : b.value === "default" ? 1 : 0));
  }

  /* #3906: the reasoning choice actually being offered for this exact model.
     Returns "" when the control has no option for the model, so the request
     keeps the pre-#3906 shape instead of inventing an unsupported level. */
  function selectedReasoningLevel(modelId) {
    const reasoningSelect = byId("padiemQuoteReasoningSelect");
    if (!reasoningSelect) return "";
    const options = reasoningOptionsForModel(modelId);
    if (!options.length) return "";
    const current = reasoningSelect.value;
    return options.some((level) => level.value === current) ? current : "";
  }

  function syncReasoningOptions() {
    const modelSelect = byId("padiemQuoteModelSelect");
    const reasoningSelect = byId("padiemQuoteReasoningSelect");
    if (!modelSelect || !reasoningSelect) return;
    const options = reasoningOptionsForModel(modelSelect.value);
    reasoningSelect.replaceChildren();
    options.forEach((level) => {
      const option = document.createElement("option");
      option.value = level.value;
      option.textContent = level.label;
      reasoningSelect.append(option);
    });
    const defaultFirst = options.some((level) => level.value === "default");
    reasoningSelect.value = defaultFirst ? "default" : (options[0] ? options[0].value : "");
    reasoningSelect.disabled = options.length === 0;
  }

  async function loadSkills() {
    const result = await api("/b66/saved-skills?limit=20");
    if (!result.response.ok || !result.data || !Array.isArray(result.data.skills)) {
      state.skills = [];
      clearServerSkill();
      setQuoteStatus("계정의 내 견적서를 불러오지 못했습니다.", "error");
      return;
    }
    state.skills = result.data.skills.filter((item) => (
      item &&
      /^b66skill_[0-9a-f]{32}$/.test(item.saved_skill_id || "") &&
      typeof item.skill_name === "string"
    ));
    const select = byId("padiemSavedSkillSelect");
    if (!select) return;
    select.replaceChildren();
    if (!state.skills.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "배정된 내 견적서 없음";
      select.append(option);
      select.disabled = true;
      clearServerSkill();
      setQuoteStatus("아직 이 계정에 배정된 내 견적서가 없습니다.", "empty");
      return;
    }
    select.disabled = false;
    state.skills.forEach((row) => {
      const option = document.createElement("option");
      option.value = row.saved_skill_id;
      option.textContent = row.skill_name;
      select.append(option);
    });
    await loadSkill(select.value);
  }

  /* canonical authenticated projection 이 owner authority 다. 브라우저는 owner 를
     선택하거나 제출하지 않는다. raw user id 는 여기서 로그/화면/저장소로 나가지 않고
     storage 경계는 app.js(단일 브라우저 저장소 authority)만 통과한다. */
  function applyOwnerScope(projection) {
    const bridge = window.B66QuoteAppBridge;
    if (bridge && typeof bridge.applyOwnerScope === "function") {
      return bridge.applyOwnerScope(projection);
    }
    /* 저장소 authority 없이는 private 상태를 노출하지 않는다. */
    const detail = { authenticated: false, privateStateReadable: false, action: null };
    document.dispatchEvent(new CustomEvent("b66:account-scope-changed", { detail }));
    return detail;
  }

  async function refreshAuth() {
    let result;
    try {
      result = await api("/auth/status");
    } catch (_) {
      applyAuthMethods(null);
      applyOwnerScope({ authenticated: false, userId: null });
      renderSignedOut();
      return { authenticated: false };
    }
    applyAuthMethods(result.response.ok ? result.data : null);
    if (
      !result.response.ok ||
      !result.data ||
      result.data.authenticated !== true ||
      result.data.session_state !== "signed_in"
    ) {
      applyOwnerScope({ authenticated: false, userId: null });
      renderSignedOut();
      return { authenticated: false };
    }
    /* opaque user.id 만 owner marker source 다. 이름/이메일/사용자명은 쓰지 않는다. */
    const owner = result.data.user && typeof result.data.user === "object" ? result.data.user : null;
    applyOwnerScope({ authenticated: true, userId: owner ? owner.id : null });
    state.authenticated = true;
    state.user = owner;
    renderSignedIn();
    await Promise.all([loadSkills(), loadCompanyProfile(), loadQuoteModels()]);
    document.dispatchEvent(new CustomEvent("b66:runtime-changed", { detail: runtimeReadiness() }));
    return { authenticated: true };
  }

  /* ── CGI primary runtime authority (#3478) ──
     배정된 승인 Saved Quote Skill + 인증된 CompanyProfile 만이 견적 생성 authority 다.
     Guided/Free-form 두 경로 모두 이 함수들을 거치며, 준비되지 않으면 demo fallback 없이
     정직하게 실패한다. CompanyProfile 은 GET bridge 로 로드하며 모델 호출로 얻지 않는다. */

  const COMPANY_PROFILE_KEYS = [
    "company", "representative", "contactPerson", "businessNumber", "address",
    "phone", "email", "defaultValidityDays", "defaultTaxMode"
  ];

  function projectCompanyProfile(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
    if (typeof raw.company !== "string" || !raw.company.trim()) return null;
    const projected = {};
    COMPANY_PROFILE_KEYS.forEach((key) => {
      if (raw[key] !== undefined && raw[key] !== null) projected[key] = raw[key];
    });
    return projected;
  }

  function runtimeReadiness() {
    const authenticated = state.authenticated === true;
    const skillReady = Boolean(state.loadedSkill);
    const profileReady = state.companyProfileLoaded === true;
    return {
      authenticated,
      skillReady,
      profileReady,
      ready: authenticated && skillReady && profileReady
    };
  }

  function notReadyCode(readiness) {
    if (!readiness.authenticated) return "auth_required";
    if (!readiness.skillReady) return "skill_not_ready";
    return "company_profile_not_ready";
  }

  async function loadCompanyProfile() {
    state.companyProfile = null;
    state.companyProfileLoaded = false;
    try {
      const result = await api("/b66/company-profile");
      const data = result.response.ok && result.data && typeof result.data === "object" ? result.data : null;
      const raw = data ? (data.company_profile && typeof data.company_profile === "object" ? data.company_profile : data) : null;
      const projected = projectCompanyProfile(raw);
      if (!projected) {
        setQuoteStatus("회사 정보(CompanyProfile)를 확인하지 못했습니다.", "error");
        return;
      }
      state.companyProfile = projected;
      state.companyProfileLoaded = true;
    } catch (_) {
      setQuoteStatus("회사 정보(CompanyProfile)를 불러오지 못했습니다.", "error");
    }
  }

  function interpretErrorText(code) {
    switch (code) {
      case "auth_required": return "로그인 후 다시 시도해 주세요.";
      case "skill_not_ready": return "배정된 내 견적서를 확인하지 못했습니다.";
      case "company_profile_not_ready": return "회사 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
      case "incomplete_request": return "거래처와 품목·수량·단가를 조금 더 알려 주세요.";
      case "needs_clarification": return "입력 내용을 정확하게 이해하지 못했습니다. 거래처명·품목명·수량·단가를 확인해 다시 알려 주세요.";
      case "empty_request": return "견적 내용을 입력해 주세요.";
      case "model_selection_required": return "좌측 견적서 관리에서 사용할 AI 모델을 먼저 선택해 주세요.";
      case "cgi_unsupported_rows": return "CGI 기본 견적서는 품목을 최대 3개까지 지원합니다. 품목을 3개 이하로 줄여 주세요.";
      case "cgi_unsupported_details": return "CGI 기본 견적서는 현재 요약 품목만 PDF로 만들 수 있습니다. 상세내역은 지원하지 않으므로 요약 품목의 수량과 단가를 알려 주세요.";
      case "cgi_scope_unavailable": return "CGI 견적서의 지원 범위를 확인하지 못했습니다. 새로고침 후 다시 시도해 주세요.";
      case "interpret_unavailable": return "해석 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.";
      default: return "견적 요청을 해석하지 못했습니다.";
    }
  }

  /* quoteNo/issueDate 결정 순서: 이번 응답의 명시값 > 이번 견적의 이미 발급된 값 > 새 발급.
     이미 발급된 값이 없으면 새 견적으로 보고 정확히 한 번만 발급한다. */
  function structuredInputFromCandidate(candidate, profile, allocated) {
    const app = window.B66QuoteAppBridge;
    const semantic = window.SavedQuoteSkill;
    if (!app || !semantic || !candidate || typeof candidate !== "object") return null;
    const pending = allocated || {};
    const quoteNo = typeof candidate.quoteNo === "string" && candidate.quoteNo.trim()
      ? candidate.quoteNo.trim()
      : (typeof pending.quoteNo === "string" && pending.quoteNo.trim()
        ? pending.quoteNo.trim()
        : app.createFreshDraft("free-form").meta.quoteNo);
    const input = {
      recipient: candidate.recipient,
      items: candidate.items,
      quoteNo,
      issueDate: typeof candidate.issueDate === "string" && candidate.issueDate.trim()
        ? candidate.issueDate.trim()
        : (typeof pending.issueDate === "string" && pending.issueDate.trim()
          ? pending.issueDate.trim()
          : window.QuoteCore.isoFormat(new Date()))
    };
    if (typeof candidate.projectName === "string" && candidate.projectName.trim()) {
      input.projectName = candidate.projectName.trim();
    }
    if (Array.isArray(candidate.detailGroups) && candidate.detailGroups.length) {
      input.detailGroups = candidate.detailGroups;
    }
    if (typeof candidate.memo === "string") input.memo = candidate.memo;
    if (typeof candidate.taxMode === "string" && candidate.taxMode) input.taxMode = candidate.taxMode;
    const built = semantic.buildDraft(state.loadedSkill.skill, input, { companyProfile: profile });
    return built && built.ok === true && built.draft ? { ok: true, draft: built.draft } : { ok: false, code: built && built.code ? built.code : "draft_build_failed" };
  }

  /* ── bounded missing-field follow-up (#3391) ──
     불완전한 첫 요청은 사실만 보관하고 견적번호를 정확히 한 번 발급한다.
     후속 답변은 원문과 합쳐 같은 stateless interpret route 로 다시 보내며,
     최종 견적이 확정될 때까지 같은 번호/발행일을 유지한다. 저장소는 브라우저 메모리 1개뿐이다. */

  const MAX_PENDING_TURNS = 4;
  const MAX_PENDING_TEXT = 4000;
  const MISSING_QUESTIONS = {
    name: "품목명을 알려 주세요.",
    qty: "수량은 몇 개인가요?",
    unitPrice: "단가는 얼마인가요?",
    recipient: "받는 업체 또는 담당자를 알려 주세요.",
    items: "품목명, 수량, 단가를 알려 주세요."
  };

  function clearPendingQuote() {
    state.pendingQuote = null;
  }

  function pendingQuote() {
    return state.pendingQuote ? {
      turns: state.pendingQuote.turns,
      quoteNo: state.pendingQuote.quoteNo,
      issueDate: state.pendingQuote.issueDate,
      missing: state.pendingQuote.missing.slice(0, 8)
    } : null;
  }

  function supportedItemRows() {
    const pdf = window.B66BrowserPdf;
    const loaded = state.loadedSkill;
    if (!pdf || typeof pdf.isCgiSkill !== "function" || !loaded || !pdf.isCgiSkill(loaded.savedSkillId)) return null;
    return Number.isInteger(pdf.MAX_ITEM_ROWS) && pdf.MAX_ITEM_ROWS > 0 ? pdf.MAX_ITEM_ROWS : 0;
  }

  function candidateScopeFailure(candidate) {
    const limit = supportedItemRows();
    if (limit === null) return null;
    if (limit === 0) return { ok: false, code: "cgi_scope_unavailable" };
    if (Array.isArray(candidate.items) && candidate.items.length > limit) {
      return { ok: false, code: "cgi_unsupported_rows" };
    }
    if (Array.isArray(candidate.detailGroups) && candidate.detailGroups.length) {
      return { ok: false, code: "cgi_unsupported_details" };
    }
    return null;
  }

  function absentFact(value) {
    return value === undefined || value === null || (typeof value === "string" && !value.trim());
  }

  function requiredMissingTargets(candidate) {
    const schema = state.loadedSkill.skill.variableSchema;
    const targets = [];
    const recipient = candidate.recipient || {};
    if (schema.recipient === true && absentFact(recipient.company) && absentFact(recipient.person)) {
      targets.push({ field: "recipient" });
    }
    if (schema.items !== true) return targets;
    const items = Array.isArray(candidate.items) ? candidate.items : [];
    if (!items.length) targets.push({ field: "items" });
    const groups = Array.isArray(candidate.detailGroups) ? candidate.detailGroups : [];
    items.forEach((item, itemIndex) => {
      ["name", "qty", "unitPrice"].forEach((field) => {
        const linked = field === "unitPrice" && groups.some((group) => group.summaryItemId === "item-" + (itemIndex + 1));
        if (!linked && absentFact((item || {})[field])) targets.push({ field, itemIndex });
      });
    });
    groups.forEach((group, groupIndex) => {
      (Array.isArray(group.items) ? group.items : []).forEach((item, detailIndex) => {
        ["name", "qty", "unitPrice"].forEach((field) => {
          if (absentFact((item || {})[field])) targets.push({ field, groupIndex, detailIndex });
        });
      });
    });
    return targets;
  }

  function missingQuestion(missing, candidate) {
    const targets = candidate ? requiredMissingTargets(candidate) : [];
    const target = targets[0];
    if (target && target.field === "qty" && state.pendingQuote) {
      // #3916: never accept an estimate as a final numeric quantity.
      // Server also removes unconfirmed qty from the normalized candidate.
      const original = state.pendingQuote.originalText.split("\n추가 질문:", 1)[0];
      const unit = "(?:미터|박스|세트|묶음|kg|KG|mm|cm|m2|EA|ea|개|대|장|톤|식|본|롤|통|병|쌍|건|벌|포|m|M|㎡)";
      const rough = new RegExp("(?:약|대략|대충|한)\\s*\\d[\\d,.]*\\s*" + unit + "|\\d[\\d,.]*\\s*(?:~|～|∼|-)\\s*\\d[\\d,.]*\\s*" + unit + "|\\d[\\d,.]*\\s*" + unit + "\\s*(?:정도|쯤|내외|가량|안팎)");
      if (rough.test(original)) {
        return "대략적으로 말씀하신 수량을 확인해야 합니다. 최종 수량을 정확한 숫자와 단위로 다시 알려 주세요.";
      }
    }
    if (target && target.groupIndex !== undefined) {
      return (target.groupIndex + 1) + "번째 상세그룹의 " + (target.detailIndex + 1) + "번째 품목: " + MISSING_QUESTIONS[target.field];
    }
    if (target && target.itemIndex !== undefined && candidate.items.length > 1) {
      const item = candidate.items[target.itemIndex];
      const name = typeof item.name === "string" && item.name.trim() ? "(" + item.name + ")" : "";
      return (target.itemIndex + 1) + "번째 품목" + name + ": " + MISSING_QUESTIONS[target.field];
    }
    const list = Array.isArray(missing) ? missing : [];
    for (const key of list) {
      if (MISSING_QUESTIONS[key]) return MISSING_QUESTIONS[key];
    }
    return "견적에 필요한 값을 조금 더 알려 주세요.";
  }

  function combinePendingText(pending, followUp) {
    const question = missingQuestion(pending.missing, pending.lastCandidate);
    const combined = pending.originalText + "\n추가 질문: " + question + "\n답변: " + followUp;
    return combined.length <= MAX_PENDING_TEXT ? combined : null;
  }

  function preserveKnownFacts(previous, current) {
    const merged = Object.assign({}, current || {});
    Object.keys(previous || {}).forEach((key) => {
      if (!absentFact(previous[key])) merged[key] = previous[key];
    });
    return merged;
  }

  function mergePendingCandidate(previous, current) {
    const merged = preserveKnownFacts(previous, current);
    merged.recipient = preserveKnownFacts(previous.recipient, current.recipient);
    const priorItems = Array.isArray(previous.items) ? previous.items : [];
    const nextItems = Array.isArray(current.items) ? current.items : [];
    const target = requiredMissingTargets(previous)[0];
    merged.items = priorItems.map((item) => Object.assign({}, item));
    nextItems.forEach((item, index) => {
      const matches = priorItems.map((prior, i) => !absentFact(item.name) && prior.name === item.name ? i : -1).filter((i) => i >= 0);
      let priorIndex = matches.length === 1 ? matches[0] : -1;
      if (priorIndex < 0 && nextItems.length === priorItems.length) priorIndex = index;
      if (priorIndex < 0 && nextItems.length === 1 && target && target.itemIndex !== undefined &&
          (absentFact(item.name) || absentFact(priorItems[target.itemIndex].name) || item.name === priorItems[target.itemIndex].name)) priorIndex = target.itemIndex;
      if (priorIndex >= 0) merged.items[priorIndex] = preserveKnownFacts(priorItems[priorIndex], item);
      else merged.items.push(Object.assign({}, item));
    });
    const priorGroups = Array.isArray(previous.detailGroups) ? previous.detailGroups : [];
    const nextGroups = Array.isArray(current.detailGroups) ? current.detailGroups : [];
    merged.detailGroups = priorGroups.map((group) => Object.assign({}, group, {
      items: group.items.map((item) => Object.assign({}, item))
    }));
    nextGroups.forEach((group) => {
      const groupIndex = priorGroups.findIndex((prior) => prior.summaryItemId === group.summaryItemId);
      if (groupIndex < 0) { merged.detailGroups.push(group); return; }
      const prior = priorGroups[groupIndex];
      const children = prior.items.map((item) => Object.assign({}, item));
      group.items.forEach((item, index) => {
        const matches = prior.items.map((old, i) => !absentFact(item.name) && old.name === item.name ? i : -1).filter((i) => i >= 0);
        let priorIndex = matches.length === 1 ? matches[0] : -1;
        if (priorIndex < 0 && group.items.length === prior.items.length) priorIndex = index;
        if (priorIndex < 0 && group.items.length === 1 && target && target.groupIndex === groupIndex) priorIndex = target.detailIndex;
        if (priorIndex >= 0) children[priorIndex] = preserveKnownFacts(prior.items[priorIndex], item);
        else children.push(item);
      });
      merged.detailGroups[groupIndex] = Object.assign(preserveKnownFacts(prior, group), { items: children });
    });
    return merged;
  }

  function startPendingQuote(text, candidate) {
    const app = window.B66QuoteAppBridge;
    const fresh = app ? app.createFreshDraft("free-form") : null;
    if (!fresh) return null;
    state.pendingQuote = {
      originalText: text,
      turns: 1,
      quoteNo: fresh.meta.quoteNo,
      issueDate: fresh.meta.issueDate,
      lastCandidate: candidate,
      missing: candidate.missing.slice(0, 8)
    };
    return state.pendingQuote;
  }

  function updatePendingQuote(text, candidate) {
    const pending = state.pendingQuote;
    if (!pending) return startPendingQuote(text, candidate);
    pending.originalText = text;
    pending.turns += 1;
    pending.lastCandidate = candidate;
    pending.missing = candidate.missing.slice(0, 8);
    return pending;
  }

  async function interpretRequest(requestText) {
    const text = typeof requestText === "string" ? requestText.trim().slice(0, MAX_PENDING_TEXT) : "";
    if (!text) return { ok: false, code: "empty_request" };
    const readiness = runtimeReadiness();
    if (!readiness.ready) {
      clearPendingQuote();
      return { ok: false, code: notReadyCode(readiness) };
    }

    /* 진행 중인 견적이 있으면 원문과 합쳐 한 번에 다시 해석한다(서버는 stateless). */
    const modelSelect = byId("padiemQuoteModelSelect");
    const modelId = modelSelect && modelSelect.value;
    if (!modelId || !state.quoteModels.includes(modelId)) {
      return { ok: false, code: "model_selection_required" };
    }
    let message = text;
    let allocated = null;
    const pending = state.pendingQuote;
    if (pending) {
      if (pending.turns >= MAX_PENDING_TURNS) {
        clearPendingQuote();
      } else {
        const combined = combinePendingText(pending, text);
        if (combined) {
          message = combined;
          allocated = pending;
        } else {
          clearPendingQuote();
        }
      }
    }

    /* #3906: forward the user's explicit reasoning choice alongside the exact
       model. Omission keeps the pre-#3906 byte layout; the field is only sent
       when the control actually offers a level for THIS model. */
    const payload = {
      saved_skill_id: state.loadedSkill.savedSkillId,
      message,
      model_id: modelId
    };
    const reasoningLevel = selectedReasoningLevel(modelId);
    if (reasoningLevel) payload.reasoning_level = reasoningLevel;

    try {
      const result = await api("/b66/quote/interpret", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = result.data;
      if (!result.response.ok || !data || data.ok !== true || !data.candidate) {
        // A 422 describes rejected MODEL output, not a customer typo.
        // No trusted candidate exists: ask the customer to restate the full
        // request instead of exposing schema errors or inventing prices.
        if (result.response.status === 422 && data && data.error &&
            data.error.code === "quote_input_unrecognized") {
          // If this is an answer to a specific question, preserve already
          // verified facts and ask for that answer again, at most four turns.
          if (state.pendingQuote && state.pendingQuote.turns < MAX_PENDING_TURNS) {
            state.pendingQuote.turns += 1;
            return {
              ok: false,
              code: "incomplete_request",
              question: "방금 답변을 정확히 이해하지 못했습니다. " +
                missingQuestion(state.pendingQuote.missing, state.pendingQuote.lastCandidate),
              pending: pendingQuote()
            };
          }
          clearPendingQuote();
          return {
            ok: false,
            code: "needs_clarification",
            question: "표현이 불분명한 부분이 있습니다. 거래처명, 품목명, 수량과 단가를 확인해 견적 내용을 다시 알려 주세요."
          };
        }
        return { ok: false, code: "interpret_failed", detail: safeMessage(data, "") };
      }
      const candidate = allocated ? mergePendingCandidate(allocated.lastCandidate, data.candidate) : data.candidate;
      const scopeFailure = candidateScopeFailure(candidate);
      if (scopeFailure) { clearPendingQuote(); return scopeFailure; }
      const missing = requiredMissingTargets(candidate).map((target) => target.field);
      candidate.missing = missing.filter((field, index) => missing.indexOf(field) === index);
      if (candidate.missing.length) {
        /* 알려진 값은 보관하고, 없는 값 하나만 구체적으로 되묻는다. */
        const pendingQuoteState = updatePendingQuote(message, candidate);
        return {
          ok: false,
          code: "incomplete_request",
          missing: candidate.missing.slice(0, 8),
          question: missingQuestion(candidate.missing, candidate),
          pending: pendingQuoteState ? pendingQuote() : null
        };
      }
      /* 서버가 이 요청에 대한 CompanyProfile 을 함께 내려주면 그것이 최신 authority 다. */
      const profile = projectCompanyProfile(data.company_profile) || state.companyProfile;
      if (!profile) return { ok: false, code: "company_profile_not_ready" };
      const built = structuredInputFromCandidate(candidate, profile, allocated);
      clearPendingQuote();
      return built;
    } catch (_) {
      return { ok: false, code: "interpret_unavailable" };
    }
  }

  async function buildQuoteFromFacts(facts) {
    const readiness = runtimeReadiness();
    if (!readiness.ready) return { ok: false, code: notReadyCode(readiness) };
    if (!facts || typeof facts !== "object") return { ok: false, code: "invalid_structured_input" };
    const scopeFailure = candidateScopeFailure(facts);
    if (scopeFailure) return scopeFailure;
    const input = {
      recipient: facts.recipient,
      items: facts.items,
      quoteNo: typeof facts.quoteNo === "string" && facts.quoteNo.trim()
        ? facts.quoteNo.trim()
        : window.B66QuoteAppBridge.createFreshDraft("guided").meta.quoteNo,
      issueDate: typeof facts.issueDate === "string" && facts.issueDate.trim()
        ? facts.issueDate.trim()
        : window.QuoteCore.isoFormat(new Date())
    };
    if (typeof facts.taxMode === "string" && facts.taxMode) input.taxMode = facts.taxMode;
    if (typeof facts.memo === "string") input.memo = facts.memo;
    const built = window.SavedQuoteSkill.buildDraft(
      state.loadedSkill.skill, input, { companyProfile: state.companyProfile }
    );
    if (!built || built.ok !== true || !built.draft) {
      return { ok: false, code: built && built.code ? built.code : "draft_build_failed" };
    }
    return { ok: true, draft: built.draft };
  }

  function pdfFailure(code, message) {
    return { ok: false, code, message: message || "PDF 다운로드에 실패했습니다. 잠시 후 다시 시도해 주세요." };
  }

  function pdfFilename(disposition, quoteNo) {
    let filename = "";
    const extended = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(disposition || "");
    if (extended) {
      try { filename = decodeURIComponent(extended[1].trim().replace(/^"|"$/g, "")); } catch (_) {}
    }
    if (!filename) {
      const plain = /filename\s*=\s*(?:"([^"]*)"|([^;]*))/i.exec(disposition || "");
      if (plain) filename = (plain[1] || plain[2] || "").trim();
    }
    filename = filename || String(quoteNo || "quote") + ".pdf";
    filename = filename.replace(/[\/\\\u0000-\u001f\u007f:*?"<>|]/g, "_")
      .replace(/^[.\s]+|[.\s]+$/g, "").slice(0, 120);
    if (!filename) filename = "quote.pdf";
    if (!/\.pdf$/i.test(filename)) filename += ".pdf";
    return filename;
  }

  function certifiedPreviewBaseUrl(savedSkillId) {
    const id = String(savedSkillId || "");
    if (!/^b66skill_[0-9a-f]{32}$/.test(id)) return "";
    return API + "/b66/quote/preview-base?saved_skill_id=" + encodeURIComponent(id);
  }

  async function downloadPdf(renderModel, previewModel) {
    const readiness = runtimeReadiness();
    if (!readiness.ready) return pdfFailure(notReadyCode(readiness), interpretErrorText(notReadyCode(readiness)));
    if (state.pendingQuote) return pdfFailure("pending_quote", "진행 중인 견적 내용을 완성한 뒤 PDF로 저장해 주세요.");
    const loaded = state.loadedSkill;
    const selected = byId("padiemSavedSkillSelect");
    const template = loaded && loaded.skill && loaded.skill.internalTemplate;
    if (!loaded || !/^b66skill_[0-9a-f]{32}$/.test(loaded.savedSkillId || "") ||
        !selected || selected.value !== loaded.savedSkillId || !loaded.fingerprint ||
        loaded.skill.fingerprint !== loaded.fingerprint || loaded.skill.approved !== true ||
        !template || !template.fingerprint || !renderModel || typeof renderModel !== "object" ||
        !renderModel.template || renderModel.template.approved !== true ||
        renderModel.template.fingerprint !== template.fingerprint) {
      return pdfFailure("pdf_skill_mismatch", "배정된 내 견적서의 PDF 양식을 다시 확인해 주세요.");
    }
    const allowedKeys = ["schemaVersion", "derivedBy", "template", "facts", "items", "totals", "coreTotals", "writtenWords", "taxReview"];
    if (Object.keys(renderModel).some((key) => allowedKeys.indexOf(key) === -1) ||
        renderModel.schemaVersion !== 1 || renderModel.derivedBy !== "quote-core" ||
        !renderModel.coreTotals || typeof renderModel.writtenWords !== "string" || !renderModel.writtenWords ||
        !renderModel.taxReview || renderModel.taxReview.required !== false ||
        (Array.isArray(renderModel.coreTotals.detailGroups) && renderModel.coreTotals.detailGroups.length)) {
      return pdfFailure("invalid_pdf_model", "PDF로 저장할 수 있는 확정된 견적 내용을 확인해 주세요.");
    }
    const body = JSON.stringify({ saved_skill_id: loaded.savedSkillId, render_model: renderModel });
    if (new window.Blob([body]).size > 32 * 1024) {
      return pdfFailure("pdf_request_too_large", "견적 내용이 PDF 양식의 지원 범위를 초과했습니다.");
    }
    // Certified CGI only: browser-local PDF first, never silently reroute to the
    // Cloudflare Worker or Modal when the private base/projection fails.
    const browserPdf = window.B66BrowserPdf;
    if (browserPdf && browserPdf.isCgiSkill(loaded.savedSkillId)) {
      try {
        const bytes = await browserPdf.makePdf(renderModel, previewModel);
        if (!state.authenticated || state.loadedSkill !== loaded || selected.value !== loaded.savedSkillId ||
            state.pendingQuote || loaded.fingerprint !== loaded.skill.fingerprint) {
          return pdfFailure("pdf_skill_changed");
        }
        if (!(bytes instanceof Uint8Array) || bytes.length < 5 || bytes[0] !== 37 ||
            bytes[1] !== 80 || bytes[2] !== 68 || bytes[3] !== 70 || bytes[4] !== 45) {
          return pdfFailure("pdf_bytes_invalid");
        }
        const filename = pdfFilename(null, renderModel.facts && renderModel.facts.meta &&
          renderModel.facts.meta.quoteNo);
        const blobUrl = window.URL.createObjectURL(new window.Blob([bytes], { type: "application/pdf" }));
        const anchor = document.createElement("a");
        try {
          anchor.href = blobUrl;
          anchor.download = filename;
          anchor.hidden = true;
          document.body.appendChild(anchor);
          anchor.click();
        } finally {
          anchor.remove();
          window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 1000);
        }
        return { ok: true, filename };
      } catch (_) {
        return pdfFailure("browser_pdf_unavailable", "CGI 브라우저 PDF를 만들지 못했습니다. 다시 확인해 주세요.");
      }
    }
    if (!browserPdf && loaded.savedSkillId === "b66skill_2eb55d822407f626b7a75c8c88d32c40") {
      return pdfFailure("browser_pdf_unavailable");
    }
    try {
      const response = await window.fetch(API + "/b66/quote/pdf", {
        method: "POST", cache: "no-store", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "Accept": "application/pdf,application/json" },
        body
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        return pdfFailure("pdf_render_failed", safeMessage(data, "배정된 양식의 PDF 다운로드가 아직 준비되지 않았습니다."));
      }
      const mediaType = String(response.headers.get("content-type") || "").split(";", 1)[0].trim().toLowerCase();
      if (mediaType !== "application/pdf") return pdfFailure("pdf_media_invalid");
      const buffer = await response.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      if (bytes.length < 5 || bytes[0] !== 37 || bytes[1] !== 80 || bytes[2] !== 68 || bytes[3] !== 70 || bytes[4] !== 45) {
        return pdfFailure("pdf_bytes_invalid");
      }
      if (!state.authenticated || state.loadedSkill !== loaded || selected.value !== loaded.savedSkillId || state.pendingQuote) {
        return pdfFailure("pdf_skill_changed", "내 견적서 선택과 현재 견적 내용을 확인한 뒤 다시 저장해 주세요.");
      }
      const filename = pdfFilename(response.headers.get("content-disposition"), renderModel.facts && renderModel.facts.meta && renderModel.facts.meta.quoteNo);
      const blobUrl = window.URL.createObjectURL(new window.Blob([buffer], { type: "application/pdf" }));
      const anchor = document.createElement("a");
      try {
        anchor.href = blobUrl;
        anchor.download = filename;
        anchor.hidden = true;
        document.body.appendChild(anchor);
        anchor.click();
      } finally {
        anchor.remove();
        window.setTimeout(() => window.URL.revokeObjectURL(blobUrl), 0);
      }
      return { ok: true, filename };
    } catch (_) {
      return pdfFailure("pdf_unavailable");
    }
  }

  window.B66QuoteRuntimeBridge = Object.freeze({
    readiness: runtimeReadiness,
    interpret: interpretRequest,
    buildFromFacts: buildQuoteFromFacts,
    downloadPdf,
    certifiedPreviewBaseUrl,
    pendingQuote: () => pendingQuote(),
    supportedItemRows: () => supportedItemRows(),
    clearPending: () => { clearPendingQuote(); },
    getCompanyProfile: () => (state.companyProfile ? JSON.parse(JSON.stringify(state.companyProfile)) : null),
    errorText: interpretErrorText
  });

  async function startGoogleSignIn() {
    const button = byId("googleSigninButton");
    if (button) button.disabled = true;
    setAuthError("");
    try {
      const result = await api("/auth/status");
      const methods = result.data && result.data.methods;
      if (result.response.ok && methods && methods.google === true) {
        window.location.assign("/api/padiem/auth/google/start");
        return;
      }
      setAuthError("구글 로그인이 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.");
    } catch (_) {
      setAuthError("로그인 연결을 확인해 주세요.");
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function passwordSignIn(event) {
    event.preventDefault();
    /* canonical /api/padiem/auth/status 의 methods.password === true 인 경우에만 로그인 요청을 보낸다. */
    if (!passwordLoginAvailable()) {
      applyAuthMethods(null);
      setAuthError("아이디/이메일 로그인은 현재 제공되지 않습니다. 구글 로그인을 이용해 주세요.");
      return;
    }
    const identifier = byId("padiemLoginIdentifier");
    const password = byId("padiemLoginPassword");
    const submit = byId("padiemLoginSubmit");
    if (!identifier || !password || !submit) return;

    const identifierValue = identifier.value.trim();
    if (!identifierValue || !password.value) {
      setAuthError("아이디 또는 이메일과 비밀번호를 입력해 주세요.");
      (identifierValue ? password : identifier).focus();
      return;
    }

    submit.disabled = true;
    setAuthError("");
    try {
      const result = await api("/auth/password/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ identifier: identifierValue, password: password.value })
      });
      if (!result.response.ok) {
        setAuthError(safeMessage(result.data, "로그인 정보를 확인해 주세요."));
        return;
      }
      password.value = "";
      await refreshAuth();
      if (!state.authenticated) {
        setAuthError("로그인 상태를 확인하지 못했습니다. 다시 시도해 주세요.");
        return;
      }
      closeAuthDialog();
    } catch (_) {
      setAuthError("로그인 연결을 확인해 주세요.");
    } finally {
      /* 메서드가 꺼진 상태에서는 제출 버튼도 비활성 상태로 되돌린다. */
      submit.disabled = !passwordLoginAvailable();
    }
  }

  /* canonical 인증 상태의 확정 여부를 함께 돌려준다. 판정 불가면 ok=false 이고
     "signed-out 이다" 라고 말하지 않는다. */
  async function canonicalAuthState() {
    try {
      const result = await api("/auth/status");
      if (!result.response.ok || !result.data || typeof result.data !== "object") {
        return { ok: false, authenticated: null };
      }
      return {
        ok: true,
        authenticated: result.data.authenticated === true && result.data.session_state === "signed_in"
      };
    } catch (_) {
      return { ok: false, authenticated: null };
    }
  }

  const LOGOUT_UNCONFIRMED_TEXT = "로그아웃을 확인하지 못했습니다. 로그인 상태를 다시 확인해 주세요.";

  async function logout() {
    /* private 인용은 요청 즉시 숨기고, canonical logout 성공 여부는 /auth/status 재확인으로만
       결정한다. POST 결과나 로컬 projection 을 성공 근거로 쓰지 않는다. */
    applyOwnerScope({ authenticated: false, userId: null });
    let posted = false;
    try {
      await api("/auth/logout", { method: "POST" });
      posted = true;
    } catch (_) {
      posted = false;
    }

    const recheck = await canonicalAuthState();
    if (recheck.ok && recheck.authenticated === false) {
      renderSignedOut();
      setQuoteStatus("로그아웃되었습니다.", "ready");
      return { ok: true, signedOut: true, posted: posted };
    }

    /* 확인 실패: canonical 세션이 남아 있을 수 있으므로 정직한 error path 를 유지한다. */
    setAuthError(LOGOUT_UNCONFIRMED_TEXT);
    const app = window.B66QuoteAppBridge;
    if (app && typeof app.toast === "function") app.toast(LOGOUT_UNCONFIRMED_TEXT, 4000);
    await refreshAuth();
    /* 갱신된 canonical projection 위에서 다시 알린다. */
    setQuoteStatus(LOGOUT_UNCONFIRMED_TEXT, "error");
    return { ok: false, signedOut: state.authenticated !== true, posted: posted };
  }

  async function changeSkill() {
    const select = byId("padiemSavedSkillSelect");
    if (!select) return;
    await loadSkill(select.value);
  }

  function bind() {
    const accountButton = byId("padiemAccountButton");
    const close = byId("padiemAuthClose");
    const googleButton = byId("googleSigninButton");
    const loginForm = byId("padiemLoginForm");
    const logoutButton = byId("padiemLogout");
    const select = byId("padiemSavedSkillSelect");

    if (accountButton) accountButton.addEventListener("click", () => {
      if (state.authenticated) {
        // The legacy account panel is not a visible destination in the 3-pane UI.
        // Open the existing account/settings controls instead of scrolling to it.
        const settings = byId("settingsButton");
        if (settings) settings.click();
      } else {
        openAuthDialog();
      }
    });
    if (close) close.addEventListener("click", closeAuthDialog);
    if (googleButton) googleButton.addEventListener("click", startGoogleSignIn);
    if (loginForm) loginForm.addEventListener("submit", passwordSignIn);
    if (logoutButton) logoutButton.addEventListener("click", logout);
    if (select) select.addEventListener("change", changeSkill);
    refreshAuth();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind, { once: true });
  } else {
    bind();
  }
})();
