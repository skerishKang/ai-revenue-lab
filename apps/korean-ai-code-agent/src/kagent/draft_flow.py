"""#1985/#1994: Claw document draft flow — two-phase with deterministic flow math.

Claw's first business use case (#1878 A): a draft-document flow. Input is a
text/markdown file containing the deal/order context; output is a structured
draft document (견적서 또는 발주서 초안) via P01/B14, never sent anywhere.

#1994: the Kilo Gateway free window (~10s) truncates long single-request
generations, and a business document's 금액/합계 must never be guessed by the
model. The flow is therefore TWO phases:

1. Phase 1 request: extract the deal context (거래처·품목·수량·단가·조건) as
   short structured fields — an output that fits the free window.
2. The FLOW computes deterministic parts locally: 합계 = Σ(수량×단가) from the
   extracted fields with exact integer arithmetic; 단가/수량 missing from the
   input stay "입력 필요" and are never invented.
3. Phase 2 request: with the flow-computed table injected verbatim, render the
   document body — a second window-sized request.

The anti-hallucination rule is kept in BOTH prompts; the DRAFT marking and the
no-send guard stay in both.

This module only consumes the existing P01 adapter surface
(``P01CoreOrchestrationAdapter`` / ``create_claw_run`` / pinned agent profile).
It adds no model/provider/credential authority: an unconfigured Engine fails
closed with the existing ``p01_engine_not_configured`` error. Input validation
is fail-closed with explicit draft error codes, following the review flow's
discipline (200 KB limit, UTF-8, path containment).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
import os
from pathlib import Path
import re
import sys
import uuid

from .contracts import ClawRunStatus, ExecutionMode, RunProjection
from .core import redact_secrets
from .p01_adapter import (
    ClawOrchestrationOutcome,
    P01AdapterError,
    P01CoreOrchestrationAdapter,
)
from .p01_run_flow import create_claw_run, p01_adapter_from_environment
from .review_flow import (
    FLOW_MAX_REQUEST_ATTEMPTS,
    FLOW_PACING_SECONDS,
    FLOW_RETRY_WAIT_SECONDS,
    _RETRYABLE_ENGINE_FAILURE_CODES,
    _force_utf8_stdio,
    _run_orchestration_request,
)

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

_NO_SEND_GUARD = (
    "초안 생성 외에 어떤 외부 동작(발송 · 이메일 · 주문 접수 · 호출)도 수행하지 마세요."
)

_NUMBER_RE = re.compile(r"(\d[\d,]*)")
_EXTRACTION_ITEM_RE = re.compile(r"^\s*-\s*품명\s*:\s*(.*)$")


class DraftFlowError(P01AdapterError):
    """Fail-closed document draft flow input or execution error."""


@dataclass(frozen=True, slots=True)
class DraftOutcome:
    projection: RunProjection
    answer: str | None
    p01_run_id: str | None
    p01_event_count: int
    p01_runs: tuple[tuple[str, str, int], ...]
    repository: str
    doc_type: str
    input_path: str
    items: tuple[tuple[str, str, str, str], ...]
    total: str
    out_path: Path | None = None

    def report_text(self) -> str:
        lines = ["# 문서 초안 보고서", ""]
        lines.append(f"- 저장소: {self.repository}")
        lines.append(f"- 문서 유형: {self.doc_type}")
        lines.append(f"- 입력 파일: {self.input_path}")
        runs_desc = ", ".join(
            f"{claw}(p01={p01 or '-'})" for claw, p01, _ in self.p01_runs
        )
        lines.append(
            f"- P01 실행 {len(self.p01_runs)}건: {runs_desc or '-'} · "
            f"상태: {self.projection.status.value}"
        )
        if self.out_path is not None:
            lines.append(f"- 초안 파일: {self.out_path} (기록됨)")
        lines.append("")
        lines.append(f"## {self.doc_type} 초안 (DRAFT)")
        lines.append("")
        lines.append(self.answer if self.answer else "(초안 결과 없음)")
        lines.append("")
        lines.append("## 산출 근거 (플로우 계산)")
        lines.append("")
        lines.append("| 품명 | 수량 | 단가 | 금액 |")
        lines.append("|---|---|---|---|")
        for name, quantity, unit_price, amount in self.items:
            lines.append(f"| {name} | {quantity} | {unit_price} | {amount} |")
        lines.append(f"| 합계 | | | {self.total} |")
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


def _build_extraction_prompt(
    repository: str, input_path: str, doc_type: str, content: str
) -> str:
    return "\n\n".join(
        [
            (
                f"# 거래 맥락 추출 요청\n\n저장소: {repository}\n문서 유형: {doc_type}\n"
                f"입력 파일: {input_path}"
            ),
            (
                f"입력 파일에 담긴 거래 맥락을 아래 형식으로 추출해 주세요. "
                f"{_NO_SEND_GUARD} {_ANTI_HALLUCINATION_RULE}"
            ),
            f"## 입력 파일 내용\n```\n{content}\n```\n",
            (
                "## 추출 형식 (반드시 아래 라인 형식만 출력하세요)\n"
                "거래처: <값 또는 \"입력 필요\">\n"
                "공급자: <값 또는 \"입력 필요\">\n"
                "품목:\n"
                "- 품명: <이름> | 수량: <숫자 또는 \"입력 필요\"> | 단가: <숫자 또는 \"입력 필요\">\n"
                "(품목마다 위 라인을 한 줄씩 반복)\n"
                "조건:\n"
                "- 납기: <값 또는 \"입력 필요\">\n"
                "- 지불조건: <값 또는 \"입력 필요\">\n"
            ),
            (
                "출력 지시: 한국어로 추출 결과만 300자 이내로 간결하게 출력하세요. "
                "입력에 없는 수량·단가는 추측하지 말고 \"입력 필요\"로 표기하세요."
            ),
        ]
    )


def _build_render_prompt(
    repository: str,
    input_path: str,
    doc_type: str,
    fields: dict[str, object],
    items: list[tuple[str, str, str, str]],
    total: str,
) -> str:
    conditions = fields.get("조건") or {}
    table = ["| 품명 | 수량 | 단가 | 금액 |", "|---|---|---|---|"]
    for name, quantity, unit_price, amount in items:
        table.append(f"| {name} | {quantity} | {unit_price} | {amount} |")
    table.append(f"| 합계 | | | {total} |")
    return "\n\n".join(
        [
            (
                f"# 문서 초안 요청\n\n저장소: {repository}\n문서 유형: {doc_type}\n"
                f"입력 파일: {input_path}"
            ),
            (
                f"입력 파일에 담긴 거래 맥락과 아래 확정된 산출표를 바탕으로 "
                f"{doc_type} 초안(\"DRAFT\")만 작성하세요. "
                f"{_NO_SEND_GUARD} {_ANTI_HALLUCINATION_RULE}"
            ),
            (
                "## 추출된 거래 맥락\n"
                f"거래처: {fields.get('거래처') or '입력 필요'}\n"
                f"공급자: {fields.get('공급자') or '입력 필요'}\n"
                f"납기: {conditions.get('납기') or '입력 필요'}\n"
                f"지불조건: {conditions.get('지불조건') or '입력 필요'}"
            ),
            (
                "## 확정된 산출표 (플로우 계산 — 값을 변경하거나 다시 계산하지 마세요)\n"
                + "\n".join(table)
            ),
            f"## {doc_type} 필수 섹션\n{_DOC_TYPE_SECTIONS[doc_type]}",
            (
                "출력 지시: 한국어로 구조화된 초안만 작성하세요. "
                "산출표의 금액·합계를 그대로 사용하고 다시 계산하지 마세요. "
                "전체 초안은 500자 이내로 간결하게 작성하세요."
            ),
        ]
    )


def _parse_amount(value: str | None) -> int | None:
    match = _NUMBER_RE.search(value or "")
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _split_item_fields(line: str) -> dict[str, str]:
    body = _EXTRACTION_ITEM_RE.match(line).group(1).strip()
    name, _, rest = body.partition("|")
    values = {"품명": name.strip() or "입력 필요"}
    for part in rest.split("|"):
        part = part.strip()
        if ":" in part:
            key, _, value = part.partition(":")
            values[key.strip()] = value.strip()
    return {
        "품명": values.get("품명") or "입력 필요",
        "수량": values.get("수량") or "입력 필요",
        "단가": values.get("단가") or "입력 필요",
    }


def _parse_extraction(answer: str) -> dict[str, object]:
    """Parse the phase-1 structured extraction output.

    Fail-closed: if no 품목 line is found the output is not usable and the
    flow cannot compute a deterministic table.
    """
    fields: dict[str, object] = {"거래처": "", "공급자": "", "조건": {}, "품목": []}
    items: list[dict[str, str]] = []
    conditions: dict[str, str] = {}
    for raw_line in (answer or "").splitlines():
        line = raw_line.strip()
        if line.startswith("거래처:"):
            fields["거래처"] = line[len("거래처:") :].strip()
        elif line.startswith("공급자:"):
            fields["공급자"] = line[len("공급자:") :].strip()
        elif _EXTRACTION_ITEM_RE.match(line):
            items.append(_split_item_fields(line))
        elif line.startswith("- 납기:"):
            conditions["납기"] = line[len("- 납기:") :].strip()
        elif line.startswith("- 지불조건:"):
            conditions["지불조건"] = line[len("- 지불조건:") :].strip()
    if not items:
        raise DraftFlowError(
            "draft_extraction_invalid",
            "거래 맥락에서 품목 정보를 추출할 수 없습니다.",
        )
    fields["조건"] = conditions
    fields["품목"] = items
    return fields


def _compute_draft_table(
    items: list[dict[str, str]],
) -> tuple[list[tuple[str, str, str, str]], str]:
    """Deterministic table: 금액 = 수량×단가, 합계 = Σ금액 — computed by the flow."""
    rows: list[tuple[str, str, str, str]] = []
    known_total = 0
    missing = False
    for item in items:
        name = item.get("품명") or "입력 필요"
        quantity_raw = item.get("수량") or "입력 필요"
        unit_price_raw = item.get("단가") or "입력 필요"
        quantity = _parse_amount(quantity_raw)
        unit_price = _parse_amount(unit_price_raw)
        if quantity is None or unit_price is None:
            missing = True
            amount = "입력 필요"
        else:
            amount = str(quantity * unit_price)
            known_total += quantity * unit_price
        rows.append(
            (
                name,
                str(quantity) if quantity is not None else "입력 필요",
                str(unit_price) if unit_price is not None else "입력 필요",
                amount,
            )
        )
    total = "입력 필요 (수량·단가 누락 항목 있음)" if missing else str(known_total)
    return rows, total


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

    flow_run_id = (
        run_id
        if isinstance(run_id, str) and run_id.startswith("run_")
        else f"run_{uuid.uuid4().hex[:24]}"
    )

    phase1_prompt = _build_extraction_prompt(str(root), rel_input, validated_type, content)
    phase1 = _run_orchestration_request(
        partial(_execute_draft, str(root), phase1_prompt, adapter),
        run_id=f"{flow_run_id}_1",
        pacing_seconds=None,
        retryable_codes=_RETRYABLE_ENGINE_FAILURE_CODES,
        retry_wait_seconds=FLOW_RETRY_WAIT_SECONDS,
        max_attempts=FLOW_MAX_REQUEST_ATTEMPTS,
    )
    if (
        phase1.projection.status is not ClawRunStatus.COMPLETED
        or not phase1.answer
    ):
        raise DraftFlowError(
            "draft_extraction_failed",
            "거래 맥락 추출 요청이 완료되지 않았습니다.",
        )
    fields = _parse_extraction(phase1.answer)
    items, total = _compute_draft_table(fields["품목"])

    phase2_prompt = _build_render_prompt(
        str(root), rel_input, validated_type, fields, items, total
    )
    phase2 = _run_orchestration_request(
        partial(_execute_draft, str(root), phase2_prompt, adapter),
        run_id=f"{flow_run_id}_2",
        pacing_seconds=FLOW_PACING_SECONDS,
        retryable_codes=_RETRYABLE_ENGINE_FAILURE_CODES,
        retry_wait_seconds=FLOW_RETRY_WAIT_SECONDS,
        max_attempts=FLOW_MAX_REQUEST_ATTEMPTS,
    )
    if phase2.projection.status is not ClawRunStatus.COMPLETED or not phase2.answer:
        raise DraftFlowError(
            "draft_render_failed",
            "초안 렌더링 요청이 완료되지 않았습니다.",
        )

    p01_runs = (
        (phase1.projection.run_id, phase1.p01_run_id, phase1.p01_event_count),
        (phase2.projection.run_id, phase2.p01_run_id, phase2.p01_event_count),
    )
    suffix = flow_run_id[4:] if flow_run_id.startswith("run_") else flow_run_id
    projection = RunProjection(
        run_id=flow_run_id,
        task_id=f"task_{suffix}",
        status=ClawRunStatus.COMPLETED,
        execution_mode=ExecutionMode.LOCAL,
    )
    result = DraftOutcome(
        projection=projection,
        answer=phase2.answer,
        p01_run_id=p01_runs[0][1],
        p01_event_count=sum(count for _, _, count in p01_runs),
        p01_runs=p01_runs,
        repository=str(root),
        doc_type=validated_type,
        input_path=rel_input,
        items=tuple(items),
        total=total,
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
        f"requests={len(outcome.p01_runs)} "
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
