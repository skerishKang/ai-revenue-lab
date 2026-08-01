/*  state-machine.js  —  deterministic meeting-to-public-notice state machine (UMD)
 *
 *  Business 29 Phase 2 UX — Apartment Governance Ledger / 주민총회 원장
 *
 *  Pure module: no DOM, no Date, no Math.random. Every transition appends a
 *  Version + AuditEvent with the acting role. Deterministic and Node-testable.
 *
 *  Contract authorities:
 *    Issue #351 (Phase 2 UX execution contract)
 *    #351 comment 5150112052 — QUORUM_STATE_SEMANTICS_CORRECTION
 *    PR #352 repair — disclosure lifecycle gating, redaction returns to
 *    disclosure-review, manual disclosure approval + final publication gates,
 *    dynamic audit actor/role.
 *
 *  Disclosure contract:
 *    - 원본 업무 객체는 기본 private.
 *    - 회의 개최 공고: Gate 1(notice-review → publishNotice) 통과 후부터 공개.
 *    - 회의 연기·재소집 공고: cancelled 상태에서만 공개.
 *    - 최종 공개 패키지(안건·규약 근거·이견·의결·정족수·후속조치 요약·문서/redacted):
 *      public-notice-published 이전에는 주민 화면에 절대 표시 금지.
 *    - 공개는 사람이 검토한 Disclosure(approvePublic) + 최종 게시(publishPublicNotice)
 *      를 통한 public projection으로만.
 */

