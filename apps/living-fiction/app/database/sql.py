"""Backend-neutral SQL adaptation for the PostgreSQL adapter.

Repository code is written once against a small, portable SQL subset using ``?``
parameter placeholders and SQLite's ``INSERT OR IGNORE``. These helpers adapt
that subset to PostgreSQL *structurally* — never by naive whole-string ``?`` to
``%s`` replacement, which would corrupt ``?`` characters inside string literals
or quoted identifiers.
"""

from __future__ import annotations

import re


def translate_placeholders(sql: str) -> str:
    """Translate ``?`` parameter placeholders to PostgreSQL ``%s``.

    The scan tracks single-quoted string literals (``'...'`` with ``''`` escapes)
    and double-quoted identifiers (``"..."`` with ``""`` escapes) so a ``?`` that
    is part of a literal or identifier is left untouched. Only placeholders in
    normal SQL context are rewritten.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        out.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif ch == "?":
            out.append("%s")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


_INSERT_OR_IGNORE = re.compile(
    r"^\s*INSERT\s+OR\s+IGNORE\s+", re.IGNORECASE
)


def translate_insert_or_ignore(sql: str) -> str:
    """Rewrite ``INSERT OR IGNORE ...`` as ``INSERT ... ON CONFLICT DO NOTHING``.

    SQLite's ``OR IGNORE`` swallows any conflicting-row error; the PostgreSQL
    equivalent with no conflict target (``ON CONFLICT DO NOTHING``) has the same
    effect for the uniqueness/primary-key conflicts the app relies on. The
    clause is appended after the statement body (before any trailing semicolon).
    Non-``INSERT OR IGNORE`` statements are returned unchanged.
    """
    if not _INSERT_OR_IGNORE.match(sql):
        return sql
    body = _INSERT_OR_IGNORE.sub("INSERT ", sql, count=1)
    stripped = body.rstrip()
    trailing = body[len(stripped):]
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
        trailing = ";" + trailing
    return stripped + " ON CONFLICT DO NOTHING" + trailing


def adapt_sql_for_postgres(sql: str) -> str:
    """Apply all structural SQL adaptations for a single repository statement."""
    return translate_placeholders(translate_insert_or_ignore(sql))
