"""Connector version compatibility — judgment wiring into the Claw display.

Covers the display half of the connector 0.3.0-rc1 rollout prep:

* the G4 translation produces the ``UPDATE_AVAILABLE`` /
  ``UPDATE_REQUIRED`` presentation variants only for a genuinely usable
  CONNECTED device whose connector version was reported and judged;
* the real local-access route feeds the judgment from the projected
  ``client_version`` with the deployment env thresholds;
* the device-directory row helpers turn a (future) trusted ``clientVersion``
  into the two notice-worthy compatibility values only;
* the web modules mirror the vocabulary and the copy in both locales.

Nothing here blocks a device: every unknown/unreported version keeps today's
exact projection (no variant, no notice, same usable state).
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_device_directory_routes import _client_version, _row_compatibility
from app.claw_local_access_routes import CLAW_LOCAL_ACCESS_PATH
from app.claw_local_projection import (
    WEB_PRESENTATION_VARIANTS,
    WEB_STATE_CONNECTED,
    translate_device_lifecycle,
)
from app.config import Settings
from app.main import create_app
from kagent.connections_center import DeviceCompatibility
from kagent.connector_version_compat import (
    CONNECTOR_MINIMUM_VERSION_ENV,
    DEFAULT_CONNECTOR_LATEST_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
HANDOFF_PATH = STATIC / "claw-local-handoff.js"
LOCALE_PATH = STATIC / "locale.js"
DEVICE_MANAGER_PATH = STATIC / "claw-device-manager.js"

BASE_URL = "https://chat.example.test"
USER_ID = "usr_version_compat_owner"
CONVERSATION_ID = "conv_version_compat_01"
# Test-only fixture value; never a deployed credential.
SESSION_SECRET = "connector-version-compat-display-fixture-0123456789abcdef"

DESKTOP_HANDOFF = "padiem://local-handoff/version-compat-opaque-token"


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class ProjectionSource:
    """Stand-in for the #3080 composition with an optional client_version."""

    configured = True

    def __init__(self, *, result: dict[str, Any] | None = None):
        self.calls: list[dict[str, Any]] = []
        self.result: dict[str, Any] = {
            "requires_local_access": True,
            "required_capabilities": ["local_computer"],
            "desktop_installed": True,
            "canonical_state": "online",
            "device_name": "VersionCompat-PC",
            "platform": "windows",
            "handoff_value": DESKTOP_HANDOFF,
            "run_id": None,
            "task_id": None,
        }
        if result is not None:
            self.result.update(result)

    async def project_local_access(self, *, owner_id: str, conversation_id: str, now: Any) -> Any:
        self.calls.append({"owner_id": owner_id, "conversation_id": conversation_id})
        return dict(self.result)


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def _get(source: ProjectionSource) -> dict[str, Any]:
    """One owner-scoped request; returns the projected device shape."""

    settings = _settings()
    app = create_app(settings, history_store=MagicMock())
    app.state.claw_local_access_source = source

    async def run() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            client.cookies.set(SESSION_COOKIE, create_session_token(settings, USER_ID))
            return await client.get(
                CLAW_LOCAL_ACCESS_PATH, params={"conversationId": CONVERSATION_ID}
            )

    response = asyncio.run(run())
    assert response.status_code == 200
    body = response.json()
    assert body.get("ok") is True and body.get("available") is True
    return body["projection"]["device"]


