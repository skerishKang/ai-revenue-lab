"""Read-only, evidence-honest report projections for simulated phone tasks.

Projection only: no audio transcript, provider CDR, conversation inference,
external calls, second task state authority, or user billing claims.
"""
from __future__ import annotations

from phone_mock import SCENARIOS, TaskError

STATE_NAMES = {
    "DIALING": "가상 발신 연결 시도",
    "IVR": "가상 ARS 안내",
    "HOLD": "가상 상담원 대기",
    "CONSULTING": "가상 상담 진행",
    "COMPLETED": "모의 완료",
    "NO_ANSWER": "가상 무응답",
    "AUTH_REQUIRED": "본인확인 필요(모의)",
    "CANCELLED": "모의 작업 취소",
    "INTERRUPTED": "서버 재시작으로 모의 작업 중단",
}
FINAL_STATES = frozenset({"COMPLETED", "NO_ANSWER", "AUTH_REQUIRED", "CANCELLED", "INTERRUPTED"})
REPORT_LIMIT_BYTES = 8192


def task_timeline(snapshot: dict) -> list[dict]:
    """Stages actually reached in the simulator, not a forecast of future stages.

    The simulator does not record carrier events. A timeline entry is always
    simulation-derived; even a COMPLETE event proves no actual consultation.
    """
    if not isinstance(snapshot, dict):
        raise TaskError("invalid_mock_snapshot")
    scenario = snapshot.get("scenario")
    steps = SCENARIOS.get(scenario) if isinstance(scenario, str) else None
    phase = snapshot.get("stage_index")
    elapsed = snapshot.get("simulated_elapsed_minutes")
    state = snapshot.get("state")
    if (steps is None or type(phase) is not int or not 0 <= phase < len(steps)
            or type(elapsed) is not int or elapsed < 0 or state not in STATE_NAMES):
        raise TaskError("invalid_mock_snapshot")
    terminal = state in FINAL_STATES
    reached = min(phase, len(steps) - 1)
    timeline = []
    minute = 0
    for index, (name, duration, _) in enumerate(steps):
        if index > reached:
            break
        completed = index < reached or (terminal and name == state)
        stage_used = duration if completed else max(0, min(duration, elapsed - minute))
        # Terminal cancellation/interruption references the last stage reached
        # but not an actual phone-provider completion.
        if terminal and name != state and index == reached:
            stage_used = max(0, min(duration, elapsed - minute))
        timeline.append({
            "state": name,
            "label": STATE_NAMES[name],
            "start_minute": minute,
            "end_minute": minute + stage_used,
            "phase": "complete" if completed else "stopped" if terminal else "current",
            "simulation_only": True,
        })
        minute += duration
    if terminal and state in ("CANCELLED", "INTERRUPTED"):
        timeline.append({
            "state": state,
            "label": STATE_NAMES[state],
            "start_minute": elapsed,
            "end_minute": elapsed,
            "phase": "stopped",
            "simulation_only": True,
        })
    return timeline


def task_report(snapshot: dict) -> str:
    """Bounded Korean UTF-8 human-readable report. Explicitly no real calls."""
    timeline = task_timeline(snapshot)
    lines = [
        "PADIEM Phone | 모의 전화 업무 보고서",
        "※ 시뮬레이션 전용. 실제 발신·ARS·상담·녹음·전사는 전혀 수행되지 않았습니다.",
        "",
        f"작업 ID: {snapshot['task_id']}",
        f"생성 시각(UTC): {snapshot['created_at']}",
        f"요청 경로(가상): {snapshot['source']}",
        f"대상(가상): {snapshot['destination']}",
        f"업무 목표: {snapshot['goal']}",
        f"확인할 질문: {snapshot['questions'] or '(없음)'}",
        f"주의사항: {snapshot['notes'] or '(없음)'}",
        f"대본 ID: {snapshot['script_id'] or '(없음)'}",
        f"결과 상태: {STATE_NAMES[snapshot['state']]}",
        f"가상 경과시간: {snapshot['simulated_elapsed_minutes']}분",
        f"가상 연결시간: {snapshot['simulated_connected_minutes']}분",
        "실제 전화 발신: 0건",
        "실제 통신요금: 0원",
        "",
        "모의 진행 단계 (실제 통신사 증거가 아님)",
    ]
    for item in timeline:
        lines.append(
            f"- {item['label']}: 가상 {item['start_minute']}~{item['end_minute']}분 "
            f"[{item['phase']}]"
        )
    lines.extend([
        "",
        "시뮬레이션 결과:",
        snapshot.get("result") or "아직 모의 작업 진행 중 — 실제 상담 답변 없음.",
        "",
        "이 문서는 실제 고객센터 상담 증명, 통화 녹취록, 계약 또는 결제 영수증이 아닙니다.",
    ])
    text = "\n".join(lines) + "\n"
    if len(text.encode("utf-8")) > REPORT_LIMIT_BYTES:
        raise TaskError("mock_report_too_large", 413)
    return text


def stage_usage(snapshots: list[dict]) -> dict:
    """Read-only simulated phase durations; not a provider billing metric."""
    phases = ("DIALING", "IVR", "HOLD", "CONSULTING")
    totals = {name: 0 for name in phases}
    visits = {name: 0 for name in phases}
    for snap in snapshots:
        for event in task_timeline(snap):
            name = event["state"]
            if name in totals:
                totals[name] += event["end_minute"] - event["start_minute"]
                visits[name] += 1
    return {
        "simulation_only": True,
        "stages": [
            {"state": name, "label": STATE_NAMES[name],
             "simulated_minutes": totals[name], "simulated_visits": visits[name]}
            for name in phases
        ],
        "real_calls": 0,
        "real_charges": 0,
    }
