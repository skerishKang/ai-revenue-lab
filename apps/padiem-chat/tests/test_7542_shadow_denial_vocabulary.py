"""#7542: the new-path denial vocabulary completes the shadow verdict.

The judge (`judge_connector_account`) and its authority-side scope/consent
reads refuse with codes that used to be outside the shadow's closed denial
set, so the comparison stayed ``denial_unavailable`` instead of assigning a
verdict. The mapping set — and only the mapping set — is widened here: no
verdict kind, no live request path and no journal shape changes.
"""
import asyncio

import pytest

from app import connector_account_shadow as shadow
from app import connector_account_subject as proof
from tests.test_7542_connector_account_shadow import (
    Binding, in_request, settled, read,
)
from app.control_plane_identity import IdentityBridgeError

#: Codes added by this change (new-path refusals with a stable per-account
#: reason). Each one must now complete the verdict instead of staying
#: ``denial_unavailable``.
NEW_DENIAL_CODES = [
    "invalid_identity_authority_rpc",
    "identity_authority_product_mismatch",
    "invalid_identity_authority",
    "canonical_subject_not_found",
    "canonical_tenant_not_found",
    "canonical_tenant_inactive",
    "canonical_tenant_membership_inactive",
    "canonical_tenant_membership_role_missing",
    "canonical_tenant_membership_role_invalid",
    "canonical_tenant_membership_not_yet_active",
    "canonical_scope_not_established",
    "canonical_scope_invalid",
    "canonical_scope_identity_required",
    "connector_enrollment_invalid_reference",
]


@pytest.mark.parametrize("code", NEW_DENIAL_CODES)
@pytest.mark.parametrize("cache", [False, True])
async def test_new_judge_denial_codes_now_get_a_verdict(code, cache, capsys):
    """New-path denial + session denial → denial_mismatch (not unavailable).

    Both storage configurations (local direct binding and the queue-backed
    cached authority the production path uses) give the same verdict.
    """
    binding = Binding()
    binding.session_error = "inactive_auth_session"
    binding.error = {"ok": False, "error": {"code": code, "message": "denied"}}

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError):
            await read(authority, "owner_scope")

    await in_request(binding, call, cache=cache)
    await settled()

    out = capsys.readouterr().out.strip()
    assert out.endswith("method=owner_scope reason=denial_mismatch latency=lt100ms")


@pytest.mark.parametrize("cache", [False, True])
async def test_identical_new_path_denial_is_a_match(cache, capsys):
    """The same new-path code on both sides is a denial match."""
    binding = Binding()
    binding.session_error = "canonical_scope_not_established"
    binding.error = {"ok": False, "error": {"code": "canonical_scope_not_established", "message": "denied"}}

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError):
            await read(authority, "owner_scope")

    await in_request(binding, call, cache=cache)
    await settled()

    out = capsys.readouterr().out.strip()
    assert out.endswith("method=owner_scope reason=denial_match latency=lt100ms")


@pytest.mark.parametrize("cache", [False, True])
async def test_unmapped_environment_code_stays_denial_unavailable(cache, capsys):
    """An environment class code is not a stable per-account refusal.

    ``canonical_scope_unavailable`` is deliberately left out of the denial set
    (lookup/transform environment), so the verdict honestly stays unavailable.
    """
    binding = Binding()
    binding.session_error = "inactive_auth_session"
    binding.error = {"ok": False, "error": {"code": "canonical_scope_unavailable", "message": "denied"}}

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError):
            await read(authority, "owner_scope")

    await in_request(binding, call, cache=cache)
    await settled()

    out = capsys.readouterr().out.strip()
    assert out.endswith("method=owner_scope reason=denial_unavailable latency=lt100ms")


async def test_dropping_a_new_code_from_the_set_back_to_unavailable(monkeypatch, capsys):
    """Tamper: remove one new code from the set and the verdict is lost again.

    Proves the widened mapping — not some other path — is what completes the
    verdict for the newly covered codes."""
    binding = Binding()
    binding.session_error = "inactive_auth_session"
    binding.error = {"ok": False, "error": {"code": "canonical_scope_not_established", "message": "denied"}}

    monkeypatch.setattr(
        shadow, "_DENIALS",
        frozenset(c for c in shadow._DENIALS if c != "canonical_scope_not_established"),
    )

    async def call(authority, _request):
        with pytest.raises(IdentityBridgeError):
            await read(authority, "owner_scope")

    await in_request(binding, call)
    await settled()

    out = capsys.readouterr().out.strip()
    assert out.endswith("method=owner_scope reason=denial_unavailable latency=lt100ms")
