"""Production operator bootstrap for Living Fiction.

Run explicitly by an operator; never at application startup and never in CI:

    python -X utf8 -m app.ops.bootstrap <command>

Commands
--------
    migrate   Apply migrations_postgres/ under an advisory lock (checksum
              verified, idempotent re-run).
    world     Seed the world catalog (repairable; verifies the world body and
              every expected character/location/clue by ID).
    canon     Seed the canon snapshot, checkpoint, and first published canon
              episode (repairable; ensures the world first).
    reader    Ensure the bootstrap reader exists (idempotent).
    invite    Ensure an active invite bound to the bootstrap reader exists;
              prints the code exactly once when a new one is issued.
    rotate    Revoke the bootstrap reader's active invite(s) and issue a
              replacement; prints the new code exactly once.
    all       migrate, world, canon, then invite (invite ensures the reader).

Repairability and atomicity
---------------------------
The repository write methods each commit internally, so a multi-step bootstrap
is NOT a single database transaction and this module does not pretend it is.
Instead every ``ensure_*`` step is independently convergent: it reads the
current state, creates whatever is missing, and FAILS CLOSED when an existing
row conflicts with the expected synthetic data rather than overwriting it. A
bootstrap interrupted at any point therefore converges to the exact complete
state on re-run (see the failure-injection integration tests). Whole-bootstrap
serialization against concurrent operators is provided by a PostgreSQL advisory
lock (:func:`bootstrap_lock`) taken by every command and always released, even
on error.

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
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

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

CANON_SNAPSHOT_ID = "snapshot-canon-1"
CANON_CHECKPOINT_ID = "checkpoint-canon-1"
CANON_VERSION = "v1"
CANON_EPISODE_NUMBER = 1

# Stable advisory-lock key serializing concurrent operator bootstraps. Derived
# from a fixed label so every operator process agrees on the same lock without
# any secret material.
BOOTSTRAP_LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"living-fiction:operator-bootstrap").digest()[:8],
    "big",
    signed=True,
)


class BootstrapConflictError(RuntimeError):
    """Raised when persisted state conflicts with expected bootstrap data.

    Bootstrap never overwrites conflicting rows; it fails closed so an operator
    can inspect the divergence. The message contains only entity identifiers and
    field names — never a database URL or secret.
    """


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


@contextmanager
def bootstrap_lock(conn: Any) -> Iterator[None]:
    """Serialize concurrent operator bootstraps with a PostgreSQL advisory lock.

    Session-level ``pg_advisory_lock`` blocks a second operator until the first
    releases; the ``finally`` guarantees release even when the body raises. Only
    meaningful on the operator's PostgreSQL connection.
    """
    raw = getattr(conn, "raw", conn)
    raw.execute("SELECT pg_advisory_lock(%s)", (BOOTSTRAP_LOCK_KEY,))
    try:
        yield
    finally:
        raw.execute("SELECT pg_advisory_unlock(%s)", (BOOTSTRAP_LOCK_KEY,))


# ── World seeding (repairable, child-by-child) ─────────────────────────────


def _check_field(entity: str, entity_id: str, field: str, expected: Any, actual: Any) -> None:
    if actual != expected:
        raise BootstrapConflictError(
            f"{entity} '{entity_id}' already exists with conflicting {field}: "
            f"expected {expected!r}, found {actual!r}; refusing to overwrite"
        )


def _ensure_characters(conn: Any, world: Any, world_id: str) -> bool:
    created = False
    for char in world.characters:
        existing = world_repo.get_character(conn, char.character_id)
        if existing is None:
            world_repo.create_character(
                conn,
                world_id,
                char.character_id,
                char.canonical_name,
                char.role,
                traits=json.dumps(char.knowledge),
                location_id=char.location_id,
            )
            created = True
        else:
            _check_field("character", char.character_id, "canonical_name",
                         char.canonical_name, existing["canonical_name"])
            _check_field("character", char.character_id, "role",
                         char.role, existing["role"])
    return created


def _ensure_locations(conn: Any, world: Any, world_id: str) -> bool:
    created = False
    for loc in world.locations:
        existing = world_repo.get_location(conn, loc.location_id)
        if existing is None:
            world_repo.create_location(conn, world_id, loc.location_id, loc.name)
            created = True
        else:
            _check_field("location", loc.location_id, "name", loc.name, existing["name"])
    return created


def _ensure_clues(conn: Any, world: Any, world_id: str) -> bool:
    created = False
    for clue in world.clues:
        existing = world_repo.get_clue(conn, clue.clue_id)
        if existing is None:
            world_repo.create_clue(conn, world_id, clue.clue_id, clue.description)
            created = True
        else:
            _check_field("clue", clue.clue_id, "description",
                         clue.description, existing["description"])
    return created


def ensure_world(conn: Any) -> bool:
    """Seed the world catalog convergently. Returns True when anything created.

    Verifies the world body (version + premise) and every expected character,
    location, and clue by ID. Missing children are created; an existing row whose
    identity fields conflict with the expected synthetic data fails closed via
    :class:`BootstrapConflictError` instead of being overwritten. Re-running after
    a partial bootstrap converges to the complete state.
    """
    from app.preview_data import WORLD_STATE  # noqa: PLC0415

    world_id = WORLD_STATE.world_id
    created = False
    world = world_repo.get_world(conn, world_id)
    if world is None:
        world_repo.create_world(conn, WORLD_STATE)
        created = True
    else:
        _check_field("world", world_id, "version", WORLD_STATE.version, world.version)
        _check_field("world", world_id, "premise", WORLD_STATE.premise, world.premise)

    created |= _ensure_characters(conn, WORLD_STATE, world_id)
    created |= _ensure_locations(conn, WORLD_STATE, world_id)
    created |= _ensure_clues(conn, WORLD_STATE, world_id)
    return created


# ── Canon seeding (repairable, step-by-step) ───────────────────────────────


def _ensure_canon_snapshot(conn: Any, world_id: str) -> bool:
    snap = canon_repo.get_canon_snapshot(conn, CANON_SNAPSHOT_ID)
    if snap is None:
        canon_repo.create_canon_snapshot(
            conn,
            snapshot_id=CANON_SNAPSHOT_ID,
            world_id=world_id,
            version=CANON_VERSION,
            episode_number=CANON_EPISODE_NUMBER,
            world_state={},
            character_states={},
            location_states={},
            clue_states={},
            unresolved_threads=[],
            accepted=True,
        )
        return True
    _check_field("canon snapshot", CANON_SNAPSHOT_ID, "world_id", world_id, snap.world_id)
    _check_field("canon snapshot", CANON_SNAPSHOT_ID, "episode_number",
                 CANON_EPISODE_NUMBER, snap.episode_number)
    if not snap.accepted:
        raise BootstrapConflictError(
            f"canon snapshot '{CANON_SNAPSHOT_ID}' exists but is not accepted; "
            "refusing to overwrite"
        )
    return False


def _ensure_canon_checkpoint(conn: Any) -> bool:
    cp = canon_repo.get_canon_checkpoint(conn, CANON_CHECKPOINT_ID)
    if cp is None:
        canon_repo.create_canon_checkpoint(
            conn,
            checkpoint_id=CANON_CHECKPOINT_ID,
            canon_snapshot_id=CANON_SNAPSHOT_ID,
            episode_number=CANON_EPISODE_NUMBER,
            label="After episode 1",
            is_compatible_for_rejoin=True,
        )
        return True
    _check_field("canon checkpoint", CANON_CHECKPOINT_ID, "canon_snapshot_id",
                 CANON_SNAPSHOT_ID, cp.canon_snapshot_id)
    _check_field("canon checkpoint", CANON_CHECKPOINT_ID, "episode_number",
                 CANON_EPISODE_NUMBER, cp.episode_number)
    return False


def _set_canon_episode_linkage(conn: Any, episode_id: str) -> None:
    """Operator-only linkage repair: bind a freshly generated canon episode to
    the bootstrap snapshot/checkpoint. Commits on its own."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE episodes SET canon_snapshot_id = ?, canon_checkpoint_id = ? "
            "WHERE id = ?",
            (CANON_SNAPSHOT_ID, CANON_CHECKPOINT_ID, episode_id),
        )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


