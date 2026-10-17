/* #4139: dedicated PC connection page (LOCAL2).
 *
 * WHAT THIS IS
 *   The single spacious page behind "connect this computer". The DEFAULT
 *   customer path is install-first and never shows manual code entry:
 *     status -> install guide -> launch installed Connector ->
 *     confirm & consent this PC -> server connection status.
 *   Challenge/code display and the operator enroll command live ONLY in the
 *   collapsed admin recovery area below; they are not customer steps.
 *
 * AUTHORITY CONTRACT (must stay true)
 *   STATUS_ONLY_DEFAULT   Opening the page issues exactly one owner-scoped
 *                         GET (devices directory). Nothing else is sent
 *                         without an explicit button click.
 *   CONSENT_FIELDS_ONLY   The grant body is built ONLY by the reviewed
 *                         window.PadiemClawPcEnrollmentConsent API. No
 *                         owner/tenant/session value is ever browser-set.
 *   ISSUE_SHAPE_PINNED    The issue reply is accepted only in the exact
 *                         reviewed shape (code_returned_once, pairing_code,
 *                         challenge.challenge_id, raw_device_credential=false,
 *                         dispatch_authorized=false).
 *   LAUNCH_ONLY           The launch control navigates to the exact reviewed
 *                         OS link "padiem-connector://start" and nothing else:
 *                         no query, no fragment, no payload. It starts the
 *                         installed tray; it is never a pairing claim.
 *   SECRET_HYGIENE        Challenge/code live only in closure memory, never
 *                         in localStorage/URL/logs; cleared on pagehide and
 *                         after a successful verify. Copy requires a click.
 *   NO_FAKE_ONLINE        Consent/code display never claims ONLINE. Only a
 *                         fresh devices-directory read may report connected.
 */
