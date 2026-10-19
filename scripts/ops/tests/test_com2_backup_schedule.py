from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "com2_backup_schedule.py"


def _load():
    spec = importlib.util.spec_from_file_location("com2_backup_schedule_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


schedule_ops = _load()
PAYLOAD_SHA = "a" * 64


class FakeOps:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.backup_ids: list[str] = []
        self.upload_failures: list[str] = []
        self.build_error: str | None = None
        self.restore_result = {
            "file_count": 2,
            "total_bytes": 10,
            "encrypted": True,
            "key_id": "com2-test",
        }

    def encryption_key_from_env(self, name: str) -> bytes:
        self.calls.append(("key", name))
        return b"k" * 32

    def default_backup_id(self) -> str:
        return "20261019t120000z"

    def build_backup(
        self,
        roots,
        out_dir,
        machine,
        backup_id,
        created_at,
        encryption_key=None,
        key_id="",
    ):
        self.calls.append(
            ("build", backup_id, tuple(str(Path(root)) for root in roots), key_id)
        )
        self.backup_ids.append(backup_id)
        if self.build_error:
            raise schedule_ops.BACKUP_OPS.OpsError(self.build_error)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "payload.tar.gz").write_bytes(b"payload")
        (out_dir / "manifest.json").write_text("{}", encoding="utf-8")
        return {
            "manifest": {"file_count": 3, "total_bytes": 30},
            "payload_bytes": 7,
            "payload_sha256": PAYLOAD_SHA,
        }

    def upload_backup(self, endpoint, directory, machine, backup_id, token):
        if self.upload_failures:
            raise schedule_ops.BACKUP_OPS.OpsError(self.upload_failures.pop(0))
        self.calls.append(("upload", backup_id))
        return {"payload_bytes": 7, "payload_sha256": PAYLOAD_SHA,
                "file_count": 3, "key_id": "com2-test"}

    def verify_backup(self, endpoint, machine, backup_id, token, local_dir=None,
                      expected_key_id=""):
        self.calls.append(
            ("verify", backup_id, str(local_dir), expected_key_id)
        )
        return {
            "sha256": PAYLOAD_SHA,
            "bytes": 7,
            "file_count": 3,
            "key_id": expected_key_id,
        }

    def restore_check(self, endpoint, machine, backup_id, token, target,
                      encryption_key=None, expected_key_id=""):
        self.calls.append(("restore", backup_id, str(target)))
        (Path(target) / "tree.txt").write_text("restored", encoding="utf-8")
        return self.restore_result


def _config(root: Path, **overrides):
    values = {
        "endpoint": "https://backup.example.test",
        "key_id": "com2-test",
        "roots": (root,),
    }
    values.update(overrides)
    return schedule_ops.BackupConfig(**values)


def _prepare(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "db.sqlite3").write_bytes(b"database")
    state = tmp_path / "state"
    state.mkdir()
    return root, state


def _set_env(monkeypatch):
    monkeypatch.setenv("PADIEM_COM2_BACKUP_WRITE_TOKEN", "fixture-token-value")
    monkeypatch.setenv("COM2_BACKUP_ENCRYPTION_KEY", "f" * 64)


def _status(state: Path) -> dict:
    return json.loads((state / schedule_ops.STATUS_NAME).read_text(encoding="utf-8"))


