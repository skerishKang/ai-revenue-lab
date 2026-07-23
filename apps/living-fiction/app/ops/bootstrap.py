"""Production operator bootstrap for Living Fiction.

Run explicitly by an operator; never at application startup and never in CI:

    python -X utf8 -m app.ops.bootstrap <command>

Commands
--------
    migrate   Apply migrations_postgres/ under an advisory lock (checksum
              verified, idempotent re-run).
    world     Seed the world catalog (idempotent).
    canon     Seed the canon snapshot, checkpoint, and first published canon
              episode (idempotent; ensures the world first).
    reader    Ensure the bootstrap reader exists (idempotent).
    invite    Ensure an active reader-bound invite exists; prints the code
              exactly once when a new one is issued.
    rotate    Revoke every active bound invite and issue a replacement; prints
              the new code exactly once.
    all       migrate, world, canon, then invite (invite ensures the reader).

Connection and secrets
----------------------
Every command connects with ``LF_MIGRATION_DATABASE_URL`` (the owner /
migration-role direct connection) and fails closed when it is missing or is not
a PostgreSQL URL. ``invite``/``rotate`` additionally require
``LF_CREDENTIAL_HMAC_KEY``. Invite codes are CSPRNG-generated and stored ONLY as
keyed HMAC digests; the plaintext code is printed once to the operator terminal
and is never persisted, written to a file, logged elsewhere, or exposed through
any web route. Error messages never include the configured URL or any secret.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app import auth
from app import canon_repository as canon_repo
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app.config import settings
from app.database.errors import ConfigurationError
from app.database.url import is_postgres_url
from app.utils import now_utc_iso

BOOTSTRAP_READER_NAME = "독서자"
APP_ROOT = Path(__file__).resolve().parent.parent.parent
POSTGRES_MIGRATIONS_DIR = APP_ROOT / "migrations_postgres"


def operator_connection() -> Any:
    """Open the owner/migration-role PostgreSQL connection, failing closed.

    Uses ``LF_MIGRATION_DATABASE_URL`` only. The URL is never echoed into the
    raised error.
    """
    url = (settings.migration_database_url or "").strip()
    if not url:
        raise ConfigurationError(
            "LF_MIGRATION_DATABASE_URL must be set to run operator commands"
        )
    if not is_postgres_url(url):
        raise ConfigurationError(
            "LF_MIGRATION_DATABASE_URL is not a valid PostgreSQL connection URL"
        )
    from app.database.postgres import connect_postgres  # noqa: PLC0415

    return connect_postgres(url)


def require_credential_key() -> str:
    """Return the credential HMAC key, failing closed when unset."""
    key = (settings.credential_hmac_key or "").strip()
    if not key:
        raise ConfigurationError(
            "LF_CREDENTIAL_HMAC_KEY must be set to manage invite credentials"
        )
    return key


# ── Idempotent seeding ─────────────────────────────────────────────────────


def ensure_world(conn: Any) -> bool:
    """Seed the world catalog if absent. Returns True when created."""
    from app.preview_data import WORLD_STATE  # noqa: PLC0415

    if world_repo.get_world(conn, WORLD_STATE.world_id) is not None:
        return False
    world_repo.create_world(conn, WORLD_STATE)
    for char in WORLD_STATE.characters:
        world_repo.create_character(
            conn,
            WORLD_STATE.world_id,
            char.character_id,
            char.canonical_name,
            char.role,
            traits=json.dumps(char.knowledge),
            location_id=char.location_id,
        )
    for loc in WORLD_STATE.locations:
        world_repo.create_location(
            conn, WORLD_STATE.world_id, loc.location_id, loc.name
        )
    for clue in WORLD_STATE.clues:
        world_repo.create_clue(
            conn, WORLD_STATE.world_id, clue.clue_id, clue.description
        )
    return True


def ensure_canon(conn: Any) -> bool:
    """Seed the canon snapshot, checkpoint, and first canon episode if absent.

    Ensures the world first. The first canon episode is generated with the
    deterministic free MockProvider and published so readers have a prior
    published episode to branch from. Returns True when created.
    """
    from app.ai.mock import MockProvider  # noqa: PLC0415
    from app.domain.enums import EpisodeType  # noqa: PLC0415
    from app.pipeline.service import (  # noqa: PLC0415
        GenerationRequest,
        generate_canon_episode,
    )
    from app.preview_data import (  # noqa: PLC0415
        CANON_EPISODE_1_CONTENT,
        CANON_EPISODE_1_PLAN,
        WORLD_STATE,
    )

    ensure_world(conn)
    if ep_repo.get_episodes_by_world(conn, WORLD_STATE.world_id, "canon"):
        return False
    canon_repo.create_canon_snapshot(
        conn,
        snapshot_id="snapshot-canon-1",
        world_id=WORLD_STATE.world_id,
        version="v1",
        episode_number=1,
        world_state={},
        character_states={},
        location_states={},
        clue_states={},
        unresolved_threads=[],
        accepted=True,
    )
    canon_repo.create_canon_checkpoint(
        conn,
        checkpoint_id="checkpoint-canon-1",
        canon_snapshot_id="snapshot-canon-1",
        episode_number=1,
        label="After episode 1",
        is_compatible_for_rejoin=True,
    )
    provider = MockProvider(
        task_payloads={
            "episode_plan": CANON_EPISODE_1_PLAN,
            "episode_content": CANON_EPISODE_1_CONTENT,
        }
    )
    request = GenerationRequest(
        world=WORLD_STATE,
        episode_type=EpisodeType.CANON,
        is_first_canon=True,
    )
    result = generate_canon_episode(
        conn, provider, request, world_id=WORLD_STATE.world_id
    )
    if not result.succeeded:
        raise RuntimeError(f"canon episode generation failed: {result.error}")
    ep_repo.publish_episode(conn, result.episode_id)
    return True


def ensure_bootstrap_reader(conn: Any, display_name: str = BOOTSTRAP_READER_NAME) -> str:
    """Return the active bootstrap reader ID, creating the reader if needed."""
    row = conn.execute(
        "SELECT id FROM readers WHERE display_name = ? AND status = 'active' "
        "ORDER BY created_at ASC LIMIT 1",
        (display_name,),
    ).fetchone()
    if row is not None:
        return row["id"]
    return reader_repo.create_reader(conn, display_name=display_name).id


def active_bound_invite_id(conn: Any) -> str | None:
    """Return the ID of a usable (bound, unrevoked, unexpired) invite, if any."""
    rows = conn.execute(
        "SELECT id, expires_at FROM invite_credentials "
        "WHERE bound_reader_id IS NOT NULL AND revoked_at IS NULL "
        "ORDER BY created_at ASC",
    ).fetchall()
    now = now_utc_iso()
    for row in rows:
        if row["expires_at"] is None or row["expires_at"] >= now:
            return row["id"]
    return None


def issue_invite(conn: Any, hmac_key: str, reader_id: str) -> str:
    """Create a reader-bound invite with no expiry; returns the one-time code."""
    code = auth.generate_invite_code()
    auth.create_invite_credential(
        conn, code, hmac_key, bound_reader_id=reader_id, expires_at=None
    )
    return code


def revoke_active_bound_invites(conn: Any) -> int:
    """Revoke every active bound invite; returns the number revoked."""
    rows = conn.execute(
        "SELECT id FROM invite_credentials "
        "WHERE bound_reader_id IS NOT NULL AND revoked_at IS NULL",
    ).fetchall()
    count = 0
    for row in rows:
        if auth.revoke_invite(conn, row["id"]):
            count += 1
    return count


# ── Commands ───────────────────────────────────────────────────────────────


def cmd_migrate() -> None:
    from app.database.migrate_postgres import (  # noqa: PLC0415
        apply_migrations,
        verify_schema_current,
    )

    conn = operator_connection()
    try:
        newly = apply_migrations(conn, POSTGRES_MIGRATIONS_DIR)
        verify_schema_current(conn, POSTGRES_MIGRATIONS_DIR)
    finally:
        conn.close()
    if newly:
        print(f"[bootstrap] applied {len(newly)} migration(s):")
        for version in newly:
            print(f"  {version}")
    else:
        print("[bootstrap] schema already current — nothing to apply.")


def cmd_world() -> None:
    conn = operator_connection()
    try:
        created = ensure_world(conn)
    finally:
        conn.close()
    print(
        "[bootstrap] world seeded."
        if created
        else "[bootstrap] world already present — skipped."
    )


def cmd_canon() -> None:
    conn = operator_connection()
    try:
        created = ensure_canon(conn)
    finally:
        conn.close()
    print(
        "[bootstrap] canon episode 1 seeded and published."
        if created
        else "[bootstrap] canon episode already present — skipped."
    )


def cmd_reader() -> None:
    conn = operator_connection()
    try:
        reader_id = ensure_bootstrap_reader(conn)
    finally:
        conn.close()
    print(f"[bootstrap] bootstrap reader ready (id={reader_id}).")


def cmd_invite() -> None:
    hmac_key = require_credential_key()
    conn = operator_connection()
    try:
        existing = active_bound_invite_id(conn)
        if existing is not None:
            print(
                "[bootstrap] an active reader-bound invite already exists — "
                "no new code issued."
            )
            return
        reader_id = ensure_bootstrap_reader(conn)
        code = issue_invite(conn, hmac_key, reader_id)
    finally:
        conn.close()
    _print_code_once(code)


def cmd_rotate() -> None:
    hmac_key = require_credential_key()
    conn = operator_connection()
    try:
        revoked = revoke_active_bound_invites(conn)
        reader_id = ensure_bootstrap_reader(conn)
        code = issue_invite(conn, hmac_key, reader_id)
    finally:
        conn.close()
    print(f"[bootstrap] revoked {revoked} active invite(s).")
    _print_code_once(code)


def cmd_all() -> None:
    cmd_migrate()
    cmd_world()
    cmd_canon()
    cmd_invite()


def _print_code_once(code: str) -> None:
    """Display the invite code exactly once on the operator terminal."""
    print()
    print("=" * 60)
    print("  INVITE CODE (displayed once — store it securely)")
    print("=" * 60)
    print()
    print(f"  {code}")
    print()
    print("  The database stores only a keyed HMAC digest of this code,")
    print("  never the plaintext. It cannot be recovered later; rotate")
    print("  to issue a replacement.")
    print()


COMMANDS = {
    "migrate": cmd_migrate,
    "world": cmd_world,
    "canon": cmd_canon,
    "reader": cmd_reader,
    "invite": cmd_invite,
    "rotate": cmd_rotate,
    "all": cmd_all,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.ops.bootstrap",
        description="Living Fiction production operator bootstrap.",
    )
    parser.add_argument(
        "command",
        choices=sorted(COMMANDS),
        help="bootstrap command to run",
    )
    args = parser.parse_args(argv)
    try:
        COMMANDS[args.command]()
    except ConfigurationError as exc:
        # Generic message only — never the URL or any secret.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: bootstrap failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
