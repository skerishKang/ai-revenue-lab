"""#5895 ② contract tests for the one general D1 migration gate.

  ONE_WORKFLOW                        = YES
  BASELINE_RECORDS_WITHOUT_EXECUTING  = YES
  WINDOW_STOPS_AT_UP_TO               = YES
  SOURCE_SHA_PINNED                   = YES
  DROP_GUARD_BLOCKS_TABLE_DROP        = YES
  RECORDING_A_DROP_IS_NOT_A_DROP      = YES
  DRIFT_IS_A_HARD_STOP                = YES
  READ_ONLY_SURFACE                   = YES

Everything here runs offline. The "live database" is the same cumulative SQLite
replay the gate uses to derive its representatives, and the "wrangler response"
is the JSON envelope the gate unwraps. No Cloudflare call is made, and a
read-only pass never asks wrangler to create the ledger table.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sqlite3

import pytest

yaml = pytest.importorskip("yaml")

# .github/tests/<this file> -> repository root is two levels up.
ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/b62-d1-migrate-gate.yml"
SCRIPT = ROOT / ".github/scripts/b62_d1_migrate_gate.py"
MIGRATIONS = ROOT / "apps/padiem-chat/migrations"

spec = importlib.util.spec_from_file_location("b62_d1_migrate_gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

CONFIRMATION = "APPLY_B62_D1_MIGRATIONS_FROM_EXACT_MAIN"
LEDGER = gate.LEDGER_TABLE
DESTRUCTIVE = {
    "051_b66_inquiry_quote_skill_assist.sql",
    "060_byte_length_capacity_ceiling_release.sql",
    "061_b66_quote_asset_byte_length_ceiling_release.sql",
    "063_oracle_mesh_dispatch_tool_call_scope.sql",
    "068_project_files_extracted_media.sql",
    "069_project_files_image_media.sql",
    "070_mesh_device_presence_source.sql",
}
UNPROVABLE = {
    "051_b66_inquiry_quote_skill_assist.sql",
    "060_byte_length_capacity_ceiling_release.sql",
    "061_b66_quote_asset_byte_length_ceiling_release.sql",
    "068_project_files_extracted_media.sql",
    "069_project_files_image_media.sql",
}


def replayed_schema(extra: str = "") -> dict[str, set[str]]:
    """The schema a fully-migrated Chat database has, built from the source files."""

    db = sqlite3.connect(":memory:")
    try:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            db.executescript(path.read_text(encoding="utf-8"))
        if extra:
            db.executescript(extra)
        return gate._schema(db)
    finally:
        db.close()


def snapshot_payload(schema: dict[str, set[str]]) -> list[dict]:
    """One execute, one statement: the schema block only."""

    return [
        {
            "success": True,
            "meta": {"duration": 1},
            "results": [
                {"type": "table", "name": name, "tbl_name": name}
                for name in sorted(schema["tables"])
            ],
        }
    ]


def probe_payload(ledger_present: bool) -> list[dict]:
    """The ledger-table probe: zero rows when the table does not exist."""

    return [
        {
            "success": True,
            "meta": {"duration": 1},
            "results": [{"name": LEDGER}] if ledger_present else [],
        }
    ]


def ledger_payload(rows: list[dict[str, object]]) -> list[dict]:
    return [{"results": list(rows)}]


def detail_payload(schema: dict[str, set[str]], tables: list[str]) -> list[dict]:
    blocks = []
    for table in tables:
        columns = sorted(
            name.split(".", 1)[1] for name in schema["columns"] if name.split(".", 1)[0] == table
        )
        blocks.append({"results": [{"cid": index, "name": name}
                                   for index, name in enumerate(columns)]})
        blocks.append({"results": [{"table_name": table, "row_count": 7}]})
    return blocks


def write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# --- the workflow file itself ------------------------------------------------------


def test_one_workflow_with_the_four_dispatch_inputs_and_no_deploy() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    trigger = data.get("on", data.get(True))
    assert set(trigger) == {"workflow_dispatch", "pull_request"}, set(trigger)
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"mode", "target_sha", "up_to", "confirmation", "allow_table_drop"}
    assert inputs["mode"]["options"] == ["readonly", "apply"]
    assert inputs["mode"]["default"] == "readonly"
    assert inputs["up_to"]["default"] == ""
    assert inputs["allow_table_drop"]["default"] is False
    assert inputs["target_sha"]["required"] is True
    assert data["permissions"] == {"contents": "read"}

    jobs = data["jobs"]
    assert set(jobs) == {"source-contract", "readonly", "apply"}
    apply_job = jobs["apply"]
    assert apply_job["needs"] == "readonly"
    assert apply_job["environment"] == "production"
    assert CONFIRMATION in apply_job["if"]
    assert "inputs.mode == 'apply'" in apply_job["if"]
    assert jobs["readonly"]["if"] != apply_job["if"]

    for forbidden in (
        "wrangler deploy", "wrangler@4 deploy", "pages deploy", "time_travel/restore",
    ):
        assert forbidden not in text
    secrets = set(re.findall(r"secrets\.([A-Z0-9_]+)", text))
    assert secrets == {"CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"}, secrets
    assert "PRODUCTION_MUTATION" in text

    # The workflow and the script are one contract: every verb and flag the
    # workflow passes must exist in the script it calls.
    joined = re.sub(r"\\\n\s*", " ", text)
    calls = re.findall(r"python \.github/scripts/b62_d1_migrate_gate\.py ([a-z-]+)([^\n]*)", joined)
    assert len(calls) >= 10, len(calls)
    script = SCRIPT.read_text(encoding="utf-8")
    verbs = set(gate.COMMANDS)
    for verb, tail in calls:
        assert verb in verbs, verb
        for flag in re.findall(r"--[a-z][a-z-]+", tail):
            assert flag in script, f"{verb} {flag}"


def test_exact_main_live_binding_and_readonly_precede_any_mutation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in (
        "PREMUTATION_REF_IS_MAIN=PASS",
        "PREMUTATION_HEAD_MATCHES_TARGET=PASS",
        'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"',
        'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"',
        "PREMUTATION_EXACT_MAIN_SHA=PASS",
        "PADIEM_CHAT_DB",
        "::add-mask::",
        "D1_BINDING_FINGERPRINT",
        "SOURCE_SHA_PINNED=PASS",
    ):
        assert marker in text, marker
    # The first dispatch stopped at this guard, so its form is pinned: a
    # porcelain check of the migration directory, never a commit-to-worktree
    # diff that needs objects a --depth=1 checkout does not carry.
    assert 'git status --porcelain --untracked-files=all -- "${MIGRATIONS_DIR}"' in text
    assert "git diff --quiet" not in text
    # The read-only half must not be able to write, and the mutation must live
    # only in the apply half. Compared on job sections, not the file's prose.
    readonly_section = text[text.index("  readonly:") : text.index("  apply:")]
    apply_section = text[text.index("  apply:") :]
    assert "PRODUCTION_MUTATION=1" not in readonly_section
    assert "PRODUCTION_MUTATION=0" in readonly_section
    assert "PRODUCTION_MUTATION=1" in apply_section
    assert "D1_BINDING_CHANGED_AFTER_READONLY" in apply_section


# --- inventory and representatives -------------------------------------------------


def test_inventory_pins_every_file_and_flags_the_real_rebuilds() -> None:
    inventory = gate.build_inventory("chat")
    assert len(inventory) == len(list(MIGRATIONS.glob("*.sql")))
    assert {item["name"] for item in inventory if item["destructive"]} == DESTRUCTIVE
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in inventory)
    assert all(re.fullmatch(r"\d{3}", item["number"]) for item in inventory)
    # every file with no distinguishing object is one of the sanctioned rebuilds
    assert {i["name"] for i in inventory if i["representative"] is None} == UNPROVABLE
    # 018 names DROP TABLE only inside a comment, so it is not destructive
    assert gate.is_destructive(
        "-- Runtime CREATE TABLE / ALTER TABLE / DROP TABLE stays\nCREATE TABLE t(a);"
    ) is False
    assert gate.is_destructive("DROP TABLE t;") is True


# --- the one-time baseline ---------------------------------------------------------


def with_detail(tmp_path, inventory, schema, name="detail", plan=None):
    """Build the PRAGMA/COUNT response the gate needs for column indicators."""

    tables = gate.detail_tables(
        inventory, max(item["number"] for item in inventory), schema["tables"]
    )
    path = write(tmp_path / f"{name}.json", detail_payload(schema, tables))
    return path, tables


def test_baseline_records_applied_migrations_without_executing_them(tmp_path, capsys) -> None:
    schema = replayed_schema()
    inventory_path = tmp_path / "inventory.json"
    assert gate.main(["inventory", "--app", "chat", "--out", str(inventory_path)]) == 0
    inventory_items = json.loads(inventory_path.read_text(encoding="utf-8"))
    detail_path, detail_tables = with_detail(tmp_path, inventory_items, schema)
    assert detail_tables
    snapshot_path = write(
        tmp_path / "snapshot.json", snapshot_payload(schema)
    )
    probe_path = write(tmp_path / "probe.json", probe_payload(False))
    plan_path = tmp_path / "plan.json"
    assert gate.main([
        "classify", "--app", "chat", "--inventory", str(inventory_path),
        "--snapshot", str(snapshot_path), "--probe", str(probe_path),
        "--detail", str(detail_path),
        "--out", str(plan_path),
    ]) == 0
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["baseline_first_run"] is True
    assert plan["apply"] == [] and plan["drift"] == []
    assert len(plan["seed"]) == len(plan["window"])
    # an empty --up-to resolves to the newest file in this checkout
    assert plan["up_to"] == max(item["number"] for item in json.loads(
        inventory_path.read_text(encoding="utf-8")))
    assert set(plan["seed_without_object_proof"]) == UNPROVABLE
    assert "B62_D1_SEED_WITHOUT_OBJECT_PROOF=" in capsys.readouterr().out

    seed_path = tmp_path / "seed.sql"
    assert gate.main([
        "seed-sql", "--plan", str(plan_path), "--inventory", str(inventory_path),
        "--out", str(seed_path),
    ]) == 0
    statements = seed_path.read_text(encoding="utf-8")
    assert "PRODUCTION_MUTATION=1" in capsys.readouterr().out
    assert statements.count(f'INSERT INTO "{LEDGER}" (name)') == len(plan["seed"])
    upper = statements.upper()
    for forbidden in ("CREATE ", "ALTER ", "DROP ", "DELETE ", "UPDATE ", "PRAGMA "):
        assert forbidden not in upper, forbidden
    assert f"'{plan['seed'][0]}'" in statements

    # Once recorded, the same window is a no-op: nothing to seed, nothing to apply.
    recorded = [{"id": index, "name": name} for index, name in enumerate(plan["seed"], start=1)]
    second_plan = tmp_path / "plan2.json"
    assert gate.main([
        "classify", "--app", "chat", "--inventory", str(inventory_path),
        "--snapshot", str(write(tmp_path / "snapshot2.json", snapshot_payload(schema))),
        "--probe", str(write(tmp_path / "probe2.json", probe_payload(True))),
        "--ledger", str(write(tmp_path / "ledger2.json", ledger_payload(recorded))),
        "--detail", str(detail_path),
        "--out", str(second_plan),
    ]) == 0
    after = json.loads(second_plan.read_text(encoding="utf-8"))
    assert after["baseline_first_run"] is False
    assert after["seed"] == [] and after["apply"] == [] and after["drift"] == []
    # a recorded ledger whose table vanished mid-flight is never seeded again
    assert after["seed_without_object_proof"] == []


# --- window, up_to and source pinning ----------------------------------------------


def use_migrations(tmp_path, extra_sql: str, name: str = "073_pending_thing.sql"):
    """Point the gate at a copy of the real migrations plus one extra file."""

    directory = tmp_path / "migrations"
    directory.mkdir(exist_ok=True)
    for source in sorted(MIGRATIONS.glob("*.sql")):
        (directory / source.name).write_bytes(source.read_bytes())
    (directory / name).write_text(extra_sql, encoding="utf-8")
    original = gate.APPS["chat"]["migrations"]
    gate.APPS["chat"]["migrations"] = directory
    return original


def test_window_applies_only_pending_files_up_to_up_to_and_verifies_bytes(tmp_path) -> None:
    schema = replayed_schema()
    inventory = gate.build_inventory("chat")
    recorded = [{"id": index, "name": item["name"]} for index, item in enumerate(inventory, 1)]
    extra = "CREATE TABLE b62_gate_probe (id INTEGER PRIMARY KEY, label TEXT);\n"
    original = use_migrations(tmp_path, extra)
    try:
        fresh = gate.build_inventory("chat")
        assert len(fresh) == len(inventory) + 1
        # The live database is the state BEFORE the pending file ran: its object
        # is missing, which is what makes it pending rather than unrecorded.
        live = replayed_schema()
        inventory_path = write(tmp_path / "inv.json", fresh)
        detail_path, _tables = with_detail(tmp_path, fresh, live, name="detail73")
        snapshot_path = write(tmp_path / "snap.json", snapshot_payload(live))
        probe_path = write(tmp_path / "probe.json", probe_payload(True))
        ledger_path = write(tmp_path / "ledger.json", ledger_payload(recorded))

        plan_73 = tmp_path / "plan73.json"
        assert gate.main([
            "classify", "--app", "chat", "--inventory", str(inventory_path),
            "--snapshot", str(snapshot_path), "--probe", str(probe_path),
            "--ledger", str(ledger_path),
            "--detail", str(detail_path),
            "--up-to", "073", "--out", str(plan_73),
        ]) == 0
        planned = json.loads(plan_73.read_text(encoding="utf-8"))
        assert planned["apply"] == ["073_pending_thing.sql"]
        assert planned["seed"] == [] and planned["drift"] == []

        window_dir = tmp_path / "window"
        assert gate.main([
            "window", "--app", "chat", "--plan", str(plan_73),
            "--inventory", str(inventory_path), "--dir", str(window_dir),
        ]) == 0
        assert [path.name for path in window_dir.iterdir()] == ["073_pending_thing.sql"]

        # up_to below the pending file leaves an empty window: nothing runs.
        plan_72 = tmp_path / "plan72.json"
        assert gate.main([
            "classify", "--app", "chat", "--inventory", str(inventory_path),
            "--snapshot", str(snapshot_path), "--probe", str(probe_path),
            "--ledger", str(ledger_path),
            "--detail", str(detail_path),
            "--up-to", "072", "--out", str(plan_72),
        ]) == 0
        assert json.loads(plan_72.read_text(encoding="utf-8"))["apply"] == []
        empty = tmp_path / "empty-window"
        assert gate.main([
            "window", "--app", "chat", "--plan", str(plan_72),
            "--inventory", str(inventory_path), "--dir", str(empty),
        ]) == 0
        assert list(empty.iterdir()) == []

        # A byte that differs from the pinned inventory is refused, not applied.
        (tmp_path / "migrations" / "073_pending_thing.sql").write_text(
            extra + "-- drifted\n", encoding="utf-8"
        )
        with pytest.raises(gate.GateError, match="SOURCE_SHA_DRIFT"):
            gate.main([
                "window", "--app", "chat", "--plan", str(plan_73),
                "--inventory", str(inventory_path), "--dir", str(tmp_path / "other-window"),
            ])
    finally:
        gate.APPS["chat"]["migrations"] = original


def test_drop_guard_blocks_an_executed_rebuild_until_the_flag_is_given(tmp_path) -> None:
    schema = replayed_schema()
    recorded = [
        {"id": index, "name": item["name"]}
        for index, item in enumerate(gate.build_inventory("chat"), start=1)
    ]
    # A sanctioned shadow rebuild has to replay cleanly into the cumulative
    # schema, so it creates something to drop before it drops it.
    rebuild = (
        "CREATE TABLE b62_probe_seed (id INTEGER PRIMARY KEY);\n"
        "DROP TABLE b62_probe_seed;\n"
        "CREATE TABLE b62_gate_probe (id INTEGER PRIMARY KEY, extra TEXT);\n"
    )
    original = use_migrations(tmp_path, rebuild, name="073_rebuild_probe.sql")
    try:
        fresh = gate.build_inventory("chat")
        assert any(
            item["name"] == "073_rebuild_probe.sql" and item["destructive"] for item in fresh
        )
        inventory_path = write(tmp_path / "inv.json", fresh)
        detail_path, _tables = with_detail(tmp_path, fresh, schema, name="detail")
        snapshot_path = write(tmp_path / "snap.json", snapshot_payload(schema))
        probe_path = write(tmp_path / "probe.json", probe_payload(True))
        ledger_path = write(tmp_path / "ledger.json", ledger_payload(recorded))
        plan = tmp_path / "plan.json"
        with pytest.raises(gate.GateError, match="DROP_GUARD_REFUSED"):
            gate.main([
                "classify", "--app", "chat", "--inventory", str(inventory_path),
                "--snapshot", str(snapshot_path), "--probe", str(probe_path),
                "--ledger", str(ledger_path),
                "--detail", str(detail_path),
                "--up-to", "073", "--out", str(plan),
            ])
        assert gate.main([
            "classify", "--app", "chat", "--inventory", str(inventory_path),
            "--snapshot", str(snapshot_path), "--probe", str(probe_path),
            "--ledger", str(ledger_path),
            "--detail", str(detail_path),
            "--up-to", "073", "--allow-table-drop", "--out", str(plan),
        ]) == 0
        assert json.loads(plan.read_text(encoding="utf-8"))["apply"] == ["073_rebuild_probe.sql"]
    finally:
        gate.APPS["chat"]["migrations"] = original


# --- ledger integrity --------------------------------------------------------------


def test_recorded_migration_whose_object_is_gone_is_a_hard_stop(tmp_path) -> None:
    schema = replayed_schema()
    inventory = gate.build_inventory("chat")
    empty = {"tables": set(), "columns": set(), "other": set()}
    with pytest.raises(gate.GateError, match="LEDGER_OBJECT_DRIFT"):
        gate.refuse(gate.classify(
            inventory=inventory, ledger=[{"id": 1, "name": "067_mesh_device_presence.sql"}],
            tables=empty["tables"], columns=empty["columns"],
            up_to="072", allow_table_drop=False,
        ))
    with pytest.raises(gate.GateError, match="LEDGER_HAS_UNKNOWN_NAME"):
        gate.classify(
            inventory=inventory, ledger=[{"id": 1, "name": "999_ghost.sql"}],
            tables=schema["tables"], columns=schema["columns"],
            up_to="072", allow_table_drop=False,
        )
    # A clean plan is returned unchanged by the same guard.
    clean = gate.refuse(gate.classify(
        inventory=inventory, ledger=[], tables=schema["tables"], columns=schema["columns"],
        up_to="072", allow_table_drop=False,
    ))
    assert clean["drift"] == [] and clean["refused_drop_guard"] == []


def test_classify_demands_the_ledger_and_column_evidence_it_cannot_guess(tmp_path) -> None:
    schema = replayed_schema()
    inventory_path = tmp_path / "inv.json"
    gate.main(["inventory", "--app", "chat", "--out", str(inventory_path)])
    snapshot_path = write(tmp_path / "snap.json", snapshot_payload(schema))
    probe_path = write(tmp_path / "probe.json", probe_payload(True))
    with pytest.raises(gate.GateError, match="LEDGER_RESPONSE_REQUIRED"):
        gate.main([
            "classify", "--app", "chat", "--inventory", str(inventory_path),
            "--snapshot", str(snapshot_path), "--probe", str(probe_path),
            "--out", str(tmp_path / "plan.json"),
        ])
    # The ledger is there, but a column indicator cannot be proven from
    # sqlite_master: without the PRAGMA response an applied ALTER would look
    # pending and be re-run in Production.
    with pytest.raises(gate.GateError, match="DETAIL_REQUIRED"):
        gate.main([
            "classify", "--app", "chat", "--inventory", str(inventory_path),
            "--snapshot", str(snapshot_path), "--probe", str(probe_path),
            "--ledger", str(write(tmp_path / "ledger.json", ledger_payload([]))),
            "--out", str(tmp_path / "plan.json"),
        ])
    assert not (tmp_path / "plan.json").exists()


# --- read-only surface -------------------------------------------------------------


def test_the_read_only_surface_selects_metadata_and_counts_only(tmp_path, capsys) -> None:
    schema = replayed_schema()
    inventory_path = tmp_path / "inv.json"
    gate.main(["inventory", "--app", "chat", "--out", str(inventory_path)])

    snapshot_sql = tmp_path / "snapshot.sql"
    probe_sql = tmp_path / "probe.sql"
    assert gate.main([
        "snapshot-sql", "--out", str(snapshot_sql), "--probe-out", str(probe_sql),
    ]) == 0
    ledger_sql = tmp_path / "ledger.sql"
    assert gate.main(["ledger-sql", "--out", str(ledger_sql)]) == 0
    detail_sql = tmp_path / "detail.sql"
    snapshot_json = write(tmp_path / "snap.json", snapshot_payload(schema))
    assert gate.main([
        "detail-sql", "--out", str(detail_sql), "--inventory", str(inventory_path),
        "--snapshot", str(snapshot_json),
    ]) == 0

    blob = (snapshot_sql.read_text(encoding="utf-8")
            + probe_sql.read_text(encoding="utf-8")
            + ledger_sql.read_text(encoding="utf-8")
            + detail_sql.read_text(encoding="utf-8"))
    for statement in blob.split(";"):
        text = statement.strip()
        if not text:
            continue
        assert gate.READ_ONLY_RE.match(text), text[:80]
    assert "SELECT *" not in blob.upper()
    # one statement per file: the schema answer carries no second query
    assert "sqlite_master" in snapshot_sql.read_text(encoding="utf-8")
    assert snapshot_sql.read_text(encoding="utf-8").count(";") == 1
    assert probe_sql.read_text(encoding="utf-8").count(";") == 1
    assert f"'{LEDGER}'" in probe_sql.read_text(encoding="utf-8")
    assert f"'{LEDGER}'" not in snapshot_sql.read_text(encoding="utf-8")
    assert f'FROM "{LEDGER}"' in ledger_sql.read_text(encoding="utf-8")

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    up_to = max(item["number"] for item in inventory)
    tables = gate.detail_tables(inventory, up_to, schema["tables"])
    # only column representatives need PRAGMA, so the statement count stays small
    assert tables and len(tables) < 20
    columns, counts = gate.detail_rows(detail_payload(schema, tables), tables)
    assert set(counts) == set(tables)
    assert all(value == 7 for value in counts.values())

    plan = gate.classify(
        inventory=inventory, ledger=[], tables=schema["tables"],
        columns=schema["columns"], up_to="999", allow_table_drop=False,
    )
    assert plan["baseline_first_run"] is True
    assert "PRODUCTION_MUTATION=0" in capsys.readouterr().out


def test_a_wrangler_response_is_parsed_around_its_banner(tmp_path) -> None:
    """The first Production readonly run died here, so the parse is pinned.

    `wrangler d1 execute --json` writes its banner and closing log lines into the
    same stdout as the JSON document, so the response file is not bare JSON.
    """

    schema = replayed_schema()
    payload = json.dumps(snapshot_payload(schema), ensure_ascii=False)
    bannered = (
        "\u26c5\ufe0f wrangler 4.130.0\n\n"
        "⛅️ wrangler: Routing ... executed 18 statements\n" + payload + "\n"
        "🪵  Logs were written to \"/home/runner/.config/.wrangler/logs/wrangler-x.log\"\n"
    )
    path = tmp_path / "snapshot.json"
    path.write_text(bannered, encoding="utf-8")
    probe_path = write(tmp_path / "probe.json", probe_payload(False))
    tables, _columns, _other, ledger_present = gate.snapshot_rows(
        gate.read_json(path), gate.read_json(probe_path)
    )
    assert "users" in tables and ledger_present is False

    plain = tmp_path / "plain.json"
    plain.write_text(payload, encoding="utf-8")
    assert gate.snapshot_rows(gate.read_json(plain), gate.read_json(probe_path)) == (
        tables, _columns, _other, ledger_present,
    )

    noise = tmp_path / "noise.json"
    noise.write_text("wrangler failed: unauthorized\n", encoding="utf-8")
    with pytest.raises(gate.GateError, match="RESPONSE_NOT_JSON"):
        gate.read_json(noise)


def test_the_split_snapshot_parses_every_real_wrangler_response_shape() -> None:
    """The Production readonly run died on the envelope, so every real shape is pinned.

    `wrangler d1 execute --remote --json` has shipped three shapes: the list of
    per-statement blocks, one block dict on its own, and the `/query`-style
    {"result": [...]} wrapper the older gates saw. One statement per execute
    means each answer carries exactly one block, and a probe with zero rows —
    the ledger table does not exist yet — is an answer, not a parse failure.
    """

    schema = replayed_schema()
    rows = [
        {"type": "table", "name": name, "tbl_name": name}
        for name in sorted(schema["tables"])
    ]
    probe_row = [{"type": "table", "name": LEDGER, "tbl_name": LEDGER}]
    shapes = {
        "block_list": lambda r: [{"success": True, "meta": {"duration": 1}, "results": r}],
        "single_block": lambda r: {"success": True, "meta": {"duration": 1}, "results": r},
        "result_wrapper": lambda r: {"success": True, "result": [{"results": r}]},
    }

    for name, wrap in shapes.items():
        tables, columns, other, present = gate.snapshot_rows(wrap(rows), wrap(probe_row))
        assert "users" in tables, name
        assert columns == set(), name
        assert present is True, name

    # ledger table absent: the probe answers zero rows, which plans a baseline
    for name, wrap in shapes.items():
        tables, _c, _o, present = gate.snapshot_rows(wrap(rows), wrap([]))
        assert "users" in tables and present is False, name

    # shapes may also be mixed between the two executes
    tables, _c, _o, present = gate.snapshot_rows(
        shapes["single_block"](rows), shapes["block_list"](probe_row)
    )
    assert "users" in tables and present is True

    # a schema answer with two blocks is the run's own bug, not a real shape
    with pytest.raises(gate.GateError, match="SNAPSHOT_BLOCKS_UNEXPECTED"):
        gate.snapshot_rows(
            shapes["block_list"](rows) + shapes["block_list"](rows),
            shapes["single_block"](probe_row),
        )
    with pytest.raises(gate.GateError, match="PROBE_BLOCKS_UNEXPECTED"):
        gate.snapshot_rows(
            shapes["single_block"](rows), shapes["block_list"](probe_row) + shapes["block_list"](probe_row)
        )


def test_an_import_stats_block_is_a_named_refusal_not_result_rows() -> None:
    """The `--file` path answers with run statistics, and reading that as rows
    would plan against a schema of zero tables and a ledger that exists.

    wrangler v4 `d1 execute --remote --file` runs an import: its one block
    carries the counters row, not query results. Every envelope form must
    refuse it by name.
    """

    stats_block = {
        "success": True,
        "meta": {},
        "results": [{"Timing": 26, "Total queries executed": 2, "Total rows read": 0}],
    }
    for payload in (stats_block, [stats_block], {"success": True, "result": [stats_block]}):
        with pytest.raises(gate.GateError, match="IMPORT_STATS_NOT_ROWS"):
            gate.snapshot_rows(payload, probe_payload(True))
    with pytest.raises(gate.GateError, match="IMPORT_STATS_NOT_ROWS"):
        gate.snapshot_rows(
            [{"success": True, "results": [{"type": "table", "name": "users", "tbl_name": "users"}]}],
            stats_block,
        )


def test_schema_report_names_objects_and_never_row_content(tmp_path, capsys) -> None:
    delta = gate.schema_diff(
        {"tables": {"users"}, "columns": {"users.id"}, "other": set()},
        {"tables": {"users", "b62_gate_probe"}, "columns": {"users.id", "b62_gate_probe.label"},
         "other": {"idx_probe"}},
    )
    assert delta["tables"]["added"] == ["b62_gate_probe"]
    assert delta["columns"]["added"] == ["b62_gate_probe.label"]
    assert delta["other"]["added"] == ["idx_probe"]
    assert delta["tables"]["removed"] == []

    schema = replayed_schema()
    inventory = gate.build_inventory("chat")
    inventory_path = write(tmp_path / "inv.json", inventory)
    snapshot_path = write(tmp_path / "snap.json", snapshot_payload(schema))
    probe_path = write(tmp_path / "probe.json", probe_payload(True))
    detail_path, tables = with_detail(tmp_path, inventory, schema)
    assert gate.main([
        "report",
        "--before", str(snapshot_path), "--before-probe", str(probe_path),
        "--after", str(snapshot_path), "--after-probe", str(probe_path),
        "--detail-before", str(detail_path), "--detail-after", str(detail_path),
        "--inventory", str(inventory_path),
    ]) == 0
    out = capsys.readouterr().out
    assert "B62_D1_SCHEMA_TABLES_ADDED=" in out
    assert "B62_D1_ROW_COUNT conversations=7->7" in out
    assert "B62_D1_REPORT_ROWS=read_count_metadata_only" in out
