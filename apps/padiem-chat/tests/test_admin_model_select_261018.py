"""Administrator-only Chat model selection: server gate and exact Muse dispatch.

The Padiem 관리자 popup entry is visible only to the server-verified global
model admin, and the Chat route dispatches exactly
``opencode-go/muse-spark-1.3-contributor`` for it. Free/Plus/Pro/Max policy,
their executability set, and ``b14/auto`` behavior stay unchanged.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app import tier_identity_client as tier_identity_module
from app.member_grade_access import selected_admin_denial
from app.model_policy import (
    ADMIN_B14_MODEL_ID,
    EXECUTABLE_B14_MODEL_IDS,
    current_request_tier_id,
    model_policy_is_executable,
    request_tier_context,
    resolve_request_model_policy,
    resolve_tier_policy,
)


ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES = (ROOT / "static" / "product-capabilities.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

MUSE_MODEL_ID = "opencode-go/muse-spark-1.3-contributor"


def _settings_request(*, authorizer=None, runtime_mode="b14", user_id="usr_admin"):
    state = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        b66_member_admin_store=authorizer,
        settings=SimpleNamespace(runtime_mode=runtime_mode),
    )))
    return state, user_id


class _AdminAuthorizer:
    def __init__(self, verdict=True, explode=False):
        self.verdict = verdict
        self.explode = explode
        self.seen = []

    async def is_google_admin(self, user_id):
        self.seen.append(user_id)
        if self.explode:
            raise RuntimeError("authority unavailable")
        return self.verdict


def _run(coro):
    return asyncio.run(coro)


def test_admin_model_id_is_the_owner_authorized_muse_model() -> None:
    assert ADMIN_B14_MODEL_ID == MUSE_MODEL_ID


def test_admin_tier_resolves_exact_muse_model_without_touching_grade_routes() -> None:
    policy = resolve_tier_policy([{"role": "user", "content": "안녕하세요"}], "admin")
    assert policy.model_id == MUSE_MODEL_ID
    assert policy.profile == "high"


def test_admin_request_context_resolves_exact_muse_model() -> None:
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("admin"):
        assert current_request_tier_id() == "admin"
        policy = resolve_request_model_policy(messages)
    assert policy.model_id == MUSE_MODEL_ID
    assert current_request_tier_id() is None


def test_admin_model_stays_outside_the_product_tier_executable_set() -> None:
    assert MUSE_MODEL_ID in (
        __import__("app.model_policy", fromlist=["MODEL_CAPABILITIES"]).MODEL_CAPABILITIES
    )
    assert model_policy_is_executable(MUSE_MODEL_ID) is False
    assert MUSE_MODEL_ID not in EXECUTABLE_B14_MODEL_IDS


def test_verified_admin_passes_the_chat_gate() -> None:
    request, user_id = _run_denial_setup(True, "usr_verified_admin")
    assert _run(selected_admin_denial(request, user_id)) is None
    store = request.app.state.b66_member_admin_store
    assert store.seen == ["usr_verified_admin"]


def _run_denial_setup(verdict, user_id, *, explode=False, authorizer="present", runtime_mode="b14"):
    if authorizer == "missing":
        auth = None
    else:
        auth = _AdminAuthorizer(verdict=verdict, explode=explode)
    request, uid = _settings_request(authorizer=auth, runtime_mode=runtime_mode, user_id=user_id)
    return request, uid


def test_forged_non_admin_request_is_rejected_with_forbidden() -> None:
    request, user_id = _run_denial_setup(False, "usr_customer")
    response = _run(selected_admin_denial(request, user_id))
    assert response.status_code == 403
    assert response.body if hasattr(response, "body") else True


def test_guest_request_is_rejected_without_admin_lookup() -> None:
    auth = _AdminAuthorizer(verdict=True)
    request, _ = _settings_request(authorizer=auth, user_id=None)
    response = _run(selected_admin_denial(request, None))
    assert response.status_code == 401
    assert auth.seen == []


def test_missing_admin_authority_fails_closed() -> None:
    request, user_id = _run_denial_setup(True, "usr_verified_admin", authorizer="missing")
    response = _run(selected_admin_denial(request, user_id))
    assert response.status_code == 503


def test_admin_lookup_failure_never_elevates() -> None:
    request, user_id = _run_denial_setup(True, "usr_verified_admin", explode=True)
    response = _run(selected_admin_denial(request, user_id))
    assert response.status_code == 503


def _live_quota_client():
    import httpx

    from app.config import Settings
    from app.dispatch_quota import DispatchAwareB14Client

    return DispatchAwareB14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal", live_enabled=True),
        stream_transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        require_service_binding=True,
    )


def test_admin_muse_survives_the_dispatch_quota_executability_gate() -> None:
    """The live quota gate must not refund the verified admin dispatch.

    Production composes DispatchAwareB14Client around the tier client; before
    this fix the admin model was rejected there with model_profile_unassigned
    even though the Chat admin gate had already approved the request.
    """

    client = _live_quota_client()
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("admin"):
        assert _run(client._reject_non_executable_policy(messages)) is None
        assert resolve_request_model_policy(messages).model_id == MUSE_MODEL_ID


def test_dispatch_quota_still_rejects_other_non_executable_models(monkeypatch) -> None:
    from app import dispatch_quota
    from app.b14_client import ChatRuntimeError

    client = _live_quota_client()
    monkeypatch.setattr(
        dispatch_quota,
        "_resolve_b62_policy",
        lambda *args, **kwargs: type(
            "P", (), {"model_id": "opencode-go/not-a-product-route"}
        )(),
    )
    try:
        _run(client._reject_non_executable_policy([{"role": "user", "content": "x"}]))
    except ChatRuntimeError as exc:
        assert exc.code == "model_profile_unassigned"
    else:
        raise AssertionError("a non-executable non-admin model must stay rejected")


def test_only_exact_admin_pair_bypasses_product_tier_executability() -> None:
    messages = [{"role": "user", "content": "안녕하세요"}]
    with request_tier_context("admin"):
        policy = resolve_request_model_policy(messages)
        assert tier_identity_module._verified_admin_exact_dispatch(policy.model_id) is True
    with request_tier_context("max"):
        assert (
            tier_identity_module._verified_admin_exact_dispatch(MUSE_MODEL_ID) is False
        )
    assert (
        tier_identity_module._verified_admin_exact_dispatch("opencode-go/cat-jam-free")
        is False
    )


def test_popup_probes_server_admin_and_never_username_matching() -> None:
    assert "/api/b66/admin/me" in CAPABILITIES
    assert "/api/admin/models/me" not in CAPABILITIES
    assert "Padiem 관리자" in CAPABILITIES
    assert "refreshAdminPresence" in CAPABILITIES
    assert 'tier === "admin"' in CAPABILITIES
    assert "charliekant" not in CAPABILITIES
    assert "[data-mode-value=\"admin\"]" in CAPABILITIES


def test_chat_payload_permits_admin_tier_for_the_server_gate() -> None:
    assert '["free", "plus", "pro", "max", "admin"]' in APP_JS


def test_free_plus_pro_max_denial_still_rejects_unknown_admin_claims() -> None:
    from app.member_grade_access import selected_grade_denial

    class _Store:
        async def runtime_access(self, user_id):
            return {"status": "approved", "tier": "FREE"}

    settings = SimpleNamespace(runtime_mode="b14", b66_member_admin_store=_Store())
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        b66_member_admin_store=_Store(), settings=settings
    )))
    response = _run(selected_grade_denial(request, "usr_customer", "admin"))
    assert response.status_code == 422
