"""Development seed for Living Fiction Phase 2A preview.

Run explicitly:

    python -X utf8 -m app.dev_seed

Creates:
- World, characters, locations, clues (synthetic)
- First canon episode (published)
- Canon snapshot and checkpoint
- Demo invite credential (CSPRNG code, stored as keyed digest)

Does NOT run on application startup. Does NOT create duplicate data.
Does NOT store plaintext invite codes or raw session tokens.
Does NOT use fixed invite codes or admin passwords.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

# Ensure tests.fixtures is importable
_APP_DIR = Path(__file__).resolve().parent.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from app import auth
from app import canon_repository as canon_repo
from app import episode_repository as ep_repo
from app import reader_repository as reader_repo
from app import world_repository as world_repo
from app.ai.mock import MockProvider
from app.config import settings
from app.db import apply_migrations, get_connection
from app.pipeline.service import GenerationRequest, generate_canon_episode
from app.domain.enums import EpisodeType
from tests.fixtures.mock_payloads import (
    CANON_EPISODE_1_PLAN,
    CANON_EPISODE_1_CONTENT,
)
from tests.fixtures.synthetic_world import WORLD_STATE


def _seed_world(conn) -> None:
    """Create world, characters, locations, and clues if not present."""
    if world_repo.get_world(conn, WORLD_STATE.world_id) is not None:
        return  # already seeded

    world_repo.create_world(conn, WORLD_STATE)
    for char in WORLD_STATE.characters:
        world_repo.create_character(
            conn, WORLD_STATE.world_id,
            char.character_id, char.canonical_name, char.role,
            traits=json.dumps(char.knowledge),
            location_id=char.location_id,
        )
    for loc in WORLD_STATE.locations:
        world_repo.create_location(
            conn, WORLD_STATE.world_id,
            loc.location_id, loc.name,
        )
    for clue in WORLD_STATE.clues:
        world_repo.create_clue(
            conn, WORLD_STATE.world_id,
            clue.clue_id, clue.description,
        )


def _seed_canon(conn) -> None:
    """Create canon snapshot, checkpoint, and first canon episode if not present."""
    # Check if canon episode already exists
    existing = ep_repo.get_episodes_by_world(conn, WORLD_STATE.world_id, "canon")
    if existing:
        return  # already seeded

    # Create canon snapshot
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

    # Generate first canon episode
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
        conn, provider, request, world_id=WORLD_STATE.world_id,
    )
    if not result.succeeded:
        raise RuntimeError(f"canon episode generation failed: {result.error}")

    # Publish the canon episode — branches require a prior published episode
    ep_repo.publish_episode(conn, result.episode_id)


def _seed_invite(conn) -> str:
    """Create an invite credential if none exists. Returns the invite code."""
    # Check if any unused invite exists
    rows = conn.execute(
        "SELECT id FROM invite_credentials WHERE used_by_reader_id IS NULL LIMIT 1"
    ).fetchall()
    if rows:
        print("[dev_seed] Invite credential already exists — skipping.")
        return "(existing — check terminal output from first run)"

    code = auth.generate_invite_code()
    auth.create_invite_credential(conn, code, settings.credential_hmac_key)
    return code


def main() -> None:
    """Run the development seed."""
    if not settings.credential_hmac_key:
        print("ERROR: LF_CREDENTIAL_HMAC_KEY environment variable is required.")
        sys.exit(1)
    if not settings.session_hmac_key:
        print("ERROR: LF_SESSION_HMAC_KEY environment variable is required.")
        sys.exit(1)

    db_path = settings.database_path
    conn = get_connection(db_path)
    try:
        migrations_dir = str(
            Path(__file__).resolve().parent.parent / "migrations"
        )
        apply_migrations(conn, migrations_dir)

        print("[dev_seed] Seeding world...")
        _seed_world(conn)

        print("[dev_seed] Seeding canon episode...")
        _seed_canon(conn)

        print("[dev_seed] Creating invite credential...")
        code = _seed_invite(conn)

        print()
        print("=" * 60)
        print("  DEV SEED COMPLETE")
        print("=" * 60)
        print()
        print(f"  Invite code: {code}")
        print()
        print("  This code was displayed once. It is stored in the DB")
        print("  only as a keyed HMAC digest — not as plaintext.")
        print()
        print(f"  DB path: {db_path}")
        print(f"  Preview: http://127.0.0.1:8033/access")
        print()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
