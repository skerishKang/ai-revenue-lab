from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_context import ExecutionContext
from padiem_ai_core.execution_runtime import ExecutionResult
from padiem_ai_core.orchestration import OrchestrationResult
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)
from padiem_ai_engine_client import (
    EngineTransportResponse,
    PadiemAiEngineClient,
)

from kagent.cli import main, parser
from kagent.contracts import ClawRunStatus, ExecutionMode, RunProjection
from kagent.order_flow import (
    ORDER_DOC_TYPE,
    OrderFlowError,
    OrderOutcome,
    run_order,
    run_order_command,
)
from kagent.p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    ClawOrchestrationOutcome,
    P01AdapterError,
)
from kagent.p01_orchestration_client import PADIEM_EXECUTABLE_MODEL_IDS
from kagent.p01_run_flow import p01_adapter_from_environment

_FAKE_CREDENTIAL = "b54-order-credential-" + ("0" * 28)
_COMPLETED_RUN_ID = "order_run_001"
_ENGINE_BASE_URL = "https://padiem-ai-engine.internal"

_QUOTE_RUN_ID = "run_" + "9f8e7d6c5b4a392817060504"

_ANTI_HALLUCINATION_PHRASES = ("절대 추측해 생성하지", "입력 필요")

_QUOTE_REPORT = (
    "# 문서 초안 보고서\n"
    "\n"
    "- 저장소: /repo\n"
    "- 문서 유형: 견적서\n"
    "- 입력 파일: context.md\n"
    f"- P01 실행 2건: {_QUOTE_RUN_ID}_1(p01=quote_01) · "
    f"{_QUOTE_RUN_ID}_2(p01=quote_02) · 상태: completed\n"
    "\n"
    "## 견적서 초안 (DRAFT)\n"
    "\n"
    "거래처: ㈜한빛상사\n"
    "공급처: ㈜청운기계\n"
    "품목: 산업용 팬 3대, 제어기 1대\n"
    "납기: 다음 달 말\n"
    "특이조건: 설치 포함\n"
    "\n"
    "## 산출 근거 (플로우 계산)\n"
    "\n"
    "| 품명 | 수량 | 단가 | 금액 |\n"
    "|---|---|---|---|\n"
    "| 산업용 팬 | 3 | 500000 | 1500000 |\n"
    "| 제어기 | 1 | 200000 | 200000 |\n"
    "| 합계 | | | 1700000 |\n"
)

_QUOTE_ANSWER = "발주서 초안 완료: 승인된 견적 산출표를 그대로 사용했습니다."


class StubAdapter:
    """Duck-typed adapter surface for validation-only order tests.

    ``answers`` are consumed one per request in order; ``answer`` is the
    fallback for any remaining request.
    """

    def __init__(
        self, answer: str = _QUOTE_ANSWER, answers: list[str] | None = None
    ) -> None:
        self.answer = answer
        self.answers = list(answers or [])
        self.runs = []

    async def execute(self, run):
        self.runs.append(run)
        run.transition(ClawRunStatus.PREPARING, summary="발주 초안 실행 준비")
        run.transition(ClawRunStatus.RUNNING, summary="발주 초안 실행")
        run.transition(ClawRunStatus.COMPLETED, summary="발주 초안 완료")
        reply = self.answers.pop(0) if self.answers else self.answer
        return ClawOrchestrationOutcome(
            projection=RunProjection(
                run_id=run.run_id,
                task_id=run.intent.task_id,
                status=ClawRunStatus.COMPLETED,
                execution_mode=ExecutionMode.LOCAL,
            ),
            answer=reply,
            p01_run_id=_COMPLETED_RUN_ID,
            p01_event_count=3,
        )


