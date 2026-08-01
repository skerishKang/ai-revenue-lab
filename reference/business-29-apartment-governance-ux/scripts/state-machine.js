/*  state-machine.js  —  deterministic meeting-to-public-notice state machine (UMD)
 *
 *  Business 29 Phase 2 UX — Apartment Governance Ledger / 주민총회 원장
 *
 *  Pure module: no DOM, no Date, no Math.random. Every transition appends a
 *  Version + AuditEvent. The machine is deterministic and Node-testable.
 *
 *  Contract authorities:
 *    Issue #351 (Phase 2 UX execution contract)
 *    #351 comment 5150112052 — QUORUM_STATE_SEMANTICS_CORRECTION
 *
 *  Quorum semantics (per correction):
 *    - quorum-recorded requires a manual confirm by the 대표회의 관리자.
 *    - quorum-incomplete blocks discussion-open and resolution-*.
 *    - quorum-incomplete → attendance-open (supplement attendance) → manual recheck.
 *    - Postponement notice (연기/재소집 안내) is the only forward action from
 *      quorum-incomplete; it leads to cancelled. No legal validity judgement.
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

  function requireManualConfirm(machine, payload) {
    if (!payload || payload.manualConfirm !== true) {
      throw new Error("quorum: manual confirm required (대표회의 관리자 수동 확인)");
    }
  }

  function confirmQuorum(machine, payload) {
    requireManualConfirm(machine, payload);
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
    machine.data.dissent = machine.fixture.dissent;
    return "dissent-recorded";
  }

  function finalizeDiscussion(machine) {
    machine.data.resolution = machine.fixture.resolution;
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
    doc.redacted = { text: String(payload.redactedText), confirmedBy: "외부 검토자(합성)", confirmed: true };
    doc.disclosure = "redacted";
    machine.data.redactionPending = null;
    return "public-notice-ready";
  }

  function approvePublic(machine) {
    var docs = machine.data.documents;
    for (var i = 0; i < docs.length; i++) {
      var doc = docs[i];
      if (doc.redactable && !doc.redacted) {
        throw new Error("disclosure: redaction required before public");
      }
    }
    return "public-notice-ready";
  }

  function publishNoticeWithFault(machine) {
    var fault = machine.fixture.fault;
    if (fault && fault.action === "publishNotice" && fault.failOnce && !machine._faultConsumed) {
      machine._faultConsumed = true;
      machine._recoverState = machine.state;
      machine.record("system-error", "publishNotice", "fault-injected");
      machine.state = "system-error";
      return machine.state;
    }
    machine.data.notice = { title: "대표회의 개최 공고 (합성)", disclosure: "public" };
    return "notice-published";
  }

  function postponeMeeting(machine) {
    machine.data.postponedNotice = {
      title: "정족수 미달로 인한 회의 연기·재소집 공고 (합성)",
      reason: "출석 미달 — 법적 효력/유효성 판단 없음",
      disclosure: "public"
    };
    return "cancelled";
  }

  function recover(machine) {
    var target = machine._recoverState;
    if (!target) {
      throw new Error("retry: no recoverable state");
    }
    machine._recoverState = null;
    return target;
  }

  var TRANSITIONS = Object.freeze({
    "empty": { startMeeting: "draft" },
    "draft": { completeAgenda: "agenda-ready" },
    "agenda-ready": { composeNotice: "notice-review" },
    "notice-review": { publishNotice: publishNoticeWithFault },
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
    "public-notice-ready": { publishPublicNotice: "public-notice-published" },
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
        redactionPending: null
      },
      events: [],
      _faultConsumed: false,
      _recoverState: null,
      _tick: 0
    };

    machine.record = function (toState, action, detail) {
      machine._tick += 1;
      var event = {
        version: machine._tick,
        action: action,
        from: machine.state,
        to: toState,
        at: "t" + machine._tick,
        audit: { type: "state_change", actor: (opts && opts.actor) || "admin" }
      };
      if (detail) event.detail = detail;
      machine.events.push(event);
      return event;
    };

    machine.apply = function (action, payload) {
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
      var target = typeof def[action] === "function" ? def[action](machine, payload) : def[action];
      if (target !== machine.state) {
        machine.record(target, action);
      }
      machine.state = target;
      return machine.state;
    };

    machine.allowed = function (action) {
      var def = TRANSITIONS[machine.state];
      return !!(def && def[action]);
    };

    machine.publicObjects = function () {
      var out = [];
      var push = function (o) {
        if (!o) return;
        var d = o.disclosure || "private";
        if (d === "public" || (d === "redacted" && o.redacted)) out.push(o);
      };
      if (machine.data.notice) push(machine.data.notice);
      if (machine.data.postponedNotice) push(machine.data.postponedNotice);
      if (machine.data.resolution) push(machine.data.resolution);
      machine.fixture.agenda.forEach(push);
      machine.fixture.rules.forEach(push);
      if (machine.data.dissent) push(machine.data.dissent);
      machine.data.documents.forEach(push);
      return out;
    };

    machine.versionEvents = function () {
      return machine.events.filter(function (e) { return e.audit && e.audit.type === "state_change"; });
    };

    return machine;
  }

  // Deterministic reachability paths (action list with payloads) from empty.
  function pathTo(state) {
    var base = [
      ["startMeeting"],
      ["completeAgenda"],
      ["composeNotice"],
      ["publishNotice"], // fault-injected → system-error once
      ["retry"],
      ["recover"],
      ["publishNotice"], // succeeds
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
      case "system-error": return path.slice(0, 4); // failed publishNotice
      case "retry": return path.slice(0, 5);
      case "quorum-recorded":
        return path.slice(0, 9).concat([
          ["supplementAttendance"],
          ["confirmQuorum", { attendance: 11, threshold: 10, manualConfirm: true }]
        ]);
      case "discussion-open":
        return pathTo("quorum-recorded").concat([["openDiscussion"]]);
      case "dissent-recorded":
        return pathTo("discussion-open").concat([["recordDissent"]]);
      case "resolution-draft":
        return pathTo("dissent-recorded").concat([["finalizeDiscussion"]]);
      case "resolution-review":
        return pathTo("resolution-draft").concat([["submitForReview"]]);
      case "resolution-approved":
        return pathTo("resolution-review").concat([["approveResolution"]]);
      case "action-pending":
        return pathTo("resolution-approved").concat([["registerActions"]]);
      case "action-overdue":
        return pathTo("action-pending").concat([["markOverdue"]]);
      case "disclosure-review":
        return pathTo("action-overdue").concat([["proceedToDisclosure"]]);
      case "redaction-required":
        return pathTo("disclosure-review").concat([["requestRedaction"]]);
      case "public-notice-ready":
        return pathTo("redaction-required").concat([["confirmRedaction", { redactedText: "[비공개 내용 마스킹] 예산 총액만 공개 (합성)" }]]);
      case "public-notice-published":
        return pathTo("public-notice-ready").concat([["publishPublicNotice"]]);
      case "version-history":
        return pathTo("public-notice-published").concat([["viewHistory"]]);
      case "completed":
        return pathTo("version-history").concat([["completeMeeting"]]);
      case "cancelled":
        return path.slice(0, 9).concat([["postponeMeeting"]]);
      default:
        return null;
    }
  }

  function runPath(machine, path) {
    var steps = [];
    for (var i = 0; i < path.length; i++) {
      var step = path[i];
      var action = step[0];
      var payload = step[1] || {};
      var target = machine.apply(action, payload);
      steps.push(target);
    }
    return steps;
  }

  function createMachineAt(fixture, state) {
    var machine = createMachine(fixture);
    var path = pathTo(state);
    if (!path) {
      throw new Error("pathTo: unknown state '" + state + "'");
    }
    runPath(machine, path);
    return machine;
  }

  return {
    STATES: STATES,
    TRANSITIONS: TRANSITIONS,
    createMachine: createMachine,
    createMachineAt: createMachineAt,
    pathTo: pathTo,
    fullJourneyPath: function () { return pathTo("completed"); }
  };
});
