"""R7-7 claw_general_execute 4/4b 증거 시험 (#7814).

리팩터 전 origin/main(6b571b62d) blob에서 옮긴 구간(소유자/드라이브 정리·
카탈로그·run/claim·근거·staging·문맥 조립· Engine 실행 후 기록/응답)의
반환 경로와 정상 입력을 끝까지 고정한다. 정상 2개는 SSE 이벤트 끝까지,
Engine 호출 인자, 기록 행을 비교한다. 가짜 값만 쓴다.

골든 출처: `git show origin/main:apps/padiem-chat/app/claw_general_routes.py`
의 해당 구간을 그대로 실행해 생성했다.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

from app import claw_general_routes as g
from app import claw_memory_routes
import test_7814_claw_general_tail_table as tail

GOLDEN_PATH = (
    Path(__file__).resolve().parent
    / "test_7814_claw_general_dispatch_table_golden.json"
)
PRE_REFACTOR_ORIGIN_MAIN = "6b571b62d5315acd38a31cc9e52925295dc2dfa6"


def _outcome(*, status="completed", answer="P01 결과"):
    return SimpleNamespace(
        projection=SimpleNamespace(status=SimpleNamespace(value=status)),
        answer=answer,
        p01_event_history=(),
        p01_run_id="p01_tail",
        selected_route_id=None,
        provider_attempt_count=None,
        fallback_used=None,
    )


def _catalog(monkeypatch, mode):
    async def ok():
        return [{"model_id": "model.fixture"}]

    async def other():
        return [{"model_id": "other.model"}]

    async def bad():
        return "not-a-roster"

    def start(request, model_id):
        del request, model_id
        if mode == "unavailable":
            return None, True
        if mode == "none":
            return None, False
        coro = {"ok": ok, "not_eligible": other, "bad": bad}[mode]()
        return asyncio.get_running_loop().create_task(coro), False

    monkeypatch.setattr(g, "_start_selectable_model_read", start)


def _pc_branch(monkeypatch, *, staged=False):
    async def fake(request, data, user_text, attachment_conflict):
        del request, data, user_text, attachment_conflict
        return None, {
            "initial_pc_capture": staged,
            "desktop_task_requested": False,
            "desktop_device_id": None,
            "requested_device_id": None,
            "pc_browser_requested": False,
            "pc_browser_device_id": None,
            "pc_files_requested": False,
            "pc_files_device_id": None,
            "initial_pc_drive_query": False,
        }

    monkeypatch.setattr(g, "_claw_general_pc_branch", fake)


class _History:
    async def record_txt_pending_run(self, **kwargs):
        return "conv_staged_fixture"


def _setup(monkeypatch, calls, *, catalog="none", staged=False,
           workspace="ws_fixture", outcome=None, evidence=False):
    adapter = tail._adapter(calls, outcome=outcome or _outcome())
    request = tail._setup(monkeypatch, calls, adapter=adapter, evidence=evidence)
    _catalog(monkeypatch, catalog)
    _pc_branch(monkeypatch, staged=staged)
    if staged:
        request.app.state.history_store = _History()

        async def resolve(request_arg, uid):
            calls.append(["resolve_workspace", uid])
            return workspace

        monkeypatch.setattr(claw_memory_routes, "_resolve_memory_workspace", resolve)
    return request


CASES = [
    ("catalog_unavailable", {"catalog": "unavailable"}),
    ("model_not_available", {"catalog": "not_eligible"}),
    ("staging_workspace_unavailable", {"staged": True, "workspace": None}),
    ("approval_required", {"outcome": _outcome(status="waiting_approval", answer=None)}),
    ("incomplete_outcome", {"outcome": _outcome(status="completed", answer=None)}),
    ("normal_p01", {}),
    ("normal_p01_evidence", {"evidence": True}),
    ("normal_pc_staged", {"staged": True}),
]


def _golden():
    if not GOLDEN_PATH.exists():
        return {"cases": [], "origin_main": PRE_REFACTOR_ORIGIN_MAIN}
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _write_golden(document):
    GOLDEN_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")


def test_dispatch_table_parseable():
    golden = _golden()
    assert golden.get("origin_main") == PRE_REFACTOR_ORIGIN_MAIN
    if os.environ.get("UPDATE_7814_DISPATCH_GOLDEN") == "1":
        return
    assert [c["name"] for c in golden["cases"]] == [c[0] for c in CASES]


def test_dispatch_table_is_identical_to_golden(monkeypatch):
    golden = {c["name"]: c for c in _golden()["cases"]}
    for name, kwargs in CASES:
        calls = []
        request = _setup(monkeypatch, calls, **kwargs)
        response = tail._run(g.claw_general_execute(request))
        got = json.loads(json.dumps(
            {"name": name, "resp": tail._resp(response), "calls": calls},
            ensure_ascii=False,
        ))
        if os.environ.get("UPDATE_7814_DISPATCH_GOLDEN") == "1":
            golden[name] = got
            continue
        assert got == golden[name], name
    if os.environ.get("UPDATE_7814_DISPATCH_GOLDEN") == "1":
        document = _golden()
        document["cases"] = [golden[name] for name, _ in CASES]
        _write_golden(document)
