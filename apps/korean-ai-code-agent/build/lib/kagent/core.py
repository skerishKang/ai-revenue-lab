from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re

from .adapters import DeterministicBusiness14Preview
from .contracts import ClawTaskIntent, ExecutionMode
from .patching import PendingPatch
from .security import redact_secrets
from .workspace import RepositoryWorkspace, WorkspaceBoundaryError


class AgentBoundaryError(RuntimeError):
    pass


_KOREAN_TASK_RE = re.compile(r"[가-힣]")


@dataclass
class PermissionState:
    write: bool = False
    command: bool = False
    network: bool = False
    git_mutation: bool = False


@dataclass
class AgentSession:
    """Phase 1 compatibility façade over separated B54 product boundaries."""

    root: Path
    task: str
    route: str = "business14/auto"
    permissions: PermissionState = field(default_factory=PermissionState)
    read_files: list[str] = field(default_factory=list)
    _workspace: RepositoryWorkspace | None = field(default=None, repr=False)
    _pending_patch: PendingPatch | None = field(default=None, repr=False)

    @classmethod
    def open(cls, root: str | Path, task: str, route: str = "business14/auto") -> "AgentSession":
        try:
            workspace = RepositoryWorkspace.open(root)
        except WorkspaceBoundaryError as exc:
            raise AgentBoundaryError(str(exc)) from exc
        normalized_task = task.strip()
        if not normalized_task:
            raise AgentBoundaryError("한국어 작업 설명이 필요합니다.")
        if not _KOREAN_TASK_RE.search(normalized_task):
            raise AgentBoundaryError("Phase 1에서는 한국어 작업 설명을 한 글자 이상 포함해야 합니다.")
        return cls(
            root=workspace.root,
            task=normalized_task,
            route=route,
            _workspace=workspace,
        )

    @property
    def workspace(self) -> RepositoryWorkspace:
        if self._workspace is None:
            self._workspace = RepositoryWorkspace.open(self.root)
        return self._workspace

    @property
    def proposed_path(self) -> str | None:
        return None if self._pending_patch is None else self._pending_patch.relative_path

    @property
    def original_text(self) -> str | None:
        return None if self._pending_patch is None else self._pending_patch.original_text

    @property
    def proposed_text(self) -> str | None:
        return None if self._pending_patch is None else self._pending_patch.proposed_text

    def task_intent(
        self,
        *,
        task_id: str,
        execution_mode: ExecutionMode = ExecutionMode.LOCAL,
        source_surface: str = "cli",
        requested_revision: str | None = None,
        trace_id: str | None = None,
    ) -> ClawTaskIntent:
        """Project the foreground session into the new B54 product task boundary.

        Route/provider details intentionally do not enter the task contract.
        """
        return ClawTaskIntent(
            task_id=task_id,
            task=self.task,
            repository_ref=str(self.root),
            execution_mode=execution_mode,
            requested_revision=requested_revision,
            source_surface=source_surface,
            trace_id=trace_id,
        )

    def contained(self, relative: str | Path) -> Path:
        try:
            return self.workspace.contained(relative)
        except WorkspaceBoundaryError as exc:
            raise AgentBoundaryError(str(exc)) from exc

    def inspect(self, limit: int = 12) -> list[str]:
        try:
            files = self.workspace.inspect(limit=limit)
        except WorkspaceBoundaryError as exc:
            raise AgentBoundaryError(str(exc)) from exc
        self.read_files = files
        return files

    def plan(self) -> list[str]:
        return [
            "저장소 구조와 관련 파일을 읽기 전용으로 확인",
            "작업 범위를 한 파일의 합성 변경안으로 제한",
            f"Business 14 경로 사용: {self.route}",
            "변경 전 unified diff를 표시하고 쓰기 권한을 요청",
            "명령 실행은 별도 승인 없이는 수행하지 않음",
            "최종 apply / reject / revise 판단은 사용자에게 남김",
        ]

    def git_worktree_status(self) -> dict[str, object]:
        return self.workspace.git_worktree_status()

    def business14_mock_response(self) -> dict[str, object]:
        """Backward-compatible network-free B14 route preview."""
        return DeterministicBusiness14Preview().preview(task=self.task, route=self.route)

    def prepare_demo_patch(self, relative: str | None = None) -> str:
        if not self.read_files:
            self.inspect()
        target = relative or next(
            (p for p in self.read_files if p.endswith((".py", ".js", ".ts", ".md", ".txt"))),
            None,
        )
        if target is None:
            self._pending_patch = PendingPatch(
                relative_path="KAGENT_DEMO_NOTE.md",
                original_text="",
                proposed_text="# KAgent preview\n\n합성 변경 미리보기입니다. 실제 저장 전 승인이 필요합니다.\n",
            )
        else:
            path = self.contained(target)
            if path.is_symlink():
                raise AgentBoundaryError("심볼릭 링크 대상 변경은 이 단계에서 차단됩니다.")
            try:
                original = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                raise AgentBoundaryError("텍스트 파일만 변경 미리보기를 만들 수 있습니다.") from exc
            marker = "\n\n<!-- KAGENT SYNTHETIC PREVIEW: user approval required -->\n"
            self._pending_patch = PendingPatch(
                relative_path=target,
                original_text=original,
                proposed_text=original + marker,
            )
        return self.diff()

    def diff(self) -> str:
        return "" if self._pending_patch is None else self._pending_patch.unified_diff()

    def apply(self) -> Path:
        if not self.permissions.write:
            raise AgentBoundaryError("쓰기 권한이 승인되지 않았습니다.")
        patch = self._pending_patch
        if patch is None:
            raise AgentBoundaryError("적용할 변경 미리보기가 없습니다.")
        target = self.contained(patch.relative_path)
        if target.exists() and target.is_symlink():
            raise AgentBoundaryError("심볼릭 링크 쓰기가 차단되었습니다.")

        if target.exists():
            try:
                current = target.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                raise AgentBoundaryError("적용 직전 원본 상태를 확인할 수 없습니다.") from exc
            if current != patch.original_text:
                raise AgentBoundaryError("미리보기 이후 파일이 변경되어 적용을 중단합니다.")
        elif patch.original_text != "":
            raise AgentBoundaryError("미리보기 이후 원본 파일이 사라져 적용을 중단합니다.")

        target.write_text(patch.proposed_text, encoding="utf-8")
        return target

    def reject(self) -> None:
        self._pending_patch = None
        self.permissions.write = False

    def runtime_contract(self) -> dict[str, object]:
        return {
            "route": self.route,
            "network": self.permissions.network,
            "git_mutation": self.permissions.git_mutation,
            "business14_base_url_configured": bool(os.getenv("BUSINESS14_BASE_URL")),
            "business14_model": os.getenv("BUSINESS14_MODEL", "automatic-route"),
            "business14_preview": self.business14_mock_response(),
            "git_worktree": self.git_worktree_status(),
        }
