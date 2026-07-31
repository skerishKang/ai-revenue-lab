(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ARLGithubLive = api;
  if (root.document) api.autoStart(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const ENDPOINT = "/api/github-status";
  /*  Timeout contract (Issue #345) — mirrors functions/_lib/outbound-deadline.js
   *  TIMEOUT_CONTRACT. The server serves a valid last-good snapshot within
   *  serverStaleRefreshBudgetMs (6000) when upstream is slow; the client deadline
   *  must stay above that budget plus a network margin so a stale snapshot is never
   *  lost to an early abort. The two bundles cannot share a module, so the contract
   *  is fixed here, in outbound-deadline.js, and by regression tests on both sides.
   *
   *  REQUEST_TIMEOUT_MS is enforced per fetch attempt by a dedicated attempt
   *  AbortController + timer inside requestOnce (see below). A hanging fetch is
   *  aborted after REQUEST_TIMEOUT_MS so retry/backoff can proceed; the timeout
   *  aborts ONLY the attempt, never the whole load, so the next attempt still runs. */
  const REQUEST_TIMEOUT_MS = 12000;
  const RETRY_DELAYS_MS = Object.freeze([800, 2400]); // backoff before retry #1 and #2
  const MAX_ATTEMPTS = RETRY_DELAYS_MS.length + 1; // initial request + 2 retries = 3
  const RECOVERY_COOLDOWN_MS = 30000; // skip auto-refresh if a success is this recent
  const RECOVERY_DEDUP_MS = 1000; // collapse simultaneous visibilitychange + focus
  const NON_RETRYABLE_CODES = Object.freeze(new Set([
    "CONFIGURATION_MISSING", "CACHE_CONFIGURATION_MISSING", "INVALID_QUERY", "METHOD_NOT_ALLOWED",
  ]));
  const state = {
    payload: null, loading: false, started: false, observer: null, scheduled: false,
    status: "idle", controller: null, inFlight: null, lastSuccessAt: null, lastRecoveryAt: null, listeners: null,
  };

  const LABELS = {
    ko: {
      synced: "동기화됨", syncPending: "동기화 대기", stale: "오래된 정보", notConnected: "연결 안 됨", unmapped: "미연결",
      issueOpen: "Issue 열림", issueClosed: "Issue 닫힘", draftPr: "PR 초안", openPr: "PR 열림", closedPr: "PR 닫힘", merged: "병합됨",
      checksPass: "검사 통과", checksFail: "검사 실패", checksPending: "검사 중", checksUnavailable: "검사 없음",
      lastSync: "마지막 동기화", repository: "저장소", latestMain: "최신 main SHA", mappedIssue: "연결 Issue",
      mappedPr: "연결 PR", prHead: "PR head SHA", lastActivity: "최근 GitHub 활동", githubStatus: "GitHub 상태", partial: "일부 정보 없음",
      productIssue: "제품 결정 Issue", phaseIssue: "단계 Issue", phasePr: "단계 PR", phaseVerdict: "단계 판정",
      discovery: "발견 방법", conflict: "충돌", unavailable: "사용 불가"
    },
    en: {
      synced: "SYNCED", syncPending: "SYNC PENDING", stale: "STALE", notConnected: "NOT CONNECTED", unmapped: "UNMAPPED",
      issueOpen: "ISSUE OPEN", issueClosed: "ISSUE CLOSED", draftPr: "DRAFT PR", openPr: "OPEN PR", closedPr: "CLOSED PR", merged: "MERGED",
      checksPass: "CHECKS PASS", checksFail: "CHECKS FAIL", checksPending: "CHECKS PENDING", checksUnavailable: "CHECKS UNAVAILABLE",
      lastSync: "LAST SYNC", repository: "REPOSITORY", latestMain: "LATEST MAIN SHA", mappedIssue: "MAPPED ISSUE",
      mappedPr: "MAPPED PR", prHead: "PR HEAD SHA", lastActivity: "LAST GITHUB ACTIVITY", githubStatus: "GITHUB STATUS", partial: "PARTIAL DATA",
      productIssue: "PRODUCT DECISION ISSUE", phaseIssue: "PHASE ISSUE", phasePr: "PHASE PR", phaseVerdict: "PHASE VERDICT",
      discovery: "DISCOVERY", conflict: "CONFLICT", unavailable: "UNAVAILABLE"
    }
  };

  function languageOf(globalObject = globalThis) { return globalObject.document?.documentElement?.lang === "en" ? "en" : "ko"; }
  function labelsFor(language) { return LABELS[language === "en" ? "en" : "ko"]; }
  function escapeHtml(value) {
    return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function safeGitHubUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "https:" && url.hostname === "github.com" ? url.toString() : null;
    } catch { return null; }
  }
  function formatDate(value, language) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat(language === "en" ? "en-US" : "ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(date);
  }
  function liveMapFromPayload(payload) {
    const result = new Map();
    if (!payload?.ok || !Array.isArray(payload.businesses)) return result;
    for (const item of payload.businesses) if (Number.isInteger(item?.number)) result.set(item.number, adaptLiveBusiness(item));
    return result;
  }
  /**
   * SINGLE compatibility adapter between the canonical Phase 2A server schema
   * and the UI-facing live object. The server emits productDecisionIssue,
   * phaseIssues.{ui,ux,backend} and currentPullRequests.{ui,ux,backend};
   * the UI consumes derived issue/pullRequest/checks primaries.
   * Legacy schemaVersion-1 payloads (already carrying issue/pullRequest)
   * pass through unchanged.
   */
  function adaptLiveBusiness(live) {
    if (!live || typeof live !== "object") return live;
    if (!("productDecisionIssue" in live) && !("currentPullRequests" in live)) return live;
    const prs = live.currentPullRequests || {};
    const issues = live.phaseIssues || {};
    const pullRequest = prs.ui || prs.ux || prs.backend || null;
    const issue = live.productDecisionIssue || issues.ui || issues.ux || issues.backend || null;
    const checks = pullRequest?.checks || { state: "unavailable", source: "none", total: 0, completed: 0 };
    return { ...live, issue, pullRequest, checks };
  }
  function mergeLiveByBusinessNumber(staticBusinesses, payload) {
    const map = liveMapFromPayload(payload);
    return (staticBusinesses || []).map((business) => ({ ...business, liveGithub: map.get(business.number) || null }));
  }
  function acceptPayload(currentPayload, nextPayload) {
    if (!nextPayload?.ok || !Array.isArray(nextPayload.businesses)) return currentPayload;
    return nextPayload;
  }
  function checkLabel(checks, labels) {
    const key = { pass: "checksPass", fail: "checksFail", pending: "checksPending", unavailable: "checksUnavailable" }[checks?.state] || "checksUnavailable";
    return labels[key];
  }
  function connectionLabel(live, labels, payload) {
    if (!live) return labels.notConnected;
    if (live.connectionState === "unmapped") return labels.unmapped;
    if (payload?.stale) return labels.stale;
    if (live.connectionState === "partial") return labels.partial;
    return labels.synced;
  }
  function pullRequestLabel(pullRequest, labels) {
    if (!pullRequest) return null;
    if (pullRequest.merged) return labels.merged;
    if (pullRequest.state === "closed") return labels.closedPr;
    if (pullRequest.draft) return labels.draftPr;
    return labels.openPr;
  }
  function primaryFact(live, labels) {
    const pr = live?.pullRequest;
    if (pr) return `${pullRequestLabel(pr, labels)} #${pr.number}`;
    const issue = live?.issue;
    if (issue) return `${issue.state === "open" ? labels.issueOpen : labels.issueClosed} #${issue.number}`;
    return labels.unmapped;
  }
  function liveSummary(live, payload, language) {
    const labels = labelsFor(language);
    return { connection: connectionLabel(live, labels, payload), primary: primaryFact(live, labels), checks: checkLabel(live?.checks, labels), syncedAt: formatDate(payload?.syncedAt, language) };
  }
  function staticStatePreserved(staticBusiness, live) { return { ...staticBusiness, liveGithub: live || null }; }

  function decorateProjectCards(globalObject) {
    const payload = state.payload;
    if (!payload?.ok) return;
    const language = languageOf(globalObject);
    const map = liveMapFromPayload(payload);
    const projects = Array.isArray(globalObject.ARL_PROJECTS) ? globalObject.ARL_PROJECTS : [];
    const projectById = new Map(projects.map((project) => [String(project.id), project]));
    globalObject.document.querySelectorAll(".pd-card[data-project-id]").forEach((card) => {
      const project = projectById.get(String(card.dataset.projectId));
      const target = card.querySelector(".pd-card-github-state");
      if (!target || !Number.isInteger(project?.businessNumber)) return;
      const live = map.get(project.businessNumber);
      if (!live) return;
      const summary = liveSummary(live, payload, language);
      const nextText = `${summary.connection} · ${summary.primary} · ${summary.checks}`;
      if (target.textContent !== nextText) target.textContent = nextText;
      target.dataset.githubLive = "true";
    });
  }
  function decorateBusinessRows(globalObject) {
    const payload = state.payload;
    if (!payload?.ok) return;
    const language = languageOf(globalObject);
    const labels = labelsFor(language);
    const map = liveMapFromPayload(payload);
    globalObject.document.querySelectorAll(".biz-item[data-biz-number]").forEach((row) => {
      const live = map.get(Number(row.dataset.bizNumber));
      const titleGroup = row.querySelector(".biz-title-group");
      if (!live || !titleGroup) return;
      let line = titleGroup.querySelector("[data-github-live-row]");
      if (!line) {
        line = globalObject.document.createElement("span");
        line.className = "biz-korean";
        line.dataset.githubLiveRow = "true";
        titleGroup.appendChild(line);
      }
      const summary = liveSummary(live, payload, language);
      const nextText = `${summary.connection} · ${summary.primary} · ${summary.checks} · ${labels.lastSync} ${summary.syncedAt}`;
      if (line.textContent !== nextText) line.textContent = nextText;
    });
  }
  function sectionHtml(label, value) {
    return `<div class="dialog-section" data-github-live-section><span class="dialog-section-label">${escapeHtml(label)}</span><span class="dialog-section-value">${value}</span></div>`;
  }
  function githubLink(value, text) {
    const url = safeGitHubUrl(value);
    return url ? `<a class="dialog-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)}</a>` : "";
  }
  function issueValue(issue) {
    return issue ? `${escapeHtml(issue.title)} · ${escapeHtml(issue.state)} #${issue.number}` : "—";
  }
  function prValue(pr, labels) {
    return pr ? `${escapeHtml(pr.title)} · ${escapeHtml(pullRequestLabel(pr, labels))} #${pr.number} · ${escapeHtml(checkLabel(pr.checks, labels))}` : "—";
  }
  function discoveryValue(discovery, labels) {
    if (!discovery) return "—";
    if (discovery.status === "conflict") return `${labels.conflict}${discovery.reason ? ` (${escapeHtml(discovery.reason)})` : ""}`;
    if (discovery.status === "unavailable") return labels.unavailable;
    return discovery.method ? `${escapeHtml(discovery.method)}${discovery.truncated ? " · truncated" : ""}` : "—";
  }
  function decorateBusinessDialog(globalObject) {
    const payload = state.payload;
    if (!payload?.ok) return;
    const dialog = globalObject.document.querySelector("#business-dialog");
    const body = globalObject.document.querySelector("#biz-dialog-body");
    if (!dialog?.open || !body) return;
    const number = Number((body.querySelector(".dialog-biznumber")?.textContent || "").replace(/\D/g, ""));
    const live = liveMapFromPayload(payload).get(number);
    if (!live) return;
    const language = languageOf(globalObject);
    const signature = `${number}|${language}|${payload.syncedAt || ""}|${payload.stale ? "1" : "0"}`;
    const existingBlock = body.querySelector("[data-github-live-block]");
    if (existingBlock?.dataset.githubLiveSignature === signature) return;
    body.querySelectorAll("[data-github-live-block]").forEach((node) => node.remove());
    const labels = labelsFor(language);
    const summary = liveSummary(live, payload, language);
    const repository = payload.repository || {};
    const issue = live.issue;
    const pr = live.pullRequest;
    const phaseIssues = live.phaseIssues || {};
    const phasePrs = live.currentPullRequests || {};
    const phaseDiscovery = live.phaseDiscovery || {};
    const canonical = "currentPullRequests" in live;
    const phaseRows = canonical ? ["ui", "ux", "backend"].map((phase) => {
      const phaseIssue = phaseIssues[phase];
      const phasePr = phasePrs[phase];
      if (!phaseIssue && !phasePr && !phaseDiscovery[phase]) return "";
      return sectionHtml(`${labels.phaseIssue} · ${phase.toUpperCase()}`, issueValue(phaseIssue))
        + sectionHtml(`${labels.phasePr} · ${phase.toUpperCase()}`, prValue(phasePr, labels))
        + sectionHtml(`${labels.discovery} · ${phase.toUpperCase()}`, discoveryValue(phaseDiscovery[phase], labels));
    }).join("") : "";
    const block = globalObject.document.createElement("div");
    block.dataset.githubLiveBlock = "true";
    block.dataset.githubLiveSignature = signature;
    block.innerHTML = `
      <hr class="dialog-divider" data-github-live-section>
      ${sectionHtml(labels.githubStatus, `${escapeHtml(summary.connection)} · ${escapeHtml(summary.checks)}`)}
      ${sectionHtml(labels.repository, escapeHtml(live.repository || repository.fullName || "—"))}
      ${sectionHtml(labels.latestMain, `<code>${escapeHtml(repository.latestSha || "—")}</code>`)}
      ${sectionHtml(labels.productIssue, issueValue(live.productDecisionIssue || issue))}
      ${phaseRows}
      ${sectionHtml(labels.mappedIssue, issueValue(issue))}
      ${sectionHtml(labels.mappedPr, prValue(pr, labels))}
      ${sectionHtml(labels.prHead, `<code>${escapeHtml(pr?.headSha || "—")}</code>`)}
      ${sectionHtml(labels.lastActivity, escapeHtml(formatDate(live.activityAt, language)))}
      ${sectionHtml(labels.lastSync, escapeHtml(formatDate(payload.syncedAt, language)))}
      <div class="dialog-links" data-github-live-section>${githubLink(issue?.url, `Issue #${issue?.number || ""}`)}${githubLink(pr?.url, `PR #${pr?.number || ""}`)}${githubLink(repository.url, labels.repository)}</div>`;
    body.appendChild(block);
    const liveFacts = globalObject.window && globalObject.window.ARLLiveFacts;
    if (liveFacts) {
      try { liveFacts.decorateVerdict(payload, body, globalObject); } catch (_) {}
    }
  }
  function decorate(globalObject) {
    decorateProjectCards(globalObject);
    decorateBusinessRows(globalObject);
    decorateBusinessDialog(globalObject);
    // Phase 2A row decoration integration
    var liveFacts = globalObject.window && globalObject.window.ARLLiveFacts;
    if (liveFacts && state.payload) {
      try { liveFacts.decorateDiscovery(state.payload, globalObject); } catch (_) {}
    }
  }
  function scheduleDecorate(globalObject) {
    if (state.scheduled) return;
    state.scheduled = true;
    globalObject.queueMicrotask(() => { state.scheduled = false; decorate(globalObject); });
  }
  const STATUS_LABELS = Object.freeze({
    ko: Object.freeze({ loading: "GitHub 동기화 중…", fresh: "GitHub 최신 동기화됨", stale: "최신 정보가 아닐 수 있음", retrying: "GitHub 재시도 중…", unavailable: "GitHub live 정보를 잠시 불러올 수 없음", retry: "다시 시도" }),
    en: Object.freeze({ loading: "Syncing GitHub…", fresh: "GitHub up to date", stale: "May be out of date", retrying: "Retrying GitHub…", unavailable: "GitHub live data temporarily unavailable", retry: "Retry" }),
  });
  function statusText(status, language) {
    const labels = STATUS_LABELS[language === "en" ? "en" : "ko"];
    return labels[status] || "";
  }
  function nowMs(globalObject) {
    return globalObject.Date && typeof globalObject.Date.now === "function" ? globalObject.Date.now() : Date.now();
  }
  // Classify a completed request. "fatal" errors (contract violations and
  // permanent configuration failures) are never auto-retried; "retryable"
  // errors (network, timeout, 5xx/429, transient upstream codes, malformed body)
  // are. A malformed body is fail-closed: acceptPayload keeps the last-good
  // payload and nothing bad is ever rendered.
  function classify(status, payload) {
    if (status === 400 || status === 405) return { kind: "fatal" };
    if (payload && payload.ok === true) {
      return Array.isArray(payload.businesses) ? { kind: "ok", stale: Boolean(payload.stale) } : { kind: "fatal" };
    }
    const code = payload && payload.error && payload.error.code;
    if (typeof code === "string" && NON_RETRYABLE_CODES.has(code)) return { kind: "fatal" };
    return { kind: "retryable" };
  }
  function sleepBackoff(globalObject, baseMs, signal) {
    const random = globalObject.Math && typeof globalObject.Math.random === "function" ? globalObject.Math.random() : Math.random();
    const ms = baseMs + Math.floor(random * baseMs * 0.2);
    return new Promise((resolve) => {
      if (signal && signal.aborted) { resolve(); return; }
      let timer = null;
      const cleanup = () => { globalObject.clearTimeout(timer); if (signal && signal.removeEventListener) signal.removeEventListener("abort", onAbort); };
      const onAbort = () => { cleanup(); resolve(); };
      timer = globalObject.setTimeout(() => { cleanup(); resolve(); }, ms);
      if (signal && signal.addEventListener) signal.addEventListener("abort", onAbort, { once: true });
    });
  }
  /*  One fetch attempt with its own enforced deadline.
   *
   *  Two cancellation scopes are kept separate:
   *    - loadSignal  — aborts the WHOLE load (manual retry or teardown). When it
   *                    fires we return { kind: "aborted" } and stop retrying.
   *    - attemptController — aborts THIS fetch only when REQUEST_TIMEOUT_MS elapses.
   *                    A timeout returns { kind: "retryable", reason: "timeout" }
   *                    and never touches loadSignal, so the next attempt can run.
   *
   *  A hanging fetch (never settles) is aborted by the attempt timer, so the load
   *  can never wedge forever in "loading" with a permanent in-flight request. The
   *  timeout timer and the loadSignal listener are both removed in every exit path. */
  async function requestOnce(globalObject, loadSignal) {
    if (loadSignal && loadSignal.aborted) return { kind: "aborted" };
    const attemptController = new globalObject.AbortController();
    let timedOut = false;
    let timer = null;
    const abortAttempt = () => { try { attemptController.abort(); } catch { /* ignore */ } };
    const clearAttempt = () => {
      if (timer != null) { globalObject.clearTimeout(timer); timer = null; }
      if (loadSignal && loadSignal.removeEventListener) { try { loadSignal.removeEventListener("abort", abortAttempt); } catch { /* ignore */ } }
    };
    if (loadSignal && loadSignal.addEventListener) loadSignal.addEventListener("abort", abortAttempt, { once: true });
    timer = globalObject.setTimeout(() => { timedOut = true; abortAttempt(); }, REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await globalObject.fetch(ENDPOINT, { method: "GET", credentials: "same-origin", headers: { Accept: "application/json" }, signal: attemptController.signal });
    } catch {
      clearAttempt();
      if (loadSignal && loadSignal.aborted) return { kind: "aborted" };
      return timedOut ? { kind: "retryable", reason: "timeout" } : { kind: "retryable", reason: "network" };
    }
    let payload = null;
    try { payload = await response.json(); } catch { payload = null; }
    clearAttempt();
    if (loadSignal && loadSignal.aborted) return { kind: "aborted" };
    const verdict = classify(response.status, payload);
    if (verdict.kind === "ok") return { kind: "ok", payload, stale: verdict.stale };
    return verdict;
  }
  function statusAnchor(globalObject) {
    const doc = globalObject.document;
    if (!doc || typeof doc.querySelector !== "function") return null;
    let node = doc.querySelector("#github-live-status");
    if (node) return node;
    const view = doc.querySelector("#view-business");
    if (!view || typeof doc.createElement !== "function") return null;
    node = doc.createElement("div");
    node.id = "github-live-status";
    node.className = "github-live-status";
    if (node.setAttribute) { node.setAttribute("role", "status"); node.setAttribute("aria-live", "polite"); }
    if (typeof view.insertBefore === "function") view.insertBefore(node, view.firstChild);
    return node;
  }
  function renderStatus(globalObject) {
    const node = statusAnchor(globalObject);
    if (!node) return;
    const language = languageOf(globalObject);
    const labels = STATUS_LABELS[language === "en" ? "en" : "ko"];
    const status = state.status || "idle";
    node.textContent = "";
    if (node.dataset) node.dataset.status = status;
    if (status === "idle") return;
    if (status === "fresh") { node.textContent = labels.fresh; return; }
    const doc = globalObject.document;
    const line = doc.createElement("span");
    line.className = "github-live-status-text";
    let text = labels[status] || "";
    if (status === "stale" && state.payload && state.payload.syncedAt) {
      text += ` · ${labelsFor(language).lastSync} ${formatDate(state.payload.syncedAt, language)}`;
    }
    line.textContent = text;
    node.appendChild(line);
    if (status === "unavailable") {
      const btn = doc.createElement("button");
      btn.type = "button";
      btn.className = "github-live-status-retry";
      btn.textContent = labels.retry;
      if (btn.setAttribute) btn.setAttribute("aria-label", labels.retry);
      btn.addEventListener("click", () => load(globalObject, { reason: "manual" }));
      node.appendChild(btn);
    }
  }
  function setStatus(globalObject, status) {
    state.status = status;
    renderStatus(globalObject);
  }
  function load(globalObject, options = {}) {
    const reason = options.reason || "startup";
    // Join an in-flight automatic load; only an explicit manual retry restarts.
    if (state.inFlight && reason !== "manual") return state.inFlight;
    if (state.controller) { try { state.controller.abort(); } catch { /* ignore */ } }
    const controller = new globalObject.AbortController();
    state.controller = controller;
    state.loading = true;
    const run = (async () => {
      let attempt = 0;
      while (attempt < MAX_ATTEMPTS) {
        if (controller.signal.aborted) return state.payload;
        setStatus(globalObject, attempt === 0 ? "loading" : "retrying");
        const result = await requestOnce(globalObject, controller.signal);
        if (result.kind === "aborted") return state.payload;
        if (result.kind === "ok") {
          state.payload = acceptPayload(state.payload, result.payload);
          state.lastSuccessAt = nowMs(globalObject);
          setStatus(globalObject, result.stale ? "stale" : "fresh");
          if (state.payload && state.payload.ok) scheduleDecorate(globalObject);
          return state.payload;
        }
        if (result.kind === "fatal") {
          setStatus(globalObject, state.payload && state.payload.ok ? "stale" : "unavailable");
          return state.payload;
        }
        attempt += 1;
        if (attempt >= MAX_ATTEMPTS) break;
        setStatus(globalObject, "retrying");
        await sleepBackoff(globalObject, RETRY_DELAYS_MS[attempt - 1], controller.signal);
      }
      setStatus(globalObject, state.payload && state.payload.ok ? "stale" : "unavailable");
      return state.payload;
    })();
    // Share one promise identity so concurrent callers join the same flight.
    const tracked = run.finally(() => {
      if (state.inFlight === tracked) { state.inFlight = null; state.loading = false; }
      if (state.controller === controller) state.controller = null;
    });
    state.inFlight = tracked;
    return tracked;
  }
  function recover(globalObject) {
    const doc = globalObject.document;
    if (doc && doc.visibilityState && doc.visibilityState !== "visible") return;
    const t = nowMs(globalObject);
    // Collapse simultaneous visibilitychange + focus into one recovery.
    if (state.lastRecoveryAt && t - state.lastRecoveryAt < RECOVERY_DEDUP_MS) return;
    state.lastRecoveryAt = t;
    // Freshness window: skip if a success landed within the cooldown.
    if ((state.status === "fresh" || state.status === "stale") && state.lastSuccessAt != null && t - state.lastSuccessAt < RECOVERY_COOLDOWN_MS) return;
    if (state.inFlight) return;
    load(globalObject, { reason: "recovery" });
  }
  function teardown(globalObject) {
    if (state.observer) { try { state.observer.disconnect(); } catch { /* ignore */ } state.observer = null; }
    if (state.listeners) {
      try { globalObject.document.removeEventListener("visibilitychange", state.listeners.onVisibility); } catch { /* ignore */ }
      try { if (globalObject.window && globalObject.window.removeEventListener) globalObject.window.removeEventListener("focus", state.listeners.onFocus); } catch { /* ignore */ }
      state.listeners = null;
    }
    if (state.controller) { try { state.controller.abort(); } catch { /* ignore */ } state.controller = null; }
    state.inFlight = null;
    state.started = false;
  }
  function autoStart(globalObject) {
    if (state.started) return;
    state.started = true;
    const start = () => {
      state.observer = new globalObject.MutationObserver(() => scheduleDecorate(globalObject));
      state.observer.observe(globalObject.document.body, { childList: true, subtree: true });
      const onVisibility = () => recover(globalObject);
      const onFocus = () => recover(globalObject);
      globalObject.document.addEventListener("visibilitychange", onVisibility);
      if (globalObject.window && globalObject.window.addEventListener) globalObject.window.addEventListener("focus", onFocus);
      state.listeners = { onVisibility, onFocus };
      load(globalObject, { reason: "startup" });
    };
    if (globalObject.document.readyState === "loading") globalObject.document.addEventListener("DOMContentLoaded", start, { once: true });
    else start();
  }

  return {
    ENDPOINT, REQUEST_TIMEOUT_MS, RETRY_DELAYS_MS, MAX_ATTEMPTS, RECOVERY_COOLDOWN_MS, RECOVERY_DEDUP_MS,
    NON_RETRYABLE_CODES, STATUS_LABELS, labelsFor, liveMapFromPayload, adaptLiveBusiness, mergeLiveByBusinessNumber,
    acceptPayload, liveSummary, staticStatePreserved, statusText, classify, requestOnce, renderStatus,
    load, recover, teardown, autoStart, _state: state,
  };
});
