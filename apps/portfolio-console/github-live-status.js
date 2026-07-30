(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ARLGithubLive = api;
  if (root.document) api.autoStart(root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const ENDPOINT = "/api/github-status";
  const REQUEST_TIMEOUT_MS = 8000;
  const state = { payload: null, loading: false, started: false, observer: null, scheduled: false };

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
  async function load(globalObject) {
    if (state.loading || state.payload?.ok) return state.payload;
    state.loading = true;
    const controller = new globalObject.AbortController();
    const timeout = globalObject.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await globalObject.fetch(ENDPOINT, { method: "GET", credentials: "same-origin", headers: { Accept: "application/json" }, signal: controller.signal });
      const payload = await response.json().catch(() => null);
      state.payload = acceptPayload(state.payload, payload);
      if (state.payload?.ok) scheduleDecorate(globalObject);
      return state.payload;
    } catch { return state.payload; }
    finally { globalObject.clearTimeout(timeout); state.loading = false; }
  }
  function autoStart(globalObject) {
    if (state.started) return;
    state.started = true;
    const start = () => {
      state.observer = new globalObject.MutationObserver(() => scheduleDecorate(globalObject));
      state.observer.observe(globalObject.document.body, { childList: true, subtree: true });
      load(globalObject);
    };
    if (globalObject.document.readyState === "loading") globalObject.document.addEventListener("DOMContentLoaded", start, { once: true });
    else start();
  }

  return { ENDPOINT, labelsFor, liveMapFromPayload, adaptLiveBusiness, mergeLiveByBusinessNumber, acceptPayload, liveSummary, staticStatePreserved, autoStart, _state: state };
});
