(() => {
  "use strict";

  // #7216 R5 A3 (pc-run): PC execution polling, unfinished-run resume, and
  // durable PC result recovery moved verbatim from app.js. Closure references
  // read live through deps getters; browser globals stay untouched.
  window.PadiemChatPcRunModule = {
    create(deps) {
      // The PC lane carries no live P01 stage, so its status chip follows the
      // run's own observed status. The wording is the existing stage vocabulary,
      // and any status shown here is settled by the run's terminal outcome.
      function showPcRuntimeStatus(article, kind) {
        const text = window.PadiemClawRunEventProjection?.label?.(
          kind, document.documentElement.lang
        );
        if (!text) return false;
        window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, text, "status");
        return true;
      }

      async function waitForAcceptedPcRun(article, handle, outboundMessages, signal, product) {
        const { run_id: runId, conversation_id: conversationId } = handle;
        const owner = deps.authState.user;
        if (!runId || !conversationId) return;
        // Chat/Claw separation: the pending run belongs to the product that submitted it, so
        // the guard compares that product's own conversation id.
        for (;;) {
          if (signal.aborted || !article.isConnected || deps.authState.authenticated !== true
              || deps.authState.user !== owner
              || deps.conversationState.getConversationId?.(product) !== conversationId) return;
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
          if (signal.aborted || !article.isConnected || deps.authState.user !== owner
              || deps.conversationState.getConversationId?.(product) !== conversationId) return;
          const response = await fetch(
            "/api/claw/runs/" + encodeURIComponent(runId) + "/pending-result",
            { headers: { Accept: "application/json" }, cache: "no-store", signal }
          );
          if (!response.ok) return;
          const data = await response.json();
          const result = data?.result;
          if (!result || result.run_id !== runId || result.conversation_id !== conversationId) return;
          if (deps.authState.user !== owner || deps.conversationState.getConversationId?.(product) !== conversationId
              || !article.isConnected || signal.aborted) return;
          if (result.status === "pending" || result.status === "running") {
            // A server-observed "running" is a real fact: the Engine reached a PC
            // step for this run. "pending" adds nothing over the preparing chip.
            if (result.status === "running") {
              // A running turn shows its status on the card, which owns that
              // surface, so the observed step is carried as the card's own hint.
              window.PadiemChatLifecycle?.setTaskHint?.(article, "tool");
              deps.showPcRuntimeStatus(article, "tool_started");
            }
            continue;
          }
          if (result.status !== "completed" || typeof result.answer !== "string") {
            window.PadiemChatLifecycle?.setTaskHint?.(article, null);
            if (result.reason === "pc_read_failed") {
              deps.showPcRuntimeStatus(article, "pc_read_failed");
            } else {
              deps.showPcRuntimeStatus(article, "run_failed");
            }
            PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.FAILED);
            return;
          }
          // #5015: only a verified PC command result may replace this article as
          // the run's completed PC result. A model reply is not a PC execution:
          // the model's own answer stays in place, and it is never presented as a
          // completed PC run.
          if (result.answer_source !== "pc_command_result") {
            if (result.answer_source === "model_reply") {
              // A model reply is not a completed PC execution, so a tool-running
              // status observed while waiting is released rather than confirmed.
              window.PadiemChatLifecycle?.setTaskHint?.(article, null);
              window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, "", "status");
              PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.COMPLETED);
            }
            return;
          }
          if (deps.resolvedPcRuns.has(runId)) return;
          deps.resolvedPcRuns.add(runId);
          const content = article.querySelector(".assistant-content");
          content.replaceChildren();
          window.PadiemChatPcScopeNotice?.render?.(content, result.scope_notice);
          const paragraph = document.createElement("p");
          paragraph.textContent = result.answer;
          content.appendChild(paragraph);
          // The durable run answered: the preparing chip is released, and a
          // tool-running status shown while waiting settles on this run's real
          // completion instead of being left stale.
          window.PadiemChatLifecycle?.setTaskHint?.(article, null);
          window.PadiemChatLifecycle?.releasePreparingRuntimeLabel?.(article);
          deps.showPcRuntimeStatus(article, "run_completed");
          deps.conversationState.setProduct?.(product);
          deps.conversationState.commitAssistant(outboundMessages, result.answer);
          deps.conversationState.setProduct?.(deps.conversationProduct);
          PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.COMPLETED);
          if (deps.authState.authenticated) deps.loadRecentConversations();
          return;
        }
      }

      // #5895: a PC turn keeps running on the server after this tab goes away, and
      // the owner's run history already names unfinished runs (#3139 reconciles a
      // finished result back into the conversation that started it). Reopening that
      // conversation continues the same "still working" display, with the elapsed
      // time the server's own run row carries, and the stored answer lands in the
      // thread through the existing restore path. Nothing is submitted from here,
      // and no attempt count or deadline is chosen here.
      function pcWaitElapsed(createdAt) {
        const started = Date.parse(createdAt);
        if (!Number.isFinite(started)) return null;
        const clock = window.PadiemChatLifecycle?.elapsedClockText;
        if (typeof clock !== "function") return null;
        return clock(Math.max(0, Date.now() - started));
      }

      async function findUnfinishedPcRun(conversationId) {
        let runs = [];
        try {
          const response = await fetch("/api/claw/runs", {
            headers: { "Accept": "application/json" }, cache: "no-store",
          });
          const data = await response.json().catch(() => null);
          if (response.ok && data?.ok === true && Array.isArray(data.runs)) runs = data.runs;
        } catch (_) {
          // A failed read adds no knowledge: the run is never replayed from here.
          return null;
        }
        return runs.find((run) => run
          && window.PadiemChatPcRecovery?.validRunId?.(run.run_id) === true
          && (run.status === "pending" || run.status === "running")
          && run.session?.conversation_id === conversationId) || null;
      }

      async function resumeUnfinishedPcRun(conversationId) {
        if (!conversationId || !deps.pcResultRecovery) return;
        const unfinished = await deps.findUnfinishedPcRun(conversationId);
        if (!unfinished || deps.resolvedPcRuns.has(unfinished.run_id)) return;
        const showWait = () => {
          const elapsed = deps.pcWaitElapsed(unfinished.created_at);
          deps.setNote(elapsed
            ? deps.uiT("pc-elapsed-note", { elapsed })
            : deps.uiT("pc-processing-note"), "status");
        };
        showWait();
        let result;
        try {
          result = await deps.pcResultRecovery.waitForResult({
            runId: unfinished.run_id, conversationId, onPending: showWait,
          });
        } catch (_) {
          // The read was cancelled or the tab moved on; the run keeps running.
          return;
        }
        if (result.kind === "pending") return;
        // This tab will not read that run again. A completed answer lands in the
        // thread; any other verdict only stops this screen from claiming that work
        // is still happening, because the client cannot see its outcome and is not
        // the one that decides what a finished PC run said.
        deps.resolvedPcRuns.add(unfinished.run_id);
        deps.setNote(deps.idleNote());
        if (result.kind === "completed" && result.conversationId === conversationId) {
          await deps.openSavedConversation(conversationId);
        }
      }

      function renderStoredPcAnswer(article, result, outboundMessages, contextSnapshot) {
        const content = article.querySelector(".assistant-content");
        if (!content) return false;
        const product = contextSnapshot.product || deps.conversationProduct;
        content.replaceChildren();
        // The recovery GET carries the same pinned notice as the live POST.
        window.PadiemChatPcScopeNotice?.render?.(content, result.scopeNotice);
        const paragraph = document.createElement("p");
        paragraph.textContent = result.answer;
        content.appendChild(paragraph);
        window.PadiemChatLifecycle?.releasePreparingRuntimeLabel?.(article);
        // The preparing release deliberately keeps a chip that already carries a
        // real status, and the PC wait paints one for the step it observed. A
        // recovered answer is that run's outcome, so the running wording is
        // released here too; it must not stay on a turn that has already answered.
        window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, "", "status");
        deps.conversationState.setProduct?.(product);
        if (result.conversationId) deps.conversationState.setConversationId(result.conversationId, product);
        deps.conversationState.commitAssistant(outboundMessages, result.answer);
        deps.conversationState.setProduct?.(deps.conversationProduct);
        PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.COMPLETED);
        if (deps.authState.authenticated) deps.loadRecentConversations();
        article.scrollIntoView?.({ block: "nearest", behavior: "smooth" });
        return true;
      }

      // A long PC turn can outlive the browser connection. The server may already
      // have persisted the canonical answer, so recover it with the owner-scoped
      // run GET. This path never submits the PC turn again.
      async function recoverStoredPcResult(article, contextSnapshot, outboundMessages, skill, signal) {
        const runId = contextSnapshot?.pcRunId;
        if (!runId || !deps.pcResultRecovery || deps.resolvedPcRuns.has(runId)) return false;
        let first;
        try {
          first = await deps.pcResultRecovery.recoverOnce({
            runId,
            conversationId: contextSnapshot.conversationId,
            signal,
          });
        } catch (error) {
          if (error && error.name === "AbortError") throw error;
          return false;
        }
        if (first.kind === "duplicate") return true;
        if (first.kind === "completed") {
          deps.resolvedPcRuns.add(runId);
          return deps.renderStoredPcAnswer(article, first, outboundMessages, contextSnapshot);
        }
        if (first.kind !== "pending") {
          // A 404 means the server has no such result. Forget this run here and
          // now, so a retry over the same handle skips the check and renders its
          // own failure instead of reading a gone run again.
          if (first.gone === true) deps.resolvedPcRuns.add(runId);
          return false;
        }
        if (first.conversationId) {
          deps.conversationState.setConversationId(first.conversationId, contextSnapshot.product);
        }
        PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.STREAMING);
        void deps.pcResultRecovery.waitForResult({
          runId,
          conversationId: first.conversationId,
          signal,
        }).then((result) => {
          if (result.kind === "completed") {
            if (!deps.resolvedPcRuns.has(runId)) {
              deps.resolvedPcRuns.add(runId);
              deps.renderStoredPcAnswer(article, result, outboundMessages, contextSnapshot);
            }
            return;
          }
          if (result.kind === "pending") {
            // #5895: an unfinished run is not a failed run. Say what is actually
            // true — still processing, and the stored answer lands in this
            // conversation — instead of a failure the owner cannot act on.
            PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.STREAMING);
            window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, deps.uiT("pc-processing-note"), "status");
            return;
          }
          if (result.gone === true) deps.resolvedPcRuns.add(runId);
          if (article.isConnected && !signal.aborted) {
            deps.renderStreamError(article, deps.uiT("stream-incomplete"), outboundMessages, skill, contextSnapshot, false);
          }
        }).catch((error) => {
          if (error && error.name === "AbortError") return;
          if (article.isConnected && !signal.aborted) {
            PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.FAILED);
          }
        });
        return true;
      }

      return {
        showPcRuntimeStatus,
        waitForAcceptedPcRun,
        pcWaitElapsed,
        findUnfinishedPcRun,
        resumeUnfinishedPcRun,
        renderStoredPcAnswer,
        recoverStoredPcResult,
      };
    },
  };
})();
