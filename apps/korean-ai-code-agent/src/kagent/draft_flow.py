"""#1985: Claw document draft flow v0 — 견적서/발주서 drafts from an input file.

Claw's first business use case (#1878 A): a draft-document flow. Input is a
text/markdown file containing the deal/order context; output is a structured
draft document (견적서 또는 발주서 초안) via P01/B14, never sent anywhere.

This module only consumes the existing P01 adapter surface
(``P01CoreOrchestrationAdapter`` / ``create_claw_run`` / pinned agent profile).
It adds no model/provider/credential authority: an unconfigured Engine fails
closed with the existing ``p01_engine_not_configured`` error. Input validation
is fail-closed with explicit draft error codes, following the review flow's
discipline (200 KB limit, UTF-8, path containment). The prompt hard-bans
hallucination: information absent from the input must be marked "입력 필요",
never invented — a business document must not be guessed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
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
from .review_flow import _force_utf8_stdio

MAX_DRAFT_INPUT_BYTES = 200 * 1024

DRAFT_DOC_TYPES = ("견적서", "발주서")

_DOC_TYPE_SECTIONS = {
    "견적서": (
        "- 공급받는 자\n"
        "- 공급자\n"
        "- 품목 · 수량 · 단가 (입력에 없는 금액은 \"입력 필요\"로 명기 — 추측 금지)\n"
        "- 합계 (입력된 수량·단가에 근거한 값만 명시, 근거가 없으면 \"입력 필요\")\n"
        "- 조건"
    ),
    "발주서": (
        "- 발주자\n"
        "- 공급처\n"
        "- 품목 · 수량 · 납기\n"
        "- 특이조건"
    ),
}

_ANTI_HALLUCINATION_RULE = (
    "입력에 없는 정보(금액 · 일정 · 회사명 등)는 절대 추측해 생성하지 말고 "
    "해당 항목을 \"입력 필요\"로 표기하세요."
)


class DraftFlowError(P01AdapterError):
    """Fail-closed document draft flow input or execution error."""


@dataclass(frozen=True, slots=True)
class DraftOutcome:
    projection: RunProjection
    answer: str | None
    p01_run_id: str | None
    p01_event_count: int
    repository: str
    doc_type: str
    input_path: str
    out_path: Path | None = None

    def report_text(self) -> str:
        lines = ["# 문서 초안 보고서", ""]
        lines.append(f"- 저장소: {self.repository}")
        lines.append(f"- 문서 유형: {self.doc_type}")
        lines.append(f"- 입력 파일: {self.input_path}")
        lines.append(
            f"- P01 실행 ID: {self.p01_run_id or '-'} · "
            f"이벤트 {self.p01_event_count}건 · 상태: {self.projection.status.value}"
        )
        if self.out_path is not None:
            lines.append(f"- 초안 파일: {self.out_path} (기록됨)")
        lines.append("")
        lines.append(f"## {self.doc_type} 초안 (DRAFT)")
        lines.append("")
        lines.append(self.answer if self.answer else "(초안 결과 없음)")
        return "\n".join(lines)


def _validate_doc_type(doc_type: str) -> str:
    if not isinstance(doc_type, str) or doc_type not in DRAFT_DOC_TYPES:
        allowed = ", ".join(DRAFT_DOC_TYPES)
        raise DraftFlowError(
            "draft_type_invalid",
            f"문서 유형은 {allowed} 중 하나여야 합니다: {doc_type!r}",
        )
    return doc_type


def _resolve_draft_input(repository: Path, input_path: str) -> Path:
    if not isinstance(input_path, str) or not input_path.strip():
        raise DraftFlowError(
            "draft_input_missing",
            "초안 입력 파일 경로가 제공되지 않았습니다.",
        )
    root = repository.resolve()
    raw = Path(input_path)
    candidate = raw if raw.is_absolute() else root / raw
    if not candidate.exists():
        raise DraftFlowError(
            "draft_input_missing",
            f"초안 입력 파일이 존재하지 않습니다: {input_path}",
        )
    try:
        current = candidate.resolve()
    except OSError:
        raise DraftFlowError(
            "draft_input_invalid",
            f"초안 입력 파일 경로를 확인할 수 없습니다: {input_path}",
        )
    if not current.is_relative_to(root):
        raise DraftFlowError(
            "draft_input_invalid",
            f"초안 입력 파일이 저장소 밖입니다: {input_path}",
        )
    if not current.is_file():
        raise DraftFlowError(
            "draft_input_missing",
            f"초안 입력이 파일이 아닙니다: {input_path}",
        )
    return current


def _read_draft_input(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        raise DraftFlowError(
            "draft_input_missing",
            f"초안 입력 파일을 확인할 수 없습니다: {path}",
        )
    if size > MAX_DRAFT_INPUT_BYTES:
        raise DraftFlowError(
            "draft_input_too_large",
            f"초안 입력 파일이 한도(200KB)를 초과합니다: {path}",
        )
    try:
        data = path.read_bytes()
    except OSError:
        raise DraftFlowError(
            "draft_input_missing",
            f"초안 입력 파일을 읽을 수 없습니다: {path}",
        )
    if b"\x00" in data:
        raise DraftFlowError(
            "draft_input_invalid",
            f"초안 입력 파일이 바이너리 파일입니다: {path}",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise DraftFlowError(
            "draft_input_invalid",
            f"초안 입력 파일이 비UTF-8 인코딩입니다: {path}",
        )
    if not text.strip():
        raise DraftFlowError(
            "draft_input_invalid",
            f"초안 입력 파일이 비어 있습니다: {path}",
        )
    return text


def _build_draft_prompt(
    repository: str, input_path: str, doc_type: str, content: str
) -> str:
    sections = [
        f"# 문서 초안 요청\n\n저장소: {repository}\n문서 유형: {doc_type}\n"
        f"입력 파일: {input_path}\n",
        (
            f"입력 파일에 담긴 거래 맥락을 바탕으로 {doc_type} 초안(\"DRAFT\")만 작성하세요. "
            "초안 생성 외에 어떤 외부 동작(발송 · 이메일 · 주문 접수 · 호출)도 수행하지 마세요. "
            f"{_ANTI_HALLUCINATION_RULE}"
        ),
        f"## 입력 파일 내용\n```\n{content}\n```\n",
        f"## {doc_type} 필수 섹션\n{_DOC_TYPE_SECTIONS[doc_type]}",
        (
            "출력 지시: 한국어로 구조화된 초안만 작성하세요. "
            "전체 초안은 800자 이내로 간결하게 작성하세요."
        ),
    ]
    return "\n\n".join(sections)


async def _execute_draft(
    repository: str,
    task: str,
    adapter: P01CoreOrchestrationAdapter,
    *,
    run_id: str | None,
) -> ClawOrchestrationOutcome:
    run = create_claw_run(repository, task, run_id=run_id)
    return await adapter.execute(run)


def run_draft(
    repository: Path,
    input_path: str,
    doc_type: str,
    adapter: P01CoreOrchestrationAdapter,
    *,
    run_id: str | None = None,
    out_path: Path | None = None,
) -> DraftOutcome:
    if not repository.exists() or not repository.is_dir():
        raise DraftFlowError(
            "draft_input_missing",
            "저장소 경로가 존재하지 않거나 디렉터리가 아닙니다.",
        )
    validated_type = _validate_doc_type(doc_type)
    root = repository.resolve()
    input_file = _resolve_draft_input(root, input_path)
    content = _read_draft_input(input_file)
    rel_input = input_file.relative_to(root).as_posix()
    prompt = _build_draft_prompt(str(root), rel_input, validated_type, content)
    outcome = asyncio.run(_execute_draft(str(root), prompt, adapter, run_id=run_id))
    result = DraftOutcome(
        projection=outcome.projection,
        answer=outcome.answer,
        p01_run_id=outcome.p01_run_id,
        p01_event_count=outcome.p01_event_count,
        repository=str(root),
        doc_type=validated_type,
        input_path=rel_input,
        out_path=out_path,
    )
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.report_text(), encoding="utf-8")
    return result


def run_draft_command(
    repository: Path,
    input_path: str,
    doc_type: str,
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
        outcome = run_draft(
            repository,
            input_path,
            doc_type,
            active,
            run_id=run_id,
            out_path=out_path,
        )
    except P01AdapterError as exc:
        print(
            f"KAGENT_DRAFT: {exc.code} · {redact_secrets(exc.safe_message)}",
            file=sys.stderr,
        )
        return 2
    print(
        f"DRAFT run={outcome.projection.run_id} "
        f"status={outcome.projection.status.value} "
        f"p01_run={outcome.p01_run_id} events={outcome.p01_event_count}"
    )
    print(outcome.report_text())
    return 0 if outcome.projection.status is ClawRunStatus.COMPLETED else 1


__all__ = [
    "DRAFT_DOC_TYPES",
    "MAX_DRAFT_INPUT_BYTES",
    "DraftFlowError",
    "DraftOutcome",
    "run_draft",
    "run_draft_command",
]
