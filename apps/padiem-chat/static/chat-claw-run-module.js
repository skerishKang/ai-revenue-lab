// #7216 R5 A5a — Claw manual run artifacts, approval controls, and the single
// execute entry point. Moved verbatim from app.js; app.js keeps one-line
// forwarders and reads closure state live via getters and setters.
(() => {
  "use strict";

  window.PadiemChatClawRunModule = {
    create(deps) {
      const CLAW_DISPATCH_KEY_WINDOW_MS = 10000;
      let clawPdfPreviewController = null;

        function setClawDocumentAction(enabled, documentId, filename) {
          const btn = deps.clawResultDocx;
          if (!btn) return;
          btn.disabled = !enabled;
          btn.setAttribute("aria-disabled", enabled ? "false" : "true");
          btn.classList.toggle("is-prominent", enabled);
          if (enabled) {
            btn.dataset.documentId = documentId;
            if (filename) btn.dataset.filename = filename;
            return;
          }
          // Clearing drops the descriptor with the result, so a later click can never
          // replay a previous run's artifact id or filename hint.
          delete btn.dataset.documentId;
          delete btn.dataset.filename;
        }

        function clearClawArtifact() {
          clawPdfPreviewController?.clear();
          if (deps.clawArtifactMeta) deps.clawArtifactMeta.hidden = true;
          if (deps.clawArtifactName) deps.clawArtifactName.textContent = "";
          if (deps.clawArtifactSize) deps.clawArtifactSize.textContent = "";
          if (deps.clawResultSuccessNote) deps.clawResultSuccessNote.hidden = true;
          setClawDocumentAction(false);
          const downloadLabel = deps.clawResultDocx?.querySelector?.('[data-locale-key="claw-result-docx"]');
          if (downloadLabel) downloadLabel.textContent = deps.clawT("claw-result-docx");
        }

        function formatClawBytes(bytes) {
          if (!Number.isFinite(bytes) || bytes < 0) return "";
          if (bytes < 1024) return `${bytes} B`;
          if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
          return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
        }

        function renderClawArtifactMeta(artifact) {
          if (!artifact || !artifact.document_id) {
            clearClawArtifact();
            return;
          }
          const filename = typeof artifact.filename === "string" && artifact.filename ? artifact.filename : "document.docx";
          const byteLength = typeof artifact.byte_length === "number" ? artifact.byte_length : null;
          if (deps.clawArtifactName) deps.clawArtifactName.textContent = filename;
          if (deps.clawArtifactSize) deps.clawArtifactSize.textContent = byteLength != null ? formatClawBytes(byteLength) : "";
          if (deps.clawArtifactMeta) deps.clawArtifactMeta.hidden = false;
          if (deps.clawResultSuccessNote) deps.clawResultSuccessNote.hidden = false;
          setClawDocumentAction(true, artifact.document_id, artifact.filename);
          const downloadLabel = deps.clawResultDocx?.querySelector?.('[data-locale-key="claw-result-docx"]');
          if (downloadLabel) downloadLabel.textContent = artifact.media_type === "application/pdf"
            ? deps.clawT("claw-result-pdf")
            : deps.clawT("claw-result-docx");
          if (!clawPdfPreviewController && deps.clawArtifactMeta && window.PadiemClawPdfPreview?.create) {
            clawPdfPreviewController = window.PadiemClawPdfPreview.create({
              mount: deps.clawArtifactMeta,
              onError: (message) => deps.setClawStatus(message, "error"),
            });
          }
          clawPdfPreviewController?.set(artifact);
        }

        function safeClawErrorMessage(data, response) {
          const code = data && data.error && typeof data.error.code === "string" ? data.error.code : "";
          const status = response ? response.status : 0;
          // #3933: a bounded pre-dispatch refusal is a product state, not a run that
          // started and then failed. The manual-intake route returns this same
          // `tier_unavailable` code before it ever dispatches, so resolving it through
          // the shared bounded-refusal authority keeps this lane's wording identical to
          // the composer and live SSE lanes instead of the generic "the run failed"
          // sentence. An unlisted code falls through to the existing bounded copy.
          const bounded = deps.clawBoundedRefusalCopy(code);
          if (bounded) return bounded.message;
          if (code === "invalid_content" || code === "content_too_short") return deps.clawT("claw-error-empty");
          if (code === "content_too_long" || code === "body_too_large" || status === 413) return deps.clawT("claw-error-too-large");
          if (code === "invalid_channel" || code === "invalid_action" || code === "unsupported_media_type" || code === "invalid_sender_hint") return deps.clawT("claw-error-invalid");
          if (code === "rate_limited" || status === 429) return deps.clawT("claw-error-rate-limited");
          if (code === "workspace_scope_unavailable" || code === "live_identity_unavailable") return deps.clawT("claw-error-auth-unavailable");
          if (code === "auth_required" || status === 401) return deps.clawT("claw-error-auth-needed");
          if (code === "workspace_storage_unavailable" || code === "artifact_storage_failed" || code === "artifact_generation_failed") return deps.clawT("claw-error-storage");
          if (status === 503 || code === "engine_not_configured" || code === "live_abuse_gate_unavailable") return deps.clawT("claw-error-generic");
          if (code === "engine_execution_failed" || status === 502) return deps.clawT("claw-error-generic");
          return deps.clawT("claw-error-generic");
        }

        async function downloadClawArtifact(documentId, filenameHint) {
          if (!documentId || !/^doc_[A-Za-z0-9]{32}$/.test(String(documentId))) return;
          try {
            const resp = await fetch(`/api/claw/manual-intake/artifact/${encodeURIComponent(documentId)}`, { cache: "no-store" });
            if (!resp.ok) {
              const err = await resp.json().catch(() => null);
              deps.setClawStatus(safeClawErrorMessage(err, resp), "error");
              deps.setClawAreaState("error");
              return;
            }
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filenameHint || "document.docx";
            a.rel = "noopener";
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 4000);
          } catch (_) {
            deps.setClawStatus(deps.clawT("claw-error-generic"), "error");
            deps.setClawAreaState("error");
          }
        }

        function revealClawCard(kindText, executed = false) {
          if (deps.clawResultEmpty) deps.clawResultEmpty.hidden = true;
          if (deps.clawResultHint) deps.clawResultHint.hidden = true;
          if (deps.clawResultCard) deps.clawResultCard.hidden = false;
          if (deps.clawResultKind) deps.clawResultKind.textContent = kindText || "";
          if (deps.clawResultBadge) {
            deps.clawResultBadge.dataset.localeKey = executed ? "claw-result-badge-run" : "claw-result-badge";
            deps.clawResultBadge.textContent = deps.clawT(executed ? "claw-result-badge-run" : "claw-result-badge");
          }
        }


        function setApprovalControlsBusy(container, busy) {
          if (!container) return;
          Array.from(container.children || []).forEach((child) => {
            if (String(child.tagName || "").toUpperCase() === "BUTTON") {
              child.disabled = busy;
              child.setAttribute("aria-disabled", String(busy));
            }
          });
        }

        function renderClawApprovalControls(container, runId, onResolved) {
          if (!container || typeof runId !== "string" || !runId) return;
          container.replaceChildren();
          container.hidden = false;

          const copy = document.createElement("p");
          copy.className = "claw-approval-copy";
          copy.textContent = deps.clawT("claw-approval-required");

          const status = document.createElement("p");
          status.className = "claw-approval-status";
          status.setAttribute("role", "status");
          status.setAttribute("aria-live", "polite");
          status.hidden = true;

          const approve = document.createElement("button");
          approve.type = "button";
          approve.className = "claw-approval-button claw-approval-approve";
          approve.textContent = deps.clawT("claw-approval-approve");

          const deny = document.createElement("button");
          deny.type = "button";
          deny.className = "claw-approval-button claw-approval-deny";
          deny.textContent = deps.clawT("claw-approval-deny");

          async function decide(decision) {
            if (deps.clawApprovalInFlight) return;
            deps.clawApprovalInFlight = true;
            // The session generation this decision belongs to, captured before any
            // await. An auth loss or account switch bumps the epoch, so a response
            // that lands afterwards is stale and must not be presented.
            const decisionEpoch = deps.clawApprovalEpoch;
            setApprovalControlsBusy(container, true);
            status.hidden = false;
            status.dataset.state = "pending";
            status.textContent = deps.clawT("claw-approval-processing");
            try {
              const response = await fetch("/api/claw/approvals/decision", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify({ run_id: runId, decision }),
              });
              const data = await response.json().catch(() => null);
              // A decision begun before the session changed is not a license to
              // present its result to the new (or signed-out) session.
              if (decisionEpoch !== deps.clawApprovalEpoch || deps.authState.authenticated !== true) return;
              if (!response.ok || !data || data.ok !== true || !data.result || typeof data.result.run_id !== "string") {
                throw deps.mappedUiError(deps.approvalDecisionErrorMessage(data, response), data);
              }
              status.hidden = true;
              status.removeAttribute("data-state");
              deps.app.invalidateClawRunsRead();
              if (typeof onResolved === "function") await onResolved(data.result);
            } catch (error) {
              if (decisionEpoch !== deps.clawApprovalEpoch || deps.authState.authenticated !== true) return;
              status.hidden = false;
              status.dataset.state = "error";
              status.textContent = deps.safeLocalUiMessage(error, deps.clawT("claw-approval-error"));
              const reference = deps.failureCodeNote(error?.code, "");
              if (reference) status.appendChild(reference);
            } finally {
              // A stale decision must not release the busy state of a newer
              // session's controls; the invalidation path already reset the shared
              // single-flight flag.
              if (decisionEpoch === deps.clawApprovalEpoch) {
                deps.clawApprovalInFlight = false;
                setApprovalControlsBusy(container, false);
              }
            }
          }

          approve.addEventListener("click", () => decide("approve"));
          deny.addEventListener("click", () => decide("deny"));
          container.append(copy, approve, deny, status);
        }

        function clearImmediateApprovalControls() {
          if (!deps.clawApprovalActions) return;
          deps.clawApprovalActions.replaceChildren();
          deps.clawApprovalActions.hidden = true;
        }

        async function applyImmediateApprovalDecision(result) {
          if (!result || typeof result.run_id !== "string") return;
          // Session authority was already adopted from the canonical execute response.
          // Approval continuation may return the same handle for presentation, but the
          // browser must not introduce a second conversation-id adoption path.
          const status = typeof result.status === "string" ? result.status : "";
          if (status === "waiting_approval" && result.approval_required === true) {
            if (deps.clawResultPreview) deps.clawResultPreview.textContent = deps.clawT("claw-approval-required");
            renderClawApprovalControls(deps.clawApprovalActions, result.run_id, applyImmediateApprovalDecision);
            deps.setClawStatus(deps.clawT("claw-approval-required"), "waiting_approval");
            deps.setClawAreaState("waiting_approval");
          } else {
            clearImmediateApprovalControls();
            const resultText = typeof result.result_text === "string" && result.result_text
              ? result.result_text
              : deps.app.clawRunStatusLabel(status);
            if (deps.clawResultPreview) deps.clawResultPreview.textContent = resultText;
            deps.setClawStatus(resultText, status || "success");
            deps.setClawAreaState(status || "success");
          }
          await deps.loadClawRunHistory();
        }

        // #2532 (R2): echo the submitted request as a user bubble in the shared
        // conversation so manual Claw reads as one continuous Chat thread. This is
        // the user's own message, never presented as an AI result.
        function renderClawRequestEcho(text) {
          if (!deps.clawRequestEcho || !deps.clawRequestEchoText) return;
          deps.clawRequestEchoText.textContent = text;
          deps.clawRequestEcho.hidden = false;
        }

        // A duplicate listener or a retried click shares the key already claimed by
        // the in-flight dispatch. Without a shared value, two closures would each
        // mint their own key and the server could not recognize the replay.
        function clawClaimDispatchKey() {
          const button = deps.clawExecuteButton;
          const existing = button && button.dataset ? button.dataset.clawDispatchKey : "";
          const existingAt = Number(
            button && button.dataset ? button.dataset.clawDispatchAt || "0" : "0",
          );
          if (existing && Date.now() - existingAt < CLAW_DISPATCH_KEY_WINDOW_MS) {
            return existing;
          }
          // #7133: the random part is minted by the shared transport helper —
          // app.js never calls crypto directly (browser-minting contracts).
          const minted = deps.chatTransport.createRequestId?.();
          const key = minted ? `claw-${minted}` : `claw-${Date.now().toString(36)}`;
          if (button && button.dataset) {
            button.dataset.clawDispatchKey = key;
            button.dataset.clawDispatchAt = String(Date.now());
          }
          return key;
        }
        function releaseClawDispatchKey(key) {
          const button = deps.clawExecuteButton;
          if (!button || !button.dataset || button.dataset.clawDispatchKey !== key) return;
          delete button.dataset.clawDispatchKey;
          delete button.dataset.clawDispatchAt;
        }

        // Single execute entry point. The primary button and the post-cooldown retry
        // button both funnel through here, so a retry can never bypass the
        // single-flight, pre-dispatch cooldown or uncertain-dispatch guards and the
        // payload is always rebuilt from the currently visible form at click time.
        async function runClawExecution() {
          if (deps.clawInFlight) return;
          if (deps.clawRetryRemaining() > 0) return; // explicit retry only after the pre-dispatch cooldown
          if (deps.clawCurrentDispatchIsUncertain()) return; // #3382: no re-send of an unresolved request
          const executePayload = deps.clawVisibleExecutePayload();
          const body = executePayload.content;
          if (!body) {
            clearClawArtifact();
            if (deps.clawResultCard) deps.clawResultCard.hidden = true;
            if (deps.clawResultEmpty) {
              deps.clawResultEmpty.hidden = false;
              deps.clawResultEmpty.textContent = deps.clawT("claw-error-empty");
            }
            deps.setClawStatus(deps.clawT("claw-error-empty"), "error");
            deps.setClawAreaState("error");
            deps.input.focus();
            return;
          }
          const idempotencyKey = clawClaimDispatchKey();
          deps.clearClawRecovery();
          // Remember the exact bytes this dispatch carried, so a later ambiguous
          // failure can tell an identical re-send apart from new work.
          deps.clawLastDispatchKey = deps.clawExecuteWireKey(executePayload);
          renderClawRequestEcho(body);
          deps.setClawButtonsBusy(true);
          // Explicit user dispatch is the only thing that may start a wait timer.
          deps.beginClawWait();
          deps.setClawStatus(deps.clawT("claw-status-execute-running"), "running", "claw-status-execute-running");
          deps.setClawAreaState("submitting");
          if (deps.clawResultCard) deps.clawResultCard.hidden = true;
          clearImmediateApprovalControls();
          clearClawArtifact();
          if (deps.clawResultEmpty) {
            deps.clawResultEmpty.hidden = false;
            deps.clawResultEmpty.textContent = deps.clawT("claw-status-execute-running");
          }

          try {
            const response = await fetch("/api/claw/manual-intake/execute", {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Idempotency-Key": idempotencyKey,
              },
              body: JSON.stringify(executePayload),
            });
            const data = await response.json().catch(() => null);
            if (data && data.ok && data.result) {
              const result = data.result;
              // Server-echoed canonical handle only (#2916): reuse it as the single
              // session authority; never build a second id here.
              if (typeof result.conversation_id === "string" && result.conversation_id) {
                deps.conversationState.setConversationId(result.conversation_id, deps.PRODUCT_CLAW);
              }
              if (
                result.status === "waiting_approval"
                && result.approval_required === true
                && typeof result.request_id === "string"
                && result.request_id
              ) {
                revealClawCard(result.title, true);
                clearClawArtifact();
                if (deps.clawResultPreview) deps.clawResultPreview.textContent = deps.clawT("claw-approval-required");
                renderClawApprovalControls(deps.clawApprovalActions, result.request_id, applyImmediateApprovalDecision);
                deps.setClawStatus(deps.clawT("claw-approval-required"), "waiting_approval");
                deps.setClawAreaState("waiting_approval");
                if (deps.clawResultPreview) deps.clawResultPreview.focus?.();
                return;
              }
              if (typeof result.result_text !== "string") {
                throw new Error(deps.clawT("claw-error-generic"));
              }
              clearImmediateApprovalControls();
              const safeText = String(result.result_text);
              revealClawCard(result.title, true);
              if (deps.clawResultPreview) deps.clawResultPreview.textContent = safeText;
              if (deps.clawResultEmpty) deps.clawResultEmpty.hidden = true;
              const artifact = result.artifact && typeof result.artifact.document_id === "string" ? result.artifact : null;
              const hasArtifact = !!(artifact && artifact.document_id);
              if (hasArtifact) renderClawArtifactMeta(artifact); else clearClawArtifact();
              deps.setClawStatus(deps.clawT("claw-status-execute-success"), "success", "claw-status-execute-success");
              deps.setClawAreaState("success");
              if (hasArtifact && deps.clawResultDocx) deps.clawResultDocx.focus?.();
              else if (deps.clawResultPreview) deps.clawResultPreview.focus?.();
              return;
            }
            const safeMsg = safeClawErrorMessage(data, response);
            // #3933: a bounded pre-dispatch refusal also states, in the result area,
            // that the request was never executed — the distinction the status line
            // alone cannot carry. Resolved from the same authority as safeMsg.
            const boundedFailure = deps.clawBoundedRefusalCopy(
              data && data.error && typeof data.error.code === "string" ? data.error.code : "",
            );
            if (deps.clawResultEmpty) {
              deps.clawResultEmpty.hidden = false;
              deps.clawResultEmpty.textContent = boundedFailure
                ? `${boundedFailure.message} ${boundedFailure.hint}`
                : safeMsg;
            }
            deps.setClawStatus(safeMsg, "error");
            deps.setClawAreaState("error");
            // A 429 usage denial happens before dispatch, so its Retry-After may be
            // honored as a cooldown. Anything ambiguous gets guidance, never a retry.
            // #3933: a bounded pre-dispatch refusal provably never dispatched, so it is
            // excluded here as well as in the classifier — widening the ambiguous set
            // later must not be able to latch a HOLD as an uncertain run.
            const retryAfter = response.status === 429 ? deps.clawRetryAfterFromResponse(response) : null;
            if (retryAfter !== null) deps.beginClawRetryCooldown(retryAfter);
            else if (!boundedFailure && deps.isAmbiguousClawFailure(data, response)) deps.showClawAmbiguousRecoveryHint();
          } catch {
            const fallback = deps.clawT("claw-error-generic");
            if (deps.clawResultEmpty) {
              deps.clawResultEmpty.hidden = false;
              deps.clawResultEmpty.textContent = fallback;
            }
            deps.setClawStatus(fallback, "error");
            deps.setClawAreaState("error");
            // The request may have reached the engine before the connection died.
            deps.showClawAmbiguousRecoveryHint();
          } finally {
            // The owning request always tears its wait timer down: success, known
            // pre-dispatch denial, ambiguous failure, and auth loss all clear it.
            deps.clearClawWait();
            releaseClawDispatchKey(idempotencyKey);
            deps.setClawButtonsBusy(false);
          }
        }
      return {
        setClawDocumentAction,
        clearClawArtifact,
        formatClawBytes,
        renderClawArtifactMeta,
        safeClawErrorMessage,
        downloadClawArtifact,
        revealClawCard,
        setApprovalControlsBusy,
        renderClawApprovalControls,
        clearImmediateApprovalControls,
        applyImmediateApprovalDecision,
        renderClawRequestEcho,
        clawClaimDispatchKey,
        releaseClawDispatchKey,
        runClawExecution,
      };
    },
  };
})();
