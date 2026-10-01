(() => {
  "use strict";

  const API = "/api/padiem";
  const state = {
    authenticated: false,
    user: null,
    skills: [],
    loadedSkill: null
  };

  const byId = (id) => document.getElementById(id);

  function safeMessage(data, fallback) {
    const message = data && data.error && data.error.message;
    return typeof message === "string" && message.trim() ? message.trim() : fallback;
  }

  function accountName(user) {
    if (!user || typeof user !== "object") return "Padiem 계정";
    for (const key of ["name", "display_name", "email", "username"]) {
      if (typeof user[key] === "string" && user[key].trim()) return user[key].trim();
    }
    return "Padiem 계정";
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
    clearServerSkill();
    const button = byId("padiemAccountButton");
    const panel = byId("padiemAccountPanel");
    const select = byId("padiemSavedSkillSelect");
    if (button) button.textContent = "로그인";
    if (panel) panel.hidden = true;
    if (select) select.replaceChildren();
  }

  function renderSignedIn() {
    const button = byId("padiemAccountButton");
    const panel = byId("padiemAccountPanel");
    const label = byId("padiemAccountLabel");
    if (button) button.textContent = accountName(state.user);
    if (label) label.textContent = accountName(state.user) + " · 내 견적서";
    if (panel) panel.hidden = false;
  }

  function openAuthDialog() {
    const dialog = byId("padiemAuthDialog");
    setAuthError("");
    if (!dialog) return;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
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
      !skill ||
      skill.approved !== true ||
      skill.fingerprint !== row.skill_fingerprint
    ) {
      clearServerSkill();
      setQuoteStatus("배정된 내 견적서를 확인하지 못했습니다.", "error");
      return false;
    }
    state.loadedSkill = {
      savedSkillId: row.saved_skill_id,
      fingerprint: row.skill_fingerprint,
      skill
    };
    const bridge = window.B66QuoteSkillBridge;
    if (!bridge || typeof bridge.setServerSkill !== "function" || !bridge.setServerSkill(skill)) {
      clearServerSkill();
      setQuoteStatus("내 견적서 렌더러를 준비하지 못했습니다.", "error");
      return false;
    }
    setQuoteStatus("배정된 양식을 불러왔습니다. 거래처·품목·수량·단가를 한 문장으로 입력해 주세요.", "ready");
    return true;
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

  async function refreshAuth() {
    let result;
    try {
      result = await api("/auth/status");
    } catch (_) {
      renderSignedOut();
      return;
    }
    if (
      !result.response.ok ||
      !result.data ||
      result.data.authenticated !== true ||
      result.data.session_state !== "signed_in"
    ) {
      renderSignedOut();
      return;
    }
    state.authenticated = true;
    state.user = result.data.user || null;
    renderSignedIn();
    await loadSkills();
  }

  async function login(event) {
    event.preventDefault();
    const identifier = byId("padiemLoginIdentifier");
    const password = byId("padiemLoginPassword");
    const submit = byId("padiemLoginSubmit");
    if (!identifier || !password) return;
    setAuthError("");
    if (submit) submit.disabled = true;
    try {
      const result = await api("/auth/password/login", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ identifier: identifier.value, password: password.value })
      });
      if (!result.response.ok || !result.data || result.data.ok !== true) {
        setAuthError(safeMessage(result.data, "로그인하지 못했습니다."));
        return;
      }
      password.value = "";
      closeAuthDialog();
      await refreshAuth();
    } catch (_) {
      setAuthError("로그인 연결을 확인해 주세요.");
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function register(event) {
    event.preventDefault();
    const username = byId("padiemRegisterUsername");
    const email = byId("padiemRegisterEmail");
    const name = byId("padiemRegisterName");
    const password = byId("padiemRegisterPassword");
    const submit = byId("padiemRegisterSubmit");
    if (!username || !email || !name || !password) return;
    setAuthError("");
    if (submit) submit.disabled = true;
    try {
      const result = await api("/auth/password/register", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({
          username: username.value,
          email: email.value,
          name: name.value,
          password: password.value
        })
      });
      if (!result.response.ok || !result.data || result.data.ok !== true) {
        setAuthError(safeMessage(result.data, "계정을 만들지 못했습니다."));
        return;
      }
      password.value = "";
      closeAuthDialog();
      await refreshAuth();
    } catch (_) {
      setAuthError("회원가입 연결을 확인해 주세요.");
    } finally {
      if (submit) submit.disabled = false;
    }
  }

  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch (_) {
      // Local projection is still cleared; canonical session will be rechecked on refresh.
    }
    renderSignedOut();
  }

  async function changeSkill() {
    const select = byId("padiemSavedSkillSelect");
    if (!select) return;
    await loadSkill(select.value);
  }

  async function generate() {
    const select = byId("padiemSavedSkillSelect");
    const message = byId("padiemQuoteRequest");
    const button = byId("padiemQuoteGenerate");
    if (!select || !message || !state.authenticated) return;
    const requestText = message.value.trim();
    if (!requestText) {
      setQuoteStatus("견적 내용을 입력해 주세요.", "error");
      message.focus();
      return;
    }
    if (!state.loadedSkill || state.loadedSkill.savedSkillId !== select.value) {
      if (!(await loadSkill(select.value))) return;
    }
    if (button) button.disabled = true;
    setQuoteStatus("견적 내용을 정리하고 있습니다.", "working");
    try {
      const result = await api("/b66/quote/interpret", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify({ saved_skill_id: select.value, message: requestText })
      });
      const candidate = result.data && result.data.candidate;
      if (!result.response.ok || !result.data || result.data.ok !== true || !candidate) {
        setQuoteStatus(safeMessage(result.data, "견적 요청을 해석하지 못했습니다."), "error");
        return;
      }
      if (Array.isArray(candidate.missing) && candidate.missing.length) {
        setQuoteStatus("거래처와 품목·수량·단가를 조금 더 알려 주세요.", "missing");
        return;
      }

      const app = window.B66QuoteAppBridge;
      const semantic = window.SavedQuoteSkill;
      const bridge = window.B66QuoteSkillBridge;
      if (!app || !semantic || !bridge || typeof semantic.buildDraft !== "function") {
        setQuoteStatus("견적 런타임을 준비하지 못했습니다.", "error");
        return;
      }
      const current = app.getDraft();
      const input = {
        recipient: candidate.recipient,
        items: candidate.items,
        quoteNo: candidate.quoteNo || (current && current.meta && current.meta.quoteNo),
        issueDate: candidate.issueDate || (current && current.meta && current.meta.issueDate)
      };
      if (typeof candidate.memo === "string") input.memo = candidate.memo;
      if (typeof candidate.taxMode === "string") input.taxMode = candidate.taxMode;

      const built = semantic.buildDraft(state.loadedSkill.skill, input);
      if (!built || built.ok !== true || !built.draft) {
        setQuoteStatus("견적 입력값을 확인해 주세요.", "error");
        return;
      }
      if (!bridge.setServerSkill(state.loadedSkill.skill)) {
        setQuoteStatus("배정된 양식을 적용하지 못했습니다.", "error");
        return;
      }
      const replaced = app.replaceDraft(built.draft, { toast: "Padiem 내 견적서로 작성했습니다." });
      if (!replaced || replaced.ok !== true) {
        setQuoteStatus("견적 화면에 반영하지 못했습니다.", "error");
        return;
      }
      const direct = byId("directModeButton");
      if (direct) direct.click();
      setQuoteStatus("견적서가 준비되었습니다. 내용을 확인한 뒤 PDF로 저장하세요.", "ready");
    } catch (_) {
      setQuoteStatus("견적 연결을 확인해 주세요.", "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function bind() {
    const accountButton = byId("padiemAccountButton");
    const close = byId("padiemAuthClose");
    const loginForm = byId("padiemLoginForm");
    const registerForm = byId("padiemRegisterForm");
    const logoutButton = byId("padiemLogout");
    const select = byId("padiemSavedSkillSelect");
    const generateButton = byId("padiemQuoteGenerate");

    if (accountButton) accountButton.addEventListener("click", () => {
      if (state.authenticated) {
        const panel = byId("padiemAccountPanel");
        if (panel) panel.scrollIntoView({ behavior: "smooth", block: "start" });
      } else {
        openAuthDialog();
      }
    });
    if (close) close.addEventListener("click", closeAuthDialog);
    if (loginForm) loginForm.addEventListener("submit", login);
    if (registerForm) registerForm.addEventListener("submit", register);
    if (logoutButton) logoutButton.addEventListener("click", logout);
    if (select) select.addEventListener("change", changeSkill);
    if (generateButton) generateButton.addEventListener("click", generate);
    refreshAuth();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind, { once: true });
  } else {
    bind();
  }
})();
