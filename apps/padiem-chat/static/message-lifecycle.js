(() => {
  "use strict";

  const states = Object.freeze({
    STREAMING: "streaming",
    COMPLETED: "completed",
    FAILED: "failed",
    CANCELLED: "cancelled",
    TIMED_OUT: "timed_out",
    WAITING_APPROVAL: "waiting_for_approval",
  });

  // The runtime status chip has one owner. The caller writes the visible
  // text; this API owns the chip state (data-runtime-state) and its
  // visibility, so a completed answer releases the "answer preparing" chip
  // and a real status (a Claw P01 stage, a failure) is never removed.
  const RUNTIME_LABEL_STATE = Object.freeze({ PREPARING: "preparing", STATUS: "status" });

  function runtimeLabelMarker(article) {
    return article && article.querySelector ? article.querySelector("[data-runtime-label]") : null;
  }

  // #5559: the status card is the single status surface of a turn, so the
  // small badge in the answer meta row does not show a second copy of the
  // same status. The badge element and its text stay (the transition still
  // runs through it); only its visibility follows the card.
  function statusCardElement(article) {
    return article && article.querySelector ? article.querySelector('[data-orchestration-ui="kit"]') : null;
  }

  // #5453: the status chip carries the sweep while the turn is really
  // running. The chip's own text always names the real state, so the movement
  // only says "still going" - it never pretends to be a progress bar. A
  // finished, failed, cancelled or timed-out turn has no sweep, and neither
  // has a chip that was released.
  function syncActivitySweep(article) {
    const marker = runtimeLabelMarker(article);
    if (!marker) return;
    const live = article.dataset.lifecycle === states.STREAMING && !marker.hidden;
    marker.classList?.toggle?.("padiem-activity-sweep", live);
  }

  // Applies the chip state. An empty text releases the chip completely: the
  // text is cleared, the chip is hidden and the locale binding is dropped so
  // a language change cannot refill a released chip.
  function applyRuntimeLabel(article, text, state) {
    const marker = runtimeLabelMarker(article);
    if (!marker) return;
    if (typeof text === "string") {
      const value = text.trim();
      if (!value) {
        marker.textContent = "";
        marker.hidden = true;
        marker.removeAttribute("data-locale-key");
        delete marker.dataset.runtimeState;
        syncActivitySweep(article);
        return;
      }
      marker.textContent = value;
    }
    marker.hidden = Boolean(statusCardElement(article));
    if (state) marker.dataset.runtimeState = state;
    syncActivitySweep(article);
  }

  // A finished answer releases the preparing chip. A chip that already
  // carries a real status stays exactly as it is.
  function releasePreparingRuntimeLabel(article) {
    const marker = runtimeLabelMarker(article);
    if (!marker) return;
    if (marker.dataset.runtimeState !== RUNTIME_LABEL_STATE.PREPARING) return;
    applyRuntimeLabel(article, "", RUNTIME_LABEL_STATE.STATUS);
  }

  // #5559: one status surface for Chat and Claw.
  //
  // The card is the single status display of a turn. Its header is the
  // clickable status label, and its body carries the real steps of the turn,
  // the tools that ran, the evidence and the terminal outcome. Nothing here
  // invents a stage: a label exists only when the matching real event
  // happened or the real lifecycle state says so.
  const taskStatusCatalog = Object.freeze({
    preparing: Object.freeze({ state: "active", ko: "답변 준비 중", en: "Preparing answer" }),
    generating: Object.freeze({ state: "active", ko: "답변 생성 중", en: "Generating answer" }),
    searching: Object.freeze({ state: "active", ko: "웹 검색 중", en: "Searching the web" }),
    tool: Object.freeze({ state: "active", ko: "도구 작업 중", en: "Tool in progress" }),
    approval: Object.freeze({ state: "paused", ko: "확인 대기 중", en: "Waiting for confirmation" }),
  });

  // The real steps of a turn. Each one is recorded only when it actually
  // happened, so the card can never show a step that did not occur.
  const taskEventCatalog = Object.freeze({
    request_sent: Object.freeze({ ko: "요청을 전달했어요.", en: "Your request was sent." }),
    answer_started: Object.freeze({ ko: "답변을 만들기 시작했어요.", en: "Started building the answer." }),
    web_search: Object.freeze({ ko: "웹 검색을 사용했어요.", en: "Used web search." }),
    deep_research: Object.freeze({ ko: "심층 리서치를 사용했어요.", en: "Used deep research." }),
    evidence: Object.freeze({ ko: "출처와 근거를 확인했어요.", en: "Checked the sources and evidence." }),
  });

  function taskEvents(article) {
    const raw = article && article.dataset ? article.dataset.taskEvents : "";
    if (!raw) return [];
    try {
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter((key) => typeof key === "string" && taskEventCatalog[key]);
    } catch (_) {
      return [];
    }
  }

  // The real live status of this turn. The Claw lane already has a recorded
  // stage; the plain lane uses its own real facts.
  function taskStatusFor(article, presentation) {
    const lifecycle = article && article.dataset ? article.dataset.lifecycle : null;
    if (lifecycle === states.WAITING_APPROVAL) return labeledStatus(taskStatusCatalog.approval);
    const hint = article && article.dataset ? article.dataset.taskHint : "";
    if (hint && taskStatusCatalog[hint]) return labeledStatus(taskStatusCatalog[hint]);
    if (presentation && presentation.latest && presentation.latest.state === "active") return null;
    if (lifecycle === states.STREAMING) {
      return labeledStatus(article.dataset.answerStarted === "true"
        ? taskStatusCatalog.generating
        : taskStatusCatalog.preparing);
    }
    return null;
  }

  function labeledStatus(item) {
    if (!item) return null;
    return Object.freeze({ state: item.state, label: text(item.ko, item.en) });
  }

  function taskStages(article) {
    return taskEvents(article).map((key, index) => {
      const item = taskEventCatalog[key];
      return Object.freeze({
        group: "agent",
        state: "ready",
        label: text(item.ko, item.en),
        sequence: index + 1,
      });
    });
  }

  function recordTaskEvent(article, key) {
    if (!article || !taskEventCatalog[key]) return;
    const events = taskEvents(article);
    if (!events.includes(key)) events.push(key);
    article.dataset.taskEvents = JSON.stringify(events);
    refreshTaskStatus(article);
  }

  function setTaskHint(article, key) {
    if (!article) return;
    const next = key && taskStatusCatalog[key] ? key : "";
    if ((article.dataset.taskHint || "") === next) return;
    article.dataset.taskHint = next;
    refreshTaskStatus(article);
  }

  function refreshTaskStatus(article) {
    if (!article || typeof article.querySelector !== "function") return;
    if (!statusCardElement(article)) return;
    const presentation = presentationModel(null, article.dataset.lifecycle || null, false);
    renderTaskCard(article, {
      stages: taskStages(article),
      status: taskStatusFor(article, presentation),
      evidenceAvailable: article.dataset.taskEvidence === "true",
      approval: null,
      terminal: terminalFor(article),
      preview: false,
      live: false,
    }, {});
  }

  function terminalFor(article) {
    const lifecycle = article && article.dataset ? article.dataset.lifecycle : null;
    if (!lifecycle || !terminalCatalog[lifecycle]) return null;
    const item = terminalCatalog[lifecycle];
    return Object.freeze({ key: lifecycle, state: item.state, label: text(item.ko, item.en) });
  }

  window.PadiemChatLifecycle = Object.freeze({
    states,
    runtimeLabelStates: RUNTIME_LABEL_STATE,
    isCompleted(article) {
      return Boolean(article && article.dataset.lifecycle === states.COMPLETED);
    },
    set(article, state) {
      if (!article || !Object.values(states).includes(state)) return;
      article.dataset.lifecycle = state;
      syncActivitySweep(article);
      article.dispatchEvent(new CustomEvent("padiem:message-lifecycle", {
        bubbles: true,
        detail: { state },
      }));
    },
    applyRuntimeLabel,
    releasePreparingRuntimeLabel,
    // #5559: the one status surface. A turn records its real steps and the
    // card renders them; nothing else shows a second copy of the status.
    renderTaskStatus,
    recordTaskEvent,
    setTaskHint,
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
  // Chat/Claw separation: the bounded orchestration lane is the Chat lane (/api/chat). Its
  // turns and its conversation id belong to the Chat product, so a resumed
  // Chat run never writes into the Claw conversation.
  const CHAT_PRODUCT = "chat";
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
    if (!article || typeof article.querySelectorAll !== "function") return;
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

  // #5559: the one card renderer. Chat and Claw use this same component, so
  // the status label, the steps, the evidence and the outcome look and behave
  // the same in both products.
  function renderTaskCard(article, view, handlers = {}) {
    if (!article || typeof article.querySelector !== "function") return null;
    ensureCapabilityStyles();
    // #5221: the work card is a disclosure, so the reader keeps the answer
    // primary and opens the real stages only when they want them. The choice
    // survives a re-render, so a live stage update never closes the card the
    // reader opened.
    const previousDisclosure = article.querySelector(".capability-kit-disclosure");
    const wasOpen = previousDisclosure ? previousDisclosure.open : null;
    removeExisting(article);

    const body = article.querySelector(".assistant-body") || article;
    const content = article.querySelector(".assistant-content");
    const section = document.createElement("section");
    section.className = "capability-kit";
    section.dataset.orchestrationUi = "kit";
    section.dataset.capabilityPresentation = "true";
    section.dataset.preview = view.preview ? "synthetic" : "live-contract";
    section.setAttribute("aria-label", text("AI 작업 진행 상태", "AI task status"));

    const disclosure = document.createElement("details");
    disclosure.className = "capability-kit-disclosure";
    // An approval needs the reader, and the synthetic preview is a UI
    // verification surface: both stay open. Every other turn starts closed
    // and keeps the reader's own choice.
    if (wasOpen === null) disclosure.open = Boolean(view.approval) || view.preview;
    else disclosure.open = wasOpen;

    const header = document.createElement("summary");
    header.className = "capability-kit-header";
    const heading = document.createElement("strong");
    heading.textContent = text("AI 작업 상태", "AI task status");
    const status = document.createElement("span");
    status.className = "capability-current";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    status.textContent = view.statusLabel || "";
    // #5453: the sweep only rides a stage that is really still running.
    if (view.live) status.classList.add("padiem-activity-sweep");
    header.append(heading, status);

    if (view.preview) {
      const badge = document.createElement("span");
      badge.className = "capability-preview-badge";
      badge.textContent = text("합성 미리보기 · 실제 실행 아님", "Synthetic preview · not a live run");
      header.appendChild(badge);
    }

    const caret = document.createElement("span");
    caret.className = "capability-kit-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = "›";
    header.appendChild(caret);

    disclosure.appendChild(header);

    const stageList = document.createElement("ol");
    stageList.className = "capability-stage-list";
    stageList.setAttribute("aria-label", text("작업 단계", "Task stages"));
    for (const stage of view.stages) {
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
    disclosure.appendChild(stageList);

    if (view.evidenceAvailable) {
      const evidence = document.createElement("div");
      evidence.className = "capability-evidence";
      evidence.dataset.capabilityGroup = "evidence";
      evidence.textContent = text("출처와 근거를 사용할 수 있습니다.", "Sources and evidence are available.");
      disclosure.appendChild(evidence);
    }

    section.appendChild(disclosure);

    renderApprovalCard(section, view, handlers);

    const terminal = document.createElement("div");
    terminal.className = "capability-terminal";
    terminal.dataset.capabilityTerminal = "true";
    terminal.hidden = true;
    section.appendChild(terminal);

    if (view.preview) {
      const truth = document.createElement("p");
      truth.className = "capability-preview-truth";
      truth.textContent = text(
        "이 화면은 UI 검증용 결정적 합성 상태입니다. 실제 Agent·Tool·Memory 실행이나 승인 권한을 나타내지 않습니다.",
        "This is a deterministic synthetic UI state. It does not represent a live Agent, Tool, Memory run, or approval authority."
      );
      section.appendChild(truth);
    }

    body.insertBefore(section, content || null);
    // #5559: the card is the single status surface, so the meta-row badge
    // does not show a second copy of the same status.
    const marker = runtimeLabelMarker(article);
    if (marker) marker.hidden = true;
    return section;
  }

  // #5559: a plain Chat turn has no orchestration events, but it still has a
  // real status and real steps. The same card renders them.
  function renderTaskStatus(article, handlers = {}) {
    if (!article || typeof article.querySelector !== "function") return null;
    if (article.dataset.capabilityPreview === "synthetic") return null;
    const status = taskStatusFor(article, null);
    renderTaskCard(article, {
      stages: taskStages(article),
      status,
      statusLabel: status ? status.label : "",
      evidenceAvailable: article.dataset.taskEvidence === "true",
      approval: null,
      terminal: terminalFor(article),
      preview: false,
      live: Boolean(status) && status.state === "active",
    }, handlers);
    bindLifecyclePresentation(article, null);
    syncTerminalPresentation(article, article.dataset.lifecycle || null, null);
    return article;
  }

  function renderCapabilityKit(article, model, handlers = {}) {
    if (!article || typeof article.querySelector !== "function") return model;
    if (!model.valid) {
      renderTaskStatus(article, handlers);
      return model;
    }
    const preview = article.dataset.capabilityPreview === "synthetic";
    const presentation = presentationModel(model, article.dataset.lifecycle || null, preview);
    renderTaskCard(article, {
      stages: presentation.stages,
      status: null,
      statusLabel: presentation.latest ? presentation.latest.label : model.statusText,
      evidenceAvailable: presentation.evidenceAvailable,
      approval: presentation.approval,
      terminal: presentation.terminal,
      preview,
      live: Boolean(presentation.latest) && presentation.latest.state === "active"
        && !presentation.terminal,
    }, handlers);
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

  // Shared Chat/Claw follow authority: a completed async result or an
  // approval pause must not pull a user who is reading earlier content back
  // to the bottom. When no follow controller exists (non-glass surface), the
  // historical reveal behavior is preserved.
  function revealArticleIfFollowing(article) {
    if (!article) return;
    const motion = window.__padiemConversationMotion;
    if (motion && typeof motion.isFollowingLatest === "function" && !motion.isFollowingLatest()) {
      return;
    }
    article.scrollIntoView({ block: "nearest", behavior: "smooth" });
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
    // The brand (Padiem Chat / Padiem Claw) stays in [data-assistant-product].
    // A finished answer releases the preparing chip; a real status stays.
    if (label && label.textContent === "AI 응답") applyRuntimeLabel(article, "", RUNTIME_LABEL_STATE.STATUS);
    else releasePreparingRuntimeLabel(article);
    const conversationState = window.PadiemChatConversationState;
    if (conversationState) {
      conversationState.commitAssistant(requestPayload.messages, data.answer, CHAT_PRODUCT);
      if (typeof data.conversation_id === "string") conversationState.setConversationId(data.conversation_id, CHAT_PRODUCT);
    }
    window.PadiemChatLifecycle.set(article, states.COMPLETED);
    revealArticleIfFollowing(article);
  }

  function renderDecisionTerminal(article, message, state) {
    clearOrchestrationUi(article);
    const content = article.querySelector(".assistant-content");
    content.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.textContent = message;
    content.appendChild(paragraph);
    const label = article.querySelector("[data-runtime-label]");
    if (label) {
      label.textContent = state === "approval_denied" ? "진행하지 않음" : "작업 취소됨";
      applyRuntimeLabel(article, label.textContent, RUNTIME_LABEL_STATE.STATUS);
    }
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
    revealArticleIfFollowing(article);
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