def _run_node(script: str) -> str:
    completed = subprocess.run(
        ["node"], input=script, check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


def _handoff_harness(body: str) -> str:
    module = HANDOFF_PATH.read_text(encoding="utf-8")
    return (
        "global.window = globalThis;\n"
        + module
        + "\nconst H = global.window.PadiemClawLocalHandoff;\n"
        + body
    )


# ---------------------------------------------------------------------------
# 1. G4 translation: compatibility -> presentation variant
# ---------------------------------------------------------------------------


def test_connected_device_with_update_available_gets_the_new_notice_variant() -> None:
    projected = translate_device_lifecycle(
        "online", compatibility="update_available",
    )
    assert projected["state"] == WEB_STATE_CONNECTED
    assert projected["usable"] is True
    assert projected["variant"] == "UPDATE_AVAILABLE"


def test_connected_device_with_update_required_keeps_the_existing_path() -> None:
    projected = translate_device_lifecycle(
        "online", compatibility="update_required",
    )
    assert projected["state"] == WEB_STATE_CONNECTED
    assert projected["usable"] is True
    assert projected["variant"] == "UPDATE_REQUIRED"


def test_current_or_unknown_compatibility_produces_no_variant() -> None:
    for compatibility in ("current", "unknown", "garbage", None, 7):
        projected = translate_device_lifecycle("online", compatibility=compatibility)
        assert projected["variant"] is None


def test_compatibility_accepts_the_contract_enum_and_its_string_value() -> None:
    for value in (DeviceCompatibility.UPDATE_AVAILABLE, "update_available"):
        assert translate_device_lifecycle("online", compatibility=value)["variant"] == (
            "UPDATE_AVAILABLE"
        )
    for value in (DeviceCompatibility.UPDATE_REQUIRED, "update_required"):
        assert translate_device_lifecycle("online", compatibility=value)["variant"] == (
            "UPDATE_REQUIRED"
        )


@pytest.mark.parametrize(
    "state", ["paired_offline", "credential_expired", "revoked", "unpaired", "not_a_state"],
)
def test_non_connected_devices_never_carry_a_variant(state: str) -> None:
    projected = translate_device_lifecycle(state, compatibility="update_available")
    assert projected["state"] != WEB_STATE_CONNECTED
    assert projected["usable"] is False
    assert projected["variant"] is None


def test_web_presentation_variants_mirror_the_js_module() -> None:
    source = HANDOFF_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"PRESENTATION_VARIANTS = Object\.freeze\(\[([^\]]*)\]\)", source,
    )
    assert match is not None
    declared = tuple(item.strip().strip('"') for item in match.group(1).split(","))
    assert declared == WEB_PRESENTATION_VARIANTS
    assert WEB_PRESENTATION_VARIANTS == ("UPDATE_REQUIRED", "UPDATE_AVAILABLE")


# ---------------------------------------------------------------------------
# 2. Route wiring: projected client_version + env thresholds
# ---------------------------------------------------------------------------


def test_old_version_online_device_shows_the_update_available_notice() -> None:
    device = _get(ProjectionSource(result={"client_version": "0.2.0"}))
    assert device["state"] == WEB_STATE_CONNECTED
    assert device["usable"] is True
    assert device["variant"] == "UPDATE_AVAILABLE"


def test_current_version_online_device_shows_no_variant() -> None:
    device = _get(ProjectionSource(result={"client_version": DEFAULT_CONNECTOR_LATEST_VERSION}))
    assert device["state"] == WEB_STATE_CONNECTED
    assert device["usable"] is True
    assert device["variant"] is None


def test_unreported_version_keeps_todays_projection_exactly() -> None:
    for result in ({}, {"client_version": "unknown"}, {"client_version": None}):
        device = _get(ProjectionSource(result=result))
        assert device["state"] == WEB_STATE_CONNECTED
        assert device["usable"] is True
        assert device["variant"] is None


def test_minimum_env_labels_a_below_minimum_device_update_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CONNECTOR_MINIMUM_VERSION_ENV, "0.2.0")
    device = _get(ProjectionSource(result={"client_version": "0.1.0"}))
    # Non-blocking by contract: the device stays connected and usable.
    assert device["state"] == WEB_STATE_CONNECTED
    assert device["usable"] is True
    assert device["variant"] == "UPDATE_REQUIRED"


def test_offline_old_version_device_never_carries_a_variant() -> None:
    device = _get(
        ProjectionSource(result={
            "canonical_state": "paired_offline", "client_version": "0.1.0",
        })
    )
    assert device["state"] == "OFFLINE"
    assert device["usable"] is False
    assert device["variant"] is None


# ---------------------------------------------------------------------------
# 3. Device-directory row helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.2.0", "0.2.0"),
        ("0.3.0-rc1", "0.3.0-rc1"),
        ("  1.2.3  ", "1.2.3"),
        ("unknown", "unknown"),
        ("v1.0.0", "v1.0.0"),
        ("0 2 0", None),
        ("0.2.0;drop", None),
        ("a" * 33, None),
        (None, None),
        (7, None),
    ],
)
def test_client_version_shape_guard(value: Any, expected: str | None) -> None:
    # Shape guard only: a shape-valid but unparseable value ("v1.0.0",
    # "unknown") flows on and the judgment — not this guard — calls it unknown.
    assert _client_version(value) == expected


