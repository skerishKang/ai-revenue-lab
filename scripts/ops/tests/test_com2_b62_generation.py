from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "com2_b62_generation.py"


def _load():
    spec = importlib.util.spec_from_file_location("com2_b62_generation_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


generation_ops = _load()


def _fixture(
    tmp_path: Path,
    *,
    kind: str = generation_ops.POINTER_KIND,
    production_bound: bool = False,
    seed_name: str = "chat-20261019T000000000000Z.sqlite3",
    seed_written: bool = True,
    seed_bytes: bytes | None = None,
    d1_bytes: int | None = None,
    d1_sha256: str | None = None,
    d1_tables: int | None = 1,
    r2_generation: str = "20261019T005000763982Z",
    r2_pointer_generation: str | None = None,
    r2_manifest: bool = True,
):
    store = tmp_path / "generation-store"
    store.mkdir()
    seed = store / seed_name
    if seed_written:
        with sqlite3.connect(seed) as db:
            db.execute("CREATE TABLE history (id INTEGER PRIMARY KEY)")
        if seed_bytes is not None:
            seed.write_bytes(seed_bytes)
    content = seed.read_bytes() if seed_written else b"seed"
    pointer = {
        "kind": kind,
        "d1_generation": "20261019T000000000000Z",
        "d1_seed": seed_name,
        "d1_bytes": len(content) if d1_bytes is None else d1_bytes,
        "d1_sha256": generation_ops.hashlib.sha256(content).hexdigest()
        if d1_sha256 is None
        else d1_sha256,
        "d1_tables": d1_tables,
        "r2_generation": r2_generation,
        "r2_root": str(tmp_path / "r2-staging"),
        "r2_write_overlay": str(store / "r2-writes"),
        "production_bound": production_bound,
    }
    (store / "current_generation.json").write_text(json.dumps(pointer), encoding="utf-8")

    r2_root = tmp_path / "r2-staging"
    generation_dir = r2_root / "generations" / r2_generation
    generation_dir.mkdir(parents=True)
    if r2_manifest:
        (generation_dir / "manifest.json").write_text("[]", encoding="utf-8")
    (r2_root / "current_generation.json").write_text(
        json.dumps(
            {
                "generation": r2_pointer_generation or r2_generation,
                "production_bound": False,
            }
        ),
        encoding="utf-8",
    )
    return store, r2_root


def _reason(callable_):
    with pytest.raises(generation_ops.GenerationError) as caught:
        callable_()
    return str(caught.value)


def test_verify_generation_ok(tmp_path):
    store, r2_root = _fixture(tmp_path)
    summary = generation_ops.verify_generation(store, r2_root)
    assert summary["d1_seed"] == "chat-20261019T000000000000Z.sqlite3"
    assert summary["r2_generation"] == "20261019T005000763982Z"
    assert summary["d1_tables"] == 1
    assert summary["production_bound"] is False


def test_missing_pointer_fails_closed(tmp_path):
    store = tmp_path / "generation-store"
    store.mkdir()
    assert _reason(lambda: generation_ops.verify_generation(store)) == "b62_generation_pointer_missing"


def test_wrong_kind_is_rejected(tmp_path):
    store, r2_root = _fixture(tmp_path, kind="SOMETHING_ELSE")
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "b62_generation_pointer_invalid"


def test_production_bound_pointer_is_rejected(tmp_path):
    store, r2_root = _fixture(tmp_path, production_bound=True)
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "b62_generation_production_bound"


def test_child_path_seed_is_rejected(tmp_path):
    store, r2_root = _fixture(tmp_path, seed_name="../escape.sqlite3")
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "b62_generation_pointer_invalid"


def test_missing_seed_fails_closed(tmp_path):
    store, r2_root = _fixture(tmp_path, seed_written=False)
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "b62_generation_seed_missing"


def test_seed_size_mismatch_is_rejected(tmp_path):
    store, r2_root = _fixture(tmp_path, d1_bytes=1)
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "b62_generation_seed_integrity_failed"


def test_seed_hash_mismatch_is_rejected(tmp_path):
    store, r2_root = _fixture(tmp_path, d1_sha256="0" * 64)
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "b62_generation_seed_integrity_failed"


def test_seed_table_mismatch_is_rejected(tmp_path):
    store, r2_root = _fixture(tmp_path, d1_tables=57)
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "b62_generation_seed_table_mismatch"


def test_r2_pointer_mismatch_is_rejected(tmp_path):
    store, r2_root = _fixture(
        tmp_path, r2_pointer_generation="20261017T170403656664Z"
    )
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "r2_generation_pointer_mismatch"


def test_r2_manifest_missing_is_rejected(tmp_path):
    store, r2_root = _fixture(tmp_path, r2_manifest=False)
    assert _reason(lambda: generation_ops.verify_generation(store, r2_root)) == "r2_staging_generation_unavailable"


def test_cli_reports_stable_result(tmp_path, capsys):
    store, r2_root = _fixture(tmp_path)
    code = generation_ops.main(["verify", "--store", str(store), "--r2-root", str(r2_root)])
    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith("B62_GENERATION_OK ")
    assert "r2_generation=20261019T005000763982Z" in out


def test_cli_failure_exit_code(tmp_path, capsys):
    store = tmp_path / "missing"
    code = generation_ops.main(["verify", "--store", str(store)])
    assert code == 2
    assert "B62_GENERATION_FAILED reason=b62_generation_pointer_missing" in capsys.readouterr().err
