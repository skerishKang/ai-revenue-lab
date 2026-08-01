/*  app.js  —  Business 29 Phase 2 UX controller
 *
 *  Deterministic meeting-to-public-notice governance ledger UI.
 *  Role switching expresses synthetic authorization (no real auth/backend).
 *  Disallowed controls are disabled + reason text. Public surface only from
 *  human-reviewed Disclosure objects. No external runtime resources.
 */

(function () {
  "use strict";

  var fixture = window.ARL_FIXTURE;
  var SM = window.ARLStateMachine;

  var ROLES = ["대표회의 관리자", "동대표·위원", "관리사무소", "감사", "일반 주민", "외부 검토자"];

  var ROLE_ALLOW = {
    startMeeting: ["대표회의 관리자", "동대표·위원"],
    completeAgenda: ["대표회의 관리자", "동대표·위원"],
    composeNotice: ["대표회의 관리자", "동대표·위원", "관리사무소"],
    publishNotice: ["대표회의 관리자"],
    openAttendance: ["대표회의 관리자", "관리사무소"],
    confirmQuorum: ["대표회의 관리자"],
    supplementAttendance: ["대표회의 관리자", "관리사무소"],
    postponeMeeting: ["대표회의 관리자"],
    openDiscussion: ["대표회의 관리자"],
    recordDissent: ["대표회의 관리자", "동대표·위원"],
    finalizeDiscussion: ["대표회의 관리자"],
    submitForReview: ["대표회의 관리자"],
    approveResolution: ["대표회의 관리자"],
    registerActions: ["대표회의 관리자", "관리사무소"],
    markOverdue: ["대표회의 관리자", "관리사무소"],
    proceedToDisclosure: ["대표회의 관리자"],
    requestRedaction: ["대표회의 관리자", "외부 검토자"],
    confirmRedaction: ["대표회의 관리자", "외부 검토자"],
    approvePublic: ["대표회의 관리자", "외부 검토자"],
    publishPublicNotice: ["대표회의 관리자"],
    viewHistory: ROLES.slice(),
    completeMeeting: ["대표회의 관리자"],
    retry: ROLES.slice(),
    recover: ROLES.slice()
  };

  var machine = SM.createMachine(fixture);
  var currentRole = "대표회의 관리자";
  var currentTab = "ledger";

  var $ = function (id) { return document.getElementById(id); };
  var badge = $("state-badge"), panel = $("panel"), flowbar = $("flowbar");
  var liveRegion = $("live-region"), caption = $("state-caption");

  function escapeHtml(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function stateLabel(state) {
    return String(state).replace(/-/g, " ").toUpperCase();
  }

  function announce(text) {
    liveRegion.hidden = false;
    liveRegion.textContent = "알림: " + text;
  }

  function can(role, action) {
    var list = ROLE_ALLOW[action];
    return !!(list && list.indexOf(role) !== -1);
  }

  function denyReason(action) {
    if (currentRole === "일반 주민") return "일반 주민은 공개 자료만 열람할 수 있습니다.";
    if (currentRole === "감사") return "감사는 원장·이력 열람만 가능하며 기록을 변경할 수 없습니다.";
    return "현재 역할(" + currentRole + ")은 이 작업을 수행할 수 없습니다.";
  }

  function actionButton(action, label, opts) {
    opts = opts || {};
    var allowed = can(currentRole, action);
    var html = '<button type="button" class="action-btn' + (opts.ghost ? " ghost" : "") + '" data-action="' + action + '"' +
      (allowed ? "" : " disabled") + ">" + escapeHtml(label) + "</button>";
    var note = allowed ? "" : '<p class="deny-note">' + escapeHtml(denyReason(action)) + "</p>";
    return html + note;
  }

  function disclosureChip(d) {
    var cls = "dp-" + d;
    return '<span class="disclosure-chip ' + cls + '">' + escapeHtml(d) + "</span>";
  }

  function objectRow(title, d, extra) {
    return "<li><strong>" + escapeHtml(title) + "</strong> " + disclosureChip(d) +
      (extra ? "<small>" + escapeHtml(extra) + "</small>" : "") + "</li>";
  }

  function renderRoleChips() {
    var html = "";
    ROLES.forEach(function (r) {
      html += '<button type="button" class="role-chip" data-role="' + escapeHtml(r) + '" aria-pressed="' + (r === currentRole) + '">' + escapeHtml(r) + "</button>";
    });
    $("role-chips").innerHTML = html;
  }

  function renderFlowbar() {
    var flow = ["draft", "agenda-ready", "notice-review", "notice-published", "attendance-open", "quorum-recorded", "discussion-open", "resolution-approved", "action-pending", "disclosure-review", "public-notice-published", "completed"];
    var order = SM.STATES;
    var idx = order.indexOf(machine.state);
    var html = "";
    flow.forEach(function (s) {
      var si = order.indexOf(s);
      var cls = si <= idx ? "done" : "";
      if (s === machine.state) cls = "current";
      html += '<span class="step ' + cls + '">' + escapeHtml(stateLabel(s)) + "</span>";
    });
    flowbar.innerHTML = html;
  }

  function renderStateBadge() {
    badge.className = "state-badge sb-" + machine.state;
    badge.textContent = stateLabel(machine.state);
    caption.textContent = "합성 회의 상태 · 현재 단계 " + machine.state;
  }

  /* ---- per-state panels ---- */

  function panelEmpty() {
    return '<div class="panel"><h3>빈 원장</h3>' +
      '<p class="empty-note">아직 생성된 회의가 없습니다. 합성 대표회의를 시작하세요.</p>' +
      '<div class="actions">' + actionButton("startMeeting", "회의 시작") + "</div></div>";
  }

  function panelDraft() {
    var list = fixture.agenda.map(function (a) { return objectRow(a.title, a.disclosure, "규약 근거: " + a.ruleRef); }).join("");
    return '<div class="panel"><h3>안건 원장 (draft)</h3><ul>' + list + "</ul>" +
      '<div class="actions">' + actionButton("completeAgenda", "안건 준비 완료") + "</div></div>";
  }

  function panelAgendaReady() {
    return '<div class="panel"><h3>안건 준비 완료 (agenda-ready)</h3>' +
      "<p>안건 2건이 규약·근거와 연결되었습니다. 회의 공고를 작성합니다.</p>" +
      '<div class="actions">' + actionButton("composeNotice", "회의 공고 작성") + "</div></div>";
  }

  function panelNoticeReview() {
    return '<div class="notice-paper"><h4>대표회의 개최 공고 (검토 중)</h4>' +
      "<p>2026년 3분기 합성 대표회의 · 솔빛마루 2단지 · 합성 데이터</p>" +
      "<p>안건: 공용부 정비 계획 논의 / 관리규약 개정 준비</p></div>" +
      '<div class="actions">' + actionButton("publishNotice", "공고 게시(검토 완료)", { ghost: false }) + "</div>";
  }

  function panelNoticePublished() {
    return '<div class="panel"><h3>공고 게시 완료 (notice-published)</h3>' +
      '<span class="notice-paper" style="display:block;border-top-width:3px">' +
      "<strong>대표회의 개최 공고 (합성)</strong></span>" +
      '<div class="actions">' + actionButton("openAttendance", "출석 입력 시작") + "</div></div>";
  }

  function panelAttendanceOpen() {
    var att = machine.data;
    return '<div class="panel"><h3>출석 입력 (attendance-open)</h3>' +
      '<div class="form-row">' +
      "<label>출석 수<input id=\"att-count\" type=\"number\" value=\"" + att.attendanceCount + "\" min=\"0\"></label>" +
      "<label>정족 기준(합성 규약)<input id=\"att-threshold\" type=\"number\" value=\"" + att.threshold + "\" min=\"0\"></label>" +
      '<label class="full"><input id="att-manual" type="checkbox"> 대표회의 관리자 수동 확인 (출석자료·규약 기준 검토 완료)</label>' +
      "</div>" +
      '<div class="actions">' + actionButton("confirmQuorum", "정족수 확인 기록") + "</div></div>";
  }

  function panelQuorumIncomplete() {
    return '<div class="quorum-card"><h4>정족수 미달 (quorum-incomplete)</h4>' +
      "<p>출석 " + machine.data.attendanceCount + " / 기준 " + machine.data.threshold + " — 의결·논의 진행 불가 (법률적 유효성 판단 아님).</p>" +
      "<p>회의 연기·재소집 공고를 생성하거나, 출석 자료를 보완해 재확인할 수 있습니다.</p></div>" +
      '<div class="actions">' +
      actionButton("supplementAttendance", "출석 자료 보완") +
      actionButton("postponeMeeting", "연기·재소집 공고 생성", { ghost: true }) +
      "</div>";
  }

  function panelQuorumRecorded() {
    return '<div class="quorum-card ok"><h4>정족수 확인 기록 (quorum-recorded)</h4>' +
      "<p>출석 " + machine.data.attendanceCount + " / 기준 " + machine.data.threshold + " — 수동 확인 완료. (법적 효력 보장 아님)</p></div>" +
      '<div class="actions">' + actionButton("openDiscussion", "논의 시작") + "</div>";
  }

  function panelDiscussionOpen() {
    var notes = fixture.discussion.notes.map(function (n) { return objectRow("논의 기록 (합성)", n.disclosure, n.text); }).join("");
    return '<div class="panel"><h3>논의 (discussion-open)</h3><ul>' + notes + "</ul>" +
      '<div class="actions">' +
      actionButton("recordDissent", "이견 기록") +
      actionButton("finalizeDiscussion", "논의 종결", { ghost: true }) +
      "</div></div>";
  }

  function panelDissentRecorded() {
    var d = fixture.dissent;
    return '<div class="panel"><h3>이견 기록 (dissent-recorded)</h3>' +
      '<ul><li><strong>' + escapeHtml(d.member) + "</strong> " + disclosureChip(d.disclosure) +
      "<small>" + escapeHtml(d.text) + " · 이견은 보존되며 의결과 함께 기록됩니다.</small></li></ul>" +
      '<div class="actions">' + actionButton("finalizeDiscussion", "논의 종결") + "</div></div>";
  }

  function panelResolutionDraft() {
    return '<div class="panel"><h3>의결안 초안 (resolution-draft)</h3>' +
      "<p>" + escapeHtml(fixture.resolution.text) + "</p>" +
      '<div class="actions">' + actionButton("submitForReview", "검토 요청") + "</div></div>";
  }

  function panelResolutionReview() {
    return '<div class="panel"><h3>의결안 검토 (resolution-review)</h3>' +
      "<p>" + escapeHtml(fixture.resolution.text) + "</p>" +
      '<div class="actions">' + actionButton("approveResolution", "의결 승인") + "</div></div>";
  }

  function panelResolutionApproved() {
    return '<div class="panel"><h3>의결 승인 (resolution-approved)</h3>' +
      '<span class="resolution-seal">의결 · APPROVED</span><span class="audit-mark">감사 기록</span>' +
      "<p>" + escapeHtml(fixture.resolution.text) + "</p>" +
      '<div class="actions">' + actionButton("registerActions", "후속조치 등록") + "</div></div>";
  }

  function panelActionPending() {
    var list = machine.data.actions.map(function (a) {
      return objectRow(a.title, a.disclosure, "담당자: " + a.owner + " · 기한: " + a.due + (a.overdue ? " · 기한 초과" : ""));
    }).join("");
    return '<div class="panel"><h3>후속조치 (action-pending)</h3><ul>' + list + "</ul>" +
      '<div class="actions">' +
      actionButton("markOverdue", "기한 초과로 표시", { ghost: true }) +
      actionButton("proceedToDisclosure", "공개 대상 검토로 진행") +
      "</div></div>";
  }

  function panelActionOverdue() {
    var a = machine.data.actions[0];
    return '<div class="quorum-card"><h4>기한 초과 후속조치 (action-overdue)</h4>' +
      "<p>" + escapeHtml(a.title) + " — 담당자 " + escapeHtml(a.owner) + " · 기한 " + escapeHtml(a.due) + " 초과 (합성). 법률 판단 아님.</p></div>" +
      '<div class="actions">' + actionButton("proceedToDisclosure", "공개 대상 검토로 진행") + "</div>";
  }

  function panelDisclosureReview() {
    var items = fixture.disclosurePackage.items.map(function (id) {
      return "<li>" + escapeHtml(id) + "</li>";
    }).join("");
    var doc = fixture.documents[0];
    var docRow = objectRow(doc.title, doc.disclosure, doc.redacted ? "redacted 복사본 확인됨" : "공개 전 redaction 필요");
    return '<div class="panel"><h3>공개 대상 검토 (disclosure-review)</h3>' +
      "<p>공개 패키지는 사람 검토 후에만 공개됩니다.</p>" +
      "<ul>" + items + "</ul>" +
      "<p><strong>문서:</strong></p><ul>" + docRow + "</ul>" +
      '<div class="actions">' +
      actionButton("requestRedaction", "redaction 필요로 보냄", { ghost: true }) +
      actionButton("approvePublic", "공개 승인(사람 검토 완료)") +
      "</div></div>";
  }

  function panelRedactionRequired() {
    var doc = machine.data.documents[0];
    return '<div class="quorum-card"><h4>redaction 필요 (redaction-required)</h4>' +
      "<p>비공개 원본 <strong>" + escapeHtml(doc.title) + "</strong>은 주민 화면에 노출될 수 없습니다. 공개용 redacted 복사본을 만드십시오.</p></div>" +
      '<div class="form-row"><label class="full">redacted 복사본 내용' +
      '<textarea id="redacted-text" rows="3">[비공개 내용 마스킹] 예산 총액만 공개 (합성)</textarea></label></div>' +
      '<div class="actions">' + actionButton("confirmRedaction", "redacted 복사본 확인") + "</div></div>";
  }

  function panelPublicNoticeReady() {
    var doc = machine.data.documents[0];
    var redactedTxt = doc.redacted ? doc.redacted.text : "";
    return '<div class="notice-paper"><h4>주민 공개 공고 (최종 확인)</h4>' +
      "<p>합성 의결 결과 · 정족수 확인 완료 · 이견 보존 기록</p>" +
      "<p>첨부(redacted): " + escapeHtml(redactedTxt) + "</p></div>" +
      '<div class="actions">' + actionButton("publishPublicNotice", "공개 게시") + "</div>";
  }

  function panelPublicNoticePublished() {
    return '<div class="notice-paper"><h4>주민 공개 공고 게시됨 (public-notice-published)</h4>' +
      "<p>합성 의결 결과가 공개되었습니다. 변경·공개 이력을 확인하고 회의를 마칩니다.</p></div>" +
      '<div class="actions">' +
      actionButton("viewHistory", "변경·공개 이력 보기", { ghost: true }) +
      actionButton("completeMeeting", "회의 완료") +
      "</div>";
  }

  function panelVersionHistory() {
    var rows = machine.events.map(function (e) {
      return "<tr><td>v" + e.version + "</td><td>" + escapeHtml(e.from) + "</td><td>" + escapeHtml(e.action) + "</td><td>" + escapeHtml(e.to) + "</td><td>" + escapeHtml(e.audit.actor) + "</td><td>" + escapeHtml(e.at) + "</td></tr>";
    }).join("");
    var publicDocs = machine.publicObjects().map(function (o) { return "<li>" + escapeHtml(o.title || o.id || "객체") + " " + disclosureChip(o.disclosure) + "</li>"; }).join("");
    return '<div class="panel"><h3>변경·공개 이력 (version-history)</h3>' +
      "<p><strong>공개 표면(public surface):</strong></p><ul>" + (publicDocs || "<li class='empty-note'>공개 객체 없음</li>") + "</ul>" +
      '<div class="audit-table-wrap"><table class="audit-table"><thead><tr><th>버전</th><th>이전 상태</th><th>액션</th><th>이후 상태</th><th>역할</th><th>시퀀스</th></tr></thead><tbody>' + rows + "</tbody></table></div>" +
      '<div class="actions">' + actionButton("completeMeeting", "회의 완료") + "</div></div>";
  }

  function panelSystemError() {
    return '<div class="error-panel"><h3>시스템 오류 (system-error)</h3>' +
      "<p>합성 주입 오류 발생 — 마지막 작업이 완료되지 않았습니다. 데이터는 보존됩니다.</p>" +
      '<div class="actions">' + actionButton("retry", "다시 시도") + "</div></div>";
  }

  function panelRetry() {
    return '<div class="panel"><h3>재시도 (retry)</h3>' +
      "<p>복구 준비 완료. 이전 상태로 복원합니다.</p>" +
      '<div class="actions">' + actionButton("recover", "이전 상태로 복원") + "</div></div>";
  }

  function panelCancelled() {
    var n = machine.data.postponedNotice;
    return '<div class="panel"><h3>회의 연기 (cancelled)</h3>' +
      (n ? objectRow(n.title, n.disclosure, n.reason) : "<p>연기 처리됨</p>") +
      "<p class='deny-note'>법률적 유효성 판단 아님 — 합성 안내.</p></div>";
  }

  function panelCompleted() {
    var publicDocs = machine.publicObjects();
    return '<div class="panel"><h3>회의 완료 (completed)</h3>' +
      "<p>합성 회의 1건이 원장에 무결하게 기록되었습니다.</p>" +
      "<p>공개 객체: " + publicDocs.length + "건 · 변경 이력(Version+AuditEvent): " + machine.events.length + "건</p>" +
      '<span class="resolution-seal">완료 · COMPLETED</span></div>';
  }

  function renderPanel() {
    var view;
    if (currentRole === "일반 주민") {
      view = panelResidentView();
    } else {
      var fns = {
        "empty": panelEmpty, "draft": panelDraft, "agenda-ready": panelAgendaReady,
        "notice-review": panelNoticeReview, "notice-published": panelNoticePublished,
        "attendance-open": panelAttendanceOpen, "quorum-incomplete": panelQuorumIncomplete,
        "quorum-recorded": panelQuorumRecorded, "discussion-open": panelDiscussionOpen,
        "dissent-recorded": panelDissentRecorded, "resolution-draft": panelResolutionDraft,
        "resolution-review": panelResolutionReview, "resolution-approved": panelResolutionApproved,
        "action-pending": panelActionPending, "action-overdue": panelActionOverdue,
        "disclosure-review": panelDisclosureReview, "redaction-required": panelRedactionRequired,
        "public-notice-ready": panelPublicNoticeReady, "public-notice-published": panelPublicNoticePublished,
        "version-history": panelVersionHistory, "system-error": panelSystemError,
        "retry": panelRetry, "cancelled": panelCancelled, "completed": panelCompleted
      };
      view = (fns[machine.state] || panelEmpty)();
    }
    panel.innerHTML = view;
  }

  function panelResidentView() {
    var pub = machine.publicObjects();
    var list = pub.map(function (o) {
      return "<li><strong>" + escapeHtml(o.title || o.id || "객체") + "</strong> " + disclosureChip(o.disclosure) +
        (o.redacted && o.redacted.text ? "<small>" + escapeHtml(o.redacted.text) + "</small>" : "") + "</li>";
    }).join("");
    return '<div class="panel"><h3>주민 공개 공고 (일반 주민 열람)</h3>' +
      "<p>주민은 공개 객체만 볼 수 있습니다. 비공개 원본은 표시되지 않습니다.</p>" +
      "<ul>" + (list || "<li class='empty-note'>아직 공개된 자료가 없습니다.</li>") + "</ul>" +
      '<div class="actions"><button type="button" class="action-btn" disabled>공개 자료 열람</button>' +
      '<p class="deny-note">일반 주민은 공개 자료만 열람할 수 있습니다.</p></div></div>';
  }

  function renderRuleTabs() {
    var map = { ledger: "원장", rulebook: "규약·근거", documents: "문서·증거", history: "변경·공개 이력" };
    document.querySelectorAll("[data-rule-tab]").forEach(function (btn) {
      btn.setAttribute("aria-selected", String(btn.dataset.ruleTab === currentTab));
    });
    if (currentTab === "rulebook") {
      panel.innerHTML = '<div class="panel"><h3>규약·근거 (rulebook)</h3>' +
        fixture.rules.map(function (r) { return objectRow(r.title, r.disclosure, r.excerpt); }).join("") +
        "</div>";
    } else if (currentTab === "documents") {
      panel.innerHTML = '<div class="panel"><h3>문서·증거 (documents)</h3>' +
        machine.data.documents.map(function (d) {
          return objectRow(d.title, d.disclosure, d.redacted ? "redacted 복사본 확인됨" : d.note);
        }).join("") + "</div>";
    } else if (currentTab === "history") {
      panel.innerHTML = panelVersionHistory();
    } else {
      renderPanel();
    }
  }

  function render() {
    renderStateBadge();
    renderFlowbar();
    renderRoleChips();
    renderRuleTabs();
  }

  function runAction(action, payload) {
    try {
      var prev = machine.state;
      var next = machine.apply(action, payload);
      render();
      announce("상태 전환: " + stateLabel(prev) + " → " + stateLabel(next));
    } catch (err) {
      announce("오류: " + err.message);
      var errBox = document.createElement("div");
      errBox.className = "error-panel";
      errBox.textContent = "동작 실패: " + err.message + " (합성 — 실제 오류 아님)";
      panel.insertAdjacentElement("afterbegin", errBox);
      setTimeout(function () { errBox.remove(); }, 4000);
    }
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("button");
    if (!btn) return;
    var action = btn.getAttribute("data-action");
    if (action) {
      if (btn.disabled) return;
      var payload = {};
      if (action === "confirmQuorum") {
        payload.attendance = Number($("att-count").value);
        payload.threshold = Number($("att-threshold").value);
        payload.manualConfirm = $("att-manual").checked;
      }
      if (action === "confirmRedaction") {
        payload.redactedText = $("redacted-text").value;
      }
      runAction(action, payload);
      return;
    }
    var role = btn.getAttribute("data-role");
    if (role) {
      currentRole = role;
      render();
      announce("역할 전환: " + role);
      return;
    }
    var tab = btn.getAttribute("data-rule-tab");
    if (tab) {
      currentTab = tab;
      render();
      return;
    }
  });

  render();
  announce("합성 회의 원장 시작 — 상태: empty");
})();
