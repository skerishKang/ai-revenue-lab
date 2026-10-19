from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "cloudflare_asset_snapshot.py"
PLAINTEXT_MARKER = "inert-plaintext-fixture"


def _load():
    spec = importlib.util.spec_from_file_location("cloudflare_asset_snapshot_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


snapshot_ops = _load()


class FakeWrangler:
    """Offline stand-in for the Wrangler CLI.

    ``responses`` maps a command without the executable name to its exit code
    and stdout. Unknown commands fail, so an unexpected read command is
    visible in the test instead of silently returning empty data.
    """

    def __init__(self, responses: dict[str, tuple[int, str]]):
        self.responses = responses
        self.calls: list[str] = []
        self.envs: list[dict[str, str]] = []

    def __call__(self, command, env, timeout):
        key = " ".join(command[1:])
        self.calls.append(key)
        self.envs.append(dict(env))
        return self.responses.get(key, (1, ""))


def _status(version_id: str) -> tuple[int, str]:
    return 0, json.dumps(
        {
            "id": "deployment-fixture",
            "source": "wrangler",
            "author_email": "owner@example.invalid",
            "annotations": {"workers/message": "fixture deploy"},
            "versions": [{"version_id": version_id, "percentage": 100}],
            "created_on": "2026-10-19T00:00:00.000000Z",
        }
    )


def _version(version_id: str, bindings: list[dict]) -> tuple[int, str]:
    return 0, json.dumps(
        {
            "id": version_id,
            "number": 2,
            "metadata": {
                "created_on": "2026-10-19T00:00:00.000000Z",
                "source": "wrangler",
                "author_id": "author-fixture",
                "author_email": "owner@example.invalid",
            },
            "annotations": {"workers/tag": "", "workers/triggered_by": "upload"},
            "resources": {
                "script": {"handlers": ["fetch"], "etag": "etag-fixture"},
                "script_runtime": {
                    "compatibility_date": "2026-05-07",
                    "compatibility_flags": ["nodejs_compat"],
                },
                "bindings": bindings,
            },
        }
    )


def _history(version_id: str) -> tuple[int, str]:
    return 0, json.dumps(
        [
            {
                "id": "deployment-new",
                "source": "wrangler",
                "author_email": "owner@example.invalid",
                "annotations": {"workers/message": "newer fixture"},
                "versions": [{"version_id": version_id, "percentage": 100}],
                "created_on": "2026-10-19T00:00:00.000000Z",
            },
            {
                "id": "deployment-old",
                "source": "wrangler",
                "annotations": {"workers/message": "older fixture"},
                "versions": [{"version_id": "version-1", "percentage": 100}],
                "created_on": "2026-10-18T00:00:00.000000Z",
            },
        ]
    )


def _d1_list() -> tuple[int, str]:
    return 0, json.dumps(
        [
            {
                "uuid": "db-fixture",
                "name": "demo-db",
                "created_at": "2026-09-01T00:00:00.000Z",
                "version": "production",
                "num_tables": 4,
                "file_size": 2048,
                "jurisdiction": None,
            }
        ]
    )


R2_TEXT = """
 ⛅️ wrangler 4.87.0
──────────────────────────────────────────────
Listing buckets...
name:           demo-workspace
creation_date:  2026-09-10T19:10:06.048Z

name:           demo-media
creation_date:  2026-09-02T09:55:29.391Z
"""

BINDINGS = [
    {"environment": "production", "name": "SERVICE", "service": "other-worker", "type": "service"},
    {"name": "DB", "id": "db-fixture", "type": "d1"},
    {"name": "FILES", "bucket_name": "demo-workspace", "type": "r2_bucket"},
    {"name": "DO_STATE", "class_name": "StateBlock", "type": "durable_object_namespace"},
    {"name": "FLAGS", "namespace_id": "kv-fixture", "type": "kv_namespace"},
    {"name": "ACCESS_KEY", "type": "secret_text"},
    {
        "name": "PROVIDER_KEY",
        "secret_name": "PROVIDER_KEY",
        "store_id": "store-fixture",
        "type": "secrets_store_secret",
    },
    {"name": "MODE", "text": PLAINTEXT_MARKER, "type": "plain_text"},
    {"name": "SETTINGS", "json": {"value": PLAINTEXT_MARKER}, "type": "json"},
]


def _fake_wrangler() -> FakeWrangler:
    return FakeWrangler(
        {
            "deployments status --name demo-worker --json": _status("version-2"),
            "versions view version-2 --name demo-worker --json": _version("version-2", BINDINGS),
            "deployments list --name demo-worker --json": _history("version-2"),
            "d1 list --json": _d1_list(),
            "r2 bucket list": (0, R2_TEXT),
        }
    )


def _worker(name: str, version_id: str, bindings: dict | None = None) -> dict:
    return {
        "name": name,
        "state": "deployed",
        "version_id": version_id,
        "created_on": "2026-10-19T00:00:00.000000Z",
        "bindings": bindings
        or {
            "counts": {},
            "secrets": [],
            "d1": [],
            "r2": [],
            "service": [],
            "durable_object": [],
            "kv": [],
            "other": [],
        },
    }


def _snapshot(workers: list[dict], d1: list[dict] | None = None, r2: list[str] | None = None) -> dict:
    return {
        "kind": snapshot_ops.SNAPSHOT_KIND,
        "version": snapshot_ops.SNAPSHOT_VERSION,
        "captured_utc": "2026-10-19T00:00:00Z",
        "account_id": None,
        "workers": workers,
        "d1": d1
        if d1 is not None
        else [
            {
                "name": "demo-db",
                "uuid": "db-fixture",
                "created_at": "2026-09-01T00:00:00.000Z",
                "version": "production",
                "num_tables": 4,
                "file_size": 2048,
            }
        ],
        "r2": [{"name": name, "creation_date": None} for name in (r2 or ["demo-workspace", "demo-media"])],
    }


def test_summarize_bindings_keeps_names_and_drops_values():
    summary = snapshot_ops.summarize_bindings(BINDINGS)

    serialized = json.dumps(summary)
    assert PLAINTEXT_MARKER not in serialized
    assert "etag-fixture" not in serialized
    assert summary["counts"] == {
        "d1": 1,
        "durable_object_namespace": 1,
        "json": 1,
        "kv_namespace": 1,
        "plain_text": 1,
        "r2_bucket": 1,
        "secret_text": 1,
        "secrets_store_secret": 1,
        "service": 1,
    }
    assert summary["secrets"] == [
        {"binding": "ACCESS_KEY", "type": "secret_text"},
        {
            "binding": "PROVIDER_KEY",
            "type": "secrets_store_secret",
            "secret_name": "PROVIDER_KEY",
            "store_id": "store-fixture",
        },
    ]
    assert summary["d1"] == [{"binding": "DB", "database_id": "db-fixture"}]
    assert summary["r2"] == [{"binding": "FILES", "bucket_name": "demo-workspace"}]
    assert summary["service"] == [{"binding": "SERVICE", "worker": "other-worker"}]
    assert summary["durable_object"] == [{"binding": "DO_STATE", "class_name": "StateBlock"}]
    assert summary["kv"] == [{"binding": "FLAGS", "namespace_id": "kv-fixture"}]
    assert summary["other"] == [
        {"binding": "MODE", "type": "plain_text"},
        {"binding": "SETTINGS", "type": "json"},
    ]


def test_summarize_bindings_rejects_missing_binding_list():
    with pytest.raises(snapshot_ops.SnapshotError, match="version_bindings_unavailable"):
        snapshot_ops.summarize_bindings(None)


def test_parse_bucket_list_ignores_banner_lines():
    assert snapshot_ops._parse_bucket_list(R2_TEXT) == [
        {"name": "demo-media", "creation_date": "2026-09-02T09:55:29.391Z"},
        {"name": "demo-workspace", "creation_date": "2026-09-10T19:10:06.048Z"},
    ]


def test_capture_worker_reads_current_version_without_author_identity():
    runner = _fake_wrangler()

    captured = snapshot_ops.capture_worker(
        "demo-worker", wrangler="wrangler", env={}, timeout=5.0, runner=runner
    )

    assert captured["state"] == "deployed"
    assert captured["version_id"] == "version-2"
    assert captured["version_number"] == 2
    assert captured["message"] == "fixture deploy"
    assert captured["handlers"] == ["fetch"]
    assert captured["compatibility_flags"] == ["nodejs_compat"]
    assert captured["bindings"]["secrets"][0]["binding"] == "ACCESS_KEY"
    assert [row["version_id"] for row in captured["history"]] == ["version-2", "version-1"]
    serialized = json.dumps(captured)
    assert "owner@example.invalid" not in serialized
    assert "author-fixture" not in serialized
    assert PLAINTEXT_MARKER not in serialized


def test_capture_worker_reports_unavailable_instead_of_raising():
    runner = FakeWrangler({})

    captured = snapshot_ops.capture_worker(
        "missing-worker", wrangler="wrangler", env={}, timeout=5.0, runner=runner
    )

    assert captured == {
        "name": "missing-worker",
        "state": "unavailable",
        "error": "wrangler_command_failed",
    }


def test_capture_snapshot_orders_workers_and_sets_account(monkeypatch):
    monkeypatch.setattr(snapshot_ops, "capture_worker", lambda name, **_: _worker(name, "version-2"))
    runner = FakeWrangler({"d1 list --json": _d1_list(), "r2 bucket list": (0, R2_TEXT)})

    captured = snapshot_ops.capture_snapshot(
        ["zeta-worker", "alpha-worker", "alpha-worker"],
        account_id="acct-fixture",
        timeout=5.0,
        runner=runner,
        now="2026-10-19T01:02:03Z",
    )

    assert captured["kind"] == snapshot_ops.SNAPSHOT_KIND
    assert captured["captured_utc"] == "2026-10-19T01:02:03Z"
    assert captured["account_id"] == "acct-fixture"
    assert [row["name"] for row in captured["workers"]] == ["alpha-worker", "zeta-worker"]
    assert captured["d1"][0]["name"] == "demo-db"
    assert [row["name"] for row in captured["r2"]] == ["demo-media", "demo-workspace"]
    assert all(env["CLOUDFLARE_ACCOUNT_ID"] == "acct-fixture" for env in runner.envs)


def test_capture_snapshot_requires_workers():
    with pytest.raises(snapshot_ops.SnapshotError, match="worker_list_required"):
        snapshot_ops.capture_snapshot([])


def test_capture_snapshot_rejects_malformed_d1_list():
    runner = FakeWrangler({"d1 list --json": (0, "{}"), "r2 bucket list": (0, "")})
    with pytest.raises(snapshot_ops.SnapshotError, match="d1_list_invalid"):
        snapshot_ops.capture_snapshot(["demo-worker"], runner=runner)


def test_compare_snapshots_identical_is_ok():
    previous = _snapshot(
        [
            _worker(
                "demo-worker",
                "version-2",
                {
                    "counts": {},
                    "secrets": [{"binding": "ACCESS_KEY", "type": "secret_text"}],
                    "d1": [{"binding": "DB", "database_id": "db-fixture"}],
                    "r2": [{"binding": "FILES", "bucket_name": "demo-workspace"}],
                    "service": [],
                    "durable_object": [],
                    "kv": [],
                    "other": [],
                },
            )
        ]
    )

    report = snapshot_ops.compare_snapshots(previous, json.loads(json.dumps(previous)))

    assert report["ok"] is True
    assert report["workers"] == {"missing": [], "version_changed": [], "binding_changed": []}
    assert report["d1"] == {"missing": [], "added": [], "changed": []}
    assert report["r2"] == {"missing": [], "added": []}


def test_compare_snapshots_detects_every_drift_kind():
    old_bindings = {
        "counts": {},
        "secrets": [{"binding": "OLD_KEY", "type": "secret_text"}],
        "d1": [{"binding": "DB", "database_id": "db-fixture"}],
        "r2": [],
        "service": [],
        "durable_object": [],
        "kv": [],
        "other": [],
    }
    previous = _snapshot([_worker("demo-worker", "version-2", old_bindings), _worker("gone-worker", "version-1")])
    current = _snapshot(
        [
            _worker(
                "demo-worker",
                "version-3",
                {
                    **old_bindings,
                    "secrets": [{"binding": "NEW_KEY", "type": "secret_text"}],
                },
            )
        ],
        d1=[
            {
                "name": "demo-db",
                "uuid": "db-fixture",
                "created_at": "2026-09-01T00:00:00.000Z",
                "version": "production",
                "num_tables": 5,
                "file_size": 4096,
            }
        ],
        r2=["demo-media", "demo-extra"],
    )

    report = snapshot_ops.compare_snapshots(previous, current)

    assert report["ok"] is False
    assert report["workers"]["missing"] == ["gone-worker"]
    assert report["workers"]["version_changed"] == [
        {
            "worker": "demo-worker",
            "from": "version-2",
            "to": "version-3",
            "from_created_on": "2026-10-19T00:00:00.000000Z",
            "to_created_on": "2026-10-19T00:00:00.000000Z",
        }
    ]
    assert report["workers"]["binding_changed"] == [
        {
            "worker": "demo-worker",
            "kind": "secrets",
            "added": ["NEW_KEY|secret_text"],
            "removed": ["OLD_KEY|secret_text"],
        }
    ]
    assert report["d1"]["changed"] == [
        {"database": "demo-db", "fields": {"num_tables": {"from": 4, "to": 5}, "file_size": {"from": 2048, "to": 4096}}}
    ]
    assert report["r2"]["missing"] == ["demo-workspace"]
    assert report["r2"]["added"] == ["demo-extra"]


def test_cli_capture_writes_snapshot_and_reports_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(snapshot_ops, "capture_snapshot", lambda workers, **_: _snapshot([_worker("demo-worker", "version-2")]))
    destination = tmp_path / "private" / "snapshot.json"

    code = snapshot_ops.main(["capture", "--out", str(destination), "--worker", "demo-worker"])

    assert code == 0
    assert json.loads(destination.read_text(encoding="utf-8"))["kind"] == snapshot_ops.SNAPSHOT_KIND
    assert f"CAPTURE_OK workers=1 d1=1 r2=2 out={destination}" in capsys.readouterr().out


def test_cli_capture_failure_is_not_a_traceback(tmp_path, capsys):
    code = snapshot_ops.main(
        [
            "capture",
            "--out",
            str(tmp_path / "snapshot.json"),
            "--worker",
            "demo-worker",
            "--wrangler",
            str(tmp_path / "no-such-wrangler"),
        ]
    )

    assert code == 2
    assert "CAPTURE_FAILED reason=wrangler_command_failed" in capsys.readouterr().err
    assert not (tmp_path / "snapshot.json").exists()


def test_cli_verify_exit_codes(tmp_path, monkeypatch, capsys):
    stored = _snapshot([_worker("demo-worker", "version-2")])
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(stored), encoding="utf-8")

    monkeypatch.setattr(snapshot_ops, "capture_snapshot", lambda workers, **_: stored)
    assert snapshot_ops.main(["verify", "--snapshot", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    monkeypatch.setattr(
        snapshot_ops,
        "capture_snapshot",
        lambda workers, **_: _snapshot([_worker("demo-worker", "version-3")]),
    )
    assert snapshot_ops.main(["verify", "--snapshot", str(path)]) == 1
    assert json.loads(capsys.readouterr().out)["workers"]["version_changed"][0]["to"] == "version-3"


def test_cli_verify_rejects_foreign_snapshot(tmp_path, capsys):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps({"kind": "SOMETHING_ELSE"}), encoding="utf-8")

    assert snapshot_ops.main(["verify", "--snapshot", str(path)]) == 2
    assert "VERIFY_FAILED reason=snapshot_kind_mismatch" in capsys.readouterr().err


def test_cli_verify_reports_unreadable_snapshot(tmp_path, capsys):
    path = tmp_path / "snapshot.json"
    path.write_text("{not-json", encoding="utf-8")

    assert snapshot_ops.main(["verify", "--snapshot", str(path)]) == 2
    assert "VERIFY_FAILED reason=snapshot_unreadable" in capsys.readouterr().err
