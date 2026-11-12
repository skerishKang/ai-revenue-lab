// #7216 R5 A6 — Android WebView login handoff: start, claim, poll, panel
// render and the handoff controls. Moved verbatim from app.js; the
// session-storage reader/writer and resumeAndroidHandoff stay in app.js (R-06)
// and are reached through deps.
(() => {
  "use strict";

  window.PadiemChatAndroidHandoffModule = {
    create(deps) {
        function isAndroidWebView() {
          if (typeof navigator === "undefined") return false;
          const userAgent = navigator.userAgent || "";
          return /Android/i.test(userAgent) && /\bwv\b/i.test(userAgent);
        }

        function stopAndroidHandoffPolling() {
          if (deps.androidHandoffTimer !== null) {
            window.clearInterval(deps.androidHandoffTimer);
            deps.androidHandoffTimer = null;
          }
        }

        function clearAndroidHandoff() {
          stopAndroidHandoffPolling();
          deps.androidHandoffClaiming = false;
          deps.androidHandoff = null;
          deps.storeAndroidHandoff();
          renderAndroidHandoff();
          deps.setAuthFormError(deps.androidHandoffError);
        }

        function androidHandoffPhaseKey(phase) {
          switch (phase) {
            case "waiting": return "auth-android-waiting";
            case "confirm": return "auth-android-confirm";
            case "claiming": return "auth-android-claiming";
            case "expired": return "auth-android-expired";
            case "error": return "auth-android-error";
            default: return "auth-android-code-help";
          }
        }

        function renderAndroidHandoff() {
          if (!deps.androidHandoffPanel) return;
          if (!deps.androidHandoff) {
            deps.androidHandoffPanel.hidden = true;
            return;
          }
          deps.androidHandoffPanel.hidden = false;
          if (deps.androidHandoffCode) deps.androidHandoffCode.textContent = deps.androidHandoff.userCode;
          if (deps.androidHandoffNote) {
            const key = androidHandoffPhaseKey(deps.androidHandoff.phase);
            deps.androidHandoffNote.dataset.localeKey = key;
            deps.androidHandoffNote.textContent = deps.uiT(key);
          }
          const busy = deps.androidHandoff.phase === "claiming";
          // The external browser is only useful while the Google sign-in itself
          // is still pending. Once the profile is bound the user only has to
          // enter the code, and re-opening Google would repeat that
          // procedure for nothing.
          const awaitingLogin = deps.androidHandoff.phase === "waiting";
          if (deps.androidHandoffOpen) {
            deps.androidHandoffOpen.hidden = busy || !awaitingLogin;
            deps.androidHandoffOpen.disabled = busy || !awaitingLogin;
          }
          if (deps.androidHandoffCopy) {
            deps.androidHandoffCopy.hidden = busy;
            deps.androidHandoffCopy.disabled = busy;
          }
          if (deps.androidHandoffCopied) {
            deps.androidHandoffCopied.hidden = true;
          }
          if (deps.androidHandoffCancel) {
            deps.androidHandoffCancel.hidden = busy;
            deps.androidHandoffCancel.disabled = busy;
          }
        }

        async function claimAndroidHandoff(current) {
          if (!current || deps.androidHandoffClaiming || deps.androidHandoff !== current) return;
          deps.androidHandoffClaiming = true;
          current.phase = "claiming";
          deps.storeAndroidHandoff();
          renderAndroidHandoff();
          let response;
          try {
            response = await fetch(`/auth/android/handoff/${encodeURIComponent(current.handoffId)}/claim`, {
              method: "POST",
              headers: {
                "Accept": "application/json",
                "X-Padiem-Handoff-Secret": current.claimSecret,
              },
              cache: "no-store",
            });
          } catch (_) {
            current.phase = "waiting";
            deps.storeAndroidHandoff();
            renderAndroidHandoff();
            deps.androidHandoffClaiming = false;
            return;
          }
          if (response.ok) {
            await deps.loadAuthStatus();
            if (deps.authState.authenticated) {
              clearAndroidHandoff();
              deps.closeAuthDialog();
            } else {
              current.phase = "error";
              deps.storeAndroidHandoff();
              renderAndroidHandoff();
            }
            deps.androidHandoffClaiming = false;
            return;
          }
          if (response.status === 410 || response.status === 404) {
            current.phase = "expired";
            stopAndroidHandoffPolling();
          } else if (response.status === 409) {
            await deps.loadAuthStatus();
            if (deps.authState.authenticated) {
              clearAndroidHandoff();
            } else {
              current.phase = "error";
              stopAndroidHandoffPolling();
            }
          } else {
            current.phase = "error";
            stopAndroidHandoffPolling();
          }
          deps.storeAndroidHandoff();
          renderAndroidHandoff();
          deps.androidHandoffClaiming = false;
        }

        async function pollAndroidHandoff() {
          const current = deps.androidHandoff;
          if (!current || deps.androidHandoffClaiming) return;
          if (Date.now() >= current.expiresAt) {
            current.phase = "expired";
            stopAndroidHandoffPolling();
            deps.storeAndroidHandoff();
            renderAndroidHandoff();
            return;
          }
          let response;
          try {
            response = await fetch(`/auth/android/handoff/${encodeURIComponent(current.handoffId)}`, {
              headers: {
                "Accept": "application/json",
                "X-Padiem-Handoff-Secret": current.claimSecret,
              },
              cache: "no-store",
            });
          } catch (_) {
            return; // transient; the next tick retries while the page is alive
          }
          if (response.status === 404) {
            current.phase = "error";
            stopAndroidHandoffPolling();
            deps.storeAndroidHandoff();
            renderAndroidHandoff();
            return;
          }
          if (!response.ok) return;
          const data = await response.json().catch(() => null);
          if (!data || typeof data.status !== "string") return;
          if (data.status === "ready") {
            await claimAndroidHandoff(current);
            return;
          }
          if (data.status === "claimed") {
            await deps.loadAuthStatus();
            if (deps.authState.authenticated) clearAndroidHandoff();
            return;
          }
          if (data.status === "expired" || data.status === "cancelled") {
            current.phase = "expired";
            stopAndroidHandoffPolling();
            deps.storeAndroidHandoff();
            renderAndroidHandoff();
            return;
          }
          current.phase = data.status === "awaiting_confirmation" ? "confirm" : "waiting";
          deps.storeAndroidHandoff();
          renderAndroidHandoff();
        }

        function startAndroidHandoffPolling() {
          stopAndroidHandoffPolling();
          if (!deps.androidHandoff || deps.androidHandoff.phase === "expired" || deps.androidHandoff.phase === "error") return;
          deps.androidHandoffTimer = window.setInterval(() => { pollAndroidHandoff(); }, deps.ANDROID_HANDOFF_POLL_MS);
        }

        async function startAndroidHandoff() {
          if (deps.androidHandoffStarting) return;
          deps.androidHandoffStarting = true;
          deps.setAuthFormError(deps.androidHandoffError);
          try {
            const response = await fetch("/auth/android/handoff", {
              method: "POST",
              headers: { "Accept": "application/json" },
              cache: "no-store",
            });
            const data = await response.json().catch(() => null);
            if (!response.ok || !data ||
                typeof data.handoff_id !== "string" ||
                typeof data.claim_secret !== "string" ||
                typeof data.user_code !== "string" ||
                typeof data.authorization_url !== "string") {
              throw new Error(deps.uiT("auth-android-error"));
            }
            const expiresIn = Number.isFinite(data.expires_in) ? data.expires_in : 600;
            deps.androidHandoff = {
              handoffId: data.handoff_id,
              claimSecret: data.claim_secret,
              userCode: data.user_code,
              authorizationUrl: data.authorization_url,
              expiresAt: Date.now() + Math.max(30, expiresIn - 5) * 1000,
              phase: "waiting",
            };
            deps.storeAndroidHandoff();
            renderAndroidHandoff();
            startAndroidHandoffPolling();
            window.location.assign(deps.androidHandoff.authorizationUrl);
          } catch (error) {
            deps.setAuthFormError(
              deps.androidHandoffError,
              error instanceof Error && error.message ? error.message : deps.uiT("auth-android-error")
            );
          } finally {
            deps.androidHandoffStarting = false;
          }
        }

      // Registered from app.js at the original position so ordering is kept.
      function wireAndroidHandoffListeners() {
        if (deps.androidHandoffOpen) {
          deps.androidHandoffOpen.addEventListener("click", () => {
            if (!deps.androidHandoff) return;
            window.location.assign(deps.androidHandoff.authorizationUrl);
          });
        }
        if (deps.androidHandoffCopy) {
          deps.androidHandoffCopy.addEventListener("click", async () => {
            if (!deps.androidHandoff) return;
            const code = deps.androidHandoff.userCode || "";
            if (!code) return;
            let copied = false;
            try {
              if (navigator.clipboard && window.isSecureContext) {
                await navigator.clipboard.writeText(code);
                copied = true;
              }
            } catch (error) {
              copied = false;
            }
            if (!copied && deps.androidHandoffCode) {
              // Fall back to selecting the code so it can still be copied.
              try {
                const range = document.createRange();
                range.selectNodeContents(deps.androidHandoffCode);
                const selection = window.getSelection();
                if (selection) {
                  selection.removeAllRanges();
                  selection.addRange(range);
                }
              } catch (error) {}
            }
            if (deps.androidHandoffCopied) {
              deps.androidHandoffCopied.hidden = false;
            }
          });
        }
        if (deps.androidHandoffCancel) {
          deps.androidHandoffCancel.addEventListener("click", () => { clearAndroidHandoff(); });
        }
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible" && deps.androidHandoff) {
            pollAndroidHandoff();
          }
        });
      }

      return {
        isAndroidWebView,
        stopAndroidHandoffPolling,
        clearAndroidHandoff,
        androidHandoffPhaseKey,
        renderAndroidHandoff,
        claimAndroidHandoff,
        pollAndroidHandoff,
        startAndroidHandoffPolling,
        startAndroidHandoff,
        wireAndroidHandoffListeners,
      };
    },
  };
})();
