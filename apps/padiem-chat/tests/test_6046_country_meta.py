"""#6046 storage slice: project files carry a content country.

Existing rows read as kr (the column default), so a Korean user's list is
unchanged. The country is content metadata only — never a jurisdiction or a
storage-region decision.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.project_files import ProjectFileRecord, _from_row
from app.project_file_routes import _parse_project_file_item

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "075_project_files_country.sql"


def test_the_migration_defaults_every_existing_row_to_korea():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "ALTER TABLE project_files ADD COLUMN country" in sql
    assert "NOT NULL DEFAULT 'kr'" in sql
    assert not re.search(r"\bUPDATE\b|\bDELETE\b", sql, re.I), "existing rows must not be rewritten"


def test_a_record_without_a_country_reads_as_korea():
    record = ProjectFileRecord(id="f1", project_id="p1", name="a.txt", media_type="text/plain", content_text="x")
    assert record.country == "kr"
    assert record.public_dict()["country"] == "kr"


def test_a_row_without_the_column_reads_as_korea():
    row = {"id": "f1", "project_id": "p1", "name": "a.txt", "media_type": "text/plain", "content_text": "x"}
    assert _from_row(row).country == "kr"


def test_a_row_with_a_country_keeps_it():
    row = {"id": "f1", "project_id": "p1", "name": "a.txt", "media_type": "text/plain",
           "content_text": "x", "country": "fr"}
    assert _from_row(row).public_dict()["country"] == "fr"


def test_the_create_parser_accepts_the_four_countries_and_defaults_to_korea():
    base = {"name": "a.txt", "media_type": "text/plain", "text": "hello"}
    assert _parse_project_file_item(dict(base))[3] == "kr"
    for country in ("kr", "us", "uk", "fr"):
        assert _parse_project_file_item(dict(base, country=country))[3] == country


@pytest.mark.parametrize("bad", ["de", "KR", "", 3, None])
def test_the_create_parser_refuses_an_unknown_country(bad):
    with pytest.raises(ValueError):
        _parse_project_file_item({"name": "a.txt", "media_type": "text/plain", "text": "hello", "country": bad})


def test_the_create_parser_still_requires_the_document_fields():
    with pytest.raises(ValueError):
        _parse_project_file_item({"name": "a.txt", "country": "us"})
