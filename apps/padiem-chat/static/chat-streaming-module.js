// #7216 R5 5b - streaming section (request lifetime) moved out of the app.js
// closure. No behavior, copy, DOM id or event name change. The request
// bookkeeping state (epoch, in-flight, controllers, cancel reasons, claw run
// id) is read/written only through the deps getters/setters. app.js keeps the
// same-named one-line forwarders.
(() => {
  "use strict";
  window.PadiemChatStreamingModule = {
    create(deps) {
  async function requestCompletedAnswer(article, payload, outboundMessages, attachment, contextSnapshot, signal) {
    const sessionScope = window.PadiemChatPcSessionModule?.captureScope?.();
    window.PadiemChatLifecycle?.startTurnClock?.(article);
    const data = await deps.chatTransport.requestCompleted(payload, signal);
    deps.renderAnswer(article, data);
    // Chat/Claw separation: the completion belongs to the product that submitted it, even
    // when the user navigated to the other product while it was in flight.
    deps.conversationState.setProduct?.(contextSnapshot.product);
    deps.conversationState.commitAssistant(outboundMessages, data.answer);
    if (typeof data.conversation_id === "string") deps.conversationState.setConversationId(data.conversation_id);
    deps.conversationState.setProduct?.(deps.conversationProduct);
    if (!signal.aborted) window.PadiemChatPcSessionModule?.render?.(data, sessionScope);
    if (typeof data.project_id === "string") {
      const resolvedProject = deps.projectById(data.project_id) || contextSnapshot.project;
      if (resolvedProject) deps.activeProject = resolvedProject;
    }
    deps.renderProjectState();
    if (deps.authState.authenticated) {
      deps.loadRecentConversations();
      if (deps.projectsReady) deps.loadProjects();
      window.PadiemChatMemoryReview?.sync?.();
    }
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
    return true;
  }
  function applyStreamDone(article, data, answer, outboundMessages, contextSnapshot) {
    // The answer is complete: the "answer preparing" chip is released here.
    // A chip that already carries a real status (a Claw P01 stage, a skill
    // title) is kept, and a failure keeps its own status.
    window.PadiemChatLifecycle?.releasePreparingRuntimeLabel?.(article);
    // Chat/Claw separation: the completion belongs to the product that submitted it, even
    // when the user navigated to the other product while it was in flight.
    deps.conversationState.setProduct?.(contextSnapshot.product);
    deps.conversationState.commitAssistant(outboundMessages, answer);
    if (typeof data.conversation_id === "string") deps.conversationState.setConversationId(data.conversation_id);
    deps.conversationState.setProduct?.(deps.conversationProduct);
    // #4469: render the terminal sources the backend already validated and sent
    // (https url + title + retrieved_at). Nothing here trusts or re-requests
    // them; the bounded renderer in claw-answer-sources.js stays the single
    // display authority, and a frame without sources leaves the answer surface
    // unchanged — a model-only answer is never shown as a searched answer.
    if (Array.isArray(data.sources) && data.sources.length) {
      window.PadiemClawAnswerSources?.render(article, data.sources);
    }
    // #4469: an automatic public search answers on the P01 lane and returns
    // its evidence in the same browser contract an explicit search uses. The
    // same bounded renderer shows the sources, so a searched answer is never
    // shown as a model-only answer.
    if (Array.isArray(data.evidence) && data.evidence.length) {
      window.PadiemSearchSources?.render?.(article, data.evidence);
      if (data.tool && data.tool.id === "web_search") {
        window.PadiemChatLifecycle?.recordTaskEvent?.(article, "web_search");
      }
      article.dataset.taskEvidence = "true";
      window.PadiemChatLifecycle?.recordTaskEvent?.(article, "evidence");
    }
    if (typeof data.project_id === "string") {
      const snapshotProject = contextSnapshot.project && contextSnapshot.project.id === data.project_id ? contextSnapshot.project : null;
      const boundedProject = data.project && data.project.id === data.project_id && typeof data.project.name === "string" ? data.project : null;
      const resolvedProject = deps.projectById(data.project_id) || snapshotProject || boundedProject;
      if (resolvedProject) deps.activeProject = resolvedProject;
    }
    if (Number.isInteger(data.project_files_used) && data.project_files_used > 0) {
      const used = document.createElement("small");
      used.className = "reference-note";
      used.textContent = deps.uiT("project-files-used", { count: data.project_files_used });
      article.querySelector(".assistant-content").appendChild(used);
    }
    deps.renderWebGroundingNotice(article.querySelector(".assistant-content"), data.notice, data.metadata);
    // #5573: the live PC scope notice is its own line above the answer.
    window.PadiemChatPcScopeNotice?.render?.(
      article.querySelector(".assistant-content"),
      data.scope_notice,
    );
    if (Array.isArray(data.memory_proposals)) {
      window.PadiemChatMemoryReview?.render?.(data.memory_proposals);
    }
    deps.renderProjectState();
    if (deps.authState.authenticated) {
      deps.loadRecentConversations();
      if (deps.projectsReady) deps.loadProjects();
      window.PadiemChatMemoryReview?.sync?.();
    }
    // Owner 2026-10-20: the answer carries the moment it completed. It is
    // turn metadata on the rendered message, not a second storage structure,
    // and it is stamped once the stream is done.
    if (!article.dataset.completedAt) {
      article.dataset.completedAt = new Date().toISOString();
    }
    PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.COMPLETED);
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  async function requestStreamingAnswer(article, payload, outboundMessages, skill, contextSnapshot, signal, route) {
    const sessionScope = window.PadiemChatPcSessionModule?.captureScope?.();
    // #5573 §7: the elapsed clock starts with the request, not with the first
    // frame. It reports only how long the turn has been in flight.
    window.PadiemChatLifecycle?.startTurnClock?.(article);
    // #3539: product-state-aware routing. A generic B54 Claw submit runs on the
    // canonical P01 Engine lane; the standalone Padiem Chat path keeps the
    // existing /api/chat/stream transport call byte-for-byte.
    // The decision is an immutable snapshot taken before showConversation()
    // mutates shell.dataset.state, so it is never re-derived from live state.
    const clawGeneralRequest = !!(route && route.clawGeneral);
    // #3930: no fabricated stages. Only validated server-emitted P01 envelopes
    // can change the runtime label; a legacy delta/done stream retains its
    // existing truthful response status.
    const canonicalEventProjection = clawGeneralRequest ? window.PadiemClawRunEventProjection?.create?.() : null;
    const verifiedClawRecovery = clawGeneralRequest ? window.PadiemClawRecoveryTruth?.create?.() : null;
    const historicalStages = [];
    // #5221: the accepted canonical envelopes of this run, so the shared work
    // card can show the real stages of the run while it happens. Only an
    // envelope the canonical projection accepted is collected, and the card
    // validates the list again before it renders anything.
    const liveOrchestrationEvents = [];
    const stageForOrchestrationKind = Object.freeze({
      run_started: "request_accepted",
      context_prepared: "question_checked",
      memory_read: "reference_context",
      plan_created: "planning",
      skill_resolved: "planning",
      tool_resolution: "tool_check",
      tool_started: "tool_started",
      tool_completed: "tool_completed",
      tool_failed: "tool_failed",
      evidence_attached: "evidence",
      verification_completed: "evidence",
      run_resumed: "question_checked",
      recovery_started: "tool_started",
      recovery_decided: "tool_check",
      retry_started: "tool_started",
      retry_completed: "tool_completed",
    });
    let streamStatusOpened = false;
    function revealStreamStatus() {
      if (streamStatusOpened) return;
      const disclosure = article.querySelector(".capability-kit-disclosure");
      if (!disclosure) return;
      disclosure.open = true;
      streamStatusOpened = true;
    }
    function safeThoughtSummary(value) {
      if (typeof value !== "string") return "";
      let summary = value.trim().slice(0, 2000);
      const userPrompts = Array.isArray(payload?.messages)
        ? payload.messages.filter((item) => item?.role === "user" && typeof item.content === "string")
            .map((item) => item.content.trim()).filter(Boolean).sort((left, right) => right.length - left.length)
        : [];
      for (const prompt of userPrompts) {
        if (prompt.length <= 3 && summary.includes(prompt)) return "";
        summary = summary.replaceAll(prompt, "[user prompt omitted]");
      }
      return summary
        .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]{8,}/gi, "Bearer [secret redacted]")
        .replace(/\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{12,}|AIza[A-Za-z0-9_-]{20,})\b/g, "[secret redacted]")
        .replace(/\b(api[_ -]?key|access[_ -]?token|token|password|secret)\s*[:=]\s*["']?[^,\s"'`]+/gi, "$1: [redacted]")
        .replace(/\b([A-Za-z][A-Za-z0-9_-]*_id)\s*[:=]\s*["']?[A-Za-z0-9_.:-]+/gi, "$1: [internal ID redacted]")
        .replace(/\b(?:run|trace|dsp|pcr|evt|event|dispatch|pc|conversation|request|tenant|user|session|continuation|message|turn|chat|app)_[A-Za-z0-9][A-Za-z0-9_.:-]*\b/gi, "[internal ID redacted]")
        .replace(/\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b/gi, "[internal ID redacted]")
        .replace(/\b[0-9a-f]{16,}\b/gi, "[internal ID redacted]")
        .replace(/(https?:\/\/[^\s"'`<>?#]+)\?[^\s"'`<>#]*/gi, "$1?[query redacted]")
        .replace(/\b[A-Za-z]:[\\/][^\s"'`<>?#]*/g, "[file path redacted]")
        .replace(/\\\\[^\\/\s]+[\\/][^\s"'`<>?#]*/g, "[file path redacted]")
        .replace(/(^|[\s("'`=,:;])~\/[^\s"'`<>?#]*/gm, "$1[file path redacted]")
        .replace(/(^|[\s("'`=,:;])\/(?!\/)[^\s"'`<>?#]*/gm, "$1[file path redacted]");
    }
    function renderThoughtSummary(value) {
      const summaryText = safeThoughtSummary(value);
      if (!summaryText) return;
      // #7459: one panel renderer for both thought streams, so markdown,
      // internal-tool hiding and the status/thought/answer order stay shared.
      window.PadiemChatThoughtPanel?.renderSummary?.(article, summaryText, {
        label: deps.uiT("orchestration-thought-summary-label"),
      });
    }
    // #7297: Chat and Claw share the Chat direct execution path; only the
    // product label differs.
    const response = await deps.chatTransport.requestStreaming(payload, signal);
    const responseContentType = response.headers?.get?.("content-type") || "";
    const shouldFollowStream = !/\bapplication\/json\b/i.test(responseContentType);
    const pcProgressRunId = window.PadiemPcBrowserSurface?.runIdForProgress?.(
      response, payload, clawGeneralRequest
    ) ?? payload.pc_run_id ?? null;
    deps.activeClawRunId = clawGeneralRequest && typeof pcProgressRunId === "string"
      ? pcProgressRunId : null;

    let answer = "";
    let paragraph = null;
    let answerTextNode = null;
    let streamScrollTrackingStarted = false;
    let done = false;
    let terminalError = false;
    // #3935: terminal P01 events outrank a later transport done/connection
    // loss. Keep any partial text, show bounded status, never mint an approval
    // button or silently submit a second request.
    function showVerifiedClawRecovery(state) {
      const content = article.querySelector(".assistant-content");
      const typing = content?.querySelector(".typing");
      if (typing) typing.remove();
      const status = document.createElement("p");
      status.className = "claw-recovery-truth";
      status.setAttribute("role", "status");
      status.textContent = window.PadiemClawRecoveryTruth.copy(state, document.documentElement.lang);
      content?.appendChild(status);
      const marker = article.querySelector("[data-runtime-label]");
      if (marker) {
        marker.textContent = status.textContent;
        window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, status.textContent, "status");
      }
      PadiemChatLifecycle.set(article, state === "waiting_for_approval"
        ? deps.MESSAGE_LIFECYCLE.WAITING_APPROVAL
        : state === "cancelled" ? deps.MESSAGE_LIFECYCLE.CANCELLED : deps.MESSAGE_LIFECYCLE.FAILED);
      deps.revealErrorState(article);
    }
    try {
      await deps.chatTransport.readSseEvents(response, async (frame) => {
        if (frame.event === "meta") {
          revealStreamStatus();
          window.PadiemChatLifecycle?.recordTaskEvent?.(article, "request_accepted");
          return false;
        }
        if (frame.event === "progress") {
          let value;
          try { value = JSON.parse(frame.data); } catch (_) { return false; }
          if (window.PadiemChatLifecycle?.recordProgressFrame?.(article, value)) revealStreamStatus();
          return false;
        }
        if (frame.event === "thought_summary") {
          let value;
          try { value = JSON.parse(frame.data); } catch (_) { return false; }
          renderThoughtSummary(value && value.summary);
          return false;
        }
        if (window.PadiemChatThoughtPanel?.handleFrame?.(article, frame, {
          activeLabel: deps.uiT("orchestration-thinking-label"),
          sanitize: safeThoughtSummary,
        })) return false;
        if (frame.event === "orchestration_event") {
          revealStreamStatus();
          let value;
          try { value = JSON.parse(frame.data); } catch (_) { return false; }
          const kind = value && typeof value.kind === "string" ? value.kind : "";
          const metadata = value && value.metadata && typeof value.metadata === "object" ? value.metadata : {};
          const toolId = metadata.tool_id === "web_search" || metadata.tool_id === "pc_tool"
            ? metadata.tool_id : "";
          if (kind === "thought_summary") renderThoughtSummary(value.summary);
          if (toolId === "web_search") window.PadiemChatLifecycle?.recordTaskEvent?.(article, "web_search");
          if (toolId === "pc_tool") window.PadiemChatLifecycle?.recordTaskEvent?.(article, "pc_work");
          const stage = stageForOrchestrationKind[kind];
          if (stage) window.PadiemChatLifecycle?.recordTaskEvent?.(article, stage);
          return false;
        }
        if (frame.event === "tool") {
          revealStreamStatus();
          let value;
          try { value = JSON.parse(frame.data); } catch (_) { return false; }
          if (value && (value.id === "web_search" || value.tool_id === "web_search")) {
            window.PadiemChatLifecycle?.recordTaskEvent?.(article, "web_search");
          } else if (value && (value.id === "pc_tool" || value.tool_id === "pc_tool")) {
            window.PadiemChatLifecycle?.recordTaskEvent?.(article, "pc_work");
          }
          const stage = value && value.status === "completed" ? "tool_completed"
            : value && value.status === "failed" ? "tool_failed" : "tool_started";
          window.PadiemChatLifecycle?.recordTaskEvent?.(article, stage);
          return false;
        }
        if (["pc_progress", "heartbeat", "scope_notice"].includes(frame.event)) {
          let value;
          try { value = JSON.parse(frame.data); } catch (_) { return false; }
          if (frame.event === "pc_progress") {
            if (window.PadiemChatLifecycle?.recordPcProgress?.(article, value, pcProgressRunId)) {
              revealStreamStatus();
              window.PadiemChatLifecycle?.recordTaskEvent?.(article, "pc_work");
            }
          } else if (frame.event === "heartbeat") {
            window.PadiemChatLifecycle?.recordPcHeartbeat?.(article, value);
          } else {
            window.PadiemChatPcScopeNotice?.render?.(article.querySelector(".assistant-content"), value.scope_notice);
          }
          return false;
        }
        if (frame.event === "p01_event") {
          if (!clawGeneralRequest || !canonicalEventProjection) return false;
          let envelope;
          try { envelope = JSON.parse(frame.data); } catch (_) { return false; }
          if (envelope.delivery !== "live" && envelope.delivery !== "post_execution") return false;
          const projected = canonicalEventProjection.consume(envelope);
          if (!projected.accepted) return false;
          // #3935: only an accepted canonical event can affect terminal truth.
          verifiedClawRecovery?.observe(projected.kind);
          const label = window.PadiemClawRunEventProjection.label(projected.kind, document.documentElement.lang);
          if (envelope.delivery === "post_execution") {
            // The Engine returned a completed run, not an actual live event.
            // Preserve truth: show these labels only as a retrospective log.
            if (label && historicalStages.length < 12) historicalStages.push(label);
            return false;
          }
          const marker = article.querySelector("[data-runtime-label]");
          // A Claw P01 stage is a real status: it replaces the preparing chip
          // and is kept when the run completes.
          if (label && marker) {
            marker.textContent = label;
            window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, label, "status");
          }
          // #5221: the shared work card shows the real stages of this run.
          // The card re-validates the list, so an envelope that does not
          // belong to this run is not rendered. The card is a presentation
          // extra: the stage labels are already on the status chip, and
          // drawing the card must never break the answer stream.
          liveOrchestrationEvents.push(envelope);
          try {
            window.PadiemChatOrchestrationUI?.render?.(article, { events: liveOrchestrationEvents }, {});
          } catch (_) {
            // The answer does not depend on the card.
          }
          return false;
        }
        if (!["delta", "done", "error"].includes(frame.event)) return false;
        let data;
        try {
          data = JSON.parse(frame.data);
        } catch (_) {
          throw new Error(deps.uiT("stream-format-invalid"));
        }
        if (frame.event === "delta") {
          // Never append new content after a verified P01 failure, cancellation
          // or approval pause; a later delta cannot revive a stopped run.
          if (clawGeneralRequest && verifiedClawRecovery && !verifiedClawRecovery.completionAllowed()) return false;
          if (!data || typeof data.delta !== "string") throw new Error(deps.uiT("stream-format-invalid"));
          if (!data.delta) return false;
          let streamScrollIntent = null;
          if (shouldFollowStream) {
            try {
              streamScrollIntent = window.__padiemConversationMotion?.beforeStreamingDelta?.() ?? null;
              if (typeof streamScrollIntent === "boolean") streamScrollTrackingStarted = true;
            } catch (_) {
              // Scrolling is presentation-only; it must never interrupt a reply.
            }
          }
          if (!paragraph) {
            const content = article.querySelector(".assistant-content");
            content.replaceChildren();
            paragraph = document.createElement("p");
            if (typeof document.createTextNode === "function") {
              answerTextNode = document.createTextNode("");
            } else {
              // Minimal fallback for older DOM shims. Browsers take the native
              // Text.appendData path, while test hosts keep the legacy text view.
              answerTextNode = {
                data: "",
                appendData(value) {
                  this.data += value;
                  paragraph.textContent = this.data;
                },
              };
            }
            paragraph.appendChild(answerTextNode);
            content.appendChild(paragraph);
            // #5559: the first token is a real fact. The status moves from
            // "preparing" to "generating" and the step is recorded.
            article.dataset.answerStarted = "true";
            window.PadiemChatLifecycle?.recordTaskEvent?.(article, "answer_started");
          }
          answer += data.delta;
          if (!window.PadiemChatLifecycle?.appendStreamDelta?.(answerTextNode, data.delta)) {
            answerTextNode.appendData(data.delta);
          }
          if (typeof streamScrollIntent === "boolean") {
            try {
              window.__padiemConversationMotion?.afterStreamingDelta?.(streamScrollIntent);
            } catch (_) {
              // Scrolling is presentation-only; it must never interrupt a reply.
            }
          }
          return false;
        }
        if (frame.event === "error") {
          if (clawGeneralRequest && verifiedClawRecovery && !verifiedClawRecovery.completionAllowed()) {
            terminalError = true;
            showVerifiedClawRecovery(verifiedClawRecovery.state());
            return true;
          }
          const clawFailure = clawGeneralRequest
            ? deps.clawGeneralFailure(data && data.error ? data.error.code : "")
            : null;
          const message = clawGeneralRequest
            ? clawFailure.message
            : deps.chatTransport.streamErrorMessage(data);
          if (clawGeneralRequest && !paragraph) throw deps.chatTransport.errorFor(data, message);
          // #5895: on the PC lane a cut stream is not a refusal. The run keeps
          // executing on the server and its answer is persisted, so keep this
          // turn in its processing state and let the owner-scoped pending-result
          // recovery below read the stored answer instead of claiming a failure.
          if (contextSnapshot?.pcRunId && deps.chatTransport.isStreamLoss?.(data)) {
            PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.STREAMING);
            window.PadiemChatLifecycle?.applyRuntimeLabel?.(article, deps.uiT("pc-processing-note"), "status");
            throw deps.chatTransport.errorFor(data, message);
          }
          // An explicit refusal is terminal even before the first token.
          // Handle it here so the outer catch never starts pending-result GETs.
          terminalError = true;
          const terminalFailure = deps.chatTransport.errorFor(data, message);
          deps.renderStreamError(article, message, outboundMessages, skill, contextSnapshot, clawGeneralRequest, deps.lifecycleForError(terminalFailure), clawFailure, terminalFailure.code);
          return true;
        }
        if (clawGeneralRequest && verifiedClawRecovery && !verifiedClawRecovery.completionAllowed()) {
          terminalError = true;
          showVerifiedClawRecovery(verifiedClawRecovery.state());
          return true;
        }
        if (!data || data.done !== true || !paragraph || !answer) throw new Error(deps.uiT("stream-complete-invalid"));
        if (done) throw new Error(deps.uiT("stream-done-duplicate"));
        done = true;
        window.PadiemChatThoughtPanel?.settle?.(
          article, deps.uiT("orchestration-thinking-done-label"),
        );
        if (data.pc_pending === true
            && typeof data.run_id === "string"
            && typeof data.conversation_id === "string") {
          const pendingConversationId = data.conversation_id;
          deps.conversationState.setConversationId(pendingConversationId, contextSnapshot.product);
          PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.STREAMING);
          void deps.waitForAcceptedPcRun(article, data, outboundMessages, signal, contextSnapshot.product)
            .catch(() => { if (article.isConnected && !signal.aborted) {
              PadiemChatLifecycle.set(article, deps.MESSAGE_LIFECYCLE.FAILED);
            } });
          return true;
        }
        deps.applyStreamDone(article, data, answer, outboundMessages, contextSnapshot);
        if (!signal.aborted) window.PadiemChatPcSessionModule?.render?.(data, sessionScope);
        if (historicalStages.length) {
          const details = document.createElement("details");
          details.className = "claw-event-history";
          const summary = document.createElement("summary");
          summary.textContent = deps.uiT("claw-event-history-post-execution");
          const stages = document.createElement("ul");
          for (const label of historicalStages) {
            const item = document.createElement("li");
            item.textContent = label;
            stages.appendChild(item);
          }
          details.append(summary, stages);
          article.querySelector(".assistant-body")?.appendChild(details);
        }
        return true;
      });
      if (done) return true;
      if (terminalError) return false;
      // No transport done: a *verified* P01 failure/cancellation/approval pause
      // still has to be represented truthfully, not replaced with "completed".
      if (clawGeneralRequest && verifiedClawRecovery && !verifiedClawRecovery.completionAllowed()) {
        showVerifiedClawRecovery(verifiedClawRecovery.state());
        return false;
      }
      throw new Error(deps.uiT("stream-incomplete"));
    } catch (error) {
      if (error && error.name === "AbortError") throw error;
      if (clawGeneralRequest && verifiedClawRecovery && !verifiedClawRecovery.completionAllowed()) {
        showVerifiedClawRecovery(verifiedClawRecovery.state());
        return false;
      }
      // The PC lane may already have persisted its answer. Let the outer
      // request catch perform the owner-scoped recovery instead of rendering a
      // premature connection error from the incomplete stream.
      if (contextSnapshot?.pcRunId && !terminalError) throw error;
      if (paragraph) {
        if (clawGeneralRequest) {
          const clawFailure = deps.clawGeneralFailure(error && error.code);
          deps.renderStreamError(article, clawFailure.message,
            outboundMessages, skill, contextSnapshot, true, deps.MESSAGE_LIFECYCLE.FAILED, clawFailure);
        } else {
          // Preserve the original standalone Chat catch path and its existing
          // rich-stream/browser contract. Only Claw uses bounded safe copy.
          deps.renderStreamError(article, error instanceof Error ? error.message : deps.uiT("stream-continue-failed"),
            outboundMessages, skill, contextSnapshot, false, deps.MESSAGE_LIFECYCLE.FAILED, null,
            error && typeof error.code === "string" ? error.code : "");
        }
        return false;
      }
      throw error;
    } finally {
      if (streamScrollTrackingStarted) {
        try {
          window.__padiemConversationMotion?.endStreaming?.();
        } catch (_) {
          // Keep stream cleanup independent from the scroll presentation.
        }
      }
    }
  }
  function cancelActiveStream() {
    if (!deps.inFlight || !deps.activeRequestController || !deps.activeRequestArticle) return;
    deps.activeRequestCancelReason = "user_cancel";
    const runId = deps.activeClawRunId;
    if (runId) {
      // The stop is a server-side fact, not only a dropped stream: the server
      // records the stop time and refuses any PC action created after it, so
      // an action the loop had not sent yet is never sent, and an action that
      // was already sent is never sent again.
      fetch("/api/pc/cancel", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId }),
      }).then((response) => (response.ok ? response.json() : null))
        .then((data) => {
          deps.invalidateClawRunsRead();
          deps.setNote(deps.uiT(data && data.ok === true ? "pc-stop-sent" : "pc-stop-failed"), "status");
        })
        .catch(() => deps.setNote(deps.uiT("pc-stop-failed"), "status"));
    }
    deps.activeRequestController.abort();
    if (!runId) deps.setNote(deps.uiT("answer-cancelled-note"), "error");
  }
  async function requestAnswer(outboundMessages, skill, attachment, contextSnapshot, clawGeneralRequest, explicitRetry = false) {
    if (deps.inFlight) return false;
    deps.inFlight = true;
    deps.activeRequestCancelReason = null;
    const requestEpoch = deps.conversationEpoch;
    const controller = new AbortController();
    deps.activeRequestController = controller;
    deps.updateComposer();
    const article = deps.addAssistantShell(deps.uiT("answer-preparing"), "preparing");
    deps.activeRequestArticle = article;
    // #5559: the status card is the one status surface of this turn. It is
    // rendered from the first moment, so the reader sees the real state while
    // the answer is still being produced.
    window.PadiemChatLifecycle?.recordTaskEvent?.(article, "request_sent");
    window.PadiemChatLifecycle?.renderTaskStatus?.(article);
    deps.renderTyping(article);
    try {
      // #5222: wait for the account's tier restore to settle before the tier
      // is read, so a request never leaves with a tier that was not verified
      // for this account yet.
      await window.PadiemTierSelection?.ready?.();
      const payload = { messages: outboundMessages, tier: deps.selectedProductTier(), skill };
      if (clawGeneralRequest || contextSnapshot?.product === "claw") payload.product = "claw";
      // #4745: retain the exact user-turn claim for a manual retry. A new
      // submitPrompt receives a new contextSnapshot, so a separate identical
      // request obtains a distinct key; explicit retry reuses this snapshot.
      if (!contextSnapshot.calendarTurnId) {
        contextSnapshot.calendarTurnId = deps.chatTransport.createCalendarTurnId?.() || null;
      }
      if (contextSnapshot.calendarTurnId) payload.calendar_turn_id = contextSnapshot.calendarTurnId;
      // PADIEM Custom is the customer-owned key lane: it replaces the PADIEM
      // tier for this request (the server rejects tier+custom) and stays on the
      // direct provider path, never through B14 orchestration.
      const customSelection = window.PadiemCustomSelection?.get?.();
      if (customSelection) {
        delete payload.tier;
        payload.custom = { provider: customSelection.provider, model: customSelection.model };
        if (customSelection.reasoning_effort) {
          payload.custom.reasoning_effort = customSelection.reasoning_effort;
        }
      }
      // The long PC lane can outlive the browser's request. Generate the
      // canonical run handle before submit so a dropped response can be
      // recovered by an owner-scoped GET instead of resubmitting the PC turn.
      // An explicit retry reuses the failed request's handle; the server
      // refuses to rewrite an existing run, so a retry cannot silently start a
      // second PC execution. A new submit gets a new snapshot/handle.
      const pcRunId = !customSelection
        ? (contextSnapshot.pcRunId || deps.chatTransport.createChatPcRunId?.()) : null;
      if (pcRunId) {
        contextSnapshot.pcRunId = pcRunId;
        payload.pc_run_id = pcRunId;
      }
      // #6828: grade-only Claw execution. No per-request model id is sent;
      // the server resolves the grade route. BYOK remains a separate Chat lane.

      // #3539: the routing decision arrives as a submit-time snapshot. It is
      // NEVER re-derived from live shell state here, because showConversation()
      // has already flipped shell.dataset.state to "chat" by the time this runs
      // (re-deriving it silently rerouted the generic Claw composer onto the
      // standalone /api/chat/stream lane in Production).
      // A generic B54 Claw submit runs on the canonical P01 Engine lane with no
      // direct-B14 /api/chat/stream fallback; the standalone Padiem Chat composer
      // keeps /api/chat/stream unchanged, and the explicit manual form submits
      // through clawManualForm below, never here.
      const attachmentItems = Array.isArray(attachment) ? attachment : (attachment ? [attachment] : []);
      const uploadedItems = [];
      for (const item of attachmentItems) {
        let current = item;
        if (current.fileLane && !current.fileId) {
          // #6579 step 3: chunk progress rides the same status line; the shared
          // module resumes a drop and owns the guidance shown on failure.
          const reference = await window.PadiemFileLane.upload(current.file, controller.signal, (state) => {
            if (!deps.projectFileStatus) return;
            deps.setNote(state.phase === "finalizing"
              ? deps.uiT("document-saving")
              : `${deps.uiT("document-saving")} ${state.percent}%`, "normal");
          });
          current = { ...current, ...reference };
        }
        uploadedItems.push(current);
      }
      attachment = uploadedItems;
      const attachments = deps.attachmentPayload(attachment);
      if (attachments) payload.attachments = attachments;
      if (contextSnapshot.conversationId) payload.conversation_id = contextSnapshot.conversationId;
      if (contextSnapshot.project) payload.project_id = contextSnapshot.project.id;
      // #2505: an attached document travels on the lane the product selected.
      // Chat keeps its existing completed-attachment request unchanged; a Claw
      // submit stays on the canonical P01 Engine lane and never falls back to
      // the standalone direct-B14 /api/chat route (#3539).
      if (attachments) {
        const completedOk = await deps.requestCompletedAnswer(article, payload, outboundMessages, attachment, contextSnapshot, controller.signal);
        if (completedOk) {
          deps.lastCompletedAnswerRequest = { outboundMessages, skill, attachment, contextSnapshot, clawGeneralRequest: Boolean(clawGeneralRequest), article };
        }
        return completedOk;
      }
      const streamOk = await deps.requestStreamingAnswer(
        article,
        payload,
        outboundMessages,
        skill,
        contextSnapshot,
        controller.signal,
        clawGeneralRequest ? { clawGeneral: true } : null,
      );
      if (streamOk) {
        deps.lastCompletedAnswerRequest = { outboundMessages, skill, attachment, contextSnapshot, clawGeneralRequest: Boolean(clawGeneralRequest), article };
      }
      return streamOk;
    } catch (error) {
      if (error && error.name === "AbortError") {
        if (deps.activeRequestCancelReason === "user_cancel" && requestEpoch === deps.conversationEpoch) {
          deps.renderCancelled(article, outboundMessages, skill, contextSnapshot, clawGeneralRequest);
        }
        return false;
      }
      if (requestEpoch !== deps.conversationEpoch) return false;
      deps.handleCustomRequestFailure(error);
      // A guest that bypassed the pre-send gate (stale auth state) still gets
      // the login path, never a raw provider error.
      if (error && error.code === "login_required") {
        deps.setNote(deps.uiT("model-requires-login"), "error");
        deps.openAuthDialog();
      }
      // An explicit retry replays the failed turn with that turn's own run
      // handle. When the server accepts it, reading the inherited handle back
      // reports it as still processing and never ends the retry turn; when the
      // server refuses it, no stored result can exist. Either way a failed
      // retry ends here, in its own failure card with its own retry action,
      // instead of sitting in the streaming state with a running clock.
      if (contextSnapshot?.pcRunId && !error?.terminalRecord
          && !error?.submissionRejected && !explicitRetry) {
        try {
          const recovered = await deps.recoverStoredPcResult(
            article, contextSnapshot, outboundMessages, skill, controller.signal,
          );
          if (recovered) return true;
        } catch (recoveryError) {
          if (recoveryError && recoveryError.name === "AbortError") return false;
        }
      }
      const clawFailure = clawGeneralRequest ? deps.clawGeneralFailure(error && error.code) : null;
      deps.renderError(
        article,
        clawGeneralRequest && error?.clawFailureDetail === "engine_provider_rate_limited"
          ? deps.uiT("claw-general-provider-limit")
          : clawGeneralRequest
            ? clawFailure.message
            : (error instanceof Error ? error.message : deps.uiT("try-again")),
        outboundMessages,
        skill,
        attachment,
        contextSnapshot,
        clawGeneralRequest,
        deps.lifecycleForError(error),
        clawFailure,
        error && typeof error.code === "string" ? error.code : "",
      );
      return false;
    } finally {
      if (deps.activeRequestController === controller) {
        deps.activeRequestController = null;
        deps.activeRequestArticle = null;
        deps.activeRequestCancelReason = null;
        deps.activeClawRunId = null;
        deps.inFlight = false;
        deps.updateComposer();
        deps.input.focus();
      }
    }
  }
      return {
        requestCompletedAnswer,
        applyStreamDone,
        requestStreamingAnswer,
        cancelActiveStream,
        requestAnswer,
      };
    },
  };
})();
