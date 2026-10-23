"""#5568 — the 066 PDF to Markdown conversion ledger migration gate.

Pins the gate contract for ``066_document_convert_jobs.sql``:

- SOURCE_PINNED=PASS (the reviewed file is the pinned one, a tampered copy is
  refused)
- ADDITIVE_ONLY=PASS (no delete/update/insert/drop/alter/trigger/view/pragma/
  WITHOUT ROWID, and exactly the two reviewed tables and three reviewed indexes)
- SHAPE_MATCHES=PASS (both column sets, both index sets and every reviewed CHECK
  and owner-scoping clause are the ones this gate reviewed)
- OWNER_SCOPING=PASS (a ledger row cannot escape its account, and removing the
  account removes its ledger through the reviewed cascade)
- BOUNDS_ENFORCED=PASS (a done item needs a Markdown object; the verification
  report cannot exceed its ceiling)
- IDEMPOTENT=PASS (re-applying the file changes nothing)
- CLASSIFY=PASS (missing / exact / drift, including a partially applied ledger)
- WORKFLOW_WIRED=PASS (the 066 gate is the only apply path and carries the 066
  safety contract)
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE_WORKFLOW = ROOT / ".github/workflows/b62-d1-migration-066-gate.yml"
HELPER = ROOT / ".github/scripts/b62_d1_migration_066_schema.py"
MIGRATION = ROOT / "apps/padiem-chat/migrations/066_document_convert_jobs.sql"
JOBS_TABLE = "document_convert_jobs"
ITEMS_TABLE = "document_convert_items"
TABLES = (JOBS_TABLE, ITEMS_TABLE)
INDEXES = (
    "idx_document_convert_jobs_recent",
    "idx_document_convert_items_job",
    "idx_document_convert_items_recent",
)


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_d1_066", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _result(rows):
    """A D1 /query response: one statement block per entry."""
    return {
        "success": True,
        "result": [{"success": True, "results": block} for block in rows],
    }


def _exact_payload():
    helper = _load_helper()
    blocks = [
        [
            {"name": table, "type": "table", "sql": f"CREATE TABLE {table} (...)"}
            for table in TABLES
        ]
    ]
    for table in TABLES:
        blocks.append(
            [
                {"name": name, "type": kind, "notnull": notnull, "pk": pk}
                for name, kind, notnull, pk in helper.EXPECTED_COLUMNS[table]
            ]
        )
        blocks.append(
            [
                {"name": name, "origin": "c", "unique": unique, "partial": partial}
                for name, (unique, partial) in helper.EXPECTED_INDEXES[table].items()
            ]
        )
    return _result(blocks)


def _partial_payload():
    """Only the job header table reached the database; the item ledger did not."""
    payload = _exact_payload()
    result = payload["result"]
    result[0]["results"] = result[0]["results"][:1]
    result[3]["results"] = []
    result[4]["results"] = []
    return payload


def _tampered(tmp_path: Path, old: str, new: str) -> Path:
    text = MIGRATION.read_text(encoding="utf-8")
    assert old in text, old
    target = tmp_path / MIGRATION.name
    target.write_text(text.replace(old, new), encoding="utf-8")
    return target


# --------------------------------------------------------------------------
# source contract
# --------------------------------------------------------------------------


def test_source_is_pinned() -> None:
    helper = _load_helper()
    digest = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", helper.PINNED_SHA256)
    assert helper.PINNED_SHA256 == digest, "the pinned 066 digest must match the file"


def test_tampered_migration_hash_is_refused(monkeypatch, tmp_path) -> None:
    """A reviewed-file edit that changes no executable SQL is still refused."""
    helper = _load_helper()
    monkeypatch.setattr(
        helper, "MIGRATION", _tampered(tmp_path, "#5568 PDF to Markdown", "#5569 PDF to Markdown")
    )
    with pytest.raises(ValueError, match="not the pinned reviewed file"):
        helper.source()


def test_offline_contract_passes() -> None:
    helper = _load_helper()
    # Raises on any contract violation.
    helper.source()


def test_migration_is_additive_only() -> None:
    text = MIGRATION.read_text(encoding="utf-8")
    body = "\n".join(line.split("--", 1)[0] for line in text.splitlines()).lower()
    for forbidden in (
        "delete from",
        "update ",
        "insert into",
        "drop ",
        "alter ",
        "trigger",
        "create view",
        "pragma",
        "without rowid",
    ):
        assert forbidden not in body, f"066 must stay additive: {forbidden}"
    for table in TABLES:
        assert f"create table if not exists {table}" in body
    for index in INDEXES:
        assert f"create index if not exists {index}" in body
    assert body.count("create table if not exists") == len(TABLES)
    assert body.count("create index if not exists") == len(INDEXES)


@pytest.mark.parametrize(
    "statement",
    [
        "DROP INDEX idx_document_convert_jobs_recent;",
        "ALTER TABLE document_convert_jobs ADD COLUMN note TEXT;",
        "UPDATE document_convert_jobs SET status = 'failed';",
        "DELETE FROM document_convert_items;",
        "INSERT INTO document_convert_jobs (id, user_id, mode, status, item_count, "
        "created_at, updated_at) VALUES ('x', 'u', 'fast', 'queued', 0, 't', 't');",
        "CREATE TRIGGER audit AFTER INSERT ON document_convert_jobs BEGIN SELECT 1; END;",
        "PRAGMA user_version = 66;",
    ],
)
def test_non_additive_statement_is_refused(tmp_path, statement) -> None:
    helper = _load_helper()
    target = tmp_path / MIGRATION.name
    target.write_text(
        MIGRATION.read_text(encoding="utf-8") + "\n" + statement + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="exceeds the reviewed additive change"):
        helper.source(target)


def test_without_rowid_is_refused(tmp_path) -> None:
    helper = _load_helper()
    target = _tampered(
        tmp_path,
        "  updated_at TEXT NOT NULL\n);\n\nCREATE INDEX IF NOT EXISTS idx_document_convert_jobs_recent",
        "  updated_at TEXT NOT NULL\n) WITHOUT ROWID;\n\nCREATE INDEX IF NOT EXISTS idx_document_convert_jobs_recent",
    )
    with pytest.raises(ValueError, match="without rowid"):
        helper.source(target)


@pytest.mark.parametrize("missing", INDEXES)
def test_missing_index_is_refused(tmp_path, missing) -> None:
    helper = _load_helper()
    text = MIGRATION.read_text(encoding="utf-8")
    pattern = re.compile(
        r"CREATE INDEX IF NOT EXISTS " + missing + r"\n[^;]*;\n", re.IGNORECASE
    )
    assert pattern.search(text), missing
    target = tmp_path / MIGRATION.name
    target.write_text(pattern.sub("", text), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed index exactly once"):
        helper.source(target)


def test_extra_table_is_refused(tmp_path) -> None:
    helper = _load_helper()
    target = tmp_path / MIGRATION.name
    target.write_text(
        MIGRATION.read_text(encoding="utf-8")
        + "\nCREATE TABLE IF NOT EXISTS document_convert_extra (id TEXT);\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="table outside the reviewed set"):
        helper.source(target)


def test_migration_creates_the_reviewed_shape() -> None:
    helper = _load_helper()
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(MIGRATION.read_text(encoding="utf-8"))
        for table in TABLES:
            shape = tuple(
                (row[1], str(row[2]).upper(), int(row[3]), int(row[5]))
                for row in db.execute(f"PRAGMA table_info({table})").fetchall()
            )
            assert shape == helper.EXPECTED_COLUMNS[table], table
            indexes = {
                str(row[1]): (int(row[2]), int(row[4]))
                for row in db.execute(f"PRAGMA index_list({table})").fetchall()
                if str(row[3]).lower() == "c"
            }
            assert indexes == helper.EXPECTED_INDEXES[table], table
    finally:
        db.close()


def test_migration_carries_the_reviewed_clauses() -> None:
    helper = _load_helper()
    db = sqlite3.connect(":memory:")
    try:
        db.executescript(MIGRATION.read_text(encoding="utf-8"))
        for table in TABLES:
            ddl = re.sub(
                r"\s+", " ", db.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
            ).lower()
            for clause in helper.REQUIRED_DDL_CLAUSES[table]:
                assert clause in ddl, (table, clause)
        # The two load-bearing item bounds, named so a reviewer can see them.
        items_ddl = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (ITEMS_TABLE,)
        ).fetchone()[0]
        assert "CHECK (status <> 'done' OR markdown_key IS NOT NULL)" in items_ddl
        assert "CHECK (report_json IS NULL OR length(report_json) <= 12000)" in items_ddl
        for table in TABLES:
            ddl = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            assert "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE" in ddl, table
    finally:
        db.close()


def test_owner_scoping_and_idempotency() -> None:
    db = sqlite3.connect(":memory:")
    try:
        db.executescript("CREATE TABLE users (id TEXT NOT NULL PRIMARY KEY);")
        db.execute("PRAGMA foreign_keys = ON")
        text = MIGRATION.read_text(encoding="utf-8")
        db.executescript(text)
        db.executescript("INSERT INTO users (id) VALUES ('usr_1'), ('usr_2');")

        def insert_job(ident: str, user: str, mode: str = "fast") -> None:
            db.execute(
                f"INSERT INTO {JOBS_TABLE} (id, user_id, mode, status, item_count, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (ident, user, mode, "queued", 0, "t", "t"),
            )

        def insert_item(
            ident: str, job: str, user: str, status: str, markdown: str | None
        ) -> None:
            db.execute(
                f"INSERT INTO {ITEMS_TABLE} (id, job_id, user_id, name, status, page_count, "
                "character_count, original_key, markdown_key, report_json, error_code, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    ident, job, user, "a.pdf", status, 1, 0, "orig/1.pdf", markdown,
                    None, None, "t", "t",
                ),
            )

        insert_job("job_1", "usr_1")
        # A ledger row cannot belong to an account that does not exist.
        with pytest.raises(sqlite3.IntegrityError):
            insert_job("job_ghost", "usr_ghost")
        # Only the reviewed job modes are admitted.
        with pytest.raises(sqlite3.IntegrityError):
            insert_job("job_bad", "usr_1", mode="turbo")
        insert_item("item_1", "job_1", "usr_1", "working", None)
        # An item cannot point at another account, nor at a job that is absent.
        with pytest.raises(sqlite3.IntegrityError):
            insert_item("item_other", "job_1", "usr_ghost", "queued", None)
        with pytest.raises(sqlite3.IntegrityError):
            insert_item("item_orphan", "job_ghost", "usr_1", "queued", None)

        # Done requires the converted Markdown object key.
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"UPDATE {ITEMS_TABLE} SET status = 'done' WHERE id = 'item_1'")
        db.execute(
            f"UPDATE {ITEMS_TABLE} SET status = 'done', markdown_key = 'md/1.md' "
            "WHERE id = 'item_1'"
        )

        # The bounded verification report cannot exceed the reviewed ceiling.
        db.execute(
            f"UPDATE {ITEMS_TABLE} SET report_json = ? WHERE id = 'item_1'",
            ("x" * 12000,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                f"UPDATE {ITEMS_TABLE} SET report_json = ? WHERE id = 'item_1'",
                ("x" * 12001,),
            )

        insert_job("job_2", "usr_2")
        before = (
            db.execute(f"SELECT COUNT(*) FROM {JOBS_TABLE}").fetchone()[0],
            db.execute(f"SELECT COUNT(*) FROM {ITEMS_TABLE}").fetchone()[0],
        )
        # Re-applying the reviewed file is a no-op.
        db.executescript(text)
        assert (
            db.execute(f"SELECT COUNT(*) FROM {JOBS_TABLE}").fetchone()[0],
            db.execute(f"SELECT COUNT(*) FROM {ITEMS_TABLE}").fetchone()[0],
        ) == before

        # Removing the account removes only its own ledger rows.
        db.execute("DELETE FROM users WHERE id = 'usr_1'")
        assert db.execute(
            f"SELECT COUNT(*) FROM {JOBS_TABLE} WHERE user_id = 'usr_1'"
        ).fetchone()[0] == 0
        assert db.execute(
            f"SELECT COUNT(*) FROM {ITEMS_TABLE} WHERE user_id = 'usr_1'"
        ).fetchone()[0] == 0
        assert db.execute(
            f"SELECT COUNT(*) FROM {JOBS_TABLE} WHERE user_id = 'usr_2'"
        ).fetchone()[0] == 1
    finally:
        db.close()


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------


def test_query_covers_every_reviewed_object() -> None:
    helper = _load_helper()
    statements = [s.strip() for s in helper.QUERY.split(";") if s.strip()]
    assert len(statements) == 1 + 2 * len(TABLES)
    for table in TABLES:
        assert any(
            table in statement and statement.lower().startswith("pragma table_info")
            for statement in statements
        ), table
        assert any(
            table in statement and statement.lower().startswith("pragma index_list")
            for statement in statements
        ), table


def test_classify_exact() -> None:
    helper = _load_helper()
    assert helper.classify(_exact_payload()) == "exact"


def test_classify_missing() -> None:
    helper = _load_helper()
    assert helper.classify(_result([[], [], [], [], []])) == "missing"


def test_classify_drift_on_wrong_shape() -> None:
    helper = _load_helper()
    payload = _exact_payload()
    payload["result"][1]["results"] = payload["result"][1]["results"][:-1]
    assert helper.classify(payload) == "drift"


def test_classify_drift_on_missing_index() -> None:
    helper = _load_helper()
    payload = _exact_payload()
    payload["result"][4]["results"] = payload["result"][4]["results"][:1]
    assert helper.classify(payload) == "drift"


def test_classify_drift_when_partially_applied() -> None:
    """Only the job header reached the database: never treated as applicable."""
    helper = _load_helper()
    assert helper.classify(_partial_payload()) == "drift"


def test_classify_drift_on_metadata_without_a_table() -> None:
    helper = _load_helper()
    payload = _result([[], _exact_payload()["result"][1]["results"], [], [], []])
    assert helper.classify(payload) == "drift"


def test_classify_refuses_an_incomplete_response() -> None:
    helper = _load_helper()
    payload = _result([[], [], []])
    with pytest.raises(ValueError, match="D1 schema response incomplete"):
        helper.classify(payload)


def test_cli_markers_are_verbatim_and_single_line(capsys, tmp_path) -> None:
    """The gate compares the classify stdout verbatim, so it must be one line."""
    helper = _load_helper()

    helper.main(["offline"])
    assert capsys.readouterr().out.splitlines() == [
        "B62_D1_MIGRATION_066_SOURCE_CONTRACT=PASS",
        "PRODUCTION_MUTATION=0",
    ]

    query = tmp_path / "query.json"
    helper.main(["query", str(query)])
    assert json.loads(query.read_text(encoding="utf-8")) == {"sql": helper.QUERY}

    response = tmp_path / "response.json"
    for verdict, payload in (
        ("EXACT", _exact_payload()),
        ("MISSING", _result([[], [], [], [], []])),
        ("DRIFT", _partial_payload()),
    ):
        response.write_text(json.dumps(payload), encoding="utf-8")
        capsys.readouterr()
        helper.main(["classify", str(response)])
        assert capsys.readouterr().out.splitlines() == [
            "B62_D1_MIGRATION_066_SCHEMA=" + verdict
        ]

    apply = tmp_path / "apply.json"
    helper.main(["apply", str(apply)])
    payload = json.loads(apply.read_text(encoding="utf-8"))
    # The apply payload is byte-exactly the reviewed migration file.
    assert payload == {"sql": MIGRATION.read_text(encoding="utf-8")}
    assert hashlib.sha256(payload["sql"].encode("utf-8")).hexdigest() == helper.PINNED_SHA256

    applied = tmp_path / "apply-response.json"
    applied.write_text(
        json.dumps({"success": True, "result": [{"success": True}]}), encoding="utf-8"
    )
    capsys.readouterr()
    helper.main(["check-apply", str(applied)])
    assert capsys.readouterr().out.splitlines() == [
        "B62_D1_MIGRATION_066_APPLY_RESPONSE=PASS"
    ]

    # An unsuccessful statement is not reported as applied.
    applied.write_text(
        json.dumps({"success": True, "result": [{"success": False}]}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="returned unsuccessful SQL"):
        helper.main(["check-apply", str(applied)])

    # An API-level failure is not reported as applied either.
    applied.write_text(json.dumps({"success": False, "result": None}), encoding="utf-8")
    with pytest.raises(ValueError, match="returned unsuccessful SQL"):
        helper.main(["check-apply", str(applied)])

    with pytest.raises(ValueError, match="unknown 066 gate operation"):
        helper.main(["drop-table", str(applied)])


# --------------------------------------------------------------------------
# workflow wiring
# --------------------------------------------------------------------------


def test_gate_workflow_is_the_only_apply_path() -> None:
    """The 066 ledger tables are created only through their own pinned gate."""
    text = GATE_WORKFLOW.read_text(encoding="utf-8")
    # An apply mode exists and needs the exact confirmation phrase.
    assert "apply_migration_066" in text
    assert "APPLY_B62_D1_MIGRATION_066_FROM_EXACT_MAIN" in text
    # The apply payload is the reviewed file, never hand-written SQL.
    assert "b62_d1_migration_066_schema.py apply" in text
    # Drift is refused rather than mutated.
    assert "drift)" in text
    # The gate never deploys a Worker.
    assert "wrangler deploy" not in text
    assert "workers/scripts/${B62_WORKER}" in text


def test_gate_workflow_keeps_the_065_safety_contract() -> None:
    text = GATE_WORKFLOW.read_text(encoding="utf-8")
    # Exactly one bounded apply, and only when the ledger is absent.
    assert text.count("b62_d1_migration_066_schema.py apply") == 1
    assert "env.READONLY_SCHEMA_STATE == 'missing'" in text
    assert "env.READONLY_SCHEMA_STATE == 'exact'" in text
    # No automatic rollback and no second mutation path.
    assert "time_travel/restore" not in text
    assert "rollback" not in text.lower()
    # The read-back verdict is compared verbatim.
    assert "B62_D1_MIGRATION_066_SCHEMA=EXACT" in text
    # Bounded evidence only: the gate cannot hang a runner.
    assert text.count("timeout-minutes: 10") == 3
    assert "migrations apply" not in text
    # The existing B62 D1 binding and the two existing secrets, nothing else and
    # no literal credential value.
    assert "D1_BINDING: PADIEM_CHAT_DB" in text
    assert "B62_WORKER: padiem-chat" in text
    used = sorted(set(re.findall(r"secrets\.([A-Z0-9_]+)", text)))
    assert used == ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"]
    assert 'CLOUDFLARE_API_TOKEN: "' not in text
    assert "Authorization: Bearer ${{" not in text


def test_gate_workflow_pins_the_reviewed_066_files() -> None:
    text = GATE_WORKFLOW.read_text(encoding="utf-8")
    for path in (
        ".github/workflows/b62-d1-migration-066-gate.yml",
        ".github/scripts/b62_d1_migration_066_schema.py",
        ".github/tests/test_b62_d1_migration_066_gate.py",
        "apps/padiem-chat/migrations/066_document_convert_jobs.sql",
    ):
        assert path in text, path
    assert "python -m pytest .github/tests/test_b62_d1_migration_066_gate.py -q" in text
    assert "b62_d1_migration_066_schema.py offline" in text
    # The gate is dispatch-only for anything that touches the live database.
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "inputs.mode != 'repository_preflight'" in text
