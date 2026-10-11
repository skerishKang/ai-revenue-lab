"""#3110: migration sequence prefixes are unique, and the applied history is safe.

The SQLite runner records the **full filename** in ``schema_migrations.version``
and skips any file whose name is already present. That is why the historical
``005`` pair cannot be repaired by renaming: a deployed database would see an
unfamiliar name, treat it as new, and re-run the SQL.

So these tests do two separate jobs, and keeping them separate is the point:

* prove the historical pair is untouched and still applies correctly, in both
  the fresh-database and existing-database paths;
* prove that a *new* duplicate prefix is rejected, including an attempt to
  smuggle a third ``005_`` file in through the grandfather allowance.

Every test that needs a migration directory builds a throwaway one. Nothing
here writes to the real ``migrations/`` directory, and the historical files are
read-only inputs.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.db import apply_migrations, get_connection
from app.migration_names import (
    GRANDFATHERED_PREFIXES,
    MigrationNameError,
    MigrationPrefixCollision,
    is_migration_file,
    parse_sequence_prefix,
    scan_migration_names,
    validate_migration_names,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"

#: The two files that legitimately share prefix 005. Named explicitly rather
#: than derived from the allowlist, so a change to the allowlist cannot quietly
#: redefine what "the historical pair" means in this test.
HISTORICAL_005 = (
    "005_episode_number_reservations.sql",
    "005_web_sessions.sql",
)


@pytest.fixture
def migration_dir():
    """A throwaway migration directory, populated by the test."""
    directory = Path(tempfile.mkdtemp(prefix="lf_migrations_"))
    try:
        yield directory
    finally:
        import shutil

        shutil.rmtree(directory, ignore_errors=True)


def _populate(directory: Path, filenames: list[str]) -> None:
    for name in filenames:
        (directory / name).write_text("SELECT 1;\n", encoding="utf-8")


def _db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="lf_3110_")
    os.close(fd)
    os.unlink(path)
    return path


# ---------------------------------------------------------------------------
# The applied history is unchanged
# ---------------------------------------------------------------------------


def test_no_historical_migration_file_was_renamed() -> None:
    """The grandfathered pair must exist under its original names.

    Asserted against the real directory, and by exact name. A rename would
    still leave *some* pair sharing 005, so only naming them proves the history
    was preserved.
    """

    names = set(scan_migration_names(MIGRATIONS))
    for filename in HISTORICAL_005:
        assert filename in names, (
            f"{filename} was renamed. Applied migrations are tracked by full "
            "filename, so renaming makes deployed databases re-run the SQL."
        )


def test_the_historical_005_files_still_both_apply_on_a_fresh_database() -> None:
    """FRESH_DB_MIGRATION: every migration applies once, in filename order."""

    conn = get_connection(_db_path())
    try:
        applied = apply_migrations(conn, str(MIGRATIONS))
    finally:
        conn.close()

    for filename in HISTORICAL_005:
        assert applied.count(filename) == 1, (
            f"{filename} applied {applied.count(filename)} times, expected once"
        )

    # Ordering is lexicographic by filename, which is what the runner relies on.
    assert applied == sorted(applied)
    assert applied == [
        "001_initial.sql",
        "002_repair_additive.sql",
        "003_idempotency_continuity_privacy.sql",
        "004_final_contract_repair.sql",
        "005_episode_number_reservations.sql",
        "005_web_sessions.sql",
        "006_reader_idempotency_key_privacy.sql",
        "007_phase2a_hardening.sql",
        "008_phase2b_acceptance.sql",
    ]


def test_restarting_an_existing_database_re_runs_nothing() -> None:
    """UPGRADE_FROM_EXISTING_DB: a restart applies no migration again.

    The full-filename ledger is what makes this safe, and it is the property
    that forbids the rename. Asserting ``applied_at`` is unchanged as well as
    the version set catches a re-run that happened to be idempotent.
    """

    path = _db_path()

    conn = get_connection(path)
    try:
        first = apply_migrations(conn, str(MIGRATIONS))
    finally:
        conn.close()
    assert len(first) == 9

    before = {
        row["version"]: row["applied_at"]
        for row in conn_rows(path)
    }

    conn = get_connection(path)
    try:
        second = apply_migrations(conn, str(MIGRATIONS))
    finally:
        conn.close()

    after = {row["version"]: row["applied_at"] for row in conn_rows(path)}

    assert second == [], f"restart re-applied {second}"
    assert before == after


def conn_rows(path: str) -> list[sqlite3.Row]:
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    try:
        return list(raw.execute("SELECT version, applied_at FROM schema_migrations"))
    finally:
        raw.close()


def test_an_existing_database_still_accepts_a_genuinely_new_migration() -> None:
    """The ledger distinguishes a new file from a renamed one.

    A new migration added to an already-current database is applied exactly
    once. A renamed historical file would also be applied, which is why the
    rename is unsafe and the validator exists. Both halves are asserted here so
    the safety argument is not one-sided.
    """

    path = _db_path()
    conn = get_connection(path)
    try:
        apply_migrations(conn, str(MIGRATIONS))
    finally:
        conn.close()

    # A copy of the directory with one extra, properly numbered migration.
    import shutil

    staged = Path(tempfile.mkdtemp(prefix="lf_staged_"))
    try:
        for source in MIGRATIONS.iterdir():
            if source.is_file():
                shutil.copy2(source, staged / source.name)
        (staged / "009_added_later.sql").write_text("SELECT 1;\n", encoding="utf-8")

        conn = get_connection(path)
        try:
            applied = apply_migrations(conn, str(staged))
        finally:
            conn.close()

        assert applied == ["009_added_later.sql"]
    finally:
        shutil.rmtree(staged, ignore_errors=True)


# ---------------------------------------------------------------------------
# New duplicate prefixes are rejected
# ---------------------------------------------------------------------------


def test_the_real_directory_validates() -> None:
    """The shipped migrations directory satisfies the contract as it stands."""

    parsed = validate_migration_names(MIGRATIONS)
    assert [entry.filename for entry in parsed] == scan_migration_names(MIGRATIONS)


def test_the_historical_pair_alone_is_allowed(migration_dir) -> None:
    _populate(migration_dir, ["001_initial.sql", *HISTORICAL_005])

    parsed = validate_migration_names(migration_dir)
    assert len(parsed) == 3


def test_a_third_005_file_is_rejected(migration_dir) -> None:
    """The grandfather allowance must not become a prefix-wide exemption."""

    _populate(
        migration_dir,
        ["001_initial.sql", *HISTORICAL_005, "005_new_duplicate.sql"],
    )

    with pytest.raises(MigrationPrefixCollision) as excinfo:
        validate_migration_names(migration_dir)

    message = str(excinfo.value)
    assert "005_new_duplicate.sql" in message
    assert "005_episode_number_reservations.sql" in message
    assert "005_web_sessions.sql" in message


def test_a_pair_with_grandfathered_names_but_removed_history_is_rejected(
    migration_dir,
) -> None:
    """The allowlist is a set equality, not a prefix exemption.

    If the historical files were ever removed, the remaining 005 must not stay
    grandfathered forever.
    """

    _populate(migration_dir, ["001_initial.sql", "005_episode_number_reservations.sql", "005_other.sql"])

    with pytest.raises(MigrationPrefixCollision):
        validate_migration_names(migration_dir)


def test_a_duplicate_prefix_outside_the_allowlist_is_rejected(migration_dir) -> None:
    _populate(migration_dir, ["001_initial.sql", "002_a.sql", "002_b.sql"])

    with pytest.raises(MigrationPrefixCollision) as excinfo:
        validate_migration_names(migration_dir)
    assert "002_a.sql" in str(excinfo.value)
    assert "002_b.sql" in str(excinfo.value)


def test_sequential_prefixes_are_accepted(migration_dir) -> None:
    _populate(
        migration_dir,
        ["001_init.sql", "002_episode.sql", "010_whatever.sql"],
    )

    assert len(validate_migration_names(migration_dir)) == 3


@pytest.mark.parametrize(
    "bad_name",
    [
        "no_prefix.sql",
        "00a_bad.sql",
        "001_.sql",
        "001.sql",
        ".sql",
        "_leading.sql",
    ],
)
def test_malformed_names_are_rejected(migration_dir, bad_name: str) -> None:
    _populate(migration_dir, ["001_init.sql", bad_name])

    with pytest.raises(MigrationNameError):
        validate_migration_names(migration_dir)


def test_a_missing_directory_is_an_error_not_a_pass() -> None:
    """A typo in the path must fail, not silently validate nothing."""

    with pytest.raises(FileNotFoundError):
        validate_migration_names(Path("/nonexistent/migrations/3110"))


# ---------------------------------------------------------------------------
# Non-migration files are not migrations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "README.md",
        "notes.txt",
        "backup~",
        "editor.sql.swp",
    ],
)
def test_non_migration_files_are_ignored(migration_dir, name: str) -> None:
    """A stray file must not be validated as a migration.

    The runner globs ``*.sql``, so these are not migrations and rejecting them
    would break a developer's editor rather than protect the history.
    """

    (migration_dir / name).write_text("not a migration\n", encoding="utf-8")
    _populate(migration_dir, ["001_init.sql"])

    assert not is_migration_file(name)
    assert scan_migration_names(migration_dir) == ["001_init.sql"]
    assert len(validate_migration_names(migration_dir)) == 1


def test_a_hidden_sql_file_is_treated_as_a_migration_and_rejected(
    migration_dir,
) -> None:
    """A hidden ``.sql`` file is a hazard, so it must be a naming error.

    ``Path.glob("*.sql")`` does not exclude dotfiles -- verified against this
    repository's Python. A validator that skipped hidden files would therefore
    ignore a file the runner still *applies*, passing while validating nothing.
    The only safe behaviour is to treat it as a migration and demand a proper
    name.
    """

    _populate(migration_dir, ["001_init.sql"])
    (migration_dir / ".hidden.sql").write_text("SELECT 1;\n", encoding="utf-8")

    # The runner would apply it, so the validator must not ignore it.
    assert sorted(p.name for p in migration_dir.glob("*.sql")) == [
        ".hidden.sql",
        "001_init.sql",
    ]
    assert is_migration_file(".hidden.sql")

    with pytest.raises(MigrationNameError) as excinfo:
        validate_migration_names(migration_dir)
    assert ".hidden.sql" in str(excinfo.value)


def test_a_hidden_file_with_a_valid_name_is_still_validated(migration_dir) -> None:
    """A hidden file is validated, and a malformed hidden name is an error.

    ``.002_b.sql`` does not match ``NNN_description.sql`` -- the leading dot
    sits where the digits must be -- so it is rejected as a naming error rather
    than as a collision. Either way it does not pass, which is the property
    that matters: a hidden file cannot be used to smuggle a duplicate past the
    guard.
    """

    _populate(migration_dir, ["001_init.sql", "002_a.sql"])
    (migration_dir / ".002_b.sql").write_text("SELECT 1;\n", encoding="utf-8")

    assert is_migration_file(".002_b.sql")
    with pytest.raises(MigrationNameError):
        validate_migration_names(migration_dir)


# ---------------------------------------------------------------------------
# Parsing details
# ---------------------------------------------------------------------------


def test_the_prefix_is_digits_and_the_description_is_required() -> None:
    entry = parse_sequence_prefix("007_phase2a_hardening.sql")
    assert entry.prefix == "007"
    assert entry.description == "phase2a_hardening"
    assert entry.width == 3


def test_the_collision_key_is_the_sequence_value_not_the_padded_literal(
    migration_dir,
) -> None:
    """``5_x`` and ``005_x`` are the same sequence, and must collide.

    A naive dictionary keyed on the literal prefix would file ``"5"`` and
    ``"005"`` in different buckets and report no collision, while a reader
    treats them as the same position. The zero padding is cosmetic; the sequence
    is the number.

    These widths do not appear in the repository, so this documents the
    behaviour rather than enforcing a style the current tree happens to satisfy.
    """

    _populate(migration_dir, ["5_x.sql", "005_y.sql"])

    with pytest.raises(MigrationPrefixCollision) as excinfo:
        validate_migration_names(migration_dir)

    message = str(excinfo.value)
    assert "5_x.sql" in message
    assert "005_y.sql" in message


def test_the_sequence_value_normalises_leading_zeros() -> None:
    """Two spellings of the same sequence share one collision key."""

    from app.migration_names import sequence_key

    assert sequence_key("005_x.sql") == sequence_key("5_x.sql")
    assert sequence_key("001_a.sql") != sequence_key("002_a.sql")


def test_the_allowlist_names_exactly_the_applied_pair() -> None:
    """The grandfather record must match the files that are actually applied."""

    assert set(GRANDFATHERED_PREFIXES) == {"005"}
    assert GRANDFATHERED_PREFIXES["005"] == frozenset(HISTORICAL_005)

    names = set(scan_migration_names(MIGRATIONS))
    for prefix, allowed in GRANDFATHERED_PREFIXES.items():
        present = {n for n in names if n.startswith(f"{prefix}_")}
        assert present == set(allowed), (
            f"prefix {prefix} is recorded as {sorted(allowed)} but the "
            f"directory holds {sorted(present)}"
        )


def test_a_collision_explains_that_renaming_is_unsafe() -> None:
    """The refusal must tell the author WHY renaming is not the fix.

    Someone who discovers the duplicate prefix will reach for a rename, because
    that is the obvious cleanup and it is what every other migration directory
    looks like. Renaming an applied migration makes deployed databases re-run
    its SQL. If the error message only said "duplicate prefix", the natural
    response would be the destructive one.

    Asserted on the message rather than on the absence of a string in the
    source, so the guidance cannot be quietly dropped during an edit.
    """

    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        _populate(directory, ["001_init.sql", "002_a.sql", "002_b.sql"])

        with pytest.raises(MigrationPrefixCollision) as excinfo:
            validate_migration_names(directory)

    message = str(excinfo.value)
    assert "re-run" in message, (
        "the refusal must say that renaming re-runs applied SQL, or the "
        "obvious fix is the destructive one"
    )
    assert "filename" in message
    # It must also point at a constructive alternative.
    assert "next unused sequence" in message
    # And name the grandfathered case, so an author who meant to extend it
    # learns that it is a recorded exception rather than a free-form one.
    assert "Grandfathered" in message
    assert "005" in message
    assert len(message) < 1200, "an over-long refusal is not read in a CI log"
