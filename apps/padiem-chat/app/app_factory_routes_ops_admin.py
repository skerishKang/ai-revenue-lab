from __future__ import annotations

from starlette.routing import Route

from .app_factory_health_static import health
from .feedback_routes import (
    admin_feedback, admin_feedback_ai_tester, admin_feedback_reply,
    admin_feedback_status, feedback, feedback_read, feedback_reply,
)
from .news_routes import news, news_unread
from .usage_log_routes import admin_usage_log
from .site_feedback_routes import (
    admin_site_feedback, admin_site_feedback_reply,
    admin_site_feedback_resend, admin_site_feedback_status,
    site_feedback, site_feedback_ingest,
)
from .central_model_control_routes import (
    central_model_admin_me, central_model_admin_snapshot,
    central_model_admin_preview,
)
from .central_model_policy_write_routes import (
    central_model_change_preview, central_model_change_apply,
    central_model_rollback_preview, central_model_change_audit,
)
from .central_model_route_routes import (
    central_model_route_apply, central_model_route_preview,
    central_model_route_rollback_preview, central_model_routes_get,
)
from .credential_slots_routes import (
    SLOT_STATUS_ROUTE as CREDENTIAL_SLOTS_ROUTE,
    credential_slots_status,
)
from .model_admin_ext_routes import MODEL_ADMIN_ROUTES
from .platform_admin_routes import (
    platform_admin_role_assign,
    platform_admin_role_revoke,
    platform_admin_session,
)

# --- 등록 영역별 나누기 (R7-1, #7814) ---
# 순서: 원래 routes = [...] 의 엘트 순서를 그대로 따른다. 한 엘트도 앞으로/뒤로 옮기지 않는다.
# (같은 경로가 두 번 등록되면 먼저 등록된 것이 이기는 프레임워크 규칙 때문이다.)
# 각 함수는 인자로 받은 routes 목록에만 쓴다(바깥 지역 변수에 기대지 않는다).

def register_util_routes(routes: list) -> None:
    routes.extend([
        Route("/health", health, methods=["GET"]),
    ])

def register_opinion_news_routes(routes: list) -> None:
    routes.extend([
        Route("/api/chat/feedback", feedback, methods=["GET", "POST"]),
        Route("/api/chat/news", news, methods=["GET"]),
        Route("/api/chat/news/unread", news_unread, methods=["GET"]),
        Route("/api/chat/feedback/{feedback_id}/read", feedback_read, methods=["POST"]),
        Route("/api/chat/feedback/{feedback_id}/replies", feedback_reply, methods=["POST"]),
    ])

def register_ops_member_routes(routes: list) -> None:
    from .ops_member_routes import register_ops_member_routes as _register
    _register(routes)


def register_ops_round_score_routes(routes: list) -> None:
    from .ops_round_score_routes import register_ops_round_score_routes as _register
    _register(routes)


def register_ops_alert_routes(routes: list) -> None:
    from .ops_alert_routes import register_ops_alert_routes as _register
    _register(routes)


def register_ops_pc_self_heal_routes(routes: list) -> None:
    from .ops_pc_self_heal import routes as _pc_routes
    routes.extend(_pc_routes())


def register_pc_helper_version_routes(routes: list) -> None:
    from .pc_helper_version_routes import register_pc_helper_version_routes as _register
    _register(routes)


def register_ops_news_routes(routes: list) -> None:
    from .ops_news_routes import register_ops_news_routes as _register
    _register(routes)


def register_admin_feedback_routes(routes: list) -> None:
    routes.extend([
        Route("/api/admin/feedback", admin_feedback, methods=["GET"]),
        Route("/api/admin/feedback/{feedback_id}", admin_feedback_status, methods=["PATCH"]),
        Route("/api/admin/feedback/{feedback_id}/replies", admin_feedback_reply, methods=["POST"]),
        Route("/api/admin/feedback/{feedback_id}/ai-tester", admin_feedback_ai_tester, methods=["PATCH"]),
        Route("/api/admin/usage-log", admin_usage_log, methods=["GET"]),
    ])

def register_site_feedback_routes(routes: list) -> None:
    routes.extend([
        Route("/api/site-feedback", site_feedback, methods=["POST", "OPTIONS"]),
        # #7690: Lovetree 서버-서버 수신. 공개 origin·브라우저 CORS 없이 HMAC만 본다.
        Route("/api/site-feedback/ingest", site_feedback_ingest, methods=["POST"]),
        Route("/api/admin/site-feedback", admin_site_feedback, methods=["GET"]),
        Route("/api/admin/site-feedback/{feedback_id}", admin_site_feedback_status, methods=["PATCH"]),
        Route("/api/admin/site-feedback/{feedback_id}/reply", admin_site_feedback_reply, methods=["POST"]),
        Route("/api/admin/site-feedback/{feedback_id}/resend", admin_site_feedback_resend, methods=["POST"]),
    ])

def register_admin_routes(routes: list) -> None:
    routes.extend([
        Route("/api/admin/models/me", central_model_admin_me, methods=["GET"]),
        Route("/api/admin/models/snapshot", central_model_admin_snapshot, methods=["GET"]),
        Route("/api/admin/models/preview", central_model_admin_preview, methods=["POST"]),
        Route("/api/admin/models/change-preview", central_model_change_preview, methods=["POST"]),
        Route("/api/admin/models/change-apply", central_model_change_apply, methods=["POST"]),
        Route("/api/admin/models/rollback-preview", central_model_rollback_preview, methods=["POST"]),
        Route("/api/admin/models/audit", central_model_change_audit, methods=["GET"]),
        Route("/api/admin/models/routes", central_model_routes_get, methods=["GET"]),
        Route("/api/admin/models/route-preview", central_model_route_preview, methods=["POST"]),
        Route("/api/admin/models/route-apply", central_model_route_apply, methods=["POST"]),
        Route("/api/admin/models/route-rollback-preview", central_model_route_rollback_preview, methods=["POST"]),
        Route(CREDENTIAL_SLOTS_ROUTE, credential_slots_status, methods=["GET"]),
        *[
            Route(path, handler, methods=[method])
            for path, handler, method in MODEL_ADMIN_ROUTES
        ],
        Route("/api/admin/session", platform_admin_session, methods=["GET"]),
        Route("/api/admin/roles", platform_admin_role_assign, methods=["POST"]),
        Route("/api/admin/roles/{user_id}", platform_admin_role_revoke, methods=["DELETE"]),
    ])
