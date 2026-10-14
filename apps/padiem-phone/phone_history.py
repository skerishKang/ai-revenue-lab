"""Local preview-only durable *mock* task record store.

Records are written outside Git in the current user's app-data directory.
Unfinished simulations are marked INTERRUPTED on restart; never claim a phone
call continued while this mock server was down. This is NOT an operational
calling, multi-tenant, authorization, CDR, or billing authority.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from uuid import UUID
import json
import os

from phone_mock import MockPhoneTasks, Task, TaskError, _validate

MAX_HISTORY_FILE = 512_000


class DurableMockPhoneTasks(MockPhoneTasks):
    """Durable snapshot history for the single-user loopback simulator."""

    def __init__(self, path: Path, **kwargs):
        self.path = Path(path)
        self._replayed: dict[str, dict] = {}
        self._saved_final: set[str] = set()
        super().__init__(**kwargs)
        self._restore()

    def _restore(self) -> None:
        if not self.path.exists():
            return
        if self.path.stat().st_size > MAX_HISTORY_FILE:
            raise ValueError("preview_history_too_large")
        body = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(body, dict) or body.get("version") != 1 or not isinstance(body.get("tasks"), list):
            raise ValueError("invalid_preview_history")
        if len(body["tasks"]) > self.max_tasks:
            raise ValueError("preview_history_over_capacity")
        interrupted = False
        for row in body["tasks"]:
            if not isinstance(row, dict) or not isinstance(row.get("snapshot"), dict):
                raise ValueError("invalid_preview_history_record")
            data = _validate(row.get("data"))
            snap = row["snapshot"]
            task_id = snap.get("task_id")
            if not isinstance(task_id, str) or len(task_id) != 32:
                raise ValueError("invalid_preview_task_id")
            try:
                if UUID(hex=task_id).hex != task_id:
                    raise ValueError("invalid_preview_task_id")
            except (ValueError, AttributeError) as exc:
                raise ValueError("invalid_preview_task_id") from exc
            if (
                snap.get("request_id") != data["request_id"]
                or snap.get("goal") != data["goal"]
                or snap.get("destination") != data["destination"]
                or snap.get("scenario") != data["scenario"]
                or snap.get("source") != data["source"]
                or snap.get("script_id") != data["script_id"]
                or not isinstance(snap.get("created_at"), str)
                or not isinstance(snap.get("terminal"), bool)
                or not isinstance(snap.get("simulated_elapsed_minutes"), int)
                or not isinstance(snap.get("simulated_connected_minutes"), int)
                or snap.get("network_calls") != 0
                or snap.get("real_charges") != 0
                or task_id in self.tasks
                or data["request_id"] in self.by_request
            ):
                raise ValueError("invalid_preview_history_snapshot")
            task = Task(task_id=task_id, data=data, created_mono=self.clock(), created_at=snap["created_at"])
            self.tasks[task_id] = task
            self.by_request[data["request_id"]] = task_id
            if snap["terminal"]:
                self._replayed[task_id] = deepcopy(snap)
            else:
                interrupted = True
                self._replayed[task_id] = {
                    **deepcopy(snap),
                    "state": "INTERRUPTED",
                    "terminal": True,
                    "result": "모의 서버가 재시작되어 진행 중이던 가상 작업이 중단되었습니다. 실제 발신은 없었습니다.",
                }
            self._saved_final.add(task_id)
        if interrupted:
            self._persist()

    def _snapshot(self, task: Task) -> dict:
        saved = self._replayed.get(task.task_id)
        return deepcopy(saved) if saved is not None else super()._snapshot(task)

    def _persist(self) -> None:
        if len(self.tasks) > self.max_tasks:
            raise TaskError("preview_history_full", 413)
        body = {
            "version": 1,
            "tasks": [
                {"data": task.data, "snapshot": self._snapshot(task)}
                for task in self.tasks.values()
            ],
        }
        encoded = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        if len(encoded) > MAX_HISTORY_FILE:
            raise TaskError("preview_history_full", 413)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_bytes(encoded)
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def create(self, raw: dict) -> dict:
        with self.lock:
            data = _validate(raw)
            was_present = data["request_id"] in self.by_request
            snapshot = super().create(raw)
            if was_present:
                return snapshot
            try:
                self._persist()
            except Exception:
                task_id = snapshot["task_id"]
                del self.tasks[task_id]
                del self.by_request[data["request_id"]]
                raise
            return snapshot

    def get(self, task_id: str) -> dict:
        with self.lock:
            snap = super().get(task_id)
            if snap["terminal"] and task_id not in self._saved_final:
                self._replayed[task_id] = deepcopy(snap)
                try:
                    self._persist()
                except Exception:
                    del self._replayed[task_id]
                    raise
                self._saved_final.add(task_id)
            return snap

    def cancel(self, task_id: str) -> dict:
        with self.lock:
            task = self._get_task(task_id)
            before = self._snapshot(task)
            if before["terminal"]:
                return before
            previous_cancelled = task.cancelled
            previous_elapsed = task.cancelled_elapsed
            after = super().cancel(task_id)
            self._replayed[task_id] = deepcopy(after)
            try:
                self._persist()
            except Exception:
                del self._replayed[task_id]
                task.cancelled = previous_cancelled
                task.cancelled_elapsed = previous_elapsed
                raise
            self._saved_final.add(task_id)
            return after

    def list(self) -> list[dict]:
        with self.lock:
            snapshots = [self._snapshot(task) for task in reversed(list(self.tasks.values()))]
            # Persist newly completed tasks so they survive a restart even when
            # the user viewed the list, rather than the single-task details.
            new_final = [(snap["task_id"], snap) for snap in snapshots
                         if snap["terminal"] and snap["task_id"] not in self._saved_final]
            if new_final:
                for task_id, snap in new_final:
                    self._replayed[task_id] = deepcopy(snap)
                try:
                    self._persist()
                except Exception:
                    for task_id, _ in new_final:
                        del self._replayed[task_id]
                    raise
                self._saved_final.update(task_id for task_id, _ in new_final)
            return snapshots


def local_history_path(script_path: Path) -> Path:
    return Path(script_path).with_name("mock_tasks.json")
