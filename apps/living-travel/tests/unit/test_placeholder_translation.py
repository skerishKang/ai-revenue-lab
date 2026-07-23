"""Unit tests for the SQLite->PostgreSQL placeholder translator."""

from __future__ import annotations

from app.database.postgres import translate_placeholders


class TestTranslatePlaceholders:
    def test_simple_placeholder(self):
        assert translate_placeholders("SELECT * FROM t WHERE id = ?") == (
            "SELECT * FROM t WHERE id = %s"
        )

    def test_multiple_placeholders(self):
        sql = "INSERT INTO t (a, b, c) VALUES (?, ?, ?)"
        assert translate_placeholders(sql) == (
            "INSERT INTO t (a, b, c) VALUES (%s, %s, %s)"
        )

    def test_placeholder_inside_single_quote_not_translated(self):
        sql = "SELECT * FROM t WHERE note = 'what?' AND id = ?"
        assert translate_placeholders(sql) == (
            "SELECT * FROM t WHERE note = 'what?' AND id = %s"
        )

    def test_placeholder_inside_double_quote_not_translated(self):
        sql = 'SELECT * FROM "weird?col" WHERE id = ?'
        assert translate_placeholders(sql) == (
            'SELECT * FROM "weird?col" WHERE id = %s'
        )

    def test_placeholder_inside_line_comment_not_translated(self):
        sql = "SELECT 1 -- where id = ?\nFROM t WHERE id = ?"
        assert translate_placeholders(sql) == (
            "SELECT 1 -- where id = ?\nFROM t WHERE id = %s"
        )

    def test_placeholder_inside_block_comment_not_translated(self):
        sql = "SELECT /* ? */ 1 FROM t WHERE id = ?"
        assert translate_placeholders(sql) == (
            "SELECT /* ? */ 1 FROM t WHERE id = %s"
        )

    def test_literal_percent_escaped(self):
        sql = "SELECT * FROM t WHERE name LIKE '%foo%' AND id = ?"
        assert translate_placeholders(sql) == (
            "SELECT * FROM t WHERE name LIKE '%%foo%%' AND id = %s"
        )

    def test_escaped_single_quote(self):
        sql = "SELECT * FROM t WHERE note = 'it''s ?' AND id = ?"
        assert translate_placeholders(sql) == (
            "SELECT * FROM t WHERE note = 'it''s ?' AND id = %s"
        )

    def test_no_placeholders_unchanged(self):
        sql = "SELECT a, b FROM t ORDER BY created_at DESC"
        assert translate_placeholders(sql) == sql

    def test_dynamic_update_builder(self):
        sql = "UPDATE travelers SET destination = ?, updated_at = ? WHERE id = ?"
        assert translate_placeholders(sql) == (
            "UPDATE travelers SET destination = %s, updated_at = %s WHERE id = %s"
        )
