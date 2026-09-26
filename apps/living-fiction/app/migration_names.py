"""#3110: migration filenames carry a unique numeric sequence prefix.

Why this module exists
----------------------
The SQLite migration runner (``app.db.apply_migrations``) records the **full
filename** in ``schema_migrations.version`` and skips a file whose name is
already in that set::

    applied.add(row["version"])          # "005_web_sessions.sql"
    if filename in applied:
        continue

That design is sound, and this module must not be read as questioning it. It
records full filenames precisely so that two files may share a numeric prefix
without colliding.

But it means the duplicate prefix cannot be fixed by renaming. Renaming
``005_web_sessions.sql`` to ``006_...`` would make every already-deployed
database see an unfamiliar filename, treat it as a brand-new migration, and
re-run its SQL. It would also collide with the existing
``006_reader_idempotency_key_privacy.sql`` and change the lexicographic order
that the runner relies on. So the history stays exactly as it is, and this
module prevents the condition from recurring.

The contract
------------
Each migration filename is ``NNN_description.sql``:

* ``NNN`` is the sequence prefix -- digits only, and zero-padded to the width
  the directory already uses;
* ``_`` separates the prefix from the description;
* the description is non-empty.
Within a migration directory, at most one filename may carry a given prefix,
with one documented exception: the historical pair below.

The grandfathered pair
----------------------
``005_episode_number_reservations.sql`` and ``005_web_sessions.sql`` both carry
prefix ``005``. They were added in different changes and both are applied in
existing databases. They are listed in :data:`GRANDFATHERED_PREFIXES` and are
allowed to coexist.

The allowlist is deliberately *pair-specific*, not prefix-specific. Allowing
"005 is fine" would permit an arbitrary third ``005_*.sql`` to slip in, which
is exactly the regression this module exists to prevent. A new file may reuse
the literal string ``005_`` only if it is one of the two names already
recorded, and any other file beginning ``005_`` is a failure.

Non-SQL files
-------------
The runner globs ``*.sql``, so only those are migrations. A stray editor swap
file or a README is not a migration and is not validated as one.

Hidden files are the subtle case, and getting it wrong is a real hazard rather
than a style question. ``pathlib.Path.glob("*.sql")`` does **not** exclude
dotfiles: on this repository's Python, ``glob("*.sql")`` returns ``.sql`` and
``.hidden.sql`` alongside the ordinary names. So a hidden ``.sql`` file would be
*applied by the runner* while a validator that skipped it would report success
and validate nothing.

The validator therefore mirrors the runner exactly: anything matching ``*.sql``
is a migration and must parse, hidden or not. That makes a hidden file a naming
error, which is the correct outcome -- the file exists, it is not named like a
migration, and the runner will try to apply it.

Editor residue that does not end in ``.sql`` (``foo.sql.swp``, ``backup~``) is
still ignored, because the runner will not see it either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "GRANDFATHERED_PREFIXES",
    "MigrationNameError",
    "MigrationPrefixCollision",
    "SequencePrefix",
    "parse_sequence_prefix",
    "scan_migration_names",
    "sequence_key",
    "validate_migration_names",
]


#: ``<prefix>_<description>.sql`` with a non-empty description.
#:
#: The prefix is digits only, one or more, so the shape is validated even when
#: the width is inconsistent -- a ``5_`` and a ``005_`` file are the same
#: sequence to a reader even though they sort differently as strings, so the
#: collision check compares the digits, not the padded text.
_MIGRATION_FILENAME = re.compile(r"^(?P<prefix>\d+)_(?P<description>.+)\.sql$")

#: The one historical duplicate, recorded by exact filename.
#:
#: Both files are applied in existing databases, so neither may be renamed. The
#: mapping is from prefix to the exact set of filenames permitted to carry it,
#: which is what makes the allowance a grandfathering of *these two* rather
#: than of the number 005.
GRANDFATHERED_PREFIXES: dict[str, frozenset[str]] = {
    "005": frozenset(
        {
            "005_episode_number_reservations.sql",
            "005_web_sessions.sql",
        }
    ),
}


class MigrationNameError(ValueError):
    """A migration filename does not follow the ``NNN_description.sql`` shape."""


class MigrationPrefixCollision(ValueError):
    """Two migration files claim the same sequence prefix."""


@dataclass(frozen=True)
class SequencePrefix:
    """One migration file's parsed sequence prefix."""

    filename: str
    prefix: str
    description: str

    @property
    def width(self) -> int:
        return len(self.prefix)


