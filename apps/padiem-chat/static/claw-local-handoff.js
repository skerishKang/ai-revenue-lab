// #3084 — Claw "Connect this computer" handoff (Web/B62 slice).
//
// SCOPE / NON-AUTHORITY CONTRACT (must stay true while #3080 is in flight):
//   PAIRING_AUTHORITY_IN_WEB_UI=NO   this file never mints, signs, parses or
//                                    stores a pairing token / device session.
//   DEVICE_SESSION_AUTHORITY=NO     no device-session store, no refresh, no
//                                    revocation logic.
//   TRANSPORT_AUTHORITY=NO          no WebSocket / SSE / polling / fetch to a
//                                    broker, no deep-link protocol handler.
//   EXECUTION_AUTHORITY=NO          no task admission, no approval decision, no
//                                    local process invocation.
//
// What this file IS: a deterministic, fail-closed *client projection* over an
// already-authoritative server/device projection, plus the presentation copy
// and the element projection for the handoff panel. Everything the panel shows
// is derived; nothing is invented, and nothing unknown is presented as usable.
//
// The only server surface consumed is a narrow typed shape:
//   { conversationId, runId, taskId, requiresLocalAccess, device, handoff, ... }
// Any field that is missing or unrecognised degrades to a safe, non-usable
// presentation instead of a guess.
(() => {
  "use strict";

  const CONTRACT_VERSION = "b62-claw-local-handoff/1";

  // Canonical server-side device lifecycle states this projection may present.
  // Anything else is normalised to ACTION_REQUIRED (fail-closed).
  const CANONICAL_DEVICE_STATES = Object.freeze([
    "PAIRING",
    "CONNECTED",
    "OFFLINE",
    "REVOKED",
    "ACTION_REQUIRED",
  ]);

  // Presentation-only variants. These never assert server truth on their own:
  // they are only reachable from a canonical CONNECTED projection and are
  // reported to the server truth via `deviceState` which stays canonical.
  const PRESENTATION_VARIANTS = Object.freeze(["UPDATE_REQUIRED"]);

  const SAFE_FALLBACK_STATE = "ACTION_REQUIRED";

  // Fields that must never reach the Web projection. The projection keeps only
  // presentation-safe, already-redacted material; raw command output, argv,
  // credentials and stderr belong to the local runner, not to the browser.
  const FORBIDDEN_EVIDENCE_KEYS = Object.freeze([
    "argv",
    "args",
    "command",
    "commandLine",
    "env",
    "credential",
    "credentials",
    "password",
    "secret",
    "token",
    "accessToken",
    "refreshToken",
    "pairingToken",
    "sessionToken",
    "stdout",
    "stderr",
    "stdin",
    "rawOutput",
    "stack",
    "stackTrace",
  ]);

  function _isPlainObject(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  function _cleanString(value, maxLength = 512) {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    return trimmed.length > maxLength ? trimmed.slice(0, maxLength) : trimmed;
  }

  // Correlation identity is preserved verbatim across the handoff. A new chat
  // must never be minted, so a projection that omits an id keeps it as null and
  // the caller decides; a projection that *changes* one is reported as a
  // mismatch rather than silently accepted.
  function _normalizeIdentity(input) {
    const conversationId = _cleanString(input.conversationId, 128);
    const runId = _cleanString(input.runId, 128);
    const taskId = _cleanString(input.taskId, 128);
    return {
      conversationId,
      runId,
      taskId,
      // True only when the caller passed at least one id. Used to prove the
      // same conversation/run/task continues rather than restarting.
      hasIdentity: Boolean(conversationId || runId || taskId),
    };
  }

  /**
   * Fail-closed normaliser over the canonical server/device projection.
   * Never throws; an unreadable projection is ACTION_REQUIRED + not usable.
   */
  function normalizeDeviceProjection(raw) {
    const source = _isPlainObject(raw) ? raw : {};
    const claimed = typeof source.state === "string" ? source.state.trim().toUpperCase() : "";
    const canonical = CANONICAL_DEVICE_STATES.includes(claimed) ? claimed : null;

    const expired = source.expired === true;
    const revoked = source.revoked === true;
    const usableFlag = source.usable === true;

    // Optional server-supplied variant. Only honoured when the canonical state
    // is a genuinely usable CONNECTED, so an offline/revoked/not-usable device
    // can never be dressed up as merely "needs an update".
    const claimedVariant =
      typeof source.variant === "string" ? source.variant.trim().toUpperCase() : "";
    const variant =
      PRESENTATION_VARIANTS.includes(claimedVariant) &&
      canonical === "CONNECTED" &&
      usableFlag === true &&
      !expired &&
      !revoked
        ? claimedVariant
        : null;

    let state = canonical || SAFE_FALLBACK_STATE;
    // A server that says CONNECTED but also says expired/revoked/not-usable is
    // contradictory. Disconnected/expired/revoked must never render as
    // connected, so the safe state wins.
    if (state === "CONNECTED" && (expired || revoked || !usableFlag)) state = "ACTION_REQUIRED";
    if (revoked) state = "REVOKED";
    if (expired && state === "CONNECTED") state = "OFFLINE";

    // Only canonical CONNECTED, unexpired, unrevoked, explicitly usable is
    // usable. Everything else is presentation-only.
    const usable = state === "CONNECTED" && !expired && !revoked && usableFlag;

    return Object.freeze({
      state,
      variant,
      usable,
      expired,
      revoked,
      // The exact literal the server sent, kept for evidence/debugging only.
      claimedState: canonical || null,
      // True when the server sent something this projection does not know.
      // Surfaced so the UI can avoid claiming a state it cannot justify.
      unrecognisedState: !canonical,
      deviceName: _cleanString(source.deviceName, 80),
      platform: _cleanString(source.platform, 40),
    });
  }

  /**
   * Consume the opaque handoff value produced upstream (#3080 owns its
   * semantics). This function only checks *shape* so the UI never parses,
   * derives, re-encodes or mints one. The value is treated as an opaque token:
   * it is length-bounded, never decoded, and never persisted.
   */
  function consumeHandoffEnvelope(raw) {
    const source = _isPlainObject(raw) ? raw : {};
    const value = _cleanString(source.value, 512);
    const kind =
      typeof source.kind === "string" ? source.kind.trim().toLowerCase() : "";

    // No value, or a shape we were not told to expect -> no handoff is offered.
    // The CTA degrades to a plain "open/install" affordance instead.
    if (!value) {
      return Object.freeze({
        available: false,
        reason: value === null && source.value !== undefined ? "malformed" : "absent",
        value: null,
        kind: kind || null,
      });
    }
    if (kind && kind !== "deep_link") {
      return Object.freeze({ available: false, reason: "unsupported_kind", value: null, kind });
    }
    return Object.freeze({ available: true, reason: null, value, kind: "deep_link" });
  }

  /**
   * Sanitise approval / status / result / evidence projection.
   * This is presentation only: it reports what upstream decided. It never
   * decides, and it never approves.
   */
  function _normalizeActivity(raw) {
    const source = _isPlainObject(raw) ? raw : {};

    const approvalState = _cleanString(source.approvalState, 40);
    const approvalRequired = source.approvalRequired === true;
    const approvalDecided = approvalState ? approvalState !== "PENDING" : false;

    const statusState = _cleanString(source.statusState, 40);
    const statusLabel = _cleanString(source.statusLabel, 160);

    const resultState = _cleanString(source.resultState, 40);
    const resultSummary = _cleanString(source.resultSummary, 600);

    // Evidence is a redacted, bounded list. Any key that could carry raw
    // process material is dropped rather than truncated.
    const rawEvidence = Array.isArray(source.evidence) ? source.evidence : [];
    const evidence = [];
    for (const item of rawEvidence.slice(0, 10)) {
      if (typeof item === "string") {
        const text = _cleanString(item, 200);
        if (text) evidence.push({ kind: "note", text });
        continue;
      }
      if (!_isPlainObject(item)) continue;
      const keys = Object.keys(item);
      if (keys.some((key) => FORBIDDEN_EVIDENCE_KEYS.includes(key))) continue;
      const kind = _cleanString(item.kind, 40) || "note";
      // A forbidden term may also arrive as the *kind* itself
      // (e.g. kind: "stdout"), so the value is filtered, not just the keys.
      if (FORBIDDEN_EVIDENCE_KEYS.includes(kind.trim().toLowerCase())) continue;
      const text = _cleanString(item.text, 200);
      if (text) evidence.push({ kind, text });
      if (evidence.length >= 10) break;
    }

    return Object.freeze({
      approvalRequired,
      approvalState,
      approvalDecided,
      approvalVisible: approvalRequired || Boolean(approvalState),
      statusState,
      statusLabel,
      statusVisible: Boolean(statusState || statusLabel),
      resultState,
      resultSummary,
      resultVisible: Boolean(resultState || resultSummary),
      evidence: Object.freeze(evidence),
      evidenceVisible: evidence.length > 0,
    });
  }

  /**
   * Build the whole presentation view model. Pure: same input -> same output.
   */
  function deriveHandoffViewModel(input) {
    const source = _isPlainObject(input) ? input : {};
    const identity = _normalizeIdentity(source);
    const device = normalizeDeviceProjection(source.device);

    // Local access requirement is capability-derived. An unreadable/absent
    // capability flag must not invent a requirement, and must not hide one
    // that upstream explicitly declared.
    const requiresLocalAccess =
      source.requiresLocalAccess === true ||
      (Array.isArray(source.requiredCapabilities) &&
        source.requiredCapabilities.some((cap) => _cleanString(cap, 60) === "local_computer"));
    const localAccessKnown = typeof source.requiresLocalAccess === "boolean";

    const handoff = consumeHandoffEnvelope(source.handoff);

    // Install-vs-open is a Desktop-installation fact, not a device fact.
    // Only the two honest answers exist; anything else -> install guidance.
    const desktopInstalled = source.desktopInstalled === true;
    const installState = desktopInstalled ? "installed" : "install_required";

    const activity = _normalizeActivity(source);

    // The single honest answer to "may the user proceed with the local step?".
    // Requires: local access really is required, the device is canonically
    // connected, and an opaque handoff value exists to hand over.
    const canProceed = requiresLocalAccess && device.usable && handoff.available;

    // Identity continuity: any id the handoff claims must match the live one.
    const handoffConversationId = _cleanString(
      _isPlainObject(source.handoff) ? source.handoff.conversationId : null,
      128,
    );
    const identityMismatch = Boolean(
      handoffConversationId && identity.conversationId && handoffConversationId !== identity.conversationId,
    );

    return Object.freeze({
      contractVersion: CONTRACT_VERSION,
      identity: Object.freeze(identity),
      identityMismatch,
      requiresLocalAccess,
      localAccessKnown,
      device,
      handoff,
      installState,
      desktopInstalled,
      activity,
      canProceed,
      // Only a canonical, usable CONNECTED device may ever be shown as usable.
      showConnected: device.usable && device.state === "CONNECTED",
    });
  }

  // ---------------------------------------------------------------------------
  // Korean IME guard (#3084 regression protection).
  //
  // Enter must submit only when it is a *real* Enter. During Hangul/IME
  // composition the browser still reports key === "Enter" for the key that
  // confirms a candidate, so submitting on it swallows the composed character
  // and can send a half-typed word. Guard on isComposing, the legacy
  // keyCode 229 fallback, and an explicit composition tracker, so a synthetic
  // or partially-supported event cannot slip through.
  // ---------------------------------------------------------------------------

  function createCompositionGuard() {
    let composing = false;
    return {
      start() {
        composing = true;
      },
      update() {
        composing = true;
      },
      end() {
        composing = false;
      },
      isComposing() {
        return composing;
      },
      reset() {
        composing = false;
      },
    };
  }

  /**
   * Pure decision function. Returns true only when Enter should submit.
   */
  function shouldSubmitOnEnter(event, guard) {
    if (!_isPlainObject(event)) return false;
    if (event.key !== "Enter") return false;
    if (event.shiftKey === true) return false; // Shift+Enter inserts a newline
    if (event.altKey === true || event.ctrlKey === true || event.metaKey === true) return false;
    if (event.isComposing === true) return false;
    // Legacy browsers / synthetic events may not carry isComposing.
    if (event.keyCode === 229) return false;
    if (guard && typeof guard.isComposing === "function" && guard.isComposing()) return false;
    return true;
  }

  // ---------------------------------------------------------------------------
  // Presentation copy.
  //
  // Consumer-facing language only. The following terms must NOT appear:
  //   agent runtime, MCP, broker, WebSocket, execution target, sandbox, process,
  //   capability manifest.
  // ---------------------------------------------------------------------------

  const COPY = Object.freeze({
    ko: Object.freeze({
      "claw-local-title": "컴퓨터 연결이 필요합니다",
      "claw-local-body": "이 작업을 대신하려면 지금 사용 중인 컴퓨터에 연결해야 합니다. 연결한 뒤 이 대화에서 그대로 이어서 진행합니다.",
      "claw-local-cta-connect": "이 컴퓨터 연결",
      "claw-local-cta-open": "이 컴퓨터 연결 열기",
      "claw-local-cta-install": "설치 안내 보기",
      "claw-local-install-note": "Padiem 데스크톱이 설치되어 있지 않습니다. 설치 안내를 열고 다시 시도해 주세요.",
      "claw-local-open-note": "Padiem 데스크톱을 열면 연결이 이어집니다. 이 대화는 그대로 유지됩니다.",
      "claw-local-identity-note": "이 대화가 그대로 이어집니다.",
      "claw-local-state-pairing": "연결을 확인하는 중입니다.",
      "claw-local-state-connected": "컴퓨터가 연결되어 있습니다.",
      "claw-local-state-offline": "컴퓨터 연결이 끊어져 있습니다.",
      "claw-local-state-revoked": "이 컴퓨터의 연결 권한이 해제되었습니다.",
      "claw-local-state-action_required": "연결을 다시 확인해야 합니다.",
      "claw-local-state-unknown": "연결 상태를 확인하는 중입니다.",
      "claw-local-state-update_required": "업데이트가 필요합니다.",
      "claw-local-approval-title": "승인이 필요합니다",
      "claw-local-approval-pending": "이 작업을 진행하려면 먼저 승인이 필요합니다.",
      "claw-local-approval-decided": "승인 결과가 반영되었습니다.",
      "claw-local-status-title": "진행 상황",
      "claw-local-result-title": "결과",
      "claw-local-evidence-title": "확인 내용",
      "claw-local-retry": "연결 다시 확인",
      "claw-local-panel-aria": "컴퓨터 연결 안내",
    }),
    en: Object.freeze({
      "claw-local-title": "This task needs your computer",
      "claw-local-body": "To do this for you, we need to connect to the computer you are using right now. Once connected, you stay in this same conversation.",
      "claw-local-cta-connect": "Connect this computer",
      "claw-local-cta-open": "Open this computer",
      "claw-local-cta-install": "See install instructions",
      "claw-local-install-note": "Padiem Desktop is not installed yet. Open the install instructions and try again.",
      "claw-local-open-note": "Opening Padiem Desktop continues the connection. This conversation stays as it is.",
      "claw-local-identity-note": "This conversation continues as-is.",
      "claw-local-state-pairing": "Checking the connection.",
      "claw-local-state-connected": "Your computer is connected.",
      "claw-local-state-offline": "The computer connection is offline.",
      "claw-local-state-revoked": "This computer's connection was revoked.",
      "claw-local-state-action_required": "The connection needs to be checked again.",
      "claw-local-state-unknown": "Checking the connection status.",
      "claw-local-state-update_required": "An update is needed.",
      "claw-local-approval-title": "Approval needed",
      "claw-local-approval-pending": "This task needs your approval before it continues.",
      "claw-local-approval-decided": "The approval decision has been applied.",
      "claw-local-status-title": "Progress",
      "claw-local-result-title": "Result",
      "claw-local-evidence-title": "What was checked",
      "claw-local-retry": "Check the connection again",
      "claw-local-panel-aria": "Computer connection",
    }),
  });

  const FORBIDDEN_USER_JARGON = Object.freeze([
    "agent runtime",
    "mcp",
    "broker",
    "websocket",
    "execution target",
    "sandbox",
    "capability manifest",
  ]);

  function copy(lang) {
    return COPY[lang === "en" ? "en" : "ko"];
  }

  // ---------------------------------------------------------------------------
  // Element projection. The panel markup is declared in index.html; this only
  // writes text/attributes/visibility into a supplied element map, so it is
  // testable in Node with plain fake elements and adds no HTML-building
  // authority to the module.
  // ---------------------------------------------------------------------------

  function _setText(element, value) {
    if (element && typeof element === "object" && value != null) element.textContent = String(value);
  }

  function _setAttr(element, name, value) {
    if (!element || typeof element !== "object") return;
    if (value == null) element.removeAttribute(name);
    else element.setAttribute(name, String(value));
  }

  function _setHidden(element, hidden) {
    if (!element || typeof element !== "object") return;
    element.hidden = Boolean(hidden);
    if (hidden) element.setAttribute("hidden", "");
    else element.removeAttribute("hidden");
  }

  function deviceStateLabel(viewModel, lang) {
    const t = copy(lang);
    if (viewModel.device.unrecognisedState && !viewModel.device.usable) {
      return t["claw-local-state-unknown"];
    }
    if (viewModel.device.variant === "UPDATE_REQUIRED") {
      return t["claw-local-state-update_required"];
    }
    return t[`claw-local-state-${viewModel.device.state.toLowerCase()}`] || t["claw-local-state-unknown"];
  }

  function ctaLabel(viewModel, lang) {
    const t = copy(lang);
    if (viewModel.installState === "install_required") return t["claw-local-cta-install"];
    if (viewModel.device.usable) return t["claw-local-cta-open"];
    return t["claw-local-cta-connect"];
  }

  /**
   * Project the view model onto the panel elements.
   * `refs` is a plain map of element references; missing entries are skipped,
   * so the panel degrades safely instead of throwing.
   */
  function projectHandoffPanel(refs, viewModel, lang) {
    const t = copy(lang);
    const elements = _isPlainObject(refs) ? refs : {};

    const visible = Boolean(viewModel.requiresLocalAccess);
    _setHidden(elements.panel, !visible);
    if (!visible) return elements;

    _setText(elements.title, t["claw-local-title"]);
    _setText(elements.body, t["claw-local-body"]);
    _setAttr(elements.panel, "aria-label", t["claw-local-panel-aria"]);
    _setAttr(elements.panel, "data-claw-local-state", viewModel.device.state);
    _setAttr(elements.panel, "data-claw-local-usable", String(viewModel.device.usable));
    _setAttr(elements.panel, "data-claw-local-install", viewModel.installState);
    _setAttr(elements.panel, "data-claw-local-contract", CONTRACT_VERSION);

    _setText(elements.state, deviceStateLabel(viewModel, lang));
    _setAttr(elements.state, "data-state", viewModel.device.state);
    // aria-live so the state change is announced without stealing focus.
    _setAttr(elements.state, "aria-live", "polite");

    // CTA. A button, never a link, because the handoff is a UI action; the
    // actual deep link is opened by the injected #3080 adapter, not here.
    _setText(elements.cta, ctaLabel(viewModel, lang));
    _setAttr(elements.cta, "type", "button");
    _setAttr(elements.cta, "data-handoff-available", String(viewModel.handoff.available));
    if (elements.cta && typeof elements.cta === "object") {
      elements.cta.disabled = !viewModel.canProceed;
      if (!viewModel.canProceed) elements.cta.setAttribute("aria-disabled", "true");
      else elements.cta.removeAttribute("aria-disabled");
    }

    // Install-vs-open guidance. Exactly one of the two notes is shown, so the
    // panel never says "not installed" and "just open it" at the same time.
    _setHidden(elements.installNote, viewModel.installState !== "install_required");
    _setHidden(elements.openNote, viewModel.installState === "install_required");

    // Same-conversation reassurance, and the ids that prove continuity.
    _setText(elements.identityNote, t["claw-local-identity-note"]);
    if (elements.identity) {
      _setAttr(elements.identity, "data-conversation-id", viewModel.identity.conversationId || null);
      _setAttr(elements.identity, "data-run-id", viewModel.identity.runId || null);
      _setAttr(elements.identity, "data-task-id", viewModel.identity.taskId || null);
    }

    _setHidden(elements.approval, !viewModel.activity.approvalVisible);
    if (viewModel.activity.approvalVisible) {
      _setText(elements.approvalTitle, t["claw-local-approval-title"]);
      _setText(
        elements.approvalBody,
        viewModel.activity.approvalDecided
          ? t["claw-local-approval-decided"]
          : t["claw-local-approval-pending"],
      );
      _setAttr(elements.approval, "data-approval-state", viewModel.activity.approvalState || null);
    }

    _setHidden(elements.status, !viewModel.activity.statusVisible);
    if (viewModel.activity.statusVisible) {
      _setText(elements.statusTitle, t["claw-local-status-title"]);
      _setText(elements.statusBody, viewModel.activity.statusLabel || viewModel.activity.statusState);
      _setAttr(elements.status, "role", "status");
    }

    _setHidden(elements.result, !viewModel.activity.resultVisible);
    if (viewModel.activity.resultVisible) {
      _setText(elements.resultTitle, t["claw-local-result-title"]);
      _setText(elements.resultBody, viewModel.activity.resultSummary || viewModel.activity.resultState);
    }

    _setHidden(elements.evidence, !viewModel.activity.evidenceVisible);
    if (viewModel.activity.evidenceVisible) {
      _setText(elements.evidenceTitle, t["claw-local-evidence-title"]);
      if (elements.evidenceList) {
        elements.evidenceList.textContent = viewModel.activity.evidence
          .map((item) => item.text)
          .join("\n");
      }
    }

    return elements;
  }

  // ---------------------------------------------------------------------------
  // Deterministic fixtures.
  //
  // These are UI fixtures only. They stand in for the #3080 contract until it
  // lands, and are never a substitute for it: no token is real, no session is
  // created, and no transport is opened. Values are obviously synthetic.
  // ---------------------------------------------------------------------------

  const FIXTURES = Object.freeze({
    installRequired: Object.freeze({
      conversationId: "conv_fixture_3084_a",
      runId: "run_fixture_3084_a",
      taskId: "task_fixture_3084_a",
      requiresLocalAccess: true,
      requiredCapabilities: Object.freeze(["local_computer"]),
      desktopInstalled: false,
      device: Object.freeze({ state: "OFFLINE", usable: false, deviceName: "fixture-pc", platform: "windows" }),
      handoff: Object.freeze({ kind: "deep_link", value: "fixture-opaque-handoff-value" }),
    }),
    installedPairing: Object.freeze({
      conversationId: "conv_fixture_3084_a",
      runId: "run_fixture_3084_a",
      taskId: "task_fixture_3084_a",
      requiresLocalAccess: true,
      desktopInstalled: true,
      device: Object.freeze({ state: "PAIRING", usable: false, deviceName: "fixture-pc", platform: "windows" }),
      handoff: Object.freeze({
        kind: "deep_link",
        value: "fixture-opaque-handoff-value",
        conversationId: "conv_fixture_3084_a",
      }),
    }),
    connected: Object.freeze({
      conversationId: "conv_fixture_3084_a",
      runId: "run_fixture_3084_a",
      taskId: "task_fixture_3084_a",
      requiresLocalAccess: true,
      desktopInstalled: true,
      device: Object.freeze({ state: "CONNECTED", usable: true, deviceName: "fixture-pc", platform: "windows" }),
      handoff: Object.freeze({
        kind: "deep_link",
        value: "fixture-opaque-handoff-value",
        conversationId: "conv_fixture_3084_a",
      }),
      approvalRequired: true,
      approvalState: "PENDING",
      statusState: "RUNNING",
      statusLabel: "fixture status",
    }),
    connectedComplete: Object.freeze({
      conversationId: "conv_fixture_3084_a",
      runId: "run_fixture_3084_a",
      taskId: "task_fixture_3084_a",
      requiresLocalAccess: true,
      desktopInstalled: true,
      device: Object.freeze({ state: "CONNECTED", usable: true, deviceName: "fixture-pc", platform: "windows" }),
      handoff: Object.freeze({
        kind: "deep_link",
        value: "fixture-opaque-handoff-value",
        conversationId: "conv_fixture_3084_a",
      }),
      approvalRequired: true,
      approvalState: "APPROVED",
      statusState: "COMPLETED",
      statusLabel: "fixture status",
      resultState: "COMPLETED",
      resultSummary: "fixture result",
      evidence: Object.freeze([{ kind: "note", text: "fixture evidence" }]),
    }),
  });

  window.PadiemClawLocalHandoff = Object.freeze({
    CONTRACT_VERSION,
    CANONICAL_DEVICE_STATES,
    PRESENTATION_VARIANTS,
    FORBIDDEN_EVIDENCE_KEYS,
    FORBIDDEN_USER_JARGON,
    FIXTURES,
    normalizeDeviceProjection,
    consumeHandoffEnvelope,
    deriveHandoffViewModel,
    shouldSubmitOnEnter,
    createCompositionGuard,
    copy,
    deviceStateLabel,
    ctaLabel,
    projectHandoffPanel,
  });
})();
