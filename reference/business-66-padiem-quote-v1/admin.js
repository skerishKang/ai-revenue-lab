(() => {
  "use strict";
  const API = "/api/padiem/b66/admin";
  const state = { offset: 0, limit: 50, loading: false, authorized: false,
    query: "", statusFilter: "all", tierFilter: "all" };
  const id = (key) => document.getElementById(key);
  const page = id("adminContent")?.dataset.page || "members";
  const ERROR_TEXT = Object.freeze({
    auth_required: "로그인 후 다시 접속해 주세요.",
    admin_forbidden: "관리자 권한이 없습니다.",
    admin_unavailable: "관리자 인증 서비스를 사용할 수 없습니다.",
    membership_store_unavailable: "회원 관리 DB가 아직 준비되지 않았습니다.",
    membership_version_conflict: "다른 관리자에 의해 수정되었습니다. 새로고침 후 다시 시도하세요."
  });
  async function request(path, options = {}) {
    const response = await fetch(API + path, {
      cache: "no-store", credentials: "same-origin",
      headers: Object.assign({ "Accept": "application/json" }, options.headers || {}),
      ...options
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload || payload.ok !== true) {
      const code = payload?.error?.code;
      throw new Error(ERROR_TEXT[code] || "요청을 처리하지 못했습니다.");
    }
    return payload;
  }
  function message(text) {
    if (id("memberStatus")) id("memberStatus").textContent = text;
  }
  function td(text, className = "") {
    const el = document.createElement("td");
    if (className) el.className = className;
    el.textContent = text;
    return el;
  }
  function select(values, current, label) {
    const el = document.createElement("select");
    el.className = "member-select";
    el.setAttribute("aria-label", label);
    for (const [value, text] of values) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      if (value === current) option.selected = true;
      el.append(option);
    }
    return el;
  }
  function renderRow(member) {
    const tr = document.createElement("tr");
    const person = document.createElement("td");
    const email = document.createElement("div");
    email.className = "member-email";
    email.textContent = member.email || "";
    const name = document.createElement("div");
    name.className = "member-name";
    name.textContent = member.name || "";
    const link = document.createElement("a");
    if (/^usr_[a-f0-9]{32}$/.test(member.user_id || "")) {
      link.href = "/admin-member.html?id=" + encodeURIComponent(member.user_id);
    }
    link.className = "member-detail-link";
    link.title = "회원 사용내역 및 상세 보기";
    link.append(email, name);
    person.append(link);
    tr.append(person, td((member.created_at || "").slice(0, 10), "member-date"));
    const status = select([["pending", "승인 대기"], ["approved", "승인"], ["suspended", "이용 정지"]], member.status, "회원 상태");
    const tier = select([["FREE", "Free"], ["PLUS", "Plus"], ["PRO", "Pro"], ["MAX", "Max"]], member.tier, "이용 등급");
    const statusCell = document.createElement("td");
    const tierCell = document.createElement("td");
    statusCell.append(status); tierCell.append(tier);
    tr.append(statusCell, tierCell);
    const action = document.createElement("td");
    const save = document.createElement("button");
    save.className = "save";
    save.type = "button";
    save.textContent = "저장";
    save.addEventListener("click", async () => {
      if (!/^usr_[a-f0-9]{32}$/.test(member.user_id || "")) return;
      if (member.status === status.value && member.tier === tier.value) {
        message("변경된 내용이 없습니다."); return;
      }
      if (!window.confirm("이 회원의 가입 상태와 이용 등급을 변경하시겠습니까?")) return;
      save.disabled = true;
      try {
        await request("/members/" + member.user_id, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: status.value, tier: tier.value, expected_revision: member.revision })
        });
        await loadMembers();
        message("회원 권한이 저장됐습니다.");
      } catch (error) {
        save.disabled = false;
        message(error.message || "저장에 실패했습니다.");
      }
    });
    action.append(save);
    tr.append(action);
    return tr;
  }
  async function loadMembers() {
    if (state.loading || !state.authorized) return;
    state.loading = true;
    id("refreshMembers").disabled = true;
    try {
      const params = new URLSearchParams({
        limit: String(state.limit), offset: String(state.offset),
        q: state.query, status: state.statusFilter, tier: state.tierFilter
      });
      const data = await request("/members?" + params.toString());
      id("countPending").textContent = data.counts.pending;
      id("countApproved").textContent = data.counts.approved;
      id("countSuspended").textContent = data.counts.suspended;
      // Signup notifications moved to a dedicated page.
      const body = id("memberRows");
      body.replaceChildren();
      for (const member of data.members) body.append(renderRow(member));
      if (!data.members.length) {
        const empty = document.createElement("tr");
        const cell = td("표시할 회원이 없습니다.");
        cell.colSpan = 5; empty.append(cell); body.append(empty);
      }
      id("previousPage").disabled = state.offset === 0;
      id("nextPage").disabled = state.offset + data.members.length >= data.matched_total;
      id("pageLabel").textContent = String(Math.floor(state.offset / state.limit) + 1) + "페이지";
      id("matchedMembers").textContent = "검색 결과 " + data.matched_total + "명";
      message("");
    } catch (error) { message(error.message); }
    finally { state.loading = false; id("refreshMembers").disabled = false; }
  }

  let policyRevision = null;
  let canEnforce = false;
  async function loadModelPolicy() {
    const holder = id("modelTierColumns");
    const switches = id("modelSwitchList");
    holder.replaceChildren();
    switches.replaceChildren();
    id("savePolicy").disabled = true;
    try {
      const result = await request("/model-policy");
      policyRevision = result.policy.revision;
      canEnforce = result.enforcement_enabled === true;
      id("activatePolicy").checked = result.policy.active === true;
      id("activatePolicy").disabled = !canEnforce;
      id("enforcementNote").textContent = canEnforce
        ? (result.policy.active ? "현재 등급별 모델 사용 제한이 적용 중입니다." : "아직 모델 사용 제한은 적용되지 않았습니다.")
        : "서버 회원 권한 검증을 활성화하기 전입니다. 현재 모델 배정은 저장만 할 수 있습니다.";
      // Every B14-registered model has its own global ON/OFF switch.
      // Tier selections are preserved when OFF, but cannot grant access.
      const disabledModels = new Set(result.policy.disabled_models || []);
      const updateTierAvailability = () => {
        const off = new Set([...switches.querySelectorAll('input[data-model-id]')]
          .filter(box => !box.checked).map(box => box.dataset.modelId));
        for (const box of holder.querySelectorAll('input[data-model-id]')) {
          box.disabled = off.has(box.dataset.modelId);
          box.closest("label")?.classList.toggle("model-is-off", box.disabled);
        }
      };
      for (const model of result.models) {
        const label = document.createElement("label");
        label.className = "model-switch";
        const title = document.createElement("span");
        title.textContent = model.name;
        const input = document.createElement("input");
        input.type = "checkbox";
        input.dataset.modelId = model.model_id;
        input.checked = !disabledModels.has(model.model_id);
        input.setAttribute("aria-label", model.name + " 전체 사용");
        const status = document.createElement("strong");
        const syncStatus = () => { status.textContent = input.checked ? "ON" : "OFF"; };
        input.addEventListener("change", () => { syncStatus();updateTierAvailability(); });
        syncStatus();
        label.append(title,input,status);
        switches.append(label);
      }
      const tiers = [["FREE","Free"],["PLUS","Plus"],["PRO","Pro"],["MAX","Max"]];
      for (const [tier,label] of tiers) {
        const box = document.createElement("div");
        box.className = "tier-card"; box.dataset.tier = tier;
        const heading = document.createElement("h3"); heading.textContent = label;
        box.append(heading);
        for (const model of result.models) {
          const row = document.createElement("label"); row.className = "tier-model";
          const check = document.createElement("input");
          check.type = "checkbox"; check.value = model.model_id;
          check.dataset.modelId = model.model_id;
          check.checked = result.policy.tiers[tier].includes(model.model_id);
          const text = document.createElement("span"); text.textContent = model.name;
          row.append(check, text);box.append(row);
        }
        holder.append(box);
      }
      updateTierAvailability();
      id("savePolicy").disabled = false;
      id("policyStatus").textContent = "";
    } catch (error) {
      id("policyStatus").textContent = error.message || "모델 정책을 불러오지 못했습니다.";
    }
  }
  async function saveModelPolicy() {
    if (policyRevision === null) return;
    const tiers = {};
    for (const tier of ["FREE","PLUS","PRO","MAX"]) {
      const box = [...id("modelTierColumns").children].find(x => x.dataset.tier === tier);
      tiers[tier] = box
        ? [...box.querySelectorAll('input[type="checkbox"]:checked')].map(x=>x.value)
        : [];
    }
    const disabledModels = [...id("modelSwitchList").querySelectorAll('input[data-model-id]')]
      .filter(box=>!box.checked).map(box=>box.dataset.modelId);
    const active = canEnforce && id("activatePolicy").checked;
    if (active && !tiers.FREE.some(model=>!disabledModels.includes(model))) {
        id("policyStatus").textContent = "Free 등급에 ON인 모델을 최소 1개 지정해 주세요.";
      return;
    }
    if (!window.confirm("등급별 모델 허용 목록을 저장하시겠습니까?")) return;
    id("savePolicy").disabled = true;
    try {
      await request("/model-policy", {
        method:"PUT", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({expected_revision:policyRevision,active,tiers,
          disabled_models:disabledModels})
      });
      await loadModelPolicy();
      id("policyStatus").textContent = "모델 권한 설정이 저장됐습니다.";
    } catch (error) {
      id("policyStatus").textContent = error.message || "모델 설정을 저장하지 못했습니다.";
      id("savePolicy").disabled = false;
    }
  }

  async function loadNotices() {
    const result = await request("/members?limit=1&offset=0");
    id("noticePending").textContent = result.signup_events_pending;
    id("retryNotices").hidden = result.notification_delivery_configured !== true;
    id("noticeGuide").textContent = result.notification_delivery_configured === true
      ? "등록된 알림 채널로 자동 전송하며, 실패한 항목은 다시 전송할 수 있습니다."
      : "알림용 서버 계정이 연결되지 않았습니다. 설정 전에는 가입 이벤트만 기록합니다.";
  }
  function addDetailItem(list,text) {
    const li=document.createElement("li");
    li.textContent=text;
    list.append(li);
  }
  async function loadMemberDetail() {
    const uid = new URLSearchParams(location.search).get("id") || "";
    if (!/^usr_[a-f0-9]{32}$/.test(uid)) {
      id("detailError").textContent="유효한 회원이 선택되지 않았습니다.";
      return;
    }
    try {
      const data = await request("/members/" + uid + "/detail");
      const member = data.member;
      id("detailName").textContent=member.name || "회원";
      id("detailEmail").textContent=member.email;
      id("detailTier").textContent="등급 · " + member.tier;
      id("detailStatus").textContent="상태 · " + ({
        pending:"승인 대기",approved:"승인",suspended:"이용 정지"
      }[member.status] || member.status);
      id("detailJoined").textContent="가입일 · " + member.created_at.slice(0,10);
      const metric=data.usage;
      id("detailToday").textContent=String(metric.today);
      id("detailWeek").textContent=String(metric.last_7_days);
      id("detailMonth").textContent=String(metric.last_30_days);
      id("detailQuoteCount").textContent="저장된 견적 " + data.quotes.saved_count + "건";
      for (const quote of data.quotes.recent) {
        addDetailItem(id("detailQuotes"),"저장 시점: " + quote.updated_at.slice(0,16));
      }
      if (!data.quotes.recent.length) addDetailItem(id("detailQuotes"),"저장된 견적 이력이 없습니다.");
      for (const audit of data.changes) {
        addDetailItem(id("detailAudit"),audit.at.slice(0,16)
          + " · " + audit.from_status + "/" + audit.from_tier
          + " → " + audit.to_status + "/" + audit.to_tier);
      }
      if (!data.changes.length) addDetailItem(id("detailAudit"),"등급 변경 이력이 없습니다.");
      id("detailBody").hidden=false;
    } catch (e) {
      id("detailError").textContent=e.message || "회원 이력을 불러오지 못했습니다.";
    }
  }
  async function init() {
    try {
      const who = await request("/me");
      if (who.admin !== true) {
        id("access").textContent = "관리자 권한이 없습니다. 권한이 있는 Google 계정으로 로그인해 주세요.";
        return;
      }
      state.authorized = true;
      id("access").hidden = true;
      id("adminContent").hidden = false;
      if (page==="members") await loadMembers();
      else if (page==="models") await loadModelPolicy();
      else if (page==="notices") await loadNotices();
      else if (page==="detail") await loadMemberDetail();
    } catch (error) {
      id("access").textContent = error.message || "관리자 권한을 확인하지 못했습니다.";
    }
  }
  for (const item of document.querySelectorAll(".nav-link[data-page]")) {
    item.classList.toggle("active",
      item.dataset.page===(page==="detail"?"members":page));
  }
  if (id("refreshMembers")) id("refreshMembers").addEventListener("click", loadMembers);
  if (id("memberFilterForm")) id("memberFilterForm").addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.loading) return;
    state.query = id("memberSearch").value.trim();
    state.statusFilter = id("memberStatusFilter").value;
    state.tierFilter = id("memberTierFilter").value;
    state.offset = 0;
    loadMembers();
  });
  if (id("savePolicy")) id("savePolicy").addEventListener("click", saveModelPolicy);
  if (id("retryNotices")) id("retryNotices").addEventListener("click", async () => {
    if (!window.confirm("전송되지 않은 가입 알림을 다시 보내시겠습니까?")) return;
    const button = id("retryNotices"); button.disabled = true;
    try {
      const result = await request("/alerts/dispatch", {method:"POST"});
      id("noticeStatus").textContent = "전송: " + result.result.sent + "건, 실패: " + result.result.failed + "건";
      await loadNotices();
    } catch (error) { id("noticeStatus").textContent = error.message; }
    finally { button.disabled = false; }
  });
  if (id("previousPage")) id("previousPage").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit); loadMembers();
  });
  if (id("nextPage")) id("nextPage").addEventListener("click", () => {
    state.offset += state.limit; loadMembers();
  });
  init();
})();