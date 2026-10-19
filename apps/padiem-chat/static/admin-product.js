/* #5108 product admin entry. Reuses the signed session; no separate login. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const B66_ADMIN_ORIGIN = String(
    (window.PADIEM_ADMIN_CONFIG || {}).b66AdminOrigin || ""
  ).replace(/\/+$/, "");
  const ROLE_LABELS = Object.freeze({ SUPER_ADMIN: "SUPER_ADMIN · 총괄 관리자", ADMIN: "ADMIN · 관리자" });
  const CONFIG = Object.freeze({
    b14: {
      capability: "central_model_admin",
      redirect: "/admin-models",
      links: [],
    },
    chat: {
      capability: "chat_admin",
      links: [
        { title: "Chat 실행 경로 관리", href: "/admin-models#routeEditorHeading", copy: "Chat·Claw·B66 공통 등급별 기본 모델과 자동 폴백" },
        { title: "Chat 열기", href: "/", copy: "현재 로그인 세션으로 Padiem Chat 홈을 엽니다." },
      ],
    },
    claw: {
      capability: "claw_admin",
      links: [
        { title: "Claw 실행 경로 관리", href: "/admin-models#routeEditorHeading", copy: "Chat·Claw·B66 공통 등급별 기본 모델과 자동 폴백" },
        { title: "Claw 열기", href: "/", copy: "Padiem Chat 홈에서 Claw 메뉴로 이동합니다." },
      ],
    },
    b66: {
      capability: "b66_platform_admin",
      anyOf: ["b66_platform_admin", "b66_customer_admin"],
      links: [],
    },
  });

  function node(tag, value, className) {
    const el = document.createElement(tag);
    if (value !== undefined && value !== null) el.textContent = String(value);
    if (className) el.className = className;
    return el;
  }

  function setNotice(message) {
    const notice = $("accessNotice");
    notice.hidden = !message;
    notice.textContent = message || "";
  }

  function b66Links(capabilities) {
    const links = [];
    if (B66_ADMIN_ORIGIN === "") return links;
    if (capabilities.b66_platform_admin === true) {
      links.push({ title: "B66 모델 권한", href: B66_ADMIN_ORIGIN + "/admin-models.html", copy: "B66 등급별 모델 허용·차단 정책" });
    }
    if (capabilities.b66_customer_admin === true) {
      links.push(
        { title: "B66 회원 관리", href: B66_ADMIN_ORIGIN + "/admin.html", copy: "가입 승인과 회원 등급" },
        { title: "회원 문의", href: B66_ADMIN_ORIGIN + "/admin-inquiries.html", copy: "회원이 접수한 문의 처리" },
        { title: "가입 알림", href: B66_ADMIN_ORIGIN + "/admin-notices.html", copy: "가입 알림 발송 상태" },
        { title: "승인 요청", href: B66_ADMIN_ORIGIN + "/admin-saved-skill-candidates.html", copy: "저장 스킬 후보 승인·반려" }
      );
    }
    return links;
  }

  function renderLinks(links) {
    const host = $("productLinks");
    host.textContent = "";
    if (!links.length) {
      host.append(node("p", "표시할 관리 화면이 없습니다.", "placeholder"));
      return;
    }
    for (const link of links) {
      const anchor = node("a", null, "product-link");
      anchor.href = link.href;
      anchor.append(node("strong", link.title), node("small", link.copy));
      host.append(anchor);
    }
  }

  function allowedFor(product, capabilities) {
    const config = CONFIG[product];
    if (!config) return false;
    if (Array.isArray(config.anyOf)) return config.anyOf.some((key) => capabilities[key] === true);
    return capabilities[config.capability] === true;
  }

  async function load() {
    const product = document.body.dataset.product || "";
    const config = CONFIG[product];
    if (!config) return;
    try {
      const response = await fetch("/api/admin/session", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        setNotice("관리자 권한을 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.");
        $("gatePanel").hidden = false;
        return;
      }
      const data = await response.json();
      const capabilities = data && typeof data.capabilities === "object" && data.capabilities
        ? data.capabilities
        : {};
      const role = typeof data.role === "string" ? data.role : null;
      const b66 = capabilities.b66_platform_admin === true || capabilities.b66_customer_admin === true;
      $("roleBadge").textContent = role ? ROLE_LABELS[role] || role : b66 ? "B66 관리자" : "관리자 아님";
      $("roleCaption").textContent = role ? ROLE_LABELS[role] || role : b66 ? "B66 관리자" : "관리자 권한 없음";
      if (data.authenticated !== true || !allowedFor(product, capabilities)) {
        $("gatePanel").hidden = false;
        $("productContent").hidden = true;
        return;
      }
      $("gatePanel").hidden = true;
      if (config.redirect) {
        window.setTimeout(() => { $("productContent").hidden = false; }, 800);
        window.location.replace(config.redirect);
        return;
      }
      renderLinks(product === "b66" ? b66Links(capabilities) : config.links);
      $("productContent").hidden = false;
      $("capabilityStatus").textContent = "서버 권한 확인됨";
    } catch (_) {
      setNotice("관리자 권한을 확인하는 중 연결이 끊겼습니다. 새로고침해 주세요.");
      $("gatePanel").hidden = false;
    }
  }

  void load();
})();
