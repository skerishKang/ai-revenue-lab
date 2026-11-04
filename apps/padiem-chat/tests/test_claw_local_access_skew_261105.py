"""261105: 메시 프레즌스의 장치 시각에 기기 시계 허용 오차를 둔다(#6875 시계 점검 후속).

observed_at은 장치 쪽 관측 시각이고 now는 Chat Worker의 시계다. 기기 시계가
몇 분 빨라도 ONLINE 투영이 통과해야 하고, 그 밖의 분명한 미래 값은 거절된다.
stale 판정과 바인딩 수명 검사는 그대로임을 확인한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kagent.contracts import ContractError
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle

from app.claw_local_access_source import MeshPresenceReceipt, project_mesh_online_binding

NOW = datetime(2026, 11, 5, 5, 30, tzinfo=timezone.utc)


def _binding() -> DeviceBinding:
    return DeviceBinding(
        device_id="device.1",
        binding_ref="pairing-binding." + "a" * 32,
        account_ref="account.1",
        workspace_ref="workspace.1",
        credential_ref="pairing-credential." + "a" * 32,
        credential_generation=1,
        issued_at=NOW - timedelta(minutes=1),
        credential_expires_at=NOW + timedelta(days=30),
        state=DeviceLifecycle.PAIRED_OFFLINE,
    )


def _presence(observed_at: datetime) -> MeshPresenceReceipt:
    return MeshPresenceReceipt(
        device_id="device.1",
        account_ref="account.1",
        credential_generation=1,
        observed_at=observed_at,
        connected=True,
        workspace_ref="workspace.1",
    )


def test_device_clock_ahead_within_device_skew_is_tolerated():
    online = project_mesh_online_binding(
        binding=_binding(),
        presence=_presence(NOW + timedelta(seconds=60)),
        now=NOW,
    )
    assert online.state == DeviceLifecycle.ONLINE


def test_device_clock_ahead_beyond_device_skew_is_refused():
    with pytest.raises(ContractError) as raised:
        project_mesh_online_binding(
            binding=_binding(),
            presence=_presence(NOW + timedelta(seconds=301)),
            now=NOW,
        )
    assert "cannot be in the future" in str(raised.value)
