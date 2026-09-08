"""B54 Claw Manual Message Intake and Action Routing Contracts (#2056).

Enables connectorless paste-to-document and paste-to-action workflows for:
- KakaoTalk, SMS, Email, Telegram, Discord, and clipboard text.
- Quote draft, order draft, reply draft, request summary, and candidate fact extraction.
- Downloadable MD/DOCX artifacts, disabled direct-send gates, and unconfirmed memory proposals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Mapping, Sequence

from .contracts import ContractError
from .core import redact_secrets
from .document_export import (
    HWPX_EXPORT_DECISION,
    LEGACY_HWP_EXPORT_DECISION,
    DocumentExportError,
    generate_docx_bytes,
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CONTROL_RE = re.compile(r"[--]")


def _safe_id(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    norm = value.strip()
    if not _SAFE_ID_RE.fullmatch(norm):
        raise ContractError(f"{field_name} has invalid identifier shape: {norm!r}")
    return norm


def _bounded_text(value: str, field_name: str, *, limit: int = 100_000, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ContractError(f"{field_name} must be a string")
    norm = value.strip()
    if not norm and not allow_empty:
        raise ContractError(f"{field_name} is required")
    if len(norm) > limit:
        raise ContractError(f"{field_name} exceeds {limit} characters")
    if _CONTROL_RE.search(norm):
        raise ContractError(f"{field_name} contains forbidden control characters")
    return norm


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field_name} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc)


class ManualIntakeChannel(str, Enum):
    KAKAO = "kakao"
    SMS = "sms"
    EMAIL = "email"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    OTHER = "other"


class ManualIntakeAction(str, Enum):
    QUOTE_DRAFT = "quote_draft"
    ORDER_DRAFT = "order_draft"
    REPLY_DRAFT = "reply_draft"
    SUMMARIZE_REQUEST = "summarize_request"
    EXTRACT_CANDIDATES = "extract_candidates"


@dataclass(frozen=True, slots=True)
class ManualIntakeSafetyDecision:
    connector_required: bool = False
    raw_input_trusted_as_memory: bool = False
    memory_update_requires_user_approval: bool = True
    direct_kakao_send_allowed: bool = False
    direct_sms_send_allowed: bool = False
    email_send_requires_user_approval: bool = True
    share_link_requires_storage_2055: bool = True
    google_drive_save_requires_connector: bool = True

    def __post_init__(self) -> None:
        if self.connector_required is not False:
            raise ContractError("Manual intake must not require connectors")
        if self.raw_input_trusted_as_memory is not False:
            raise ContractError("Raw input must never be trusted as permanent memory")
        if self.memory_update_requires_user_approval is not True:
            raise ContractError("Memory updates must require user approval")
        if self.direct_kakao_send_allowed is not False:
            raise ContractError("Direct Kakao sending is forbidden")
        if self.direct_sms_send_allowed is not False:
            raise ContractError("Direct SMS sending is forbidden")


@dataclass(frozen=True, slots=True)
class ManualIntakeDisabledAction:
    action_key: str
    reason: str
    remedy: str

    def safe_dict(self) -> dict[str, str]:
        return {
            "action_key": self.action_key,
            "reason": self.reason,
            "remedy": self.remedy,
        }


@dataclass(frozen=True, slots=True)
class ManualIntakeArtifact:
    artifact_id: str
    file_name: str
    media_type: str
    size_bytes: int
    content_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _safe_id(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "file_name", _bounded_text(self.file_name, "file_name", limit=256))
        object.__setattr__(self, "media_type", _bounded_text(self.media_type, "media_type", limit=128))
        if not isinstance(self.size_bytes, int) or self.size_bytes < 0:
            raise ContractError("size_bytes must be non-negative integer")
        if not isinstance(self.content_bytes, bytes):
            raise ContractError("content_bytes must be bytes")


@dataclass(frozen=True, slots=True)
class ManualIntakeRequest:
    request_id: str
    workspace_id: str
    channel: ManualIntakeChannel
    action: ManualIntakeAction
    raw_content: str
    sender_hint: str | None = None
    requested_format: str = "md"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _safe_id(self.request_id, "request_id"))
        object.__setattr__(self, "workspace_id", _safe_id(self.workspace_id, "workspace_id"))
        if not isinstance(self.channel, ManualIntakeChannel):
            try:
                object.__setattr__(self, "channel", ManualIntakeChannel(self.channel))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"invalid intake channel: {self.channel}") from exc
        if not isinstance(self.action, ManualIntakeAction):
            try:
                object.__setattr__(self, "action", ManualIntakeAction(self.action))
            except (TypeError, ValueError) as exc:
                raise ContractError(f"invalid intake action: {self.action}") from exc
        object.__setattr__(self, "raw_content", _bounded_text(self.raw_content, "raw_content", limit=100_000))
        if self.sender_hint is not None:
            object.__setattr__(self, "sender_hint", _bounded_text(self.sender_hint, "sender_hint", limit=256))
        object.__setattr__(self, "requested_format", _bounded_text(self.requested_format.lower(), "requested_format", limit=16))
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class ManualIntakeResult:
    request_id: str
    workspace_id: str
    channel: ManualIntakeChannel
    action: ManualIntakeAction
    title: str
    result_text: str
    safety_decision: ManualIntakeSafetyDecision
    artifacts: tuple[ManualIntakeArtifact, ...] = field(default_factory=tuple)
    disabled_actions: tuple[ManualIntakeDisabledAction, ...] = field(default_factory=tuple)
    memory_proposals: tuple[dict[str, str], ...] = field(default_factory=tuple)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def safe_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "workspace_id": self.workspace_id,
            "channel": self.channel.value,
            "action": self.action.value,
            "title": self.title,
            "result_text": redact_secrets(self.result_text),
            "artifacts": [
                {
                    "artifact_id": a.artifact_id,
                    "file_name": a.file_name,
                    "media_type": a.media_type,
                    "size_bytes": a.size_bytes,
                }
                for a in self.artifacts
            ],
            "disabled_actions": [d.safe_dict() for d in self.disabled_actions],
            "memory_proposals": list(self.memory_proposals),
            "connector_required": self.safety_decision.connector_required,
            "raw_input_trusted_as_memory": self.safety_decision.raw_input_trusted_as_memory,
            "memory_update_requires_user_approval": self.safety_decision.memory_update_requires_user_approval,
            "direct_kakao_send": False,
            "direct_sms_send": False,
        }


class ManualIntakeRouter:
    """Processes untrusted pasted messages into deterministic business drafts and safe proposals."""

    def process(self, request: ManualIntakeRequest) -> ManualIntakeResult:
        safety = ManualIntakeSafetyDecision()

        # Build disabled actions
        disabled = [
            ManualIntakeDisabledAction(
                action_key="direct_kakao_send",
                reason="Direct automated messaging to personal KakaoTalk accounts is forbidden",
                remedy="Copy generated text and send manually via official channels",
            ),
            ManualIntakeDisabledAction(
                action_key="direct_sms_send",
                reason="Direct SMS automated dispatch is disabled without verified template authorization",
                remedy="Review text and dispatch through verified SMS gateway",
            ),
            ManualIntakeDisabledAction(
                action_key="share_link",
                reason="Share link requires persistent #2055 workspace storage configuration",
                remedy="Download artifact locally as MD or DOCX",
            ),
            ManualIntakeDisabledAction(
                action_key="google_drive_save",
                reason="Google Drive saving is unavailable without an active Drive connector",
                remedy="Download local file and upload manually to Drive",
            ),
            ManualIntakeDisabledAction(
                action_key="email_send",
                reason="Direct outbound email sending requires explicit user approval",
                remedy="Review email draft and approve delivery via authenticated outbox",
            ),
        ]

        title = f"[{request.channel.value.upper()}] 수기 접수: {request.action.value}"
        result_text = ""
        items_extracted: list[tuple[str, str, str, str]] = []
        memory_proposals: list[dict[str, str]] = []

        # Simple deterministic parser for Korean business text
        sender = request.sender_hint or "거래처 (미지정)"
        text = request.raw_content

        if request.action is ManualIntakeAction.QUOTE_DRAFT:
            title = f"견적서 초안 (DRAFT) — {sender}"
            items_extracted = [
                ("요청 품목", "1", "입력 필요", "입력 필요"),
            ]
            result_text = (
                f"# 견적서 초안 보고서\n\n"
                f"- 접수 채널: {request.channel.value}\n"
                f"- 요청자/거래처: {sender}\n\n"
                f"## 견적서 초안 (DRAFT)\n\n"
                f"고객 요청 내용:\n{text}\n\n"
                f"## 산출 근거 (플로우 계산)\n\n"
                f"| 품명 | 수량 | 단가 | 금액 |\n"
                f"|---|---|---|---|\n"
                f"| 요청 품목 | 1 | 입력 필요 | 입력 필요 |\n"
                f"| 합계 | | | 입력 필요 |\n"
            )
            memory_proposals.append({
                "type": "customer_contact_candidate",
                "name": sender,
                "note": f"접수 채널 {request.channel.value}에서 추출된 잠재 고객명 (미확인)",
            })

        elif request.action is ManualIntakeAction.ORDER_DRAFT:
            title = f"발주서/판매오더 초안 (DRAFT) — {sender}"
            items_extracted = [
                ("발주 품목", "1", "입력 필요", "입력 필요"),
            ]
            result_text = (
                f"# 발주서/판매오더 초안 보고서 (ORDER)\n\n"
                f"- 접수 채널: {request.channel.value}\n"
                f"- 발주처: {sender}\n\n"
                f"## 발주서/판매오더 초안 (DRAFT)\n\n"
                f"접수 내용 기반 발주서 초안입니다.\n{text}\n\n"
                f"## 산출 근거\n\n"
                f"| 품명 | 수량 | 단가 | 금액 |\n"
                f"|---|---|---|---|\n"
                f"| 발주 품목 | 1 | 입력 필요 | 입력 필요 |\n"
                f"| 합계 | | | 입력 필요 |\n"
            )

        elif request.action is ManualIntakeAction.REPLY_DRAFT:
            title = f"답장 초안 (DRAFT) — {sender}"
            result_text = (
                f"안녕하세요 {sender} 담당자님,\n\n"
                f"보내주신 문의 내용({request.channel.value} 접수) 감사히 확인했습니다.\n\n"
                f"[문의 요약]\n{text}\n\n"
                f"해당 건에 대해 견적 및 납기 일정을 검토 후 신속히 회신드리겠습니다.\n"
                f"추가 문의사항이 있으시면 언제든 말씀 부탁드립니다.\n\n"
                f"감사합니다."
            )

        elif request.action is ManualIntakeAction.SUMMARIZE_REQUEST:
            title = f"요청 사항 요약 보고서 — {sender}"
            result_text = (
                f"# 요청 사항 요약 ({request.channel.value})\n\n"
                f"- 거래처/발신: {sender}\n"
                f"- 원문 길이: {len(text)}자\n\n"
                f"## 핵심 요약\n"
                f"- 접수 내용: {text.strip().splitlines()[0] if text.strip() else '-'}\n"
                f"- 특이 사항: 추가 일정 및 단가 확인 필요\n"
            )

        elif request.action is ManualIntakeAction.EXTRACT_CANDIDATES:
            title = f"후보 정보 추출 결과 — {sender}"
            result_text = (
                f"# 추출된 거래처/품목 후보\n\n"
                f"- 거래처 후보: {sender}\n"
                f"- 상태: 미확정 제안 (사용자 승인 전까지 메모리 미반영)\n"
            )
            memory_proposals.append({
                "type": "organization_candidate",
                "name": sender,
                "source_channel": request.channel.value,
            })

        # Artifact generation
        artifacts: list[ManualIntakeArtifact] = []

        # 1. Always generate MD artifact
        md_bytes = result_text.encode("utf-8")
        artifacts.append(
            ManualIntakeArtifact(
                artifact_id=f"art_md_{request.request_id}",
                file_name=f"{request.action.value}_{request.request_id}.md",
                media_type="text/markdown",
                size_bytes=len(md_bytes),
                content_bytes=md_bytes,
            )
        )

        # 2. If docx requested or default, generate DOCX artifact where #2016 is available
        if request.requested_format in ("docx", "all"):
            table_headers = ("품명", "수량", "단가", "금액") if items_extracted else None
            table_rows = items_extracted if items_extracted else None
            docx_bytes = generate_docx_bytes(
                title=title,
                metadata_fields=[
                    ("접수 채널", request.channel.value),
                    ("요청 작업", request.action.value),
                    ("발신/거래처", sender),
                ],
                section_title="접수 및 작성 초안",
                body_text=result_text,
                table_headers=table_headers,
                table_rows=table_rows,
                footer_text="Padiem Claw · Connectorless Manual Intake",
            )
            artifacts.append(
                ManualIntakeArtifact(
                    artifact_id=f"art_docx_{request.request_id}",
                    file_name=f"{request.action.value}_{request.request_id}.docx",
                    media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    size_bytes=len(docx_bytes),
                    content_bytes=docx_bytes,
                )
            )

        elif request.requested_format == "hwpx":
            # HWPX documented decision fails closed
            raise DocumentExportError(
                "document_format_unsupported",
                f"HWPX export is deferred per documented architecture decision ({HWPX_EXPORT_DECISION}); use docx or md",
            )

        elif request.requested_format not in ("md", "docx", "all"):
            raise DocumentExportError(
                "document_format_unsupported",
                f"unsupported format: {request.requested_format}",
            )

        return ManualIntakeResult(
            request_id=request.request_id,
            workspace_id=request.workspace_id,
            channel=request.channel,
            action=request.action,
            title=title,
            result_text=result_text,
            safety_decision=safety,
            artifacts=tuple(artifacts),
            disabled_actions=tuple(disabled),
            memory_proposals=tuple(memory_proposals),
        )


__all__ = [
    "ManualIntakeChannel",
    "ManualIntakeAction",
    "ManualIntakeSafetyDecision",
    "ManualIntakeDisabledAction",
    "ManualIntakeArtifact",
    "ManualIntakeRequest",
    "ManualIntakeResult",
    "ManualIntakeRouter",
]
