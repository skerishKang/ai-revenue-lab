// #4428 S1 — PADIEM customer home (signed-in service launcher).
//
// AUTHORITY CONTRACT (must stay true)
//   SERVER_ACCESS_PROJECTION First verify GET /api/auth/status (presentation),
//                             then GET /api/home/product-access (server-approved
//                             shared Chat+Claw bundle). Neither read mints any
//                             identity, entitlement, device grant or token.
//   FAIL_CLOSED               Only a fully consistent signed-in envelope may
//                             render the catalog. ready !== true, a missing or
//                             malformed owner identity, a contradictory state,
//                             5xx, malformed JSON and network errors all show
//                             the gate.
//   NO_FABRICATED_ACCESS      Only a closed, fresh authenticated server
//                             projection may display the bundle as available.
//                             Failures and absent grants remain unverified.
//   NAVIGATION_NOT_GRANT      A link navigates to a product screen; it grants
//                             nothing. Each product keeps its own access check.
//                             Only an already supported destination is linked.
//   B66_SEPARATE              B66 is a different brand with its own customer
//                             account screens. It is absent from this catalog
//                             and from every customer-facing string; no B66
//                             member, quote, grade or PC fact is read, shown or
//                             linked here.
//   NO_PERSISTENCE            Nothing is written to browser storage, and no
//                             credential ever enters the URL.
//
// NOT INTEGRATED (known, documented): nothing in the PADIEM Chat app links to
// this page yet, and it is served from the public static mount rather than a
// server-enforced private route. The privacy boundary is therefore (a) the
// gate below, and (b) the fact that this HTML contains no private data at all —
// the catalog is a public allowlist and every owner fact arrives only from the
// authenticated status read. Wiring a server-enforced private route and an
// in-app entry point is follow-up work outside this PR's allowed files.
(() => {
  "use strict";

  const STATUS_ENDPOINT = "/api/auth/status";
  const ACCESS_ENDPOINT = "/api/home/product-access";
  const LOGOUT_ENDPOINT = "/api/auth/logout";
  const READ_TIMEOUT_MS = 10000;

  // Allowlisted PADIEM customer surfaces only. B66 is intentionally absent.
  // `href: null` means there is no supported destination to link to, so the
  // card must render explanatory text instead of a launch action.
  const SERVICES = Object.freeze([
    Object.freeze({ id: "chat", name: "PADIEM Chat", mark: "C", href: "./", entry: "chat" }),
    Object.freeze({ id: "claw", name: "PADIEM Claw", mark: "K", href: "./", entry: "claw" }),
  ]);

  const COPY = Object.freeze({
    ko: {
      title: "PADIEM Home",
      lead: "이 계정으로 사용하는 PADIEM 서비스를 한 곳에서 확인합니다.",
      loading: "로그인 상태를 확인하고 있습니다.",
      servicesTitle: "내 PADIEM 서비스",
      notice: "파디엠챗·클로는 하나의 이용권으로 표시됩니다. 각 실행·파일 권한은 해당 기능에서 별도로 확인합니다.",
      gateTitle: "로그인이 필요합니다",
      gateGuest: "PADIEM Home은 로그인한 사용자만 볼 수 있습니다.",
      gateExpired: "로그인 세션이 만료되었습니다. 다시 로그인해 주세요.",
      gateUnavailable: "로그인 상태를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요.",
      gateAction: "PADIEM Chat에서 로그인",
      accessAvailable: "이용 가능",
      accessUnverified: "확인 불가",
      entryChatBlocked: "이용권 확인 대기",
      accessUnverifiedHelp: "이 홈에서는 제품별 이용 권한을 확인할 수 없습니다.",
      entryChat: "PADIEM Chat 열기",
      entryChatHelp: "PADIEM Chat 화면을 엽니다. 로그인과 계정 메뉴도 그곳에 있습니다.",
      entryClawBlocked: "진입 경로 미연결",
      entryClawHelp: "공통 Chat 화면으로 이동한 뒤 왼쪽 Claw 메뉴를 선택하세요.",
      entryClaw: "Chat에서 Claw 선택",
      entryEngineBlocked: "별도 화면 없음",
      entryEngineHelp: "Engine은 Chat과 Claw 뒤에서 동작하는 서비스입니다.",
      helpSummary: "이용 상태를 확인할 수 없는 이유",
      helpBody1: "Chat·Claw 공동 이용권은 서버 확인 결과에만 따라 표시합니다. 세션이나 이용권 확인이 불가능하면 ‘확인 불가’로 표시합니다.",
      helpBody2: "제품 접근 권한은 각 제품 화면이 스스로 확인합니다. 이 홈은 접근 권한을 부여하지 않습니다.",
      signOut: "로그아웃",
      accountMenu: "계정 메뉴",
      signingOut: "로그아웃하는 중입니다.",
      signOutRefused: "로그아웃을 확인하지 못했습니다. 서버에는 아직 로그인 상태로 남아 있을 수 있습니다.",
    },
    en: {
      title: "PADIEM Home",
      lead: "One place to see the PADIEM services you use with this account.",
      loading: "Checking your sign-in state.",
      servicesTitle: "My PADIEM services",
      notice: "Chat and Claw share a single account bundle. Tool and file permissions remain separately enforced.",
      gateTitle: "Sign-in required",
      gateGuest: "PADIEM Home is only visible to signed-in users.",
      gateExpired: "Your session expired. Please sign in again.",
      gateUnavailable: "The sign-in state cannot be confirmed. Please try again shortly.",
      gateAction: "Sign in from PADIEM Chat",
      accessAvailable: "Available",
      accessUnverified: "Unverified",
      entryChatBlocked: "Access not confirmed",
      accessUnverifiedHelp: "This home cannot confirm per-product access.",
      entryChat: "Open PADIEM Chat",
      entryChatHelp: "Opens the PADIEM Chat screen. Sign-in and the account menu live there.",
      entryClawBlocked: "Entry not linked",
      entryClawHelp: "Opens the shared Chat screen. Select Claw from the sidebar.",
      entryClaw: "Select Claw in Chat",
      entryEngineBlocked: "No separate screen",
      entryEngineHelp: "Engine runs behind Chat and Claw.",
      helpSummary: "Why access status cannot be confirmed",
      helpBody1: "The shared Chat/Claw bundle is shown as available only with server-verified access. If verification fails, access is marked unverified.",
      helpBody2: "Each product screen confirms its own access. This home grants no access.",
      signOut: "Sign out",
      accountMenu: "Account menu",
      signingOut: "Signing out.",
      signOutRefused: "Could not confirm sign-out. You may still be signed in on the server.",
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
  // Suppress every incidental status refresh while the explicit logout POST
  // is unresolved: the previous server cookie may still be valid, but its
  // owner must never reappear during this transition.
  let signingOut = false;
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
    );
  }

  function buildCard(service) {
    const t = locale();
    const verified = view && view.accesses
      && view.accesses[service.entry] === "available";
    const item = element("li", "padiem-home-card");
    item.dataset.service = service.id;

    const mark = element("span", "padiem-home-card-mark", service.mark);
    mark.setAttribute("aria-hidden", "true");
    const name = element("h3", "padiem-home-card-name", service.name);

    const chip = element("span", "padiem-home-card-access",
      verified ? t.accessAvailable : t.accessUnverified);
    chip.dataset.access = verified ? "available" : "unverified";
    chip.title = verified ? t.accessAvailable : t.accessUnverifiedHelp;

    const detail = element("p", "padiem-home-card-help",
      service.entry === "chat" ? t.entryChatHelp
        : service.entry === "claw" ? t.entryClawHelp : t.entryEngineHelp);

    const foot = element("div", "padiem-home-card-foot");
    if (service.href && verified) {
      // Only a destination that already exists may be linked.
      const link = element("a", "padiem-home-card-action",
        service.entry === "claw" ? t.entryClaw : t.entryChat);
      link.href = service.href;
      foot.appendChild(link);
    } else {
      // No supported destination: explain honestly, never render a dead or
      // misleading launch action.
      foot.appendChild(element("span", "padiem-home-card-noaction",
        service.entry === "claw" ? t.entryClawBlocked : t.entryChatBlocked));
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
    if (!view) {
      if (signingOut) refs.status.textContent = t.signingOut;
      return;
    }

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

  // Cancel any in-flight status read and invalidate its epoch, so a response
  // that arrives after a sign-out or account switch cannot repaint stale data.
  function invalidatePending() {
    if (pending) pending.abort();
    pending = null;
    sequence += 1;
  }

  function showGate(reason) {
    signedInName = null;
    view = { kind: "gate", reason };
    paint();
  }

  function showServices(name, accesses) {
    signedInName = name;
    view = { kind: "services", accesses };
    paint();
  }

  function classifyAccess(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)
        || payload.version !== "product-access-projection-v1"
        || !Array.isArray(payload.products) || payload.products.length !== 2) return null;
    const result = Object.create(null);
    const names = { b62: "chat", "b54-padiem-claw": "claw" };
    for (const item of payload.products) {
      if (!item || typeof item !== "object" || Array.isArray(item)) return null;
      if (!Object.prototype.hasOwnProperty.call(names, item.product_id)) return null;
      const name = names[item.product_id];
      if (!name || Object.prototype.hasOwnProperty.call(result, name)
          || !["available", "unavailable", "denied"].includes(item.access)) return null;
      result[name] = item.access === "available"
        && item.reason === "server_allow_confirmed"
        && item.authority === "padiem-chat-claw-bundle-v1"
          ? "available" : "unverified";
    }
    return Object.keys(result).length === 2 ? result : null;
  }

  // The whole access decision. Only a fully consistent signed-in envelope may
  // render the catalog. `/api/auth/status` sets `ready` and a resolved user
  // profile only for an authenticated session, so anything else is closed.
  function classify(payload) {
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "unavailable";
    if (payload.ready !== true) return "unavailable";
    if (payload.authenticated !== true) {
      if (payload.session_state === "expired") return "expired";
      if (payload.session_state === "unavailable") return "unavailable";
      return "guest";
    }
    // A signed-in claim must be a signed_in state carrying a resolved owner
    // identity. A malformed or missing name is not a usable identity.
    if (payload.session_state !== "signed_in") return "unavailable";
    const user = payload.user;
    if (!user || typeof user !== "object" || Array.isArray(user)) return "unavailable";
    if (typeof user.name !== "string") return "unavailable";
    const name = user.name.trim();
    if (!name) return "unavailable";
    return { name: name.slice(0, 80) };
  }

  async function load() {
    if (signingOut) return;
    invalidatePending();
    // Focus, bfcache restoration and auth-state refresh may now belong to a
    // different account. Hide the previous identity/catalog while the server
    // read is pending, even if this GET stalls or returns an error.
    clearPrivate();
    const controller = new AbortController();
    pending = controller;
    const request = sequence;
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
      if (typeof verdict === "string") {
        showGate(verdict);
      } else {
        let accesses = null;
        try {
          const accessResponse = await fetch(ACCESS_ENDPOINT, {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            headers: { Accept: "application/json" },
            signal: controller.signal,
          });
          if (request !== sequence) return;
          if (accessResponse.ok) accesses = classifyAccess(await accessResponse.json());
        } catch {
          // An unverified product is not an allowed product link.
        }
        if (request !== sequence) return;
        showServices(verdict.name, accesses);
      }
    } catch {
      if (request === sequence) showGate("unavailable");
    } finally {
      window.clearTimeout(timer);
      if (pending === controller) pending = null;
    }
  }

  async function signOut() {
    if (signingOut) return;
    signingOut = true;
    // Clear the previous owner's identity and catalog BEFORE the request, so a
    // slow or unresolved logout cannot leave stale data on screen.
    invalidatePending();
    clearPrivate();
    refs.status.textContent = locale().signingOut;
    refs.signOut.disabled = true;
    let unconfirmed = false;
    try {
      const response = await fetch(LOGOUT_ENDPOINT, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      unconfirmed = !response.ok;
    } catch {
      unconfirmed = true;
    } finally {
      signingOut = false;
      refs.signOut.disabled = false;
    }
    // Never claim the session was revoked: re-read the real server state and
    // report it. Only if the server still reports signed-in is the refusal
    // surfaced, and even then the account remains honestly shown.
    await load();
    if (unconfirmed && view && view.kind === "services") {
      refs.status.textContent = locale().signOutRefused;
    }
  }

  refs.signOut.addEventListener("click", () => { void signOut(); });
  for (const event of ["padiem:auth-changed", "padiem:auth-state", "padiem:account-changed"]) {
    window.addEventListener(event, () => {
      // Drop the previous owner's view before the new state is known.
      invalidatePending();
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