(() => {
  "use strict";

  const GRANT_PATH = "/api/claw/connector/enrollments/consent/grant";
  const ISSUE_PATH = "/api/claw/connector/enrollments/issue";
  const DEVICES_PATH = "/api/claw/local-access/devices";
  const CONSENT_VERSION = "pc-enrollment-consent-v1";
  const NATIVE_LAUNCH_LINK = "padiem-connector://start";
  const MAX_RESPONSE_BYTES = 32768;
  const READ_TIMEOUT_MS = 12000;
  const DEVICE_ID_PATTERN = /^[A-Za-z0-9_.:-]{1,128}$/;

  const COPY = Object.freeze({
    ko: {
      eyebrow: "PADIEM CLAW · PC 연결",
      title: "컴퓨터 연결하기",
      close: "닫기",
      chipChecking: "상태 확인 중",
      chipNone: "미연결",
      chipReady: "연결됨",
      chipAttention: "확인 필요",
      pcUnknown: "이 컴퓨터",
      stepInstall: "설치 안내",
      stepConsent: "확인·동의",
      stepVerify: "연결 확인",
      statusTitle: "내 PC 상태",
      statusChecking: "서버에서 PC 연결 상태를 확인하고 있습니다.",
      statusEmpty: "아직 연결된 컴퓨터가 없습니다. 아래 순서대로 연결해 주세요.",
      statusFound: "승인된 컴퓨터가 있습니다. 실제 작업은 별도 승인이 필요합니다.",
      statusFailed: "연결 상태를 확인하지 못했습니다. 다시 시도해 주세요.",
      login: "로그인한 뒤에 연결할 수 있습니다.",
      installTitle: "최초 설치 안내",
      installBody: "연결하려면 Windows PC에 PADIEM Connector가 설치되어 있어야 합니다. 설치가 끝나면 자동으로 실행되고, 이미 등록된 PC는 다시 연결됩니다.",
      installNote: "설치 파일은 별도 안내로 받으세요. 설치가 이미 끝났다면 아래 버튼으로 커넥터를 실행하세요.",
      launch: "설치된 커넥터 실행",
      launched: "커넥터 실행을 요청했습니다. 실제 연결 상태는 서버에서 확인됩니다.",
      consentTitle: "해당 PC 확인·동의",
      consentBody: "이 PC를 Padiem Claw에 연결합니다. 서버가 이 PC의 연결 상태를 확인하고, 승인된 작업 요청을 이 PC로 전달할 수 있게 됩니다.",
      allowRead: "연결 상태 확인과 승인된 작업 요청 전달",
      denyFiles: "파일 읽기·수정은 이 동의만으로 허용되지 않음",
      denyRun: "프로그램 실행·화면 제어는 별도 P01 승인 필요",
      ack: "위 내용을 확인했고, 이 PC를 연결하는 데 동의합니다.",
      grant: "동의하고 등록",
      granting: "동의를 저장하는 중입니다.",
      granted: "동의가 저장되었습니다. 아래 관리자 등록·복구에서 등록을 이어가세요.",
      grantFailed: "동의를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      notReady: "등록 서비스가 아직 준비되지 않았습니다.",
      targetRequired: "연결할 PC가 확인되지 않았습니다.",
      adminTitle: "관리자 등록·복구",
      adminBody: "일반 설치 흐름에서는 필요 없습니다. 등록 코드가 필요한 경우에만 펼치세요.",
      codeTitle: "일회용 등록 코드",
      codeBody: "아래 두 값을 PC에 입력하세요. 이 화면을 벗어나면 사라집니다.",
      challengeLabel: "Challenge ID",
      codeLabel: "등록 코드",
      issue: "등록 코드 발급",
      issuing: "등록 코드를 발급하는 중입니다.",
      issued: "등록 코드가 발급되었습니다.",
      issueFailed: "등록 코드 발급에 실패했습니다.",
      copy: "복사",
      copied: "복사했습니다.",
      enterBody: "Windows PC에서 아래 명령을 실행한 뒤, 물어보는 입력창에 등록 코드를 입력하세요.",
      verifyTitle: "서버 연결 상태",
      verifyBody: "등록이 끝났으면 서버에서 상태를 확인하세요. 온라인 표시는 서버 확인 후에만 바뀝니다.",
      verify: "서버에서 상태 확인",
      verifying: "서버 등록 상태를 조회하고 있습니다.",
      verified: "서버에서 이 PC의 연결을 확인했습니다.",
      offline: "PC 등록 기록은 확인됐지만 현재 오프라인입니다.",
      missing: "아직 이 PC의 서버 등록 기록이 없습니다. 동의 후 관리자 등록·복구에서 코드를 발급받아 PC에 입력하세요.",
    },
    en: {
      eyebrow: "PADIEM CLAW · PC CONNECTION",
      title: "Connect this computer",
      close: "Close",
      chipChecking: "Checking",
      chipNone: "Not connected",
      chipReady: "Connected",
      chipAttention: "Needs attention",
      pcUnknown: "This computer",
      stepInstall: "Install",
      stepConsent: "Confirm",
      stepVerify: "Verify",
      statusTitle: "My PC status",
      statusChecking: "Checking your PC connection with the server.",
      statusEmpty: "No computers connected yet. Follow the steps below.",
      statusFound: "Approved computers exist. Real work still needs approval.",
      statusFailed: "Could not verify the connection. Please retry.",
      login: "Sign in before connecting.",
      installTitle: "First-time install guide",
      installBody: "This Windows PC needs PADIEM Connector installed. After install it starts automatically, and an enrolled PC reconnects.",
      installNote: "Get the installer through its separate notice. If already installed, launch it below.",
      launch: "Launch installed Connector",
      launched: "Connector launch requested. The real state is confirmed on the server.",
      consentTitle: "Confirm and consent this PC",
      consentBody: "Connect this PC to Padiem Claw. The server may confirm this PC's connection state and deliver approved task requests to it.",
      allowRead: "Connection-state checks and approved request delivery",
      denyFiles: "Reading files is not permitted by this consent alone",
      denyRun: "Running programs needs a separate P01 approval",
      ack: "I have read the above and agree to connect this computer.",
      grant: "Agree and enroll",
      granting: "Saving your consent.",
      granted: "Consent stored. Continue in admin enrollment & recovery below.",
      grantFailed: "Consent could not be stored. Please retry shortly.",
      notReady: "Enrollment service is not ready yet.",
      targetRequired: "The computer to enroll is unconfirmed.",
      adminTitle: "Admin enrollment & recovery",
      adminBody: "Not needed for the normal install flow. Expand only when an enrollment code is required.",
      codeTitle: "One-time enrollment code",
      codeBody: "Enter these two values on the PC. They vanish off this screen.",
      challengeLabel: "Challenge ID",
      codeLabel: "Enrollment code",
      issue: "Issue enrollment code",
      issuing: "Issuing the enrollment code.",
      issued: "Enrollment code issued.",
      issueFailed: "Could not issue the enrollment code.",
      copy: "Copy",
      copied: "Copied.",
      enterBody: "On the Windows PC, run the command below, then type the code at its prompt.",
      verifyTitle: "Server connection state",
      verifyBody: "After enrolling, confirm the state on the server. Online appears only after server confirmation.",
      verify: "Check server status",
      verifying: "Reading the server enrollment state.",
      verified: "The server confirmed this PC connection.",
      offline: "Enrollment is on record but the PC is offline.",
      missing: "No server enrollment record for this PC yet. After consent, issue a code in admin enrollment & recovery and enter it on the PC.",
    },
  });

  function lang() {
    return document.documentElement.lang === "en" ? COPY.en : COPY.ko;
  }
  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (typeof text === "string") node.textContent = text;
    return node;
  }
  function isClaw() {
    const shell = document.querySelector(".app-shell");
    return !!shell && shell.getAttribute("data-state") === "claw";
  }
  function consentApi() {
    const api = window.PadiemClawPcEnrollmentConsent;
    return api && typeof api === "object" ? api : null;
  }
  function consentPort() {
    const port = window.__padiemPcEnrollmentConsentPort;
    return port && typeof port === "object" ? port : null;
  }
  function projector() {
    const fn = window.PadiemClawLocalHandoff &&
      window.PadiemClawLocalHandoff.deriveDeviceDirectory;
    return typeof fn === "function" ? fn : null;
  }

  async function readJson(path, payload) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), READ_TIMEOUT_MS);
    try {
      const response = await fetch(path, {
        method: payload === undefined ? "GET" : "POST",
        mode: "same-origin",
        credentials: "same-origin",
        redirect: "error",
        referrerPolicy: "no-referrer",
        cache: "no-store",
        headers: payload === undefined
          ? { Accept: "application/json" }
          : { "Content-Type": "application/json", Accept: "application/json" },
        body: payload === undefined ? undefined : JSON.stringify(payload),
        signal: controller.signal,
      });
      const raw = await response.text();
      if (raw.length > MAX_RESPONSE_BYTES) throw new Error("oversize");
      return { status: response.status, payload: JSON.parse(raw) };
    } finally {
      window.clearTimeout(timer);
    }
  }

  function build() {
    const dialog = el("dialog", "claw-connection-page");
    dialog.id = "clawConnectionPage";
    const sheet = el("div", "claw-connection-sheet");

    const head = el("div", "claw-connection-head");
    const heading = el("div", "claw-connection-heading");
    const kicker = el("p", "claw-connection-kicker");
    const title = el("h2", "claw-connection-title");
    heading.append(kicker, title);
    const close = el("button", "claw-connection-close");
    close.type = "button";
    head.append(heading, close);

    const statusRow = el("div", "claw-connection-statusrow");
    const chip = el("span", "claw-connection-chip");
    chip.dataset.state = "checking";
    const pcName = el("span", "claw-connection-pcname");
    statusRow.append(chip, pcName);

    const steps = el("ol", "claw-connection-steps");
    const stepKeys = ["stepInstall", "stepConsent", "stepVerify"];
    const stepItems = stepKeys.map((key, index) => {
      const li = el("li", null);
      const n = el("span", "n", String(index + 1));
      const label = el("span", null);
      label.dataset.stepLabel = key;
      li.append(n, label);
      steps.append(li);
      return li;
    });

    const body = el("div", "claw-connection-body");

    const statusCard = el("section", "claw-connection-card");
    const statusTitle = el("h3", null);
    const statusText = el("p", "claw-connection-status");
    statusText.setAttribute("role", "status");
    statusText.setAttribute("aria-live", "polite");
    statusCard.append(statusTitle, statusText);

    const installCard = el("section", "claw-connection-card");
    const installTitle = el("h3", null);
    const installBody = el("p", null);
    const installNote = el("p", null);
    const installActions = el("div", "claw-connection-actions");
    const launch = el("button", "claw-connection-secondary");
    launch.type = "button";
    installActions.append(launch);
    const launchStatus = el("p", "claw-connection-status");
    launchStatus.setAttribute("role", "status");
    launchStatus.setAttribute("aria-live", "polite");
    installCard.append(installTitle, installBody, installNote, installActions, launchStatus);

    const consentCard = el("section", "claw-connection-card");
    const consentTitle = el("h3", null);
    const consentBody = el("p", null);
    const allow = el("ul", "claw-connection-allow");
    const ackRow = el("div", "claw-connection-ack");
    const ack = el("input", null);
    ack.type = "checkbox";
    ack.id = "clawConnectionAck";
    ack.checked = false;
    const ackLabel = el("label", null);
    ackLabel.htmlFor = "clawConnectionAck";
    ackRow.append(ack, ackLabel);
    const consentActions = el("div", "claw-connection-actions");
    const grant = el("button", "claw-connection-primary");
    grant.type = "button";
    grant.disabled = true;
    consentActions.append(grant);
    const consentStatus = el("p", "claw-connection-status");
    consentStatus.setAttribute("role", "status");
    consentStatus.setAttribute("aria-live", "polite");
    consentCard.append(consentTitle, consentBody, allow, ackRow, consentActions, consentStatus);

    const verifyCard = el("section", "claw-connection-card");
    const verifyTitle = el("h3", null);
    const verifyBody = el("p", null);
    const verifyActions = el("div", "claw-connection-actions");
    const verifyBtn = el("button", "claw-connection-primary");
    verifyBtn.type = "button";
    verifyActions.append(verifyBtn);
    const verifyStatus = el("p", "claw-connection-status");
    verifyStatus.setAttribute("role", "status");
    verifyStatus.setAttribute("aria-live", "polite");
    verifyCard.append(verifyTitle, verifyBody, verifyActions, verifyStatus);

    const admin = el("details", "claw-connection-admin");
    const adminSummary = el("summary", "claw-connection-admin-summary");
    const adminInner = el("div", "claw-connection-admin-inner");
    const adminBody = el("p", null);
    const codeTitle = el("h3", null);
    const codeBody = el("p", null);
    const codeBox = el("dl", "claw-connection-codebox");
    codeBox.hidden = true;
    const challengeDt = el("dt", null);
    const challengeDd = el("dd", null);
    const codeDt = el("dt", null);
    const codeDd = el("dd", null);
    codeBox.append(challengeDt, challengeDd, codeDt, codeDd);
    const codeActions = el("div", "claw-connection-actions");
    const issue = el("button", "claw-connection-primary");
    issue.type = "button";
    issue.disabled = true;
    const copyCode = el("button", "claw-connection-secondary");
    copyCode.type = "button";
    copyCode.hidden = true;
    codeActions.append(issue, copyCode);
    const codeStatus = el("p", "claw-connection-status");
    codeStatus.setAttribute("role", "status");
    codeStatus.setAttribute("aria-live", "polite");
    const enterBody = el("p", null);
    const cmd = el("pre", "claw-connection-cmd");
    cmd.hidden = true;
    adminInner.append(adminBody, codeTitle, codeBody, codeBox, codeActions, codeStatus, enterBody, cmd);
    admin.append(adminSummary, adminInner);

    body.append(statusCard, installCard, consentCard, verifyCard, admin);
    sheet.append(head, statusRow, steps, body);
    dialog.append(sheet);
    document.body.append(dialog);
    return {
      dialog, kicker, title, close, chip, pcName, stepItems,
      statusTitle, statusText,
      installTitle, installBody, installNote, launch, launchStatus,
      consentTitle, consentBody, allow, ack, ackLabel, grant, consentStatus,
      admin, adminSummary, adminBody,
      codeTitle, codeBody, codeBox, challengeDt, challengeDd,
      codeDt, codeDd, issue, copyCode, codeStatus, enterBody, cmd,
      verifyTitle, verifyBody, verifyBtn, verifyStatus,
    };
  }

  function install() {
    if (!document.getElementById("clawWorkspace")) return;
    if (document.getElementById("clawConnectionPage")) return;
    const ui = build();
    const t = () => lang();

    let generation = 0;
    let source = null;
    let targetDeviceId = null;
    let grantedDeviceId = null;
    let challengeId = null;
    let pairingCode = null;
    let busy = false;

    function translate() {
      const c = t();
      ui.kicker.textContent = c.eyebrow;
      ui.title.textContent = c.title;
      ui.close.textContent = c.close;
      ui.close.setAttribute("aria-label", c.close);
      const labels = ["stepInstall", "stepConsent", "stepVerify"];
      ui.stepItems.forEach((li, index) => {
        li.querySelector("[data-step-label]").textContent = c[labels[index]];
      });
      ui.statusTitle.textContent = c.statusTitle;
      ui.installTitle.textContent = c.installTitle;
      ui.installBody.textContent = c.installBody;
      ui.installNote.textContent = c.installNote;
      ui.launch.textContent = c.launch;
      ui.consentTitle.textContent = c.consentTitle;
      ui.consentBody.textContent = c.consentBody;
      ui.allow.replaceChildren();
      const items = [
        { ok: true, text: c.allowRead },
        { ok: false, text: c.denyFiles },
        { ok: false, text: c.denyRun },
      ];
      for (const item of items) {
        const li = el("li", null, item.text);
        li.dataset.ok = String(item.ok);
        ui.allow.append(li);
      }
      ui.ackLabel.textContent = c.ack;
      ui.grant.textContent = c.grant;
      ui.adminSummary.textContent = c.adminTitle;
      ui.adminBody.textContent = c.adminBody;
      ui.codeTitle.textContent = c.codeTitle;
      ui.codeBody.textContent = c.codeBody;
      ui.challengeDt.textContent = c.challengeLabel;
      ui.codeDt.textContent = c.codeLabel;
      ui.issue.textContent = c.issue;
      ui.copyCode.textContent = c.copy;
      ui.enterBody.textContent = c.enterBody;
      ui.verifyTitle.textContent = c.verifyTitle;
      ui.verifyBody.textContent = c.verifyBody;
      ui.verifyBtn.textContent = c.verify;
    }

    function setStep(active) {
      ui.stepItems.forEach((li, index) => {
        li.dataset.done = String(index < active);
        if (index === active) li.setAttribute("aria-current", "step");
        else li.removeAttribute("aria-current");
      });
    }

    function setChip(state, text) {
      ui.chip.dataset.state = state;
      ui.chip.textContent = text;
    }

    function clearSecrets() {
      challengeId = null;
      pairingCode = null;
      ui.codeBox.hidden = true;
      ui.challengeDd.textContent = "";
      ui.codeDd.textContent = "";
      ui.cmd.hidden = true;
      ui.cmd.textContent = "";
      ui.copyCode.hidden = true;
    }

    function reset() {
      generation += 1;
      targetDeviceId = null;
      grantedDeviceId = null;
      busy = false;
      ui.ack.checked = false;
      ui.grant.disabled = true;
      ui.issue.disabled = true;
      ui.launchStatus.textContent = "";
      clearSecrets();
      setStep(0);
    }

    async function loadStatus() {
      const c = t();
      setChip("checking", c.chipChecking);
      ui.statusText.textContent = c.statusChecking;
      const request = generation;
      let data = null;
      try {
        const reply = await readJson(DEVICES_PATH);
        if (request !== generation) return;
        if (reply.status === 401 || reply.status === 403) {
          ui.statusText.textContent = c.login;
          setChip("attention", c.chipAttention);
          return;
        }
        if (reply.status !== 200) throw new Error("unavailable");
        data = reply.payload;
      } catch {
        if (request !== generation) return;
        ui.statusText.textContent = c.statusFailed;
        setChip("attention", c.chipAttention);
        return;
      }
      if (data?.ok !== true || data?.available !== true ||
          data?.ownerScoped !== true || !Array.isArray(data.devices)) {
        ui.statusText.textContent = c.statusFailed;
        setChip("attention", c.chipAttention);
        return;
      }
      const project = projector();
      const directory = project ? project(data, null) : null;
      const devices = (directory && directory.available
        ? directory.devices : data.devices) || [];
      const usable = devices.filter((d) => d && (d.usable || d.online) && !d.revoked);
      if (usable.length > 0) {
        const first = usable[0];
        targetDeviceId = first.deviceId || first.device_id || null;
        ui.pcName.textContent = first.deviceName || first.device_name || targetDeviceId || c.pcUnknown;
        ui.statusText.textContent = c.statusFound;
        setChip("ready", c.chipReady);
      } else {
        targetDeviceId = null;
        ui.pcName.textContent = c.pcUnknown;
        ui.statusText.textContent = c.statusEmpty;
        setChip("none", c.chipNone);
      }
      syncConsent();
    }

    function describeTarget() {
      const port = consentPort();
      if (port && typeof port.describeTarget === "function") {
        try {
          const descriptor = port.describeTarget();
          if (descriptor && typeof descriptor === "object") return descriptor;
        } catch { /* fall through to directory target */ }
      }
      if (typeof targetDeviceId === "string" && DEVICE_ID_PATTERN.test(targetDeviceId)) {
        return { deviceId: targetDeviceId, featureActivated: true, productId: "b54-padiem-claw" };
      }
      return null;
    }

    function syncConsent() {
      const c = t();
      const api = consentApi();
      if (!api) {
        ui.consentStatus.textContent = c.notReady;
        ui.grant.disabled = true;
        return;
      }
      const descriptor = describeTarget();
      const readiness = api.consentReadiness({
        deviceId: descriptor ? descriptor.deviceId : undefined,
        productId: descriptor ? descriptor.productId : undefined,
        featureActivated: descriptor ? descriptor.featureActivated : undefined,
        acknowledged: ui.ack.checked === true,
      });
      if (grantedDeviceId) {
        ui.consentStatus.textContent = c.granted;
        ui.grant.disabled = true;
        return;
      }
      ui.grant.disabled = busy || readiness.ready !== true;
      if (!busy) {
        ui.consentStatus.textContent = readiness.ready === true ? "" : (
          readiness.blocked === "consent_target_unknown" ? c.targetRequired :
          readiness.blocked === "consent_feature_not_active" ? c.notReady : ""
        );
      }
    }

    function launchConnector() {
      const c = t();
      try {
        window.location.href = NATIVE_LAUNCH_LINK;
      } catch { /* OS handler absent: status stays server-truthful */ }
      ui.launchStatus.textContent = c.launched;
    }

    async function submitConsent() {
      const c = t();
      const api = consentApi();
      const port = consentPort();
      if (busy || grantedDeviceId || !api || !port || typeof port.grantConsent !== "function") {
        ui.consentStatus.textContent = c.notReady;
        return;
      }
      const descriptor = describeTarget();
      const readiness = api.consentReadiness({
        deviceId: descriptor ? descriptor.deviceId : undefined,
        productId: descriptor ? descriptor.productId : undefined,
        featureActivated: descriptor ? descriptor.featureActivated : undefined,
        acknowledged: ui.ack.checked === true,
      });
      if (readiness.ready !== true) return;
      const body = api.buildGrantBody(descriptor.deviceId);
      if (!body) return;
      const request = generation;
      busy = true;
      ui.grant.disabled = true;
      ui.consentStatus.textContent = c.granting;
      let result = null;
      try {
        result = await port.grantConsent(body);
      } catch {
        result = null;
      }
      if (request !== generation) return;
      busy = false;
      const projection = api.projectGrantReceipt(result, descriptor.deviceId);
      if (projection.accepted) {
        grantedDeviceId = descriptor.deviceId;
        ui.consentStatus.textContent = c.granted;
        ui.issue.disabled = false;
        setStep(1);
        return;
      }
      ui.consentStatus.textContent = c.grantFailed;
      ui.grant.disabled = false;
    }

    async function submitIssue() {
      const c = t();
      if (busy || !grantedDeviceId || ui.ack.checked !== true) return;
      const request = generation;
      busy = true;
      ui.issue.disabled = true;
      ui.codeStatus.textContent = c.issuing;
      try {
        const reply = await readJson(ISSUE_PATH, { device_id: grantedDeviceId });
        if (request !== generation) return;
        const out = reply.payload && reply.payload.enrollment;
        if (!reply.payload || reply.payload.ok !== true ||
            out?.code_returned_once !== true ||
            typeof out.pairing_code !== "string" ||
            typeof out.challenge?.challenge_id !== "string" ||
            out.raw_device_credential !== false ||
            out.dispatch_authorized !== false) {
          throw new Error("invalid issue receipt");
        }
        challengeId = out.challenge.challenge_id;
        pairingCode = out.pairing_code;
        ui.challengeDd.textContent = challengeId;
        ui.codeDd.textContent = pairingCode;
        ui.codeBox.hidden = false;
        ui.copyCode.hidden = false;
        ui.codeStatus.textContent = c.issued;
        ui.cmd.textContent = "padiem-connector enroll " + challengeId + " --operator-wss-review";
        ui.cmd.hidden = false;
        setStep(2);
      } catch {
        if (request !== generation) return;
        clearSecrets();
        ui.codeStatus.textContent = c.issueFailed;
      } finally {
        if (request === generation) {
          busy = false;
          ui.issue.disabled = false;
        }
      }
    }

    async function copyCode() {
      const c = t();
      if (!pairingCode) return;
      try {
        await navigator.clipboard.writeText(challengeId + "\n" + pairingCode);
        ui.codeStatus.textContent = c.copied;
      } catch { /* clipboard unavailable: user reads on screen */ }
    }

    async function submitVerify() {
      const c = t();
      if (busy) return;
      const request = generation;
      busy = true;
      ui.verifyBtn.disabled = true;
      ui.verifyStatus.textContent = c.verifying;
      try {
        const reply = await readJson(DEVICES_PATH);
        if (request !== generation) return;
        const data = reply.payload;
        if (!reply || reply.status !== 200 || !data || data.ok !== true ||
            data.available !== true || !Array.isArray(data.devices)) {
          throw new Error("unavailable");
        }
        const matchId = grantedDeviceId;
        const matched = matchId ? data.devices.find(
          (item) => item && (item.deviceId === matchId || item.device_id === matchId),
        ) : null;
        const anyUsable = data.devices.some(
          (item) => item && (item.usable || item.online) && !item.revoked,
        );
        if (matched && ((matched.state === "CONNECTED" && matched.usable === true ||
            matched.online === true) && matched.revoked !== true)) {
          ui.verifyStatus.textContent = c.verified;
          setChip("ready", c.chipReady);
          clearSecrets();
        } else if (matched) {
          ui.verifyStatus.textContent = c.offline;
        } else if (anyUsable) {
          ui.verifyStatus.textContent = c.statusFound;
          setChip("ready", c.chipReady);
        } else {
          ui.verifyStatus.textContent = c.missing;
        }
      } catch {
        if (request !== generation) return;
        ui.verifyStatus.textContent = c.statusFailed;
      } finally {
        if (request === generation) {
          busy = false;
          ui.verifyBtn.disabled = false;
        }
      }
    }

    function open(origin) {
      if (!isClaw()) return;
      source = origin || null;
      const connectors = document.getElementById("connectorsDialog");
      if (connectors && connectors.open) connectors.close();
      reset();
      translate();
      if (typeof ui.dialog.showModal === "function" && !ui.dialog.open) {
        ui.dialog.showModal();
      }
      setChip("checking", t().chipChecking);
      ui.pcName.textContent = t().pcUnknown;
      void loadStatus();
    }

    function close() {
      if (ui.dialog.open) ui.dialog.close();
    }

    ui.close.addEventListener("click", close);
    ui.dialog.addEventListener("click", (event) => {
      if (event.target === ui.dialog) close();
    });
    ui.dialog.addEventListener("close", () => {
      clearSecrets();
      if (source && typeof source.focus === "function") {
        try { source.focus({ preventScroll: true }); } catch { /* noop */ }
      }
      source = null;
    });
    ui.launch.addEventListener("click", launchConnector);
    ui.ack.addEventListener("change", () => { if (!busy) syncConsent(); });
    ui.grant.addEventListener("click", () => { void submitConsent(); });
    ui.issue.addEventListener("click", () => { void submitIssue(); });
    ui.copyCode.addEventListener("click", () => { void copyCode(); });
    ui.verifyBtn.addEventListener("click", () => { void submitVerify(); });
    document.addEventListener("pagehide", clearSecrets);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && ui.dialog.open && !busy) void loadStatus();
    });
    for (const evt of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
      window.addEventListener(evt, () => {
        if (ui.dialog.open) {
          reset();
          translate();
          void loadStatus();
        }
      });
    }
    new MutationObserver(() => {
      if (!isClaw() && ui.dialog.open) close();
    }).observe(document.querySelector(".app-shell"), {
      attributes: true, attributeFilter: ["data-state"],
    });
    new MutationObserver(() => {
      if (ui.dialog.open) translate();
    }).observe(document.documentElement, {
      attributes: true, attributeFilter: ["lang"],
    });

    // Capture the two PC entry buttons BEFORE the legacy small-card guide.
    // This script loads before claw-connection-guide.js, so the legacy dialog
    // never opens for PC: the full connection page opens instead. Other
    // services keep their existing guide behavior untouched.
    document.addEventListener("click", (event) => {
      const statusButton = event.target?.closest?.("#clawComputerDeviceStatusButton");
      const homeCard = event.target?.closest?.('[data-claw-connection="pc"]');
      const hit = statusButton || homeCard;
      if (!hit || !isClaw()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      open(hit);
    }, true);

    window.PadiemClawConnectionPage = Object.freeze({
      open,
      close,
      GRANT_PATH,
      ISSUE_PATH,
      DEVICES_PATH,
      CONSENT_VERSION,
      NATIVE_LAUNCH_LINK,
    });
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
