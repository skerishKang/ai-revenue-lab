#!/usr/bin/env python3
"""Owner-authorized production D1 027 exact-schema gate; never reads user rows.

027 is the B66 template-source custody table. It is the one table the
byte-ceiling release chain still needs in the live database: 060 rebuilds
``b66_template_source`` and 061 rebuilds ``b66_quote_asset``, so 060 cannot be
applied before 027 is.

The gate follows the reviewed 026 pattern rather than standing up a second
deployment system. The applied SQL is the pinned merged migration and nothing
else, the live shape is derived by replaying the reviewed sources on SQLite
instead of being hand-written, and the only legal live states are missing,
exact and drift. A drift is never applied. The gate reads schema only: it
never reads a user row and never emits a database identifier.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "apps/padiem-chat/migrations/027_b66_template_source.sql"
# The reviewed 027 source. The 060 gate pins the same file with the
# same digest, so there is one authority for the merged migration.
PINNED_SHA256 = "78ab452740be1144d029d2d5e88a171942f662dc4a5e3aecda62b1881e210374"
TABLE = "b66_template_source"
INDEX = "idx_b66_template_source_owner_workspace_status"
# The only parent table 027 references. The live schema read proves it exists
# before the child table is created, exactly like the 026 gate proves its own
# 014/015 history columns.
PARENT = "users"
PREREQUISITE_MIGRATIONS = ("001_auth_history.sql",)
QUERY = f"""SELECT type,name,sql FROM sqlite_master WHERE name IN ('{TABLE}','{INDEX}') ORDER BY name;
PRAGMA table_info({TABLE});
PRAGMA foreign_key_list({TABLE});
PRAGMA index_xinfo({INDEX});
PRAGMA table_info({PARENT});"""


class GateError(RuntimeError):
    """A fail-closed refusal. The message never carries row content or secrets."""


def assert_additive_only(text: str) -> None:
    """Refuse any statement that is not the reviewed CREATE pair.

    The reviewed 027 migration creates exactly one table and one index. A
    statement that mutates, drops or alters anything is refused here, so a
    changed source can never reach the live database.
    """
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [stmt.strip() for stmt in code.split(";") if stmt.strip()]
    creates = []
    for statement in statements:
        if re.fullmatch(r"PRAGMA foreign_keys\s*=\s*ON", statement, re.IGNORECASE):
            continue
        if re.search(r"\b(ALTER|DROP|UPDATE|INSERT|REPLACE|TRUNCATE|ATTACH|DETACH)\b", statement, re.IGNORECASE):
            raise GateError("approved 027 cannot contain any non-create mutation")
        match = re.fullmatch(
            r"CREATE\s+(TABLE|INDEX)\s+IF\s+NOT\s+EXISTS\s+(\w+)[\s\S]+", statement, re.IGNORECASE
        )
        if match is None:
            raise GateError("approved 027 may only create its table and its index")
        creates.append((match.group(1).upper(), match.group(2)))
    if creates != [("TABLE", TABLE), ("INDEX", INDEX)]:
        raise GateError("approved 027 must create exactly its table and its index")


def assert_approved_source() -> str:
    """Return the reviewed 027 SQL, refusing any change to the pinned file.

    The returned text is the reviewed migration file itself, byte for byte, so
    the applied SQL is the reviewed source and nothing else.
    """
    contents = MIGRATION.read_bytes()
    actual = hashlib.sha256(contents).hexdigest()
    if actual != PINNED_SHA256:
        raise GateError("027 source SHA differs from the reviewed merged migration")
    text = contents.decode("utf-8")
    assert_additive_only(text)
    return text


def normalized(sql: str) -> str:
    sql = re.sub(r"(?i)\bIF NOT EXISTS\b\s*", "", sql)
    return re.sub(r"\s+", "", sql).casefold()


def expected_metadata():
    """Derive the reviewed live shape by replaying the reviewed sources."""
    con = sqlite3.connect(":memory:")
    try:
        con.execute("PRAGMA foreign_keys=ON")
        for name in PREREQUISITE_MIGRATIONS:
            con.executescript((MIGRATION.parent / name).read_text(encoding="utf8"))
        con.executescript(assert_approved_source())
        master = {
            name: (kind, normalized(sql))
            for kind, name, sql in con.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name IN (?,?)", (TABLE, INDEX)
            )
        }
        cols = [(row[1], row[2].upper(), row[3], row[5]) for row in con.execute(
            f"PRAGMA table_info({TABLE})")]
        fks = [(row[2], row[3], row[4], row[6]) for row in con.execute(
            f"PRAGMA foreign_key_list({TABLE})")]
        idx = [(row[0], row[2], row[3], row[5]) for row in con.execute(
            f"PRAGMA index_xinfo({INDEX})")]
        return master, cols, fks, idx
    finally:
        con.close()


def _results(path) -> list[list[dict]]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("success") is not True or not isinstance(doc.get("result"), list):
        raise GateError("D1 API unsuccessful")
    if len(doc["result"]) != 5:
        raise GateError("unexpected D1 metadata query count")
    outputs = []
    for part in doc["result"]:
        if part.get("success") is not True or not isinstance(part.get("results"), list):
            raise GateError("D1 statement result unsuccessful")
        outputs.append(part["results"])
    return outputs


def classify(path: str) -> str:
    """Return MISSING, EXACT or DRIFT from bounded schema-only evidence."""
    master_rows, col_rows, fk_rows, idx_rows, parent_rows = _results(path)
    parent = {row.get("name") for row in parent_rows}
    if "id" not in parent:
        raise GateError("D1 base 001 users table is not ready")
    if not master_rows and not col_rows and not fk_rows and not idx_rows:
        return "MISSING"
    expected_master, expected_cols, expected_fks, expected_idx = expected_metadata()
    if len(master_rows) != 2:
        return "DRIFT"
    actual_master = {}
    for item in master_rows:
        name, kind, sql = item.get("name"), item.get("type"), item.get("sql")
        if not isinstance(sql, str) or name in actual_master or name not in expected_master:
            return "DRIFT"
        actual_master[name] = (kind, normalized(sql))
    cols = [(r.get("name"), str(r.get("type", "")).upper(), r.get("notnull"), r.get("pk"))
            for r in col_rows]
    fks = [(r.get("table"), r.get("from"), r.get("to"), r.get("on_delete")) for r in fk_rows]
    idx = [(r.get("seqno"), r.get("name"), r.get("desc"), r.get("key")) for r in idx_rows]
    return "EXACT" if (
        actual_master == expected_master
        and cols == expected_cols
        and sorted(fks) == sorted(expected_fks)
        and idx == expected_idx
    ) else "DRIFT"


def _pack(con) -> Path:
    import tempfile

    con.row_factory = sqlite3.Row
    out = []
    for stmt in QUERY.split(";"):
        if stmt.strip():
            rows = [dict(x) for x in con.execute(stmt)]
            out.append({"success": True, "results": rows})
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".json", delete=False
    ) as tmp:
        json.dump({"success": True, "result": out}, tmp)
        return Path(tmp.name)


def offline() -> None:
    """Replay the reviewed source and prove the three legal live states."""
    expected_metadata()
    con = sqlite3.connect(":memory:")
    try:
        con.execute("PRAGMA foreign_keys=ON")
        for name in PREREQUISITE_MIGRATIONS:
            con.executescript((MIGRATION.parent / name).read_text(encoding="utf8"))
        missing = _pack(con)
        if classify(str(missing)) != "MISSING":
            raise GateError("027 must be missing before it is applied")
        con.executescript(assert_approved_source())
        ready = _pack(con)
        if classify(str(ready)) != "EXACT":
            raise GateError("027 must be exact after it is applied")
        con.execute(f"DROP INDEX {INDEX}")
        drift = _pack(con)
        if classify(str(drift)) != "DRIFT":
            raise GateError("027 must be drift when its index is missing")
        print("D1_027_APPROVED_SOURCE_SHA=PASS")
        print("D1_027_ADDITIVE_SOURCE_ONLY=PASS")
        print("D1_027_SCHEMA_STATES=MISSING_EXACT_DRIFT_PASS")
        print("D1_027_PARENT_TABLE_CHECK=PASS")
        print("PRODUCTION_MUTATION=0")
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(args) == 1 and args[0] == "offline":
            offline()
            return 0
        if len(args) == 2 and args[0] == "query":
            assert_approved_source()
            Path(args[1]).write_text(json.dumps({"sql": QUERY}), encoding="utf-8")
            return 0
        if len(args) == 2 and args[0] == "payload":
            Path(args[1]).write_text(
                json.dumps({"sql": assert_approved_source()}), encoding="utf-8"
            )
            return 0
        if len(args) == 2 and args[0] == "inspect":
            state = classify(args[1])
            print(f"B62_D1_MIGRATION_027_SCHEMA={state}")
            print("D1_USER_ROW_DATA_READ=0")
            if state == "DRIFT":
                raise GateError("027 schema drift, refusing to apply")
            return 0
        raise GateError("usage: [offline | query OUT | payload OUT | inspect RESPONSE]")
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, GateError) as error:
        print(f"B62_D1_MIGRATION_027_GATE=FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
