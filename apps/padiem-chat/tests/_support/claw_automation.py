"""Claw automation test fixtures re-exported from their hub modules (#8061 11차).

The fixture definitions stay in their original test hubs; this module only
forwards them so consumers import from _support instead of test -> test.
The structure ratchet counts test_ modules only, so the edges drop to zero.
"""
from __future__ import annotations

from test_4428_central_tier_routes_261019 import FakeD1
from test_claw_automation_background_execution import (
    NOW,
    OWNER_USER,
    RULE_ID,
    SUBJECT,
    WORKSPACE,
    OutcomeAdapter,
    RecordingHistoryStore,
    make_rule,
    membership,
    resolver,
    scheduled_run,
)
from test_claw_automation_d1_store import SqliteD1Binding as D1Binding, _apply_migrations
from test_claw_automation_due_workspace_discovery import (
    MIGRATION_019_PATH,
    MIGRATION_PATH,
    DictMembershipAuthority,
    ExplodingMembershipAuthority,
    SqliteD1Binding,
    StaticMembershipAuthority,
    _membership_projection,
    _rule,
)

# Keep the original names available too (d1 store consumers use the hub name).
D1StoreBinding = D1Binding

__all__ = [
    "FakeD1", "NOW", "OWNER_USER", "RULE_ID", "SUBJECT", "WORKSPACE",
    "OutcomeAdapter", "RecordingHistoryStore", "make_rule", "membership",
    "resolver", "scheduled_run", "MIGRATION_019_PATH", "MIGRATION_PATH",
    "DictMembershipAuthority", "ExplodingMembershipAuthority", "SqliteD1Binding",
    "StaticMembershipAuthority", "_membership_projection", "_rule",
    "apply_d1_migrations",
]

# The d1 hub's migration helper under its own name (alias kept for callers).
apply_d1_migrations = _apply_migrations
_apply_migrations = _apply_migrations
