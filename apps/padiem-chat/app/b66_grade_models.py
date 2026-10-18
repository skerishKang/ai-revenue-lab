"""#5009: B66 CGI grade -> model map, single truth for the three B66 lanes.

Free stays Beam Free; Plus/Pro/Max use Muse Spark; a centrally verified
Google admin is offered the administrator option on the same Muse model.
Labels are B66 product names. The raw B14 catalog is untouched.

The browser never chooses the model freely: each lane matches the requested
tier against this map server-side and refuses anything else.
"""
from __future__ import annotations

from starlette.requests import Request

from padiem_control_plane.product_tier_routes import (
    FREE_PRIMARY_B14_MODEL_ID,
    MUSE_B14_MODEL_ID,
)

B66_GRADES = ("free", "plus", "pro", "max")

B66_GRADE_MODEL_IDS = {
    "free": FREE_PRIMARY_B14_MODEL_ID,
    "plus": MUSE_B14_MODEL_ID,
    "pro": MUSE_B14_MODEL_ID,
    "max": MUSE_B14_MODEL_ID,
}

B66_GRADE_NAMES = {
    "free": "시지아이 Free",
    "plus": "시지아이 Plus",
    "pro": "시지아이 Pro",
    "max": "시지아이 Max",
}

B66_ADMIN_GRADE = "admin"
B66_ADMIN_NAME = "Padiem 관리자"


def b66_grade_model_id(tier: object) -> str | None:
    """Return the grade model for a B66 tier, or ``None`` when unknown."""
    if not isinstance(tier, str):
        return None
    return B66_GRADE_MODEL_IDS.get(tier)


async def b66_verified_admin(request: Request, user_id: str) -> bool:
    """Centrally verified Google admin, same store that gates B66 admin APIs."""
    store = getattr(request.app.state, "b66_member_admin_store", None)
    is_admin = getattr(store, "is_google_admin", None) if store is not None else None
    if callable(is_admin) and isinstance(user_id, str) and user_id:
        try:
            return await is_admin(user_id) is True
        except Exception:
            return False
    return False


__all__ = [
    "B66_ADMIN_GRADE",
    "B66_ADMIN_NAME",
    "B66_GRADE_MODEL_IDS",
    "B66_GRADE_NAMES",
    "B66_GRADES",
    "b66_grade_model_id",
    "b66_verified_admin",
]
