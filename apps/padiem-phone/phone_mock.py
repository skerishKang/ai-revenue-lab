"""Dependency-free, network-isolated outbound voice task simulator.

This module deliberately has no SIP, PSTN, provider SDK, or billing integration.
Local-only demonstrations must not be mistaken for authorized live calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import RLock
from time import monotonic
from uuid import uuid4
import re


class TaskError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


# (state, simulated elapsed minutes, wall seconds in the local demonstration)
SCENARIOS = {
    "standard": (
        ("DIALING", 2, 1.2),
        ("IVR", 3, 1.2),
        ("HOLD", 20, 2.0),
        ("CONSULTING", 5, 1.6),
        ("COMPLETED", 0, 0),
    ),
    "extended": (
        ("DIALING", 2, 1.2),
        ("IVR", 3, 1.2),
        ("HOLD", 55, 3.0),
        ("CONSULTING", 5, 1.6),
        ("COMPLETED", 0, 0),
    ),
    "no_answer": (
        ("DIALING", 4, 2.0),
        ("NO_ANSWER", 0, 0),
    ),
    "verification": (
        ("DIALING", 2, 1.2),
        ("IVR", 3, 1.2),
        ("HOLD", 14, 2.0),
        ("CONSULTING", 1, 1.2),
        ("AUTH_REQUIRED", 0, 0),
    ),
}
FINAL = frozenset({"COMPLETED", "NO_ANSWER", "AUTH_REQUIRED", "CANCELLED"})
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,80}$")


def _validate(data: dict) -> dict:
    if not isinstance(data, dict):
        raise TaskError("invalid_request")
    request_id = data.get("request_id")
    goal = data.get("goal")
    destination = data.get("destination")
    scenario = data.get("scenario", "standard")
    source = data.get("source", "web")
    if not isinstance(request_id, str) or not ID_PATTERN.fullmatch(request_id):
        raise TaskError("invalid_request_id")
    if not isinstance(goal, str) or not 3 <= len(goal.strip()) <= 300:
        raise TaskError("invalid_goal")
    if not isinstance(destination, str) or not 2 <= len(destination.strip()) <= 80:
        raise TaskError("invalid_destination")
    if any(ord(c) < 32 for c in goal + destination):
        raise TaskError("invalid_text")
    if not isinstance(scenario, str) or not isinstance(source, str):
        raise TaskError("invalid_mode")
    if scenario not in SCENARIOS or source not in ("web", "claw"):
        raise TaskError("invalid_mode")
    return {
        "request_id": request_id,
        "goal": goal.strip(),
        "destination": destination.strip(),
        "scenario": scenario,
        "source": source,
    }


@dataclass
class Task:
    task_id: str
    data: dict
    created_mono: float
    created_at: str
    cancelled: bool = False
    cancelled_elapsed: float | None = None


class MockPhoneTasks:
    """In-memory local task manager; caller supplies monotonic clock for tests."""

    def __init__(self, clock=None, max_tasks: int = 100):
        self.clock = clock or monotonic
        self.max_tasks = max_tasks
        self.tasks: dict[str, Task] = {}
        self.by_request: dict[str, str] = {}
        self.lock = RLock()

    def create(self, raw: dict) -> dict:
        data = _validate(raw)
        with self.lock:
            previous_id = self.by_request.get(data["request_id"])
            if previous_id:
                task = self.tasks[previous_id]
                if task.data != data:
                    raise TaskError("request_id_conflict", status=409)
                return self._snapshot(task)
            if len(self.tasks) >= self.max_tasks:
                raise TaskError("demo_capacity_reached", status=429)
            task = Task(
                task_id=uuid4().hex,
                data=data,
                created_mono=self.clock(),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self.tasks[task.task_id] = task
            self.by_request[data["request_id"]] = task.task_id
            return self._snapshot(task)

    def _get_task(self, task_id: str) -> Task:
        task = self.tasks.get(task_id)
        if not task:
            raise TaskError("task_not_found", status=404)
        return task

    def _snapshot(self, task: Task) -> dict:
        stages = SCENARIOS[task.data["scenario"]]
        real_elapsed = max(0.0, self.clock() - task.created_mono)
        if task.cancelled_elapsed is not None:
            real_elapsed = min(real_elapsed, task.cancelled_elapsed)
        accumulated_wall = 0.0
        simulated_minutes = 0
        state = stages[-1][0]
        phase_index = len(stages) - 1
        phase_elapsed = 0.0
        for index, (name, minutes, wall) in enumerate(stages):
            if real_elapsed < accumulated_wall + wall:
                state = name
                phase_index = index
                # Estimate progress within the phase, not just whole-phase time.
                phase_elapsed = min(1, max(0, (real_elapsed - accumulated_wall) / wall)) if wall else 0
                simulated_minutes += round(minutes * phase_elapsed)
                break
            accumulated_wall += wall
            simulated_minutes += minutes
        if task.cancelled:
            state = "CANCELLED"
        # The call provider is considered answered only after DIALING.
        answered = simulated_minutes if phase_index > 0 else 0
        if phase_index > 0:
            answered = max(0, simulated_minutes - stages[0][1])
        return {
            "task_id": task.task_id,
            "request_id": task.data["request_id"],
            "source": task.data["source"],
            "goal": task.data["goal"],
            "destination": task.data["destination"],
            "scenario": task.data["scenario"],
            "created_at": task.created_at,
            "state": state,
            "stage_index": phase_index,
            "stage_total": len(stages),
            "simulated_elapsed_minutes": simulated_minutes,
            "simulated_connected_minutes": answered,
            "terminal": state in FINAL,
            "result": (
                "모의 상담 처리 완료. 실제 상담 결과가 아닙니다."
                if state == "COMPLETED"
                else "모의 통화 무응답. 실제 발신은 없었습니다."
                if state == "NO_ANSWER"
                else "모의 본인확인 요청으로 작업을 보류했습니다."
                if state == "AUTH_REQUIRED"
                else "모의 작업이 중지되었습니다."
                if state == "CANCELLED"
                else None
            ),
            "network_calls": 0,
            "real_charges": 0,
        }

    def get(self, task_id: str) -> dict:
        with self.lock:
            return self._snapshot(self._get_task(task_id))

    def cancel(self, task_id: str) -> dict:
        with self.lock:
            task = self._get_task(task_id)
            current = self._snapshot(task)
            if not current["terminal"]:
                task.cancelled_elapsed = max(0.0, self.clock() - task.created_mono)
                task.cancelled = True
            return self._snapshot(task)

    def list(self) -> list[dict]:
        with self.lock:
            return [self._snapshot(t) for t in reversed(list(self.tasks.values()))]

    def summary(self) -> dict:
        snapshots = self.list()
        return {
            "tasks": len(snapshots),
            "completed": sum(t["state"] == "COMPLETED" for t in snapshots),
            "active": sum(not t["terminal"] for t in snapshots),
            "simulated_elapsed_minutes": sum(t["simulated_elapsed_minutes"] for t in snapshots),
            "real_calls": 0,
            "real_charges": 0,
        }
