// #4139 — PC enrollment consent UI (LOCAL1).
//
// WHAT THIS IS
//   The explicit user consent step that CENTRAL's reviewed #4476 consent routes
//   require before a PADIEM Connector PC may be enrolled. It is the missing UI
//   the CENTRAL contract document explicitly defers: "The route methods are NOT
//   mounted ... and there is no new UI/consent checkbox yet ... eventual UI
//   needs explicit consent text + affirmative checkbox and same-origin CSRF."
//
// AUTHORITY CONTRACT (must stay true)
//   CONSENT_AUTHORITY=NO       Enrolling consent is NOT task-execution approval.
//                              This module never grants Broker, device, READ,
//                              WRITE or P01 authority, and never claims ONLINE.
//   NETWORK_WHEN_READY=NO      In the ready state it issues ZERO network calls.
//                              It never issues an HTTP request itself. It can
//                              only reach a verified server port published on
//                              window.__padiemPcEnrollmentConsentPort. With no
//                              port installed (the current production default)
//                              an explicit confirm resolves to an honest
//                              "not ready" state and sends nothing at all.
//   BROWSER_FIELD_AUTHORITY=NO The browser may send only the reviewed consent
//                              fields. owner / tenant / workspace / session /
//                              consent id are never browser-settable.
//   DEFAULT_OFF                The affirmative checkbox starts unchecked and the
//                              confirm control starts disabled.
//   NO_SERVER_HTML             Server strings are never inserted as HTML and no
//                              credential, token or raw error text is rendered.
//
// The reviewed wire contract (from CENTRAL #4476, source-only and unmounted):
//   grant  body == {device_id, confirmed:true, confirmation_version:"pc-enrollment-consent-v1"}
//   revoke body == {consent_id, confirmed:true, confirmation_version:"pc-enrollment-consent-v1"}
//   receipt      == {ok:true, consent:{..., dispatch_authorized:false}}
(() => {
  "use strict";

  const CONSENT_VERSION = "pc-enrollment-consent-v1";
  const GRANT_PATH = "/api/claw/connector/enrollments/consent/grant";
  const REVOKE_PATH = "/api/claw/connector/enrollments/consent/revoke";
  // The one canonical product this consent belongs to. The same server session
  // contract requires product_id === "b54-padiem-claw" (#4476).
  const CONSENT_PRODUCT_ID = "b54-padiem-claw";
  // B66 quote customers keep a separate account and PC-connection authority.
  // A shared email or a shared PC never auto-links the two products.
  const SEPARATE_PRODUCT_PREFIX = "b66";
  const DEVICE_ID_PATTERN = /^[A-Za-z0-9_.:-]{1,128}$/;
  const CONSENT_ID_PATTERN = /^[A-Za-z0-9_.:-]{1,128}$/;

  const COPY = Object.freeze({
    ko: {
      toggle: "내 PC 등록 동의",
      title: "이 컴퓨터를 Padiem에 연결",
      close: "닫기",
      targetLabel: "등록 대상 PC",
      targetUnknown: "아직 선택된 PC가 없습니다",
      serviceLabel: "연결 서비스",
      serviceValue: "Padiem Claw",
      details: "무엇에 동의하는지 자세히 보기",
      allowedTitle: "연결하면 허용되는 것",
      allowedBody: "서버가 이 PC의 연결 상태를 확인하고, 승인된 작업 요청을 이 PC로 전달할 수 있습니다.",
      deniedTitle: "연결해도 허용되지 않는 것",
      deniedBody: "파일 읽기·수정, 프로그램 실행, 화면 제어는 이 동의만으로는 허용되지 않습니다.",
      approvalNote: "파일 읽기·쓰기와 실제 PC 작업 실행에는 작업마다 별도의 P01 승인이 필요합니다.",
      revokeNote: "동의를 철회하면 새 등록과 아직 사용되지 않은 등록 코드가 중단됩니다. 이미 연결된 PC의 연결 해제나 실행 중인 작업의 종료는 별도의 검토된 해제 절차로 처리되며, 이 철회만으로 즉시 끊기지는 않습니다.",
      ackLabel: "위 내용을 확인했고, 이 PC를 Padiem Claw에 연결하는 데 동의합니다.",
      confirm: "동의하고 등록",
      cancel: "취소",
      ready: "동의하려면 아래 확인란을 직접 선택해 주세요.",
      targetRequired: "먼저 등록할 PC를 선택해 주세요. 대상이 확인되지 않으면 진행할 수 없습니다.",
      productUnknown: "연결 대상 제품을 확인할 수 없어 진행할 수 없습니다.",
      productSeparate: "이 서비스의 PC 등록 대상으로 확인되지 않았습니다. 다른 서비스의 PC 등록 권한은 여기에서 사용할 수 없습니다.",
      notReady: "PC 등록 서비스가 아직 준비되지 않았습니다. 지금은 동의를 저장할 수 없습니다.",
      submitting: "동의를 저장하는 중입니다.",
      granted: "동의가 저장되었습니다. 연결 상태는 서버 확인 후 별도로 표시됩니다.",
      grantedNotOnline: "동의 저장은 PC 연결 완료나 온라인 상태를 뜻하지 않습니다.",
      denied: "동의가 거부되었습니다. 다시 시도해 주세요.",
      expired: "동의가 만료되었습니다. 다시 동의해 주세요.",
      revoked: "동의가 철회되었습니다.",
      failed: "동의를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    },
    en: {
      toggle: "PC enrollment consent",
      title: "Connect this computer to Padiem",
      close: "Close",
      targetLabel: "Computer to enroll",
      targetUnknown: "No computer selected yet",
      serviceLabel: "Connecting service",
      serviceValue: "Padiem Claw",
      details: "See exactly what you are agreeing to",
      allowedTitle: "Allowed once connected",
      allowedBody: "The server may confirm this computer's connection state and deliver approved task requests to it.",
      deniedTitle: "Not allowed by connecting",
      deniedBody: "Reading or editing files, running programs and controlling the screen are not permitted by this consent alone.",
      approvalNote: "Reading or writing files and running real PC work each require a separate P01 approval.",
      revokeNote: "Revoking consent stops new enrollment and any outstanding enrollment code. Disconnecting an already connected PC or ending running work is handled by a separate reviewed release path, so this withdrawal alone does not disconnect it immediately.",
      ackLabel: "I have read the above and agree to connect this computer to Padiem Claw.",
      confirm: "Agree and enroll",
      cancel: "Cancel",
      ready: "Select the checkbox below yourself to continue.",
      targetRequired: "Select the computer to enroll first. Progress is blocked while the target is unconfirmed.",
      productUnknown: "The connecting product could not be confirmed, so progress is blocked.",
      productSeparate: "This service cannot confirm the selected PC enrollment. PC permissions for other services cannot be used here.",
      notReady: "PC enrollment service is not ready yet. Consent cannot be stored right now.",
      submitting: "Saving your consent.",
      granted: "Consent stored. Connection state is shown separately after server confirmation.",
      grantedNotOnline: "Storing consent does not mean the PC is connected or online.",
      denied: "Consent was refused. Please try again.",
      expired: "Consent expired. Please agree again.",
      revoked: "Consent was revoked.",
      failed: "Consent could not be stored. Please try again shortly.",
    },
  });

  function isPlainObject(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function locale() {
    const current = window.__padiemLocale &&
      typeof window.__padiemLocale.getCurrent === "function"
        ? window.__padiemLocale.getCurrent()
        : document.documentElement.lang;
    return current === "en" ? COPY.en : COPY.ko;
  }

  function element(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (typeof text === "string") el.textContent = text;
    return el;
  }

  // ---------------------------------------------------------------------------
  // Pure consent contract core (no DOM, no network). Exported for direct tests.
  // ---------------------------------------------------------------------------

  // Exactly the reviewed browser fields. A fresh literal is built every time so
  // no caller-supplied object can smuggle owner/tenant/workspace/session/consent
  // id, a grant, or an approval decision into the request.
  function buildGrantBody(deviceId) {
    if (typeof deviceId !== "string" || !DEVICE_ID_PATTERN.test(deviceId)) return null;
    return Object.freeze({
      device_id: deviceId,
      confirmed: true,
      confirmation_version: CONSENT_VERSION,
    });
  }

  function buildRevokeBody(consentId) {
    if (typeof consentId !== "string" || !CONSENT_ID_PATTERN.test(consentId)) return null;
    return Object.freeze({
      consent_id: consentId,
      confirmed: true,
      confirmation_version: CONSENT_VERSION,
    });
  }

  // A single readiness gate: user acknowledgement AND a verified, active server
  // feature AND a known target AND the canonical product must all hold. Any
  // missing input blocks progress with an honest, specific reason.
  function consentReadiness(state) {
    const s = isPlainObject(state) ? state : {};
    if (s.featureActivated !== true) {
      return Object.freeze({ ready: false, blocked: "consent_feature_not_active" });
    }
    const product = typeof s.productId === "string" ? s.productId : "";
    if (product === "") {
      return Object.freeze({ ready: false, blocked: "consent_product_unknown" });
    }
    if (product !== CONSENT_PRODUCT_ID) {
      // Includes B66 quote accounts: separate product, separate PC authority.
      return Object.freeze({ ready: false, blocked: "consent_separate_product" });
    }
    if (typeof s.deviceId !== "string" || !DEVICE_ID_PATTERN.test(s.deviceId)) {
      return Object.freeze({ ready: false, blocked: "consent_target_unknown" });
    }
    if (s.acknowledged !== true) {
      return Object.freeze({ ready: false, blocked: "consent_not_acknowledged" });
    }
    return Object.freeze({ ready: true, blocked: null });
  }

  // A grant receipt is accepted only when the server explicitly reports that
  // dispatch is NOT authorized and the device matches. `dispatch_authorized`
  // must be the strict boolean false: a receipt that would imply execution
  // authority is refused rather than displayed.
  function projectGrantReceipt(raw, expectedDeviceId) {
    if (!isPlainObject(raw) || raw.ok !== true || !isPlainObject(raw.consent)) {
      return Object.freeze({ accepted: false, reason: "consent_receipt_invalid" });
    }
    const consent = raw.consent;
    if (consent.dispatch_authorized !== false) {
      return Object.freeze({ accepted: false, reason: "consent_authority_escalation" });
    }
    if (typeof expectedDeviceId !== "string" || consent.device_id !== expectedDeviceId) {
      return Object.freeze({ accepted: false, reason: "consent_receipt_mismatch" });
    }
    const consentId = typeof consent.consent_id === "string" &&
      CONSENT_ID_PATTERN.test(consent.consent_id) ? consent.consent_id : null;
    if (consentId === null) {
      // Without a canonical ID the user cannot safely identify/revoke the consent.
      return Object.freeze({ accepted: false, reason: "consent_receipt_invalid" });
    }
    // Consent recorded is NOT "PC online". online stays false by construction.
    return Object.freeze({
      accepted: true,
      state: "GRANTED",
      deviceId: expectedDeviceId,
      consentId,
      dispatchAuthorized: false,
      online: false,
    });
  }

  function projectRevokeReceipt(raw, expectedConsentId) {
    if (!isPlainObject(raw) || raw.ok !== true || !isPlainObject(raw.consent)) {
      return Object.freeze({ accepted: false, reason: "consent_receipt_invalid" });
    }
    const consent = raw.consent;
    if (consent.dispatch_authorized !== false) {
      return Object.freeze({ accepted: false, reason: "consent_authority_escalation" });
    }
    if (typeof expectedConsentId !== "string" || consent.consent_id !== expectedConsentId) {
      return Object.freeze({ accepted: false, reason: "consent_receipt_mismatch" });
    }
    return Object.freeze({
      accepted: true,
      state: "REVOKED",
      consentId: expectedConsentId,
      dispatchAuthorized: false,
      online: false,
    });
  }

  // Map a bounded server refusal to an honest local state. Only reviewed,
  // secret-free codes are recognised; anything else fails closed.
  function consentStateFromError(status, code) {
    if (code === "connector_enrollment_explicit_consent_required") {
      return Object.freeze({ state: "DENIED", retryable: true });
    }
    if (code === "enrollment_consent_withdrawn" || code === "enrollment_consent_required") {
      return Object.freeze({ state: "REVOKED", retryable: true });
    }
    if (code === "enrollment_consent_expired") {
      return Object.freeze({ state: "EXPIRED", retryable: true });
    }
    if (status === 401 || status === 403) {
      return Object.freeze({ state: "DENIED", retryable: false });
    }
    return Object.freeze({ state: "FAILED", retryable: true });
  }

  const api = Object.freeze({
    CONSENT_VERSION,
    GRANT_PATH,
    REVOKE_PATH,
    CONSENT_PRODUCT_ID,
    buildGrantBody,
    buildRevokeBody,
    consentReadiness,
    projectGrantReceipt,
    projectRevokeReceipt,
    consentStateFromError,
  });
  window.PadiemClawPcEnrollmentConsent = api;

  // ---------------------------------------------------------------------------
  // DOM surface. Renders nothing until it can mount inside the Claw workspace.
  // ---------------------------------------------------------------------------

  // The only path to the network. Absent by default (production is unmounted),
  // so the ready state can never emit a request on its own.
  function port() {
    const candidate = window.__padiemPcEnrollmentConsentPort;
    return isPlainObject(candidate) ? candidate : null;
  }

  function describeTarget() {
    const p = port();
    if (!p || typeof p.describeTarget !== "function") return null;
    try {
      const descriptor = p.describeTarget();
      return isPlainObject(descriptor) ? descriptor : null;
    } catch {
      return null;
    }
  }

  function install() {
    const shell = document.querySelector(".app-shell");
    const workspace = document.getElementById("clawWorkspace");
    if (!shell || !workspace) return;

    const root = element("section", "claw-pc-consent");
    root.id = "clawPcEnrollmentConsent";
    root.hidden = true;

    const toggle = element("button", "claw-pc-consent-toggle");
    toggle.id = "clawPcConsentToggle";
    toggle.type = "button";
    toggle.setAttribute("aria-controls", "clawPcConsentPanel");
    toggle.setAttribute("aria-expanded", "false");

    const panel = element("section", "claw-pc-consent-panel");
    panel.id = "clawPcConsentPanel";
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-labelledby", "clawPcConsentTitle");
    panel.hidden = true;

    const head = element("div", "claw-pc-consent-head");
    const title = element("h2", "claw-pc-consent-title", "");
    title.id = "clawPcConsentTitle";
    const close = element("button", "claw-pc-consent-close");
    close.type = "button";
    close.setAttribute("aria-label", "");
    head.append(title, close);

    const summary = element("dl", "claw-pc-consent-summary");
    const targetDt = element("dt", "", "");
    const targetDd = element("dd", "claw-pc-consent-target");
    targetDd.id = "clawPcConsentTarget";
    const serviceDt = element("dt", "", "");
    const serviceDd = element("dd", "claw-pc-consent-service");
    summary.append(targetDt, targetDd, serviceDt, serviceDd);

    const details = element("details", "claw-pc-consent-details");
    const detailsSummary = element("summary", "claw-pc-consent-details-summary", "");
    const allowedTitle = element("h3", "", "");
    const allowedBody = element("p", "", "");
    const deniedTitle = element("h3", "", "");
    const deniedBody = element("p", "", "");
    const approvalNote = element("p", "claw-pc-consent-approval", "");
    const revokeNote = element("p", "claw-pc-consent-revoke", "");
    details.append(detailsSummary, allowedTitle, allowedBody, deniedTitle, deniedBody,
      approvalNote, revokeNote);

    const ackRow = element("div", "claw-pc-consent-ack");
    const ack = element("input", "claw-pc-consent-ack-input");
    ack.id = "clawPcConsentAck";
    ack.type = "checkbox";
    ack.checked = false; // DEFAULT_OFF
    const ackLabel = element("label", "claw-pc-consent-ack-label", "");
    ackLabel.htmlFor = "clawPcConsentAck";
    ackRow.append(ack, ackLabel);

    const status = element("p", "claw-pc-consent-status");
    status.id = "clawPcConsentStatus";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");

    const actions = element("div", "claw-pc-consent-actions");
    const confirm = element("button", "claw-pc-consent-confirm");
    confirm.id = "clawPcConsentConfirm";
    confirm.type = "button";
    confirm.disabled = true;
    const cancel = element("button", "claw-pc-consent-cancel");
    cancel.id = "clawPcConsentCancel";
    cancel.type = "button";
    actions.append(confirm, cancel);

    panel.append(head, summary, details, ackRow, status, actions);
    root.append(toggle, panel);
    workspace.insertBefore(root, workspace.querySelector(".claw-workspace-tagline") || workspace.firstChild);

    let opened = false;
    let submitting = false;
    // A stored consent is terminal for this panel session: the confirm control
    // must never become clickable again for the same acknowledgement.
    let granted = false;
    // Last rendered status key(s), re-rendered on a locale change.
    let lastKeys = ["ready"];
    // Monotonic request generation. Every action that invalidates the current
    // panel state — close, Escape, re-open, account change, leaving Claw —
    // bumps it, so a late async response can never mutate the current screen.
    let generation = 0;

    function isClaw() {
      return shell.getAttribute("data-state") === "claw";
    }

    function invalidate() {
      generation += 1;
    }

    function renderStatus() {
      const t = locale();
      status.textContent = lastKeys.map((key) => t[key] || t.failed).join(" ");
    }

    function setStatus(key, extraKey) {
      lastKeys = extraKey ? [key, extraKey] : [key];
      renderStatus();
    }

    function currentReadiness() {
      const descriptor = describeTarget();
      return consentReadiness({
        deviceId: descriptor ? descriptor.deviceId : undefined,
        productId: descriptor ? descriptor.productId : undefined,
        featureActivated: descriptor ? descriptor.featureActivated : undefined,
        acknowledged: ack.checked === true,
      });
    }

    function blockedKey(blocked) {
      switch (blocked) {
        case "consent_feature_not_active": return "notReady";
        case "consent_product_unknown": return "productUnknown";
        case "consent_separate_product": return "productSeparate";
        case "consent_target_unknown": return "targetRequired";
        case "consent_not_acknowledged": return "ready";
        default: return "notReady";
      }
    }

    function syncControls() {
      const descriptor = describeTarget();
      const t = locale();
      targetDd.textContent = descriptor && typeof descriptor.deviceName === "string" && descriptor.deviceName
        ? descriptor.deviceName
        : (descriptor && typeof descriptor.deviceId === "string" ? descriptor.deviceId : t.targetUnknown);
      const readiness = currentReadiness();
      if (granted) {
        // Terminal for this panel session: keep the stored-consent status and
        // the confirm disabled so a later locale change cannot re-arm a grant.
        confirm.disabled = true;
        return;
      }
      confirm.disabled = submitting || readiness.ready !== true;
      if (!submitting) setStatus(blockedKey(readiness.blocked));
    }

    function translations() {
      const t = locale();
      toggle.textContent = t.toggle;
      title.textContent = t.title;
      close.textContent = t.close;
      close.setAttribute("aria-label", t.close);
      targetDt.textContent = t.targetLabel;
      serviceDt.textContent = t.serviceLabel;
      serviceDd.textContent = t.serviceValue;
      detailsSummary.textContent = t.details;
      allowedTitle.textContent = t.allowedTitle;
      allowedBody.textContent = t.allowedBody;
      deniedTitle.textContent = t.deniedTitle;
      deniedBody.textContent = t.deniedBody;
      approvalNote.textContent = t.approvalNote;
      revokeNote.textContent = t.revokeNote;
      ackLabel.textContent = t.ackLabel;
      confirm.textContent = t.confirm;
      cancel.textContent = t.cancel;
      renderStatus();
      if (opened && !submitting && !granted) syncControls();
    }

    function reset() {
      ack.checked = false; // cancel always returns to DEFAULT_OFF
      submitting = false;
      granted = false;
      lastKeys = ["ready"];
      panel.removeAttribute("aria-busy");
      // Any response still in flight is now stale for this panel session.
      invalidate();
    }

    function closePanel() {
      opened = false;
      reset();
      panel.hidden = true;
      toggle.setAttribute("aria-expanded", "false");
      toggle.focus();
    }

    // One explicit click performs at most one submission. A second click while a
    // submission is in flight, or after this panel session already stored a
    // consent, is ignored rather than re-sent.
    async function submitConsent() {
      if (submitting || granted) return;
      const readiness = currentReadiness();
      if (readiness.ready !== true) return;
      const descriptor = describeTarget();
      const body = buildGrantBody(descriptor.deviceId);
      if (!body) return;
      const p = port();
      if (!p || typeof p.grantConsent !== "function") {
        // No verified server port: honest "not ready", and nothing is sent.
        setStatus("notReady");
        return;
      }
      // Claim the current generation. A close/reopen, Escape, account switch or
      // Claw exit during the await bumps it, making this response stale.
      const request = generation;
      submitting = true;
      confirm.disabled = true;
      panel.setAttribute("aria-busy", "true");
      setStatus("submitting");
      let result;
      try {
        result = await p.grantConsent(body);
      } catch {
        result = null;
      }
      // A response from a superseded generation (or a closed panel) must not
      // change the current screen in any way.
      if (request !== generation || !opened) return;
      submitting = false;
      panel.removeAttribute("aria-busy");
      const projection = projectGrantReceipt(result, descriptor.deviceId);
      if (projection.accepted) {
        // Consent stored — explicitly NOT online and NOT an execution approval.
        granted = true;
        setStatus("granted", "grantedNotOnline");
        confirm.disabled = true;
        return;
      }
      const raw = isPlainObject(result) ? result : {};
      const error = isPlainObject(raw.error) ? raw.error : {};
      const mapped = consentStateFromError(
        typeof raw.status === "number" ? raw.status : 0,
        typeof error.code === "string" ? error.code : "",
      );
      setStatus(mapped.state === "DENIED" ? "denied"
        : mapped.state === "REVOKED" ? "revoked"
          : mapped.state === "EXPIRED" ? "expired" : "failed");
      confirm.disabled = false;
    }

    toggle.addEventListener("click", () => {
      if (!isClaw()) return;
      if (opened) {
        closePanel();
        return;
      }
      opened = true;
      panel.hidden = false;
      toggle.setAttribute("aria-expanded", "true");
      // A re-open supersedes any response from a previous panel session.
      invalidate();
      // Opening is a pure read of the local descriptor; no network is issued.
      syncControls();
    });
    close.addEventListener("click", closePanel);
    cancel.addEventListener("click", closePanel);
    ack.addEventListener("change", () => {
      if (opened && !submitting) syncControls();
    });
    confirm.addEventListener("click", () => {
      void submitConsent();
    });
    root.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && opened) {
        event.preventDefault();
        closePanel();
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && opened && !submitting) syncControls();
    });
    for (const evt of ["padiem:auth-state", "padiem:auth-changed", "padiem:account-changed"]) {
      window.addEventListener(evt, () => {
        // An account change invalidates any pending acknowledgement.
        reset();
        if (opened && isClaw()) syncControls();
      });
    }
    new MutationObserver(() => {
      if (isClaw()) {
        root.hidden = false;
        return;
      }
      root.hidden = true;
      if (opened) closePanel();
      else reset();
    }).observe(shell, { attributes: true, attributeFilter: ["data-state"] });
    new MutationObserver(translations).observe(document.documentElement, {
      attributes: true, attributeFilter: ["lang"],
    });
    translations();
    root.hidden = !isClaw();
  }

  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
