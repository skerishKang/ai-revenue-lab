"""The COM2 B62 runtime pointer must name the currently published generation.

Nothing published the pointer after a successful D1/R2 sync, so the COM2 B62
runtime kept serving the generation published on 2026-10-19 while the sync
published a new one every day. ``com2_b62_generation_publish.py`` closes that
gap.

These tests use a synthetic published generation and a synthetic generation
store. They never reach Cloudflare, never touch a production database and
never hold a credential. The published pointer is additionally checked with the
existing read-only operator verifier, so the publisher and the runtime cannot
disagree about what a valid pointer is.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "com2_b62_generation_publish.py"
VERIFIER = Path(__file__).resolve().parents[1] / "com2_b62_generation.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


publish_ops = _load("com2_b62_generation_publish_ops", SCRIPT)
verifier_ops = _load("com2_b62_generation_verify_ops", VERIFIER)


def _make_chat_db(path: Path, tables: int = 6) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    for index in range(tables):
        connection.execute("CREATE TABLE t%d (a INTEGER, b TEXT)" % index)
    connection.execute("INSERT INTO t0 (a, b) VALUES (1, 'one')")
    connection.commit()
    connection.close()
    return path


def _published(
    tmp_path: Path,
    *,
    generation: str = "20261021T074313336936Z",
    r2_generation: str = "20261021T074335749153Z",
    fresh: bool = True,
    with_manifest: bool = True,
    tables: int = 6,
) -> Path:
    source_root = tmp_path / "storage-migration"
    snapshot = _make_chat_db(
        source_root / "snapshots" / "generations" / generation / "chat.sqlite3", tables
    )
    digest = publish_ops._sha256(snapshot)
    (source_root / "snapshots" / POINTER).write_text(
        json.dumps(
            {
                "generation": generation,
                "databases": {
                    "chat": {
                        "database": "padiem-chat-db",
                        "tables": tables,
                        "bytes": snapshot.stat().st_size,
                        "sha256": digest,
                    }
                },
                "fresh_remote_export": fresh,
                "production_bound": False,
            }
        ),
        encoding="utf-8",
    )
    r2_root = source_root / "r2-staging"
    (r2_root / "generations" / r2_generation).mkdir(parents=True, exist_ok=True)
    if with_manifest:
        (r2_root / "generations" / r2_generation / "manifest.json").write_text(
            "[]", encoding="utf-8"
        )
    (r2_root / POINTER).write_text(
        json.dumps({"generation": r2_generation, "production_bound": False}),
        encoding="utf-8",
    )
    return source_root


POINTER = "current_generation.json"


def test_publishing_names_the_currently_published_generation(tmp_path: Path) -> None:
    source_root = _published(tmp_path)
    store = tmp_path / "generation-store"

    result = publish_ops.publish(source_root=source_root, store=store)

    assert result["published"] is True
    assert result["kind"] == "PADIEM_COM2_B62_GENERATION_V1"
    assert result["d1_generation"] == "20261021T074313336936Z"
    assert result["d1_seed"] == "chat-20261021T074313336936Z.sqlite3"
    assert result["r2_generation"] == "20261021T074335749153Z"
    assert result["production_bound"] is False
    assert result["d1_tables"] == 6
    assert (store / result["d1_seed"]).is_file()
    published = json.loads((store / POINTER).read_text(encoding="utf-8"))
    assert published["d1_generation"] == "20261021T074313336936Z"


def test_the_published_pointer_satisfies_the_existing_operator_verifier(
    tmp_path: Path,
) -> None:
    """The publisher and the read-only operator check must agree."""

    source_root = _published(tmp_path)
    store = tmp_path / "generation-store"
    publish_ops.publish(source_root=source_root, store=store)

    summary = verifier_ops.verify_generation(store, source_root / "r2-staging")

    assert summary["d1_generation"] == "20261021T074313336936Z"
    assert summary["d1_seed"] == "chat-20261021T074313336936Z.sqlite3"
    assert summary["d1_tables"] == 6
    assert summary["r2_generation"] == "20261021T074335749153Z"
    assert summary["production_bound"] is False


def test_a_dry_run_publishes_nothing(tmp_path: Path) -> None:
    source_root = _published(tmp_path)
    store = tmp_path / "generation-store"

    result = publish_ops.publish(source_root=source_root, store=store, dry_run=True)

    assert result["published"] is False
    assert result["d1_generation"] == "20261021T074313336936Z"
    assert not (store / POINTER).exists()
    assert not list(store.glob("chat-*.sqlite3"))


def test_the_immutable_published_generation_is_never_modified(tmp_path: Path) -> None:
    source_root = _published(tmp_path)
    store = tmp_path / "generation-store"
    snapshot = source_root / "snapshots" / "generations" / "20261021T074313336936Z" / "chat.sqlite3"
    before = publish_ops._sha256(snapshot)
    before_mtime = snapshot.stat().st_mtime_ns

    publish_ops.publish(source_root=source_root, store=store)

    assert publish_ops._sha256(snapshot) == before
    assert snapshot.stat().st_mtime_ns == before_mtime


def test_the_previous_pointer_is_kept_for_a_rollback(tmp_path: Path) -> None:
    source_root = _published(tmp_path)
    store = tmp_path / "generation-store"
    store.mkdir(parents=True)
    (store / POINTER).write_text('{"kind": "PADIEM_COM2_B62_GENERATION_V1", "d1_generation": "old"}', encoding="utf-8")

    publish_ops.publish(source_root=source_root, store=store)

    previous = json.loads((store / (POINTER + ".previous")).read_text(encoding="utf-8"))
    assert previous["d1_generation"] == "old"


def test_a_stale_d1_generation_is_refused(tmp_path: Path) -> None:
    source_root = _published(tmp_path, fresh=False)
    store = tmp_path / "generation-store"

    with pytest.raises(publish_ops.PublishError) as excinfo:
        publish_ops.publish(source_root=source_root, store=store)

    assert str(excinfo.value) == "b62_d1_generation_not_fresh"
    assert not (store / POINTER).exists()


def test_a_missing_r2_manifest_is_refused(tmp_path: Path) -> None:
    source_root = _published(tmp_path, with_manifest=False)
    store = tmp_path / "generation-store"

    with pytest.raises(publish_ops.PublishError) as excinfo:
        publish_ops.publish(source_root=source_root, store=store)

    assert str(excinfo.value) == "r2_staging_generation_unavailable"
    assert not (store / POINTER).exists()


def test_an_existing_corrupt_seed_is_refused_and_not_overwritten(tmp_path: Path) -> None:
    source_root = _published(tmp_path)
    store = tmp_path / "generation-store"
    store.mkdir(parents=True)
    seed = store / "chat-20261021T074313336936Z.sqlite3"
    seed.write_bytes(b"not a database")

    with pytest.raises(publish_ops.PublishError) as excinfo:
        publish_ops.publish(source_root=source_root, store=store)

    assert str(excinfo.value) == "b62_generation_seed_integrity_failed"
    assert seed.read_bytes() == b"not a database"
    assert not (store / POINTER).exists()


def test_republishing_the_same_generation_is_idempotent(tmp_path: Path) -> None:
    source_root = _published(tmp_path)
    store = tmp_path / "generation-store"

    first = publish_ops.publish(source_root=source_root, store=store)
    second = publish_ops.publish(source_root=source_root, store=store)

    assert first["d1_generation"] == second["d1_generation"]
    assert first["d1_seed"] == second["d1_seed"]
    assert first["d1_sha256"] == second["d1_sha256"]
    verifier_ops.verify_generation(store, source_root / "r2-staging")
