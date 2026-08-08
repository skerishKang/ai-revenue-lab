from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import difflib
import os


class AgentBoundaryError(RuntimeError):
    pass


@dataclass
class PermissionState:
    write: bool = False
    command: bool = False
    network: bool = False
    git_mutation: bool = False


@dataclass
class AgentSession:
    root: Path
    task: str
    route: str = "business14/auto"
    permissions: PermissionState = field(default_factory=PermissionState)
    read_files: list[str] = field(default_factory=list)
    proposed_path: str | None = None
    original_text: str | None = None
    proposed_text: str | None = None

    @classmethod
    def open(cls, root: str | Path, task: str, route: str = "business14/auto") -> "AgentSession":
        resolved = Path(root).expanduser().resolve()
        if not resolved.is_dir():
            raise AgentBoundaryError("저장소 경로가 존재하지 않습니다.")
        if not task.strip():
            raise AgentBoundaryError("한국어 작업 설명이 필요합니다.")
        return cls(root=resolved, task=task.strip(), route=route)

    def contained(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise AgentBoundaryError("저장소 바깥 경로 접근이 차단되었습니다.") from exc
        return candidate

    def inspect(self, limit: int = 12) -> list[str]:
        ignored = {".git", ".venv", "node_modules", "__pycache__"}
        files: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if any(part in ignored for part in path.parts):
                continue
            if path.is_file():
                try:
                    rel = str(path.relative_to(self.root))
                except ValueError:
                    continue
                files.append(rel)
                if len(files) >= limit:
                    break
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

    def prepare_demo_patch(self, relative: str | None = None) -> str:
        if not self.read_files:
            self.inspect()
        target = relative or next((p for p in self.read_files if p.endswith((".py", ".js", ".ts", ".md", ".txt"))), None)
        if target is None:
            self.proposed_path = "KAGENT_DEMO_NOTE.md"
            self.original_text = ""
            self.proposed_text = "# KAgent preview\n\n합성 변경 미리보기입니다. 실제 저장 전 승인이 필요합니다.\n"
        else:
            path = self.contained(target)
            if path.is_symlink():
                raise AgentBoundaryError("심볼릭 링크 대상 변경은 이 단계에서 차단됩니다.")
            try:
                original = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError) as exc:
                raise AgentBoundaryError("텍스트 파일만 변경 미리보기를 만들 수 있습니다.") from exc
            self.proposed_path = target
            self.original_text = original
            marker = "\n\n<!-- KAGENT SYNTHETIC PREVIEW: user approval required -->\n"
            self.proposed_text = original + marker
        return self.diff()

    def diff(self) -> str:
        if self.proposed_path is None or self.original_text is None or self.proposed_text is None:
            return ""
        return "".join(
            difflib.unified_diff(
                self.original_text.splitlines(keepends=True),
                self.proposed_text.splitlines(keepends=True),
                fromfile=f"a/{self.proposed_path}",
                tofile=f"b/{self.proposed_path}",
            )
        )

    def apply(self) -> Path:
        if not self.permissions.write:
            raise AgentBoundaryError("쓰기 권한이 승인되지 않았습니다.")
        if self.proposed_path is None or self.proposed_text is None:
            raise AgentBoundaryError("적용할 변경 미리보기가 없습니다.")
        target = self.contained(self.proposed_path)
        if target.exists() and target.is_symlink():
            raise AgentBoundaryError("심볼릭 링크 쓰기가 차단되었습니다.")
        target.write_text(self.proposed_text, encoding="utf-8")
        return target

    def reject(self) -> None:
        self.proposed_path = None
        self.original_text = None
        self.proposed_text = None
        self.permissions.write = False

    def runtime_contract(self) -> dict[str, str | bool]:
        return {
            "route": self.route,
            "network": self.permissions.network,
            "git_mutation": self.permissions.git_mutation,
            "business14_base_url_configured": bool(os.getenv("BUSINESS14_BASE_URL")),
            "business14_model": os.getenv("BUSINESS14_MODEL", "automatic-route"),
        }
