"""Canonical-subject variant of the B62 Engine orchestration bridge.

The existing B62 `usr_*` remains the product-local owner key for history and
orchestration snapshot/audit rows. Only the Engine request `subject_id` is
replaced with a freshly resolved Shared Control Plane canonical subject.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextvars import ContextVar
import re
from typing import Any, Protocol

from .control_plane_identity import IdentityBridgeError
from .orchestration_bridge import B62EngineOrchestrationBridge, B62OrchestrationError

_ENGINE_SUBJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")


class CanonicalSubjectResolver(Protocol):
    async def resolve_subject_id(self, *, product_user_id: str) -> str: ...


def _canonical_error(exc: IdentityBridgeError) -> B62OrchestrationError:
    status = exc.status_code if 400 <= exc.status_code <= 599 else 503
    return B62OrchestrationError(
        exc.code,
        "공용 AI 작업에 사용할 인증 정보를 확인할 수 없습니다.",
        status_code=status,
    )


class CanonicalSubjectB62EngineOrchestrationBridge(B62EngineOrchestrationBridge):
    """Use current canonical subject for Engine while preserving B62 ownership IDs."""

    def __init__(self, *args: Any, canonical_subject_resolver: CanonicalSubjectResolver, **kwargs: Any) -> None:
        if canonical_subject_resolver is None:
            raise ValueError("canonical_subject_resolver is required")
        super().__init__(*args, **kwargs)
        self._canonical_subject_resolver = canonical_subject_resolver
        self._current_engine_subject: ContextVar[str | None] = ContextVar(
            "b62_current_engine_canonical_subject",
            default=None,
        )

    async def _resolve_engine_subject(self, product_user_id: str) -> str:
        try:
            subject_id = await self._canonical_subject_resolver.resolve_subject_id(
                product_user_id=product_user_id
            )
        except IdentityBridgeError as exc:
            raise _canonical_error(exc) from exc
        except Exception as exc:
            raise B62OrchestrationError(
                "control_plane_session_unavailable",
                "공용 AI 작업에 사용할 인증 정보를 확인할 수 없습니다.",
                status_code=503,
            ) from exc
        if not isinstance(subject_id, str) or not _ENGINE_SUBJECT_RE.fullmatch(subject_id):
            raise B62OrchestrationError(
                "canonical_subject_invalid",
                "공용 AI 작업에 사용할 사용자 식별자를 확인할 수 없습니다.",
                status_code=503,
            )
        return subject_id

    def build_engine_request(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, str]],
        skill: Any,
        model_id: str,
        conversation_id: str | None,
        additional_system_context: str | None = None,
    ) -> dict[str, Any]:
        subject_id = self._current_engine_subject.get()
        if subject_id is None:
            raise B62OrchestrationError(
                "canonical_subject_unavailable",
                "공용 AI 작업에 사용할 사용자 식별자를 확인할 수 없습니다.",
                status_code=503,
            )
        return B62EngineOrchestrationBridge.build_engine_request(
            user_id=subject_id,
            messages=messages,
            skill=skill,
            model_id=model_id,
            conversation_id=conversation_id,
            additional_system_context=additional_system_context,
        )

    async def start(
        self,
        *,
        user_id: str,
        messages: Sequence[Mapping[str, str]],
        skill: Any,
        model_id: str,
        user_text: str,
        conversation_id: str | None,
        additional_system_context: str | None = None,
    ):
        subject_id = await self._resolve_engine_subject(user_id)
        token = self._current_engine_subject.set(subject_id)
        try:
            return await super().start(
                user_id=user_id,
                messages=messages,
                skill=skill,
                model_id=model_id,
                user_text=user_text,
                conversation_id=conversation_id,
                additional_system_context=additional_system_context,
            )
        finally:
            self._current_engine_subject.reset(token)

    async def resume(
        self,
        *,
        user_id: str,
        continuation_ref: str,
        pause_id: str,
        outcome: str,
    ):
        current_subject = await self._resolve_engine_subject(user_id)
        # Read-only preflight. The base bridge still owns the actual decision/state
        # transition. A canonical mismatch therefore occurs before any mutation or
        # Engine resume call.
        snapshot = await self._store.load_active(
            user_id=user_id,
            continuation_ref=continuation_ref,
        )
        if snapshot.engine_request.get("subject_id") != current_subject:
            raise B62OrchestrationError(
                "canonical_subject_mismatch",
                "현재 인증 사용자와 이전 AI 작업의 사용자 식별자가 일치하지 않습니다.",
                status_code=409,
            )
        return await super().resume(
            user_id=user_id,
            continuation_ref=continuation_ref,
            pause_id=pause_id,
            outcome=outcome,
        )
