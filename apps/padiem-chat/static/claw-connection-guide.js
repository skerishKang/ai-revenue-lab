/* Small, shared-shell connection guidance. Does not mint connection state.
 * Capture only the Claw home status switch; existing Connectors and verified
 * disconnect handlers remain the authority for real operations.
 */
(() => {
  "use strict";
  const shell = document.querySelector(".app-shell");
  const dialog = document.getElementById("clawConnectionGuide");
  const title = document.getElementById("clawConnectionGuideTitle");
  const description = document.getElementById("clawConnectionGuideDescription");
  const hint = document.getElementById("clawConnectionGuideHint");
  const action = document.getElementById("clawConnectionGuideAction");
  const eyebrow = document.getElementById("clawConnectionGuideEyebrow");
  if (!shell || !dialog || !title || !description || !hint || !action || !eyebrow) return;

  const ids = ["pc", "drive", "github"];
  const cardIds = {pc:"clawComputerWorkspace", drive:"clawDriveWorkspace", github:"clawGithubWorkspace"};
  const labels = {pc:"Windows PC", drive:"Google Drive", github:"GitHub"};
  const isEnglish = () => document.documentElement.lang === "en";
  const tr = (ko, en) => isEnglish() ? en : ko;
  const home = () => shell.dataset.state === "claw" &&
    document.getElementById("clawWorkspace")?.dataset.view === "general";
  const signedIn = () => document.querySelector(".sidebar-account")?.dataset.accountState === "signed_in";
  let source = null, intent = "manage", bypass = false;

  function details(id, state) {
    if (!signedIn()) return {
      headline: tr("먼저 PADIEM에 로그인해 주세요", "Sign in to PADIEM first"),
      copy: tr("한 번 로그인하면 CLAW에서 연결을 관리할 수 있습니다.",
               "Your PADIEM account manages your CLAW connections."),
      foot: tr("외부 계정이나 PC 프로그램에 별도 PADIEM 로그인이 필요하지 않습니다.",
               "No second PADIEM sign-in is needed inside the connector."),
      button: tr("PADIEM 로그인", "Sign in"), intent: "login"
    };
    if (state === "unknown" && id === "pc") return {
      headline: tr("컴퓨터 연결 상태를 확인해 주세요", "Check this computer"),
      copy: tr("서버에서 PC 상태를 확인하지 못했습니다. 아직 설치 전이라면 Connector를 설치해 주세요.",
               "The PC status is unavailable. Install Connector if you have not already."),
      foot: tr("설치 후 자동 실행·연결됩니다. 이미 설치했다면 실행 상태를 확인해 주세요.",
               "It starts and connects automatically after install. If installed, check whether it is running."),
      button: tr("설치·연결 안내", "Installation & connection"), intent: "manage"
    };
    if (state === "unknown") return {
      headline: tr("연결 상태를 확인할 수 없어요", "Connection status unavailable"),
      copy: tr("아직 서버에서 연결 여부를 확인하지 못했습니다. 연결 설정에서 상태를 확인해 주세요.",
               "The server has not confirmed this connection. Check its settings."),
      foot: tr("확인 전에는 임의로 ON이나 OFF로 바꾸지 않습니다.",
               "ON and OFF are not assumed without verification."),
      button: tr("연결 설정 보기", "View connection settings"), intent: "manage"
    };
    if (id === "github" && state === "off" &&
        document.querySelector('[data-claw-connection="github"]')?.dataset.connectionLinked === "true") return {
      headline: tr("GitHub가 일시 중지되어 있어요", "GitHub is paused"),
      copy: tr("연결 정보는 유지됩니다. 다시 켜면 기존 GitHub 계정으로 사용합니다.",
               "Your authorization is retained. Resume without signing in again."),
      foot: tr("실제 GitHub 접근이 확인된 후 ON으로 표시됩니다.",
               "ON appears only after real GitHub access is verified."),
      button: tr("GitHub 다시 켜기", "Resume GitHub"), intent: "resume-github"
    };
    if (state === "on" && id === "github") return {
      headline: tr("GitHub가 연결되어 있어요", "GitHub is connected"),
      copy: tr("사용을 잠시 중지해도 GitHub 인증 정보는 유지됩니다.",
               "Pause GitHub access without removing authorization."),
      foot: tr("연결 자체를 삭제하는 기능은 별도 연결 관리에서 제공됩니다.",
               "Removing account authorization is a separate connection setting."),
      button: tr("GitHub 일시 중지", "Pause GitHub"), intent: "pause-github"
    };
    if (state === "on") return id === "drive" ? {
      headline: tr("Google Drive가 연결되어 있어요", "Google Drive is connected"),
      copy: tr("드라이브 연결은 유지됩니다. 계정 연결 자체를 삭제하려면 커넥터 관리에서 선택해 주세요.",
               "Your Drive link is retained. Use Connectors to remove account authorization."),
      foot: tr("일시 중지는 아직 지원하지 않습니다. OFF를 연결 삭제처럼 처리하지 않습니다.",
               "Temporary Drive pause is not yet supported; OFF must not revoke the link."),
      button: tr("연결 관리", "Manage connection"), intent: "manage"
    } : {
      headline: tr(labels[id] + " 연결됨", labels[id] + " connected"),
      copy: tr(id === "pc" ?
        "설치된 Connector는 기본적으로 자동 실행하고 다시 연결합니다." :
        "GitHub 연결이 확인됐습니다. 연결 관리에서 권한을 확인할 수 있습니다.",
        id === "pc" ? "The installed Connector starts and reconnects automatically." :
        "GitHub access is verified. Manage permissions in connection settings."),
      foot: tr("연결을 끄는 기능은 실제 서버 지원 상태에 따라 제공됩니다.",
               "Pause depends on the available server controls."),
      button: tr("연결 관리", "Manage connection"), intent: "manage"
    };
    if (id === "pc") return {
      headline: tr("컴퓨터에 Connector를 설치해 주세요", "Install PADIEM Connector"),
      copy: tr("설치가 끝나면 자동으로 실행되어 CLAW와 연결됩니다.",
               "Once installed, Connector starts and connects to CLAW automatically."),
      foot: tr("별도 로그인이나 '프로그램 켜기' 단계는 필요하지 않습니다. PC가 꺼져 있으면 재연결을 기다립니다.",
               "No extra sign-in or start step. Reconnection resumes when the PC returns."),
      button: tr("설치 안내 보기", "View installation"), intent: "manage"
    };
    if (id === "drive") return {
      headline: tr("Google Drive를 연결해 주세요", "Connect Google Drive"),
      copy: tr("Google 계정으로 로그인하고 드라이브 접근을 승인해 주세요.",
               "Sign in with Google and authorize Drive access."),
      foot: tr("연결이 실제 확인된 후에만 ON으로 바뀝니다.",
               "ON appears only after the connection is verified."),
      button: tr("Google Drive 연결", "Connect Google Drive"), intent: "connect-drive"
    };
    return {
      headline: tr("GitHub를 연결해 주세요", "Connect GitHub"),
      copy: tr("GitHub 계정으로 연결하고 사용할 저장소 접근을 허용해 주세요.",
               "Connect your GitHub account and authorize repository access."),
      foot: tr("저장소는 기본적으로 전체를 선택하며, 원하면 일부만 제한할 수 있습니다. GitHub 로그인 화면에서 연결을 승인해 주세요.",
               "All repositories is the default; you may restrict it at GitHub."),
      button: tr("GitHub 로그인", "Sign in with GitHub"), intent: "connect-github"
    };
  }

  function open(button) {
    const id = button.dataset.clawConnection;
    if (!ids.includes(id) || !home()) return;
    source = button;
    const state = ["on","off","unknown"].includes(button.dataset.connectionState)
      ? button.dataset.connectionState : "unknown";
    const copy = details(id, state);
    eyebrow.textContent = labels[id] + " · " + (state === "unknown" ? tr("상태 확인", "Status") : state.toUpperCase());
    title.textContent = copy.headline;
    description.textContent = copy.copy;
    hint.textContent = copy.foot;
    action.textContent = copy.button;
    const cancel = dialog.querySelector(".claw-connection-guide-cancel");
    if (cancel) cancel.textContent = tr("나중에", "Later");
    intent = copy.intent;
    dialog.dataset.service = id;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
  }

  document.addEventListener("click", event => {
    const button = event.target?.closest?.("[data-claw-connection]");
    if (bypass || !button || !home()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const id = button.dataset.clawConnection;
    const state = button.dataset.connectionState;
    if (signedIn() && id === "pc" && (state === "off" || state === "unknown")) {
      // One authenticated owner gesture enters the existing Claw card flow.
      // Do not turn an unregistered PC into a misleading reinstall dialog.
      document.getElementById(cardIds.pc)?.click();
      return;
    }
    if (signedIn() && state === "off" && id === "drive") {
      document.dispatchEvent(new Event("padiem:drive-quick-connect"));
      return;
    }
    if (signedIn() && id === "github" && ["on","off"].includes(state)) {
      if (state === "off" && button.dataset.connectionLinked !== "true") {
        window.location.assign("/api/connectors/github/start");
        return;
      }
      // Known links toggle pause/resume through their server-authoritative handler.
      bypass = true;
      try { button.click(); } finally { bypass = false; }
      return;
    }
    open(button);
  }, true);

  dialog.querySelector("[data-claw-guide-close]")?.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target === dialog) dialog.close();
  });
  action.addEventListener("click", () => {
    if (!source) return;
    const button = source;
    const id = button.dataset.clawConnection;
    dialog.close();
    if (intent === "pause-github" || intent === "resume-github") {
      // Delegate to the canonical owner-scoped state handler; never fake the switch.
      bypass = true;
      try { button.click(); } finally { bypass = false; }
      return;
    }
    if (intent === "connect-github") {
      window.location.assign("/api/connectors/github/start");
      return;
    }
    if (intent === "login") {
      const login = document.getElementById("loginButton");
      if (login && !login.disabled && !login.hidden) login.click();
      else {
        const auth = document.getElementById("authDialog");
        if (auth && !auth.open && typeof auth.showModal === "function") auth.showModal();
      }
      return;
    }
    if (intent === "connect-drive") {
      // Existing product-owned OAuth ticket flow, only when the canonical
      // workspace projection has offered its real connect control.
      const offered = document.querySelector('[data-google-connector-connect="google-drive"]');
      if (offered && !offered.hidden && !offered.disabled) {
        offered.click();
        return;
      }
    }
    // Otherwise reuse the existing Connectors card, never an invented installer/OAuth URL.
    document.getElementById(cardIds[id])?.click();
  });
  dialog.addEventListener("close", () => { source?.focus({preventScroll:true}); source = null; });
})();
