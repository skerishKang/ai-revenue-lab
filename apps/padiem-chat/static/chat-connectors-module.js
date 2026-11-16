// #7216 R5 A9 — Web Claw connector surface: status card projection, the
// reviewed Google Drive / Gmail connect handoff, and the standalone
// Connectors page mount. Moved verbatim from app.js; the declarations (DOM
// refs, connector constants, in-flight state) stay in app.js and are reached
// through deps, and app.js keeps the OAuth-return handling, one-line
// forwarders and a single wire call at the original listener position.
(() => {
  "use strict";

  window.PadiemChatConnectorsModule = {
    create(deps) {
      const connectorsNavButton = document.getElementById("connectorsNavButton");
      const connectorsDialog = document.getElementById("connectorsDialog");
      const connectorsDialogClose = document.getElementById("connectorsDialogClose");
      const connectorsLoading = document.getElementById("connectorsLoading");
      const connectorsRetry = document.getElementById("connectorsRetry");
      // #3289: the reviewed Google Drive READ-only connect handoff reuses the
      // same reviewed ticket endpoint; only the reviewed connector id differs.
      const GOOGLE_DRIVE_CONNECTOR = "google-drive";
      const GOOGLE_DRIVE_TICKET_ENDPOINT = "/api/connectors/google/ticket";
      // #7088: Gmail joins the same reviewed READ-only connect handoff with its
      // already-registered readonly scope set.
      const GOOGLE_GMAIL_CONNECTOR = "gmail";
      const GOOGLE_GMAIL_TICKET_ENDPOINT = "/api/connectors/google/ticket";
      const CONNECTOR_STATUS_IDS = new Set([
        "connector:google:drive@1",
        "connector:google:gmail@1",
        "connector:telegram:bot@1",
        "connector:slack:workspace@1",
        "connector:google:calendar@1",
      ]);
      let connectorStatusInFlight = false;
      // Standalone-page mount flag (R5 A9): the let sat with the moved
      // mountConnectorsView body; the module owns it as create-scoped state.
      let connectorsViewMounted = false;
      function setConnectorCopy(element, key) {
        if (!element) return;
        element.dataset.localeKey = key;
        element.textContent = deps.uiT(key);
      }

      function connectorSupportKey(value) {
        if (value === "complete") return "connectors-support-complete";
        if (value === "source_ready") return "connectors-support-source-ready";
        if (value === "deferred") return "connectors-support-deferred";
        return "connectors-status-unavailable";
      }

      function connectorWorkspaceKey(value) {
        if (value === "connected") return "connectors-workspace-connected";
        if (value === "not_connected") return "connectors-workspace-not-connected";
        if (value === "ambiguous") return "connectors-workspace-ambiguous";
        if (value === "unverified") {
          return deps.authState.authenticated
            ? "connectors-workspace-unverified"
            : "connectors-workspace-sign-in";
        }
        return "connectors-workspace-unverified";
      }

      function connectorUnavailableCopyKeys(connectorId) {
        if (connectorId === "connector:telegram:bot@1" || connectorId === "connector:slack:workspace@1") {
          return { support: "connectors-workspace-unverified", workspace: "connectors-workspace-unverified" };
        }
        return { support: "connectors-status-unavailable", workspace: "connectors-workspace-unavailable" };
      }

      function liveConnectorCards() {
        const scope = connectorsScope();
        if (!scope) return [];
        try {
          return Array.from(scope.querySelectorAll("[data-connector-id]"));
        } catch (_) {
          return [];
        }
      }

      function googleDriveConnectButton() {
        const scope = connectorsScope();
        if (!scope) return null;
        try {
          return scope.querySelector(`[data-google-connector-connect="${GOOGLE_DRIVE_CONNECTOR}"]`);
        } catch (_) {
          return null;
        }
      }

      function googleDriveCard() {
        const scope = connectorsScope();
        if (!scope) return null;
        try {
          return scope.querySelector(`[data-connector-id="connector:google:drive@1"]`);
        } catch (_) {
          return null;
        }
      }

      function gmailConnectButton() {
        const scope = connectorsScope();
        if (!scope) return null;
        try {
          return scope.querySelector(`[data-google-connector-connect="${GOOGLE_GMAIL_CONNECTOR}"]`);
        } catch (_) {
          return null;
        }
      }

      function driveConnectOffered(authenticated, workspaceState) {
        return Boolean(authenticated && workspaceState === "not_connected");
      }

      function syncGoogleDriveConnectButton(row = null) {
        const button = googleDriveConnectButton();
        if (!button) return;
        const workspaceState = row && typeof row.workspace_state === "string" ? row.workspace_state : "";
        const offered = driveConnectOffered(deps.authState.authenticated, workspaceState);
        button.hidden = !offered;
        button.disabled = deps.googleConnectorConnectInFlight;
        if (offered && !deps.googleConnectorConnectInFlight) {
          setConnectorCopy(button, "connectors-connect-drive");
        }
      }

      function connectorTicketErrorKey(startDocument, fallbackKey) {
        const code = startDocument && startDocument.error && startDocument.error.code;
        return code === "connector_ticket_origin_not_canonical" ? "connectors-connect-canonical-only" : fallbackKey;
      }

      async function beginGoogleDriveConnect() {
        const button = googleDriveConnectButton();
        if (!button || deps.googleConnectorConnectInFlight) return;
        if (!deps.authState.authenticated) {
          deps.openAuthDialog();
          return;
        }
        deps.googleConnectorConnectInFlight = true;
        button.disabled = true;
        setConnectorCopy(button, "connectors-connecting-drive");
        if (deps.connectorsError) deps.connectorsError.hidden = true;
        let ticketErrorKey = "connectors-connect-drive-error";
        try {
          // Exactly one ticket POST per user attempt. The raw connect ticket is
          // never handed to this scope: the reviewed route performs the single
          // OAuth-edge exchange server-side and answers with the bounded
          // authorization shape only, so no ticket, provider or credential
          // material can reach the DOM, storage, logs or the query string.
          const startResponse = await fetch(GOOGLE_DRIVE_TICKET_ENDPOINT, {
            method: "POST",
            headers: { "Accept": "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({ connector_id: GOOGLE_DRIVE_CONNECTOR, begin_oauth: true }),
            cache: "no-store",
          });
          const startDocument = await startResponse.json().catch(() => null);
          const authorization = startDocument && startDocument.authorization;
          const redirect = startResponse.ok && authorization &&
            authorization.connector_id === GOOGLE_DRIVE_CONNECTOR
            ? deps.reviewedGoogleAuthorizationUrl(authorization.authorization_url)
            : null;
          if (!redirect) ticketErrorKey = connectorTicketErrorKey(startDocument, ticketErrorKey);
          if (!redirect) throw new Error("drive authorization unavailable");
          window.location.assign(redirect);
        } catch (_) {
          // Bounded failure with no automatic retry: only a new explicit user
          // gesture starts another attempt, and this attempt's state is dropped.
          deps.googleConnectorConnectInFlight = false;
          button.disabled = false;
          setConnectorCopy(button, "connectors-connect-drive");
          if (deps.connectorsError) {
            setConnectorCopy(deps.connectorsError, ticketErrorKey);
            deps.connectorsError.hidden = false;
          }
        }
      }

      function syncGmailConnectButton(row = null) {
        const button = gmailConnectButton();
        if (!button) return;
        const workspaceState = row && typeof row.workspace_state === "string" ? row.workspace_state : "";
        const offered = driveConnectOffered(deps.authState.authenticated, workspaceState);
        button.hidden = !offered;
        button.disabled = deps.googleConnectorConnectInFlight;
        if (offered && !deps.googleConnectorConnectInFlight) {
          setConnectorCopy(button, "connectors-connect-gmail");
        }
      }

      async function beginGmailConnect() {
        const button = gmailConnectButton();
        if (!button || deps.googleConnectorConnectInFlight) return;
        if (!deps.authState.authenticated) {
          deps.openAuthDialog();
          return;
        }
        deps.googleConnectorConnectInFlight = true;
        button.disabled = true;
        setConnectorCopy(button, "connectors-connecting-gmail");
        if (deps.connectorsError) deps.connectorsError.hidden = true;
        let ticketErrorKey = "connectors-connect-drive-error";
        try {
          const startResponse = await fetch(GOOGLE_GMAIL_TICKET_ENDPOINT, {
            method: "POST",
            headers: { "Accept": "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({ connector_id: GOOGLE_GMAIL_CONNECTOR, begin_oauth: true }),
            cache: "no-store",
          });
          const startDocument = await startResponse.json().catch(() => null);
          const authorization = startDocument && startDocument.authorization;
          const redirect = startResponse.ok && authorization &&
            authorization.connector_id === GOOGLE_GMAIL_CONNECTOR
            ? deps.reviewedGoogleAuthorizationUrl(authorization.authorization_url)
            : null;
          if (!redirect) ticketErrorKey = connectorTicketErrorKey(startDocument, ticketErrorKey);
          if (!redirect) throw new Error("gmail authorization unavailable");
          window.location.assign(redirect);
        } catch (_) {
          // Bounded failure with no automatic retry: only a new explicit user
          // gesture starts another attempt, and this attempt's state is dropped.
          deps.googleConnectorConnectInFlight = false;
          button.disabled = false;
          setConnectorCopy(button, "connectors-connect-gmail");
          if (deps.connectorsError) {
            setConnectorCopy(deps.connectorsError, ticketErrorKey);
            deps.connectorsError.hidden = false;
          }
        }
      }

      function setConnectorCardsLoading() {
        liveConnectorCards().forEach((card) => {
          card.dataset.connectorStatus = "loading";
          setConnectorCopy(card.querySelector("[data-connector-support]"), "connectors-status-loading");
          setConnectorCopy(card.querySelector("[data-connector-workspace]"), "connectors-workspace-loading");
        });
        deps.syncGoogleCalendarConnectButton();
        syncGoogleDriveConnectButton();
        syncGmailConnectButton();
      }

      function setConnectorCardsUnavailable() {
        liveConnectorCards().forEach((card) => {
          card.dataset.connectorStatus = "unavailable";
          const keys = connectorUnavailableCopyKeys(card.dataset.connectorId);
          setConnectorCopy(card.querySelector("[data-connector-support]"), keys.support);
          setConnectorCopy(card.querySelector("[data-connector-workspace]"), keys.workspace);
        });
        deps.syncGoogleCalendarConnectButton();
        syncGoogleDriveConnectButton();
        syncGmailConnectButton();
      }

      function renderConnectorStatus(document) {
        if (!document || document.static_support_vs_workspace_state_separated !== true ||
            document.send_write_authorized !== false || !Array.isArray(document.connectors)) {
          throw new Error("connector status unavailable");
        }
        const rows = new Map();
        document.connectors.forEach((row) => {
          if (!row || typeof row.connector_id !== "string" || !CONNECTOR_STATUS_IDS.has(row.connector_id)) return;
          rows.set(row.connector_id, row);
        });
        liveConnectorCards().forEach((card) => {
          const connectorId = card.dataset.connectorId;
          const row = rows.get(connectorId);
          if (!row) {
            card.dataset.connectorStatus = "unavailable";
            setConnectorCopy(card.querySelector("[data-connector-support]"), "connectors-status-unavailable");
            setConnectorCopy(card.querySelector("[data-connector-workspace]"), "connectors-workspace-unavailable");
            return;
          }
          const supportKey = connectorSupportKey(row.read_availability);
          const workspaceKey = connectorWorkspaceKey(row.workspace_state);
          card.dataset.connectorStatus = String(row.workspace_state || "unverified");
          setConnectorCopy(card.querySelector("[data-connector-support]"), supportKey);
          setConnectorCopy(card.querySelector("[data-connector-workspace]"), workspaceKey);
        });
        deps.syncGoogleCalendarConnectButton(rows.get("connector:google:calendar@1") || null);
        syncGoogleDriveConnectButton(rows.get("connector:google:drive@1") || null);
        syncGmailConnectButton(rows.get("connector:google:gmail@1") || null);
      }

      async function loadConnectorStatus() {
        if (!connectorsDialog || connectorStatusInFlight) return;
        connectorStatusInFlight = true;
        if (connectorsLoading) connectorsLoading.hidden = false;
        if (deps.connectorsError) {
          setConnectorCopy(deps.connectorsError, "connectors-error");
          deps.connectorsError.hidden = true;
        }
        if (connectorsRetry) {
          connectorsRetry.hidden = true;
          connectorsRetry.disabled = true;
        }
        setConnectorCardsLoading();
        try {
          // #7368: a front-edge loss (502/503/504) or a network error asks one
          // more time after 0.8s. The checking state persists through the retry,
          // and a second failure keeps the same unavailable answer as before.
          const response = await window.PadiemChatTransport.fetchStatusWithRetry("/api/connectors/status", {
            headers: { "Accept": "application/json" },
            cache: "no-store",
          });
          const data = await response.json().catch(() => null);
          if (!response.ok) throw new Error("connector status unavailable");
          renderConnectorStatus(data);
          if (deps.googleCalendarReadActivationAfterConnectReturn) {
            deps.googleCalendarReadActivationAfterConnectReturn = false;
            const calendarButton = deps.googleCalendarConnectButton();
            if (calendarButton?.dataset.calendarAction === "activate-read") {
              await deps.activateGoogleCalendarRead();
            }
          }
        } catch (_) {
          setConnectorCardsUnavailable();
          if (deps.connectorsError) deps.connectorsError.hidden = false;
          if (connectorsRetry) connectorsRetry.hidden = false;
        } finally {
          connectorStatusInFlight = false;
          if (connectorsLoading) connectorsLoading.hidden = true;
          if (connectorsRetry) connectorsRetry.disabled = false;
        }
      }

      function connectorsScope() {
        try {
          const body = document.getElementById("connectorsViewBody");
          if (body && body.querySelector("[data-connector-id]")) return body;
        } catch (_) {}
        return connectorsDialog;
      }

      function mountConnectorsView() {
        if (connectorsViewMounted) return;
        let body = null;
        let grid = null;
        let status = null;
        try {
          body = document.getElementById("connectorsViewBody");
          grid = connectorsDialog ? connectorsDialog.querySelector(".capability-grid") : null;
          status = document.getElementById("connectorsLiveStatus");
        } catch (_) {
          return;
        }
        if (!body || !grid) return;
        if (status) body.appendChild(status);
        body.appendChild(grid);
        connectorsViewMounted = true;
      }

      function openConnectorsView() {
        mountConnectorsView();
        const view = document.getElementById("connectorsView");
        if (view) view.hidden = false;
        deps.shell.dataset.state = "connectors";
        deps.setNavActive();
        deps.closeSidebar();
        if (connectorsNavButton) connectorsNavButton.setAttribute("aria-expanded", "false");
        void loadConnectorStatus();
      }

      function openConnectorsDialog() {
        openConnectorsView();
      }

      function closeConnectorsDialog() {
        if (!connectorsDialog) return;
        if (connectorsDialog.open && typeof connectorsDialog.close === "function") connectorsDialog.close();
        else connectorsDialog.removeAttribute("open");
        if (connectorsNavButton) {
          connectorsNavButton.setAttribute("aria-expanded", "false");
          // Return focus to the sidebar entry that opened it.
          if (typeof connectorsNavButton.focus === "function") connectorsNavButton.focus();
        }
      }

      // Original listener registrations from app.js, called at the original
      // block position so the registration timing and order are preserved.
      function wireConnectorsListeners() {
        if (connectorsNavButton) connectorsNavButton.addEventListener("click", openConnectorsView);
        if (connectorsDialogClose) connectorsDialogClose.addEventListener("click", closeConnectorsDialog);
        if (connectorsRetry) connectorsRetry.addEventListener("click", () => void loadConnectorStatus());
        document.addEventListener("padiem:refresh-connector-status", () => void loadConnectorStatus());
        const calendarConnectButton = window.PadiemChatCalendarModule ? deps.googleCalendarConnectButton() : null;
        if (calendarConnectButton) calendarConnectButton.addEventListener("click", () => {
          if (calendarConnectButton.dataset.calendarAction === "activate-read") {
            void deps.activateGoogleCalendarRead();
            return;
          }
          void deps.beginGoogleCalendarConnect();
        });
        // #3289: Drive connect starts only from this explicit user gesture.
        const driveConnectButton = googleDriveConnectButton();
        if (driveConnectButton) driveConnectButton.addEventListener("click", () => {
          void beginGoogleDriveConnect();
        });
        // #7088: Gmail connect starts only from this explicit user gesture.
        const gmailConnectButtonEl = gmailConnectButton();
        if (gmailConnectButtonEl) gmailConnectButtonEl.addEventListener("click", () => {
          void beginGmailConnect();
        });
        document.addEventListener("padiem:drive-quick-connect", () => {
          void (async () => {
            // Existing server-trusted workspace truth, not a synthetic OFF.
            await loadConnectorStatus();
            const offered = googleDriveConnectButton();
            if (offered && !offered.hidden && !offered.disabled) {
              offered.click();
            } else {
              openConnectorsDialog();
            }
          })();
        });
        if (connectorsDialog) {
          connectorsDialog.addEventListener("cancel", (event) => {
            event.preventDefault();
            closeConnectorsDialog();
          });
          connectorsDialog.addEventListener("close", () => connectorsNavButton?.setAttribute("aria-expanded", "false"));
        }
      }

      return {
        setConnectorCopy,
        connectorSupportKey,
        connectorWorkspaceKey,
        connectorUnavailableCopyKeys,
        liveConnectorCards,
        googleDriveConnectButton,
        googleDriveCard,
        gmailConnectButton,
        driveConnectOffered,
        syncGoogleDriveConnectButton,
        connectorTicketErrorKey,
        beginGoogleDriveConnect,
        syncGmailConnectButton,
        beginGmailConnect,
        setConnectorCardsLoading,
        setConnectorCardsUnavailable,
        renderConnectorStatus,
        loadConnectorStatus,
        connectorsScope,
        mountConnectorsView,
        openConnectorsView,
        openConnectorsDialog,
        closeConnectorsDialog,
        wireConnectorsListeners,
      };
    },
  };
})();
