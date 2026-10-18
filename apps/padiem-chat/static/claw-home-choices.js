/* Padiem Claw first-use destinations: reuse the existing Chat four-card shell.
 * No copy of the composer, image, auth, approval, or connector implementation.
 * Cards open the already-existing Connectors dialog and owner-scoped PC list.
 * No download URL, device connection, GitHub write access or success is forged.
 */
(() => {
  "use strict";

  const actions = Object.freeze({
    clawComputerWorkspace: "connectorComputerCard",
    clawDriveWorkspace: 'capability-card[data-connector="google-drive"]',
    clawGithubWorkspace: "connectorGithubCard",
  });

  function install() {
    const shell = document.querySelector(".app-shell");
    const opener = document.getElementById("connectorsNavButton");
    const dialog = document.getElementById("connectorsDialog");
    if (!shell || !opener || !dialog) return;

    function isClawHome() {
      return shell.dataset.state === "claw" &&
        document.getElementById("clawWorkspace")?.dataset.view === "general";
    }

    // #4139: this tab's existing signed-in Claw click is the ONLY approval
    // intent. No URL/session storage, manual code, extra checkbox or retry.
    const pcChannelName = "padiem-claw-pc-connect-v1";
    const pcOfferRef = /^link\.[0-9a-f]{32}$/;
    // First-time install may take 30m, but an individual Broker offer expires
    // in 90s. A new owner click after that TTL may retry the real native launch.
    const pcIntentLifetimeMs = 30 * 60 * 1000;
    const pcOfferRetryIntervalMs = 90 * 1000;
    let pcChannel = null;
    let pcIntent = null;
    let pcApprovalPending = false;
    // Constant-only diagnostic stages. Never log IDs, refs, payloads, cookies.
    function pcStage(code) {
      console.info("PADIEM_4139_STAGE=" + code);
      // Bounded, in-memory readback only. No browser persistence, request
      // refs, account/device identifiers or payloads.
      const safe = /^(?:receiver_js_loaded|receiver_ready|click_intent_created|native_uri_issued|pagehide_intent_cleared|offer_message_received|offer_intent_absent|offer_context_rejected|approve_post_dispatch|approve_fetch_rejected|approve_http_(?:[1-5][0-9]{2}|unknown)|approve_denied_[a-z_]{1,65}|approve_receipt_(?:valid|read_failed|too_large|json_invalid|contract_invalid)|approve_failed)$/;
      if (!safe.test(code)) return;
      try {
        const saved = window.__padiemPcConnectStages;
        const previous = Array.isArray(saved) ? saved.filter(
          (entry) => typeof entry === "string" && safe.test(entry)).slice(-23) : [];
        previous.push(code);
        window.__padiemPcConnectStages = previous;
      } catch {
        // Console logging remains sufficient if the page forbids readback.
      }
    }
    pcStage("receiver_js_loaded");

    function signedIn() {
      return document.querySelector(".sidebar-account")?.dataset.accountState === "signed_in";
    }

    // A guest card click must go to the EXISTING PADIEM authentication UI,
    // never to the Windows protocol, installer, or connector management.
    // We do not remember a privileged click across the login boundary.
    function promptForPcLogin() {
      if (signedIn()) return false;
      pcNote("\uCEF4\uD4E8\uD130\uB97C \uC5F0\uACB0\uD558\uB824\uBA74 \uBA3C\uC800 Padiem\uC5D0 \uB85C\uADF8\uC778\uD574 \uC8FC\uC138\uC694.",
             "Sign in to Padiem before connecting your computer.");
      const hint = document.getElementById("clawPcCardStatus");
      if (hint) hint.textContent = document.documentElement.lang === "en"
        ? "Sign in first" : "\uB85C\uADF8\uC778\uD558\uC138\uC694";
      const login = document.getElementById("loginButton");
      const account = document.querySelector(".sidebar-account");
      // A mismatched/loading account must never accidentally click Logout.
      if (account?.dataset.accountState === "signed_in" ||
          !login || login.hidden || login.disabled) return true;
      login.click(); // opens the canonical app.js auth dialog, no extra modal
      return true;
    }

    function pcNote(ko, en) {
      const note = document.getElementById("clawComputerLiveStatus");
      if (!note) return;
      note.textContent = document.documentElement.lang === "en" ? en : ko;
      note.hidden = false;
    }

    // Existing server-defined public denial enums only. Do not log arbitrary
    // response data, tokens, refs, cookies, device IDs or exception messages.
    const pcApprovalDenials = new Set([
      "canonical_session_required", "connector_enrollment_csrf_denied",
      "enrollment_server_dependency_unavailable",
      "explicit_pc_consent_required", "invalid_pending_pc_request",
      "pending_pc_unavailable", "pending_pc_not_authenticated",
      "pending_pc_expired", "canonical_consent_unavailable",
      "canonical_consent_unconfirmed", "canonical_challenge_unavailable",
      "canonical_challenge_invalid", "pc_delivery_unconfirmed",
    ]);

    async function approveReadyPc(requestRef) {
      try {
        // Existing authenticated, same-origin/CSRF-guarded owner POST contract.
        let response;
        try {
          response = await fetch("/api/claw/connector/enrollments/approve-link", {
            method: "POST", mode: "same-origin", credentials: "same-origin",
            redirect: "error", referrerPolicy: "no-referrer", cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ request_ref: requestRef }),
          });
        } catch {
          // Redirect disallowed by fetch, network/transport errors, etc.
          pcStage("approve_fetch_rejected");
          throw new Error("owner_approval_transport");
        }
        pcStage("approve_http_" + (Number.isInteger(response.status) &&
          response.status >= 100 && response.status <= 599 ? response.status : "unknown"));
        if (!response.ok) {
          let safeCode = "unclassified";
          try {
            const denialBody = await response.text();
            if (denialBody.length <= 2048) {
              const denial = JSON.parse(denialBody);
              const code = denial?.error?.code;
              if (denial?.ok === false && pcApprovalDenials.has(code)) safeCode = code;
            }
          } catch {
            // Diagnostic body unavailable; preserve the HTTP status and reject.
          }
          pcStage("approve_denied_" + safeCode);
          throw new Error("owner_approval_refused");
        }
        let raw;
        try {
          raw = await response.text();
        } catch {
          pcStage("approve_receipt_read_failed");
          throw new Error("owner_receipt_unreadable");
        }
        if (raw.length > 8192) {
          pcStage("approve_receipt_too_large");
          throw new Error("owner_receipt_too_large");
        }
        let reply;
        try {
          reply = JSON.parse(raw);
        } catch {
          pcStage("approve_receipt_json_invalid");
          throw new Error("owner_receipt_json_invalid");
        }
        const pendingReceipt = reply?.state === "awaiting_device_confirmation" && reply.registered === false;
        const installedReceipt = reply?.state === "paired_offline" && reply.registered === true;
        if (reply?.ok !== true || (!pendingReceipt && !installedReceipt) ||
            reply.connected !== false ||
            reply.dispatch_authorized !== false) {
          pcStage("approve_receipt_contract_invalid");
          throw new Error("owner_receipt_invalid");
        }
        pcStage("approve_receipt_valid");
        // Pending is NOT registered/connected. The original server-owned GET
        // remains the only source of actual PC status.
        pcNote("PC 등록 요청을 전달했습니다. 실제 연결 상태를 확인합니다.",
               "PC registration was requested. Checking the actual status.");
        const check = document.getElementById("clawComputerDeviceStatusButton");
        if (check && !check.disabled) check.click();
      } catch {
        pcStage("approve_failed");
        pcNote("PC 연결 요청이 완료되지 않았습니다. 자동 재시도하지 않습니다.",
               "The PC connection request did not complete. It will not retry automatically.");
      } finally {
        pcApprovalPending = false;
      }
    }

    function onPcOfferMessage(event) {
      const data = event?.data;
      if (data?.type === "pc_offer_ready") {
        pcStage("offer_message_received");
        if (!pcIntent) pcStage("offer_intent_absent");
      }
      if (!pcIntent || pcIntent.used || pcApprovalPending ||
          !data || Object.getPrototypeOf(data) !== Object.prototype ||
          Object.keys(data).length !== 2 ||
          data.type !== "pc_offer_ready" ||
          typeof data.request_ref !== "string" || !pcOfferRef.test(data.request_ref)) return;
      const valid = isClawHome() && signedIn() &&
        Date.now() >= pcIntent.at && Date.now() - pcIntent.at <= pcIntentLifetimeMs;
      // Consume BEFORE the authenticated request: duplicates and failures
      // cannot create additional approval POSTs.
      pcIntent.used = true;
      pcIntent = null;
      if (!valid) {
        pcStage("offer_context_rejected");
        return;
      }
      pcStage("approve_post_dispatch");
      pcApprovalPending = true;
      void approveReadyPc(data.request_ref);
    }

    function startPcConnectionFromOriginalClick() {
      if (!isClawHome() || !signedIn()) return false;
      if (document.querySelector('[data-claw-connection="pc"]')?.dataset.pcPaused === "true") {
        pcNote("\uC0AC\uC6A9\uC790\uAC00 PC \uC5F0\uACB0\uC744 \uAEBC\uB1A8\uC2B5\uB2C8\uB2E4. ON\uC744 \uB20C\uB7EC \uC7AC\uAC1C\uD558\uC138\uC694.",
               "PC use is paused. Choose ON to resume.");
        return true;
      }
      if (document.querySelector('[data-claw-connection="pc"]')?.dataset.connectionState === "on") {
        return false;
      }
      if (pcApprovalPending) return true;
      if (pcIntent && !pcIntent.used &&
          Date.now() - pcIntent.at <= pcOfferRetryIntervalMs) {
        pcNote("\uC5F0\uACB0 \uC911... \uC2E4\uD589 \uD655\uC778 \uD6C4 \uC790\uB3D9\uC73C\uB85C \uC5F0\uACB0\uD569\uB2C8\uB2E4.",
               "Connecting. Once the program is running, connection proceeds automatically.");
        return true;
      }
      if (typeof window.BroadcastChannel !== "function") {
        pcNote("현재 브라우저에서 PC 연결 수신을 준비할 수 없습니다.",
               "This browser could not prepare the PC connection receiver.");
        return true;
      }
      try {
        if (!pcChannel) {
          pcChannel = new window.BroadcastChannel(pcChannelName);
          // Register the receiver BEFORE the native connector launch.
          pcChannel.onmessage = onPcOfferMessage;
          pcStage("receiver_ready");
        }
        pcIntent = { at: Date.now(), used: false };
        pcStage("click_intent_created");
        window.location.assign("padiem-connector://start");
        pcStage("native_uri_issued");
      } catch {
        pcIntent = null;
        pcNote("커넥터 실행을 요청하지 못했습니다. 설치 상태를 확인하세요.",
               "Could not start Connector. Check its installation.");
      }
      return true;
    }

    window.addEventListener("pagehide", () => {
      if (pcIntent) pcStage("pagehide_intent_cleared");
      pcIntent = null;
      if (pcChannel) pcChannel.close();
      pcChannel = null;
    });

    function openWorkspaceConnector(target) {
      if (!isClawHome()) return;
      // Use the EXACT existing authenticated owner Connectors UI flow.
      opener.click();
      if (!dialog.open && !dialog.hasAttribute("open")) return;
      const selector = target === actions.clawDriveWorkspace
        ? ".capability-card[data-connector=\"google-drive\"]"
        : "#" + target;
      const card = dialog.querySelector(selector);
      if (!card) return;
      if (!card.hasAttribute("tabindex")) card.setAttribute("tabindex", "-1");
      card.focus({ preventScroll: true });
      if (typeof card.scrollIntoView === "function") {
        card.scrollIntoView({ block: "nearest", behavior: "instant" });
      }
    }

    for (const [id, target] of Object.entries(actions)) {
      const card = document.getElementById(id);
      if (card) card.addEventListener("click", () => {
        if (id === "clawComputerWorkspace") {
          if (!isClawHome()) return;
          if (promptForPcLogin()) return;
          if (startPcConnectionFromOriginalClick()) return;
        }
        openWorkspaceConnector(target);
      });
    }

    // Empty parts of the same PC card behave like its one primary action.
    // The single ON/OFF switch stops propagation, so OFF cannot reconnect.
    document.querySelector('[data-claw-card="computer"]')?.addEventListener("click", event => {
      if (!isClawHome() || event.target.closest("button")) return;
      document.getElementById("clawComputerWorkspace")?.click();
    });

    const web = document.getElementById("clawWebWorkspace");
    web?.addEventListener("click", () => {
      if (!isClawHome()) return;
      // General Claw is already Web-first. Keep the user's current draft
      // and reuse the same shared #messageInput as Padiem Chat.
      document.getElementById("messageInput")?.focus();
    });

    const historyShortcut = document.getElementById("clawPreviousConversations");
    const historyFeedback = document.getElementById("clawPreviousConversationsFeedback");
    historyShortcut?.addEventListener("click", () => {
      if (!isClawHome()) return;
      const history = document.getElementById("historySection");
      const list = document.getElementById("historyList");
      const en = document.documentElement.lang === "en";
      if (!history || history.hidden) {
        // A signed-in owner may have a temporarily unavailable history API.
        // Never click the signed-in logout button on that error path.
        const login = document.getElementById("loginButton");
        const signedIn = document.getElementById("accountContainer")?.dataset.accountState === "signed_in" ||
          document.querySelector(".sidebar-account")?.dataset.accountState === "signed_in";
        if (!signedIn && login && !login.disabled && !login.hidden) login.click();
        if (historyFeedback) {
          historyFeedback.textContent = signedIn
            ? (en ? "Previous conversations are temporarily unavailable." : "이전 대화를 불러오지 못했습니다.")
            : (en ? "Sign in to view previous conversations." : "이전 대화를 보려면 로그인해 주세요.");
          historyFeedback.hidden = false;
        }
        return;
      }
      if (historyFeedback) {
        historyFeedback.textContent = "";
        historyFeedback.hidden = true;
      }
      const shell = document.querySelector(".app-shell");
      if (shell?.classList.contains("sidebar-collapsed")) {
        document.getElementById("sidebarRestoreButton")?.click();
      }
      if (window.matchMedia?.("(max-width: 920px)")?.matches) {
        document.getElementById("mobileMenu")?.click();
      }
      history.setAttribute("tabindex", "-1");
      history.scrollIntoView?.({ block: "nearest" });
      history.focus?.({ preventScroll: true });
      // Existing #historyList renders Claw-labelled saved conversations and
      // opens them with the canonical openSavedConversation(id) handler.
      // Do not focus delete controls or interpret recent runs as chat history.
      if (list && list.children.length === 0 && historyFeedback) {
        historyFeedback.textContent = en ? "There are no saved conversations yet." : "저장된 이전 대화가 없습니다.";
        historyFeedback.hidden = false;
      }
    });

    const deviceStatus = document.getElementById("clawComputerDeviceStatusButton");
    const statusText = document.getElementById("clawComputerLiveStatus");
    deviceStatus?.addEventListener("click", async () => {
      if (!isClawHome() || !statusText || deviceStatus.disabled) return;
      // Use the SAME existing, owner-scoped GET endpoint as the Claw device
      // manager; this is status-only and cannot issue a pairing or task grant.
      const en = document.documentElement.lang === "en";
      const show = (ko, english) => {
        statusText.textContent = en ? english : ko;
        statusText.hidden = false;
      };
      deviceStatus.disabled = true;
      show("컴퓨터 연결 상태를 확인하고 있습니다.", "Checking your computer connection.");
      try {
        const response = await fetch("/api/claw/local-access/devices", {
          method: "GET", credentials: "same-origin", cache: "no-store",
          headers: { Accept: "application/json" },
        });
        if (response.status === 401 || response.status === 403) {
          show("먼저 로그인해 주세요.", "Please sign in first.");
        } else if (!response.ok) {
          show("컴퓨터 연결을 아직 확인할 수 없습니다.", "Computer connection is not yet available.");
        } else {
          const raw = await response.text();
          if (raw.length > 32768) throw new Error("invalid device response");
          const data = JSON.parse(raw);
          if (data?.ok !== true || data?.available !== true ||
              data?.ownerScoped !== true || !Array.isArray(data.devices)) {
            throw new Error("unverified device response");
          }
          const count = data.devices.length;
          show(
            count ? "승인된 컴퓨터 " + count + "대가 있습니다. 작업 시 별도 승인이 필요합니다." : "아직 승인된 컴퓨터가 없습니다.",
            count ? count + " approved computer(s). Tasks still require approval." : "No approved computers yet.",
          );
        }
      } catch (_) {
        show("컴퓨터 연결 상태를 확인하지 못했습니다.", "Could not verify computer connection.");
      } finally {
        deviceStatus.disabled = false;
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
