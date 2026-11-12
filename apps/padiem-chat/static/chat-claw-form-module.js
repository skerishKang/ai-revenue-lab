// #7216 R5 A5b — Claw manual form submit/preview and the execute/retry control
// wiring. Moved verbatim from app.js; app.js keeps the declaration block and
// calls wireManualForm()/wireExecuteControls() at the original positions.
(() => {
  "use strict";

  window.PadiemChatClawFormModule = {
    create(deps) {
      // Manual submit is the only path that posts the preview request; the
      // execute and retry buttons share the single run entry point.
      function wireManualForm() {
        // Single artifact handler: reads the current dataset at click time (no
        // per-result listener leak), and is the only control wired to the download.
        if (deps.clawResultDocx) deps.clawResultDocx.addEventListener("click", () => {
          const docId = deps.clawResultDocx.dataset.documentId;
          const fname = deps.clawResultDocx.dataset.filename;
          if (docId && !deps.clawResultDocx.disabled) deps.downloadClawArtifact(docId, fname);
        });

        if (deps.clawManualForm) {
          deps.clawManualForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            if (deps.clawInFlight) return;
            const body = (deps.input.value || "").trim();
            if (!body) {
              if (deps.clawResultCard) deps.clawResultCard.hidden = true;
              deps.clearClawArtifact();
              if (deps.clawResultEmpty) {
                deps.clawResultEmpty.hidden = false;
                deps.clawResultEmpty.textContent = deps.clawT("claw-error-empty");
              }
              if (deps.clawResultHint) deps.clawResultHint.hidden = false;
              deps.setClawStatus(deps.clawT("claw-error-empty"), "error");
              deps.setClawAreaState("error");
              deps.input.focus();
              return;
            }
            const channelValue = deps.clawChannel?.value || "other";
            const actionValue = deps.clawAction?.value || "quote";
            const channelText = deps.clawChannel?.options[deps.clawChannel.selectedIndex]?.textContent || channelValue;
            const actionText = deps.clawAction?.options[deps.clawAction.selectedIndex]?.textContent || actionValue;
            const senderText = (deps.clawSender?.value || "").trim();

            deps.renderClawRequestEcho(body);
            deps.setClawButtonsBusy(true);
            deps.setClawStatus(deps.clawT("claw-status-preview-running"), "running", "claw-status-preview-running");
            deps.setClawAreaState("submitting");
            if (deps.clawResultCard) deps.clawResultCard.hidden = true;
            deps.clearClawArtifact();
            if (deps.clawResultEmpty) {
              deps.clawResultEmpty.hidden = false;
              deps.clawResultEmpty.textContent = deps.clawT("claw-status-preview-running");
            }

            const renderPreviewError = () => {
              if (deps.clawResultCard) deps.clawResultCard.hidden = true;
              deps.clearClawArtifact();
              if (deps.app.clawMemoryReview) deps.app.clawMemoryReview.hidden = true;
              if (deps.clawResultEmpty) {
                deps.clawResultEmpty.hidden = false;
                deps.clawResultEmpty.textContent = deps.clawT("claw-error-preview");
              }
              if (deps.clawResultHint) deps.clawResultHint.hidden = false;
              deps.setClawStatus(deps.clawT("claw-error-preview"), "error", "claw-error-preview");
              deps.setClawAreaState("error");
            };

            try {
              const response = await fetch("/api/claw/manual-intake/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Accept": "application/json" },
                body: JSON.stringify({ content: body, channel: channelValue, action: actionValue, sender_hint: senderText || null }),
              });
              if (!response.ok) {
                renderPreviewError();
                return;
              }
              const data = await response.json();
              if (!data || !data.ok || !data.preview || typeof data.preview.result_text !== "string") {
                renderPreviewError();
                return;
              }
              const preview = data.preview;
              deps.revealClawCard(preview.title);
              if (deps.clawResultPreview) deps.clawResultPreview.textContent = preview.result_text;
              deps.clearClawArtifact();
              deps.app.renderMemoryProposalReview(Array.isArray(preview.memory_proposals) ? preview.memory_proposals : []);
              deps.setClawStatus(deps.clawT("claw-status-preview-success"), "success", "claw-status-preview-success");
              deps.setClawAreaState("success");
              // Move focus to result for screen-reader and keyboard users
              if (deps.clawResultPreview) deps.clawResultPreview.focus?.();
            } catch {
              renderPreviewError();
            } finally {
              deps.setClawButtonsBusy(false);
            }
          });
        }
      }

      function wireExecuteControls() {
        if (deps.clawExecuteButton) {
          if (deps.clawExecuteButton.dataset.clawExecuteWired !== "1") {
            deps.clawExecuteButton.dataset.clawExecuteWired = "1";
            deps.clawExecuteButton.addEventListener("click", () => {
              void deps.runClawExecution();
            });
          }
        }
        if (deps.clawRetryButton) {
          if (deps.clawRetryButton.dataset.clawRetryWired !== "1") {
            deps.clawRetryButton.dataset.clawRetryWired = "1";
            deps.clawRetryButton.addEventListener("click", () => {
              void deps.runClawExecution();
            });
          }
        }
        // #3382: composing different work — new text, channel, action,
        // sender or conversation — is what releases the uncertain-dispatch latch.
        [deps.input, deps.clawChannel, deps.clawAction, deps.clawSender].forEach((node) => {
          if (!node || typeof node.addEventListener !== "function") return;
          node.addEventListener("input", deps.noteClawContentEdited);
          node.addEventListener("change", deps.noteClawContentEdited);
        });
      }

      return { wireManualForm, wireExecuteControls };
    },
  };
})();
