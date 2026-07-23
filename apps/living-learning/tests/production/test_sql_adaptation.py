"""SQL adaptation contracts (sqlite -> postgres, structural not naive)."""

from __future__ import annotations

from app.production.database import (
    adapt_sql_for_postgres,
    translate_insert_or_ignore,
    translate_placeholders,
)


def test_placeholders_translated():
    assert translate_placeholders("SELECT * FROM t WHERE a = ? AND b = ?") == (
        "SELECT * FROM t WHERE a = %s AND b = %s"
    )


def test_placeholder_inside_string_literal_untouched():
    sql = "SELECT * FROM t WHERE name = 'a ? b' AND x = ?"
    out = translate_placeholders(sql)
    assert "'a ? b'" in out
    assert out.endswith("x = %s")


def test_literal_percent_inside_string_untouched():
    # A % inside a single-quoted literal is part of the value, not a parameter
    # marker, so it is left untouched.
    sql = "SELECT '50%' WHERE x = ?"
    assert translate_placeholders(sql) == "SELECT '50%' WHERE x = %s"


def test_literal_percent_outside_string_escaped():
    # A % outside a string literal is escaped to %% for psycopg.
    sql = "SELECT 50 % 3 WHERE x = ?"
    assert translate_placeholders(sql) == "SELECT 50 %% 3 WHERE x = %s"


def test_insert_or_ignore_to_on_conflict():
    sql = "INSERT OR IGNORE INTO t (a, b) VALUES (?, ?)"
    out = translate_insert_or_ignore(sql)
    assert "INSERT OR IGNORE" not in out
    assert out.startswith("INSERT INTO t")
    assert out.endswith("ON CONFLICT DO NOTHING")


def test_plain_insert_unchanged():
    sql = "INSERT INTO t (a) VALUES (?)"
    assert translate_insert_or_ignore(sql) == sql


def test_adapt_composes_both():
    sql = "INSERT OR IGNORE INTO t (a) VALUES (?)"
    out = adapt_sql_for_postgres(sql)
    assert "ON CONFLICT DO NOTHING" in out
    assert "%s" in out
    assert "?" not in out