class CorrelatedTransport:
    """Network-free transport answering with a public result correlated to the
    outgoing request, so the real adapter's correlation checks pass."""

    def __init__(self, answer: str = _QUOTE_ANSWER) -> None:
        self.answer = answer
        self.requests: list[dict] = []

    async def request(self, *, method, url, headers, body):
        self.requests.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body}
        )
        payload = json.loads(body.decode("utf-8"))
        trace_id = payload["trace_id"]
        session_id = payload["session_id"]
        app_id = payload["app_id"]
        events = tuple(
            public_orchestration_event(
                event_id=f"evt_{sequence:03d}",
                run_id=_COMPLETED_RUN_ID,
                trace_id=trace_id,
                app_id=app_id,
                kind=kind,
                sequence=sequence,
                message=None,
                timestamp_iso="2026-09-06T05:00:00+00:00",
            )
            for sequence, kind in enumerate(
                (
                    OrchestrationEventKind.RUN_STARTED,
                    OrchestrationEventKind.CONTEXT_PREPARED,
                    OrchestrationEventKind.RUN_COMPLETED,
                ),
                start=1,
            )
        )
        result = OrchestrationResult(
            execution_result=ExecutionResult(
                answer=self.answer,
                route=B14RouteMetadata(),
                metadata=RunMetadata(
                    trace_id=trace_id,
                    app_id=app_id,
                    agent_id=P01_AGENT_ID,
                    session_id=session_id,
                    status=RunStatus.COMPLETED,
                ),
            ),
            context=ExecutionContext(trace_id=trace_id),
            app_id=app_id,
            subject_id=None,
            plan=None,
            activated_skill=None,
            resolved_tool_ids=(),
            evidence_graph=None,
            claim_assessments=(),
            grounded_citations=(),
            events=events,
        )
        public = result.to_public_dict()
        wrapped = json.dumps({"ok": True, "orchestration": public}, ensure_ascii=False)
        return EngineTransportResponse(status=200, body=wrapped.encode("utf-8"))


def _write(repo: Path, name: str, content: bytes | str) -> Path:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
    with open(path, mode, **kwargs) as handle:
        handle.write(content)
    return path


class OrderFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.quote_file = _write(self.repo, "quote.md", _QUOTE_REPORT)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_happy_path_single_request_exact_figures_and_evidence(self) -> None:
        adapter = StubAdapter()
        outcome = run_order(self.repo, "quote.md", adapter, accept=True)

        self.assertIsInstance(outcome, OrderOutcome)
        self.assertEqual(outcome.quote_path, "quote.md")
        self.assertEqual(outcome.quote_run_id, _QUOTE_RUN_ID)
        self.assertEqual(outcome.p01_run_id, _COMPLETED_RUN_ID)
        self.assertEqual(outcome.p01_event_count, 3)
        self.assertEqual(outcome.projection.status, ClawRunStatus.COMPLETED)
        self.assertEqual(len(adapter.runs), 1)
        self.assertEqual(
            outcome.items,
            (
                ("산업용 팬", "3", "500000", "1500000"),
                ("제어기", "1", "200000", "200000"),
            ),
        )
        self.assertEqual(outcome.total, "1700000")
        self.assertTrue(outcome.accepted_at.endswith("+00:00"))

        prompt = adapter.runs[0].intent.task
        self.assertIn("발주서/판매오더", prompt)
        self.assertIn("DRAFT", prompt)
        self.assertIn("1500000", prompt)
        self.assertIn("1700000", prompt)
        self.assertIn("승인 근거", prompt)
        self.assertIn(_QUOTE_RUN_ID, prompt)
        self.assertIn("한빛상사", prompt)
        self.assertIn("청운기계", prompt)
        for section in ("거래처", "공급처", "품목 · 수량 · 단가 · 금액", "납기", "특이조건"):
            self.assertIn(section, prompt)
        for phrase in _ANTI_HALLUCINATION_PHRASES:
            self.assertIn(phrase, prompt)
        self.assertNotIn(_FAKE_CREDENTIAL, prompt)

    def test_quote_table_injected_verbatim_into_prompt(self) -> None:
        adapter = StubAdapter()
        run_order(self.repo, "quote.md", adapter, accept=True)

        prompt = adapter.runs[0].intent.task
        self.assertIn("| 품명 | 수량 | 단가 | 금액 |", prompt)
        self.assertIn("| 산업용 팬 | 3 | 500000 | 1500000 |", prompt)
        self.assertIn("| 제어기 | 1 | 200000 | 200000 |", prompt)
        self.assertIn("| 합계 | | | 1700000 |", prompt)

    def test_no_accept_fails_closed_order_not_accepted(self) -> None:
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "quote.md", StubAdapter(), accept=False)
        self.assertEqual(ctx.exception.code, "order_not_accepted")

    def test_no_accept_command_exit_2(self) -> None:
        code = run_order_command(self.repo, "quote.md", adapter=StubAdapter())
        self.assertEqual(code, 2)

    def test_total_mismatch_fails_closed(self) -> None:
        edited = _QUOTE_REPORT.replace("| 합계 | | | 1700000 |", "| 합계 | | | 1700001 |")
        _write(self.repo, "edited-total.md", edited)
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "edited-total.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_total_mismatch")

    def test_row_amount_mismatch_fails_closed(self) -> None:
        edited = _QUOTE_REPORT.replace(
            "| 산업용 팬 | 3 | 500000 | 1500000 |", "| 산업용 팬 | 3 | 500000 | 1500001 |"
        )
        _write(self.repo, "edited-row.md", edited)
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "edited-row.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_total_mismatch")

    def test_unsettled_row_fails_closed(self) -> None:
        edited = _QUOTE_REPORT.replace(
            "| 제어기 | 1 | 200000 | 200000 |", "| 제어기 | 1 | 입력 필요 | 입력 필요 |"
        )
        _write(self.repo, "unsettled.md", edited)
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "unsettled.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_total_mismatch")

    def test_quote_table_missing_section_fails_closed(self) -> None:
        no_section = _QUOTE_REPORT.replace(
            "## 산출 근거 (플로우 계산)\n", ""
        )
        _write(self.repo, "no-section.md", no_section)
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "no-section.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_quote_table_missing")

    def test_quote_table_missing_rows_fails_closed(self) -> None:
        no_rows = _QUOTE_REPORT.replace(
            "| 산업용 팬 | 3 | 500000 | 1500000 |\n"
            "| 제어기 | 1 | 200000 | 200000 |\n",
            "",
        )
        _write(self.repo, "no-rows.md", no_rows)
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "no-rows.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_quote_table_missing")

    def test_quote_table_missing_total_fails_closed(self) -> None:
        no_total = _QUOTE_REPORT.replace("| 합계 | | | 1700000 |\n", "")
        _write(self.repo, "no-total.md", no_total)
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "no-total.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_quote_table_missing")

    def test_missing_quote_raises_order_input_missing(self) -> None:
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "does-not-exist.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_input_missing")

    def test_directory_quote_raises_order_input_missing(self) -> None:
        _write(self.repo, "folder/.keep", "")
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "folder", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_input_missing")

    def test_outside_repo_quote_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside_tmp:
            outside = Path(outside_tmp) / "outside.md"
            outside.write_text(_QUOTE_REPORT, encoding="utf-8")
            with self.assertRaises(OrderFlowError) as ctx:
                run_order(self.repo, str(outside), StubAdapter(), accept=True)
            self.assertEqual(ctx.exception.code, "order_input_invalid")

    def test_oversized_quote_is_rejected(self) -> None:
        big = self.repo / "big.md"
        big.write_text("x" * (200 * 1024 + 1), encoding="utf-8")
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "big.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_input_too_large")

    def test_binary_quote_is_rejected(self) -> None:
        _write(self.repo, "logo.bin", b"\x00\x01\x02\x89PNG\r\n")
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "logo.bin", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_input_invalid")

    def test_empty_quote_is_rejected(self) -> None:
        _write(self.repo, "empty.md", "")
        with self.assertRaises(OrderFlowError) as ctx:
            run_order(self.repo, "empty.md", StubAdapter(), accept=True)
        self.assertEqual(ctx.exception.code, "order_input_invalid")

    def test_request_failure_fails_closed_exit_2(self) -> None:
        class RaisingAdapter(StubAdapter):
            async def execute(self, run):
                self.runs.append(run)
                raise P01AdapterError("p01_engine_request_failed", "엔진 요청 실패")

        code = run_order_command(
            self.repo,
            "quote.md",
            accept=True,
            adapter=RaisingAdapter(),
        )
        self.assertEqual(code, 2)

    def test_run_order_command_writes_markdown_out_path(self) -> None:
        out = self.repo / "out" / "order.md"
        code = run_order_command(
            self.repo,
            "quote.md",
            accept=True,
            adapter=StubAdapter(),
            out_path=out,
        )
        self.assertEqual(code, 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# 발주서/판매오더 초안 보고서 (ORDER)", text)
        self.assertIn(f"## {ORDER_DOC_TYPE} 초안 (DRAFT)", text)
        self.assertIn(_QUOTE_ANSWER, text)
        self.assertIn("## 산출 근거 (플로우 계산 — 재검증 완료)", text)
        self.assertIn("1500000", text)
        self.assertIn("1700000", text)
        self.assertIn(_QUOTE_RUN_ID, text)

    def test_run_order_command_prints_status_line_marker(self) -> None:
        sink = io.StringIO()
        with mock.patch("sys.stdout", sink):
            code = run_order_command(
                self.repo,
                "quote.md",
                accept=True,
                adapter=StubAdapter(),
            )
        self.assertEqual(code, 0)
        captured = sink.getvalue()
        self.assertIn("ORDER run=", captured)
        self.assertIn("status=completed", captured)
        self.assertIn("requests=1", captured)
        self.assertIn(f"p01_run={_COMPLETED_RUN_ID}", captured)
        self.assertIn("events=3", captured)
        self.assertIn("승인 근거: accept=true", captured)

    def test_run_order_command_without_engine_config_fails_closed(self) -> None:
        code = run_order_command(self.repo, "quote.md", accept=True, environ={})
        self.assertEqual(code, 2)

    def test_cli_subcommand_wires_order_flags(self) -> None:
        args = parser().parse_args(
            ["repo", "order", "quote.md", "--accept", "--out", "o.md"]
        )
        self.assertEqual(args.mode, "order")
        self.assertEqual(args.quote, "quote.md")
        self.assertTrue(args.accept)
        self.assertEqual(args.out, "o.md")

    def test_cli_order_defaults_accept_false(self) -> None:
        args = parser().parse_args(["repo", "order", "quote.md"])
        self.assertFalse(args.accept)

    def test_cli_main_without_accept_exits_2(self) -> None:
        code = main(
            [str(self.repo), "order", "quote.md"],
            adapter=StubAdapter(),
        )
        self.assertEqual(code, 2)

    def test_cli_main_runs_order_with_adapter(self) -> None:
        code = main(
            [str(self.repo), "order", "quote.md", "--accept"],
            adapter=StubAdapter(),
        )
        self.assertEqual(code, 0)

    def test_end_to_end_through_real_adapter_and_fake_transport(self) -> None:
        transport = CorrelatedTransport()
        adapter = p01_adapter_from_environment(
            {
                "P01_ENGINE_BASE_URL": _ENGINE_BASE_URL,
                "P01_ENGINE_CALLER_ID": "b54-order-e2e",
                "P01_ENGINE_CREDENTIAL": _FAKE_CREDENTIAL,
            },
            transport=transport,
        )
        out = self.repo / "e2e.md"
        code = run_order_command(
            self.repo,
            "quote.md",
            accept=True,
            adapter=adapter,
            out_path=out,
        )
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())
        self.assertIn(_QUOTE_ANSWER, out.read_text(encoding="utf-8"))
        self.assertEqual(len(transport.requests), 1)
        sent = transport.requests[0]
        self.assertEqual(sent["url"], f"{_ENGINE_BASE_URL}/internal/v1/orchestrate")
        payload = json.loads(sent["body"].decode("utf-8"))
        self.assertIn(
            payload["agent"]["model_policy"]["model"],
            PADIEM_EXECUTABLE_MODEL_IDS,
        )
        self.assertNotIn("provider", json.dumps(payload).lower())
        self.assertNotIn("credential", payload["agent"])
        self.assertNotIn(_FAKE_CREDENTIAL, sent["body"].decode("utf-8"))
        self.assertEqual(
            sent["headers"]["X-Padiem-Engine-Credential"], _FAKE_CREDENTIAL
        )
        content = json.loads(sent["body"].decode("utf-8"))["messages"][0]["content"]
        self.assertIn("발주서/판매오더", content)
        self.assertIn("1700000", content)
        self.assertIn(_QUOTE_RUN_ID, content)
        for phrase in _ANTI_HALLUCINATION_PHRASES:
            self.assertIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