(function (root, factory) {
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ARLStateMachine = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  var STATES = Object.freeze([
    "empty", "draft", "agenda-ready", "notice-review", "notice-published",
    "attendance-open", "quorum-incomplete", "quorum-recorded", "discussion-open",
    "dissent-recorded", "resolution-draft", "resolution-review", "resolution-approved",
    "action-pending", "action-overdue", "disclosure-review", "redaction-required",
    "public-notice-ready", "public-notice-published", "version-history",
    "system-error", "retry", "cancelled", "completed"
  ]);

  function requireManualConfirm(payload) {
    if (!payload || payload.manualConfirm !== true) {
      throw new Error("manual confirm required");
    }
  }

  function confirmQuorum(machine, payload) {
    requireManualConfirm(payload);
    var attendance = Number(payload.attendance);
    var threshold = Number(payload.threshold);
    if (!isFinite(attendance) || !isFinite(threshold)) {
      throw new Error("quorum: attendance/threshold must be numeric");
    }
    machine.data.attendanceCount = attendance;
    machine.data.threshold = threshold;
    return attendance >= threshold ? "quorum-recorded" : "quorum-incomplete";
  }

  function supplementAttendance(machine) {
    machine.data.attendanceCount = Number(machine.fixture.attendance.supplementedCount);
    machine.data.supplemented = true;
    return "attendance-open";
  }

  function recordDissent(machine) {
    machine.data.dissent = JSON.parse(JSON.stringify(machine.fixture.dissent));
    return "dissent-recorded";
  }

  function finalizeDiscussion(machine) {
    machine.data.resolution = JSON.parse(JSON.stringify(machine.fixture.resolution));
    if (machine.data.dissent) {
      machine.data.resolution.dissentRef = machine.data.dissent.agenda;
    }
    return "resolution-draft";
  }

  function registerActions(machine) {
    machine.data.actions = JSON.parse(JSON.stringify(machine.fixture.actions));
    return "action-pending";
  }

  function markOverdue(machine) {
    if (machine.data.actions && machine.data.actions.length) {
      machine.data.actions[0].overdue = true;
    }
    return "action-overdue";
  }

  function requestRedaction(machine) {
    var doc = machine.data.documents[0];
    if (!doc || !doc.redactable || doc.redacted) {
      throw new Error("redaction: no private redactable document pending");
    }
    machine.data.redactionPending = doc.id;
    return "redaction-required";
  }

  function confirmRedaction(machine, payload) {
    if (!payload || !payload.redactedText) {
      throw new Error("redaction: redacted copy text is required");
    }
    var doc = machine.data.documents[0];
    doc.redacted = { text: String(payload.redactedText), confirmedBy: machine._ctx.actor, confirmed: true };
    doc.disclosure = "redacted";
    machine.data.redactionPending = null;
    // redaction은 공개 패키지 승인이 아니다 — 검토(disclosure-review)로 복귀
    return "disclosure-review";
  }

  /* ---- public projections ---- */

  function meetingNoticeProjection(machine) {
    return {
      id: "meeting-notice",
      publicTitle: "대표회의 개최 공고",
      publicSummary: machine.fixture.meeting.name + " · " + machine.fixture.community.name + " (" + machine.fixture.community.households + "세대)",
      disclosureState: "public",
      sourceObjectId: "meeting-notice",
      reviewedBy: machine.data.notice.reviewedBy || null,
      publishedBy: machine.data.notice.publishedBy || null,
      publishedVersion: machine.data.notice.publishedVersion || null
    };
  }

  function postponedNoticeProjection(machine) {
    return {
      id: "postponed-notice",
      publicTitle: machine.data.postponedNotice.title,
      publicSummary: machine.data.postponedNotice.reason,
      disclosureState: "public",
      sourceObjectId: "postponed-notice",
      reviewedBy: machine.data.postponedNotice.reviewedBy || null,
      publishedBy: machine.data.postponedNotice.publishedBy || null,
      publishedVersion: machine.data.postponedNotice.publishedVersion || null
    };
  }

  function agendaProjection(machine, id) {
    var a = null;
    machine.fixture.agenda.forEach(function (x) { if (x.id === id) a = x; });
    if (!a) return null;
    return {
      id: "agenda-" + id,
      publicTitle: a.title,
      publicSummary: "규약 근거: " + a.ruleRef,
      disclosureState: "public",
      sourceObjectId: id,
      reviewedBy: null, publishedBy: null, publishedVersion: null
    };
  }

  function resolutionProjection(machine) {
    return {
      id: "resolution",
      publicTitle: "의결 결과",
      publicSummary: machine.data.resolution.text,
      disclosureState: "public",
      sourceObjectId: "resolution",
      reviewedBy: null, publishedBy: null, publishedVersion: null
    };
  }

  function dissentProjection(machine) {
    return {
      id: "dissent",
      publicTitle: "이견 기록",
      publicSummary: machine.data.dissent.text,
      disclosureState: "public",
      sourceObjectId: machine.data.dissent.agenda,
      reviewedBy: null, publishedBy: null, publishedVersion: null
    };
  }

  function quorumProjection(machine) {
    return {
      id: "quorum",
      publicTitle: "정족수 결과",
      publicSummary: "출석 " + machine.data.attendanceCount + " / 기준 " + machine.data.threshold + " · 수동 확인",
      disclosureState: "public",
      sourceObjectId: "quorum",
      reviewedBy: null, publishedBy: null, publishedVersion: null
    };
  }

  function actionSummaryProjection(machine) {
    var summary = machine.data.actions.map(function (a) {
      return a.title + (a.overdue ? " (기한 초과)" : "");
    }).join(" · ");
    return {
      id: "action-summary",
      publicTitle: "후속조치 요약",
      publicSummary: summary || "후속조치 없음",
      disclosureState: "public",
      sourceObjectId: "action-summary",
      reviewedBy: null, publishedBy: null, publishedVersion: null
    };
  }

  function documentProjection(machine) {
    var doc = machine.data.documents[0];
    if (!doc || !doc.redacted) return null;
    return {
      id: "doc-" + doc.id,
      publicTitle: doc.title,
      publicSummary: doc.redacted.text,
      disclosureState: "redacted",
      sourceObjectId: doc.id,
      reviewedBy: null, publishedBy: null, publishedVersion: null
    };
  }

  function buildApprovedProjections(machine) {
    var projs = [];
    var packageItems = machine.fixture.disclosurePackage.items;
    packageItems.forEach(function (id) {
      if (id === "notice") return; // 회의 개최 공고는 별도 Gate 1
      if (id === "resolution") {
        var rp = resolutionProjection(machine);
        if (rp) projs.push(rp);
      } else if (id === "doc-1") {
        var dp = documentProjection(machine);
        if (dp) projs.push(dp);
      } else if (/^agenda-/.test(id)) {
        var ap = agendaProjection(machine, id);
        if (ap) projs.push(ap);
      }
    });
    if (machine.data.dissent) {
      projs.push(dissentProjection(machine));
    }
    projs.push(quorumProjection(machine));
    projs.push(actionSummaryProjection(machine));
    return projs;
  }

  function approvePublic(machine, payload) {
    requireManualConfirm(payload);
    if (machine._ctx.role !== "외부 검토자") {
      throw new Error("disclosure: approval requires 외부 검토자 role");
    }
    var docs = machine.data.documents;
    for (var i = 0; i < docs.length; i++) {
      if (docs[i].redactable && !docs[i].redacted) {
        throw new Error("disclosure: redaction required before public");
      }
    }
    var items = machine.fixture.disclosurePackage.items;
    if (!items || !items.length) {
      throw new Error("disclosure: package items missing");
    }
    var projs = buildApprovedProjections(machine);
    machine.data.disclosureApproved = true;
    machine.data.reviewedBy = machine._ctx.actor;
    machine.data.reviewedVersion = machine._tick + 1;
    machine.data.approvedProjectionIds = projs.map(function (p) { return p.id; });
    machine.data.approvedProjections = projs;
    return "public-notice-ready";
  }

  function publishPublicNotice(machine, payload) {
    if (!machine.data.disclosureApproved) {
      throw new Error("publish: disclosure approval required first");
    }
    requireManualConfirm(payload);
    if (machine._ctx.role !== "대표회의 관리자") {
      throw new Error("publish: requires 대표회의 관리자 role");
    }
    machine.data.published = true;
    machine.data.publishedBy = machine._ctx.actor;
    machine.data.publishedVersion = machine._tick + 1;
    (machine.data.approvedProjections || []).forEach(function (p) {
      p.publishedBy = machine._ctx.actor;
      p.publishedVersion = machine.data.publishedVersion;
    });
    return "public-notice-published";
  }

  function publishNotice(machine) {
    var fault = machine.fixture.fault;
    if (fault && fault.action === "publishNotice" && fault.failOnce && !machine._faultConsumed) {
      machine._faultConsumed = true;
      machine._recoverState = machine.state;
      machine.record("system-error", "publishNotice", "fault-injected");
      machine.state = "system-error";
      return machine.state;
    }
    machine.data.notice = {
      title: "대표회의 개최 공고 (합성)",
      disclosure: "public",
      published: true,
      reviewedBy: machine._ctx.actor,
      publishedBy: machine._ctx.actor,
      publishedVersion: machine._tick + 1
    };
    return "notice-published";
  }

  function postponeMeeting(machine) {
    machine.data.postponedNotice = {
      title: "정족수 미달로 인한 회의 연기·재소집 공고 (합성)",
      reason: "출석 미달 — 법적 효력/유효성 판단 없음",
      disclosure: "public",
      published: true,
      reviewedBy: machine._ctx.actor,
      publishedBy: machine._ctx.actor,
      publishedVersion: machine._tick + 1
    };
    return "cancelled";
  }

  function recover(machine) {
    var target = machine._recoverState;
    if (!target) throw new Error("retry: no recoverable state");
    machine._recoverState = null;
    return target;
  }

  var TRANSITIONS = Object.freeze({
    "empty": { startMeeting: "draft" },
    "draft": { completeAgenda: "agenda-ready" },
    "agenda-ready": { composeNotice: "notice-review" },
    "notice-review": { publishNotice: publishNotice },
    "notice-published": { openAttendance: "attendance-open" },
    "attendance-open": { confirmQuorum: confirmQuorum },
    "quorum-incomplete": { supplementAttendance: supplementAttendance, postponeMeeting: postponeMeeting },
    "quorum-recorded": { openDiscussion: "discussion-open" },
    "discussion-open": { recordDissent: recordDissent, finalizeDiscussion: finalizeDiscussion },
    "dissent-recorded": { finalizeDiscussion: finalizeDiscussion },
    "resolution-draft": { submitForReview: "resolution-review" },
    "resolution-review": { approveResolution: "resolution-approved" },
    "resolution-approved": { registerActions: registerActions },
    "action-pending": { markOverdue: markOverdue, proceedToDisclosure: "disclosure-review" },
    "action-overdue": { proceedToDisclosure: "disclosure-review" },
    "disclosure-review": { requestRedaction: requestRedaction, approvePublic: approvePublic },
    "redaction-required": { confirmRedaction: confirmRedaction },
    "public-notice-ready": { publishPublicNotice: publishPublicNotice },
    "public-notice-published": { viewHistory: "version-history", completeMeeting: "completed" },
    "version-history": { completeMeeting: "completed" },
    "system-error": { retry: "retry" },
    "retry": { recover: recover },
    "cancelled": {},
    "completed": {}
  });

  function createMachine(fixture, opts) {
    var fx = JSON.parse(JSON.stringify(fixture));
    var machine = {
      fixture: fx,
      state: "empty",
      data: {
        attendanceCount: Number(fx.attendance.initialCount),
        threshold: Number(fx.attendance.threshold),
        supplemented: false,
        dissent: null,
        resolution: null,
        actions: JSON.parse(JSON.stringify(fx.actions)),
        documents: JSON.parse(JSON.stringify(fx.documents)),
        notice: null,
        postponedNotice: null,
        redactionPending: null,
        disclosureApproved: false,
        reviewedBy: null,
        reviewedVersion: null,
        approvedProjectionIds: [],
        approvedProjections: [],
        published: false,
        publishedBy: null,
        publishedVersion: null
      },
      events: [],
      _faultConsumed: false,
      _recoverState: null,
      _tick: 0,
      _ctx: null
    };

    machine.record = function (toState, action, detail) {
      machine._tick += 1;
      var ctx = machine._ctx || { actor: "system", role: "system" };
      var event = {
        version: machine._tick,
        from: machine.state,
        to: toState,
        action: action,
        actor: ctx.actor,
        role: ctx.role,
        sequence: machine._tick,
        at: "t" + machine._tick,
        audit: { type: "state_change" }
      };
      if (detail) event.detail = detail;
      machine.events.push(event);
      return event;
    };

    machine.apply = function (action, payload, context) {
      context = context || {};
      if (machine.state === "system-error" && action !== "retry") {
        throw new Error("system-error: retry required before other actions");
      }
      if (machine.state === "retry" && action !== "recover") {
        throw new Error("retry: recover required before other actions");
      }
      var def = TRANSITIONS[machine.state];
      if (!def || !def[action]) {
        throw new Error("transition: action '" + action + "' not allowed from '" + machine.state + "'");
      }
      machine._ctx = { actor: context.actor || "system", role: context.role || "system" };
      var target = typeof def[action] === "function" ? def[action](machine, payload) : def[action];
      if (target !== machine.state) {
        machine.record(target, action);
      }
      machine.state = target;
      machine._ctx = null;
      return machine.state;
    };

    machine.allowed = function (action) {
      var def = TRANSITIONS[machine.state];
      return !!(def && def[action]);
    };

    /* Public surface = lifecycle-gated public projections (never raw objects). */
    machine.publicSurface = function () {
      var out = [];
      var state = machine.state;
      if (state === "cancelled") {
        if (machine.data.postponedNotice) out.push(postponedNoticeProjection(machine));
        return out;
      }
      var afterNotice = [
        "notice-published", "attendance-open", "quorum-incomplete", "quorum-recorded",
        "discussion-open", "dissent-recorded", "resolution-draft", "resolution-review",
        "resolution-approved", "action-pending", "action-overdue", "disclosure-review",
        "redaction-required", "public-notice-ready", "public-notice-published",
        "version-history", "completed"
      ];
      if (machine.data.notice && machine.data.notice.published && afterNotice.indexOf(state) !== -1) {
        out.push(meetingNoticeProjection(machine));
      }
      if (machine.data.published) {
        (machine.data.approvedProjections || []).forEach(function (p) { out.push(p); });
      }
      return out;
    };

    machine.publicObjects = function () {
      return machine.publicSurface();
    };

    machine.versionEvents = function () {
      return machine.events.filter(function (e) { return e.audit && e.audit.type === "state_change"; });
    };

    return machine;
  }

  /* Deterministic reachability paths from empty, with action payloads.
   * runPath passes the synthetic acting role per action so the audit actor
   * contract is exercised by every path. */
  var ACTION_ROLE = {
    recordDissent: "동대표·위원",
    registerActions: "관리사무소",
    requestRedaction: "외부 검토자",
    confirmRedaction: "외부 검토자",
    approvePublic: "외부 검토자",
    publishPublicNotice: "대표회의 관리자"
  };

  function ctxFor(action) {
    var role = ACTION_ROLE[action] || "대표회의 관리자";
    return { actor: role + "(합성)", role: role };
  }

  function pathTo(state) {
    var base = [
      ["startMeeting"],
      ["completeAgenda"],
      ["composeNotice"],
      ["publishNotice"],
      ["retry"],
      ["recover"],
      ["publishNotice"],
      ["openAttendance"],
      ["confirmQuorum", { attendance: 8, threshold: 10, manualConfirm: true }]
    ];
    var path = base.slice();
    switch (state) {
      case "empty": return [];
      case "draft": return path.slice(0, 1);
      case "agenda-ready": return path.slice(0, 2);
      case "notice-review": return path.slice(0, 3);
      case "notice-published": return path.slice(0, 7);
      case "attendance-open": return path.slice(0, 8);
      case "quorum-incomplete": return path.slice(0, 9);
      case "system-error": return path.slice(0, 4);
      case "retry": return path.slice(0, 5);
      case "quorum-recorded":
        return path.slice(0, 9).concat([
          ["supplementAttendance"],
          ["confirmQuorum", { attendance: 11, threshold: 10, manualConfirm: true }]
        ]);
      case "discussion-open": return pathTo("quorum-recorded").concat([["openDiscussion"]]);
      case "dissent-recorded": return pathTo("discussion-open").concat([["recordDissent"]]);
      case "resolution-draft": return pathTo("dissent-recorded").concat([["finalizeDiscussion"]]);
      case "resolution-review": return pathTo("resolution-draft").concat([["submitForReview"]]);
      case "resolution-approved": return pathTo("resolution-review").concat([["approveResolution"]]);
      case "action-pending": return pathTo("resolution-approved").concat([["registerActions"]]);
      case "action-overdue": return pathTo("action-pending").concat([["markOverdue"]]);
      case "disclosure-review": return pathTo("action-overdue").concat([["proceedToDisclosure"]]);
      case "redaction-required": return pathTo("disclosure-review").concat([["requestRedaction"]]);
      case "public-notice-ready":
        return pathTo("redaction-required").concat([
          ["confirmRedaction", { redactedText: "[비공개 내용 마스킹] 예산 총액만 공개 (합성)" }],
          ["approvePublic", { manualConfirm: true }]
        ]);
      case "public-notice-published":
        return pathTo("public-notice-ready").concat([["publishPublicNotice", { manualConfirm: true }]]);
      case "version-history": return pathTo("public-notice-published").concat([["viewHistory"]]);
      case "completed": return pathTo("version-history").concat([["completeMeeting"]]);
      case "cancelled": return path.slice(0, 9).concat([["postponeMeeting"]]);
      default: return null;
    }
  }

  function runPath(machine, path) {
    var steps = [];
    for (var i = 0; i < path.length; i++) {
      var step = path[i];
      var action = step[0];
      var payload = step[1] || {};
      var target = machine.apply(action, payload, ctxFor(action));
      steps.push(target);
    }
    return steps;
  }

  function createMachineAt(fixture, state) {
    var machine = createMachine(fixture);
    var path = pathTo(state);
    if (!path) throw new Error("pathTo: unknown state '" + state + "'");
    runPath(machine, path);
    return machine;
  }

  return {
    STATES: STATES,
    TRANSITIONS: TRANSITIONS,
    createMachine: createMachine,
    createMachineAt: createMachineAt,
    pathTo: pathTo,
    ctxFor: ctxFor,
    fullJourneyPath: function () { return pathTo("completed"); }
  };
});
