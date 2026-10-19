"""#5015 — one bounded, server-verified PC work context for new conversations."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.pc_work_context import (
    PcWorkContext,
    PcWorkDevice,
    render_pc_work_context,
    resolve_pc_work_context,
)


class _Source:
    configured = True

    def __init__(self, rows):
        self.rows = rows

    async def list_devices(self, *, owner_id, workspace_id, now):
        del owner_id, workspace_id, now
        return self.rows


def _request(rows):
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(
            claw_device_directory_source=_Source(rows),
        )),
    )


def _row(device_id, name, state="CONNECTED", usable=True, **extra):
    return {
        "deviceId": device_id, "deviceName": name, "state": state,
        "usable": usable, **extra,
    }


def test_single_connected_device_is_the_explicit_target():
    context = asyncio.run(resolve_pc_work_context(
        _request([_row("device-1", "Padiem-Command-Center")]),
        owner_id="usr_owner", workspace_id="ws-1",
    ))
    assert context.status == "ready"
    assert context.target_device_id == "device-1"
    text = render_pc_work_context(context)
    assert "Padiem-Command-Center" in text
    assert "온라인" in text
    assert "승인된 폴더 목록" in text


def test_two_usable_devices_are_never_silently_selected():
    context = asyncio.run(resolve_pc_work_context(
        _request([
            _row("device-1", "PC-A"), _row("device-2", "PC-B"),
        ]),
        owner_id="usr_owner", workspace_id="ws-1",
    ))
    assert context.target_device_id is None
    text = render_pc_work_context(context)
    assert "여러 대" in text and "임의로 하나를 고르지 말고" in text


def test_paused_and_offline_are_distinct_states():
    paused = asyncio.run(resolve_pc_work_context(
        _request([_row("device-1", "PC-A", usagePaused=True)]),
        owner_id="usr_owner", workspace_id="ws-1",
    ))
    assert paused.status == "paused"
    assert "일시중지" in render_pc_work_context(paused)

    offline = asyncio.run(resolve_pc_work_context(
        _request([_row("device-1", "PC-A", state="OFFLINE", usable=False)]),
        owner_id="usr_owner", workspace_id="ws-1",
    ))
    assert offline.status == "offline"
    assert "온라인 상태가 확인되지 않았습니다" in render_pc_work_context(offline)


def test_unverified_owner_and_unconfigured_source_fail_closed():
    unverified = asyncio.run(resolve_pc_work_context(
        _request([]), owner_id=None, workspace_id="ws-1",
    ))
    assert unverified.status == "unverified_owner"
    assert "확인하지 못해" in render_pc_work_context(unverified)

    no_source = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    unconfigured = asyncio.run(resolve_pc_work_context(
        no_source, owner_id="usr_owner", workspace_id="ws-1",
    ))
    assert unconfigured.status == "unconfigured"
    assert "확인하지 못했습니다" in render_pc_work_context(unconfigured)
