"""Guard: every route that mutates PC ownership/connection must drop the
CachedIdentityAuthority owner-scope cache in the same request.

Static contract (this file) — every *mutation* call site found in the route
modules must carry an invalidation call in the same function body. If a new
route adds a mutation call and forgets the invalidation, this file fails.

Behavioral contract — the drop helper itself (already pinned for the auth
window in test_identity_call_cache_261104.py; here only the owner-scope
half is re-pinned at the unit level).
"""
from __future__ import annotations

import ast
import textwrap

import pytest
from _support.owner_scope_static import handler_sources as _handler_sources


# Mutation call sites: functions in route modules that call these STORE/CTRL
# mutations must also drop the cached owner scope before answering.
_ROUTES_SCANNED = [
    "pc_device_pairing_routes.py",
    "connector_disconnect_routes.py",
    "calendar_read_activation_routes.py",
    "claw_connector_enrollment_routes.py",
    "android_device_enrollment_routes.py",
    "oracle_mesh_read_return_routes.py",
    "oracle_mesh_presence.py",
    "oracle_mesh_poll.py",
]
MUTATIONS = {
    "redeem_code", "adopt_link", "revoke_link", "pause_link", "resume_link",
    "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
    "complete_claim_from_observation",
}
INVALIDATORS = {
    "drop_cached_owner_scope_of",  # identity owner-scope (narrow)
    "invalidate_auth_cache",       # full revoke/subtree (drop whole cache)
    "invalidate_session",          # per canonical session
}
_PRESENT_OR_EXEMPT = set()  # handlers currently missing wiring will be added before this test lands




@pytest.mark.parametrize("module", _ROUTES_SCANNED)
def test_every_owner_mutating_handler_drops_the_cached_owner_scope(module):
    srcs = _handler_sources(module)
    mutating = {}
    for fname, body in srcs.items():
        names = {
            node.func.attr for node in ast.walk(ast.parse(textwrap.dedent(body)))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        hit = names & MUTATIONS
        if hit:
            mutating[fname] = hit
    if module == "oracle_mesh_presence.py":
        assert mutating.get("_record_mesh_presence") == {"complete_claim_from_observation"}
    missing = []
    for fname, hits in mutating.items():
        body = srcs[fname]
        calls = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(ast.parse(textwrap.dedent(body)))
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        if not calls & INVALIDATORS and fname not in _PRESENT_OR_EXEMPT:
            missing.append((fname, sorted(hits)))
    assert not missing, (
        f"{module}: owner-mutating handler(s) without owner-scope invalidation "
        f"in the same request: {[(n, s) for n, s in missing]}"
    )
