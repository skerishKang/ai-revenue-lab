"""Named Engine service bundle for the Worker composition root (#1792 R2A).

Both entrypoint modules build their request services through this explicit
named type instead of positional tuples. The canonical composition root
(``worker_identity.py``) overrides which factory the shared ``Default`` dispatch
uses; a field is selected by name, so an entrypoint can no longer silently
disagree with the fetch route about how many services exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent_skill_service import AgentSkillEngineService
from app.attachment_admission_service import AttachmentAdmissionEngineService
from app.auth_session_scope_authority import AuthSessionScopeAuthority
from app.browser_control_owner_ticket_issue_service import (
    BrowserControlOwnerTicketIssueEngineService,
)
from app.document_admission_service import DocumentAdmissionEngineService
from app.document_context_service import DocumentContextEngineService
from app.idempotency_replay_service import IdempotencyReplayEngineService
from app.memory_service import MemoryRetrievalEngineService
from app.multimodal_attachment_service import (
    MultimodalAttachmentEngineService,
    MultimodalStreamingEngineService,
)
from app.orchestration_service import OrchestrationEngineService
from app.service import EngineService
from app.streaming_service import StreamingEngineService
from app.tool_execution_service import ToolExecutionEngineService
from app.web_research_service import WebResearchEngineService


@dataclass(frozen=True)
class EngineServices:
    """One explicit service per Engine route family, addressed by name.

    Agent/Skill, multimodal attachment projection and the trusted document
    context route are optional source seams until their trusted Production
    authority is activated. Absence means fail-closed/unavailable, never an
    alternate runtime or storage fallback.
    """

    completed: EngineService
    streaming: StreamingEngineService
    orchestration: OrchestrationEngineService
    research: WebResearchEngineService
    memory: MemoryRetrievalEngineService
    agent_skill: AgentSkillEngineService | None = None
    multimodal: MultimodalAttachmentEngineService | None = None
    multimodal_streaming: MultimodalStreamingEngineService | None = None
    documents: DocumentContextEngineService | None = None
    tool_execution: ToolExecutionEngineService | None = None
    # #3782 private signed-caller browser ticket issuance; absent until the
    # independent owner D1 and genuine canonical USER session are provisioned.
    browser_p01_ticket_issue: BrowserControlOwnerTicketIssueEngineService | None = None
    # #1964 source slice: replay stays fail-closed until the trusted durable
    # idempotency adapter is explicitly composed.
    idempotency_replay: IdempotencyReplayEngineService | None = None
    scope_authority: AuthSessionScopeAuthority | None = None
    attachment_admission: AttachmentAdmissionEngineService | None = None
    # #2764 source composition: the document admission seam follows the same
    # named-bundle convention as attachment admission; absence fails closed.
    document_admission: DocumentAdmissionEngineService | None = None

    def __post_init__(self) -> None:
        for name in ("completed", "streaming", "orchestration", "research", "memory"):
            if getattr(self, name) is None:
                raise ValueError(f"engine service {name!r} must not be None")
        if self.agent_skill is not None and not isinstance(
            self.agent_skill, AgentSkillEngineService
        ):
            raise ValueError(
                "engine service 'agent_skill' must be AgentSkillEngineService or None"
            )
        if self.multimodal is not None and not isinstance(
            self.multimodal, MultimodalAttachmentEngineService
        ):
            raise ValueError(
                "engine service 'multimodal' must be MultimodalAttachmentEngineService or None"
            )
        if self.multimodal_streaming is not None and not isinstance(
            self.multimodal_streaming, MultimodalStreamingEngineService
        ):
            raise ValueError(
                "engine service 'multimodal_streaming' must be MultimodalStreamingEngineService or None"
            )
        if self.documents is not None and not isinstance(
            self.documents, DocumentContextEngineService
        ):
            raise ValueError(
                "engine service 'documents' must be DocumentContextEngineService or None"
            )
        if self.browser_p01_ticket_issue is not None and not isinstance(
            self.browser_p01_ticket_issue, BrowserControlOwnerTicketIssueEngineService
        ):
            raise ValueError(
                "engine service 'browser_p01_ticket_issue' must be canonical or None"
            )
        if self.tool_execution is not None and not isinstance(
            self.tool_execution, ToolExecutionEngineService
        ):
            raise ValueError(
                "engine service 'tool_execution' must be ToolExecutionEngineService or None"
            )
        if self.idempotency_replay is not None and not isinstance(
            self.idempotency_replay, IdempotencyReplayEngineService
        ):
            raise ValueError(
                "engine service 'idempotency_replay' must be IdempotencyReplayEngineService or None"
            )
        if self.attachment_admission is not None and not isinstance(
            self.attachment_admission, AttachmentAdmissionEngineService
        ):
            raise ValueError(
                "engine service 'attachment_admission' must be "
                "AttachmentAdmissionEngineService or None"
            )
        if self.document_admission is not None and not isinstance(
            self.document_admission, DocumentAdmissionEngineService
        ):
            raise ValueError(
                "engine service 'document_admission' must be "
                "DocumentAdmissionEngineService or None"
            )