def _repair_canon_episode_linkage(conn: Any, episode: Any) -> None:
    """Fail closed if linked elsewhere; fill in missing linkage."""
    if episode.canon_snapshot_id not in (None, CANON_SNAPSHOT_ID):
        raise BootstrapConflictError(
            f"canon episode '{episode.id}' is linked to unexpected snapshot "
            f"{episode.canon_snapshot_id!r}; refusing to overwrite"
        )
    if episode.canon_checkpoint_id not in (None, CANON_CHECKPOINT_ID):
        raise BootstrapConflictError(
            f"canon episode '{episode.id}' is linked to unexpected checkpoint "
            f"{episode.canon_checkpoint_id!r}; refusing to overwrite"
        )
    if episode.canon_snapshot_id is None or episode.canon_checkpoint_id is None:
        _set_canon_episode_linkage(conn, episode.id)


def _generate_first_canon_episode(conn: Any, world_id: str) -> str:
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
    result = generate_canon_episode(conn, provider, request, world_id=world_id)
    if not result.succeeded or result.episode_id is None:
        raise RuntimeError(f"canon episode generation failed: {result.error}")
    return result.episode_id


def _ensure_canon_episode(conn: Any, world_id: str) -> bool:
    canon_episodes = ep_repo.get_episodes_by_world(conn, world_id, "canon")
    if len(canon_episodes) > 1:
        raise BootstrapConflictError(
            f"expected at most one canon episode for world '{world_id}', found "
            f"{len(canon_episodes)}; refusing to proceed"
        )

    if len(canon_episodes) == 1:
        episode = canon_episodes[0]
        _repair_canon_episode_linkage(conn, episode)
        if episode.review_state == "published":
            return False
        if episode.review_state == "pending_review":
            # Interrupted after generation but before publish — recover.
            ep_repo.publish_episode(conn, episode.id)
            return True
        raise BootstrapConflictError(
            f"canon episode '{episode.id}' is in state "
            f"{episode.review_state!r}; refusing to overwrite"
        )

    episode_id = _generate_first_canon_episode(conn, world_id)
    _set_canon_episode_linkage(conn, episode_id)
    ep_repo.publish_episode(conn, episode_id)
    return True


