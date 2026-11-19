"""#8098 — the Chat verifier knows every scope name the Engine can admit.

#8048 taught the Engine (kagent's ``PC_REQUEST_SCOPE_TOOLS``) three read-only
single-step scopes — ``files_search``, ``files_search_contents``,
``files_chunk`` — and the decision stage escalated a recursive name search to
``admitted=files_search``. Chat's signed-claim verifier never learned those
names, so a recursive ``pc_search`` on the external connector died 422
``pc_scope_claim_invalid`` before the PC saw it.

No Mesh, Identity or PC is contacted here. The claim is verified with the
real route helper on both products (the Chat lane and the b54 claw lane share
it), and the name-set contract pins Chat's table to the Engine's table.
The helpers are local on purpose: test modules must not import other tests.
"""
from __future__ import annotations

import ast
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import oracle_mesh_read_return_routes as routes

KAGENT_ADAPTER = (Path(__file__).resolve().parents[2]
                  / "korean-ai-code-agent" / "src" / "kagent" / "pc_query_adapter.py")
SECRET = "s" * 48


def _claim(*, admitted, ops, requested=None, product="chat"):
    return {
        "version": 1, "requested": requested or admitted, "admitted": admitted,
        "source": "decision", "ops": ops,
        "app_id": "padiem-chat" if product == "chat" else "b54-padiem-claw",
    }


def _request_for(claim, *, product="chat", raw=b'{"mode":"context"}'):
    encoded = json.dumps(claim, sort_keys=True, separators=(",", ":"))
    timestamp = "1762000000"
    proof = hmac.new(
        SECRET.encode(), timestamp.encode() + b"." + raw + b"." + encoded.encode(),
        hashlib.sha256,
    ).hexdigest()
    return SimpleNamespace(
        headers={
            "X-Claw-PC-Scope": encoded, "X-Claw-PC-Scope-Proof": proof,
            "X-Claw-Engine-Time": timestamp,
        },
        app=SimpleNamespace(state=SimpleNamespace(
            claw_engine_desktop_secret=SECRET,
        )),
    )


def test_recursive_name_search_claim_is_accepted_on_both_products():
    # #8048's decision escalation: requested stays the declared files_list,
    # admitted is the single-step files_search the escalation chose.
    for product in ("chat", "claw"):
        claim = _claim(admitted="files_search", requested="files_list",
                       ops=["search_name"], product=product)
        parsed, error = routes._engine_pc_scope_claim(
            _request_for(claim, product=product), b'{"mode":"context"}', product=product,
        )
        assert error is None and parsed == claim, product


def test_content_search_and_chunk_claims_are_accepted():
    contents = _claim(admitted="files_search_contents", requested="files",
                      ops=["search_content"])
    parsed, error = routes._engine_pc_scope_claim(
        _request_for(contents), b'{"mode":"context"}', product="chat",
    )
    assert error is None and parsed == contents

    # The chunk reader is its own step with no named op: the Engine derives
    # an empty ops list for it, and an empty ceiling is a subset of anything.
    chunk = _claim(admitted="files_chunk", requested="files", ops=[])
    parsed, error = routes._engine_pc_scope_claim(
        _request_for(chunk), b'{"mode":"context"}', product="chat",
    )
    assert error is None and parsed == chunk


def test_an_unknown_scope_name_is_still_refused():
    invented = _claim(admitted="files_search_recursive", requested="files_list",
                      ops=["search_name"])
    _, error = routes._engine_pc_scope_claim(
        _request_for(invented), b'{"mode":"context"}', product="chat",
    )
    assert error is not None and error.status_code == 422

    unknown_requested = _claim(admitted="files_list", requested="files_deep",
                               ops=["search_name"])
    _, error = routes._engine_pc_scope_claim(
        _request_for(unknown_requested), b'{"mode":"context"}', product="chat",
    )
    assert error is not None and error.status_code == 422


def test_ops_outside_the_scope_ceiling_are_refused():
    # files_search names exactly one op; it never widens into a listing,
    # a content search or a read.
    for ops in (["list"], ["search_content"], ["read"]):
        over = _claim(admitted="files_search", requested="files_list", ops=ops)
        _, error = routes._engine_pc_scope_claim(
            _request_for(over), b'{"mode":"context"}', product="chat",
        )
        assert error is not None and error.status_code == 422, ops
    # the chunk scope names no op at all — "read" is not its op
    chunk_over = _claim(admitted="files_chunk", requested="files", ops=["read"])
    _, error = routes._engine_pc_scope_claim(
        _request_for(chunk_over), b'{"mode":"context"}', product="chat",
    )
    assert error is not None and error.status_code == 422
    # an empty ops list is a subset of every ceiling by contract (the Engine
    # derives [] for the chunk-only scope), so a chunk claim verifies on a
    # files_list request too — the dispatch below refuses the unnamed op.


def test_chat_verifier_names_match_the_engine_scope_table():
    # Same-type regression guard (#8098): every scope name the Engine's
    # PC_REQUEST_SCOPE_TOOLS can admit must exist in Chat's file-lane
    # verifier table, minus the browser scope — a browser claim verifies in
    # claw_pc_browser_routes and must stay out of the file lane.
    chat_names = set(routes._ENGINE_PC_FILES_SCOPE_OPS)

    tree = ast.parse(KAGENT_ADAPTER.read_text(encoding="utf-8"))
    engine_names = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "PC_REQUEST_SCOPE_TOOLS"
                        for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            engine_names = {
                key.value for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
            break
    assert engine_names, "PC_REQUEST_SCOPE_TOOLS not found in the kagent adapter"

    assert chat_names == engine_names - {"browser"}, (
        f"Chat verifier scopes {sorted(chat_names)} vs "
        f"Engine file scopes {sorted(engine_names - {'browser'})} — a new "
        "Engine scope name must be mirrored in _ENGINE_PC_FILES_SCOPE_OPS "
        "(or explicitly kept browser-only)."
    )
    assert "browser" in engine_names