def is_migration_file(name: str) -> bool:
    """Whether the runner would treat this name as a migration.

    Mirrors ``Path.glob("*.sql")``, which is **case-sensitive** and does not
    exclude dotfiles. That second detail is load-bearing: skipping a hidden
    ``.sql`` here would let a file through that the runner still applies, so the
    validator would pass while validating nothing.

    Residue that does not end in ``.sql`` is ignored, because the runner will not
    see it either.
    """

    return name.endswith(".sql")


def parse_sequence_prefix(filename: str) -> SequencePrefix:
    """Parse ``NNN_description.sql``.

    Raises :class:`MigrationNameError` when the name does not match, rather
    than returning ``None``. A caller that forgot to handle a bad name would
    otherwise get a silent pass, which for a validator is the dangerous
    outcome.
    """

    match = _MIGRATION_FILENAME.match(filename)
    if match is None:
        raise MigrationNameError(
            f"migration filename {filename!r} does not match "
            "'NNN_description.sql' with a non-empty description"
        )
    return SequencePrefix(
        filename=filename,
        prefix=match.group("prefix"),
        description=match.group("description"),
    )


def sequence_key(filename: str) -> int:
    """The sequence a filename claims, as an integer.

    Zero padding is cosmetic, so ``5_x.sql`` and ``005_x.sql`` claim the same
    position. Keying the collision map on the padded literal instead would file
    them separately and miss the collision, while the runner -- which sorts the
    filenames as strings -- would interleave them confusingly.

    Raises :class:`MigrationNameError` for a name with no parseable prefix, so
    this cannot be used to quietly group malformed files.
    """

    return int(parse_sequence_prefix(filename).prefix)


def scan_migration_names(directory: Path) -> list[str]:
    """Every filename in ``directory`` the runner would apply, sorted.

    Returned as a list rather than a generator so a caller can validate the
    same set twice without a second directory read that could disagree.
    """

    if not directory.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {directory}")

    return sorted(
        entry.name for entry in directory.iterdir() if is_migration_file(entry.name)
    )


def validate_migration_names(directory: Path) -> list[SequencePrefix]:
    """Validate every migration name in ``directory``.

    Returns the parsed prefixes on success. Raises on the first problem, with a
    message naming the files and the prefix involved, because the actionable
    information for an author is the collision set, not the first file scanned.

    Order of checks matters. Malformed names are rejected before collisions,
    so an author is told their filename is wrong rather than being told two
    unrelated files collide.
    """

    filenames = scan_migration_names(directory)
    parsed = [parse_sequence_prefix(name) for name in filenames]

    # Keyed on the integer sequence, not the padded literal, so two spellings of
    # one sequence are recognised as a collision rather than as two buckets.
    by_sequence: dict[int, list[str]] = {}
    for entry in parsed:
        by_sequence.setdefault(int(entry.prefix), []).append(entry.filename)

    # The allowlist is written in the padded form the directory uses, so map
    # each recorded name through the same key.
    grandfathered: dict[int, set[str]] = {}
    for prefix, allowed in GRANDFATHERED_PREFIXES.items():
        grandfathered.setdefault(int(prefix), set()).update(allowed)

    for sequence in sorted(by_sequence):
        owners = by_sequence[sequence]
        if len(owners) < 2:
            continue

        allowed = grandfathered.get(sequence)
        if allowed is not None and set(owners) <= allowed:
            # Exactly the recorded historical pair, and nothing else.
            continue

        unexpected = sorted(set(owners) - (allowed or set()))
        detail = (
            f"unexpected new file(s) with sequence {owners[0].split('_')[0]!r}: "
            f"{', '.join(unexpected)}"
            if unexpected
            else f"sequence {owners[0].split('_')[0]!r} is used by more files "
            "than recorded"
        )
        raise MigrationPrefixCollision(
            f"duplicate migration sequence prefix in {directory.name}: {detail}. "
            f"Files sharing that sequence: {', '.join(sorted(owners))}. "
            f"Applied migrations are tracked by full filename, so renaming an "
            f"existing file would make deployed databases re-run it; give the "
            f"new migration the next unused sequence instead. "
            f"Grandfathered sequences: {sorted(GRANDFATHERED_PREFIXES)}"
        )

    return parsed
