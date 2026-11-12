// #7216 R5 A4 — Claw status, pre-dispatch retry, and in-flight elapsed wait.
// Moved verbatim from app.js; app.js keeps one-line forwarders and reads
// closure state live via getters and setters.
(() => {
  "use strict";

  window.PadiemChatClawStatusModule = {
    create(deps) {
      const CLAW_WAIT_TICK_MS = 1000;
      const CLAW_WAIT_REVEAL_MS = 3000;
      const CLAW_WAIT_LONG_SECONDS = 10;
      const CLAW_WAIT_VERY_LONG_SECONDS = 30;

      function syncComposerForClaw(isClaw) {
        const { input, shell, clawWorkspace } = deps;
        if (!input) return;
        if (isClaw) shell.dataset.clawTier = deps.selectedProductTier();
        // #3531: the business-request prompt belongs to the explicit manual
        // workflow view only. The general Claw view shares the generic prompt
        // so placeholder parity with Chat Home holds.
        const manualView = isClaw && clawWorkspace && clawWorkspace.dataset.view === "manual";
        if (manualView) {
          input.placeholder = deps.localeOr("claw-request-placeholder", "Paste a business request you received by chat, SMS, or email.");
          input.setAttribute("aria-describedby", "clawStatus");
          // Executable Claw task authority is validated by the server.
          // No separate pilot-era 4,000-character browser ceiling.
        } else {
          // #7166: the general Claw view gets its own one-line placeholder so the
          // shared composer says what Claw does instead of repeating Chat's.
          input.placeholder = isClaw
            ? deps.localeOr("claw-input-placeholder", "What can I do? e.g. tidy files")
            : deps.localeOr("input", "Ask anything");
          input.removeAttribute("aria-describedby");
          input.removeAttribute("aria-invalid");
          // General Claw and Chat accept provider-native prompts. The distinct
          // manual executable tasks keep their separate tool authorization and bounds.
          input.removeAttribute("maxlength");
        }
      }

      function setClawStatus(message, state, localeKey) {
        const { clawStatus, input } = deps;
        if (!clawStatus) return;
        if (!message) {
          clawStatus.hidden = true;
          clawStatus.textContent = "";
          clawStatus.removeAttribute("data-state");
          clawStatus.classList?.remove?.("padiem-activity-sweep");
          input.removeAttribute("aria-invalid");
          return;
        }
        clawStatus.hidden = false;
        clawStatus.textContent = message;
        if (state) clawStatus.dataset.state = state;
        else clawStatus.removeAttribute("data-state");
        // #5453: the sweep only rides a state the run is really in.
        clawStatus.classList?.toggle?.("padiem-activity-sweep", state === "running");
        if (localeKey) clawStatus.dataset.localeKey = localeKey;
        else delete clawStatus.dataset.localeKey;
        if (state === "error") input.setAttribute("aria-invalid", "true");
        else input.removeAttribute("aria-invalid");
      }

      function setClawAreaState(state) {
        const { clawResultArea } = deps;
        if (clawResultArea) clawResultArea.dataset.clawState = state;
      }

      function setClawButtonsBusy(busy) {
        deps.clawInFlight = busy;
        const busyVal = busy ? "true" : "false";
        const { clawGenerateBtn, clawExecuteButton } = deps;
        if (clawGenerateBtn) {
          clawGenerateBtn.disabled = busy;
          clawGenerateBtn.setAttribute("aria-busy", busyVal);
          clawGenerateBtn.setAttribute("aria-disabled", String(busy));
        }
        if (clawExecuteButton) {
          // A running pre-dispatch cooldown, and an ambiguous outcome whose dispatch
          // cannot be ruled out, both block the one manual-execute entry point. The
          // draft/preview button and the chat lane stay available: they are separate
          // requests with their own server-side bounds.
          const blocked = busy || clawRetryRemaining() > 0 || clawCurrentDispatchIsUncertain();
          clawExecuteButton.disabled = blocked;
          clawExecuteButton.setAttribute("aria-busy", busyVal);
          clawExecuteButton.setAttribute("aria-disabled", String(blocked));
        }
      }

      // ── Pre-dispatch execute recovery (#2760) ───────────────────────────────
      //
      // Dispatch certainty decides retryability. The server-side UsageGate runs
      // BEFORE P01/Engine dispatch, so a 429 that carries a bounded numeric
      // Retry-After is a known pre-dispatch denial: the browser may offer an
      // explicit, user-pressed retry once that cooldown expires. Failures where a
      // dispatch may already have happened (browser network error, the engine
      // execution-failure family) are ambiguous, so they get a "check Recent runs
      // first" hint and never a retry affordance.
      //
      // Retry target: the CURRENT VISIBLE FORM, re-read at click time. No hidden
      // payload snapshot is stored, so a stale request cannot be replayed. Nothing
      // in this block submits on a timer; the ticker only re-renders copy and
      // control state. No auto-retry, no provider retry, no server policy change.
      // The bound lives on the SERVER, not here (#5882 A-15). app/usage_gate.py is
      // the only producer of Retry-After on these routes and it emits a fixed
      // integer — 60s for the minute bucket — while quota_exhausted and
      // service_limit_reached carry no header at all (claw_routes.py:270 guards the
      // emission). A second 900s client re-clamp could therefore never bind; it only
      // risked disagreeing with the server and blocking this form for a ceiling the
      // server is not enforcing. The parsed seconds are used exactly as sent, and
      // the closed parse below is what fails closed on malformed/negative/HTTP-date
      // values instead of a ceiling.

      function clawRetryRemaining() {
        return deps.clawRetrySeconds > 0 ? deps.clawRetrySeconds : 0;
      }

      // The manual-execute lane's duplicate check compares WIRE CONTENT, so the
      // request shape is assembled in exactly one place and reused by both the
      // dispatch and the comparison. Canonical conversation reuse (#2916): forward
      // only the exact handle this page already owns; the browser never mints one.
      // The model ID field is deliberately absent — /api/claw/manual-intake/execute
      // does not read it (it selects the conversation lane only), so changing it
      // cannot make the next run a different request.
      function clawVisibleExecutePayload() {
        const { input, clawChannel, clawAction, clawSender } = deps;
        const body = (input.value || "").trim();
        const channelValue = clawChannel?.value || "other";
        const actionValue = clawAction?.value || "quote";
        const senderText = (clawSender?.value || "").trim();
        const activeConversationId = deps.conversationState.getConversationId();
        const executePayload = {
          content: body,
          channel: channelValue,
          action: actionValue,
          sender_hint: senderText || null,
          tier: deps.selectedProductTier(),
        };
        if (typeof activeConversationId === "string" && activeConversationId) {
          executePayload.conversation_id = activeConversationId;
        }
        return executePayload;
      }

      function clawExecuteWireKey(payload) {
        return JSON.stringify([
          payload.content,
          payload.channel,
          payload.action,
          payload.sender_hint ?? null,
          payload.tier,
          payload.conversation_id ?? null,
        ]);
      }

      // Availability is derived from the request the form would send RIGHT NOW, so it
      // is re-evaluated on every edit rather than released once by an edit event.
      function clawCurrentDispatchIsUncertain() {
        return deps.clawUncertainKeys.size > 0
          && deps.clawUncertainKeys.has(clawExecuteWireKey(clawVisibleExecutePayload()));
      }

      function noteClawContentEdited() {
        if (deps.clawUncertainKeys.size === 0) return;
        setClawButtonsBusy(deps.clawInFlight);
      }

      // Closed parse: integer seconds only, positive. Missing, non-integer, zero,
      // negative and HTTP-date (RFC 7231) values make no countdown claim — the copy
      // then falls back to the safe rate-limit sentence with no fabricated number.
      function parseClawRetryAfter(value) {
        if (typeof value !== "string") return null;
        const raw = value.trim();
        if (!/^[0-9]+$/.test(raw)) return null;
        const seconds = Number.parseInt(raw, 10);
        if (!Number.isFinite(seconds) || seconds < 1) return null;
        return seconds;
      }

      function clawRetryAfterFromResponse(response) {
        try {
          const headers = response && response.headers;
          if (!headers || typeof headers.get !== "function") return null;
          return parseClawRetryAfter(headers.get("Retry-After"));
        } catch (_) {
          return null;
        }
      }

      // Ambiguous = the request may already have reached the engine, so a second
      // POST could double-run it. This is a closed allowlist: on this route the
      // adapter reports Engine unbound/timeout/unreachable and malformed P01
      // responses as `engine_execution_failed` with status 502, and the #830
      // invariant keeps a dispatched or ambiguous failure counted rather than
      // refunded. Every other bounded failure (input, auth, limit, storage,
      // run-history, tier) is a pre-dispatch denial or a post-run persistence
      // problem with its own copy, so it must never claim a possible dispatch.
      function isAmbiguousClawFailure(data, response) {
        const status = response ? response.status : 0;
        const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
        return status === 502 || code === "engine_execution_failed";
      }

      function stopClawRetryTimer() {
        const timer = deps.clawRetryTimer;
        if (timer) {
          clearInterval(timer);
          deps.clawRetryTimer = null;
        }
      }

      function clearClawRecovery(options = {}) {
        stopClawRetryTimer();
        deps.clawRetrySeconds = 0;
        const { clawRetryBox, clawRetryCopy, clawRetryButton, clawRetryHint } = deps;
        if (clawRetryBox) clawRetryBox.hidden = true;
        if (clawRetryCopy) clawRetryCopy.textContent = "";
        if (clawRetryButton) {
          clawRetryButton.disabled = true;
          clawRetryButton.setAttribute("aria-disabled", "true");
        }
        if (clawRetryHint) {
          clawRetryHint.hidden = true;
          clawRetryHint.textContent = "";
          delete clawRetryHint.dataset.localeKey;
        }
        if (options.syncControls) setClawButtonsBusy(deps.clawInFlight);
      }

      function renderClawRetryBox() {
        const remaining = clawRetryRemaining();
        const { clawRetryCopy, clawRetryButton } = deps;
        if (clawRetryCopy) {
          clawRetryCopy.textContent = remaining > 0
            ? deps.clawT("claw-retry-waiting", { seconds: remaining })
            : deps.clawT("claw-retry-ready");
        }
        if (clawRetryButton) {
          clawRetryButton.disabled = remaining > 0;
          clawRetryButton.setAttribute("aria-disabled", remaining > 0 ? "true" : "false");
        }
      }

      function beginClawRetryCooldown(seconds) {
        stopClawRetryTimer();
        deps.clawRetrySeconds = seconds;
        const { clawRetryHint, clawRetryBox } = deps;
        if (clawRetryHint) {
          clawRetryHint.hidden = true;
          clawRetryHint.textContent = "";
          delete clawRetryHint.dataset.localeKey;
        }
        if (clawRetryBox) clawRetryBox.hidden = false;
        renderClawRetryBox();
        setClawButtonsBusy(deps.clawInFlight);
        deps.clawRetryTimer = setInterval(() => {
          const next = deps.clawRetrySeconds > 0 ? deps.clawRetrySeconds - 1 : 0;
          deps.clawRetrySeconds = next;
          if (next === 0) stopClawRetryTimer();
          renderClawRetryBox();
          setClawButtonsBusy(deps.clawInFlight);
        }, 1000);
      }

      function showClawAmbiguousRecoveryHint() {
        const { clawRetryHint, clawRetryBox, clawRetryCopy, clawRetryButton } = deps;
        if (!clawRetryHint) return;
        stopClawRetryTimer();
        deps.clawRetrySeconds = 0;
        // The request may already be running, so its exact content is recorded as
        // uncertain. The finally block releases the busy flag, so without this the
        // execute button would reopen on an unresolved run.
        if (deps.clawLastDispatchKey) deps.clawUncertainKeys.add(deps.clawLastDispatchKey);
        if (clawRetryBox) clawRetryBox.hidden = true;
        if (clawRetryCopy) clawRetryCopy.textContent = "";
        if (clawRetryButton) {
          clawRetryButton.disabled = true;
          clawRetryButton.setAttribute("aria-disabled", "true");
        }
        clawRetryHint.dataset.localeKey = "claw-error-check-runs";
        clawRetryHint.textContent = deps.clawT("claw-error-check-runs");
        clawRetryHint.hidden = false;
        setClawButtonsBusy(deps.clawInFlight);
      }

      // ── In-flight elapsed wait (#2763) ──────────────────────────────────────
      //
      // The execute POST is a single synchronous browser request: no server-side
      // progress, phase, or completion-percentage source exists, and B54 owns no
      // cancellation authority. So this surface shows only what the browser truly
      // knows — how long the user has been waiting. It never polls the run-history
      // route, never re-dispatches, never infers an Engine/P01 stage, and shows no
      // percentage, phase list, or Cancel control.
      //
      // One 1000ms ticker per in-flight request, started only by explicit user
      // dispatch. A tick re-renders copy from state; it issues no network call and
      // cannot reach the execute entry point. The ticking value is a role="timer"
      // region (implicitly aria-live off), readable on demand without announcing
      // every second; only the two bounded long-wait states are announced, through
      // the single canonical polite status region.

      function clawWaitElapsedSeconds() {
        const startedAt = deps.clawWaitStartedAt;
        if (!startedAt) return 0;
        const elapsed = Date.now() - startedAt;
        return elapsed > 0 ? Math.floor(elapsed / 1000) : 0;
      }

      function clawWaitStageFor(elapsedSeconds) {
        if (elapsedSeconds >= CLAW_WAIT_VERY_LONG_SECONDS) return 2;
        if (elapsedSeconds >= CLAW_WAIT_LONG_SECONDS) return 1;
        return 0;
      }

      function clawWaitStageKey(stage) {
        return stage >= 2 ? "claw-wait-very-long" : "claw-wait-long";
      }

      // Bounded reassurance copy: at most two announcements per request, and the
      // copy carries no elapsed value so the live region is never re-announced once
      // per second.
      function applyClawWaitStageCopy() {
        if (deps.clawWaitAnnouncedStage < 1) return;
        const key = clawWaitStageKey(deps.clawWaitAnnouncedStage);
        setClawStatus(deps.clawT(key), "running", key);
      }

      // Presentation only. Returns true while it owns the status region, so a locale
      // switch re-renders from state (elapsed value preserved) instead of resolving
      // a stale key on its own.
      function renderClawWait() {
        if (!deps.clawWaitStartedAt) return false;
        const elapsed = clawWaitElapsedSeconds();
        if (!deps.clawWaitRevealed && elapsed * 1000 >= CLAW_WAIT_REVEAL_MS) deps.clawWaitRevealed = true;
        if (deps.clawWait) {
          deps.clawWait.hidden = !deps.clawWaitRevealed;
          if (deps.clawWaitRevealed) deps.clawWait.textContent = deps.clawT("claw-wait-elapsed", { seconds: elapsed });
        }
        const stage = clawWaitStageFor(elapsed);
        if (stage > deps.clawWaitAnnouncedStage) {
          deps.clawWaitAnnouncedStage = stage;
          applyClawWaitStageCopy();
        }
        return deps.clawWaitAnnouncedStage > 0;
      }

      function beginClawWait() {
        clearClawWait();
        deps.clawWaitStartedAt = Date.now();
        deps.clawWaitTimer = setInterval(() => {
          renderClawWait();
        }, CLAW_WAIT_TICK_MS);
      }

      // Idempotent teardown: it only ever stops, never starts, so a completion that
      // arrives after a clear can never resurrect a wait.
      function clearClawWait() {
        const timer = deps.clawWaitTimer;
        if (timer) {
          clearInterval(timer);
          deps.clawWaitTimer = null;
        }
        deps.clawWaitStartedAt = 0;
        deps.clawWaitRevealed = false;
        deps.clawWaitAnnouncedStage = 0;
        if (deps.clawWait) {
          deps.clawWait.hidden = true;
          deps.clawWait.textContent = "";
        }
      }

      return {
        syncComposerForClaw,
        setClawStatus,
        setClawAreaState,
        setClawButtonsBusy,
        clawRetryRemaining,
        clawVisibleExecutePayload,
        clawExecuteWireKey,
        clawCurrentDispatchIsUncertain,
        noteClawContentEdited,
        clawRetryAfterFromResponse,
        isAmbiguousClawFailure,
        clearClawRecovery,
        renderClawRetryBox,
        beginClawRetryCooldown,
        showClawAmbiguousRecoveryHint,
        applyClawWaitStageCopy,
        renderClawWait,
        beginClawWait,
        clearClawWait,
      };
    },
  };
})();
