"""#3099 the Broker stores the device's local diagnostic hint.

These exercise the real durable runtime against a SQLite-backed Durable
Object adapter; no client flag is ever an authority. The store keeps the
hint next to the canonical Broker state and decides freshness with the
server's own clock.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from test_local_agent_broker_enqueue_material_atomicity import (
    _runtime, _register_and_open,
)

#: The store decides freshness with the server's own clock, so the tests
#: use the real current time rather than a fixed base date.
NOW = datetime.now(timezone.utc)

DEVICE = "device.atomic.1"
OTHER_DEVICE = "device.atomic.2"
ACCOUNT = "account.atomic.1"
WORKSPACE = "workspace.atomic.1"

HINT = {
    "version": "padiem-pc-device-diagnostics.v1",
    "revision": 3,
    "checks": {"agent_source": "not_installed", "autostart": "disabled", "resident": "stopped"},
}


def _record(runtime, *, hint, device_id=DEVICE, at=NOW):
    return runtime.record_device_diagnostics(
        device_id=device_id,
        account_ref=ACCOUNT,
        workspace_ref=WORKSPACE,
        hint=hint,
        observed_at=at.isoformat(),
    )


def test_a_hint_is_stored_and_projected_for_its_own_device(tmp_path):
    runtime = _runtime(tmp_path / "diagnostics.sqlite3")
    _register_and_open(runtime)
    assert _record(runtime, hint=HINT)["ok"] is True
    stored = runtime.diagnostics_store.hint_for(DEVICE)
    assert stored["status"] == "reported"
    assert stored["device_id"] == DEVICE
    assert stored["checks"]["agent_source"] == "not_installed"


def test_a_device_that_never_reported_is_unavailable(tmp_path):
    runtime = _runtime(tmp_path / "diagnostics.sqlite3")
    _register_and_open(runtime)
    stored = runtime.diagnostics_store.hint_for(DEVICE)
    assert stored["status"] == "unavailable"
    assert stored["checks"] == {}


def test_a_hint_is_never_stored_under_another_device(tmp_path):
    runtime = _runtime(tmp_path / "diagnostics.sqlite3")
    _register_and_open(runtime)
    _record(runtime, hint=HINT, device_id=OTHER_DEVICE)
    assert runtime.diagnostics_store.hint_for(DEVICE)["status"] == "unavailable"
    assert runtime.diagnostics_store.hint_for(OTHER_DEVICE)["status"] == "reported"


def test_an_observation_that_stopped_advancing_becomes_stale(tmp_path):
    runtime = _runtime(tmp_path / "diagnostics.sqlite3")
    _register_and_open(runtime)
    _record(runtime, hint=HINT)
    # The same revision seen again keeps the labels but grows the age, so the
    # surface stops presenting it as current.
    _record(runtime, hint=HINT, at=NOW + timedelta(seconds=60))
    assert runtime.diagnostics_store.hint_for(DEVICE)["status"] == "reported"
    late = NOW - timedelta(seconds=60 * 60)
    _record(runtime, hint=HINT, at=late)
    stored = runtime.diagnostics_store.hint_for(DEVICE)
    assert stored["status"] == "stale"
    # The values stay available to the server but are never shown as current.
    assert stored["checks"]["agent_source"] == "not_installed"


def test_a_rolled_back_observation_is_refused(tmp_path):
    runtime = _runtime(tmp_path / "diagnostics.sqlite3")
    _register_and_open(runtime)
    _record(runtime, hint={**HINT, "revision": 9})
    refused = _record(runtime, hint={**HINT, "revision": 2})
    assert refused["ok"] is False
    assert refused["error"]["code"] == "device_diagnostics_revision_rollback"
    assert runtime.diagnostics_store.hint_for(DEVICE)["checks"]["agent_source"] == "not_installed"


def test_an_unusable_hint_is_refused_and_changes_nothing(tmp_path):
    runtime = _runtime(tmp_path / "diagnostics.sqlite3")
    _register_and_open(runtime)
    for hint in (
        None,
        {},
        {"version": "other", "revision": 1, "checks": HINT["checks"]},
        {**HINT, "checks": {"agent_source": "deleted", "autostart": "enabled", "resident": "running"}},
        {**HINT, "checks": {"agent_source": "ready"}},
        {**HINT, "revision": -1},
        {**HINT, "extra": 1},
    ):
        assert _record(runtime, hint=hint)["ok"] is False, hint
    assert runtime.diagnostics_store.hint_for(DEVICE)["status"] == "unavailable"


def test_the_hint_never_touches_the_canonical_device_state(tmp_path):
    """The hint is display only: the canonical state is unchanged."""
    runtime = _runtime(tmp_path / "diagnostics.sqlite3")
    _register_and_open(runtime)
    before = runtime.device_directory({"account_ref": ACCOUNT, "workspace_ref": WORKSPACE})
    _record(runtime, hint=HINT)
    after = runtime.device_directory({"account_ref": ACCOUNT, "workspace_ref": WORKSPACE})
    for row in before["devices"]:
        for key in ("canonical_state", "binding", "session", "heartbeat_last_seen_at"):
            assert row[key] == after["devices"][0][key], key
    assert after["devices"][0]["device_diagnostics"]["status"] == "reported"