def test_cycle_builds_uploads_and_requires_remote_verification(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    ops = FakeOps()

    code, status = schedule_ops.run_once(state, _config(root), ops=ops, retry_delay=0)

    assert code == 0
    assert status["ok"] is True
    assert status["remote_verified"] is True
    assert status["backup_id"] == "20261019t120000z"
    assert status["source"] == {"roots": 1, "files": 3, "bytes": 30}
    assert status["payload"]["sha256"] == PAYLOAD_SHA
    verify = [call for call in ops.calls if call[0] == "verify"]
    assert verify == [
        ("verify", "20261019t120000z", str(state / "backups" / "20261019t120000z"),
         "com2-test")
    ]
    assert _status(state)["last_success_backup_id"] == "20261019t120000z"
    serialized = json.dumps(_status(state))
    assert "fixture-token-value" not in serialized
    assert "f" * 64 not in serialized


def test_retry_uses_a_new_backup_id_and_never_reuses_bytes(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    ops = FakeOps()
    ops.upload_failures = ["http_503"]

    code, status = schedule_ops.run_once(
        state, _config(root), ops=ops, retries=2, retry_delay=0
    )

    assert code == 0
    assert status["attempts"] == 2
    assert ops.backup_ids == ["20261019t120000z", "20261019t120000z-r2"]
    assert [call[1] for call in ops.calls if call[0] == "upload"] == [
        "20261019t120000z-r2"
    ]


def test_non_retryable_error_stops_with_operator_action(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    ops = FakeOps()
    ops.build_error = "no_source_files"

    code, status = schedule_ops.run_once(
        state, _config(root), ops=ops, retries=3, retry_delay=0
    )

    assert code == 1
    assert status["attempts"] == 1
    assert status["failed_stage"] == "build"
    assert status["error"] == "no_source_files"
    assert status["recoverable"] is False
    assert status["operator_action_required"] is True


def test_failure_preserves_the_last_successful_backup(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    (state / schedule_ops.STATUS_NAME).write_text(
        json.dumps(
            {
                "ok": True,
                "last_success_utc": "2026-10-18T00:00:00Z",
                "last_success_backup_id": "previous-backup",
                "consecutive_failures": 0,
            }
        ),
        encoding="utf-8",
    )
    ops = FakeOps()
    ops.upload_failures = ["http_500", "http_500", "http_500"]

    code, status = schedule_ops.run_once(
        state, _config(root), ops=ops, retries=3, retry_delay=0
    )

    assert code == 1
    assert status["failed_stage"] == "upload"
    assert status["recoverable"] is True
    assert status["operator_action_required"] is False
    assert status["last_success_utc"] == "2026-10-18T00:00:00Z"
    assert status["last_success_backup_id"] == "previous-backup"
    assert status["consecutive_failures"] == 1


def test_missing_key_fails_before_any_build(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    monkeypatch.setenv("PADIEM_COM2_BACKUP_WRITE_TOKEN", "fixture-token-value")
    monkeypatch.delenv("COM2_BACKUP_ENCRYPTION_KEY", raising=False)

    class MissingKeyOps(FakeOps):
        def encryption_key_from_env(self, name):
            raise schedule_ops.BACKUP_OPS.OpsError("encryption_key_env_missing")

    code, status = schedule_ops.run_once(
        state, _config(root), ops=MissingKeyOps(), retry_delay=0
    )

    assert code == 1
    assert status["failed_stage"] == "prepare"
    assert status["error"] == "encryption_key_env_missing"
    assert status["operator_action_required"] is True


def test_fresh_lock_prevents_overlap(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    (state / schedule_ops.LOCK_NAME).write_text(
        json.dumps({"pid": 999999}), encoding="utf-8"
    )
    ops = FakeOps()

    code = schedule_ops.run(state, _config(root), ops=ops)

    assert code == 3
    assert ops.calls == []
    assert (state / schedule_ops.LOCK_NAME).exists()


def test_stale_lock_is_replaced(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    lock = state / schedule_ops.LOCK_NAME
    lock.write_text(json.dumps({"pid": 999999}), encoding="utf-8")
    old = time.time() - 4 * 3600
    os.utime(lock, (old, old))

    code = schedule_ops.run(
        state, _config(root), ops=FakeOps(), stale_minutes=180
    )

    assert code == 0
    assert not lock.exists()
    assert _status(state)["ok"] is True


def test_generation_pointer_selects_the_current_snapshot(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    generations, snapshot, pointer = _generation_tree(tmp_path)
    ops = FakeOps()

    code, status_payload = schedule_ops.run_once(
        state,
        _config(root, generation_pointer=pointer, generations_dir=generations),
        ops=ops,
        retry_delay=0,
    )

    assert code == 0
    build = [call for call in ops.calls if call[0] == "build"][0]
    assert str(snapshot.resolve()) in build[2]
    assert set(status_payload["databases"]) == {"chat", "engine"}
    assert status_payload["databases"]["engine"]["sha256"] == hashlib.sha256(
        b"engine-database-bytes"
    ).hexdigest()


def test_generation_without_engine_database_fails_before_build(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    generations, _snapshot, pointer = _generation_tree(tmp_path, engine=False)
    ops = FakeOps()

    code, status = schedule_ops.run_once(
        state,
        _config(root, generation_pointer=pointer, generations_dir=generations),
        ops=ops,
        retry_delay=0,
    )

    assert code == 1
    assert status["error"] == "generation_engine_missing"
    assert status["failed_stage"] == "prepare"
    assert status["operator_action_required"] is True
    assert not [call for call in ops.calls if call[0] == "build"]


def test_engine_seed_must_match_the_published_generation(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    generations, _snapshot, pointer = _generation_tree(tmp_path, engine_sha="b" * 64)

    code, status = schedule_ops.run_once(
        state,
        _config(root, generation_pointer=pointer, generations_dir=generations),
        ops=FakeOps(),
        retry_delay=0,
    )

    assert code == 1
    assert status["error"] == "generation_engine_integrity_failed"
    assert status["operator_action_required"] is True


def test_chat_runtime_seed_must_match_the_published_generation(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    generations, _snapshot, pointer = _generation_tree(tmp_path)
    (pointer.parent / f"chat-20261019T084722757869Z.sqlite3").write_bytes(b"stale")

    code, status = schedule_ops.run_once(
        state,
        _config(root, generation_pointer=pointer, generations_dir=generations),
        ops=FakeOps(),
        retry_delay=0,
    )

    assert code == 1
    assert status["error"] == "generation_chat_seed_integrity_failed"
    assert status["operator_action_required"] is True


def test_published_generation_must_match_the_runtime_pointer(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    generations, _snapshot, pointer = _generation_tree(
        tmp_path, published_generation="20261019T000000000000Z"
    )

    code, status = schedule_ops.run_once(
        state,
        _config(root, generation_pointer=pointer, generations_dir=generations),
        ops=FakeOps(),
        retry_delay=0,
    )

    assert code == 1
    assert status["error"] == "generation_pointer_mismatch"


def test_generation_manifest_is_required(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    generations, _snapshot, pointer = _generation_tree(tmp_path)
    (tmp_path / "current_generation.json").unlink()

    code, status = schedule_ops.run_once(
        state,
        _config(root, generation_pointer=pointer, generations_dir=generations),
        ops=FakeOps(),
        retry_delay=0,
    )

    assert code == 1
    assert status["error"] == "generation_manifest_missing"


def test_generation_pointer_fails_closed_when_snapshot_is_missing(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    generations = tmp_path / "generations"
    generations.mkdir()
    pointer = tmp_path / "current_generation.json"
    pointer.write_text(
        json.dumps(
            {
                "kind": "PADIEM_COM2_B62_GENERATION_V1",
                "d1_generation": "20261019T000000000000Z",
            }
        ),
        encoding="utf-8",
    )

    code, status = schedule_ops.run_once(
        state,
        _config(root, generation_pointer=pointer, generations_dir=generations),
        ops=FakeOps(),
        retry_delay=0,
    )

    assert code == 1
    assert status["error"] == "generation_snapshot_missing"
    assert status["operator_action_required"] is True


def _generation_tree(
    tmp_path: Path,
    *,
    engine: bool = True,
    engine_sha: str | None = None,
    published_generation: str | None = None,
):
    """Create the runtime pointer, published pointer and snapshot pair."""
    generation = "20261019T084722757869Z"
    chat_bytes = b"chat-database-bytes"
    engine_bytes = b"engine-database-bytes"
    generations = tmp_path / "generations"
    snapshot = generations / generation
    snapshot.mkdir(parents=True)
    (snapshot / "chat.sqlite3").write_bytes(chat_bytes)
    if engine:
        (snapshot / "engine.sqlite3").write_bytes(engine_bytes)
    store = tmp_path / "store"
    store.mkdir()
    seed = store / f"chat-{generation}.sqlite3"
    seed.write_bytes(chat_bytes)
    pointer = store / "current_generation.json"
    pointer.write_text(
        json.dumps(
            {
                "kind": "PADIEM_COM2_B62_GENERATION_V1",
                "d1_generation": generation,
                "d1_seed": seed.name,
                "d1_bytes": len(chat_bytes),
                "d1_sha256": hashlib.sha256(chat_bytes).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    databases = {
        "chat": {
            "database": "padiem-chat-db",
            "tables": 57,
            "bytes": len(chat_bytes),
            "sha256": hashlib.sha256(chat_bytes).hexdigest(),
        }
    }
    if engine:
        databases["engine"] = {
            "database": "padiem-engine",
            "tables": 10,
            "bytes": len(engine_bytes),
            "sha256": engine_sha or hashlib.sha256(engine_bytes).hexdigest(),
        }
    (tmp_path / "current_generation.json").write_text(
        json.dumps(
            {
                "generation": published_generation or generation,
                "databases": databases,
                "production_bound": False,
            }
        ),
        encoding="utf-8",
    )
    return generations, snapshot, pointer


def test_restore_verify_uses_a_throwaway_directory(tmp_path, monkeypatch):
    root, state = _prepare(tmp_path)
    _set_env(monkeypatch)
    ops = FakeOps()

    code, status = schedule_ops.restore_verify(
        state, _config(root), "20261019t120000z", ops=ops
    )

    assert code == 0
    assert status["ok"] is True
    assert status["files"] == 2
    assert status["bytes"] == 10
    restore_call = [call for call in ops.calls if call[0] == "restore"][0]
    target = Path(restore_call[2])
    assert target.parent == state / "restore-check"
    assert not target.exists()
    assert list((state / "restore-check").iterdir()) == []
    saved = json.loads(
        (state / schedule_ops.RESTORE_STATUS_NAME).read_text(encoding="utf-8")
    )
    assert saved["backup_id"] == "20261019t120000z"


def test_install_task_dry_run_embeds_roots_and_dpapi_wrapper(tmp_path, capsys):
    root, state = _prepare(tmp_path)
    repo = tmp_path / "repo"
    (repo / "scripts" / "ops").mkdir(parents=True)
    (repo / "scripts" / "ops" / "com2_backup_schedule.py").write_text(
        "# fixture\n", encoding="utf-8"
    )
    store = tmp_path / "store.py"
    store.write_text("# fixture store\n", encoding="utf-8")

    code = schedule_ops.main(
        [
            "install-task",
            "--state-dir", str(state),
            "--repo", str(repo),
            "--endpoint", "https://backup.example.test",
            "--key-id", "com2-test",
            "--root", str(root),
            "--time", "05:30",
            "--secret-store", str(store),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"][:2] == ["schtasks", "/Create"]
    assert payload["command"][payload["command"].index("/ST") + 1] == "05:30"
    assert "PADIEM-COM2-Backup" in payload["command"]
    assert str(store) in payload["launcher_content"]
    assert "store.py" in payload["launcher_content"]
    assert "'run'" in payload["launcher_content"]
    assert str(root) in payload["launcher_content"]
    assert not (state / "run-backup.ps1").exists()


def test_install_task_rejects_an_invalid_time(tmp_path):
    root, state = _prepare(tmp_path)
    code = schedule_ops.main(
        [
            "install-task",
            "--state-dir", str(state),
            "--repo", str(tmp_path),
            "--endpoint", "https://backup.example.test",
            "--key-id", "com2-test",
            "--root", str(root),
            "--time", "5:30",
            "--secret-store", "",
            "--dry-run",
        ]
    )
    assert code == 1


def test_status_reports_staleness_only_with_an_explicit_bound(tmp_path, capsys):
    _root, state = _prepare(tmp_path)
    (state / schedule_ops.STATUS_NAME).write_text(
        json.dumps(
            {
                "ok": False,
                "last_success_utc": "2026-10-17T00:00:00Z",
                "last_success_backup_id": "old",
            }
        ),
        encoding="utf-8",
    )

    assert schedule_ops.main(["status", "--state-dir", str(state)]) == 1
    capsys.readouterr()
    assert (
        schedule_ops.main(
            ["status", "--state-dir", str(state), "--max-age-hours", "24"]
        )
        == 1
    )
    assert "LAST_SUCCESS_STALE" in capsys.readouterr().err
    assert (
        schedule_ops.main(
            ["status", "--state-dir", str(state), "--max-age-hours", "240"]
        )
        == 0
    )
    assert "LAST_SUCCESS_OK" in capsys.readouterr().out


def test_status_missing_returns_two(tmp_path, capsys):
    state = tmp_path / "empty"
    state.mkdir()
    assert schedule_ops.main(["status", "--state-dir", str(state)]) == 2
    assert "STATUS_MISSING" in capsys.readouterr().err
