"""Named Engine service bundle for the Worker composition root (#1792 R2A).

Both entrypoint modules build their request services through this explicit
named type instead of positional tuples. The canonical composition root
(``worker_identity.py``) overrides which factory the shared ``Default``
dispatch uses; a field is selected by name, so an entrypoint can no longer
silently disagree with the fetch route about how many services exist.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agent_skill_service import AgentSkillEngineService
from app.memory_service import MemoryRetrievalEngineService
from app.orchestration_service import OrchestrationEngineService
from app.service import EngineService
from app.streaming_service import StreamingEngineService
from app.web_research_service import WebResearchEngineService


@dataclass(frozen=True)
class EngineServices:
    """One explicit service per Engine route family, addressed by name."""

    completed: EngineService
    streaming: StreamingEngineService
    orchestration: OrchestrationEngineService
    research: WebResearchEngineService
    memory: MemoryRetrievalEngineService
    agent_skill: AgentSkillEngineService

    def __post_init__(self) -> None:
        for name in (
            "completed",
            "streaming",
            "orchestration",
            "research",
            "memory",
            "agent_skill",
        ):
            if getattr(self, name) is None:
                raise ValueError(f"engine service {name!r} must not be None")
