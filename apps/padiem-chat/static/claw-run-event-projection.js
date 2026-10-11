// #3930. Source-only projection of canonical P01 OrchestrationEvent.to_public_dict().
// No timer, synthetic progress, approval authority, network access, or raw event message.
(() => {
  "use strict";
  const COPY = Object.freeze({
    run_started: ["작업이 시작되었습니다", "Task started"],
    context_prepared: ["작업을 준비했습니다", "Task context prepared"],
    plan_created: ["실행 계획이 준비되었습니다", "Execution plan prepared"],
    tool_resolution: ["실행 도구를 확인했습니다", "Execution tool resolved"],
    tool_started: ["도구가 실행 중입니다", "Tool running"],
    tool_completed: ["도구 실행이 끝났습니다", "Tool step finished"],
    tool_failed: ["도구 실행에 실패했습니다", "Tool step failed"],
    verification_completed: ["결과 검증 단계가 끝났습니다", "Verification step finished"],
    approval_paused: ["사용자 승인을 기다리고 있습니다", "Awaiting user approval"],
    run_resumed: ["작업이 재개되었습니다", "Task resumed"],
    run_cancelled: ["작업이 취소되었습니다", "Task cancelled"],
    run_failed: ["작업이 실패했습니다", "Task failed"],
    run_completed: ["작업 실행이 완료되었습니다", "Task execution completed"],
  });
  const TERMINAL = new Set(["run_cancelled", "run_failed", "run_completed"]);
  const KNOWN = new Set([
    "run_started", "context_prepared", "memory_read", "plan_created",
    "skill_resolved", "tool_resolution", "tool_started", "tool_completed",
    "tool_failed", "evidence_attached", "verification_completed",
    "approval_paused", "run_resumed", "recovery_started", "recovery_decided",
    "retry_started", "retry_completed", "run_cancelled", "run_failed",
    "run_completed",
  ]);
  const IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/;
  const rejected = (reason) => ({ accepted: false, reason });
  const safeId = (value) => typeof value === "string" && IDENTIFIER.test(value);

  function create() {
    let runId = null;
    let traceId = null;
    let appId = null;
    let sequence = 0;
    let terminal = false;
    return Object.freeze({
      consume(event) {
        if (!event || typeof event !== "object" || Array.isArray(event)) return rejected("invalid_envelope");
        if (!safeId(event.event_id) || !safeId(event.run_id) || !safeId(event.trace_id) || !safeId(event.app_id)) return rejected("invalid_identity");
        if (!KNOWN.has(event.kind) || !Number.isSafeInteger(event.sequence) || event.sequence < 1) return rejected("invalid_event");
        if (typeof event.timestamp_iso !== "string" || !event.timestamp_iso.trim()) return rejected("invalid_timestamp");
        if (terminal) return rejected("already_terminal");
        if (sequence === 0) {
          if (event.sequence !== 1 || event.kind !== "run_started") return rejected("missing_start");
          runId = event.run_id;
          traceId = event.trace_id;
          appId = event.app_id;
        } else {
          if (event.run_id !== runId || event.trace_id !== traceId || event.app_id !== appId) return rejected("foreign_run");
          if (event.sequence <= sequence) return rejected("replayed_or_stale");
          if (event.sequence !== sequence + 1) return rejected("sequence_gap");
        }
        sequence = event.sequence;
        terminal = TERMINAL.has(event.kind);
        // Projection is deliberately a finite kind, never the untrusted message or metadata.
        return { accepted: true, kind: event.kind, sequence, terminal, labelAvailable: Object.hasOwn(COPY, event.kind) };
      },
      snapshot() { return Object.freeze({ runId, traceId, appId, sequence, terminal }); },
    });
  }

  function label(kind, lang = "ko") {
    const translated = COPY[kind];
    return translated ? translated[lang === "en" ? 1 : 0] : null;
  }
  window.PadiemClawRunEventProjection = Object.freeze({ create, label });
})();
