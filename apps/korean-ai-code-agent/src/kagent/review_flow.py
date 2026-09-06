"""#1957/#1994: Claw repository review flow — per-file requests, local aggregation.

Turns the one-shot ``p01-run`` execution path into a product flow the owner
runs daily: select files in a repository, review them through P01/B14, and get
a structured Korean report.

#1994: the Kilo Gateway free window (~10s) truncates long single-request
generations. The flow now issues ONE orchestration request per file (or per
small chunk of up to ``MAX_REVIEW_FILES_PER_CHUNK`` files, bounded in total
characters) and assembles the final report LOCALLY: header, per-file sections,
and an aggregate risk list. A file larger than the per-chunk budget is
forced-sliced into ``MAX_REVIEW_CHUNK_CHARS``-sized parts (each its own
request, labeled ``(파트 i/n)``), so no assembled task can exceed the
``ClawRun`` task bound and the whole file stays covered. A failed per-file
request marks that section failed-with-code and continues — a partial report
is still valuable. A ``ContractError``/``ValueError`` (e.g. an over-bound
task) is isolated the same way as ``review_task_too_large`` without exposing a
raw traceback. Answers that look truncated (no terminal punctuation near the
historical cut length) are marked ``"(생성 창 초과로 잘림)"`` visibly instead
of being hidden.

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
from math import ceil
import os
from pathlib import Path
import re
import sys
import uuid

from .contracts import ClawRunStatus, ContractError, ExecutionMode, RunProjection
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
MAX_REVIEW_FILES_PER_CHUNK = 2
MAX_REVIEW_CHUNK_CHARS = 3_500

_REVIEW_TASK_TOO_LARGE = "review_task_too_large"
_TRUNCATION_MARKER = "(생성 창 초과로 잘림)"
_TERMINAL_CHARS = frozenset(".!?)]」』】\"'`")
_MIN_TRUNCATION_SUSPECT_CHARS = 120
_RISK_LINE = re.compile(r"^\s*위험\s*:\s*(.+)$", re.MULTILINE)

_GLOB_META = frozenset("*?[")


@dataclass(frozen=True, slots=True)
class _ReviewPart:
    """One file segment carried by a single review request.

    ``part_label`` is empty for a whole file and ``" (파트 i/n)"`` for a slice
    of a file that exceeded the per-chunk character budget.
    """

    rel_path: str
    content: str
    part_label: str = ""

    @property
    def display_name(self) -> str:
        return f"{self.rel_path}{self.part_label}"


class ReviewFlowError(P01AdapterError):
    """Fail-closed repository review flow input or execution error."""


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    projection: RunProjection
    p01_run_id: str | None
    p01_event_count: int
    p01_runs: tuple[tuple[str, str, int], ...]
    repository: str
    reviewed: tuple[str, ...]
    failed: tuple[tuple[str, str], ...]
    truncated: tuple[str, ...]
    skipped: tuple[tuple[str, str], ...]
    sections: tuple[tuple[str, str], ...]
    out_path: Path | None = None

    def report_text(self) -> str:
        lines = ["# 저장소 리뷰 보고서", ""]
        lines.append(f"- 저장소: {self.repository}")
        lines.append(
            f"- 리뷰 대상: {len(self.reviewed) + len(self.failed) + len(self.skipped)}개 · "
            f"리뷰 완료: {len(self.reviewed)}개 · "
            f"실패: {len(self.failed)}개 · 건너뜀: {len(self.skipped)}개"
        )
        for path in self.reviewed:
            marker = f" · {_TRUNCATION_MARKER}" if path in self.truncated else ""
            lines.append(f"  - 리뷰 완료: {path}{marker}")
        for path, code in self.failed:
            lines.append(f"  - 실패: {path} — {code}")
        for path, reason in self.skipped:
            lines.append(f"  - 건너뜀: {path} — {reason}")
        runs_desc = ", ".join(
            f"{claw}(p01={p01 or '-'})" for claw, p01, _ in self.p01_runs
        )
        lines.append(
            f"- P01 실행 {len(self.p01_runs)}건: {runs_desc or '-'} · "
            f"상태: {self.projection.status.value}"
        )
        if self.out_path is not None:
            lines.append(f"- 보고서 파일: {self.out_path} (기록됨)")
        lines.append("")
        lines.append("## 리뷰 결과")
        lines.append("")
        for label, section in self.sections:
            lines.append(f"### {label}")
            lines.append("")
            lines.append(section)
            lines.append("")
        if self.failed:
            lines.append("### 실패한 파일")
            lines.append("")
            for path, code in self.failed:
                lines.append(f"- {path} — 리뷰 요청 실패 ({code})")
            lines.append("")
        lines.append("## 통합 위험 목록")
        lines.append("")
        risks = self._aggregate_risks()
        if risks:
            for label, risk in risks:
                lines.append(f"- {label}: {risk}")
        else:
            lines.append("(추출된 위험 항목 없음)")
        return "\n".join(lines)

    def _aggregate_risks(self) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        for label, section in self.sections:
            for risk in _extract_risk_lines(section):
                result.append((label, risk))
            if not _extract_risk_lines(section) and _TRUNCATION_MARKER in section:
                result.append((label, f"위험 정보 누락 — {_TRUNCATION_MARKER}"))
        for path, code in self.failed:
            result.append((path, f"리뷰 요청 실패 ({code})"))
        return result


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


def _chunk_review_files(
    reviewed: list[tuple[str, str]],
) -> list[list[_ReviewPart]]:
    """Group reviewed files into bounded per-request chunks.

    A chunk holds at most ``MAX_REVIEW_FILES_PER_CHUNK`` files and at most
    ``MAX_REVIEW_CHUNK_CHARS`` total content characters, so every orchestration
    request stays inside one free-window-sized unit. A single file larger than
    the per-chunk budget is forced-sliced into budget-sized parts, each of
    which becomes its own chunk — the whole file stays fully covered across
    requests and the assembled task never exceeds the ``ClawRun`` task bound.
    """
    chunks: list[list[_ReviewPart]] = []
    current: list[_ReviewPart] = []
    current_chars = 0
    for rel_path, content in reviewed:
        size = len(content)
        if size > MAX_REVIEW_CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = []
                current_chars = 0
            part_count = ceil(size / MAX_REVIEW_CHUNK_CHARS)
            for part_index in range(part_count):
                start = part_index * MAX_REVIEW_CHUNK_CHARS
                chunks.append(
                    [
                        _ReviewPart(
                            rel_path,
                            content[start : start + MAX_REVIEW_CHUNK_CHARS],
                            f" (파트 {part_index + 1}/{part_count})",
                        )
                    ]
                )
            continue
        if current and (
            len(current) >= MAX_REVIEW_FILES_PER_CHUNK
            or current_chars + size > MAX_REVIEW_CHUNK_CHARS
        ):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(_ReviewPart(rel_path, content))
        current_chars += size
    if current:
        chunks.append(current)
    return chunks


def _build_review_prompt(repository: str, files: list[_ReviewPart]) -> str:
    sections = [
        f"# 저장소 리뷰 요청\n\n저장소: {repository}\n리뷰 대상 파일 {len(files)}개:\n"
    ]
    for index, part in enumerate(files, start=1):
        sections.append(
            f"## 파일 {index}: {part.display_name}\n```\n{part.content}\n```\n"
        )
    sections.append(
        "각 파일을 리뷰하고 한국어로 구조화된 파일별 리뷰 섹션을 작성하세요:\n"
        "- 파일별 핵심 관찰 (2-3문장)\n"
        "- 버그 · 보안 · 품질 위험\n"
        "- 우선순위 있는 개선 제안\n"
        "파일마다 마지막 줄에 '위험: [HIGH|MEDIUM|LOW] — 요약' 형태의 위험 한 줄을 반드시 포함하세요.\n"
        "출력 길이 가이드: 각 파일별 섹션은 400자 이내로 간결하게 작성하세요."
    )
    return "\n".join(sections)


def _looks_truncated(answer: str) -> bool:
    """Heuristic: no terminal punctuation AND length near historical cut points."""
    text = (answer or "").strip()
    if not text:
        return False
    if text.endswith("```"):
        text = text[:-3].rstrip()
    if len(text) < _MIN_TRUNCATION_SUSPECT_CHARS:
        return False
    return text[-1] not in _TERMINAL_CHARS


def _extract_risk_lines(section_text: str) -> list[str]:
    return [line.strip() for line in _RISK_LINE.findall(section_text or "")]


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

    flow_run_id = (
        run_id
        if isinstance(run_id, str) and run_id.startswith("run_")
        else f"run_{uuid.uuid4().hex[:24]}"
    )
    sections: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    truncated: list[str] = []
    p01_runs: list[tuple[str, str, int]] = []

    for index, chunk in enumerate(_chunk_review_files(reviewed), start=1):
        chunk_run_id = f"{flow_run_id}_{index}"
        prompt = _build_review_prompt(str(root), chunk)
        try:
            outcome = asyncio.run(
                _execute_review(str(root), prompt, adapter, run_id=chunk_run_id)
            )
        except (ContractError, ValueError):
            for part in chunk:
                failed.append((part.rel_path, _REVIEW_TASK_TOO_LARGE))
            continue
        except P01AdapterError as exc:
            for part in chunk:
                failed.append((part.rel_path, exc.code))
            continue
        if (
            outcome.projection.status is not ClawRunStatus.COMPLETED
            or not outcome.answer
        ):
            for part in chunk:
                failed.append((part.rel_path, outcome.projection.status.value))
            continue
        p01_runs.append(
            (outcome.projection.run_id, outcome.p01_run_id, outcome.p01_event_count)
        )
        section_text = outcome.answer
        if _looks_truncated(section_text):
            truncated.extend(part.rel_path for part in chunk)
            section_text = f"{section_text.rstrip()}\n\n{_TRUNCATION_MARKER}"
        label = ", ".join(part.display_name for part in chunk)
        sections.append((label, section_text))

    suffix = flow_run_id[4:] if flow_run_id.startswith("run_") else flow_run_id
    projection = RunProjection(
        run_id=flow_run_id,
        task_id=f"task_{suffix}",
        status=ClawRunStatus.COMPLETED,
        execution_mode=ExecutionMode.LOCAL,
    )
    result = ReviewOutcome(
        projection=projection,
        p01_run_id=p01_runs[0][1] if p01_runs else None,
        p01_event_count=sum(count for _, _, count in p01_runs),
        p01_runs=tuple(p01_runs),
        repository=str(root),
        reviewed=tuple(rel for rel, _ in reviewed),
        failed=tuple(failed),
        truncated=tuple(dict.fromkeys(truncated)),
        skipped=tuple(skipped),
        sections=tuple(sections),
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
        f"requests={len(outcome.p01_runs)} "
        f"p01_run={outcome.p01_run_id} events={outcome.p01_event_count}"
    )
    print(outcome.report_text())
    return 0 if outcome.projection.status is ClawRunStatus.COMPLETED else 1


__all__ = [
    "MAX_REVIEW_CHUNK_CHARS",
    "MAX_REVIEW_FILE_BYTES",
    "MAX_REVIEW_FILES",
    "MAX_REVIEW_FILES_PER_CHUNK",
    "MAX_REVIEW_TOTAL_BYTES",
    "ReviewFlowError",
    "ReviewOutcome",
    "run_review",
    "run_review_command",
]
