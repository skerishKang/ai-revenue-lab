// #7216 R5 2단계 — 캘린더 구역 (app.js 클로저에서 이동).
// 동작·문구·DOM id·이벤트 이름 변경 없음. 공유 상태와 DOM 참조는 deps getter/
// setter로만 읽고 쓴다. app.js는 같은 이름의 한 줄 전달 함수를 유지한다.
(() => {
  "use strict";
  window.PadiemChatCalendarModule = {
    create(deps) {
      const CALENDAR_READ_STATES = Object.freeze(["unknown", "activating", "active", "failed", "unavailable"]);
      const CALENDAR_READ_STATE_KEYS = Object.freeze({
        unknown: "connectors-calendar-read-pending",
        activating: "connectors-calendar-read-activating",
        active: "connectors-calendar-read-active",
        failed: "connectors-calendar-read-failed",
        unavailable: "connectors-calendar-read-unavailable",
      });
      // The closed per-row vocabulary the status projection publishes for the
      // Calendar row's persisted READ grant axis.
      const CALENDAR_SERVER_GRANT_STATES = Object.freeze(["active", "inactive", "unavailable"]);

      // Bounded backend-code → copy mapping (#3451 reviewed diagnostics). Only
      // this closed, reviewed, secret-free vocabulary gets entries; anything else
      // — including any future code CENTRAL has not reviewed — falls back to the
      // generic OAuth-preserving message. The server's raw message text is never
      // rendered and no credential material is read from the body.
      const CALENDAR_READ_ERROR_KEYS = Object.freeze({
        "calendar_activation_engine_auth_failed": "connectors-calendar-read-error-engine-auth",
        "calendar_activation_workspace_unavailable": "connectors-calendar-read-error-workspace",
        "calendar_activation_binding_unavailable": "connectors-calendar-read-error-binding",
        "calendar_activation_not_connected": "connectors-calendar-read-error-not-connected",
        "calendar_activation_grant_unavailable": "connectors-calendar-read-error-grant",
        "calendar_read_activation_unavailable": "connectors-calendar-read-activation-error",
      });

      function calendarReadStateKey(state) {
        return Object.prototype.hasOwnProperty.call(CALENDAR_READ_STATE_KEYS, state)
          ? CALENDAR_READ_STATE_KEYS[state]
          : "connectors-calendar-read-pending";
      }

      function calendarServerGrantSessionState(current, serverState) {
        if (!CALENDAR_SERVER_GRANT_STATES.includes(serverState)) return current;
        if (current !== "unknown" && current !== "unavailable") return current;
        return serverState === "inactive" ? "unknown" : serverState;
      }

      function calendarReadActivationErrorKey(error) {
        const code = error && typeof error === "object" && typeof error.calendarReadErrorCode === "string"
          ? error.calendarReadErrorCode
          : "";
        return Object.prototype.hasOwnProperty.call(CALENDAR_READ_ERROR_KEYS, code)
          ? CALENDAR_READ_ERROR_KEYS[code]
          : "connectors-calendar-read-activation-error";
      }

      function googleCalendarConnectButton() {
        const scope = deps.connectorsScope();
        if (!scope) return null;
        try {
          return scope.querySelector(`[data-google-connector-connect="${deps.GOOGLE_CALENDAR_CONNECTOR}"]`);
        } catch (_) {
          return null;
        }
      }

      function googleCalendarCard() {
        const scope = deps.connectorsScope();
        if (!scope) return null;
        try {
          return scope.querySelector(`[data-connector-id="connector:google:calendar@1"]`);
        } catch (_) {
          return null;
        }
      }

      function renderCalendarReadState() {
        const card = googleCalendarCard();
        if (!card) return;
        const element = card.querySelector("[data-connector-read-state]");
        if (!element) return;
        const state = CALENDAR_READ_STATES.includes(deps.googleCalendarReadState)
          ? deps.googleCalendarReadState
          : "unknown";
        if (card.dataset.connectorStatus !== "connected") {
          element.hidden = true;
          delete card.dataset.calendarReadState;
          return;
        }
        // The visual states are the four reviewed ones: an in-session "unknown"
        // grant presents as "pending" — activation has not happened here yet.
        const visualState = state === "unknown" ? "pending" : state;
        element.hidden = false;
        element.dataset.readState = visualState;
        card.dataset.calendarReadState = state;
        deps.setConnectorCopy(element, calendarReadStateKey(state));
      }

      function syncGoogleCalendarConnectButton(row = null) {
        // Consume the persisted server truth for the READ grant axis before the
        // button logic: a fresh session must show the server's answer, not
        // "activation needed" for a grant the Engine already holds.
        const serverGrantState =
          row && typeof row.calendar_read_grant_state === "string"
            ? row.calendar_read_grant_state
            : "";
        deps.googleCalendarReadState = calendarServerGrantSessionState(
          deps.googleCalendarReadState,
          serverGrantState,
        );
        const button = googleCalendarConnectButton();
        const calendarCard = googleCalendarCard();
        if (calendarCard) {
          // When the OAuth/workspace axis is connected, say so in Calendar-specific
          // words: a connected Google account is not the same truth as an active
          // Calendar READ grant. The generic workspace copy stays for every other
          // connector.
          if (row && row.workspace_state === "connected") {
            deps.setConnectorCopy(calendarCard.querySelector("[data-connector-workspace]"), "connectors-calendar-oauth-connected");
          }
          renderCalendarReadState();
        }
        if (!button) return;
        const workspaceState = row && typeof row.workspace_state === "string" ? row.workspace_state : "";
        const canConnect = Boolean(
          deps.authState.authenticated &&
          (workspaceState === "not_connected" || workspaceState === "unverified")
        );
        const canActivateRead = Boolean(
          deps.authState.authenticated &&
          workspaceState === "connected"
        );
        button.hidden = !(canConnect || canActivateRead);
        button.dataset.calendarAction = canActivateRead ? "activate-read" : "connect";
        button.disabled = deps.googleConnectorConnectInFlight ||
          deps.googleCalendarReadState === "activating" ||
          deps.googleCalendarReadState === "active";
        if (deps.googleCalendarReadState === "active") {
          deps.setConnectorCopy(button, "connectors-calendar-read-activation-done");
        } else if (canActivateRead && deps.googleCalendarReadState !== "activating") {
          deps.setConnectorCopy(button, "connectors-activate-calendar-read");
        } else if (canConnect && !deps.googleConnectorConnectInFlight) {
          deps.setConnectorCopy(button, "connectors-connect-calendar");
        }
      }

      async function beginGoogleCalendarConnect() {
        const button = googleCalendarConnectButton();
        if (!button || deps.googleConnectorConnectInFlight) return;
        if (!deps.authState.authenticated) {
          deps.openAuthDialog();
          return;
        }
        deps.googleConnectorConnectInFlight = true;
        button.disabled = true;
        deps.setConnectorCopy(button, "connectors-connecting-calendar");
        if (deps.connectorsError) deps.connectorsError.hidden = true;
        try {
          const startResponse = await deps.fetch(deps.GOOGLE_CALENDAR_TICKET_ENDPOINT, {
            method: "POST",
            headers: { "Accept": "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({ connector_id: deps.GOOGLE_CALENDAR_CONNECTOR, begin_oauth: true }),
            cache: "no-store",
          });
          const startDocument = await startResponse.json().catch(() => null);
          const authorization = startDocument && startDocument.authorization;
          const redirect = startResponse.ok && authorization &&
            authorization.connector_id === deps.GOOGLE_CALENDAR_CONNECTOR
            ? deps.reviewedGoogleAuthorizationUrl(authorization.authorization_url)
            : null;
          if (!redirect) throw new Error("calendar authorization unavailable");
          window.location.assign(redirect);
        } catch (_) {
          deps.googleConnectorConnectInFlight = false;
          button.disabled = false;
          deps.setConnectorCopy(button, "connectors-connect-calendar");
          if (deps.connectorsError) {
            deps.setConnectorCopy(deps.connectorsError, "connectors-connect-error");
            deps.connectorsError.hidden = false;
          }
        }
      }

      async function activateGoogleCalendarRead() {
        const button = googleCalendarConnectButton();
        if (!button || deps.googleCalendarReadState === "activating" || deps.googleCalendarReadState === "active") return;
        if (!deps.authState.authenticated) {
          deps.openAuthDialog();
          return;
        }
        deps.googleCalendarReadState = "activating";
        button.disabled = true;
        deps.setConnectorCopy(button, "connectors-activating-calendar-read");
        renderCalendarReadState();
        if (deps.connectorsError) deps.connectorsError.hidden = true;
        try {
          const response = await deps.fetch(deps.GOOGLE_CALENDAR_READ_ACTIVATION_ENDPOINT, {
            method: "POST",
            headers: { "Accept": "application/json", "Content-Type": "application/json" },
            body: JSON.stringify({}),
            cache: "no-store",
          });
          const data = await response.json().catch(() => null);
          if (!response.ok || !data || data.ok !== true ||
              data.calendar_read_grant !== "active" ||
              data.calendar_write_authorized !== false) {
            // Only the bounded code travels; the server's raw message text is never
            // rendered and no credential material is read from the body.
            const failure = new Error("calendar read activation unavailable");
            failure.calendarReadErrorCode =
              data && typeof data === "object" &&
              data.error && typeof data.error === "object" &&
              typeof data.error.code === "string"
                ? data.error.code
                : "";
            throw failure;
          }
          deps.googleCalendarReadState = "active";
          deps.setConnectorCopy(button, "connectors-calendar-read-activation-done");
          renderCalendarReadState();
        } catch (error) {
          // The Google OAuth/workspace connection is untouched by an activation
          // failure: the card keeps the connected-account copy and the failure
          // copy says exactly that, so a grant problem is never presented as an
          // OAuth one. The cause-specific wording comes from the locale table,
          // keyed by the bounded backend code (see CALENDAR_READ_ERROR_KEYS).
          deps.googleCalendarReadState = "failed";
          renderCalendarReadState();
          if (deps.connectorsError) {
            deps.setConnectorCopy(deps.connectorsError, calendarReadActivationErrorKey(error));
            deps.connectorsError.hidden = false;
          }
          deps.setConnectorCopy(button, "connectors-activate-calendar-read");
        } finally {
          button.disabled = deps.googleCalendarReadState === "active";
        }
      }
      return {
        calendarReadStateKey, calendarServerGrantSessionState, calendarReadActivationErrorKey,
        googleCalendarConnectButton, googleCalendarCard, renderCalendarReadState,
        syncGoogleCalendarConnectButton, beginGoogleCalendarConnect, activateGoogleCalendarRead,
      };
    },
  };
})();
