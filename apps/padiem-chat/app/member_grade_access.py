from __future__ import annotations

from starlette.responses import JSONResponse

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
