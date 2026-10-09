// #3935: pure client-side Claw/P01 observed-run recovery state. No authority,
// synthetic events, polling, retries, model fallback or completion grants.
(() => {
  "use strict";
  const TERMINAL = new Set(["failed", "cancelled", "completed"]);
  const KNOWN = new Set([
    "run_started", "context_prepared", "memory_read", "plan_created",
    "skill_resolved", "tool_resolution", "tool_started", "tool_completed",
    "tool_failed", "evidence_attached", "verification_completed",
    "approval_paused", "run_resumed", "recovery_started", "recovery_decided",
    "retry_started", "retry_completed", "run_cancelled", "run_failed",
    "run_completed",
  ]);
  const COPY = Object.freeze({
    failed: Object.freeze({
      ko: "실행이 실패했습니다. 일부 내용이 남아 있어도 전체 작업 완료가 아닙니다. 최근 실행을 확인하세요.",
      en: "Execution failed. Any partial output is not a completed task. Check Recent runs.",
    }),
    cancelled: Object.freeze({
      ko: "실행이 취소됐습니다. 일부 내용은 최종 결과가 아닙니다. 재전송하지 않고 최근 실행을 확인하세요.",
      en: "Execution was cancelled. Partial output is not final. Check Recent runs before a new request.",
    }),
    waiting_for_approval: Object.freeze({
      ko: "승인을 기다리는 작업입니다. 이 화면에는 승인 권한이 없으며 자동으로 다시 실행하지 않습니다.",
      en: "This task is awaiting approval. No approval authority or automatic replay is available here.",
    }),
    unknown: Object.freeze({
      ko: "실행 상태를 확인하지 못했습니다. 이미 실행됐을 수 있으니 최근 실행을 확인하세요. 자동 재시도하지 않습니다.",
      en: "Run state is unverified. It may already have executed. Check Recent runs; there is no automatic retry.",
    }),
  });
  function create() {
    let state = "unknown";
    let seen = false;
    return Object.freeze({
      observe(kind) {
        // Only call AFTER PadiemClawRunEventProjection.consume validated identity,
        // sequence, and terminal provenance. This object cannot validate the event.
        if (!KNOWN.has(kind) || TERMINAL.has(state)) return false;
        if (state === "waiting_for_approval" && kind !== "run_resumed" &&
            kind !== "run_cancelled" && kind !== "run_failed") return false;
        if (kind === "run_failed") state = "failed";
        else if (kind === "run_cancelled") state = "cancelled";
        else if (kind === "run_completed") state = "completed";
        else if (kind === "approval_paused") state = "waiting_for_approval";
        else if (kind === "run_resumed" && state === "waiting_for_approval") state = "running";
        else if (state === "unknown") state = "running";
        seen = true;
        return true;
      },
      state() { return state; },
      seen() { return seen; },
      completionAllowed() {
        // The existing validated SSE done frame remains required and is
        // authoritative if there was no terminal P01 event at all.
        return !["failed", "cancelled", "waiting_for_approval"].includes(state);
      },
    });
  }
  function copy(state, lang = "ko") {
    const item = COPY[state] || COPY.unknown;
    return lang === "en" || String(lang).toLowerCase().startsWith("en-") ? item.en : item.ko;
  }
  window.PadiemClawRecoveryTruth = Object.freeze({ create, copy });
})();
