"""World, character, location, and clue repository.

Stores the canonical world state. World records are independent from
sibling apps. The world is the source of truth for all validation.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from app.domain.models import WorldState
from app.reader_repository import RepositoryTransactionError
from app.utils import now_utc_iso


@dataclass(frozen=True)
class WorldRecord:
    id: str
    version: str
    premise: str
    genre: str
    world_rules: str
    canonical_timeline: str
    unresolved_global_questions: str
    created_at: str


class WorldValidationError(ValueError):
    pass


class WorldNotFoundError(RuntimeError):
    pass


def _row_to_record(row: sqlite3.Row) -> WorldRecord:
    return WorldRecord(
        id=row["id"],
        version=row["version"],
        premise=row["premise"],
        genre=row["genre"],
        world_rules=row["world_rules"],
        canonical_timeline=row["canonical_timeline"] or "",
        unresolved_global_questions=row["unresolved_global_questions"] or "",
        created_at=row["created_at"],
    )


def create_world(
    conn: sqlite3.Connection,
    world: WorldState,
) -> WorldRecord:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO worlds "
            "(id, version, premise, genre, world_rules, canonical_timeline, "
            "unresolved_global_questions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                world.world_id,
                world.version,
                world.premise,
                world.genre,
                json.dumps([r.model_dump() for r in world.world_rules]),
                json.dumps(world.canonical_timeline),
                json.dumps(world.unresolved_global_questions),
                now,
            ),
        )
        conn.commit()
        return WorldRecord(
            id=world.world_id,
            version=world.version,
            premise=world.premise,
            genre=world.genre,
            world_rules=json.dumps([r.model_dump() for r in world.world_rules]),
            canonical_timeline=json.dumps(world.canonical_timeline),
            unresolved_global_questions=json.dumps(world.unresolved_global_questions),
            created_at=now,
        )
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise WorldValidationError(f"world already exists: {exc}") from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_world(conn: sqlite3.Connection, world_id: str) -> WorldRecord | None:
    row = conn.execute(
        "SELECT * FROM worlds WHERE id = ? ORDER BY version DESC LIMIT 1",
        (world_id,),
    ).fetchone()
    return _row_to_record(row) if row else None


def get_world_by_id_version(
    conn: sqlite3.Connection, world_id: str, version: str
) -> WorldRecord | None:
    row = conn.execute(
        "SELECT * FROM worlds WHERE id = ? AND version = ?",
        (world_id, version),
    ).fetchone()
    return _row_to_record(row) if row else None


# ── Characters ───────────────────────────────────────────────────────────


def create_character(
    conn: sqlite3.Connection,
    world_id: str,
    character_id: str,
    canonical_name: str,
    role: str,
    *,
    aliases: str | None = None,
    traits: str = "[]",
    knowledge_state: str | None = None,
    relationships: str | None = None,
    location_id: str | None = None,
) -> None:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO characters "
            "(id, world_id, canonical_name, aliases, role, traits, "
            "knowledge_state, relationships, location_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (
                character_id, world_id, canonical_name, aliases, role,
                traits, knowledge_state, relationships, location_id, now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise WorldValidationError(f"character already exists: {exc}") from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_character(conn: sqlite3.Connection, character_id: str):
    return conn.execute(
        "SELECT * FROM characters WHERE id = ?",
        (character_id,),
    ).fetchone()


# ── Locations ────────────────────────────────────────────────────────────


def create_location(
    conn: sqlite3.Connection,
    world_id: str,
    location_id: str,
    name: str,
    *,
    physical_properties: str | None = None,
    access_rules: str | None = None,
    known_history: str | None = None,
    connected_locations: str | None = None,
    current_state: str | None = None,
) -> None:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO locations "
            "(id, world_id, name, physical_properties, access_rules, "
            "known_history, connected_locations, current_state, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                location_id, world_id, name, physical_properties,
                access_rules, known_history, connected_locations,
                current_state, now,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise WorldValidationError(f"location already exists: {exc}") from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_location(conn: sqlite3.Connection, location_id: str):
    return conn.execute(
        "SELECT * FROM locations WHERE id = ?",
        (location_id,),
    ).fetchone()


# ── Clues ────────────────────────────────────────────────────────────────


def create_clue(
    conn: sqlite3.Connection,
    world_id: str,
    clue_id: str,
    description: str,
    *,
    introduced_in_episode: str | None = None,
) -> None:
    if conn.in_transaction:
        raise RepositoryTransactionError(
            "repository write requires an idle connection"
        )
    now = now_utc_iso()
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO clues "
            "(id, world_id, description, introduced_in_episode, resolved, "
            "created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (clue_id, world_id, description, introduced_in_episode, now),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise WorldValidationError(f"clue already exists: {exc}") from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def get_clue(conn: sqlite3.Connection, clue_id: str):
    return conn.execute(
        "SELECT * FROM clues WHERE id = ?",
        (clue_id,),
    ).fetchone()
