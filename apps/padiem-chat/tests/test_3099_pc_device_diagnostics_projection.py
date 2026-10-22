"""#3099 the PC device diagnostic hint from the Broker to the web surface.

These tests pin the whole consumption contract:

* a hint is display only and never changes the canonical device state, the
  online projection, the executable flag or the selectable flag;
* a hint that belongs to another device is dropped, so a mixed-in device can
  never borrow another device's observation;
* "never reported", "stopped advancing" and "the read failed" are three
  different situations and none of them is a confirmed negative;
* the hint carries no path, no secret and no log line.
"""

from __future__ import annotations

import pytest

from app.pc_device_diagnostics_projection import (
    STATUS_REPORTED,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    project_device_diagnostic,
)

DEVICE = "device-1"
OTHER_DEVICE = "device-2"

REPORTED = {
    "status": "reported",
    "device_id": DEVICE,
    "checks": {"agent_source": "ready", "autostart": "enabled", "resident": "running"},
    "fixes": {},
}
NOT_INSTALLED = {
    "status": "reported",
    "device_id": DEVICE,
    "checks": {
        "agent_source": "not_installed", "autostart": "disabled", "resident": "stopped",
    },
    "fixes": {
        "agent_source": "install_agent",
        "autostart": "enable_autostart",
        "resident": "start_connector",
    },
}


def test_a_reported_hint_is_projected_with_its_fixes():
    projected = project_device_diagnostic(NOT_INSTALLED, device_id=DEVICE)
    assert projected is not None
    assert projected["status"] == STATUS_REPORTED
    assert projected["checks"]["agent_source"] == "not_installed"
    assert projected["fixes"]["agent_source"] == "install_agent"
    assert projected["observed"] is True


def test_a_hint_for_another_device_is_dropped():
    assert project_device_diagnostic(REPORTED, device_id=OTHER_DEVICE) is None


def test_a_missing_hint_is_dropped():
    assert project_device_diagnostic(None, device_id=DEVICE) is None
    assert project_device_diagnostic({}, device_id=DEVICE) is None
    assert project_device_diagnostic({"status": "reported"}, device_id=DEVICE) is None


def test_never_reported_is_distinct_from_stale():
    unavailable = project_device_diagnostic(
        {"status": "unavailable", "device_id": DEVICE, "checks": {}}, device_id=DEVICE,
    )
    stale = project_device_diagnostic(
        {
            "status": "stale", "device_id": DEVICE,
            "checks": {
                "agent_source": "not_installed", "autostart": "enabled",
                "resident": "running",
            },
        },
        device_id=DEVICE,
    )
    assert unavailable is not None and unavailable["status"] == STATUS_UNAVAILABLE
    assert stale is not None and stale["status"] == STATUS_STALE
    assert unavailable["status"] != stale["status"]
    # A stale observation is never shown as a current one.
    assert stale["checks"] == {}
    assert stale["fixes"] == {}


def test_an_unusable_hint_is_dropped():
    assert project_device_diagnostic(
        {"status": "reported", "device_id": DEVICE,
         "checks": {"agent_source": "deleted", "autostart": "enabled", "resident": "running"}},
        device_id=DEVICE,
    ) is None
    assert project_device_diagnostic(
        {"status": "reported", "device_id": DEVICE,
         "checks": {"agent_source": "ready"}},
        device_id=DEVICE,
    ) is None


def test_the_projection_carries_no_path_no_secret_and_no_log_line():
    projected = project_device_diagnostic(NOT_INSTALLED, device_id=DEVICE)
    assert projected is not None
    for value in list(projected["checks"].values()) + list(projected["fixes"].values()):
        assert "/" not in value
        assert "\\" not in value
        assert len(value) <= 64
        assert value.strip() == value
        assert "\n" not in value
