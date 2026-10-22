"""#3099 the Connector's bounded local diagnostics file.

The Connector writes one small file into its own state directory and the
Resident picks it up for the heartbeat it already sends. These tests pin the
Connector side: the file carries only the three closed labels and a
monotonic revision, and it never carries a path, a secret or a log line.

The Resident side of the same contract is covered in the kagent lane.
"""

from __future__ import annotations

import json

from claw_connect.local_diagnostics_report import (
    LOCAL_DIAGNOSTICS_FILE_ENV,
    LOCAL_DIAGNOSTICS_VERSION,
    local_diagnostics_file_from_environ,
    local_diagnostics_path,
    read_local_diagnostics,
    write_local_diagnostics,
)

READY = {"agent_source": "ready", "autostart": "enabled", "resident": "running"}


def test_the_connector_writes_a_bounded_file(tmp_path):
    path = write_local_diagnostics(tmp_path, checks=READY)
    assert path is not None
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == LOCAL_DIAGNOSTICS_VERSION
    assert raw["checks"] == READY
    assert set(raw) == {"version", "revision", "checks"}


def test_the_file_carries_no_path_no_secret_and_no_log(tmp_path):
    write_local_diagnostics(tmp_path, checks=READY)
    text = local_diagnostics_path(tmp_path).read_text(encoding="utf-8")
    assert "C:\\" not in text
    assert "/" not in text
    assert "password" not in text.lower()
    assert "stdout" not in text.lower()


def test_the_revision_advances_on_every_write(tmp_path):
    write_local_diagnostics(tmp_path, checks=READY)
    first = read_local_diagnostics(tmp_path)["revision"]
    write_local_diagnostics(tmp_path, checks=READY)
    second = read_local_diagnostics(tmp_path)["revision"]
    assert second == first + 1


def test_an_unusable_label_set_is_not_written(tmp_path):
    assert write_local_diagnostics(tmp_path, checks={"agent_source": "ready"}) is None
    assert not local_diagnostics_path(tmp_path).exists()


def test_a_missing_or_foreign_file_reads_as_nothing(tmp_path):
    assert read_local_diagnostics(tmp_path) is None
    local_diagnostics_path(tmp_path).write_text(
        json.dumps({"version": "other", "revision": 1, "checks": READY}),
        encoding="utf-8",
    )
    assert read_local_diagnostics(tmp_path) is None


def test_a_corrupt_file_reads_as_nothing(tmp_path):
    local_diagnostics_path(tmp_path).write_text("{not json", encoding="utf-8")
    assert read_local_diagnostics(tmp_path) is None


def test_the_connector_names_the_file_for_the_resident(tmp_path):
    path = local_diagnostics_path(tmp_path)
    environ = {LOCAL_DIAGNOSTICS_FILE_ENV: str(path)}
    assert local_diagnostics_file_from_environ(environ) == path
    assert local_diagnostics_file_from_environ({}) is None
