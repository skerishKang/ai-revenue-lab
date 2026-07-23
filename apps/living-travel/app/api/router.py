"""Assemble the /api/v1 JSON API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes_common import router as common_router
from app.api.routes_operator import router as operator_router
from app.api.routes_traveler import router as traveler_router


def build_api_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    router.include_router(common_router)
    router.include_router(traveler_router)
    router.include_router(operator_router)
    return router
