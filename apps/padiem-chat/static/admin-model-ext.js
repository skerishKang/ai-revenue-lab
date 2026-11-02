/* Owner write surface for the B14 model console: providers, key slots and
   model registration. Read-only policy editing stays in admin-models.js; this
   file only talks to /api/admin/model-admin/* and never renders a key value
   that a server did not return as length/last4 metadata. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const API = "/api/admin/model-admin";
  const POLICY_BLOCKS = [
    ".content > .route-panel",
    ".content > .work-grid",
    ".content > .route-editor",
    ".content > .position-panel",
    ".content > details.advanced:not(#extAuditBox)",
  ];
  const MAX_SLOT = 14;
  const PROVIDER_MESSAGES = {
    authentication_required: "로그인이 필요합니다. 총관리자 계정으로 다시 로그인해 주세요.",
    global_model_admin_forbidden: "대표(owner) 계정만 사용할 수 있습니다.",
    central_admin_not_configured: "관리자 권한 확인이 구성되지 않았습니다.",
    central_admin_authority_unavailable: "관리자 권한을 확인하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    b14_model_ops_unconfigured: "B14 연결이 구성되지 않아 저장할 수 없습니다.",
    b14_model_ops_proof_unconfigured: "서버 간 증명 비밀값이 구성되지 않았습니다.",
    b14_model_ops_unreachable: "B14에 연결하지 못했습니다.",
    b14_model_ops_refused: "B14가 요청을 거부했습니다. 증명 설정을 확인해 주세요.",
    b14_model_ops_invalid_response: "B14 응답을 확인할 수 없습니다.",
    b14_model_ops_unavailable: "B14 작업을 완료하지 못했습니다.",
    reauth_required: "최근 5분 안에 로그인한 기록이 필요합니다. 아래에서 다시 로그인해 주세요.",
    request_body_invalid: "입력 내용을 확인해 주세요.",
    request_body_too_large: "입력 내용이 너무 큽니다.",
    provider_binding_not_a_governed_slot: "배정표에 있는 키 슬롯만 고를 수 있습니다.",
    provider_credential_source_invalid: "키 사용 방식을 확인해 주세요.",
    provider_origin_invalid: "기본 주소는 https:// 로 시작해야 합니다.",
    provider_hosts_invalid: "허용 호스트를 쉼표로 구분해 주세요.",
    provider_id_invalid: "프로바이더 ID를 확인해 주세요.",
    provider_invalid: "프로바이더 정보를 확인해 주세요.",
    provider_unknown_field: "허용되지 않은 항목이 있습니다.",
    provider_not_registered: "프로바이더를 먼저 저장해 주세요.",
    credential_slot_full: "이 키 슬롯은 이미 가득 찼습니다.",
    slot_not_governed: "배정표에 없는 슬롯입니다.",
    credential_value_invalid: "키 값 형식을 확인해 주세요. 공백 없는 8~4096자여야 합니다.",
    credential_value_placeholder: "예시 값은 저장할 수 없습니다.",
    credential_write_unconfigured: "이 배포에는 키를 저장할 환경 파일이 없습니다.",
    credential_write_store_managed: "이 배포는 Cloudflare Secrets Store가 키를 관리합니다.",
    credential_write_failed: "키를 저장하지 못했습니다. 서버 로그를 확인해 주세요.",
    model_probe_required: "모델 점검을 먼저 통과해야 등록할 수 있습니다.",
    model_probe_stale: "점검 후 모델 정보가 바뀌었습니다. 다시 점검해 주세요.",
    model_is_retired: "퇴역한 모델 ID는 다시 등록할 수 없습니다.",
    model_not_registered: "등록된 모델이 아닙니다.",
    model_not_retired: "퇴역 상태가 아닙니다.",
    model_id_must_start_with_provider_id: "모델 ID는 '프로바이더/모델명' 형식이어야 합니다.",
    model_id_invalid: "모델 ID를 확인해 주세요.",
    model_source_must_be_https: "가격 근거 URL은 https:// 로 시작해야 합니다.",
    model_unexpected_fields: "입력 항목을 확인해 주세요.",
    b14_model_registry_unavailable: "모델 등록 정보를 읽지 못했습니다.",
    b14_model_registry_write_failed: "저장하지 못했습니다. 서버 로그를 확인해 주세요.",
  };
  const ACTION_LABELS = {
    provider_save: "프로바이더 저장",
    model_probe: "모델 점검",
    model_register: "모델 등록",
    model_retire: "모델 퇴역",
    model_restore: "모델 복구",
    credential_write: "키 저장",
  };

  const state = { active: "policy", registry: null, probe: null, pendingSlotWrite: null };

  function node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined && text !== null) el.textContent = String(text);
    if (className) el.className = className;
    return el;
  }

  function cell(content) {
    const td = node("td");
    td.append(content);
    return td;
  }

  function show(box, message, variant) {
    if (!box) return;
    box.hidden = !message;
    box.className = "preview" + (variant === "error" ? " error" : "");
    box.replaceChildren();
    if (!message) return;
    const heading = variant === "error" ? "완료하지 못했습니다"
      : variant === "info" ? "진행 중"
      : "완료했습니다";
    box.append(node("strong", heading));
    box.append(node("div", message));
  }

  function messageFor(code) {
    return PROVIDER_MESSAGES[code] || "작업을 완료하지 못했습니다. (code: " + code + ")";
  }

  async function api(path, body) {
    const options = {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
    };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(API + path, options);
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    if (!response.ok || !data || data.ok !== true) {
      const code = typeof data?.error?.code === "string" ? data.error.code : "http_" + response.status;
      const error = new Error(code);
      error.code = code;
      throw error;
    }
    return data;
  }

  function fail(box, error) {
    const code = String(error?.code || error?.message || "unknown");
    show(box, messageFor(code), "error");
    if (code === "reauth_required") openReauth();
  }

  function failInline(target, error) {
    const code = String(error?.code || error?.message || "unknown");
    target.hidden = false;
    target.className = "ext-status is-bad";
    target.textContent = messageFor(code);
  }

  // --- tabs ------------------------------------------------------------------

  function activate(name) {
    state.active = name;
    for (const tab of document.querySelectorAll("[data-ext-tab]")) {
      tab.setAttribute("aria-selected", tab.dataset.extTab === name ? "true" : "false");
    }
    for (const block of document.querySelectorAll(POLICY_BLOCKS)) block.hidden = name !== "policy";
    for (const page of document.querySelectorAll("[data-ext-page]")) page.hidden = true;
    const page = document.querySelector('[data-ext-page="' + name + '"]');
    if (page) page.hidden = false;
    if (name !== "policy") loadRegistry();
    if (name === "providers") loadAudit();
  }

  for (const tab of document.querySelectorAll("[data-ext-tab]")) {
    tab.addEventListener("click", () => activate(tab.dataset.extTab));
  }

  // --- registry --------------------------------------------------------------

  function providerRows() {
    return Array.isArray(state.registry?.providers) ? state.registry.providers : [];
  }

  function slotLabel(binding) {
    const match = /PADIEM_B14_CREDENTIAL_(\d{2})$/.exec(String(binding || ""));
    return match ? "슬롯 " + match[1] : "—";
  }

  function renderSlotSelects() {
    const select = $("providerSlotSelect");
    const previous = select.value;
    select.replaceChildren();
    for (let number = 1; number <= MAX_SLOT; number += 1) {
      const value = "PADIEM_B14_CREDENTIAL_" + String(number).padStart(2, "0");
      const option = node("option", "슬롯 " + String(number).padStart(2, "0"));
      option.value = value;
      select.append(option);
    }
    if (previous) select.value = previous;
  }

  function renderProviderTable() {
    const body = $("providerBody");
    body.replaceChildren();
    const rows = providerRows();
    if (!rows.length) {
      const tr = node("tr");
      const td = node("td", "등록된 프로바이더가 없습니다.", "placeholder");
      td.colSpan = 4;
      tr.append(td);
      body.append(tr);
      return;
    }
    for (const row of rows) {
      const tr = node("tr");
      tr.append(cell(node("strong", row.provider_id, "slot-name")));
      const origin = node("div", null, "tail");
      origin.append(node("div", row.base_origin));
      if (Array.isArray(row.allowed_hosts) && row.allowed_hosts.length) {
        origin.append(node("small", row.allowed_hosts.join(", "), "dim"));
      }
      tr.append(cell(origin));
      tr.append(cell(node("span",
        row.credential_source === "platform_secret" ? slotLabel(row.credential_binding_name) : "키 없음",
        row.credential_source === "platform_secret" ? "tail" : "dim")));
      tr.append(cell(node("span", row.enabled ? "사용" : "중지", "state " + (row.enabled ? "good" : "idle"))));
      tr.title = "이 프로바이더의 값을 폼에 채웁니다";
      tr.addEventListener("click", () => fillProviderForm(row));
      body.append(tr);
    }
  }

  function fillProviderForm(row) {
    $("providerIdInput").value = row.provider_id || "";
    $("providerOriginInput").value = row.base_origin || "";
    $("providerHostsInput").value = Array.isArray(row.allowed_hosts) ? row.allowed_hosts.join(", ") : "";
    $("providerSourceSelect").value = row.credential_source === "none" ? "none" : "platform_secret";
    $("providerEnabledInput").checked = row.enabled !== false;
    if (row.credential_source === "platform_secret" && row.credential_binding_name) {
      $("providerSlotSelect").value = row.credential_binding_name;
    }
    updateProviderSlotState();
  }

  function updateProviderSlotState() {
    const disabled = $("providerSourceSelect").value === "none";
    $("providerSlotSelect").disabled = disabled;
  }

  function renderSlotWriteTable() {
    const body = $("slotWriteBody");
    body.replaceChildren();
    const grouped = new Map();
    for (const row of providerRows()) {
      if (row.credential_source !== "platform_secret") continue;
      const key = String(row.credential_binding_name || "");
      if (!grouped.has(key)) grouped.set(key, []);
      grouped.get(key).push(row.provider_id);
    }
    for (let number = 1; number <= MAX_SLOT; number += 1) {
      const binding = "PADIEM_B14_CREDENTIAL_" + String(number).padStart(2, "0");
      const tr = node("tr");
      const name = node("td");
      const strong = node("strong", "슬롯 " + String(number).padStart(2, "0"), "slot-name");
      strong.append(node("small", binding));
      name.append(strong);
      tr.append(name);

      const ids = grouped.get(binding) || [];
      const providers = node("div", null, "provider-list");
      if (ids.length) {
        for (const id of ids) providers.append(node("span", id, "provider-tag"));
      } else {
        providers.append(node("span", "비어 있음", "dim"));
      }
      tr.append(cell(providers));

      const input = document.createElement("input");
      input.type = "password";
      input.autocomplete = "new-password";
      input.spellcheck = false;
      input.placeholder = "새 키 값";
      input.dataset.slotNumber = String(number);
      input.setAttribute("aria-label", "슬롯 " + number + " 새 키 값");
      const wrap = node("div", null, "ext-inline");
      wrap.append(input);
      tr.append(cell(wrap));

      const save = node("button", "저장", "btn");
      save.type = "button";
      save.dataset.slotSave = String(number);
      save.addEventListener("click", () => writeSlot(number, input));
      const action = node("div", null, "ext-inline");
      action.append(save);
      tr.append(cell(action));
      body.append(tr);
    }
  }

  function renderModelTables() {
    const body = $("modelAdminBody");
    const retiredBody = $("retiredBody");
    body.replaceChildren();
    retiredBody.replaceChildren();
    const models = Array.isArray(state.registry?.models) ? state.registry.models : [];
    if (!models.length) {
      const tr = node("tr");
      const td = node("td", "등록된 모델이 없습니다.", "placeholder");
      td.colSpan = 4;
      tr.append(td);
      body.append(tr);
    }
    for (const model of models) {
      const tr = node("tr");
      const name = node("td");
      name.append(node("strong", model.display_name || model.id, "slot-name"));
      name.append(node("small", model.id, "dim"));
      tr.append(name);
      tr.append(cell(node("span", model.provider_id, "provider-tag")));
      tr.append(cell(node("span", model.enabled ? "사용" : "중지", "state " + (model.enabled ? "good" : "idle"))));
      const retire = node("button", "퇴역", "btn");
      retire.type = "button";
      retire.addEventListener("click", () => retireModel(model.id, model.display_name || model.id));
      const action = node("div", null, "ext-inline");
      action.append(retire);
      tr.append(cell(action));
      body.append(tr);
    }

    const retired = Array.isArray(state.registry?.retired_models) ? state.registry.retired_models : [];
    if (!retired.length) {
      const tr = node("tr");
      const td = node("td", "퇴역한 모델이 없습니다.", "placeholder");
      td.colSpan = 2;
      tr.append(td);
      retiredBody.append(tr);
      return;
    }
    for (const modelId of retired) {
      const tr = node("tr");
      tr.append(cell(node("span", modelId, "tail")));
      const restore = node("button", "복구", "btn");
      restore.type = "button";
      restore.addEventListener("click", () => retireModel(modelId, modelId, false));
      const action = node("div", null, "ext-inline");
      action.append(restore);
      tr.append(cell(action));
      retiredBody.append(tr);
    }
  }

  function renderModelProviderSelect() {
    const select = $("modelProviderSelect");
    const previous = select.value;
    select.replaceChildren();
    const rows = providerRows();
    if (!rows.length) {
      const option = node("option", "프로바이더를 먼저 저장하세요");
      option.value = "";
      select.append(option);
      return;
    }
    for (const row of rows) {
      const option = node("option", row.provider_id);
      option.value = row.provider_id;
      select.append(option);
    }
    if (previous && rows.some((row) => row.provider_id === previous)) select.value = previous;
  }

  function renderRegistry(data) {
    state.registry = data;
    $("providerStatus").textContent = providerRows().length + "개 프로바이더";
    const slots = Array.isArray(data.slot_usage) ? data.slot_usage : [];
    const used = slots.filter((slot) => Number(slot.providers) > 0).length;
    $("slotsStatus").textContent = used + "/" + MAX_SLOT + " 슬롯 사용 중";
    $("modelsStatus").textContent = (data.models?.length || 0) + "개 등록 · " +
      (data.retired_models?.length || 0) + "개 퇴역";
    renderSlotSelects();
    renderProviderTable();
    renderSlotWriteTable();
    renderModelTables();
    renderModelProviderSelect();
  }

  let loading = null;
  function loadRegistry() {
    if (loading) return loading;
    loading = (async () => {
      try {
        renderRegistry(await api("/registry"));
        $("providerStatus").classList.remove("is-bad");
      } catch (error) {
        const text = messageFor(error.code);
        $("providerStatus").textContent = "확인 불가";
        $("providerStatus").classList.add("is-bad");
        $("slotsStatus").textContent = "확인 불가";
        $("modelsStatus").textContent = "확인 불가";
        show($("providerResult"), text, "error");
        if (error.code === "authentication_required" ||
            error.code === "b14_model_ops_unconfigured") {
          const notice = $("accessNotice");
          if (notice) {
            notice.hidden = false;
            notice.textContent = text;
          }
        }
      } finally {
        loading = null;
      }
    })();
    return loading;
  }

  // --- providers -------------------------------------------------------------

  function providerPayload() {
    const providerId = $("providerIdInput").value.trim();
    const hosts = $("providerHostsInput").value.split(",")
      .map((value) => value.trim()).filter(Boolean);
    const source = $("providerSourceSelect").value;
    return {
      provider: {
        provider_id: providerId,
        base_origin: $("providerOriginInput").value.trim(),
        allowed_hosts: hosts,
        credential_source: source,
        credential_binding_name: source === "none" ? "" : $("providerSlotSelect").value,
        enabled: $("providerEnabledInput").checked,
      },
    };
  }

  async function saveProvider() {
    const box = $("providerResult");
    const button = $("providerApplyBtn");
    button.disabled = true;
    try {
      const data = await api("/provider-apply", providerPayload());
      show(box, "프로바이더 " + data.provider_id + " 저장됨 · 전체 " + data.provider_count + "개");
      await loadRegistry();
    } catch (error) {
      fail(box, error);
    } finally {
      button.disabled = false;
    }
  }

  // --- key slots -------------------------------------------------------------

  function writeSlot(number, input) {
    const value = input.value.trim();
    const box = $("slotResult");
    if (!value) {
      show(box, "새 키 값을 입력해 주세요.", "error");
      return;
    }
    input.value = "";
    state.pendingSlotWrite = { number, value };
    sendSlotWrite(box);
  }

  async function sendSlotWrite(box) {
    const pending = state.pendingSlotWrite;
    if (!pending) return;
    try {
      const data = await api("/credential-write", {
        slot_number: pending.number,
        value: pending.value,
      });
      state.pendingSlotWrite = null;
      show(box, "슬롯 " + String(pending.number).padStart(2, "0") + " 저장됨 · 길이 " +
        data.length + " · 끝 4자리 " + data.last4 + " · " +
        (data.target === "secret_file" ? "시크릿 파일" : "환경 파일") +
        (data.backup_kept ? " · 이전 값 백업됨" : ""));
      closeReauth();
      await loadRegistry();
    } catch (error) {
      if (error.code === "reauth_required") {
        show(box, messageFor("reauth_required"), "error");
        openReauth();
        return;
      }
      state.pendingSlotWrite = null;
      fail(box, error);
    }
  }

  // --- reauthentication ------------------------------------------------------

  function openReauth() {
    $("reauthPanel").hidden = false;
    $("reauthResult").hidden = true;
    $("reauthIdentifier").focus();
  }

  function closeReauth() {
    $("reauthPanel").hidden = true;
    $("reauthPassword").value = "";
    state.pendingSlotWrite = null;
  }

  async function submitReauth() {
    const box = $("reauthResult");
    const button = $("reauthSubmitBtn");
    const identifier = $("reauthIdentifier").value.trim();
    const password = $("reauthPassword").value;
    $("reauthPassword").value = "";
    if (!identifier || !password) {
      show(box, "이메일/아이디와 비밀번호를 입력해 주세요.", "error");
      return;
    }
    button.disabled = true;
    try {
      const response = await fetch("./api/auth/password/login", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ identifier, password }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        const code = typeof data?.error?.code === "string" ? data.error.code : "http_" + response.status;
        throw new Error(code === "invalid_credentials" ? "invalid_credentials" : code);
      }
      show(box, "다시 로그인했습니다. 저장을 이어서 진행합니다.", "info");
      if (state.pendingSlotWrite) await sendSlotWrite($("slotResult"));
    } catch (error) {
      const code = String(error?.message || "unknown");
      show(box, code === "invalid_credentials"
        ? "이메일/아이디 또는 비밀번호가 맞지 않습니다."
        : "로그인하지 못했습니다. (code: " + code + ")", "error");
    } finally {
      button.disabled = false;
    }
  }

  // --- models ----------------------------------------------------------------

  function modelPayload() {
    const providerId = $("modelProviderSelect").value;
    const capabilities = $("modelCapabilitiesInput").value.split(",")
      .map((value) => value.trim()).filter(Boolean)
      .filter((value, index, all) => all.indexOf(value) === index);
    const price = (id) => {
      const raw = $(id).value.trim();
      return raw === "" ? null : Number(raw);
    };
    return {
      id: $("modelIdInput").value.trim(),
      provider_id: providerId,
      upstream_model: $("modelUpstreamInput").value.trim(),
      display_name: $("modelDisplayNameInput").value.trim(),
      provider_name: $("modelProviderNameInput").value.trim() || providerId,
      capabilities,
      context_window: Number($("modelContextInput").value),
      input_price_usd_per_1m: price("modelInputPriceInput"),
      output_price_usd_per_1m: price("modelOutputPriceInput"),
      source: $("modelSourceInput").value.trim(),
      source_checked_at: $("modelCheckedInput").value,
      enabled: $("modelEnabledInput").checked,
    };
  }

  function clearProbe() {
    state.probe = null;
    $("modelApplyBtn").disabled = true;
  }

  async function probeModel() {
    const box = $("modelResult");
    const button = $("modelProbeBtn");
    const model = modelPayload();
    if (!model.provider_id) {
      show(box, "프로바이더를 먼저 저장한 뒤 골라 주세요.", "error");
      return;
    }
    clearProbe();
    button.disabled = true;
    show(box, "모델을 점검하고 있습니다. 실제 호출이라 최대 20초 걸립니다.", "info");
    try {
      const data = await api("/model-probe", { model });
      const probe = data.probe || {};
      if (probe.status === "PASS") {
        state.probe = { id: data.probe_id, model };
        $("modelApplyBtn").disabled = false;
        const latency = probe.latency_ms || {};
        show(box, "점검 통과 · 첫 토큰 " + (latency.first_token ?? "—") + "ms · 전체 " +
          (latency.stream_total ?? "—") + "ms · 10분 안에 등록하세요.");
      } else {
        show(box, "점검 실패(" + (probe.stage || "?") + ") · " + (probe.reason || "이유 미상") +
          " · 모델은 등록되지 않았습니다.", "error");
      }
    } catch (error) {
      fail(box, error);
    } finally {
      button.disabled = false;
    }
  }

  async function applyModel() {
    const box = $("modelResult");
    const button = $("modelApplyBtn");
    if (!state.probe) {
      show(box, messageFor("model_probe_required"), "error");
      return;
    }
    button.disabled = true;
    try {
      const data = await api("/model-apply", { model: state.probe.model, probe_id: state.probe.id });
      state.probe = null;
      show(box, "모델 " + data.model.id + " 등록됨 · 전체 " + data.model_count + "개");
      await loadRegistry();
    } catch (error) {
      fail(box, error);
      if (error.code !== "reauth_required") clearProbe();
    } finally {
      button.disabled = false;
    }
  }

  async function retireModel(modelId, label, retire = true) {
    const verb = retire ? "퇴역" : "복구";
    if (!window.confirm("'" + label + "' 모델을 " + verb + "할까요?\n퇴역은 실행 목록에서 빠지고 복구할 수 있습니다.")) return;
    const box = $("modelResult");
    try {
      const data = await api("/model-retire", { model_id: modelId, retire });
      show(box, modelId + " " + verb + "됨 · 전체 " + data.model_count + "개");
      await loadRegistry();
    } catch (error) {
      fail(box, error);
    }
  }

  // --- audit -----------------------------------------------------------------

  async function loadAudit() {
    const target = $("extAudit");
    if (!target) return;
    try {
      const data = await api("/audit");
      const entries = Array.isArray(data.entries) ? data.entries : [];
      $("extAuditCount").textContent = entries.length + "건";
      target.replaceChildren();
      if (!entries.length) {
        target.append(node("p", "아직 기록이 없습니다.", "placeholder"));
        return;
      }
      const list = node("div");
      for (const entry of entries.slice(0, 20)) {
        const line = node("div", null, "ext-inline");
        line.append(node("span", ACTION_LABELS[entry.action] || entry.action, "provider-tag"));
        line.append(node("span", (entry.model_id || entry.provider_id || entry.slot_number || "") + "", "dim"));
        line.append(node("span", entry.result === "pass" ? "성공" : "차단",
          "state " + (entry.result === "pass" ? "good" : "bad")));
        if (entry.last4) line.append(node("span", "끝 4자리 " + entry.last4, "dim"));
        list.append(line);
      }
      target.append(list);
    } catch (error) {
      target.replaceChildren(node("p", messageFor(error.code), "placeholder"));
    }
  }

  // --- wiring ----------------------------------------------------------------

  $("providerSourceSelect").addEventListener("change", updateProviderSlotState);
  $("providerApplyBtn").addEventListener("click", saveProvider);
  $("providerResetBtn").addEventListener("click", () => {
    for (const id of ["providerIdInput", "providerOriginInput", "providerHostsInput"]) $(id).value = "";
    $("providerSourceSelect").value = "platform_secret";
    $("providerEnabledInput").checked = true;
    updateProviderSlotState();
    show($("providerResult"), "");
  });
  $("extAuditBox").addEventListener("toggle", () => { if (!$("extAuditBox").open) return; loadAudit(); });

  $("reauthSubmitBtn").addEventListener("click", submitReauth);
  $("reauthCloseBtn").addEventListener("click", closeReauth);
  $("reauthPassword").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); submitReauth(); }
  });

  $("modelProbeBtn").addEventListener("click", probeModel);
  $("modelApplyBtn").addEventListener("click", applyModel);
  for (const id of ["modelIdInput", "modelProviderSelect", "modelProviderNameInput",
    "modelUpstreamInput", "modelDisplayNameInput", "modelCapabilitiesInput",
    "modelContextInput", "modelInputPriceInput", "modelOutputPriceInput",
    "modelSourceInput", "modelCheckedInput", "modelEnabledInput"]) {
    const field = $(id);
    if (field) field.addEventListener("input", clearProbe);
    if (field) field.addEventListener("change", clearProbe);
  }
  $("modelProviderSelect").addEventListener("change", () => {
    const providerId = $("modelProviderSelect").value;
    if (providerId && !$("modelProviderNameInput").value.trim()) {
      $("modelProviderNameInput").value = providerId;
    }
    const idField = $("modelIdInput");
    if (providerId && !idField.value.trim()) idField.value = providerId + "/";
  });
  $("modelCheckedInput").value = new Date().toISOString().slice(0, 10);

  const refresh = $("refreshBtn");
  if (refresh) {
    refresh.addEventListener("click", () => {
      if (state.active !== "policy") loadRegistry();
      if (state.active === "providers") loadAudit();
    });
  }

  renderSlotSelects();
  updateProviderSlotState();
})();