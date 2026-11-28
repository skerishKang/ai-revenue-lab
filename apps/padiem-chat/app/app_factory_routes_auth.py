from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .android_auth_routes import (
    android_handoff_claim,
    android_handoff_confirm,
    android_handoff_create,
    android_handoff_status,
)

from .lovetree_auth_routes import lovetree_handoff_start

from .home_product_access_routes import ACCESS_PATH, home_product_access

from .account_deletion import account_delete, chat_account_delete_rpc, shared_account_delete

from .password_rpc import password_register_rpc, password_verify_rpc

from .password_recovery import RECOVERY_PATHS, password_recovery_rpc

from .email_confirmation import EMAIL_CONFIRMATION_PATH, email_confirmation_rpc

from .auth_routes import (
    auth_status,
    google_callback,
    google_start,
    logout,
    password_change,
    password_login,
    password_register,
    password_reset_confirm,
    password_reset_request,
)

from .voice_stt_routes import IDENTITY_PATH as VOICE_IDENTITY_PATH

from .voice_stt_routes import TRANSCRIBE_PATH as VOICE_TRANSCRIBE_PATH

from .voice_stt_routes import LIVE_TOKEN_PATH as VOICE_LIVE_TOKEN_PATH

from .voice_stt_routes import CLAW_IDENTITY_PATH as CLAW_VOICE_IDENTITY_PATH

from .voice_stt_routes import CLAW_TRANSCRIBE_PATH as CLAW_VOICE_TRANSCRIBE_PATH

from .voice_stt_routes import CLAW_LIVE_TOKEN_PATH as CLAW_VOICE_LIVE_TOKEN_PATH

from .voice_stt_routes import voice_identity, voice_transcribe, voice_live_token

from .voice_stt_rpc import VOICE_RPC_PATH, voice_stt_rpc

from .voice_relay import RELAY_WS_PATH as VOICE_RELAY_WS_PATH, voice_relay_ws

from .owner_model_preview_routes import claw_verified_model_choices

def register_auth_voice_routes(routes: list) -> None:
    routes.extend([
        Route("/api/claw/verified-model-choices", claw_verified_model_choices, methods=["GET"]),
        Route("/api/auth/status", auth_status, methods=["GET"]),
        Route(VOICE_IDENTITY_PATH, voice_identity, methods=["GET"]),
        Route(VOICE_TRANSCRIBE_PATH, voice_transcribe, methods=["POST"]),
        Route(VOICE_LIVE_TOKEN_PATH, voice_live_token, methods=["POST"]),
        # #6828 voice-relay: same-origin WebSocket; COM2 relays to the provider.
        WebSocketRoute(VOICE_RELAY_WS_PATH, voice_relay_ws),
        Route(CLAW_VOICE_IDENTITY_PATH, voice_identity, methods=["GET"]),
        Route(CLAW_VOICE_TRANSCRIBE_PATH, voice_transcribe, methods=["POST"]),
        Route(CLAW_VOICE_LIVE_TOKEN_PATH, voice_live_token, methods=["POST"]),
        Route(ACCESS_PATH, home_product_access, methods=["GET"]),
    ])

def register_auth_login_routes(routes: list) -> None:
    routes.extend([
        Route("/auth/google/start", google_start, methods=["GET"]),
        Route("/auth/google/callback", google_callback, methods=["GET"]),
        # Android 1.0.0 external-browser return contract. The callback above
        # serves both flows; these routes create, poll, confirm, and claim a
        # one-time handoff without adding a second account/session authority.
        Route("/auth/android/handoff", android_handoff_create, methods=["POST"]),
        Route("/auth/android/handoff/{handoff_id}", android_handoff_status, methods=["GET"]),
        Route("/auth/android/handoff/{handoff_id}/claim", android_handoff_claim, methods=["POST"]),
        Route("/auth/android/confirm", android_handoff_confirm, methods=["POST"]),
        # LoveTree 4.0 starts a login here; the callback above returns the one-time ticket.
        Route("/auth/lovetree/start", lovetree_handoff_start, methods=["GET"]),
        Route("/api/auth/password/register", password_register, methods=["POST"]),
        Route("/api/auth/password/login", password_login, methods=["POST"]),
        # padiem-auth email signup/login (opt-in) verifies credentials here.
        Route("/internal/password-verify", password_verify_rpc, methods=["POST"]),
        # #7228 recovery: the COM2 host's authenticated voice STT RPC. The
        # receiver fails closed (404) unless PADIEM_CHAT_VOICE_RPC_SECRET is
        # configured, so hosts that only call this route are unaffected.
        Route(VOICE_RPC_PATH, voice_stt_rpc, methods=["POST"]),
        Route("/internal/password-register", password_register_rpc, methods=["POST"]),
        *[Route(path, password_recovery_rpc, methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
          for path in RECOVERY_PATHS],
        # #7679: the optional confirmation mail of the shared login. Absent
        # (404 for every method) unless its own switch is on.
        Route(EMAIL_CONFIRMATION_PATH, email_confirmation_rpc,
              methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]),
        Route("/internal/account-delete", chat_account_delete_rpc, methods=["POST"]),
        Route("/api/auth/password/change", password_change, methods=["POST"]),
        # #5441 lost-password self-service reset. The request route issues one
        # short-lived, single-use link; the confirm route redeems it and sets
        # the new password.
        Route("/api/auth/password/reset/request", password_reset_request, methods=["POST"]),
        Route("/api/auth/password/reset/confirm", password_reset_confirm, methods=["POST"]),
        Route("/api/auth/logout", logout, methods=["POST"]),
        # #6659 3번 1단계: signed-in account self-deletion over its own Chat DB
        # rows only, behind the same-origin guard and the exact-email confirm.
        Route("/api/account/delete", account_delete, methods=["POST"]),
        Route("/api/account/shared-delete", shared_account_delete, methods=["POST"]),
    ])
