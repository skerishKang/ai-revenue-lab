/* #5108 integrated administrator hub. Server session is the only authority input. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const B66_ADMIN_ORIGIN = String(
    (window.PADIEM_ADMIN_CONFIG || {}).b66AdminOrigin || ""
  ).replace(/\/+$/, "");
  const ROLE_LABELS = Object.freeze({ SUPER_ADMIN: "SUPER_ADMIN · 총괄 관리자", ADMIN: "ADMIN · 관리자" });
  const CAPABILITY_ROWS = Object.freeze([
    ["admin_hub", "총관리자 허브"],
    ["role_management", "관리자 역할 지정·해제 (SUPER_ADMIN 전용)"],
    ["chat_admin", "Chat 관리"],
    ["claw_admin", "Claw 관리"],
    ["central_model_admin", "B14·중앙 모델 관리"],
    ["b66_platform_admin", "B66 플랫폼 정책"],
    ["b66_customer_admin", "B66 고객 데이터 (회원·문의)"],
  ]);
  const PRODUCTS = Object.freeze([
    {
      key: "b14",
      title: "B14 모델 관리",
      href: "./admin-models",
      copy: "B14 등록 모델, 중앙 정책, 등급별 실행 경로를 미리보기·저장·롤백합니다.",
      tag: "모델·정책",
      allowed: (caps) => caps.central_model_admin === true,
    },
    {
      key: "chat",
      title: "Chat 관리",
      href: "./admin/chat",
      copy: "Chat 회원 등급별 기본 모델과 자동 폴백 경로를 관리합니다.",
      tag: "실행 경로",
      allowed: (caps) => caps.chat_admin === true,
    },
    {
      key: "claw",
      title: "Claw 관리",
      href: "./admin/claw",
      copy: "Claw 회원 등급별 기본 모델과 자동 폴백 경로를 관리합니다.",
      tag: "실행 경로",
      allowed: (caps) => caps.claw_admin === true,
    },
    {
      key: "b66",
      title: "B66 관리",
      href: "./admin/b66",
      copy: "B66 모델 권한 화면과, 권한이 있는 경우 회원·문의 관리 화면으로 이동합니다.",
      tag: "견적 관리",
      allowed: (caps) => caps.b66_platform_admin === true || caps.b66_customer_admin === true,
    },
  ]);

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  function setNotice(message, variant) {
    const notice = $("accessNotice");
    notice.hidden = !message;
    notice.className = "notice " + (variant || "");
    notice.textContent = message || "";
  }

  function setRole(role) {
    $("roleBadge").textContent = role ? ROLE_LABELS[role] || role : "관리자 아님";
    $("roleCaption").textContent = role ? ROLE_LABELS[role] : "관리자 권한 없음";
  }

  function renderCards(capabilities) {
    const grid = $("hubGrid");
    grid.textContent = "";
    for (const product of PRODUCTS) {
      if (!product.allowed(capabilities)) continue;
      const card = node("a", null, "hub-card hub-card-" + product.key);
      card.href = product.href;
      card.append(
        node("span", product.tag, "hub-card-tag"),
        node("strong", product.title),
        node("small", product.copy),
        node("span", "열기 →", "hub-arrow")
      );
      grid.append(card);
    }
    if (!grid.childElementCount) {
      grid.append(node("p", "이 계정으로 열 수 있는 관리 화면이 없습니다.", "placeholder"));
    }
  }

  function renderCapabilities(capabilities) {
    const list = $("capabilityList");
    list.textContent = "";
    for (const [key, label] of CAPABILITY_ROWS) {
      const allowed = capabilities[key] === true;
      const row = node("div", null, "capability-row");
      row.dataset.capability = key;
      row.dataset.allowed = allowed ? "true" : "false";
      row.append(
        node("span", label, "capability-label"),
        node("span", allowed ? "✓ 사용 가능" : "— 없음", "capability-value " + (allowed ? "yes" : "no"))
      );
      list.append(row);
    }
  }

  function showGate(capabilities, authenticated) {
    $("adminContent").hidden = true;
    $("gatePanel").hidden = false;
    // #8312: 두 상태를 한 장의 카드에서 갈린다. 비로그인은 Chat 로그인 흐름으로
    // 곧장 들어가고(?admin_return=1 → 로그인 후 이 화면 복귀), 로그인했지만
    // 관리자가 아닌 계정은 권한 없음 안내와 다른 계정 로그인을 제공한다.
    const signedIn = authenticated === true;
    $("gateTitle").textContent = signedIn ? "관리자 권한이 없습니다" : "로그인이 필요합니다";
    $("gateCopy").textContent = signedIn
      ? "이 계정에는 관리자 권한이 없습니다. 관리자 권한이 있는 계정으로 다시 로그인하면 이 화면이 열립니다."
      : "관리자 화면은 Chat 로그인으로 열립니다. 로그인하면 이 화면으로 돌아옵니다.";
    $("gateLoginLink").hidden = signedIn;
    $("gateSwitchButton").hidden = !signedIn;
    const legacyB66 = (capabilities.b66_platform_admin === true || capabilities.b66_customer_admin === true)
      && B66_ADMIN_ORIGIN !== "";
    $("legacyB66Link").hidden = !legacyB66;
    if (legacyB66) {
      const customer = capabilities.b66_customer_admin === true;
      $("legacyB66Link").href = B66_ADMIN_ORIGIN + (customer ? "/admin.html" : "/admin-models.html");
      $("legacyB66Link").textContent = customer ? "기존 B66 관리자 화면" : "기존 B66 모델 권한 화면";
    }
  }

  async function load() {
    setNotice("");
    $("refreshBtn").disabled = true;
    try {
      const response = await fetch("/api/admin/session", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        setNotice("관리자 권한을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.", "error");
        $("roleBadge").textContent = "확인 실패";
        $("roleCaption").textContent = "권한 확인 실패";
        showGate({}, false);
        return;
      }
      const data = await response.json();
      const capabilities = data && typeof data.capabilities === "object" && data.capabilities
        ? data.capabilities
        : {};
      const role = typeof data.role === "string" ? data.role : null;
      setRole(role);
      if (data.authenticated !== true || !role) {
        showGate(capabilities, data.authenticated === true);
        return;
      }
      $("gatePanel").hidden = true;
      renderCards(capabilities);
      renderCapabilities(capabilities);
      $("adminContent").hidden = false;
    } catch (_) {
      setNotice("관리자 권한을 확인하는 중 연결이 끊겼습니다. 새로고침해 주세요.", "error");
      showGate({}, false);
    } finally {
      $("refreshBtn").disabled = false;
    }
  }

  $("refreshBtn").addEventListener("click", () => void load());

  // #8312: "다른 계정으로 로그인" — Chat 자체 로그아웃이 쓰는 같은 종료 경로를
  // 그대로 걷고(공유 세션이 있으면 먼저 끊는다), Chat 로그인 흐름으로 넘긴다.
  // 로그인이 끝나면 admin-session-shared.js가 /admin으로 되돌린다. 별도 로그인
  // 화면은 만들지 않는다.
  $("gateSwitchButton").addEventListener("click", async () => {
    const button = $("gateSwitchButton");
    button.disabled = true;
    try {
      await fetch("/auth/shared/logout", {
        method: "POST", headers: { Accept: "application/json" }, cache: "no-store",
      });
    } catch (_) {}
    try {
      await fetch("/api/auth/logout", { method: "POST", headers: { Accept: "application/json" } });
    } catch (_) {}
    window.location.assign("./index.html?admin_return=1");
  });

  const managedState = new Map();
  const selfHealState = new Map();

  function managedRow(link) {
    const item = document.createElement("li");
    item.className = "mcp-settings-card";
    const detail = document.createElement("div");
    detail.className = "mcp-settings-detail";
    const name = document.createElement("strong");
    name.textContent = link.label || link.mesh_node_id;
    detail.append(name);
    const state = document.createElement("span");
    state.textContent = managedState.get(link.link_id) ? "관리 PC" : "일반 PC";
    detail.append(state);
    const choice = document.createElement("label");
    choice.className = "mcp-settings-field";
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = managedState.get(link.link_id) === true;
    box.addEventListener("change", () => { void setManaged(link, box); });
    choice.append(box, document.createTextNode("관리 PC"));
    item.append(detail, choice);
    const label = link.label || (link.mesh_node_id || "").split("$")[0];
    const heal = selfHealState.get(label) || selfHealState.get(link.mesh_node_id);
    if (heal) {
      const note = document.createElement("span");
      note.className = "pc-self-heal";
      note.textContent = "자가 복구: " + heal.action + " · " + heal.detail + " · " + heal.at;
      detail.append(note);
    }
    // #8036: reported shares are candidates. An administrator picks one; the
    // consent line is sent with the approval so the scope stays one share unit.
    for (const candidate of (Array.isArray(link.share_candidates) ? link.share_candidates : [])) {
      if (!candidate || !candidate.root_ref) continue;
      const row = document.createElement("div");
      row.className = "mcp-settings-field";
      const label = document.createElement("span");
      label.textContent = (candidate.mapped_drive ? candidate.mapped_drive + " → " : "") +
        (candidate.label || candidate.path);
      const approve = document.createElement("button");
      approve.type = "button";
      approve.textContent = "이 공유 폴더 안만 열린다";
      approve.addEventListener("click", () => {
        void fetch("/api/pc/pairings/" + encodeURIComponent(link.link_id) + "/roots", {
          method: "POST", credentials: "same-origin", cache: "no-store",
          headers: { Accept: "application/json", "Content-Type": "application/json" },
          body: JSON.stringify({
            root_ref: candidate.root_ref,
            consent: "이 공유 폴더 안만 열린다",
          }),
        }).then((reply) => { if (reply.ok) window.location.reload(); });
      });
      row.append(label, approve);
      item.append(row);
    }
    return item;
  }

  async function setManaged(link, box) {
    const previous = managedState.get(link.link_id) === true;
    try {
      const response = await fetch("/api/pc/devices/" + encodeURIComponent(link.link_id) + "/managed", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ managed: !previous }),
      });
      const body = await response.json().catch(() => null);
      if (response.status === 200 && body?.ok === true) {
        managedState.set(link.link_id, body.link.managed === true);
        $("pcManagedError").hidden = true;
      } else if (response.status === 503 && body?.error?.code === "pc_pairing_not_ready") {
        $("pcManagedStatus").textContent = "준비 중";
        $("pcManagedError").textContent = "관리 PC 표시를 아직 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.";
        $("pcManagedError").hidden = false;
      } else {
        $("pcManagedError").textContent = "관리 PC 표시를 변경하지 못했습니다. 다시 시도해 주세요.";
        $("pcManagedError").hidden = false;
      }
    } catch (_) {
      $("pcManagedError").textContent = "관리 PC 표시를 변경하는 중 연결이 끊겼습니다.";
      $("pcManagedError").hidden = false;
    }
    box.checked = managedState.get(link.link_id) === true;
  }

  async function loadManaged() {
    const list = $("pcManagedList");
    list.replaceChildren();
    try {
      const response = await fetch("/api/pc/pairings", {
        headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store",
      });
      const body = await response.json().catch(() => null);
      const links = body?.ok === true && Array.isArray(body.links) ? body.links : [];
      const active = links.filter((link) => link && link.state === "active" && link.link_id);
      if (!active.length) {
        const empty = document.createElement("li");
        empty.className = "mcp-settings-card";
        empty.textContent = "연결된 PC가 없습니다.";
        list.append(empty);
        return;
      }
      selfHealState.clear();
      try {
        const healReply = await fetch("/api/ops/pc/self-heal", {
          headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store",
        });
        const healBody = await healReply.json().catch(() => null);
        (healBody?.reports || []).forEach((row) => selfHealState.set(row.node, row));
      } catch (_) {}
      const states = await Promise.allSettled(active.map((link) =>
        fetch("/api/pc/devices/" + encodeURIComponent(link.link_id) + "/managed", {
          headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store",
        }).then((reply) => reply.json().then((body) => ({ status: reply.status, body })))
      ));
      let notReady = false;
      active.forEach((link, index) => {
        const settled = states[index];
        if (settled.status !== "fulfilled" || settled.value.status === 503) {
          notReady = true;
          managedState.delete(link.link_id);
          return;
        }
        if (settled.value.status === 200 && settled.value.body?.ok === true) {
          managedState.set(link.link_id, settled.value.body.managed === true);
        }
      });
      for (const link of active) list.append(managedRow(link));
      $("pcManagedError").hidden = !notReady;
      if (notReady) {
        $("pcManagedStatus").textContent = "준비 중";
        $("pcManagedError").textContent = "관리 PC 표시를 아직 사용할 수 없습니다. 잠시 후 새로고침해 주세요.";
      } else {
        $("pcManagedStatus").textContent = "";
      }
    } catch (_) {
      $("pcManagedError").textContent = "PC 연결 목록을 불러오지 못했습니다.";
      $("pcManagedError").hidden = false;
    }
  }

  const adminLoad = load;
  load = async function () {
    await adminLoad();
    if (!$("adminContent").hidden) {
      $("pcManagedPanel").hidden = false;
      await loadManaged();
    }
  };
  void load();
})();
