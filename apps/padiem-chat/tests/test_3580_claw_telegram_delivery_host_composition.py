"""#3580 Claw Telegram SEND host injection boundary.

Hermetic: every host authority is a local fake, the sendDocument transport is
the canonical stdlib port with its HTTPS connection never opened, and no token,
chat id, grant or Production binding is exercised.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.app_factory import create_app
from app.claw_telegram_delivery_host_composition import (
    ClawTelegramDeliveryHostError, ClawTelegramDeliveryHostState,
    HOST_INJECTION_BOUNDARY_IMPLEMENTED, PRODUCTION_TELEGRAM_DELIVERY_INJECTED,
    READ_SCOPE_IS_NOT_SEND, SEND_DOCUMENT_CAPABILITY,
    build_claw_telegram_artifact_delivery, build_claw_telegram_delivery_host_state,
    telegram_send_grant_present,
)
from app.config import Settings
from kagent.connector_trust import ConnectorBindingProjection, ConnectorBindingState
from kagent.telegram_artifact_delivery import TelegramArtifactDeliveryAdapter
from kagent.telegram_contracts import (
    TelegramBotScope, TelegramChatKind, TelegramPairedChat,
)
from kagent.telegram_document_send_composition import (
    build_telegram_document_send_composition,
)

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
BINDING = "binding_telegram_boundary"
ACTOR = "actor_telegram_boundary"
ACCOUNT = "acct_telegram_boundary"
WORKSPACE = "workspace_telegram_boundary"
BOT_REF = "bot_telegram_boundary"
CHAT_REF = "chat_telegram_boundary"
TOKEN = b"123456:AAboundaryFixtureTokenMaterial"

WORKER = Path(__file__).resolve().parents[1] / "worker.py"


class _TrustedBinding:
    def resolve_bot_token(self, *, binding_ref, bot_ref):
        return TOKEN

    def provider_chat_id(self, *, binding_ref, bot_ref, chat_ref):
        return -100_123_456_789


class _MaterialResolver:
    def resolve_artifact_material(self, artifact_ref, *, workspace_ref, run_ref):
        return None


class _ScopeBlindResolver:
    def resolve_artifact_material(self, artifact_ref):
        return None


class _ApprovalAuthority:
    def verify_delivery_approval(self, *, approval_ref, request):
        return None


def binding(*, capabilities=(SEND_DOCUMENT_CAPABILITY,), connector="telegram",
            state=ConnectorBindingState.ACTIVE,
            expires_at=NOW + timedelta(hours=1), revoked_at=None,
            workspace=WORKSPACE):
    return ConnectorBindingProjection(
        binding_ref=BINDING, connector_id=connector, actor_ref=ACTOR,
        account_ref=ACCOUNT, workspace_ref=workspace,
        granted_scopes=("telegram.outbound",), granted_capabilities=tuple(capabilities),
        issued_at=NOW - timedelta(hours=1), updated_at=NOW - timedelta(hours=1),
        expires_at=expires_at, revoked_at=revoked_at, state=state,
    )


def scope(*, workspace=WORKSPACE):
    return TelegramBotScope(
        binding_ref=BINDING, workspace_ref=workspace, bot_ref=BOT_REF,
        telegram_bot_user_ref="tg-bot-user-boundary",
        paired_chats=(
            TelegramPairedChat(
                chat_ref=CHAT_REF, telegram_chat_id_ref="tg-chat-123",
                kind=TelegramChatKind.PRIVATE, allowed_sender_refs=(ACTOR,),
            ),
        ),
    )


def composition():
    return build_telegram_document_send_composition()


def full_inputs(**overrides):
    params = dict(
        binding=binding(), scope=scope(), trusted_binding=_TrustedBinding(),
        artifact_material=_MaterialResolver(), channel_context=lambda: None,
        approval_authority=_ApprovalAuthority(),
        account_ref=ACCOUNT, actor_ref=ACTOR, composition=composition(),
    )
    params.update(overrides)
    return params


def settings():
    return Settings.from_values(
        runtime_mode="mock", auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="tg-boundary-client.apps.googleusercontent.com",
        google_client_secret="tg-boundary-google-secret",
        session_secret="tg-boundary-session-secret-not-a-real-credential",
        session_max_age_seconds=3600,
    )


class TestClawTelegramDeliveryHostBoundary:
    def test_boundary_fails_closed_with_no_trusted_input(self):
        state = build_claw_telegram_delivery_host_state()
        assert isinstance(state, ClawTelegramDeliveryHostState)
        assert state.delivery is None
        assert state.injected is False
        reasons = " ".join(state.blocked_reasons)
        for expected in ("connector binding", "bot scope", "trusted_binding authority",
                         "artifact_material authority", "approval_authority authority",
                         "current-channel context", "account reference",
                         "actor reference", "sendDocument port"):
            assert expected in reasons
        projection = state.safe_dict()
        assert projection["boundary_implemented"] is HOST_INJECTION_BOUNDARY_IMPLEMENTED
        assert projection["delivery_injected"] is False
        assert projection["production_claim"] is False

    def test_read_only_grant_is_not_a_send_grant(self):
        read_only = binding(capabilities=("telegram.read",))
        assert telegram_send_grant_present(read_only, now=NOW) is False
        state = build_claw_telegram_delivery_host_state(
            **full_inputs(binding=read_only)
        )
        assert state.delivery is None
        assert any("READ-only" in reason for reason in state.blocked_reasons)
        assert READ_SCOPE_IS_NOT_SEND is True

    def test_send_grant_requires_a_live_binding(self):
        assert telegram_send_grant_present(binding(), now=NOW) is True
        expired = binding(expires_at=NOW - timedelta(seconds=1))
        assert telegram_send_grant_present(expired, now=NOW) is False
        revoked = binding(state=ConnectorBindingState.REVOKED, revoked_at=NOW)
        assert telegram_send_grant_present(revoked, now=NOW) is False
        assert telegram_send_grant_present(
            binding(), now=datetime(2026, 10, 11, 12, 0)
        ) is False
        assert telegram_send_grant_present(None, now=NOW) is False

    def test_all_trusted_inputs_bind_the_canonical_delivery_adapter(self):
        composed = composition()
        state = build_claw_telegram_delivery_host_state(
            **full_inputs(composition=composed)
        )
        assert isinstance(state.delivery, TelegramArtifactDeliveryAdapter)
        assert state.delivery._document_send is composed.document_send
        assert state.blocked_reasons == ()
        assert state.safe_dict()["delivery_injected"] is True
        assert isinstance(
            build_claw_telegram_artifact_delivery(**full_inputs()),
            TelegramArtifactDeliveryAdapter,
        )

    def test_wrong_connector_or_foreign_scope_is_refused(self):
        assert build_claw_telegram_delivery_host_state(
            **full_inputs(binding=binding(connector="google-drive"))
        ).delivery is None
        state = build_claw_telegram_delivery_host_state(
            **full_inputs(scope=scope(workspace="some_other_workspace"))
        )
        assert state.delivery is None
        assert any("does not belong" in reason for reason in state.blocked_reasons)

    def test_missing_authority_is_refused(self):
        state = build_claw_telegram_delivery_host_state(
            **full_inputs(approval_authority=object())
        )
        assert state.delivery is None
        assert any("approval_authority authority" in reason
                   for reason in state.blocked_reasons)

    def test_a_scope_blind_material_lookup_is_refused_by_the_adapter(self):
        # The existing adapter owns the deeper structural rule; the boundary
        # fails closed instead of forwarding its message.
        state = build_claw_telegram_delivery_host_state(
            **full_inputs(artifact_material=_ScopeBlindResolver())
        )
        assert state.delivery is None
        assert any("rejected by the existing delivery adapter" in reason
                   for reason in state.blocked_reasons)

    def test_an_injected_state_cannot_also_report_a_blocker(self):
        with pytest.raises(ClawTelegramDeliveryHostError):
            ClawTelegramDeliveryHostState(
                delivery=build_claw_telegram_artifact_delivery(**full_inputs()),
                blocked_reasons=("contradiction",),
            )

    def test_projection_leaks_no_token_chat_id_or_reference(self):
        rendered = json.dumps(
            build_claw_telegram_delivery_host_state(**full_inputs()).safe_dict(),
            ensure_ascii=False, sort_keys=True,
        )
        for secret in (TOKEN.decode("ascii"), "-100123456789", BINDING,
                       WORKSPACE, CHAT_REF):
            assert secret not in rendered
        assert PRODUCTION_TELEGRAM_DELIVERY_INJECTED is False

    def test_worker_passes_the_boundary_result_into_create_app(self):
        source = WORKER.read_text(encoding="utf-8")
        assert "from app.claw_telegram_delivery_host_composition import" in source
        assert (
            "claw_telegram_artifact_delivery = build_claw_telegram_artifact_delivery()"
            in source
        )
        assert "claw_telegram_artifact_delivery=claw_telegram_artifact_delivery," in source

    def test_create_app_keeps_the_delivery_seam_unbound_without_injection(self):
        app = create_app(settings=settings(), claw_telegram_artifact_delivery=None)
        assert app.state.claw_telegram_artifact_delivery is None
        assert build_claw_telegram_artifact_delivery() is None
