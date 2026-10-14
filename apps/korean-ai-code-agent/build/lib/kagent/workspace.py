from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess


class WorkspaceBoundaryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RepositoryWorkspace:
    """Selected repository filesystem/Git read boundary.

    The workspace owns path containment and read-only Git inspection. It does
    not own task planning, model execution, command authorization, or writes.
    """

    root: Path

    @classmethod
    def open(cls, root: str | Path) -> "RepositoryWorkspace":
        resolved = Path(root).expanduser().resolve()
        if not resolved.is_dir():
            raise WorkspaceBoundaryError("저장소 경로가 존재하지 않습니다.")
        return cls(root=resolved)

    def contained(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceBoundaryError("저장소 바깥 경로 접근이 차단되었습니다.") from exc
        return candidate

    def inspect(self, limit: int = 12) -> list[str]:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 1_000:
            raise WorkspaceBoundaryError("inspect limit must be between 1 and 1000")
        ignored = {".git", ".venv", "node_modules", "__pycache__"}
        files: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if any(part in ignored for part in path.parts):
                continue
            if path.is_symlink():
                continue
            if path.is_file():
                try:
                    resolved = path.resolve()
                    resolved.relative_to(self.root)
                    rel = str(path.relative_to(self.root))
                except (OSError, ValueError):
                    continue
                files.append(rel)
                if len(files) >= limit:
                    break
        return files

    def git_worktree_status(self) -> dict[str, object]:
        """Read Git worktree state without modifying Git or repository files."""
        command = ["git", "status", "--porcelain=v1", "--untracked-files=all"]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
        except FileNotFoundError:
            return {
                "available": False,
                "is_git_repository": False,
                "clean": None,
                "changed_count": 0,
                "status": "git_unavailable",
            }
        except subprocess.TimeoutExpired:
            return {
                "available": True,
                "is_git_repository": False,
                "clean": None,
                "changed_count": 0,
                "status": "git_status_timeout",
            }

        if result.returncode != 0:
            return {
                "available": True,
                "is_git_repository": False,
                "clean": None,
                "changed_count": 0,
                "status": "not_git_repository",
            }

        entries = [line for line in result.stdout.splitlines() if line.strip()]
        return {
            "available": True,
            "is_git_repository": True,
            "clean": not entries,
            "changed_count": len(entries),
            "status": "clean" if not entries else "dirty",
        }
