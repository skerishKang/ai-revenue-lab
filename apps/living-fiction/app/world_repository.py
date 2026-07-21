"""World, character, location, and clue repository.

Stores the canonical world state. World records are independent from
sibling apps. The world is the source of truth for all validation.

Includes functions to reconstruct a WorldState from persisted DB records.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from app.domain.models import (
    CharacterRef,
    ClueRef,
    LocationRef,
    WorldRule,
    WorldState,
)
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


# ── WorldState reconstruction from persisted DB records ──────────────────


def load_world_state(
    conn: sqlite3.Connection,
    world_id: str,
) -> WorldState | None:
    """Reconstruct a WorldState from persisted DB records.

    Loads world, characters, locations, and clues from DB.
    Returns None if the world is not found.
    This is the authoritative source — caller-supplied WorldState is
    NOT trusted in production paths.
    """
    world_row = conn.execute(
        "SELECT * FROM worlds WHERE id = ? ORDER BY version DESC LIMIT 1",
        (world_id,),
    ).fetchone()
    if world_row is None:
        return None

    # Characters
    char_rows = conn.execute(
        "SELECT * FROM characters WHERE world_id = ?",
        (world_id,),
    ).fetchall()
    characters: list[CharacterRef] = []
    for cr in char_rows:
        knowledge: list[str] = []
        rels: list[str] = []
        possessions: list[str] = []
        injuries: list[str] = []
        if cr["knowledge_state"]:
            try:
                val = json.loads(cr["knowledge_state"])
                if isinstance(val, list):
                    knowledge = val
            except (json.JSONDecodeError, TypeError):
                pass
        if cr["relationships"]:
            try:
                val = json.loads(cr["relationships"])
                if isinstance(val, list):
                    rels = val
            except (json.JSONDecodeError, TypeError):
                pass
        characters.append(CharacterRef(
            character_id=cr["id"],
            canonical_name=cr["canonical_name"],
            role=cr["role"],
            location_id=cr["location_id"],
            status=cr["status"] or "active",
            knowledge=knowledge,
            relationships=rels,
            possessions=possessions,
            injuries=injuries,
        ))

    # Locations
    loc_rows = conn.execute(
        "SELECT * FROM locations WHERE world_id = ?",
        (world_id,),
    ).fetchall()
    locations: list[LocationRef] = []
    for lr in loc_rows:
        connected: list[str] = []
        if lr["connected_locations"]:
            try:
                val = json.loads(lr["connected_locations"])
                if isinstance(val, list):
                    connected = val
            except (json.JSONDecodeError, TypeError):
                pass
        locations.append(LocationRef(
            location_id=lr["id"],
            name=lr["name"],
            current_state=lr["current_state"] or "",
            connected_locations=connected,
        ))

    # Clues
    clue_rows = conn.execute(
        "SELECT * FROM clues WHERE world_id = ?",
        (world_id,),
    ).fetchall()
    clues: list[ClueRef] = []
    for clr in clue_rows:
        clues.append(ClueRef(
            clue_id=clr["id"],
            description=clr["description"],
            resolved=bool(clr["resolved"]),
        ))

    # World rules
    world_rules: list[WorldRule] = []
    if world_row["world_rules"]:
        try:
            val = json.loads(world_row["world_rules"])
            if isinstance(val, list):
                for rule_dict in val:
                    if isinstance(rule_dict, dict):
                        world_rules.append(WorldRule(**rule_dict))
        except (json.JSONDecodeError, TypeError):
            pass

    # Canonical timeline
    timeline: list[str] = []
    if world_row["canonical_timeline"]:
        try:
            val = json.loads(world_row["canonical_timeline"])
            if isinstance(val, list):
                timeline = val
        except (json.JSONDecodeError, TypeError):
            pass

    # Unresolved questions
    questions: list[str] = []
    if world_row["unresolved_global_questions"]:
        try:
            val = json.loads(world_row["unresolved_global_questions"])
            if isinstance(val, list):
                questions = val
        except (json.JSONDecodeError, TypeError):
            pass

    return WorldState(
        world_id=world_row["id"],
        version=world_row["version"],
        premise=world_row["premise"],
        genre=world_row["genre"] or "urban_mystery",
        world_rules=world_rules,
        characters=characters,
        locations=locations,
        clues=clues,
        canonical_timeline=timeline,
        unresolved_global_questions=questions,
        current_canon_episode=0,
    )
