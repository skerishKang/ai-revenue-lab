/* #5108 integrated administrator hub. Server session is the only authority input. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const B66_ADMIN_ORIGIN = "https://quick-quote-kr.pages.dev";
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

  function showGate(capabilities) {
    $("adminContent").hidden = true;
    $("gatePanel").hidden = false;
    const legacyB66 = capabilities.b66_platform_admin === true || capabilities.b66_customer_admin === true;
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
        $("gatePanel").hidden = false;
        $("adminContent").hidden = true;
        return;
      }
      const data = await response.json();
      const capabilities = data && typeof data.capabilities === "object" && data.capabilities
        ? data.capabilities
        : {};
      const role = typeof data.role === "string" ? data.role : null;
      setRole(role);
      if (data.authenticated !== true || !role) {
        showGate(capabilities);
        return;
      }
      $("gatePanel").hidden = true;
      renderCards(capabilities);
      renderCapabilities(capabilities);
      $("adminContent").hidden = false;
    } catch (_) {
      setNotice("관리자 권한을 확인하는 중 연결이 끊겼습니다. 새로고침해 주세요.", "error");
      $("gatePanel").hidden = false;
      $("adminContent").hidden = true;
    } finally {
      $("refreshBtn").disabled = false;
    }
  }

  $("refreshBtn").addEventListener("click", () => void load());
  void load();
})();
