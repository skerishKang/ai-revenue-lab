# -*- coding: utf-8 -*-
"""The 080 draft must stay additive and fail closed (#3595 follow-up).

The draft is not in the applied migration sequence yet, so this test does not
touch D1. It applies the draft to an in-memory SQLite database shaped like
migration 060's `b66_template_source` and proves three things:

1. every statement is `ALTER TABLE ... ADD COLUMN` (no DROP / CREATE / RENAME,
   no backfill UPDATE or DELETE, i.e. no table rebuild);
2. a pre-existing uploaded row survives with a NULL certification state, which
   means "no certification recorded" and never "pass";
3. the CHECK accepts exactly the five states #3595 names and rejects anything
   else.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DRAFT = ROOT / "docs/products/b66/drafts/080_b66_template_source_certification_state.sql"
DESIGN = ROOT / "docs/products/b66/CERTIFICATION_STATE_080_DESIGN.md"

STATES = (
    "ANALYZED",
    "REPRODUCTION_IN_PROGRESS",
    "CERTIFIED",
    "CERTIFIED_WITH_TOLERANCE",
    "REJECTED",
)

# Column set of b66_template_source as migration 060 leaves it.
MIGRATION_060_SHAPE = """
CREATE TABLE b66_template_source (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    media_type TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    object_key TEXT NOT NULL UNIQUE,
    byte_length INTEGER NOT NULL CHECK (byte_length >= 1),
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('uploaded', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def statements() -> list[str]:
    sql = DRAFT.read_text(encoding="utf-8")
    stripped = re.sub(r"--[^\n]*", "", sql)
    return [part.strip() for part in stripped.split(";") if part.strip()]


def test_draft_is_additive_only():
    parts = statements()
    assert len(parts) == 3
    for part in parts:
        head = " ".join(part.split()[:5]).upper()
        assert head == "ALTER TABLE B66_TEMPLATE_SOURCE ADD COLUMN", part
    for forbidden in ("DROP ", "CREATE ", "RENAME ", "UPDATE ", "DELETE ", "INSERT "):
        assert forbidden not in DRAFT.read_text(encoding="utf-8").upper()


def test_existing_upload_stays_uncertified():
    db = sqlite3.connect(":memory:")
    db.executescript(MIGRATION_060_SHAPE)
    db.execute(
        "INSERT INTO b66_template_source (id,user_id,workspace_id,media_type,"
        "original_filename,object_key,byte_length,sha256,status,created_at,updated_at) "
        "VALUES ('row','u','w','application/pdf','f.pdf','b66/template-source/x',10,"
        "'" + "0" * 64 + "','uploaded','t','t')"
    )
    for part in statements():
        db.execute(part)

    state, evidence, updated = db.execute(
        "SELECT certification_state, certification_evidence_json, "
        "certification_updated_at FROM b66_template_source WHERE id='row'"
    ).fetchone()
    assert (state, evidence, updated) == (None, None, None)
    # The upload lifecycle column is untouched by this draft.
    assert db.execute("SELECT status FROM b66_template_source").fetchone() == ("uploaded",)


def test_only_the_five_named_states_are_accepted():
    db = sqlite3.connect(":memory:")
    db.executescript(MIGRATION_060_SHAPE)
    db.execute(
        "INSERT INTO b66_template_source (id,user_id,workspace_id,media_type,"
        "original_filename,object_key,byte_length,sha256,status,created_at,updated_at) "
        "VALUES ('row','u','w','application/pdf','f.pdf','b66/template-source/x',10,"
        "'" + "0" * 64 + "','uploaded','t','t')"
    )
    for part in statements():
        db.execute(part)

    for state in STATES:
        db.execute("UPDATE b66_template_source SET certification_state=? WHERE id='row'",
                   (state,))
        assert db.execute(
            "SELECT certification_state FROM b66_template_source WHERE id='row'"
        ).fetchone() == (state,)

    for bad in ("NOPE", "certified", "uploaded", ""):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE b66_template_source SET certification_state=? WHERE id='row'",
                       (bad,))


def test_evidence_json_must_be_json_but_has_no_byte_cap():
    """Only validity is enforced: a byte cap here would be an arbitrary number.

    The physical bound is D1's 2 MiB row limit. A long but well-formed evidence
    record (accepted differences, per-gate results) must not be refused by a
    CHECK that guesses at a size.
    """
    db = sqlite3.connect(":memory:")
    db.executescript(MIGRATION_060_SHAPE)
    db.execute(
        "INSERT INTO b66_template_source (id,user_id,workspace_id,media_type,"
        "original_filename,object_key,byte_length,sha256,status,created_at,updated_at) "
        "VALUES ('row','u','w','application/pdf','f.pdf','b66/template-source/x',10,"
        "'" + "0" * 64 + "','uploaded','t','t')"
    )
    for part in statements():
        db.execute(part)

    assert db.execute(
        "SELECT certification_evidence_json FROM b66_template_source WHERE id='row'"
    ).fetchone() == (None,)

    for bad in ("{", "not json", "", "{'a': 1}"):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE b66_template_source SET certification_evidence_json=? WHERE id='row'",
                (bad,),
            )

    long_record = json.dumps({
        "accepted_differences": [
            {"area": f"gate_{n}", "measured_delta_pt": 0.1, "reviewed_by": "owner",
             "reviewed_at": "2026-10-29T00:00:00Z"}
            for n in range(600)
        ],
        "gates": {"TABLE_LINES_BORDERS": True},
    })
    assert len(long_record) > 50_000
    db.execute("UPDATE b66_template_source SET certification_evidence_json=? WHERE id='row'",
               (long_record,))
    assert json.loads(db.execute(
        "SELECT certification_evidence_json FROM b66_template_source WHERE id='row'"
    ).fetchone()[0]) == json.loads(long_record)


def test_draft_is_not_in_the_applied_sequence_yet():
    """Deliberate: a copy under migrations/ would be applied by the next D1 gate.

    Moving it there is its own CTO-ordered step; doing it silently would change
    Production ordering without that decision, so this test refuses the copy.
    """
    assert not (ROOT / "apps/padiem-chat/migrations" / DRAFT.name).exists()


def test_design_names_the_same_states_and_keeps_the_bundle_untouched():
    text = DESIGN.read_text(encoding="utf-8")
    for state in STATES:
        assert state in text
    # The bundle manifest is deliberately out of scope: adding a key there would
    # reject already-issued bundles (exact key-set check in parse_bundle).
    assert "_MANIFEST_KEYS" in text
    assert "migrations/" in text
    assert "미적용" in text
