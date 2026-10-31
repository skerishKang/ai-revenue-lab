"""Synthetic tests for the object reference check (#5115 step ③-2).

No R2 bucket and no Production D1 is touched: the database is a small SQLite
file and the mirror inventory is a JSON file.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

check_mod = importlib.import_module("chat_object_reference_check")


def _db(path: Path, rows: dict[str, list[tuple]]) -> Path:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE claw_document_metadata "
        "(document_id TEXT PRIMARY KEY, object_key TEXT NOT NULL UNIQUE, filename TEXT)"
    )
    connection.execute(
        "CREATE TABLE b66_quote_asset "
        "(id TEXT PRIMARY KEY, object_key TEXT NOT NULL UNIQUE, byte_length INTEGER)"
    )
    # Not an object key: a D1 row id that merely ends with "_key".
    connection.execute(
        "CREATE TABLE project_files (id TEXT PRIMARY KEY, project_file_key TEXT)"
    )
    for table, values in rows.items():
        for value in values:
            placeholders = ", ".join("?" for _ in value)
            connection.execute(f'INSERT INTO "{table}" VALUES ({placeholders})', value)
    connection.commit()
    connection.close()
    return path


BASE_ROWS = {
    "claw_document_metadata": [
        ("d1", "org/a/doc-1/file.pdf", "file.pdf"),
        ("d2", "org/a/doc-2/sheet.xlsx", "sheet.xlsx"),
    ],
    "b66_quote_asset": [("a1", "org/a/assets/logo.png", 1200)],
    "project_files": [("f1", "org/a/doc-1/file.pdf")],
}

INVENTORY = [
    "org/a/doc-1/file.pdf",
    "org/a/doc-2/sheet.xlsx",
    "org/a/assets/logo.png",
    "org/unused/object.bin",
]


@pytest.fixture()
def pair(tmp_path):
    db = _db(tmp_path / "d1.sqlite3", BASE_ROWS)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps({"keys": INVENTORY}), encoding="utf-8")
    return db, inventory


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_every_referenced_key_is_mirrored(pair, capsys):
    db, inventory = pair
    report = check_mod.check(db, inventory)

    assert report.matches
    assert report.unique_keys == 3
    assert report.missing_keys == 0
    assert check_mod.main(["--db", str(db), "--inventory", str(inventory)]) == check_mod.EXIT_MATCH

    out = capsys.readouterr().out
    assert "CHAT_OBJECT_REFERENCE=MATCH tables=2 inventories=1 keys=3 missing=0" in out
    assert "claw_document_metadata.object_key keys=2 missing=0" in out


def test_a_key_missing_from_the_mirror_is_a_gap(tmp_path, capsys):
    db = _db(
        tmp_path / "d1.sqlite3",
        {
            "claw_document_metadata": [
                ("d1", "org/a/doc-1/file.pdf", "file.pdf"),
                ("d2", "org/a/doc-9/late.pdf", "late.pdf"),
            ]
        },
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(INVENTORY), encoding="utf-8")

    report = check_mod.check(db, inventory)
    assert not report.matches
    assert report.missing_keys == 1
    assert report.missing_digest and len(report.missing_digest) == 64
    assert report.missing_key_values == ["org/a/doc-9/late.pdf"]

    assert check_mod.main(["--db", str(db), "--inventory", str(inventory)]) == check_mod.EXIT_GAP
    out = capsys.readouterr().out
    assert "CHAT_OBJECT_REFERENCE=GAP" in out
    assert "missing=1" in out
    # Object paths are never printed.
    assert "late.pdf" not in out


def test_only_object_key_columns_are_scanned(tmp_path):
    db = _db(tmp_path / "d1.sqlite3", BASE_ROWS)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(INVENTORY), encoding="utf-8")

    columns = check_mod.key_columns(sqlite3.connect(db))
    assert ("claw_document_metadata", "object_key") in columns
    assert ("b66_quote_asset", "object_key") in columns
    assert not any(column == "project_file_key" for _table, column in columns)


@pytest.mark.parametrize(
    "payload",
    [
        ["k1"],
        {"keys": ["k1"]},
        {"objects": [{"key": "k1"}]},
        {"objects": ["k1"]},
    ],
)
def test_inventory_shapes_are_accepted(tmp_path, payload):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    assert check_mod.load_inventory(inventory) == {"k1"}


@pytest.mark.parametrize(
    "payload,reason",
    [
        ({"nope": 1}, "CHAT_OBJECT_INVENTORY_SHAPE_UNKNOWN"),
        ([], "CHAT_OBJECT_INVENTORY_EMPTY"),
    ],
)
def test_bad_inventory_is_refused(tmp_path, payload, reason):
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(payload), encoding="utf-8")
    db = _db(tmp_path / "d1.sqlite3", BASE_ROWS)
    with pytest.raises(check_mod.CheckError) as excinfo:
        check_mod.check(db, inventory)
    assert reason in str(excinfo.value)


def test_a_database_without_key_columns_is_refused(tmp_path):
    db = tmp_path / "d1.sqlite3"
    connection = sqlite3.connect(db)
    connection.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT)")
    connection.commit()
    connection.close()
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(INVENTORY), encoding="utf-8")

    assert check_mod.main(["--db", str(db), "--inventory", str(inventory)]) == check_mod.EXIT_USAGE


def test_a_missing_input_is_a_usage_error(tmp_path):
    assert check_mod.main([
        "--db", str(tmp_path / "absent.sqlite3"),
        "--inventory", str(tmp_path / "absent.json"),
    ]) == check_mod.EXIT_USAGE


def test_the_database_is_never_written(pair, tmp_path):
    db, inventory = pair
    before = (_sha(db), _sha(inventory))
    out = tmp_path / "report.json"

    assert check_mod.main([
        "--db", str(db), "--inventory", str(inventory), "--json", str(out),
    ]) == check_mod.EXIT_MATCH

    assert (_sha(db), _sha(inventory)) == before
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["missing_keys"] == 0
    assert "missing_key_values" not in payload


def test_the_json_report_keeps_keys_out_unless_asked(tmp_path):
    db = _db(
        tmp_path / "d1.sqlite3",
        {"claw_document_metadata": [("d1", "org/a/late.pdf", "late.pdf")]},
    )
    inventory = tmp_path / "inventory.json"
    inventory.write_text(json.dumps(INVENTORY), encoding="utf-8")
    out = tmp_path / "report.json"

    assert check_mod.main([
        "--db", str(db), "--inventory", str(inventory), "--json", str(out),
    ]) == check_mod.EXIT_GAP
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["missing_keys"] == 1
    assert "missing_key_values" not in payload

    assert check_mod.main([
        "--db", str(db), "--inventory", str(inventory),
        "--json", str(out), "--include-keys",
    ]) == check_mod.EXIT_GAP
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["missing_key_values"] == ["org/a/late.pdf"]


def test_a_bom_inventory_is_read(tmp_path, capsys):
    """A Windows-side dump starts with a BOM; it is still a valid inventory."""

    inventory = tmp_path / "inventory.json"
    inventory.write_text("\ufeff" + json.dumps({"keys": INVENTORY}), encoding="utf-8")
    assert check_mod.load_inventory(inventory) == set(INVENTORY)

    db = _db(tmp_path / "d1.sqlite3", {
        "claw_document_metadata": [("d1", "org/a/doc-1/file.pdf", "file.pdf")],
    })
    assert check_mod.main([
        "--db", str(db), "--inventory", str(inventory),
    ]) == check_mod.EXIT_MATCH
    capsys.readouterr()


def test_bucket_inventories_are_unioned(tmp_path, capsys):
    """Each bucket has its own list; a key only has to appear in one of them."""

    db = _db(tmp_path / "d1.sqlite3", BASE_ROWS)
    media = tmp_path / "media.json"
    media.write_text(
        json.dumps({"objects": [{"key": "org/a/doc-1/file.pdf"}]}), encoding="utf-8"
    )
    workspace = tmp_path / "workspace.json"
    workspace.write_text(
        "\ufeff" + json.dumps({
            "keys": ["org/a/doc-2/sheet.xlsx", "org/a/assets/logo.png"],
        }),
        encoding="utf-8",
    )

    report = check_mod.check(db, [media, workspace])
    assert report.matches
    assert report.inventory_files == 2
    assert report.unique_keys == 3

    assert check_mod.main([
        "--db", str(db),
        "--mirror-inventory", str(media),
        "--mirror-inventory", str(workspace),
    ]) == check_mod.EXIT_MATCH
    out = capsys.readouterr().out
    assert "CHAT_OBJECT_REFERENCE=MATCH tables=2 inventories=2 keys=3 missing=0" in out


def test_a_key_in_no_bucket_names_the_table_and_column(tmp_path, capsys):
    db = _db(
        tmp_path / "d1.sqlite3",
        {
            "claw_document_metadata": [("d1", "org/a/doc-1/file.pdf", "file.pdf")],
            "b66_quote_asset": [("a1", "org/a/assets/late.png", 1200)],
        },
    )
    media = tmp_path / "media.json"
    media.write_text(json.dumps(INVENTORY), encoding="utf-8")
    workspace = tmp_path / "workspace.json"
    workspace.write_text(
        json.dumps({"keys": ["org/a/doc-1/file.pdf"]}), encoding="utf-8"
    )

    assert check_mod.main([
        "--db", str(db),
        "--inventory", str(media),
        "--inventory", str(workspace),
    ]) == check_mod.EXIT_GAP

    out = capsys.readouterr().out
    assert "CHAT_OBJECT_MISSING_SOURCES b66_quote_asset.object_key=1" in out
    assert "claw_document_metadata.object_key=0" not in out
    # Counts only: the object path stays out of the log.
    assert "late.png" not in out


def test_the_multi_bucket_digest_ignores_argument_order(tmp_path):
    db = _db(tmp_path / "d1.sqlite3", BASE_ROWS)
    media = tmp_path / "media.json"
    media.write_text(json.dumps({"keys": INVENTORY}), encoding="utf-8")
    workspace = tmp_path / "workspace.json"
    workspace.write_text(
        json.dumps({"keys": ["org/a/doc-1/file.pdf"]}), encoding="utf-8"
    )

    forward = check_mod.check(db, [media, workspace])
    reverse = check_mod.check(db, [workspace, media])
    single = check_mod.check(db, media)

    assert forward.inventory_sha256 == reverse.inventory_sha256
    assert forward.inventory_sha256 != single.inventory_sha256
    assert forward.matches and reverse.matches and single.matches


def test_an_empty_bucket_still_refuses_the_run(tmp_path):
    """A bucket that dumped empty is a broken export, not a bucket without keys."""

    db = _db(tmp_path / "d1.sqlite3", BASE_ROWS)
    media = tmp_path / "media.json"
    media.write_text(json.dumps({"keys": INVENTORY}), encoding="utf-8")
    empty = tmp_path / "workspace.json"
    empty.write_text(json.dumps({"keys": []}), encoding="utf-8")

    with pytest.raises(check_mod.CheckError) as excinfo:
        check_mod.check(db, [media, empty])
    assert "CHAT_OBJECT_INVENTORY_EMPTY" in str(excinfo.value)
