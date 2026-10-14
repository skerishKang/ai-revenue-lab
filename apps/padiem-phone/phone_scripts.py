"""Local-only script library for the phone-task mock preview.

No customer authentication or telephony adapter is present. This store is not
for real customer records; a user-local file keeps fictitious templates across
preview restarts, outside the Git worktree.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import RLock
from uuid import uuid4
import json
import os
import re

from phone_mock import TaskError

SAMPLE_SCRIPTS = (
    {
        "script_id": "sample-general",
        "title": "일반 문의",
        "destination": "고객센터 (가상)",
        "goal": "이용 내역을 확인하고 필요한 절차를 알려줘.",
        "questions": "필요 서류와 신청 절차는 무엇인가요?",
        "notes": "개인정보 확인이나 유료 계약 변경은 진행하지 않습니다.",
        "revision": 1,
        "built_in": True,
    },
    {
        "script_id": "sample-vendor",
        "title": "거래처 확인",
        "destination": "거래처 (가상)",
        "goal": "현재 주문 건의 진행 상태와 예상 완료 시점을 확인해 줘.",
        "questions": "현재 진행 단계와 예상 완료일은 언제인가요?",
        "notes": "추가 발주나 계약 변경은 하지 않습니다.",
        "revision": 1,
        "built_in": True,
    },
    {
        "script_id": "sample-booking",
        "title": "예약 문의",
        "destination": "예약센터 (가상)",
        "goal": "예약 가능한 시간과 필요한 준비 사항을 확인해 줘.",
        "questions": "가능한 날짜와 준비 사항을 확인해 주세요.",
        "notes": "예약 확정이나 결제는 진행하지 않습니다.",
        "revision": 1,
        "built_in": True,
    },
)
IDENTIFIER = re.compile(r"^custom-[0-9a-f]{32}$")
FIELD_LIMITS = {"title": (2, 80), "destination": (2, 80), "goal": (3, 300),
                "questions": (0, 400), "notes": (0, 400)}
MAX_SCRIPTS = 40
MAX_FILE_BYTES = 65536


def _validated(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise TaskError("invalid_script")
    data = {}
    for key, (low, high) in FIELD_LIMITS.items():
        value = raw.get(key, "" if low == 0 else None)
        if not isinstance(value, str) or not low <= len(value.strip()) <= high:
            raise TaskError("invalid_script_" + key)
        if any(ord(char) < 32 for char in value):
            raise TaskError("invalid_script_text")
        data[key] = value.strip()
    return data


class ScriptStore:
    """Thread-safe custom scripts; built-ins are immutable defaults."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path is not None else None
        self.lock = RLock()
        self.custom: dict[str, dict] = {}
        if self.path is not None and self.path.exists():
            if self.path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("script_store_too_large")
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("scripts"), list):
                raise ValueError("invalid_script_store")
            for value in raw["scripts"]:
                if not isinstance(value, dict) or not isinstance(value.get("script_id"), str) or not IDENTIFIER.fullmatch(value["script_id"]):
                    raise ValueError("invalid_script_store_id")
                validated = _validated(value)
                version = value.get("revision")
                if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                    raise ValueError("invalid_script_store_revision")
                script_id = value["script_id"]
                if script_id in self.custom:
                    raise ValueError("duplicate_script_id")
                self.custom[script_id] = {**validated, "script_id": script_id, "revision": version, "built_in": False}
            if len(self.custom) > MAX_SCRIPTS:
                raise ValueError("script_store_over_capacity")

    def _persist(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps({"version": 1, "scripts": list(self.custom.values())}, ensure_ascii=False, indent=2)
        if len(serialized.encode("utf-8")) > MAX_FILE_BYTES:
            raise TaskError("script_store_full", 413)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(serialized, encoding="utf-8")
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()

    def list(self) -> list[dict]:
        with self.lock:
            return deepcopy([*SAMPLE_SCRIPTS, *self.custom.values()])

    def _get(self, script_id: str) -> dict:
        script = self.custom.get(script_id)
        if script is None:
            raise TaskError("script_not_found", 404)
        return script

    def resolve(self, script_id: str) -> dict:
        with self.lock:
            for built_in in SAMPLE_SCRIPTS:
                if script_id == built_in["script_id"]:
                    return deepcopy(built_in)
            return deepcopy(self._get(script_id))

    def create(self, raw: object) -> dict:
        validated = _validated(raw)
        with self.lock:
            if len(self.custom) >= MAX_SCRIPTS:
                raise TaskError("script_capacity_reached", 429)
            script_id = "custom-" + uuid4().hex
            script = {**validated, "script_id": script_id, "revision": 1, "built_in": False}
            self.custom[script_id] = script
            try:
                self._persist()
            except Exception:
                del self.custom[script_id]
                raise
            return deepcopy(script)

    def update(self, script_id: str, raw: object) -> dict:
        validated = _validated(raw)
        if not isinstance(raw, dict) or not isinstance(raw.get("revision"), int) or isinstance(raw.get("revision"), bool):
            raise TaskError("invalid_script_revision")
        with self.lock:
            old = self._get(script_id)
            if old["revision"] != raw["revision"]:
                raise TaskError("script_revision_conflict", 409)
            script = {**validated, "script_id": script_id, "revision": old["revision"] + 1, "built_in": False}
            self.custom[script_id] = script
            try:
                self._persist()
            except Exception:
                self.custom[script_id] = old
                raise
            return deepcopy(script)

    def delete(self, script_id: str, revision: object) -> dict:
        if not isinstance(revision, int) or isinstance(revision, bool):
            raise TaskError("invalid_script_revision")
        with self.lock:
            old = self._get(script_id)
            if old["revision"] != revision:
                raise TaskError("script_revision_conflict", 409)
            del self.custom[script_id]
            try:
                self._persist()
            except Exception:
                self.custom[script_id] = old
                raise
            return {"deleted": True, "script_id": script_id}


def local_preview_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".local" / "share") / "PadiemPhonePreview" / "scripts.json"
