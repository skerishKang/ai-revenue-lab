"""P1: Goal and Diagnostic snapshot persistence.

Goals are superseded (history preserved) when replaced; diagnostic snapshots are
immutable append-only records. Persistence survives close/reopen.
"""

from __future__ import annotations

import sqlite3

from app.repositories.history_repository import (
    get_active_goal,
    get_diagnostic_snapshots,
    get_goals,
    record_diagnostic_snapshot,
    record_goal,
)

from tests.contracts.conftest import bootstrap_learner, make_pipeline


def test_goal_history_is_persisted(file_db):
    learner_id, _ = bootstrap_learner(file_db)
    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        record_goal(conn, learner_id=learner_id, goal_text="learn python basics", commit=True)
        record_goal(conn, learner_id=learner_id, goal_text="automate my work", commit=True)

        goals = get_goals(conn, learner_id)
        assert len(goals) == 2

        active = get_active_goal(conn, learner_id)
        assert active is not None
        assert active.goal_text == "automate my work"

        # The first goal was superseded, not deleted.
        superseded = [g for g in goals if g.status == "superseded"]
        assert len(superseded) == 1
        assert superseded[0].goal_text == "learn python basics"
        assert superseded[0].superseded_at is not None
    finally:
        conn.close()


def test_diagnostic_snapshot_is_immutable(file_db):
    learner_id, _ = bootstrap_learner(file_db)
    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        s1 = record_diagnostic_snapshot(
            conn,
            learner_id=learner_id,
            coding_experience="none",
            explanation_preference="example",
            theory_practice_balance="practice",
            derived_difficulty="intro_1",
            commit=True,
        )
        s2 = record_diagnostic_snapshot(
            conn,
            learner_id=learner_id,
            coding_experience="some",
            explanation_preference="concept",
            theory_practice_balance="balanced",
            derived_difficulty="intro_2",
            commit=True,
        )

        snapshots = get_diagnostic_snapshots(conn, learner_id)
        # Snapshots append; nothing is overwritten.
        assert len(snapshots) == 2
        assert snapshots[0].id == s1.id
        assert snapshots[0].coding_experience == "none"
        assert snapshots[1].id == s2.id
        assert snapshots[1].coding_experience == "some"
        # The first snapshot is unchanged after the second is added.
        assert snapshots[0].derived_difficulty == "intro_1"
    finally:
        conn.close()


def test_diagnostic_close_reopen_persistence(file_db):
    learner_id, _ = bootstrap_learner(file_db)

    # Write a goal and a snapshot, then close the connection.
    conn = sqlite3.connect(file_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    record_goal(conn, learner_id=learner_id, goal_text="persist me", commit=True)
    record_diagnostic_snapshot(
        conn,
        learner_id=learner_id,
        coding_experience="none",
        explanation_preference="example",
        theory_practice_balance="practice",
        derived_difficulty="intro_1",
        commit=True,
    )
    conn.close()

    # Reopen on a fresh connection: history is still present.
    reopened = sqlite3.connect(file_db)
    reopened.row_factory = sqlite3.Row
    try:
        active = get_active_goal(reopened, learner_id)
        assert active is not None
        assert active.goal_text == "persist me"

        snapshots = get_diagnostic_snapshots(reopened, learner_id)
        assert len(snapshots) == 1
        assert snapshots[0].derived_difficulty == "intro_1"
    finally:
        reopened.close()
