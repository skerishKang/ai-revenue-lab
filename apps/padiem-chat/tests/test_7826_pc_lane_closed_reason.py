"""#7826: a closed PC lane leaves a reason behind.

The PC lane is closed by ``resolve_chat_pc_stream_context`` returning ``None``.
That value is unchanged here — these tests pin only the *name* the resolver leaves
on the request so the existing turn timing line can carry it, and prove every
closing point has one. No device id, account value or address is asserted.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import app.chat_pc_drive as lane
import app.pc_work_context as pc_work_context
from app.orchestration_timing import OrchestrationTiming

DEVICE = "node/meshdomain1/owner-pc"
UID = "usr_7826"


def _run(coro):
    return asyncio.run(coro)


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace()),
        state=SimpleNamespace(),
        cookies={},
    )


def _owner(session=True, subject=True, workspace="tenant-1"):
    async def _resolve(request, uid):
        return (
            SimpleNamespace(session_id="sess_7826") if session else None,
            "usr_7826" if subject else None,
            workspace,
        )
    return _resolve


def _selection(status, device_id=None):
    async def _read(request, *, owner_id, workspace_id):
        return SimpleNamespace(status=status, device_id=device_id)
    return _read


def _context(**overrides):
    base = dict(
        broker_status="ready",
        devices=(pc_work_context.PcWorkDevice(DEVICE, None, "CONNECTED", True),),
        execution=pc_work_context.PcExecutionTarget(status="ready", device_id=DEVICE),
        mapping="confirmed",
        selected_device_id=None,
        saved_selection_status=pc_work_context.SAVED_SELECTION_NONE,
    )
    base.update(overrides)
    return pc_work_context.PcWorkContext(**base)


def _resolve(context):
    async def _resolve_context(request, **kwargs):
        return context
    return _resolve_context


def _grant(allowed=True):
    async def _check(request, session, *, device_id=None, owner_ref=None):
        return allowed
    return _check


def _call(monkeypatch, *, user_text="PC의 C:\\ 목록", requested_device_id=DEVICE,
          owner=None, selection=None, context=None, grant=None, links=()):
    monkeypatch.setattr(lane, "_resolve_chat_owner", owner or _owner())
    monkeypatch.setattr(lane, "_check_mesh_grant", grant or _grant())
    monkeypatch.setattr(pc_work_context, "read_saved_device_selection",
                        selection or _selection(pc_work_context.SAVED_SELECTION_NONE))
    monkeypatch.setattr(pc_work_context, "resolve_pc_work_context",
                        _resolve(context or _context()))
    monkeypatch.setattr(pc_work_context, "linked_pc_targets",
                        _links(links))

    async def _target(*args, **kwargs):
        return None, "unavailable"

    monkeypatch.setattr("app.oracle_mesh_read_return_routes._engine_pc_files_target",
                        _target)
    request = _request()
    result = _run(lane.resolve_chat_pc_stream_context(
        request, uid=UID, requested_device_id=requested_device_id,
        user_text=user_text,
    ))
    return result, getattr(request.state, "pc_lane_closed", None)


def _links(items):
    async def _read(request, uid):
        return list(items)
    return _read


def test_an_open_lane_records_no_reason(monkeypatch) -> None:
    result, closed = _call(monkeypatch, requested_device_id=None)
    assert result is not None
    assert closed is None


def test_an_unresolved_owner_is_named(monkeypatch) -> None:
    result, closed = _call(monkeypatch, owner=_owner(subject=False))
    assert result is None
    assert closed == lane.PC_LANE_SESSION_UNRESOLVED


def test_an_unreadable_saved_selection_is_named(monkeypatch) -> None:
    result, closed = _call(
        monkeypatch,
        selection=_selection(pc_work_context.SAVED_SELECTION_UNAVAILABLE),
    )
    assert result is None
    assert closed == lane.PC_LANE_SELECTION_UNREADABLE


def test_a_turn_that_names_no_pc_is_named(monkeypatch) -> None:
    result, closed = _call(monkeypatch, user_text="오늘 날씨 알려줘",
                           requested_device_id=None)
    assert result is None
    assert closed == lane.PC_LANE_TURN_NAMES_NO_PC


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # The five observations PcWorkContext.tool_available ANDs, one at a time.
        ({"execution": pc_work_context.PcExecutionTarget(status="no_target")},
         "tool_unavailable_execution_not_ready"),
        ({"saved_selection_status": pc_work_context.SAVED_SELECTION_UNAVAILABLE},
         "tool_unavailable_saved_selection_unavailable"),
        ({"selection_offline": True}, "tool_unavailable_selection_offline"),
        ({"broker_status": "paused"}, "tool_unavailable_broker_paused"),
        ({"mapping": "unknown"}, "tool_unavailable_mapping_unconfirmed"),
    ],
)
def test_each_tool_available_sub_condition_is_named(monkeypatch, overrides, expected) -> None:
    result, closed = _call(monkeypatch, context=_context(**overrides))
    assert result is None
    assert closed == lane.PC_LANE_TOOL_UNAVAILABLE_PREFIX + expected.split(
        "tool_unavailable_", 1)[1]


def test_a_selection_not_confirmed_by_the_mapping_is_named(monkeypatch) -> None:
    # A stored choice the directory does not confirm closes the lane; an unmapped
    # execution target alone still opens it, which is why mapping is the deciding
    # observation here and not the presence of a selection.
    result, closed = _call(
        monkeypatch,
        context=_context(selected_device_id=DEVICE, mapping="unmapped"),
    )
    assert result is None
    assert closed == lane.PC_LANE_SELECTION_UNCONFIRMED


def test_an_invalid_execution_identity_is_named(monkeypatch) -> None:
    result, closed = _call(
        monkeypatch,
        context=_context(execution=pc_work_context.PcExecutionTarget(
            status="ready", device_id="C:/Users/owner")),
    )
    assert result is None
    assert closed == lane.PC_LANE_DEVICE_IDENTITY_INVALID


def test_a_requested_device_mismatch_is_named(monkeypatch) -> None:
    result, closed = _call(monkeypatch, requested_device_id="node/meshdomain1/other")
    assert result is None
    assert closed == lane.PC_LANE_REQUESTED_DEVICE_MISMATCH


def test_a_refused_mesh_grant_is_named(monkeypatch) -> None:
    result, closed = _call(monkeypatch, grant=_grant(False))
    assert result is None
    assert closed == lane.PC_LANE_MESH_GRANT_UNAVAILABLE


def test_an_unreadable_authority_is_named(monkeypatch) -> None:
    async def _boom(*args, **kwargs):
        raise RuntimeError("authority down")

    monkeypatch.setattr(lane, "_resolve_chat_owner", _boom)
    request = _request()
    result = _run(lane.resolve_chat_pc_stream_context(
        request, uid=UID, requested_device_id=DEVICE, user_text="PC 목록"))
    assert result is None
    assert getattr(request.state, "pc_lane_closed", None) == lane.PC_LANE_AUTHORITY_UNREADABLE


def test_the_timing_line_carries_the_reason() -> None:
    timing = OrchestrationTiming()
    assert "pc_lane_closed=none" in timing.line()
    timing.set_pc_lane_closed(lane.PC_LANE_TURN_NAMES_NO_PC)
    assert "pc_lane_closed=turn_names_no_pc" in timing.line()


def test_the_timing_line_accepts_only_a_lower_case_name() -> None:
    timing = OrchestrationTiming()
    timing.set_pc_lane_closed("not a code")
    assert "pc_lane_closed=none" in timing.line()
    timing.set_pc_lane_closed("node/meshdomain1/owner-pc")
    assert "pc_lane_closed=none" in timing.line()
