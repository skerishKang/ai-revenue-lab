// #4428 S1 — PADIEM customer home (signed-in service launcher).
//
// AUTHORITY CONTRACT (must stay true)
//   SINGLE_SESSION_AUTHORITY  The only server fact this page reads is the
//                             existing canonical GET /api/auth/status. It adds
//                             no identity store, no second session, no token
//                             and no cookie of its own.
//   FAIL_CLOSED               Anything other than a server-confirmed
//                             authenticated signed-in session shows the gate.
//                             guest / expired / unavailable / network error are
//                             all "not signed in" for rendering purposes.
//   NO_FABRICATED_ACCESS      The canonical authority exposes no per-product
//                             entitlement read to the browser, so every service
//                             is reported as unverified. This page never claims
//                             a product is available or denied on its own.
//   NAVIGATION_NOT_GRANT      A link navigates to a product screen; it grants
//                             nothing. Each product keeps its own access check.
//   B66_SEPARATE              B66 is a different brand with its own customer
//                             account screens. It is absent from this catalog
//                             and no B66 member, quote, grade or PC fact is
//                             read, shown or linked here.
//   NO_PERSISTENCE            Nothing is written to browser storage, and no
//                             credential ever enters the URL.
(() => {
  "use strict";

  const STATUS_ENDPOINT = "/api/auth/status";
  const LOGOUT_ENDPOINT = "/api/auth/logout";
  const READ_TIMEOUT_MS = 10000;

  // Allowlisted PADIEM customer surfaces only. B66 is intentionally absent.
  // `href: null` means the entry is a platform service with no customer screen
  // of its own; it must never render a launch action.
  const SERVICES = Object.freeze([
    Object.freeze({ id: "chat", name: "PADIEM Chat", mark: "C", href: "./", entry: "open" }),
    Object.freeze({ id: "claw", name: "PADIEM Claw", mark: "K", href: "./", entry: "in_chat" }),
    Object.freeze({ id: "engine", name: "PADIEM Engine", mark: "E", href: null, entry: "platform" }),
  ]);

  const COPY = Object.freeze({
    ko: {
      title: "PADIEM Home",
      lead: "이 계정으로 사용하는 PADIEM 서비스를 한 곳에서 확인합니다.",
      loading: "로그인 상태를 확인하고 있습니다.",
      servicesTitle: "내 PADIEM 서비스",
      notice: "표시된 이용 상태는 권한 확인 결과가 아닙니다. 실제 접근 권한은 각 제품 화면에서 확인됩니다.",
      gateTitle: "로그인이 필요합니다",
      gateGuest: "PADIEM Home은 로그인한 사용자만 볼 수 있습니다.",
      gateExpired: "로그인 세션이 만료되었습니다. 다시 로그인해 주세요.",
      gateUnavailable: "로그인 상태를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
      gateAction: "로그인하기",
      accessUnverified: "확인 불가",
      accessUnverifiedHelp: "이 홈에서는 제품별 이용 권한을 확인할 수 없습니다.",
      entryOpen: "열기",
      entryInChat: "PADIEM Chat에서 열기",
      entryInChatHelp: "Claw는 PADIEM Chat 안에서 열립니다.",
      entryPlatform: "별도 화면 없음",
      entryPlatformHelp: "Engine은 Chat과 Claw 뒤에서 동작하는 서비스입니다.",
      helpSummary: "이용 상태를 확인할 수 없는 이유",
      helpBody1: "현재 서버는 로그인한 사용자의 제품별 이용 권한을 브라우저에 알려주는 계약을 제공하지 않습니다. 그래서 이 홈은 모든 서비스를 ‘확인 불가’로 표시하며, 이용 가능하다고 임의로 안내하지 않습니다.",
      helpBody2: "제품 접근 권한은 각 제품 화면이 스스로 확인합니다. 이 홈은 접근 권한을 부여하지 않습니다.",
      helpBody3: "B66 견적은 별도 브랜드로 고객 계정 화면이 다릅니다. 같은 이메일로 로그인해도 이 홈에 B66 회원 정보나 견적, PC 목록은 표시되지 않습니다.",
      signOut: "로그아웃",
      accountMenu: "계정 메뉴",
    },
    en: {
      title: "PADIEM Home",
      lead: "One place to see the PADIEM services you use with this account.",
      loading: "Checking your sign-in state.",
      servicesTitle: "My PADIEM services",
      notice: "The status shown is not a permission result. Each product screen confirms its own access.",
      gateTitle: "Sign-in required",
      gateGuest: "PADIEM Home is only visible to signed-in users.",
      gateExpired: "Your session expired. Please sign in again.",
      gateUnavailable: "The sign-in state cannot be confirmed. Please try again shortly.",
      gateAction: "Sign in",
      accessUnverified: "Unverified",
      accessUnverifiedHelp: "This home cannot confirm per-product access.",
      entryOpen: "Open",
      entryInChat: "Open in PADIEM Chat",
      entryInChatHelp: "Claw opens inside PADIEM Chat.",
      entryPlatform: "No separate screen",
      entryPlatformHelp: "Engine runs behind Chat and Claw.",
      helpSummary: "Why access status cannot be confirmed",
      helpBody1: "The server does not currently expose a per-product access contract to the browser. This home therefore marks every service as unverified instead of claiming it is available.",
      helpBody2: "Each product screen confirms its own access. This home grants no access.",
      helpBody3: "B66 quotes are a separate brand with its own customer account screens. Signing in with the same email does not show B66 member details, quotes or PCs here.",
      signOut: "Sign out",
      accountMenu: "Account menu",
    },
  });

  function locale() {
    const current = window.__padiemLocale && typeof window.__padiemLocale.getCurrent === "function"
      ? window.__padiemLocale.getCurrent()
      : document.documentElement.lang;
    return current === "en" ? COPY.en : COPY.ko;
  }

  const refs = {
    account: document.getElementById("padiemHomeAccount"),
    accountName: document.getElementById("padiemHomeAccountName"),
    accountMenu: document.getElementById("padiemHomeAccountMenu"),
    signOut: document.getElementById("padiemHomeSignOut"),
    title: document.getElementById("padiemHomeTitle"),
    lead: document.getElementById("padiemHomeLead"),
    status: document.getElementById("padiemHomeStatus"),
    gate: document.getElementById("padiemHomeGate"),
    gateTitle: document.getElementById("padiemHomeGateTitle"),
    gateBody: document.getElementById("padiemHomeGateBody"),
    gateAction: document.getElementById("padiemHomeGateAction"),
    services: document.getElementById("padiemHomeServices"),
    servicesTitle: document.getElementById("padiemHomeServicesTitle"),
    notice: document.getElementById("padiemHomeNotice"),
    grid: document.getElementById("padiemHomeGrid"),
    helpSummary: document.getElementById("padiemHomeHelpSummary"),
    helpBody: document.getElementById("padiemHomeHelpBody"),
  };

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (typeof text === "string") node.textContent = text;
    return node;
  }

  let sequence = 0;
  let pending = null;
  let signedInName = null;
  // What the page currently shows. A language change repaints from this, so a
  // translated page can never mix two languages.
  let view = null;

  function staticCopy() {
    const t = locale();
    refs.title.textContent = t.title;
    refs.lead.textContent = t.lead;
    refs.servicesTitle.textContent = t.servicesTitle;
    refs.notice.textContent = t.notice;
    refs.helpSummary.textContent = t.helpSummary;
    refs.signOut.textContent = t.signOut;
    refs.accountMenu.textContent = t.accountMenu;
    refs.helpBody.replaceChildren(
      element("p", "", t.helpBody1),
      element("p", "", t.helpBody2),
      element("p", "", t.helpBody3),
    );
  }

  function buildCard(service) {
    const t = locale();
    const item = element("li", "padiem-home-card");
    item.dataset.service = service.id;

    const mark = element("span", "padiem-home-card-mark", service.mark);
    mark.setAttribute("aria-hidden", "true");
    const name = element("h3", "padiem-home-card-name", service.name);

    // The canonical authority exposes no per-product access to the browser, so
    // this is the only honest value. Never "available" or "denied".
    const chip = element("span", "padiem-home-card-access", t.accessUnverified);
    chip.dataset.access = "unverified";
    chip.title = t.accessUnverifiedHelp;

    const detail = element("p", "padiem-home-card-help",
      service.entry === "platform" ? t.entryPlatformHelp
        : service.entry === "in_chat" ? t.entryInChatHelp : t.accessUnverifiedHelp);

    const foot = element("div", "padiem-home-card-foot");
    if (service.href) {
      const link = element("a", "padiem-home-card-action",
        service.entry === "in_chat" ? t.entryInChat : t.entryOpen);
      link.href = service.href;
      foot.appendChild(link);
    } else {
      // A platform service must not render a launch action it cannot honour.
      foot.appendChild(element("span", "padiem-home-card-noaction", t.entryPlatform));
    }

    item.append(mark, name, chip, detail, foot);
    return item;
  }

  // Single painter. Every region is reset first so no previous owner's view or
  // stale language can survive a repaint.
  function paint() {
    const t = locale();
    refs.gate.hidden = true;
    refs.services.hidden = true;
    refs.grid.replaceChildren();
    refs.account.hidden = true;
    refs.accountName.textContent = signedInName === null ? "" : signedInName;
    refs.status.textContent = "";
    if (!view) return;

    if (view.kind === "gate") {
      refs.gateTitle.textContent = t.gateTitle;
      refs.gateBody.textContent = view.reason === "expired" ? t.gateExpired
        : view.reason === "unavailable" ? t.gateUnavailable : t.gateGuest;
      refs.gateAction.textContent = t.gateAction;
      refs.gate.hidden = false;
      return;
    }

    for (const service of SERVICES) refs.grid.appendChild(buildCard(service));
    refs.services.hidden = false;
    refs.account.hidden = signedInName === null;
  }

  // Nothing user-specific survives this call: a sign-out or account switch must
  // never leave the previous owner's identity or service view on screen.
  function clearPrivate() {
    signedInName = null;
    view = null;
    paint();
  }

  function showGate(reason) {
    signedInName = null;
    view = { kind: "gate", reason };
    paint();
  }

  function showServices(name) {
    signedInName = name;
    view = { kind: "services" };
    paint();
  }

  // The whole access decision. Only a server-confirmed signed-in session passes.
  function classify(payload) {
    if (!payload || typeof payload !== "object") return "unavailable";
    if (payload.authenticated !== true) {
      if (payload.session_state === "expired") return "expired";
      if (payload.session_state === "unavailable") return "unavailable";
      return "guest";
    }
    // A contradictory payload (authenticated but not a signed-in state) is not
    // trusted as a signed-in session.
    if (payload.session_state !== "signed_in") return "unavailable";
    const user = payload.user;
    const name = user && typeof user.name === "string" && user.name.trim()
      ? user.name.trim().slice(0, 80) : null;
    return { name };
  }

  async function load() {
    if (pending) pending.abort();
    const controller = new AbortController();
    pending = controller;
    const request = ++sequence;
    refs.status.textContent = locale().loading;
    const timer = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
    try {
      const response = await fetch(STATUS_ENDPOINT, {
        method: "GET",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (request !== sequence) return;
      if (!response.ok) {
        showGate("unavailable");
        return;
      }
      const payload = await response.json();
      if (request !== sequence) return;
      const verdict = classify(payload);
      if (typeof verdict === "string") showGate(verdict);
      else showServices(verdict.name);
    } catch {
      if (request === sequence) showGate("unavailable");
    } finally {
      window.clearTimeout(timer);
      if (pending === controller) pending = null;
    }
  }

  async function signOut() {
    refs.signOut.disabled = true;
    try {
      await fetch(LOGOUT_ENDPOINT, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
    } catch {
      // A failed logout still clears this view and re-reads the real state.
    } finally {
      refs.signOut.disabled = false;
    }
    clearPrivate();
    await load();
  }

  refs.signOut.addEventListener("click", () => { void signOut(); });
  for (const event of ["padiem:auth-changed", "padiem:auth-state", "padiem:account-changed"]) {
    window.addEventListener(event, () => {
      // Drop the previous owner's view before the new state is known.
      clearPrivate();
      void load();
    });
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void load();
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) void load();
  });
  new MutationObserver(() => { staticCopy(); paint(); }).observe(
    document.documentElement, { attributes: true, attributeFilter: ["lang"] },
  );

  staticCopy();
  paint();
  void load();
})();
