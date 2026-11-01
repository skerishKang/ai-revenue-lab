"""재발 방지 계약: 은퇴한 b14/auto 레인이 저장소에 돌아오면 CI가 실패한다 (B7).

검사 대상은 운영 표면이다: apps·packages·static·스크립트·설정 예시.
테스트 파일은 제외한다 — 부존재·거절 단언이 은퇴한 id를 문자열로 지칭하는 것은
이 계약의 정상이다. 운영 코드에서 이 이름들이 발견되면 이 테스트는 파일 목록과
함께 실패하고, 해당 파일은 같은 PR에서 지워야 한다.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

BANNED_TOKENS = (
    "b14/auto",
    "AUTO_B14_MODEL_ID",
    "B14_AUTO_MODEL_ID",
    "B14_AUTO_CHAIN",
    "RouteMode.AUTO",
    "AUTO_FALLBACK",
    "auto_stream_gateway",
    "ensure_generic_auto_enabled",
    "B14_ENABLE_FUTURE_AUTO",
    "SUSPENDED_AUTO_MODEL",
)

SCAN_ROOTS = (
    "apps/korean-ai-platform/app",
    "apps/korean-ai-platform/static",
    "apps/korean-ai-platform/templates",
    "apps/korean-ai-platform/worker.py",
    "apps/padiem-chat/app",
    "apps/padiem-chat/static",
    "apps/padiem-chat/worker.py",
    "apps/padiem-ai-engine/app",
    "apps/padiem-designer/app",
    "apps/padiem-designer/static",
    "apps/living-fiction/app",
    "apps/living-learning/app",
    "apps/b66-quote-adapter/app",
    "apps/korean-ai-code-agent/src",
    "packages/padiem-ai-core/padiem_ai_core",
    "packages/padiem-control-plane/padiem_control_plane",
    "deploy",
)

SCAN_SUFFIXES = {
    ".py", ".js", ".ts", ".json", ".toml", ".html", ".css",
    ".example", ".sh", ".ps1", ".md",
}


def _iter_scan_files() -> list[Path]:
    files: list[Path] = []
    for rel in SCAN_ROOTS:
        base = ROOT / rel
        if base.is_file():
            files.append(base)
            continue
        if not base.is_dir():
            continue
        files.extend(
            p for p in base.rglob("*")
            if p.is_file() and p.suffix in SCAN_SUFFIXES
        )
    return files


def _is_test_path(path: Path) -> bool:
    parts = {segment.lower() for segment in path.parts}
    return (
        "tests" in parts
        or any(name.startswith("test_") for name in parts)
        or path.name.startswith("test_")
        or path.name.endswith("_test.py")
    )


def test_the_retired_auto_lane_never_returns() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _iter_scan_files():
        if _is_test_path(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = [token for token in BANNED_TOKENS if token in text]
        if hits:
            offenders[path.relative_to(ROOT).as_posix()] = hits

    assert not offenders, (
        "은퇴한 b14/auto 레인의 식별자가 운영 표면에 다시 나타났다. "
        "자동 선택·자동 폴백은 대표 결정으로 폐지되었다(B7/#4844). "
        "아래 파일에서 해당 식별자를 지우고, 자동 경로 대신 명시적 등록 모델 또는 "
        "설정 오류 실패 폐쇄를 사용한다:\n"
        + "\n".join(f"- {file}: {', '.join(tokens)}" for file, tokens in sorted(offenders.items()))
    )