def test_row_compatibility_default_env_only_flags_old_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PADIEM_CONNECTOR_LATEST_VERSION", raising=False)
    monkeypatch.delenv(CONNECTOR_MINIMUM_VERSION_ENV, raising=False)
    assert _row_compatibility("0.2.0") == "update_available"
    assert _row_compatibility("0.1.1-rc2") == "update_available"
    # The prepared release itself and anything newer stay silent.
    assert _row_compatibility("0.3.0-rc1") is None
    assert _row_compatibility("0.4.0") is None
    # Unknown/unparseable never becomes a row notice.
    assert _row_compatibility(None) is None
    assert _row_compatibility("garbage") is None


def test_row_compatibility_honours_the_owner_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PADIEM_CONNECTOR_LATEST_VERSION", raising=False)
    monkeypatch.setenv(CONNECTOR_MINIMUM_VERSION_ENV, "0.2.0")
    assert _row_compatibility("0.1.0") == "update_required"
    assert _row_compatibility("0.2.0") == "update_available"


# ---------------------------------------------------------------------------
# 4. Web modules mirror the vocabulary and the copy
# ---------------------------------------------------------------------------


def test_handoff_js_honours_the_new_variant_only_when_connected() -> None:
    out = _run_node(
        _handoff_harness(
            "const rows = ["
            " H.normalizeDeviceProjection({state: 'CONNECTED', usable: true, variant: 'UPDATE_AVAILABLE'}),"
            " H.normalizeDeviceProjection({state: 'OFFLINE', usable: false, variant: 'UPDATE_AVAILABLE'}),"
            " H.normalizeDeviceProjection({state: 'CONNECTED', usable: true, variant: 'MADE_UP'})"
            "].map((d) => ({state: d.state, usable: d.usable, variant: d.variant}));"
            "console.log(JSON.stringify(rows));"
        )
    )
    rows = json.loads(out)
    assert rows[0] == {"state": "CONNECTED", "usable": True, "variant": "UPDATE_AVAILABLE"}
    assert rows[1]["variant"] is None
    assert rows[2]["variant"] is None


def test_handoff_js_state_copy_in_both_locales() -> None:
    out = _run_node(
        _handoff_harness(
            "const m = H.deriveHandoffViewModel({conversationId: 'c1', requiresLocalAccess: true,"
            " desktopInstalled: true, device: {state: 'CONNECTED', usable: true,"
            " variant: 'UPDATE_AVAILABLE'}, handoff: {kind: 'deep_link', value: 'v'}});"
            "console.log(JSON.stringify({ko: H.deviceStateLabel(m, 'ko'),"
            " en: H.deviceStateLabel(m, 'en'),"
            " requiredKo: H.deviceStateLabel("
            "   {...m, device: {...m.device, variant: 'UPDATE_REQUIRED'}}, 'ko'),"
            " requiredEn: H.deviceStateLabel("
            "   {...m, device: {...m.device, variant: 'UPDATE_REQUIRED'}}, 'en')}));"
        )
    )
    labels = json.loads(out)
    assert labels["ko"] == "새 버전이 있어요."
    assert labels["en"] == "A new version is available."
    assert labels["requiredKo"] == "업데이트가 필요합니다."
    assert labels["requiredEn"] == "An update is needed."


def test_locale_dictionary_declares_the_new_key_in_both_languages() -> None:
    source = LOCALE_PATH.read_text(encoding="utf-8")
    assert source.count('"claw-local-state-update_available"') == 2
    assert source.count('"claw-local-state-update_required"') == 2


def test_device_manager_declares_the_notice_copy_and_branch() -> None:
    source = DEVICE_MANAGER_PATH.read_text(encoding="utf-8")
    # Both locales carry both notices.
    for key in ("updateAvailable", "updateRequired"):
        assert len(re.findall(rf"\b{key}: \"", source)) == 2, key
    assert "새 버전이 있어요" in source
    assert "업데이트가 필요합니다" in source
    # The row branch is presentation-only and driven by the server judgment.
    assert 'device.compatibility === "update_available"' in source
    assert 'device.compatibility === "update_required"' in source
    assert "claw-device-manager-version" in source
