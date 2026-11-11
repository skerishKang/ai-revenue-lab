"""#7229 후속: state Worker HTTPS ingress가 P01 Engine의 Calendar 바인딩 조회를 허용하는지 고정.

P01 활성화 경로가 `select_calendar_binding`을 `/internal/rpc/select_calendar_binding`으로
호출한다(비공개 운영 기록(거버넌스 폴더, 같은 상대 경로), COM2_P01_CONTROL_PLANE_BINDINGS_20261109.md §2.2). 허용 목록에서
빠지면 P01은 계속 503으로 남는다. 반대로 티켓·리스·콜백류가 목록에 새어 나가면 안 된다.
구성 파일의 `secrets.required`에 ingress secret이 선언되어야 보존 검사가 HOLD 내지 않는다.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "google_oauth_worker.py"
STATE_CONFIG = ROOT / ("wrang" + "ler.google-oauth.jsonc")

ALLOWED = {
    "workspace_connector_state",
    "workspace_calendar_connector_state",
    "select_calendar_binding",
    "disconnect_calendar",
    "disconnect_gmail",
}

# 티켓·리스·콜백·Drive/B66 슬라이스는 HTTPS ingress로 열지 않는다(바인딩 전용 유지).
FORBIDDEN = {
    "begin_connect",
    "complete_callback",
    "issue_access_lease",
    "select_drive_binding",
    "disconnect_drive",
    "select_b66_drive_binding",
    "disconnect_b66_drive",
    "select_b66_drive_full_binding",
    "disconnect_b66_drive_full",
}


def test_ingress_allowlist_is_exactly_the_reviewed_methods() -> None:
    source = WORKER.read_text(encoding="utf-8")
    assert 'RPC_INGRESS_SECRET_BINDING = "PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET"' in source
    block = source.split("RPC_INGRESS_METHODS = frozenset({", 1)[1].split("})", 1)[0]
    listed = {line.strip().strip('",') for line in block.strip().splitlines()}
    assert listed == ALLOWED


def test_forbidden_methods_never_appear_in_the_ingress_block() -> None:
    source = WORKER.read_text(encoding="utf-8")
    block = source.split("RPC_INGRESS_METHODS = frozenset({", 1)[1].split("})", 1)[0]
    for name in FORBIDDEN:
        assert f'"{name}"' not in block


def test_state_config_declares_the_ingress_secret_as_required() -> None:
    config = json.loads(STATE_CONFIG.read_text(encoding="utf-8"))
    assert config["name"] == "padiem-google-oauth-state"
    required = set(config["secrets"]["required"])
    assert "PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET" in required
    # 기존 필수 시크릿이 사라지지 않았는지도 함께 고정한다.
    assert {
        "GOOGLE_CONNECT_TICKET_KEY",
        "GOOGLE_OAUTH_SEAL_KEY",
        "GOOGLE_OAUTH_CLIENT_SECRET",
    } <= required
