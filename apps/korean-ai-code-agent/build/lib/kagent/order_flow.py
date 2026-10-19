"""#2004: Claw quote-to-order flow — one approved request, local revalidation.

Turns an APPROVED 견적서 draft (the markdown report produced by the draft flow)
into a 발주서/판매오더 초안 via P01/B14. The quote is the authority: the flow
parses the deterministic "산출 근거 (플로우 계산)" table, re-validates the math
itself (금액 = 수량×단가, 합계 = Σ금액) to detect hand-edits, and never lets
the model invent or recompute amounts.

Fail-closed gates, in order:

1. Parse the 산출표 from the quote file; no table/헤더/품목/합계 →
   ``order_quote_table_missing``.
2. Acceptance gate (#1528 core rule): without an explicit ``--accept`` the
   flow refuses to create an order → ``order_not_accepted``.
3. Math revalidation: every 품목 row must be fully numeric with 금액 ==
   수량×단가, and 합계 must equal Σ금액; any hand-edit or unsettled
   ("입력 필요") row → ``order_total_mismatch``.

Only then is ONE orchestration request issued: the verified table is injected
VERBATIM together with the quote's own draft text and the acceptance evidence
(timestamp + exact figures). The model renders the 발주서/판매오더 초안
("DRAFT") with absent fields as "입력 필요" (anti-hallucination) and no send —
mirroring the draft flow's two-phase discipline while keeping this flow to a
single request.

This module only consumes the existing P01 adapter surface
(``P01CoreOrchestrationAdapter`` / ``create_claw_run`` / pinned agent profile).
It adds no model/provider/credential authority: an unconfigured Engine fails
closed with the existing ``p01_engine_not_configured`` error. Input validation
is fail-closed with explicit order error codes, following the review/draft
flow discipline (200 KB limit, UTF-8, path containment).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import sys
import uuid

from .contracts import ClawRunStatus, ExecutionMode, RunProjection
from .core import redact_secrets
from .document_export import export_outcome_to_file
from .p01_adapter import (
    ClawOrchestrationOutcome,
    P01AdapterError,
    P01CoreOrchestrationAdapter,
)
from .p01_run_flow import create_claw_run, p01_adapter_from_environment
from .review_flow import _force_utf8_stdio

MAX_ORDER_INPUT_BYTES = 200 * 1024

ORDER_DOC_TYPE = "발주서/판매오더"

_QUOTE_SECTION_HEADER = "산출 근거 (플로우 계산)"
_QUOTE_DRAFT_SECTION = "견적서 초안 (DRAFT)"
_QUOTE_HEADER_CELLS = ("품명", "수량", "단가", "금액")
_ORDER_SECTIONS = (
    "- 거래처 (구매처)\n"
    "- 공급처\n"
    "- 품목 · 수량 · 단가 · 금액 (확정 산출표 그대로 — 재계산 금지)\n"
    "- 납기\n"
    "- 특이조건"
)

_ANTI_HALLUCINATION_RULE = (
    "입력에 없는 정보(금액 · 일정 · 회사명 등)는 절대 추측해 생성하지 말고 "
    "해당 항목을 \"입력 필요\"로 표기하세요."
)

_NO_SEND_GUARD = (
    "초안 생성 외에 어떤 외부 동작(발송 · 이메일 · 주문 접수 · 호출)도 수행하지 마세요."
)

_NUMBER_RE = re.compile(r"(\d[\d,]*)")
_RUN_ID_RE = re.compile(r"run_[0-9a-fA-F]{24}")
_SEPARATOR_CELL_RE = re.compile(r":?-+:?")


class OrderFlowError(P01AdapterError):
    """Fail-closed quote-to-order flow input, gate, or execution error."""


@dataclass(frozen=True, slots=True)
class OrderOutcome:
    projection: RunProjection
    answer: str | None
    p01_run_id: str | None
    p01_event_count: int
    p01_runs: tuple[tuple[str, str, int], ...]
    repository: str
    quote_path: str
    quote_run_id: str | None
    accepted_at: str
    items: tuple[tuple[str, str, str, str], ...]
    total: str
    out_path: Path | None = None

    def report_text(self) -> str:
        lines = ["# 발주서/판매오더 초안 보고서 (ORDER)", ""]
        lines.append(f"- 저장소: {self.repository}")
        lines.append(f"- 견적 파일: {self.quote_path}")
        lines.append(f"- 견적 실행: {self.quote_run_id or '-'}")
        lines.append(
            f"- 승인 근거: accept=true · {self.accepted_at} · "
            f"합계 {self.total}원 (플로우 재검증 완료)"
        )
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
        lines.append(f"## {ORDER_DOC_TYPE} 초안 (DRAFT)")
        lines.append("")
        lines.append(self.answer if self.answer else "(초안 결과 없음)")
        lines.append("")
        lines.append("## 산출 근거 (플로우 계산 — 재검증 완료)")
        lines.append("")
        lines.append("| 품명 | 수량 | 단가 | 금액 |")
        lines.append("|---|---|---|---|")
        for name, quantity, unit_price, amount in self.items:
            lines.append(f"| {name} | {quantity} | {unit_price} | {amount} |")
        lines.append(f"| 합계 | | | {self.total} |")
        return "\n".join(lines)


def _resolve_quote_input(root: Path, quote_path: str) -> Path:
    if not isinstance(quote_path, str) or not quote_path.strip():
        raise OrderFlowError(
            "order_input_missing",
            "견적서 파일 경로가 제공되지 않았습니다.",
        )
    raw = Path(quote_path)
    candidate = raw if raw.is_absolute() else root / raw
    if not candidate.exists():
        raise OrderFlowError(
            "order_input_missing",
            f"견적서 파일이 존재하지 않습니다: {quote_path}",
        )
    try:
        current = candidate.resolve()
    except OSError:
        raise OrderFlowError(
            "order_input_invalid",
            f"견적서 파일 경로를 확인할 수 없습니다: {quote_path}",
        )
    if not current.is_relative_to(root):
        raise OrderFlowError(
            "order_input_invalid",
            f"견적서 파일이 저장소 밖입니다: {quote_path}",
        )
    if not current.is_file():
        raise OrderFlowError(
            "order_input_missing",
            f"견적서가 파일이 아닙니다: {quote_path}",
        )
    return current


def _read_quote_input(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        raise OrderFlowError(
            "order_input_missing",
            f"견적서 파일을 확인할 수 없습니다: {path}",
        )
    if size > MAX_ORDER_INPUT_BYTES:
        raise OrderFlowError(
            "order_input_too_large",
            f"견적서 파일이 한도(200KB)를 초과합니다: {path}",
        )
    try:
        data = path.read_bytes()
    except OSError:
        raise OrderFlowError(
            "order_input_missing",
            f"견적서 파일을 읽을 수 없습니다: {path}",
        )
    if b"\x00" in data:
        raise OrderFlowError(
            "order_input_invalid",
            f"견적서 파일이 바이너리 파일입니다: {path}",
        )
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise OrderFlowError(
            "order_input_invalid",
            f"견적서 파일이 비UTF-8 인코딩입니다: {path}",
        )
    if not text.strip():
        raise OrderFlowError(
            "order_input_invalid",
            f"견적서 파일이 비어 있습니다: {path}",
        )
    return text


def _parse_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.split("|")[1:-1]]


def _is_separator_row(cells: list[str]) -> bool:
    """Markdown table alignment/separator rows like ``|---|---|`` are not data."""
    has_dash = False
    for cell in cells:
        if not cell:
            continue
        if not _SEPARATOR_CELL_RE.fullmatch(cell):
            return False
        has_dash = True
    return has_dash


def _parse_quote_table(
    text: str,
) -> tuple[list[tuple[str, str, str, str]], str]:
    """Deterministically parse the quote's "산출 근거" table.

    Returns (items, total). Fail-closed: no section, no 품명/수량/단가/금액
    header, no 품목 row, or no 합계 row is an ``order_quote_table_missing``.
    """
    lines = (text or "").splitlines()
    section_pos = None
    for index, raw in enumerate(lines):
        if _QUOTE_SECTION_HEADER in raw:
            section_pos = index
            break
    if section_pos is None:
        raise OrderFlowError(
            "order_quote_table_missing",
            "견적서에 '산출 근거 (플로우 계산)' 섹션이 없습니다.",
        )

    table_lines: list[str] = []
    for raw in lines[section_pos + 1 :]:
        stripped = raw.strip()
        if stripped.startswith("#"):
            break
        if stripped.startswith("|"):
            table_lines.append(stripped)

    header_pos = None
    for pos, line in enumerate(table_lines):
        cells = _parse_cells(line)
        if len(cells) >= 4 and all(name in cells for name in _QUOTE_HEADER_CELLS):
            header_pos = pos
            break
    if header_pos is None:
        raise OrderFlowError(
            "order_quote_table_missing",
            "견적서 산출표 헤더(품명 · 수량 · 단가 · 금액)를 찾을 수 없습니다.",
        )

    items: list[tuple[str, str, str, str]] = []
    total = ""
    for line in table_lines[header_pos + 1 :]:
        cells = _parse_cells(line)
        if len(cells) < 4 or _is_separator_row(cells):
            continue
        if cells[0] == "합계":
            total = cells[3]
            continue
        items.append((cells[0], cells[1], cells[2], cells[3]))
    if not items:
        raise OrderFlowError(
            "order_quote_table_missing",
            "견적서 산출표에 품목 행이 없습니다.",
        )
    if not total:
        raise OrderFlowError(
            "order_quote_table_missing",
            "견적서 산출표에 합계 행이 없습니다.",
        )
    normalized = tuple(
        (
            name or "입력 필요",
            quantity or "입력 필요",
            unit_price or "입력 필요",
            amount or "입력 필요",
        )
        for name, quantity, unit_price, amount in items
    )
    return normalized, total or "입력 필요"


def _parse_amount(value: str | None) -> int | None:
    match = _NUMBER_RE.search(value or "")
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _revalidate_table(
    items: list[tuple[str, str, str, str]], total: str
) -> str:
    """Recompute 금액 = 수량×단가 and 합계 = Σ금액 with exact integer math.

    Fail-closed: any unsettled row ("입력 필요") or a row/total that disagrees
    with the flow's own computation is a hand-edit signal →
    ``order_total_mismatch``.
    """
    flow_total = 0
    for name, quantity, unit_price, amount in items:
        quantity_value = _parse_amount(quantity)
        unit_price_value = _parse_amount(unit_price)
        amount_value = _parse_amount(amount)
        if quantity_value is None or unit_price_value is None or amount_value is None:
            raise OrderFlowError(
                "order_total_mismatch",
                f"산출표 품목 '{name}'에 확정되지 않은 수량·단가·금액이 있어 "
                "발주서/판매오더를 생성할 수 없습니다.",
            )
        expected = quantity_value * unit_price_value
        if amount_value != expected:
            raise OrderFlowError(
                "order_total_mismatch",
                f"산출표 품목 '{name}'의 금액이 수량×단가({expected})와 "
                f"일치하지 않습니다: {amount}",
            )
        flow_total += amount_value
    total_value = _parse_amount(total)
    if total_value is None:
        raise OrderFlowError(
            "order_total_mismatch",
            "산출표 합계 금액을 확인할 수 없습니다.",
        )
    if total_value != flow_total:
        raise OrderFlowError(
            "order_total_mismatch",
            f"산출표 합계({total})가 품목 금액 합계({flow_total})와 일치하지 않습니다.",
        )
    return str(flow_total)


def _extract_quote_run_id(text: str) -> str | None:
    for raw in (text or "").splitlines():
        if raw.startswith("- P01 실행"):
            match = _RUN_ID_RE.search(raw)
            if match:
                return match.group(0)
    return None


def _extract_quote_draft(text: str) -> str:
    lines = (text or "").splitlines()
    start = None
    for index, raw in enumerate(lines):
        if _QUOTE_DRAFT_SECTION in raw:
            start = index + 1
            break
    if start is None:
        return ""
    parts: list[str] = []
    for raw in lines[start:]:
        if raw.strip().startswith("## "):
            break
        parts.append(raw)
    return "\n".join(parts).strip()


def _build_order_prompt(
    repository: str,
    quote_path: str,
    quote_run_id: str | None,
    accepted_at: str,
    items: list[tuple[str, str, str, str]],
    total: str,
    quote_draft: str,
) -> str:
    table = ["| 품명 | 수량 | 단가 | 금액 |", "|---|---|---|---|"]
    for name, quantity, unit_price, amount in items:
        table.append(f"| {name} | {quantity} | {unit_price} | {amount} |")
    table.append(f"| 합계 | | | {total} |")
    sections = [
        (
            f"# 발주서/판매오더 초안 요청\n\n저장소: {repository}\n"
            f"견적 파일: {quote_path}\n견적 실행: {quote_run_id or '알 수 없음'}\n"
            f"승인 근거: {accepted_at} · 산출표 합계 {total}원 (플로우 재검증 완료)"
        ),
        (
            f"승인된 견적서의 확정 산출표와 초안 내용을 바탕으로 "
            f"{ORDER_DOC_TYPE} 초안(\"DRAFT\")만 작성하세요. "
            f"{_NO_SEND_GUARD} {_ANTI_HALLUCINATION_RULE}"
        ),
        (
            "## 확정된 견적 산출표 (승인됨 — 값을 변경하거나 다시 계산하지 마세요)\n"
            + "\n".join(table)
        ),
    ]
    if quote_draft:
        sections.append(
            "## 견적서 초안 내용 (근거)\n" + quote_draft
        )
    sections.append(
        f"## {ORDER_DOC_TYPE} 필수 섹션\n{_ORDER_SECTIONS}"
    )
    sections.append(
        "출력 지시: 한국어로 구조화된 초안만 작성하세요. "
        "산출표의 금액·합계를 그대로 사용하고 다시 계산하지 마세요. "
        "전체 초안은 500자 이내로 간결하게 작성하세요."
    )
    return "\n\n".join(sections)


async def _execute_order(
    repository: str,
    task: str,
    adapter: P01CoreOrchestrationAdapter,
    *,
    run_id: str | None,
) -> ClawOrchestrationOutcome:
    run = create_claw_run(repository, task, run_id=run_id)
    return await adapter.execute(run)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_order(
    repository: Path,
    quote_path: str,
    adapter: P01CoreOrchestrationAdapter,
    *,
    accept: bool = False,
    run_id: str | None = None,
    out_path: Path | None = None,
    doc_format: str = "md",
) -> OrderOutcome:
    if not repository.exists() or not repository.is_dir():
        raise OrderFlowError(
            "order_input_missing",
            "저장소 경로가 존재하지 않거나 디렉터리가 아닙니다.",
        )
    root = repository.resolve()
    quote_file = _resolve_quote_input(root, quote_path)
    text = _read_quote_input(quote_file)
    rel_quote = quote_file.relative_to(root).as_posix()

    items, total = _parse_quote_table(text)
    if not accept:
        raise OrderFlowError(
            "order_not_accepted",
            "견적서 승인(--accept)이 선언되지 않아 발주서/판매오더를 생성할 수 없습니다.",
        )
    verified_total = _revalidate_table(items, total)

    flow_run_id = (
        run_id
        if isinstance(run_id, str) and run_id.startswith("run_")
        else f"run_{uuid.uuid4().hex[:24]}"
    )
    quote_run_id = _extract_quote_run_id(text)
    accepted_at = _utc_now_iso()
    prompt = _build_order_prompt(
        str(root),
        rel_quote,
        quote_run_id,
        accepted_at,
        items,
        verified_total,
        _extract_quote_draft(text),
    )
    outcome = asyncio.run(
        _execute_order(str(root), prompt, adapter, run_id=f"{flow_run_id}_1")
    )
    if (
        outcome.projection.status is not ClawRunStatus.COMPLETED
        or not outcome.answer
    ):
        raise OrderFlowError(
            "order_render_failed",
            "발주서/판매오더 렌더링 요청이 완료되지 않았습니다.",
        )

    p01_runs = (
        (outcome.projection.run_id, outcome.p01_run_id, outcome.p01_event_count),
    )
    suffix = flow_run_id[4:] if flow_run_id.startswith("run_") else flow_run_id
    projection = RunProjection(
        run_id=flow_run_id,
        task_id=f"task_{suffix}",
        status=ClawRunStatus.COMPLETED,
        execution_mode=ExecutionMode.LOCAL,
    )
    result = OrderOutcome(
        projection=projection,
        answer=outcome.answer,
        p01_run_id=outcome.p01_run_id,
        p01_event_count=outcome.p01_event_count,
        p01_runs=p01_runs,
        repository=str(root),
        quote_path=rel_quote,
        quote_run_id=quote_run_id,
        accepted_at=accepted_at,
        items=tuple(items),
        total=verified_total,
        out_path=out_path,
    )
    if out_path is not None:
        metadata = [
            ("저장소", result.repository),
            ("견적 파일", result.quote_path),
            ("견적 실행", result.quote_run_id or "-"),
            ("승인 근거", f"accept=true · {result.accepted_at} · 합계 {result.total}원 (플로우 재검증 완료)"),
            ("P01 실행", f"{len(result.p01_runs)}건 · 상태: {result.projection.status.value}"),
        ]
        export_outcome_to_file(
            out_path=out_path,
            file_format=doc_format or "md",
            title="발주서/판매오더 초안 보고서 (ORDER)",
            metadata_fields=metadata,
            section_title=f"{ORDER_DOC_TYPE} 초안 (DRAFT)",
            body_text=result.answer if result.answer else "(초안 결과 없음)",
            items=result.items,
            total=result.total,
            markdown_fallback_text=result.report_text(),
        )
    return result


def run_order_command(
    repository: Path,
    quote_path: str,
    *,
    accept: bool = False,
    adapter: P01CoreOrchestrationAdapter | None = None,
    environ: Mapping[str, str] | None = None,
    run_id: str | None = None,
    out_path: Path | None = None,
    doc_format: str = "md",
) -> int:
    _force_utf8_stdio()
    try:
        active = (
            adapter if adapter is not None else p01_adapter_from_environment(environ)
        )
        outcome = run_order(
            repository,
            quote_path,
            active,
            accept=accept,
            run_id=run_id,
            out_path=out_path,
            doc_format=doc_format,
        )
    except P01AdapterError as exc:
        print(
            f"KAGENT_ORDER: {exc.code} · {redact_secrets(exc.safe_message)}",
            file=sys.stderr,
        )
        return 2
    print(
        f"ORDER run={outcome.projection.run_id} "
        f"status={outcome.projection.status.value} "
        f"requests={len(outcome.p01_runs)} "
        f"p01_run={outcome.p01_run_id} events={outcome.p01_event_count}"
    )
    print(outcome.report_text())
    return 0 if outcome.projection.status is ClawRunStatus.COMPLETED else 1


__all__ = [
    "MAX_ORDER_INPUT_BYTES",
    "ORDER_DOC_TYPE",
    "OrderFlowError",
    "OrderOutcome",
    "run_order",
    "run_order_command",
]
