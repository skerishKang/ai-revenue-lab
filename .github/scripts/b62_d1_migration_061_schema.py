#!/usr/bin/env python3
"""B62 D1 migration 061 gate: the ordered second step of the byte-ceiling release.

060 and 061 are two separate migrations and they are applied in order. 060
released the 10 MiB byte ceiling that 008, 026 and 027 declared on three
canonical D1 metadata tables. 061 releases the 256 KiB byte ceiling that 022
declared on the B66 quote asset metadata, because the application no longer
imposes that total either.

This gate reuses the 060 gate instead of standing up a second deployment
system. It imports the 060 helper's primitives, keeps the 060 gate's
reviewed-source discipline and its fail-closed classification, and adds only
what 061 needs:

* it pins the approved source of 022 and of 061 by SHA-256, so neither of the
  two migrations is ever rewritten and the applied SQL is the reviewed file
  itself, byte for byte;
* it replays 022 and 061 on a real SQLite database and derives the only two
  legal live shapes of the quote asset table: ``pre_061`` (the ceiling is
  still present) and ``exact`` (the ceiling is released);
* it classifies live schema evidence as ``missing``, ``pre_061``, ``exact``
  or ``drift`` and never mutates a database by itself;
* it compares aggregate row counts and foreign-key violation counts around
  the one permitted apply. It reads aggregate counts only, never row content,
  identifiers or secrets;
* it proves the B66 file storage path survives the rebuild: the object key
  stays unique, the owner/workspace/status index is recreated, the foreign key
  to the owner row stays, and a row written the way the application writes it
  is still readable and still valid under the application's own rules.

The order guard is the point of this module. 061 may only be applied to a
database whose 060 tables are already in the released shape, so a database
where 060 has not been applied is refused and 061 can never run first.

Applying 061 to Production is a separate owner-authorized workflow dispatch.
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from b62_d1_migration_060_schema import (  # noqa: E402
    MIGRATIONS,
    PREREQUISITE_MIGRATIONS,
    GateError,
    _blocks,
    _payload_from_connection,
    _rebuild_scope,
    _sha256,
    _shape_from_connection,
    _shape_from_live,
)

ROOT = Path(__file__).resolve().parents[2]
RELEASE = MIGRATIONS / "061_b66_quote_asset_byte_length_ceiling_release.sql"
SOURCE_022 = MIGRATIONS / "022_b66_quote_asset.sql"

# The applied SQL must be exactly the reviewed file. 022 is pinned so that a
# change to the released migration is an explicit, reviewable act, and 061 is
# pinned so that any change to the applied migration is too.
PINNED_SHA256 = {
    SOURCE_022.name: "0d197e4b2064a3d69e6ce277e842bfef613ccef5fee175789bb30cad046f469e",
    RELEASE.name: "419142f8fe91ac37fe2f80961dc79fbb89d3c1fe3520f7e535433ddbef554938",
}

CEILING = "262144"

TABLE = "b66_quote_asset"
INDEX = "idx_b66_quote_asset_owner_workspace_status"

# The columns the application writes and reads. The rebuild must not change
# them: the B66 file storage path is this column set plus the unique object
# key, the owner index and the foreign key to the owner row.
APP_COLUMNS = (
    "id",
    "user_id",
    "workspace_id",
    "asset_kind",
    "media_type",
    "object_key",
    "byte_length",
    "sha256",
    "status",
    "created_at",
    "updated_at",
)

SCHEMA_STATEMENTS = (
    "SELECT type, name, sql FROM sqlite_master WHERE name IN "
    "('b66_quote_asset','idx_b66_quote_asset_owner_workspace_status') ORDER BY name",
    "PRAGMA table_info(b66_quote_asset)",
    "PRAGMA index_list(b66_quote_asset)",
    "PRAGMA foreign_key_list(b66_quote_asset)",
)
SCHEMA_QUERY = ";\n".join(SCHEMA_STATEMENTS)

COUNTS_STATEMENTS = (f"SELECT COUNT(*) AS n FROM {TABLE}",)
COUNTS_QUERY = ";\n".join(COUNTS_STATEMENTS)

FK_STATEMENTS = ("PRAGMA foreign_key_check",)
FK_QUERY = ";\n".join(FK_STATEMENTS)

REBUILD_TABLES = (
    {"table": TABLE, "index": INDEX, "column": "byte_length", "source": SOURCE_022.name},
)


def _statements(text: str) -> list[str]:
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )
    return [statement.strip() for statement in code.split(";") if statement.strip()]


def prerequisite_source() -> str:
    """Return the reviewed 022 source, refusing any change to the pinned file."""
    actual = _sha256(SOURCE_022)
    expected = PINNED_SHA256[SOURCE_022.name]
    if actual != expected:
        raise GateError("022 source SHA differs from the reviewed migration")
    return SOURCE_022.read_text(encoding="utf-8")


def release_source() -> str:
    """Return the reviewed 061 SQL, refusing any change to the pinned file."""
    actual = _sha256(RELEASE)
    expected = PINNED_SHA256[RELEASE.name]
    if actual != expected:
        raise GateError("061 source SHA differs from the reviewed migration")
    return RELEASE.read_text(encoding="utf-8")


def replay_connection(*, with_release: bool) -> sqlite3.Connection:
    """Replay the reviewed migrations on an in-memory database."""
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys=OFF")
    for name in PREREQUISITE_MIGRATIONS:
        con.executescript((MIGRATIONS / name).read_text(encoding="utf-8"))
    con.executescript(prerequisite_source())
    if with_release:
        con.executescript(release_source())
    return con


def expected_shapes(*, with_release: bool) -> dict:
    con = replay_connection(with_release=with_release)
    try:
        return {
            TABLE: _shape_from_connection(con, TABLE, INDEX),
        }
    finally:
        con.close()


def schema_payload(con: sqlite3.Connection) -> dict:
    return _payload_from_connection(con, SCHEMA_STATEMENTS)


def counts_payload(con: sqlite3.Connection) -> dict:
    return _payload_from_connection(con, COUNTS_STATEMENTS)


def fk_payload(con: sqlite3.Connection) -> dict:
    return _payload_from_connection(con, FK_STATEMENTS)


def classify(payload: object) -> str:
    """Return ``missing``, ``pre_061``, ``exact`` or ``drift``."""
    blocks = _blocks(payload, len(SCHEMA_STATEMENTS))
    live = _shape_from_live(
        blocks[0], blocks[1], blocks[2], blocks[3], TABLE, INDEX
    )

    pre = expected_shapes(with_release=False)[TABLE]
    post = expected_shapes(with_release=True)[TABLE]

    if not live["table_sql"]:
        return "missing"
    if live == pre:
        return "pre_061"
    if live == post:
        return "exact"
    return "drift"


def classify_counts(payload: object) -> int:
    blocks = _blocks(payload, len(COUNTS_STATEMENTS))
    if len(blocks[0]) != 1:
        raise GateError(f"unexpected row count evidence for {TABLE}")
    value = blocks[0][0].get("n")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise GateError(f"unreadable row count for {TABLE}")
    return value


def classify_fk(payload: object) -> int:
    blocks = _blocks(payload, len(FK_STATEMENTS))
    violations = 0
    for row in blocks[0]:
        table = row.get("table")
        if not isinstance(table, str):
            # An unreadable violation row must never be counted as "no violation".
            raise GateError("foreign key evidence is malformed")
        if table == TABLE:
            violations += 1
    return violations


def check_counts(before_payload: object, after_payload: object) -> dict[str, int]:
    """Refuse a release that loses rows and report the delta."""
    before = classify_counts(before_payload)
    after = classify_counts(after_payload)
    if after < before:
        raise GateError(f"061 lost rows in {TABLE}")
    return {TABLE: after - before}


def check_fk(before_payload: object, after_payload: object) -> dict[str, int]:
    """Refuse a release that adds foreign key violations to the quote table."""
    before = classify_fk(before_payload)
    after = classify_fk(after_payload)
    if after > before:
        raise GateError(f"061 introduced foreign key violations in {TABLE}")
    return {TABLE: after}


def storage_path_contract(payload: object) -> dict:
    """Prove the B66 file storage path still holds on the live table.

    The storage path is the unique object key, the owner/workspace/status
    index and the foreign key to the owner row. The gate proves the live
    evidence still carries all three, and that the column set is exactly the
    one the application writes.
    """
    blocks = _blocks(payload, len(SCHEMA_STATEMENTS))
    live = _shape_from_live(
        blocks[0], blocks[1], blocks[2], blocks[3], TABLE, INDEX
    )
    if not live["table_sql"]:
        raise GateError(f"{TABLE} is absent; the B66 storage path cannot be verified")
    expected_columns = tuple(
        (name, "INTEGER" if name == "byte_length" else "TEXT")
        for name in APP_COLUMNS
    )
    if tuple((name, kind) for name, kind, _, _ in live["columns"]) != expected_columns:
        raise GateError(f"{TABLE} no longer carries the application column set")
    if "object_key" not in live["table_sql"] or "unique" not in live["table_sql"]:
        raise GateError(f"{TABLE} no longer keeps a unique object key")
    if not any(index[0] == INDEX for index in live["indexes"]):
        raise GateError(f"{TABLE} no longer carries the owner index")
    if not live["index_sql"]:
        raise GateError(f"{TABLE} no longer carries the owner index definition")
    if not any(key[0] == "users" for key in live["foreign_keys"]):
        raise GateError(f"{TABLE} no longer references the owner row")
    return {
        "table": TABLE,
        "columns": len(APP_COLUMNS),
        "object_key_unique": True,
        "index": INDEX,
    }


def source_contract() -> dict:
    """Prove the reviewed sources still describe the reviewed release."""
    prerequisite = prerequisite_source()
    release = release_source()
    if CEILING not in prerequisite:
        raise GateError("022 no longer carries the reviewed 256 KiB ceiling")
    if CEILING in release:
        raise GateError("061 must not re-introduce the 256 KiB ceiling")
    scope = _rebuild_scope(release, REBUILD_TABLES, "061")

    pre = expected_shapes(with_release=False)[TABLE]
    post = expected_shapes(with_release=True)[TABLE]
    ceiling = f"byte_length<={CEILING}"
    if ceiling not in pre["table_sql"]:
        raise GateError(f"{TABLE} no longer carries the reviewed ceiling")
    if ceiling in post["table_sql"]:
        raise GateError(f"{TABLE} still carries the ceiling after 061")
    if pre["table_sql"].replace("and" + ceiling, "") != post["table_sql"]:
        raise GateError(f"{TABLE} changes more than the ceiling in 061")
    for key in ("columns", "indexes", "foreign_keys", "index_sql"):
        if pre[key] != post[key]:
            raise GateError(f"{TABLE} changes {key} in 061")
    if TABLE not in scope:
        raise GateError(f"{TABLE} is not part of the reviewed rebuild")

    replay = replay_connection(with_release=False)
    try:
        user = "usr_" + "a" * 32
        digest = "a" * 64
        asset_id = "b66asset_" + "c" * 32
        replay.execute(
            "INSERT INTO users (id,auth_provider,provider_subject,email,created_at,updated_at)"
            " VALUES (?,'google','subj','a@b.c','2026-01-01','2026-01-01')", (user,),
        )
        # The row is written the way the application writes it: the object key
        # is derived from the asset id and the media type, the status is
        # 'approved' and the length and digest describe the stored bytes.
        replay.execute(
            "INSERT INTO b66_quote_asset (id,user_id,workspace_id,asset_kind,media_type,"
            "object_key,byte_length,sha256,status,created_at,updated_at)"
            " VALUES (?,?,'owner:x','logo','image/png',?,?,?,'approved','2026-01-01','2026-01-01')",
            (asset_id, user, f"b66/quote-assets/{asset_id}.png", 4096, digest),
        )
        replay.executescript(release_source())
        kept = replay.execute(
            "SELECT id,user_id,workspace_id,asset_kind,media_type,object_key,byte_length,"
            "sha256,status,created_at,updated_at FROM b66_quote_asset WHERE id=?",
            (asset_id,),
        ).fetchone()
        if kept is None or len(kept) != len(APP_COLUMNS):
            raise GateError("061 does not preserve the carried quote asset row")
        stored = dict(zip(APP_COLUMNS, kept))
        if stored["object_key"] != f"b66/quote-assets/{asset_id}.png":
            raise GateError("061 does not preserve the B66 object key")
        if stored["byte_length"] < 1:
            raise GateError("061 does not preserve the B66 byte length")
        if not re.fullmatch(r"[0-9a-f]{64}", stored["sha256"]):
            raise GateError("061 does not preserve the B66 digest")
        if stored["status"] != "approved":
            raise GateError("061 does not preserve the B66 asset status")
        if replay.execute("PRAGMA foreign_key_check").fetchall():
            raise GateError("061 leaves foreign key violations behind")
        names = {
            row[0]
            for row in replay.execute(
                "SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        if INDEX not in names:
            raise GateError("061 does not recreate the B66 owner index")
        if [row[0] for row in replay.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_next'"
        )]:
            raise GateError("061 leaves a rebuild table behind")
        try:
            replay.execute(
                "INSERT INTO b66_quote_asset (id,user_id,workspace_id,asset_kind,media_type,"
                "object_key,byte_length,sha256,status,created_at,updated_at)"
                " VALUES (?,?,'owner:x','logo','image/png',?,0,?,'approved','now','now')",
                ("b66asset_" + "d" * 32, user, f"b66/quote-assets/{'d' * 32}.png", digest),
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise GateError("061 must keep refusing a zero-length quote asset row")
    finally:
        replay.close()

    return {
        "sources": sorted(PINNED_SHA256),
        "tables": [TABLE],
        "release": RELEASE.name,
    }


def ordered_state(state_060: str, state_061: str) -> str:
    """Return the ordered state of the two releases.

    ``pre_060`` means neither release is applied yet, ``pre_061`` means 060 is
    applied and 061 is still pending, and ``exact`` means both are applied.
    061 is only ever the next pending step after 060.
    """
    if state_061 == "drift" or state_060 == "drift":
        return "drift"
    if state_061 == "missing" or state_060 == "missing":
        return "missing"
    if state_060 == "exact" and state_061 == "pre_061":
        return "pre_061"
    if state_060 == "pre_060" and state_061 == "pre_061":
        return "pre_060"
    if state_060 == "exact" and state_061 == "exact":
        return "exact"
    # Any other combination is a partially released schema, which this gate
    # never applies again.
    return "drift"


def offline() -> None:
    source_contract()
    pre = expected_shapes(with_release=False)[TABLE]
    post = expected_shapes(with_release=True)[TABLE]
    print("B62_D1_MIGRATION_061_SOURCE_CONTRACT=PASS")
    print("D1_061_APPROVED_SOURCE_SHA=PASS")
    print("D1_061_RELEASED_MIGRATION_022_UNCHANGED=PASS")
    print("D1_061_REBUILD_SCOPE=PASS")
    print("D1_061_ROW_PRESERVATION_REPLAY=PASS")
    print("D1_061_CEILING_RELEASED_FLOOR_KEPT=PASS")
    print("D1_061_B66_STORAGE_PATH=PASS")
    print(
        "D1_061_SCHEMA_STATES="
        + f"{TABLE}:{'PRE' if pre != post else 'SAME'}"
    )
    print("PRODUCTION_MUTATION=0")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args:
            raise GateError("expected an action")
        action = args[0]
        if action == "offline":
            offline()
            return 0
        if action == "query":
            source_contract()
            Path(args[1]).write_text(json.dumps({"sql": SCHEMA_QUERY}), encoding="utf-8")
            return 0
        if action == "counts":
            source_contract()
            Path(args[1]).write_text(json.dumps({"sql": COUNTS_QUERY}), encoding="utf-8")
            return 0
        if action == "fk":
            source_contract()
            Path(args[1]).write_text(json.dumps({"sql": FK_QUERY}), encoding="utf-8")
            return 0
        if action == "classify":
            print(
                "B62_D1_MIGRATION_061_SCHEMA="
                + classify(json.loads(Path(args[1]).read_text(encoding="utf-8"))).upper()
            )
            return 0
        if action == "storage-path":
            contract = storage_path_contract(
                json.loads(Path(args[1]).read_text(encoding="utf-8"))
            )
            print("B66_QUOTE_ASSET_STORAGE_PATH=PASS")
            print("B66_QUOTE_ASSET_STORAGE_PATH=" + json.dumps(contract, sort_keys=True))
            return 0
        if action == "apply":
            # The order guard lives here, in the reviewed script, not in the
            # workflow: 061 may only be emitted for a database whose 060
            # tables are already released and whose quote asset table still
            # carries the ceiling.
            if len(args) != 4:
                raise GateError("expected the 060 evidence, the 061 evidence and the target")
            release_060 = Path(args[1]).read_text(encoding="utf-8")
            release_061 = Path(args[2]).read_text(encoding="utf-8")
            state_060 = classify_060(json.loads(release_060))
            state_061 = classify(json.loads(release_061))
            if state_060 != "exact":
                raise GateError(
                    "061 is refused until the 060 tables are in the released shape"
                )
            if state_061 != "pre_061":
                raise GateError("061 is refused: the quote asset table is not pending")
            source_contract()
            Path(args[3]).write_text(
                json.dumps({"sql": release_source()}), encoding="utf-8"
            )
            print("B62_D1_MIGRATION_061_ORDER_GUARD=PASS")
            return 0
        if action == "check-apply":
            payload = json.loads(Path(args[1]).read_text(encoding="utf-8"))
            blocks = payload.get("result") if isinstance(payload, dict) else None
            if payload.get("success") is not True or not isinstance(blocks, list) or not blocks:
                raise GateError("061 apply returned an unsuccessful response")
            for block in blocks:
                if not isinstance(block, dict) or block.get("success") is not True:
                    raise GateError("061 apply returned an unsuccessful statement")
            print("B62_D1_MIGRATION_061_APPLY_RESPONSE=PASS")
            print(f"B62_D1_MIGRATION_061_APPLY_STATEMENTS={len(blocks)}")
            return 0
        if action == "check-counts":
            deltas = check_counts(
                json.loads(Path(args[1]).read_text(encoding="utf-8")),
                json.loads(Path(args[2]).read_text(encoding="utf-8")),
            )
            print("B62_D1_MIGRATION_061_ROW_COUNTS_PRESERVED=PASS")
            print("B62_D1_MIGRATION_061_ROW_COUNT_DELTAS=" + json.dumps(deltas, sort_keys=True))
            return 0
        if action == "check-fk":
            violations = check_fk(
                json.loads(Path(args[1]).read_text(encoding="utf-8")),
                json.loads(Path(args[2]).read_text(encoding="utf-8")),
            )
            print("B62_D1_MIGRATION_061_FOREIGN_KEYS=PASS")
            print(
                "B62_D1_MIGRATION_061_FOREIGN_KEY_VIOLATIONS="
                + json.dumps(violations, sort_keys=True)
            )
            return 0
        raise GateError(f"unknown 061 gate action: {action}")
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, GateError) as error:
        print(f"B62_D1_MIGRATION_061_GATE=FAIL: {error}", file=sys.stderr)
        return 1


def classify_060(payload: object) -> str:
    """Classify the 060 tables with the 060 gate's own classifier."""
    from b62_d1_migration_060_schema import classify as classify_060_tables

    return classify_060_tables(payload)


if __name__ == "__main__":
    raise SystemExit(main())
