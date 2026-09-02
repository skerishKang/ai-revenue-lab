(() => {
  "use strict";

  const states = Object.freeze({
    STREAMING: "streaming",
    COMPLETED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
    TIMED_OUT: "timed_out",
  });

  window.PadiemChatLifecycle = Object.freeze({
    states,
    isCompleted(article) {
      return Boolean(article && article.dataset.lifecycle === states.COMPLETED);
    },
    set(article, state) {
      if (!article || !Object.values(states).includes(state)) return;
      article.dataset.lifecycle = state;
      article.dispatchEvent(new CustomEvent("padiem:message-lifecycle", {
        bubbles: true,
        detail: { state },
      }));
    },
  });

  const orchestrationKinds = Object.freeze({
    RUN_STARTED: "run_started",
    CONTEXT_PREPARED: "context_prepared",
    MEMORY_READ: "memory_read",
    PLAN_CREATED: "plan_created",
    SKILL_RESOLVED: "skill_resolved",
    TOOL_RESOLUTION: "tool_resolution",
    TOOL_STARTED: "tool_started",
    TOOL_COMPLETED: "tool_completed",
    TOOL_FAILED: "tool_failed",
    EVIDENCE_ATTACHED: "evidence_attached",
    VERIFICATION_COMPLETED: "verification_completed",
    APPROVAL_PAUSED: "approval_paused",
    RUN_RESUMED: "run_resumed",
    RECOVERY_STARTED: "recovery_started",
    RECOVERY_DECIDED: "recovery_decided",
    RETRY_STARTED: "retry_started",
    RETRY_COMPLETED: "retry_completed",
    RUN_CANCELLED: "run_cancelled",
    RUN_FAILED: "run_failed",
    RUN_COMPLETED: "run_completed",
  });

  const kindValues = new Set(Object.values(orchestrationKinds));
  const safeId = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;
  const publicCopy = Object.freeze({
    run_started: "작업을 시작했어요.",
    context_prepared: "질문에 필요한 맥락을 준비했어요.",
    memory_read: "필요한 참고 정보를 확인했어요.",
    plan_created: "답변 순서를 정리하고 있어요.",
    skill_resolved: "필요한 기능을 준비했어요.",
    tool_resolution: "필요한 도구를 확인하고 있어요.",
    tool_started: "도구를 사용하고 있어요.",
    tool_completed: "도구 작업을 마쳤어요.",
    tool_failed: "도구 작업을 완료하지 못했습니다.",
    evidence_attached: "출처와 근거를 준비했어요.",
    verification_completed: "출처와 결과를 확인했어요.",
    approval_paused: "계속하기 전에 확인이 필요합니다.",
    run_resumed: "확인 후 작업을 이어가고 있어요.",
    recovery_started: "작업을 안전하게 복구하고 있어요.",
    recovery_decided: "복구 방법을 확인했어요.",
    retry_started: "작업을 다시 시도하고 있어요.",
    retry_completed: "다시 시도한 작업을 마쳤어요.",
    run_cancelled: "작업이 취소되었습니다.",
    run_failed: "작업을 완료하지 못했습니다.",
    run_completed: "작업을 완료했어요.",
  });

  function isRecord(value) {
    return Boolean(value && typeof value === "object" && !Array.isArray(value));
  }

  function normalizedEvents(rawEvents) {
    if (!Array.isArray(rawEvents)) return [];
    const events = [];
    const sequences = new Set();
    for (const raw of rawEvents) {
      if (!isRecord(raw)) return [];
      if (!kindValues.has(raw.kind)) return [];
      if (!Number.isInteger(raw.sequence) || raw.sequence < 1 || sequences.has(raw.sequence)) return [];
      if (typeof raw.event_id !== "string" || !safeId.test(raw.event_id)) return [];
      if (typeof raw.run_id !== "string" || !safeId.test(raw.run_id)) return [];
      if (typeof raw.trace_id !== "string" || !safeId.test(raw.trace_id)) return [];
      if (typeof raw.app_id !== "string" || !safeId.test(raw.app_id)) return [];
      sequences.add(raw.sequence);
      events.push(Object.freeze({ kind: raw.kind, sequence: raw.sequence }));
    }
    return events.sort((a, b) => a.sequence - b.sequence);
  }

  function approvalView(orchestration, events) {
    if (!events.some((event) => event.kind === orchestrationKinds.APPROVAL_PAUSED)) return null;
    const pause = orchestration && orchestration.approval_pause;
    const continuationRef = orchestration && orchestration.continuation_ref;
    if (!isRecord(pause) || typeof continuationRef !== "string" || !/^cont_[A-Za-z0-9_-]{8,}$/.test(continuationRef)) return null;
    if (pause.status !== "paused") return null;
    if (typeof pause.continuation_id !== "string" || !safeId.test(pause.continuation_id)) return null;
    if (!["user_confirmation", "external_authorization"].includes(pause.requirement)) return null;
    if (typeof pause.expires_at !== "string" || !pause.expires_at.trim()) return null;
    return Object.freeze({
      continuationRef,
      pauseId: pause.continuation_id,
      requirement: pause.requirement,
      expiresAt: pause.expires_at,
    });
  }

  function viewModel(orchestration) {
    if (!isRecord(orchestration)) return Object.freeze({ valid: false, events: [], statusText: "", evidenceAvailable: false, terminal: null, approval: null });
    const events = normalizedEvents(orchestration.events);
    if (!events.length) return Object.freeze({ valid: false, events: [], statusText: "", evidenceAvailable: false, terminal: null, approval: null });
    const latest = events[events.length - 1];
    let terminal = null;
    if (latest.kind === orchestrationKinds.RUN_COMPLETED) terminal = "completed";
    if (latest.kind === orchestrationKinds.RUN_FAILED) terminal = "failed";
    if (latest.kind === orchestrationKinds.RUN_CANCELLED) terminal = "cancelled";
    return Object.freeze({
      valid: true,
      events,
      statusText: publicCopy[latest.kind] || "작업을 진행하고 있어요.",
      evidenceAvailable: events.some((event) => event.kind === orchestrationKinds.EVIDENCE_ATTACHED),
      terminal,
      approval: approvalView(orchestration, events),
    });
  }

  function approvalIntent(orchestration, outcome) {
    const model = viewModel(orchestration);
    if (!model.approval || !["approved", "denied"].includes(outcome)) return null;
    // This is only browser intent. A trusted server/control-plane adapter must
    // authenticate the actor and construct the Engine decision evidence.
    return Object.freeze({
      continuationRef: model.approval.continuationRef,
      pauseId: model.approval.pauseId,
      outcome,
      requiresTrustedDecision: true,
    });
  }

  function cancelIntent(orchestration) {
    const model = viewModel(orchestration);
    if (!model.approval) return null;
    return Object.freeze({ continuationRef: model.approval.continuationRef });
  }

  function removeExisting(article) {
    article.querySelectorAll("[data-orchestration-ui]").forEach((node) => node.remove());
  }

  function render(article, orchestration, handlers = {}) {
    const model = viewModel(orchestration);
    if (!article || typeof article.querySelector !== "function") return model;
    removeExisting(article);
    if (!model.valid) return model;

    const body = article.querySelector(".assistant-body") || article;
    const content = article.querySelector(".assistant-content");
    const progress = document.createElement("div");
    progress.className = "reference-note orchestration-progress";
    progress.dataset.orchestrationUi = "progress";
    progress.setAttribute("role", "status");
    progress.setAttribute("aria-live", "polite");
    progress.textContent = model.statusText;
    body.insertBefore(progress, content || null);

    if (model.evidenceAvailable) {
      const evidence = document.createElement("small");
      evidence.className = "reference-note orchestration-evidence";
      evidence.dataset.orchestrationUi = "evidence";
      evidence.textContent = "출처와 근거를 사용할 수 있습니다.";
      body.insertBefore(evidence, content || null);
    }

    if (!model.approval) return model;

    const card = document.createElement("div");
    card.className = "error-box orchestration-approval";
    card.dataset.orchestrationUi = "approval";
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", "작업 계속 확인");

    const heading = document.createElement("strong");
    heading.textContent = "확인이 필요합니다.";
    const copy = document.createElement("p");
    copy.textContent = model.approval.requirement === "external_authorization"
      ? "외부 권한 확인이 필요한 작업입니다. Padiem Chat은 권한을 새로 만들거나 넓히지 않습니다."
      : "도구 작업을 계속하기 전에 사용자의 확인이 필요합니다.";
    const expiry = document.createElement("time");
    expiry.className = "reference-note";
    expiry.dateTime = model.approval.expiresAt;
    expiry.textContent = "확인 가능 시간이 제한되어 있습니다.";

    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "retry-button";
    approve.textContent = "계속";
    const deny = document.createElement("button");
    deny.type = "button";
    deny.className = "retry-button";
    deny.textContent = "거부";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "retry-button";
    cancel.textContent = "취소";

    const decisionHandler = typeof handlers.onApprovalIntent === "function" ? handlers.onApprovalIntent : null;
    const cancelHandler = typeof handlers.onCancelIntent === "function" ? handlers.onCancelIntent : null;
    [approve, deny].forEach((button) => {
      button.disabled = !decisionHandler;
      button.setAttribute("aria-disabled", decisionHandler ? "false" : "true");
    });
    cancel.disabled = !cancelHandler;
    cancel.setAttribute("aria-disabled", cancelHandler ? "false" : "true");

    if (decisionHandler) {
      approve.addEventListener("click", () => decisionHandler(approvalIntent(orchestration, "approved")));
      deny.addEventListener("click", () => decisionHandler(approvalIntent(orchestration, "denied")));
    }
    if (cancelHandler) cancel.addEventListener("click", () => cancelHandler(cancelIntent(orchestration)));

    card.append(heading, copy, expiry, approve, deny, cancel);
    body.insertBefore(card, content || null);
    return model;
  }

  window.PadiemChatOrchestrationUI = Object.freeze({
    kinds: orchestrationKinds,
    normalizedEvents,
    viewModel,
    approvalIntent,
    cancelIntent,
    render,
  });
})();
