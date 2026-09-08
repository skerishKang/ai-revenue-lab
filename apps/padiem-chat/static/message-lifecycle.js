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
    tool_failed: "도구 작업 상태를 확인하고 있어요.",
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
    let previousSequence = 0;
    for (const raw of rawEvents) {
      if (!isRecord(raw)) return [];
      if (!kindValues.has(raw.kind)) return [];
      if (!Number.isInteger(raw.sequence) || raw.sequence <= previousSequence) return [];
      if (typeof raw.event_id !== "string" || !safeId.test(raw.event_id)) return [];
      if (typeof raw.run_id !== "string" || !safeId.test(raw.run_id)) return [];
      if (typeof raw.trace_id !== "string" || !safeId.test(raw.trace_id)) return [];
      if (typeof raw.app_id !== "string" || !safeId.test(raw.app_id)) return [];
      previousSequence = raw.sequence;
      events.push(Object.freeze({ kind: raw.kind, sequence: raw.sequence }));
    }
    return events;
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

  function text(ko, en) {
    const language = document.documentElement.lang || "ko";
    return language.toLowerCase().startsWith("en") ? en : ko;
  }

  const capabilityCatalog = Object.freeze({
    run_started: Object.freeze({ group: "agent", state: "active", ko: "AI 작업 시작", en: "AI task started" }),
    context_prepared: Object.freeze({ group: "context", state: "ready", ko: "대화 맥락 준비", en: "Context prepared" }),
    memory_read: Object.freeze({ group: "context", state: "ready", ko: "참고 정보 준비", en: "Reference context prepared" }),
    plan_created: Object.freeze({ group: "agent", state: "active", ko: "응답 계획 정리", en: "Response plan prepared" }),
    skill_resolved: Object.freeze({ group: "agent", state: "active", ko: "필요 기능 준비", en: "Capability prepared" }),
    tool_resolution: Object.freeze({ group: "tool", state: "active", ko: "도구 확인 중", en: "Checking tool availability" }),
    tool_started: Object.freeze({ group: "tool", state: "active", ko: "도구 작업 중", en: "Tool in progress" }),
    tool_completed: Object.freeze({ group: "tool", state: "success", ko: "도구 작업 완료", en: "Tool completed" }),
    tool_failed: Object.freeze({ group: "tool", state: "failed", ko: "도구 작업 확인 필요", en: "Tool needs attention" }),
    evidence_attached: Object.freeze({ group: "evidence", state: "ready", ko: "근거 준비", en: "Evidence available" }),
    verification_completed: Object.freeze({ group: "evidence", state: "success", ko: "근거 확인 완료", en: "Evidence verified" }),
    approval_paused: Object.freeze({ group: "approval", state: "paused", ko: "사용자 확인 대기", en: "Waiting for confirmation" }),
    run_resumed: Object.freeze({ group: "approval", state: "success", ko: "확인 완료 · 작업 재개", en: "Confirmed · work resumed" }),
    recovery_started: Object.freeze({ group: "agent", state: "active", ko: "안전 복구 중", en: "Safe recovery in progress" }),
    recovery_decided: Object.freeze({ group: "agent", state: "ready", ko: "복구 경로 확인", en: "Recovery path selected" }),
    retry_started: Object.freeze({ group: "agent", state: "active", ko: "다시 시도 중", en: "Retry in progress" }),
    retry_completed: Object.freeze({ group: "agent", state: "success", ko: "다시 시도 완료", en: "Retry completed" }),
    run_cancelled: Object.freeze({ group: "terminal", state: "cancelled", ko: "작업 취소", en: "Task cancelled" }),
    run_failed: Object.freeze({ group: "terminal", state: "failed", ko: "작업 실패", en: "Task failed" }),
    run_completed: Object.freeze({ group: "terminal", state: "success", ko: "작업 완료", en: "Task completed" }),
  });

  const terminalCatalog = Object.freeze({
    completed: Object.freeze({ state: "success", ko: "작업을 완료했습니다.", en: "Task completed." }),
    failed: Object.freeze({ state: "failed", ko: "작업을 완료하지 못했습니다.", en: "Task could not be completed." }),
    cancelled: Object.freeze({ state: "cancelled", ko: "작업이 취소되었습니다.", en: "Task cancelled." }),
    timed_out: Object.freeze({ state: "timed_out", ko: "응답 시간이 지나 작업을 마치지 못했습니다.", en: "The task timed out before completion." }),
  });

  function presentationModel(model, lifecycleState = null, preview = false) {
    if (!model || model.valid !== true || !Array.isArray(model.events)) {
      return Object.freeze({ valid: false, stages: [], terminal: null, evidenceAvailable: false, approval: null, preview: Boolean(preview) });
    }
    const latestByGroup = new Map();
    for (const event of model.events) {
      const item = capabilityCatalog[event.kind];
      if (!item) continue;
      latestByGroup.set(item.group, Object.freeze({
        group: item.group,
        state: item.state,
        label: text(item.ko, item.en),
        sequence: event.sequence,
      }));
    }
    const stages = Array.from(latestByGroup.values()).sort((left, right) => left.sequence - right.sequence);
    const terminalKey = Object.prototype.hasOwnProperty.call(terminalCatalog, lifecycleState)
      ? lifecycleState
      : model.terminal;
    const terminal = terminalKey && terminalCatalog[terminalKey]
      ? Object.freeze({ key: terminalKey, state: terminalCatalog[terminalKey].state, label: text(terminalCatalog[terminalKey].ko, terminalCatalog[terminalKey].en) })
      : null;
    return Object.freeze({
      valid: true,
      stages,
      latest: stages.length ? stages[stages.length - 1] : null,
      terminal,
      evidenceAvailable: model.evidenceAvailable === true,
      approval: model.approval,
      preview: Boolean(preview),
    });
  }

  function ensureCapabilityStyles() {
    if (document.querySelector("link[data-capability-presentation-styles]")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "./capability-presentation.css";
    link.dataset.capabilityPresentationStyles = "true";
    document.head.appendChild(link);
  }

  function removeExisting(article) {
    article.querySelectorAll("[data-orchestration-ui]").forEach((node) => node.remove());
  }

  function syncTerminalPresentation(article, state, fallbackTerminal = null) {
    const node = article && article.querySelector ? article.querySelector("[data-capability-terminal]") : null;
    if (!node) return;
    const key = Object.prototype.hasOwnProperty.call(terminalCatalog, state) ? state : fallbackTerminal;
    const item = key && terminalCatalog[key];
    if (!item) {
      node.hidden = true;
      node.removeAttribute("data-state");
      return;
    }
    node.hidden = false;
    node.dataset.state = item.state;
    node.textContent = text(item.ko, item.en);
  }

  function bindLifecyclePresentation(article, fallbackTerminal) {
    if (!article || article.dataset.capabilityLifecycleBound === "true") return;
    article.dataset.capabilityLifecycleBound = "true";
    article.addEventListener("padiem:message-lifecycle", (event) => {
      const state = event && event.detail ? event.detail.state : null;
      syncTerminalPresentation(article, state, fallbackTerminal);
    });
  }

  function renderApprovalCard(section, model, handlers) {
    if (!model.approval) return;
    const card = document.createElement("div");
    card.className = "capability-approval";
    card.dataset.capabilityGroup = "approval";
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", text("작업 계속 확인", "Continue task confirmation"));

    const heading = document.createElement("strong");
    heading.textContent = text("확인이 필요합니다.", "Confirmation required.");
    const copy = document.createElement("p");
    copy.textContent = model.approval.requirement === "external_authorization"
      ? text("외부 권한 확인이 필요한 작업입니다. Padiem Chat은 권한을 새로 만들거나 넓히지 않습니다.", "This step requires external authorization. Padiem Chat does not create or widen permissions.")
      : text("도구 작업을 계속하기 전에 사용자의 확인이 필요합니다.", "Your confirmation is required before the tool work continues.");
    const expiry = document.createElement("time");
    expiry.dateTime = model.approval.expiresAt;
    expiry.textContent = text("확인 가능 시간이 제한되어 있습니다.", "This confirmation is available for a limited time.");

    const actions = document.createElement("div");
    actions.className = "capability-actions";
    const approve = document.createElement("button");
    approve.type = "button";
    approve.className = "capability-action capability-action-primary";
    approve.textContent = text("계속", "Continue");
    const deny = document.createElement("button");
    deny.type = "button";
    deny.className = "capability-action";
    deny.textContent = text("거부", "Deny");
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "capability-action";
    cancel.textContent = text("취소", "Cancel");

    const decisionHandler = typeof handlers.onApprovalIntent === "function" ? handlers.onApprovalIntent : null;
    const cancelHandler = typeof handlers.onCancelIntent === "function" ? handlers.onCancelIntent : null;
    [approve, deny].forEach((button) => {
      button.disabled = !decisionHandler || model.preview;
      button.setAttribute("aria-disabled", button.disabled ? "true" : "false");
    });
    cancel.disabled = !cancelHandler || model.preview;
    cancel.setAttribute("aria-disabled", cancel.disabled ? "true" : "false");

    if (decisionHandler && !model.preview) {
      approve.addEventListener("click", () => decisionHandler("approved"));
      deny.addEventListener("click", () => decisionHandler("denied"));
    }
    if (cancelHandler && !model.preview) cancel.addEventListener("click", cancelHandler);

    actions.append(approve, deny, cancel);
    card.append(heading, copy, expiry, actions);
    section.appendChild(card);
  }

  function renderCapabilityKit(article, model, handlers = {}) {
    if (!article || typeof article.querySelector !== "function") return model;
    removeExisting(article);
    if (!model.valid) return model;
    ensureCapabilityStyles();

    const preview = article.dataset.capabilityPreview === "synthetic";
    const presentation = presentationModel(model, article.dataset.lifecycle || null, preview);
    const body = article.querySelector(".assistant-body") || article;
    const content = article.querySelector(".assistant-content");
    const section = document.createElement("section");
    section.className = "capability-kit";
    section.dataset.orchestrationUi = "kit";
    section.dataset.capabilityPresentation = "true";
    section.dataset.preview = preview ? "synthetic" : "live-contract";
    section.setAttribute("aria-label", text("AI 작업 진행 상태", "AI task status"));

    const header = document.createElement("div");
    header.className = "capability-kit-header";
    const heading = document.createElement("strong");
    heading.textContent = text("AI 작업 상태", "AI task status");
    const status = document.createElement("span");
    status.className = "capability-current";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = presentation.latest ? presentation.latest.label : model.statusText;
    header.append(heading, status);

    if (preview) {
      const badge = document.createElement("span");
      badge.className = "capability-preview-badge";
      badge.textContent = text("합성 미리보기 · 실제 실행 아님", "Synthetic preview · not a live run");
      header.appendChild(badge);
    }
    section.appendChild(header);

    const stageList = document.createElement("ol");
    stageList.className = "capability-stage-list";
    stageList.setAttribute("aria-label", text("작업 단계", "Task stages"));
    for (const stage of presentation.stages) {
      const row = document.createElement("li");
      row.className = "capability-stage";
      row.dataset.capabilityGroup = stage.group;
      row.dataset.state = stage.state;
      const marker = document.createElement("span");
      marker.className = "capability-stage-marker";
      marker.setAttribute("aria-hidden", "true");
      marker.textContent = "•";
      const label = document.createElement("span");
      label.textContent = stage.label;
      row.append(marker, label);
      stageList.appendChild(row);
    }
    section.appendChild(stageList);

    if (presentation.evidenceAvailable) {
      const evidence = document.createElement("div");
      evidence.className = "capability-evidence";
      evidence.dataset.capabilityGroup = "evidence";
      evidence.textContent = text("출처와 근거를 사용할 수 있습니다.", "Sources and evidence are available.");
      section.appendChild(evidence);
    }

    renderApprovalCard(section, presentation, handlers);

    const terminal = document.createElement("div");
    terminal.className = "capability-terminal";
    terminal.dataset.capabilityTerminal = "true";
    terminal.hidden = true;
    section.appendChild(terminal);

    if (preview) {
      const truth = document.createElement("p");
      truth.className = "capability-preview-truth";
      truth.textContent = text(
        "이 화면은 UI 검증용 결정적 합성 상태입니다. 실제 Agent·Tool·Memory 실행이나 승인 권한을 나타내지 않습니다.",
        "This is a deterministic synthetic UI state. It does not represent a live Agent, Tool, Memory run, or approval authority."
      );
      section.appendChild(truth);
    }

    body.insertBefore(section, content || null);
    bindLifecyclePresentation(article, model.terminal);
    syncTerminalPresentation(article, article.dataset.lifecycle || null, model.terminal);
    return model;
  }

  const capabilityPresentation = Object.freeze({
    catalog: capabilityCatalog,
    terminalCatalog,
    presentationModel,
    render: renderCapabilityKit,
  });
  window.PadiemChatCapabilityPresentation = capabilityPresentation;

  function render(article, orchestration, handlers = {}) {
    const model = viewModel(orchestration);
    if (!article || typeof article.querySelector !== "function") return model;
    return capabilityPresentation.render(article, model, {
      onApprovalIntent: typeof handlers.onApprovalIntent === "function"
        ? (outcome) => handlers.onApprovalIntent(approvalIntent(orchestration, outcome))
        : null,
      onCancelIntent: typeof handlers.onCancelIntent === "function"
        ? () => handlers.onCancelIntent(cancelIntent(orchestration))
        : null,
    });
  }

  const orchestrationUi = Object.freeze({
    kinds: orchestrationKinds,
    normalizedEvents,
    viewModel,
    approvalIntent,
    cancelIntent,
    render,
  });
  window.PadiemChatOrchestrationUI = orchestrationUi;

  function setExtendedLifecycle(article, state) {
    if (!article) return;
    article.dataset.lifecycle = state;
    article.dispatchEvent(new CustomEvent("padiem:message-lifecycle", {
      bubbles: true,
      detail: { state },
    }));
  }

  function currentAssistantArticle() {
    const messageList = document.getElementById("messageList");
    if (!messageList) return null;
    const items = messageList.querySelectorAll(".assistant-message");
    return items.length ? items[items.length - 1] : null;
  }

  function clearOrchestrationUi(article) {
    if (!article) return;
    article.querySelectorAll("[data-orchestration-ui]").forEach((node) => node.remove());
  }

  function applyCompletedOrchestration(article, requestPayload, data) {
    if (!article || !data || typeof data.answer !== "string" || !data.answer) {
      throw new Error("AI 작업 완료 응답을 확인할 수 없습니다.");
    }
    if (data.orchestration) orchestrationUi.render(article, data.orchestration, {});
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.textContent = data.answer;
    content.appendChild(paragraph);
    const label = article.querySelector("[data-runtime-label]");
    if (label) label.textContent = "AI 응답";
    const conversationState = window.PadiemChatConversationState;
    if (conversationState) {
      conversationState.commitAssistant(requestPayload.messages, data.answer);
      if (typeof data.conversation_id === "string") conversationState.setConversationId(data.conversation_id);
    }
    window.PadiemChatLifecycle.set(article, states.COMPLETED);
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function renderDecisionTerminal(article, message, state) {
    clearOrchestrationUi(article);
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.textContent = message;
    content.appendChild(paragraph);
    const label = article.querySelector("[data-runtime-label]");
    if (label) label.textContent = state === "approval_denied" ? "진행하지 않음" : "작업 취소됨";
    if (state === "orchestration_cancelled") {
      window.PadiemChatLifecycle.set(article, states.CANCELLED);
    } else {
      setExtendedLifecycle(article, state);
    }
  }

  function renderApprovalError(article, orchestration, requestPayload, error) {
    renderApprovalPause(article, orchestration, requestPayload);
    const content = article.querySelector(".assistant-content");
    const note = document.createElement("p");
    note.className = "reference-note";
    note.textContent = error instanceof Error ? error.message : "확인 요청을 처리하지 못했습니다.";
    content.appendChild(note);
  }

  function renderApprovalPause(article, orchestration, requestPayload) {
    const transport = window.PadiemChatTransport;
    if (!article || !transport) throw new Error("확인 화면을 표시할 수 없습니다.");
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const label = article.querySelector("[data-runtime-label]");
    if (label) label.textContent = "확인 대기 중";

    const handlers = {
      onApprovalIntent: async (intent) => {
        if (!intent) return;
        orchestrationUi.render(article, orchestration, {});
        try {
          const data = await transport.resumeOrchestration(intent);
          if (data.decision_status === "denied") {
            renderDecisionTerminal(article, "요청을 진행하지 않았습니다.", "approval_denied");
            return;
          }
          if (data.orchestration && data.orchestration.approval_pause) {
            renderApprovalPause(article, data.orchestration, requestPayload);
            return;
          }
          applyCompletedOrchestration(article, requestPayload, data);
        } catch (error) {
          renderApprovalError(article, orchestration, requestPayload, error);
        }
      },
      onCancelIntent: async (intent) => {
        if (!intent) return;
        orchestrationUi.render(article, orchestration, {});
        try {
          await transport.cancelOrchestration(intent);
          renderDecisionTerminal(article, "작업을 취소했습니다.", "orchestration_cancelled");
        } catch (error) {
          renderApprovalError(article, orchestration, requestPayload, error);
        }
      },
    };
    orchestrationUi.render(article, orchestration, handlers);
    setExtendedLifecycle(article, "approval_paused");
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function bindOrchestrationController() {
    const transport = window.PadiemChatTransport;
    if (!transport || typeof transport.setOrchestrationPauseHandler !== "function") return false;
    transport.setOrchestrationPauseHandler(({ orchestration, requestPayload }) => {
      const article = currentAssistantArticle();
      renderApprovalPause(article, orchestration, requestPayload);
    });
    return true;
  }

  window.PadiemChatOrchestrationController = Object.freeze({
    bind: bindOrchestrationController,
  });
  bindOrchestrationController();

  function syntheticOrchestration(kinds, approvalRequirement = null) {
    const events = kinds.map((kind, index) => Object.freeze({
      event_id: `preview_evt_${index + 1}`,
      run_id: "preview_run_1",
      trace_id: "preview_trace_1",
      app_id: "padiem-chat-preview",
      kind,
      sequence: index + 1,
    }));
    const result = { events };
    if (approvalRequirement) {
      result.approval_pause = {
        status: "paused",
        continuation_id: "preview_pause_1",
        requirement: approvalRequirement,
        expires_at: "2099-01-01T00:00:00Z",
      };
      result.continuation_ref = "cont_SYNTHETIC_PREVIEW_0001";
    }
    return result;
  }

  const previewFixtures = Object.freeze([
    Object.freeze({ id: "agent", titleKo: "Agent 진행", titleEn: "Agent progress", kinds: ["run_started", "plan_created", "skill_resolved"] }),
    Object.freeze({ id: "memory", titleKo: "Memory / Context", titleEn: "Memory / Context", kinds: ["run_started", "context_prepared", "memory_read"] }),
    Object.freeze({ id: "tool-completed", titleKo: "Tool 완료", titleEn: "Tool completed", kinds: ["run_started", "tool_resolution", "tool_started", "tool_completed"] }),
    Object.freeze({ id: "tool-failed", titleKo: "Tool 실패", titleEn: "Tool failed", kinds: ["run_started", "tool_started", "tool_failed"] }),
    Object.freeze({ id: "approval", titleKo: "Approval 대기", titleEn: "Approval required", kinds: ["run_started", "tool_started", "approval_paused"], approval: "user_confirmation" }),
    Object.freeze({ id: "approval-resumed", titleKo: "Approval 해결 / 재개", titleEn: "Approval resolved / resumed", kinds: ["run_started", "run_resumed", "tool_completed"] }),
    Object.freeze({ id: "evidence", titleKo: "Evidence", titleEn: "Evidence", kinds: ["run_started", "tool_completed", "evidence_attached", "verification_completed"] }),
    Object.freeze({ id: "completed", titleKo: "완료", titleEn: "Completed", kinds: ["run_started", "run_completed"], lifecycle: "completed" }),
    Object.freeze({ id: "failed", titleKo: "실패", titleEn: "Failed", kinds: ["run_started", "run_failed"], lifecycle: "failed" }),
    Object.freeze({ id: "cancelled", titleKo: "취소", titleEn: "Cancelled", kinds: ["run_started", "run_cancelled"], lifecycle: "cancelled" }),
    Object.freeze({ id: "timed-out", titleKo: "시간 초과", titleEn: "Timed out", kinds: ["run_started", "tool_started"], lifecycle: "timed_out" }),
  ]);

  function syntheticPreviewEnabled() {
    try {
      return new URLSearchParams(window.location.search).get("capability-preview") === "synthetic";
    } catch (_) {
      return false;
    }
  }

  function createPreviewArticle(fixture, template) {
    const fragment = template.content.cloneNode(true);
    const article = fragment.querySelector(".assistant-message");
    if (!article) return null;
    article.dataset.capabilityPreview = "synthetic";
    article.dataset.previewFixture = fixture.id;
    if (fixture.lifecycle) article.dataset.lifecycle = fixture.lifecycle;
    const runtimeLabel = article.querySelector("[data-runtime-label]");
    if (runtimeLabel) runtimeLabel.textContent = text("합성 미리보기", "Synthetic preview");
    const content = article.querySelector(".assistant-content");
    if (content) {
      const heading = document.createElement("strong");
      heading.className = "capability-preview-fixture-title";
      heading.textContent = document.documentElement.lang.toLowerCase().startsWith("en") ? fixture.titleEn : fixture.titleKo;
      const copy = document.createElement("p");
      copy.textContent = text("UI 검증용 고정 상태입니다. 실제 실행 결과가 아닙니다.", "Fixed UI verification state. Not a live execution result.");
      content.append(heading, copy);
    }
    orchestrationUi.render(article, syntheticOrchestration(fixture.kinds, fixture.approval || null), {});
    return article;
  }

  function renderSyntheticPreview() {
    if (!syntheticPreviewEnabled()) return false;
    const list = document.getElementById("messageList");
    const empty = document.getElementById("emptyState");
    const template = document.getElementById("assistantMessageTemplate");
    const conversation = document.querySelector(".conversation");
    if (!list || !template || !conversation) return false;

    document.body.dataset.capabilityPreview = "synthetic";
    document.documentElement.dataset.capabilityPreview = "synthetic";
    const shell = document.querySelector(".app-shell");
    if (shell) shell.dataset.state = "chat";
    if (empty) empty.hidden = true;
    list.hidden = false;
    list.replaceChildren();

    let banner = document.getElementById("capabilityPreviewBanner");
    if (!banner) {
      banner = document.createElement("aside");
      banner.id = "capabilityPreviewBanner";
      banner.className = "capability-preview-banner";
      banner.setAttribute("role", "note");
      conversation.insertBefore(banner, list);
    }
    banner.textContent = text(
      "DETERMINISTIC PREVIEW · 합성 상태 · 실제 Agent / Tool / Memory 실행 없음",
      "DETERMINISTIC PREVIEW · synthetic states · no live Agent / Tool / Memory execution"
    );

    for (const fixture of previewFixtures) {
      const article = createPreviewArticle(fixture, template);
      if (article) list.appendChild(article);
    }

    const composer = document.getElementById("composerForm");
    const input = document.getElementById("messageInput");
    const send = document.getElementById("sendButton");
    if (composer) composer.setAttribute("aria-disabled", "true");
    if (input) {
      input.disabled = true;
      input.placeholder = text("합성 미리보기에서는 메시지를 보낼 수 없습니다.", "Messages are disabled in synthetic preview.");
    }
    if (send) send.disabled = true;
    return true;
  }

  window.PadiemChatCapabilityPreview = Object.freeze({
    enabled: syntheticPreviewEnabled,
    fixtures: previewFixtures,
    render: renderSyntheticPreview,
  });

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", renderSyntheticPreview, { once: true });
    } else {
      queueMicrotask(renderSyntheticPreview);
    }
  }
})();
