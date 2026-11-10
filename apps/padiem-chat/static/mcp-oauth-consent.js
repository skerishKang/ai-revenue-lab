(() => {
  "use strict";

  const params = new URLSearchParams(window.location.search);
  const card = document.getElementById("mcpOauthCard");
  const loading = document.querySelector(".mcp-oauth-loading");
  const content = document.getElementById("mcpOauthContent");
  const login = document.getElementById("mcpOauthLogin");
  const loginLink = document.getElementById("mcpOauthLoginLink");
  const intro = document.getElementById("mcpOauthIntro");
  const accountLine = document.getElementById("mcpOauthAccount");
  const switchLink = document.getElementById("mcpOauthSwitch");
  const clientName = document.getElementById("mcpOauthClientName");
  const redirectHost = document.getElementById("mcpOauthRedirectHost");
  const pcSelect = document.getElementById("mcpOauthPc");
  const pcList = document.getElementById("mcpOauthPcList");
  const scopeSelectedHelp = document.getElementById("mcpOauthScopeSelectedHelp");
  const noPc = document.getElementById("mcpOauthNoPc");
  const approve = document.getElementById("mcpOauthApprove");
  const deny = document.getElementById("mcpOauthDeny");
  const status = document.getElementById("mcpOauthStatus");
  let info = null;

  function text(key, variables) {
    if (window.__padiemLocale && typeof window.__padiemLocale.text === "function") {
      return window.__padiemLocale.text(key, variables || null);
    }
    return key;
  }

  function showStatus(key) {
    if (!status) return;
    if (loading) loading.hidden = true;
    status.textContent = text(key);
    status.hidden = false;
    if (card) card.setAttribute("aria-busy", "false");
  }

  function syncTitle() {
    document.title = text("mcp-oauth-page-title");
  }

  function safeLoginUrl(value) {
    return typeof value === "string" && value.startsWith("/") && !value.startsWith("//") && !value.includes("\\")
      ? value
      : "/";
  }

  // 계정 전환은 세션을 폐기하는 변경 요청이라 POST로만 받는다. 링크 클릭을
  // 같은 주소의 폼 POST로 바꿔 제출한다(브라우저가 이동하며 쿠키를 실어 보낸다).
  function submitSwitchAccount(url) {
    const form = document.createElement("form");
    form.method = "post";
    form.action = url;
    document.body.append(form);
    form.submit();
  }

  function showLogin(url) {
    if (loading) loading.hidden = true;
    if (content) content.hidden = true;
    if (status) status.hidden = true;
    if (loginLink) loginLink.setAttribute("href", safeLoginUrl(url));
    if (login) login.hidden = false;
    if (card) card.setAttribute("aria-busy", "false");
  }

  // Same facts `pc_devices` shows: the owner's label, the device's last six
  // characters and whether the queue currently reports it online.
  function pcText(pc) {
    const name = (pc && (pc.name || pc.label)) || "";
    const id6 = (pc && pc.id6) || "";
    const shown = name || id6 || (pc && pc.device_id) || "";
    const parts = [shown];
    if (id6 && name && id6 !== name) parts.push(id6);
    if (pc && pc.online === true) parts.push(text("mcp-oauth-pc-online"));
    return parts.join(" · ");
  }

  function accountName() {
    const account = (info && info.account) || null;
    return account && typeof account.display === "string" ? account.display : "";
  }

  function render() {
    if (!info) return;
    // 이 화면이 어느 계정으로 연결하는지 먼저 밝힌다. "다른 계정으로 로그인"은
    // 로그아웃한 뒤 같은 OAuth 요청 값 그대로 이 화면으로 돌아온다.
    const account = accountName();
    if (accountLine) {
      accountLine.textContent = account ? text("mcp-oauth-account", { account: account }) : "";
      accountLine.hidden = !account;
    }
    if (switchLink) {
      const target = safeLoginUrl(info.switch_account_url || "");
      switchLink.setAttribute("href", target);
      // 세션 폐기는 POST 변경 요청: 평시 링크 이동 대신 폼 제출로 보낸다.
      // render()는 정보 갱신 때 다시 불릴 수 있으므로 리스너는 한 번만 붙인다.
      if (!switchLink.dataset.switchBound) {
        switchLink.dataset.switchBound = "1";
        switchLink.addEventListener("click", (event) => {
          event.preventDefault();
          submitSwitchAccount(safeLoginUrl(info && info.switch_account_url || ""));
        });
      }
    }
    if (intro) {
      intro.replaceChildren();
      const strong = document.createElement("strong");
      strong.textContent = info.client_name;
      intro.append(strong, document.createTextNode(" " + text("mcp-oauth-intro-suffix")));
    }
    if (clientName) clientName.textContent = info.client_name;
    if (redirectHost) {
      try {
        redirectHost.textContent = new URL(info.redirect_uri).host;
      } catch (_) {
        redirectHost.textContent = info.redirect_uri;
      }
    }
    if (pcSelect) {
      const previous = pcSelect.value;
      pcSelect.replaceChildren();
      (info.pcs || []).forEach((pc) => {
        const option = document.createElement("option");
        option.value = pc.device_id;
        option.textContent = pcText(pc);
        pcSelect.append(option);
      });
      if (previous && info.pcs.some((pc) => pc.device_id === previous)) pcSelect.value = previous;
      const empty = !info.pcs || info.pcs.length === 0;
      pcSelect.hidden = empty;
      if (noPc) {
        noPc.hidden = !empty;
        if (empty) {
          noPc.textContent = account
            ? text("mcp-oauth-no-pc-account", { account: account })
            : text("mcp-oauth-no-pc");
        }
      }
      if (approve) approve.disabled = empty;
    }
    if (pcList) {
      // 선택 범위의 체크 목록. 처음에는 전부 체크 — "고른 PC만"을 골라도
      // 체크를 지우기 전까지는 "내 PC 전부"와 같은 결과다.
      pcList.replaceChildren();
      (info.pcs || []).forEach((pc) => {
        const label = document.createElement("label");
        label.className = "mcp-oauth-pc-choice";
        const box = document.createElement("input");
        box.type = "checkbox";
        box.value = pc.device_id;
        box.checked = true;
        box.addEventListener("change", () => {
          if (!box.checked && pcSelect && pcSelect.value === pc.device_id) {
            const first = Array.from(pcList.querySelectorAll("input")).find((item) => item.checked);
            if (first && pcSelect) pcSelect.value = first.value;
          }
        });
        const text = document.createElement("span");
        text.textContent = pcText(pc);
        label.append(box, text);
        pcList.append(label);
      });
    }
  }

  function selectedScope() {
    const checked = document.querySelector('input[name="mcpOauthDeviceScope"]:checked');
    return checked ? checked.value : "all";
  }

  function syncScopeView() {
    const selected = selectedScope() === "selected";
    if (pcList) pcList.hidden = !selected;
    if (scopeSelectedHelp) scopeSelectedHelp.hidden = !selected;
  }

  function checkedDeviceIds() {
    return Array.from((pcList || document).querySelectorAll("input[type=checkbox]:checked"))
      .map((box) => box.value);
  }

  async function load() {
    try {
      const response = await fetch("/oauth/authorize/info?" + params.toString(), {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      if (response.status === 401) {
        showLogin(response.headers.get("X-MCP-Login-Url") || "/");
        return;
      }
      if (!response.ok) {
        showStatus("mcp-oauth-error");
        return;
      }
      info = await response.json();
      if (!info || typeof info.client_name !== "string" || !Array.isArray(info.pcs)) {
        showStatus("mcp-oauth-error");
        return;
      }
      if (loading) loading.hidden = true;
      content.hidden = false;
      render();
      if (card) card.setAttribute("aria-busy", "false");
    } catch (_) {
      showStatus("mcp-oauth-error");
    }
  }

  async function decide(decision) {
    if (decision === "approve" && (!pcSelect || !pcSelect.value)) return;
    approve.disabled = true;
    deny.disabled = true;
    if (status) status.hidden = true;
    const payload = {};
    ["response_type", "client_id", "redirect_uri", "code_challenge",
     "code_challenge_method", "resource", "scope", "state"].forEach((key) => {
      const value = params.get(key);
      if (value !== null) payload[key] = value;
    });
    payload.decision = decision;
    if (decision === "approve") {
      payload.device_id = pcSelect.value;
      // 기본은 "내 PC 전부". "고른 PC만"이면 체크한 목록을 보내고, 기본 PC는
      // 항상 목록에 남는다(서버도 강제한다).
      const scope = selectedScope();
      payload.device_scope = scope;
      if (scope === "selected") {
        const ids = checkedDeviceIds();
        if (pcSelect.value && !ids.includes(pcSelect.value)) ids.push(pcSelect.value);
        payload.device_ids = ids;
      }
    }
    syncScopeView();
    try {
      const response = await fetch("/oauth/authorize", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(payload),
      });
      if (response.status === 401) {
        showLogin(window.location.pathname + window.location.search);
        return;
      }
      if (!response.ok) {
        showStatus("mcp-oauth-error");
        return;
      }
      const result = await response.json();
      if (!result || typeof result.redirect_url !== "string") {
        showStatus("mcp-oauth-error");
        return;
      }
      window.location.assign(result.redirect_url);
    } catch (_) {
      showStatus("mcp-oauth-error");
    } finally {
      approve.disabled = false;
      deny.disabled = false;
    }
  }

  approve?.addEventListener("click", () => decide("approve"));
  deny?.addEventListener("click", () => decide("deny"));
  document.querySelectorAll('input[name="mcpOauthDeviceScope"]').forEach((radio) => {
    radio.addEventListener("change", syncScopeView);
  });
  window.addEventListener("padiem:localechange", () => {
    syncTitle();
    render();
  });
  syncTitle();
  syncScopeView();
  load();
})();