def ensure_canon(conn: Any) -> bool:
    """Seed the canon snapshot, checkpoint, and first canon episode convergently.

    Ensures the world first, then each canon artifact step-by-step: snapshot
    (content verified), checkpoint (linkage verified), and the canon episode
    (existence, snapshot/checkpoint linkage, and ``published`` state verified).
    Missing steps are created/recovered; conflicting existing canon fails closed
    via :class:`BootstrapConflictError`. More than one canon episode is treated as
    a conflict (no duplicate generation). Returns True when anything was created
    or published.
    """
    from app.preview_data import WORLD_STATE  # noqa: PLC0415

    ensure_world(conn)
    world_id = WORLD_STATE.world_id
    created = False
    created |= _ensure_canon_snapshot(conn, world_id)
    created |= _ensure_canon_checkpoint(conn)
    created |= _ensure_canon_episode(conn, world_id)
    return created


# ── Reader + invite (reader-scoped) ────────────────────────────────────────


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


def active_bound_invite_id(conn: Any, reader_id: str) -> str | None:
    """Return the ID of a usable invite bound to *reader_id*, if any.

    Scoped to a single reader: invites bound to other readers are never
    considered, so rotating the bootstrap reader's invite cannot touch anyone
    else's.
    """
    rows = conn.execute(
        "SELECT id, expires_at FROM invite_credentials "
        "WHERE bound_reader_id = ? AND revoked_at IS NULL "
        "ORDER BY created_at ASC",
        (reader_id,),
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


def revoke_active_bound_invites(conn: Any, reader_id: str) -> int:
    """Revoke *reader_id*'s active invites only; returns the number revoked.

    There is deliberately no reader-less global revoke: an operator can only ever
    revoke the specific bootstrap reader's invites.
    """
    rows = conn.execute(
        "SELECT id FROM invite_credentials "
        "WHERE bound_reader_id = ? AND revoked_at IS NULL",
        (reader_id,),
    ).fetchall()
    count = 0
    for row in rows:
        if auth.revoke_invite(conn, row["id"]):
            count += 1
    return count


def ensure_active_invite(conn: Any, hmac_key: str, reader_id: str) -> str | None:
    """Return a new invite code only when the reader has no active invite.

    Idempotent: a reader that already has a usable bound invite yields ``None``
    and no duplicate row is created, even after an interrupted prior run.
    """
    if active_bound_invite_id(conn, reader_id) is not None:
        return None
    return issue_invite(conn, hmac_key, reader_id)


def run_locked_bootstrap(conn: Any, hmac_key: str) -> tuple[str, str | None]:
    """Run world + canon + reader + invite under the bootstrap advisory lock.

    The caller supplies an already-migrated operator connection. The advisory
    lock serializes concurrent operators so that two simultaneous bootstraps
    still yield exactly one world, one canon episode, one bootstrap reader, and
    one active invite. Returns ``(reader_id, invite_code_or_None)``; the code is
    ``None`` when an active invite already existed.
    """
    with bootstrap_lock(conn):
        ensure_world(conn)
        ensure_canon(conn)
        reader_id = ensure_bootstrap_reader(conn)
        code = ensure_active_invite(conn, hmac_key, reader_id)
        return reader_id, code


# ── Commands (each serialized by the bootstrap advisory lock) ──────────────


def _do_migrate(conn: Any) -> None:
    from app.database.migrate_postgres import (  # noqa: PLC0415
        apply_migrations,
        verify_schema_current,
    )

    newly = apply_migrations(conn, POSTGRES_MIGRATIONS_DIR)
    verify_schema_current(conn, POSTGRES_MIGRATIONS_DIR)
    if newly:
        print(f"[bootstrap] applied {len(newly)} migration(s):")
        for version in newly:
            print(f"  {version}")
    else:
        print("[bootstrap] schema already current — nothing to apply.")


def cmd_migrate() -> None:
    conn = operator_connection()
    try:
        with bootstrap_lock(conn):
            _do_migrate(conn)
    finally:
        conn.close()


def cmd_world() -> None:
    conn = operator_connection()
    try:
        with bootstrap_lock(conn):
            created = ensure_world(conn)
    finally:
        conn.close()
    print(
        "[bootstrap] world seeded."
        if created
        else "[bootstrap] world already present and consistent — skipped."
    )


def cmd_canon() -> None:
    conn = operator_connection()
    try:
        with bootstrap_lock(conn):
            created = ensure_canon(conn)
    finally:
        conn.close()
    print(
        "[bootstrap] canon episode 1 seeded and published."
        if created
        else "[bootstrap] canon episode already present and published — skipped."
    )


def cmd_reader() -> None:
    conn = operator_connection()
    try:
        with bootstrap_lock(conn):
            reader_id = ensure_bootstrap_reader(conn)
    finally:
        conn.close()
    print(f"[bootstrap] bootstrap reader ready (id={reader_id}).")


def cmd_invite() -> None:
    hmac_key = require_credential_key()
    conn = operator_connection()
    try:
        with bootstrap_lock(conn):
            reader_id = ensure_bootstrap_reader(conn)
            code = ensure_active_invite(conn, hmac_key, reader_id)
    finally:
        conn.close()
    if code is None:
        print(
            "[bootstrap] an active invite for the bootstrap reader already "
            "exists — no new code issued."
        )
        return
    _print_code_once(code)


def cmd_rotate() -> None:
    hmac_key = require_credential_key()
    conn = operator_connection()
    try:
        with bootstrap_lock(conn):
            reader_id = ensure_bootstrap_reader(conn)
            revoked = revoke_active_bound_invites(conn, reader_id)
            code = issue_invite(conn, hmac_key, reader_id)
    finally:
        conn.close()
    print(f"[bootstrap] revoked {revoked} active invite(s) for the bootstrap reader.")
    _print_code_once(code)


def cmd_all() -> None:
    hmac_key = require_credential_key()
    conn = operator_connection()
    try:
        with bootstrap_lock(conn):
            _do_migrate(conn)
            ensure_world(conn)
            ensure_canon(conn)
            reader_id = ensure_bootstrap_reader(conn)
            code = ensure_active_invite(conn, hmac_key, reader_id)
    finally:
        conn.close()
    if code is None:
        print("[bootstrap] bootstrap complete; invite already active.")
    else:
        _print_code_once(code)


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
    except BootstrapConflictError as exc:
        print(f"ERROR: bootstrap conflict: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR: bootstrap failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
