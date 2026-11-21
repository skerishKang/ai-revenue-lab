from datetime import datetime, timedelta, timezone

import pytest

from app.pc_helper_update_policy import update_view, version_parts

NOW = datetime(2026, 11, 21, tzinfo=timezone.utc)
DEVICE = "node//testpc"
MANIFEST = {
    "version": "0.4.0", "min_supported_version": "0.3.0-rc1", "sha256": "a" * 64,
}


def row(version, *, received=NOW, digest="b" * 64, device=DEVICE):
    return {"device_id": device, "received_at": received.isoformat(),
            "helper_version": version, "helper_sha256": digest}


@pytest.mark.parametrize(("version", "available", "required"), [
    ("0.2.9", True, True), ("0.3.0-rc1", True, False),
    ("0.4.0-rc2", True, False), ("0.4.0", False, False),
    ("0.5.0", False, False),
])
def test_observed_version_policy(version, available, required):
    result = update_view(row(version), MANIFEST, device_id=DEVICE, now=NOW)
    assert result == {"helper_version": version, "latest_version": "0.4.0",
                      "update_available": available, "update_required": required}


@pytest.mark.parametrize("observation", [
    None, row("0.2.0", device="node//another"),
    row("0.2.0", received=NOW - timedelta(seconds=181)),
    row("0.2.0", received=NOW + timedelta(seconds=1)),
    row("unknown"),
])
def test_uncertain_version_does_not_invent_an_update_requirement(observation):
    assert update_view(observation, MANIFEST, device_id=DEVICE, now=NOW) == {
        "helper_version": None, "latest_version": None,
        "update_available": False, "update_required": False,
    }


def test_matching_release_digest_identifies_current_build():
    result = update_view(row(None, digest=MANIFEST["sha256"]), MANIFEST,
                         device_id=DEVICE, now=NOW)
    assert result["helper_version"] == MANIFEST["version"]
    assert not result["update_available"]
    assert not result["update_required"]


def test_version_order_matches_windows_updater():
    assert version_parts("0.3.0-rc2") < version_parts("0.3.0-rc10") < version_parts("0.3.0")
    assert version_parts("0.10.0") > version_parts("0.9.0")
    assert version_parts("0.3.0-beta") is None
