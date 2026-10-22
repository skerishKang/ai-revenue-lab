"""#3099 the Resident reads the Connector's local diagnostics for the heartbeat.

The Connector writes one bounded local file; this module reads it and turns
it into the hint the heartbeat already carries. These tests pin that a
missing, unreadable, foreign or unusable file is simply not reported - the
server then shows "확인 불가" instead of a fabricated state.
"""

from __future__ import annotations

import json

from kagent.pc_device_diagnostics import (
    LOCAL_DIAGNOSTICS_FILE_ENV,
    LOCAL_DIAGNOSTICS_VERSION,
    diagnostics_hint,
    normalize_local_checks,
    read_local_diagnostics,
)

READY = {"agent_source": "ready", "autostart": "enabled", "resident": "running"}


def _write(path, *, version=LOCAL_DIAGNOSTICS_VERSION, revision=1, checks=READY):
    path.write_text(
        json.dumps({"version": version, "revision": revision, "checks": checks}),
        encoding="utf-8",
    )
    return path


def test_the_resident_reads_the_file_the_connector_named(tmp_path):
    path = _write(tmp_path / "connector-diagnostics.json")
    environ = {LOCAL_DIAGNOSTICS_FILE_ENV: str(path)}
    diagnostics = read_local_diagnostics(environ)
    assert diagnostics is not None
    assert diagnostics["checks"] == READY
    assert diagnostics["revision"] == 1
    assert diagnostics["version"] == "padiem-pc-device-diagnostics.v1"


def test_a_missing_file_reports_nothing(tmp_path):
    environ = {LOCAL_DIAGNOSTICS_FILE_ENV: str(tmp_path / "missing.json")}
    assert read_local_diagnostics(environ) is None


def test_no_configured_file_reports_nothing():
    assert read_local_diagnostics({}) is None
    assert read_local_diagnostics({LOCAL_DIAGNOSTICS_FILE_ENV: "  "}) is None


def test_a_corrupt_or_foreign_file_reports_nothing(tmp_path):
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert read_local_diagnostics({LOCAL_DIAGNOSTICS_FILE_ENV: str(corrupt)}) is None
    foreign = _write(tmp_path / "foreign.json", version="other")
    assert read_local_diagnostics({LOCAL_DIAGNOSTICS_FILE_ENV: str(foreign)}) is None


def test_an_unusable_label_set_reports_nothing(tmp_path):
    partial = _write(tmp_path / "partial.json", checks={"agent_source": "ready"})
    assert read_local_diagnostics({LOCAL_DIAGNOSTICS_FILE_ENV: str(partial)}) is None
    unknown = _write(
        tmp_path / "unknown.json",
        checks={"agent_source": "deleted", "autostart": "enabled", "resident": "running"},
    )
    assert read_local_diagnostics({LOCAL_DIAGNOSTICS_FILE_ENV: str(unknown)}) is None


def test_the_hint_carries_only_the_bounded_shape(tmp_path):
    path = _write(tmp_path / "connector-diagnostics.json", revision=7)
    diagnostics = read_local_diagnostics({LOCAL_DIAGNOSTICS_FILE_ENV: str(path)})
    hint = diagnostics_hint(diagnostics)
    assert hint is not None
    assert set(hint) == {"version", "revision", "checks"}
    assert set(hint["checks"]) == {"agent_source", "autostart", "resident"}
    assert hint["revision"] == 7
    # Nothing from the local file but the three labels and the revision.
    assert "path" not in str(hint).lower()
    assert "/" not in str(hint)


def test_a_hint_is_never_built_from_an_unusable_source():
    assert diagnostics_hint(None) is None
    assert diagnostics_hint({"version": "other", "revision": 1}) is None
    assert diagnostics_hint({"checks": READY}) is None
    assert diagnostics_hint({"version": "padiem-pc-device-diagnostics.v1", "checks": READY}) is None


def test_the_local_label_vocabulary_is_closed():
    assert normalize_local_checks(READY) == READY
    assert normalize_local_checks({"agent_source": "ready"}) is None
    assert normalize_local_checks({**READY, "extra": 1}) is None
    assert normalize_local_checks(None) is None
