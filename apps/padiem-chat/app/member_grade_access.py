from __future__ import annotations

from starlette.responses import JSONResponse

from .platform_model_authority import is_model_admin

GRADES = ("free", "plus", "pro", "max")


def _known_grade(access):
    if isinstance(access, dict) and access.get("status") == "approved":
        tier = access.get("tier")
        if isinstance(tier, str) and tier.lower() in GRADES:
            return tier.lower()
    return None


async def verified_member_grade(request, user_id, access=None):
    # Reuse the authenticated account's existing server-side member record.
    # Missing/unreadable membership evidence never grants a paid tier.
    # The Google-verified owner has the maximum model grade independently
    # of customer membership. Never trust a client-supplied admin flag.
    #
    # #5483: the administrator model ceiling is judged by the same server
    # authority that already reveals the administrator hub, so an account the
    # server proves to be an administrator is never locked to the ordinary
    # member grade. The member record below stays the only source of a paid
    # grade for everybody else.
    if await is_model_admin(request, user_id):
        return "max"
    known = _known_grade(access)
    if known is not None:
        return known
    store = getattr(request.app.state, "b66_member_admin_store", None)
    read = getattr(store, "runtime_access", None) if store is not None else None
    if callable(read) and isinstance(user_id, str) and user_id:
        try:
            candidate = await read(user_id)
            known = _known_grade(candidate)
            if known is not None:
                return known
        except Exception:
            pass
    # No live member grade is configured in an isolated mock app. Only test
    # fixtures may exercise paid grades without real production credentials.
    settings = getattr(request.app.state, "settings", None)
    if getattr(settings, "runtime_mode", None) == "mock":
        return "max"
    return "free"


async def selected_admin_denial(request, user_id):
    """Gate the administrator-only Chat model through the verified operator admin.

    Authority is the product's own B66 member-admin store, which matches the
    D1-verified Google subject against the trusted owner email — the same
    server-side identity that already gates B66 admin APIs. Never infer this
    role from a username, email, member grade, browser flag or tier. Forged or
    ordinary sessions are rejected here, before model policy. The CENTRAL
    cross-product model APIs keep their separate central authorizer untouched.
    """
    settings = getattr(request.app.state, "settings", None)
    if not user_id and getattr(settings, "runtime_mode", None) != "mock":
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    store = getattr(request.app.state, "b66_member_admin_store", None)
    verify = getattr(store, "is_google_admin", None)
    if not callable(verify):
        return JSONResponse({"error": {"code": "admin_unavailable", "message": "관리자 확인 기능을 사용할 수 없습니다."}}, status_code=503)
    try:
        is_admin = await verify(user_id)
    except Exception:
        return JSONResponse({"error": {"code": "admin_unavailable", "message": "관리자 확인에 실패했습니다. 잠시 후 다시 시도해 주세요."}}, status_code=503)
    if is_admin is not True:
        return JSONResponse({"error": {"code": "admin_forbidden", "message": "관리자 전용 기능입니다."}}, status_code=403)
    return None


async def selected_grade_denial(request, user_id, selected_grade):
    if not isinstance(selected_grade, str) or selected_grade.lower() not in GRADES:
        return JSONResponse({"error": {"code": "invalid_tier", "message": "지원하지 않는 AI 등급입니다."}}, status_code=422)
    settings = getattr(request.app.state, "settings", None)
    if not user_id and getattr(settings, "runtime_mode", None) != "mock":
        return JSONResponse({"error": {"code": "unauthorized", "message": "로그인이 필요합니다."}}, status_code=401)
    allowed = await verified_member_grade(request, user_id)
    if GRADES.index(selected_grade.lower()) > GRADES.index(allowed):
        return JSONResponse({"error": {"code": "tier_not_available", "message": "회원 등급 이하의 AI 등급을 선택해 주세요."}}, status_code=403)
    return None
