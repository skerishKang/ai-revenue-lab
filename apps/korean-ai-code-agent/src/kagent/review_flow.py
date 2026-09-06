"""#1957: Claw repository review flow — the first repeatable product workflow.

Turns the one-shot ``p01-run`` execution path into a product flow the owner
runs daily: select files in a repository, review them through P01/B14, and get
a structured Korean report.

This module only consumes the existing P01 adapter surface
(``P01CoreOrchestrationAdapter`` / ``P01RequestFactory`` / pinned agent
profile). It adds no model/provider/credential authority and no new
configuration: an unconfigured Engine fails closed with the existing
``p01_engine_not_configured`` error. Input validation is fail-closed with
explicit review error codes; binary/non-UTF-8 files are never silently
dropped — they are recorded as skipped in the report.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import glob
import os
from pathlib import Path
import sys

from .contracts import ClawRunStatus, RunProjection
from .core import redact_secrets
from .p01_adapter import (
    ClawOrchestrationOutcome,
    P01AdapterError,
    P01CoreOrchestrationAdapter,
)
from .p01_run_flow import create_claw_run, p01_adapter_from_environment

MAX_REVIEW_FILES = 20
MAX_REVIEW_FILE_BYTES = 200 * 1024
MAX_REVIEW_TOTAL_BYTES = 1024 * 1024

_GLOB_META = frozenset("*?[")


class ReviewFlowError(P01AdapterError):
    """Fail-closed repository review flow input or execution error."""


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    projection: RunProjection
    answer: str | None
    p01_run_id: str | None
    p01_event_count: int
    repository: str
    reviewed: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    out_path: Path | None = None

    def report_text(self) -> str:
        lines = ["# 저장소 리뷰 보고서", ""]
        lines.append(f"- 저장소: {self.repository}")
        lines.append(
            f"- 리뷰 대상: {len(self.reviewed) + len(self.skipped)}개 · "
            f"리뷰 완료: {len(self.reviewed)}개 · 건너뜀: {len(self.skipped)}개"
        )
        for path in self.reviewed:
            lines.append(f"  - 리뷰 완료: {path}")
        for path, reason in self.skipped:
            lines.append(f"  - 건너뜀: {path} — {reason}")
        lines.append(
            f"- P01 실행 ID: {self.p01_run_id or '-'} · "
            f"이벤트 {self.p01_event_count}건 · 상태: {self.projection.status.value}"
        )
        if self.out_path is not None:
            lines.append(f"- 보고서 파일: {self.out_path} (기록됨)")
        lines.append("")
        lines.append("## 리뷰 결과")
        lines.append("")
        lines.append(self.answer if self.answer else "(리뷰 결과 없음)")
        return "\n".join(lines)


def _has_glob_meta(value: str) -> bool:
    return any(char in _GLOB_META for char in value)


def _glob_candidates(repository: Path, target: str) -> list[Path]:
    pattern = target if os.path.isabs(target) else str(repository / target)
    return [Path(item) for item in glob.glob(pattern, recursive=True)]


def _resolve_review_files(repository: Path, targets: list[str]) -> list[Path]:
    root = repository.resolve()
    resolved: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        if _has_glob_meta(target):
            candidates = _glob_candidates(root, target)
        else:
            raw = Path(target)
            candidate = raw if raw.is_absolute() else root / raw
            if not candidate.exists():
                raise ReviewFlowError(
                    "review_target_missing",
                    f"리뷰 대상 경로가 존재하지 않습니다: {target}",
                )
            candidates = [candidate]
        if not candidates:
            raise ReviewFlowError(
                "review_target_missing",
                f"리뷰 대상 glob이 일치하지 않습니다: {target}",
            )
        for candidate in candidates:
            try:
                current = candidate.resolve()
            except OSError:
                raise ReviewFlowError(
                    "review_target_invalid",
                    f"리뷰 대상 경로를 확인할 수 없습니다: {target}",
                )
            if not current.is_relative_to(root):
                raise ReviewFlowError(
                    "review_target_invalid",
                    f"리뷰 대상이 저장소 밖입니다: {target}",
                )
            if not current.is_file():
                raise ReviewFlowError(
                    "review_target_missing",
                    f"리뷰 대상이 파일이 아닙니다: {target}",
                )
            if current not in seen:
                seen.add(current)
                resolved.append(current)
    return resolved


def _check_review_limits(files: list[Path]) -> None:
    if len(files) > MAX_REVIEW_FILES:
        raise ReviewFlowError(
            "review_input_too_large",
            f"리뷰 대상 파일이 {len(files)}개로 한도({MAX_REVIEW_FILES}개)를 초과합니다.",
        )
    total = 0
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            raise ReviewFlowError(
                "review_target_missing",
                f"리뷰 대상 파일을 확인할 수 없습니다: {path}",
            )
        if size > MAX_REVIEW_FILE_BYTES:
            raise ReviewFlowError(
                "review_input_too_large",
                f"파일이 개당 한도(200KB)를 초과합니다: {path}",
            )
        total += size
    if total > MAX_REVIEW_TOTAL_BYTES:
        raise ReviewFlowError(
            "review_input_too_large",
            "리뷰 대상 총 크기가 한도(1MB)를 초과합니다.",
        )


def _collect_review_files(
    files: list[Path], root: Path
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    reviewed: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except OSError:
            raise ReviewFlowError(
                "review_target_missing",
                f"리뷰 대상 파일을 읽을 수 없습니다: {rel}",
            )
        if b"\x00" in data:
            skipped.append((rel, "바이너리 파일 — 건너뜀"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append((rel, "비UTF-8 인코딩 — 건너뜀"))
            continue
        reviewed.append((rel, text))
    return reviewed, skipped


def _build_review_prompt(repository: str, files: list[tuple[str, str]]) -> str:
    sections = [
        f"# 저장소 리뷰 요청\n\n저장소: {repository}\n리뷰 대상 파일 {len(files)}개:\n"
    ]
    for index, (rel_path, content) in enumerate(files, start=1):
        sections.append(f"## 파일 {index}: {rel_path}\n```\n{content}\n```\n")
    sections.append(
        "각 파일을 리뷰하고 한국어로 구조화된 보고서를 작성하세요:\n"
        "- 파일별 핵심 관찰\n"
        "- 버그 · 보안 · 품질 위험\n"
        "- 우선순위 있는 개선 제안"
    )
    return "\n".join(sections)


async def _execute_review(
    repository: str,
    task: str,
    adapter: P01CoreOrchestrationAdapter,
    *,
    run_id: str | None,
) -> ClawOrchestrationOutcome:
    run = create_claw_run(repository, task, run_id=run_id)
    return await adapter.execute(run)


def run_review(
    repository: Path,
    targets: list[str],
    adapter: P01CoreOrchestrationAdapter,
    *,
    run_id: str | None = None,
    out_path: Path | None = None,
) -> ReviewOutcome:
    if not repository.exists() or not repository.is_dir():
        raise ReviewFlowError(
            "review_target_missing",
            "저장소 경로가 존재하지 않거나 디렉터리가 아닙니다.",
        )
    root = repository.resolve()
    files = _resolve_review_files(root, targets)
    _check_review_limits(files)
    reviewed, skipped = _collect_review_files(files, root)
    if not reviewed:
        raise ReviewFlowError(
            "review_target_missing",
            "리뷰할 텍스트 파일이 없습니다 (전부 건너뜀).",
        )
    prompt = _build_review_prompt(str(root), reviewed)
    outcome = asyncio.run(_execute_review(str(root), prompt, adapter, run_id=run_id))
    result = ReviewOutcome(
        projection=outcome.projection,
        answer=outcome.answer,
        p01_run_id=outcome.p01_run_id,
        p01_event_count=outcome.p01_event_count,
        repository=str(root),
        reviewed=tuple(rel for rel, _ in reviewed),
        skipped=tuple(skipped),
        out_path=out_path,
    )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.report_text(), encoding="utf-8")
    return result


def _force_utf8_stdio() -> None:
    """Make report printing independent of the host console codepage.

    Windows CI defaults ``sys.stdout``/``sys.stderr`` to the ANSI codepage
    (e.g. cp1252), which cannot encode the Korean report. Reconfigure both to
    UTF-8 so ``print`` never fails with ``UnicodeEncodeError``.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass


def run_review_command(
    repository: Path,
    targets: list[str],
    *,
    adapter: P01CoreOrchestrationAdapter | None = None,
    environ: Mapping[str, str] | None = None,
    run_id: str | None = None,
    out_path: Path | None = None,
) -> int:
    _force_utf8_stdio()
    try:
        active = (
            adapter if adapter is not None else p01_adapter_from_environment(environ)
        )
        outcome = run_review(
            repository,
            targets,
            active,
            run_id=run_id,
            out_path=out_path,
        )
    except P01AdapterError as exc:
        print(
            f"KAGENT_REVIEW: {exc.code} · {redact_secrets(exc.safe_message)}",
            file=sys.stderr,
        )
        return 2
    print(
        f"REVIEW run={outcome.projection.run_id} "
        f"status={outcome.projection.status.value} "
        f"p01_run={outcome.p01_run_id} events={outcome.p01_event_count}"
    )
    print(outcome.report_text())
    return 0 if outcome.projection.status is ClawRunStatus.COMPLETED else 1


__all__ = [
    "MAX_REVIEW_FILE_BYTES",
    "MAX_REVIEW_FILES",
    "MAX_REVIEW_TOTAL_BYTES",
    "ReviewFlowError",
    "ReviewOutcome",
    "run_review",
    "run_review_command",
]
