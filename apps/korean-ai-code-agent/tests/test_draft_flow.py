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

from kagent import review_flow as review_flow_module
from kagent.cli import main, parser
from kagent.contracts import ClawRunStatus, ExecutionMode, RunProjection
from kagent.draft_flow import (
    DRAFT_DOC_TYPES,
    DraftFlowError,
    DraftOutcome,
    run_draft,
    run_draft_command,
)
from kagent.p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    ClawOrchestrationOutcome,
    P01AdapterError,
)
from kagent.p01_run_flow import p01_adapter_from_environment
from kagent.review_flow import (
    FLOW_PACING_SECONDS,
    FLOW_RETRY_WAIT_SECONDS,
    run_review_command,
)

_FAKE_CREDENTIAL = "b54-draft-credential-" + ("0" * 32)
_COMPLETED_RUN_ID = "draft_run_001"
_ENGINE_BASE_URL = "https://padiem-ai-engine.internal"

_QUOTE_CONTEXT = (
    "# 거래 맥락\n"
    "거래처: ㈜한빛상사\n"
    "품목: 산업용 팬 3대, 제어기 1대\n"
    "납기: 다음 달 말\n"
)

_EXTRACTION_OUTPUT = (
    "거래처: ㈜한빛상사\n"
    "공급자: 입력 필요\n"
    "품목:\n"
    "- 품명: 산업용 팬 | 수량: 3 | 단가: 500000\n"
    "- 품명: 제어기 | 수량: 1 | 단가: 입력 필요\n"
    "조건:\n"
    "- 납기: 다음 달 말\n"
    "- 지불조건: 입력 필요\n"
)

_EXTRACTION_FULL_TOTALS = (
    "거래처: ㈜한빛상사\n"
    "공급자: ㈜청운기계\n"
    "품목:\n"
    "- 품명: 산업용 팬 | 수량: 3 | 단가: 500,000\n"
    "- 품명: 제어기 | 수량: 1 | 단가: 200000\n"
    "조건:\n"
    "- 납기: 다음 달 말\n"
    "- 지불조건: 발송 후 30일\n"
)

_ANTI_HALLUCINATION_PHRASES = ("절대 추측해 생성하지", "입력 필요")


class StubAdapter:
    """Duck-typed adapter surface for validation-only draft tests.

    ``answers`` are consumed one per phase request in order; ``answer`` is the
    fallback for any remaining phase.
    """

    def __init__(self, answer: str = "초안 완료", answers: list[str] | None = None) -> None:
        self.answer = answer
        self.answers = list(answers or [])
        self.runs = []

    async def execute(self, run):
        self.runs.append(run)
        run.transition(ClawRunStatus.PREPARING, summary="초안 실행 준비")
        run.transition(ClawRunStatus.RUNNING, summary="초안 실행")
        run.transition(ClawRunStatus.COMPLETED, summary="초안 완료")
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

    def __init__(self, answer: str = "견적서 초안 완료", answers: list[str] | None = None) -> None:
        self.answer = answer
        self.answers = list(answers or [])
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
        reply = self.answers.pop(0) if self.answers else self.answer
        result = OrchestrationResult(
            execution_result=ExecutionResult(
                answer=reply,
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


class DraftFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.input_file = _write(self.repo, "context.md", _QUOTE_CONTEXT)
        self.sleep_calls: list[float] = []
        sleeper = mock.patch.object(
            review_flow_module,
            "_sleep",
            side_effect=lambda seconds: self.sleep_calls.append(seconds),
        )
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_happy_path_two_phase_prompts_and_anti_hallucination(self) -> None:
        adapter = StubAdapter(answers=[_EXTRACTION_OUTPUT, "초안 완료"])
        outcome = run_draft(self.repo, "context.md", "견적서", adapter)

        self.assertIsInstance(outcome, DraftOutcome)
        self.assertEqual(outcome.doc_type, "견적서")
        self.assertEqual(outcome.input_path, "context.md")
        self.assertEqual(outcome.p01_run_id, _COMPLETED_RUN_ID)
        self.assertEqual(outcome.p01_event_count, 6)
        self.assertEqual(outcome.projection.status, ClawRunStatus.COMPLETED)
        self.assertEqual(len(adapter.runs), 2)
        self.assertEqual(self.sleep_calls, [FLOW_PACING_SECONDS])

        extraction = adapter.runs[0].intent.task
        self.assertIn("거래 맥락 추출", extraction)
        self.assertIn("한빛상사", extraction)
        self.assertIn("산업용 팬", extraction)
        for phrase in _ANTI_HALLUCINATION_PHRASES:
            self.assertIn(phrase, extraction)
        self.assertIn("발송", extraction)

        render = adapter.runs[1].intent.task
        self.assertIn("DRAFT", render)
        self.assertIn("산출표", render)
        self.assertIn("합계", render)
        for section in ("공급받는 자", "공급자", "품목 · 수량 · 단가", "조건"):
            self.assertIn(section, render)
        for phrase in _ANTI_HALLUCINATION_PHRASES:
            self.assertIn(phrase, render)

    def test_happy_path_order_document_sections_in_render_prompt(self) -> None:
        adapter = StubAdapter(answers=[_EXTRACTION_OUTPUT, "초안 완료"])
        outcome = run_draft(self.repo, "context.md", "발주서", adapter)

        self.assertEqual(outcome.doc_type, "발주서")
        render = adapter.runs[1].intent.task
        for section in ("발주자", "공급처", "품목 · 수량 · 납기", "특이조건"):
            self.assertIn(section, render)
        for phrase in _ANTI_HALLUCINATION_PHRASES:
            self.assertIn(phrase, render)

    def test_prompt_carries_input_context_and_no_hardcoded_values(self) -> None:
        adapter = StubAdapter(answers=[_EXTRACTION_OUTPUT, "초안 완료"])
        run_draft(self.repo, "context.md", "견적서", adapter)

        for run in adapter.runs:
            self.assertIn("한빛상사", run.intent.task)
            self.assertIn("산업용 팬", run.intent.task)
            self.assertNotIn(_FAKE_CREDENTIAL, run.intent.task)

    def test_flow_computes_deterministic_total_and_injects_table(self) -> None:
        adapter = StubAdapter(answers=[_EXTRACTION_FULL_TOTALS, "초안 완료"])
        outcome = run_draft(self.repo, "context.md", "견적서", adapter)

        self.assertEqual(outcome.total, "1700000")
        self.assertEqual(
            outcome.items,
            (
                ("산업용 팬", "3", "500000", "1500000"),
                ("제어기", "1", "200000", "200000"),
            ),
        )
        render = adapter.runs[1].intent.task
        self.assertIn("1500000", render)
        self.assertIn("1700000", render)
        report = outcome.report_text()
        self.assertIn("1500000", report)
        self.assertIn("1700000", report)

    def test_input_needed_propagates_into_computed_table(self) -> None:
        adapter = StubAdapter(answers=[_EXTRACTION_OUTPUT, "초안 완료"])
        outcome = run_draft(self.repo, "context.md", "견적서", adapter)

        self.assertEqual(
            outcome.items,
            (
                ("산업용 팬", "3", "500000", "1500000"),
                ("제어기", "1", "입력 필요", "입력 필요"),
            ),
        )
        self.assertTrue(outcome.total.startswith("입력 필요"))
        render = adapter.runs[1].intent.task
        self.assertIn("입력 필요", render)
        report = outcome.report_text()
        self.assertIn("입력 필요", report)
        self.assertIn("1500000", report)

    def test_unparseable_extraction_fails_closed(self) -> None:
        adapter = StubAdapter(answers=["형식 없는 텍스트만 있습니다.", "무관"])
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "context.md", "견적서", adapter)
        self.assertEqual(ctx.exception.code, "draft_extraction_invalid")

    def test_empty_phase1_answer_fails_closed(self) -> None:
        adapter = StubAdapter(answers=[""])
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "context.md", "견적서", adapter)
        self.assertEqual(ctx.exception.code, "draft_extraction_failed")

    def test_phase_request_failure_fails_closed(self) -> None:
        class RaisingAdapter(StubAdapter):
            async def execute(self, run):
                self.runs.append(run)
                raise P01AdapterError("p01_engine_request_failed", "엔진 요청 실패")

        code = run_draft_command(
            self.repo,
            "context.md",
            "견적서",
            adapter=RaisingAdapter(),
        )
        self.assertEqual(code, 2)

    def test_retryable_phase_failure_retries_once_after_wait(self) -> None:
        class RetryThenSucceedAdapter(StubAdapter):
            def __init__(self, answers=None):
                super().__init__(answers=answers)
                self.attempts = 0

            async def execute(self, run):
                self.attempts += 1
                if self.attempts == 1:
                    raise P01AdapterError(
                        "p01_engine_request_failed", "엔진 요청 실패"
                    )
                return await super().execute(run)

        adapter = RetryThenSucceedAdapter(
            answers=[_EXTRACTION_OUTPUT, "초안 완료"]
        )
        outcome = run_draft(self.repo, "context.md", "견적서", adapter)

        self.assertEqual(adapter.attempts, 3)
        self.assertEqual(len(adapter.runs), 2)
        self.assertEqual(outcome.projection.status, ClawRunStatus.COMPLETED)
        self.assertEqual(
            self.sleep_calls,
            [FLOW_RETRY_WAIT_SECONDS, FLOW_PACING_SECONDS],
        )

    def test_invalid_doc_type_raises_draft_type_invalid(self) -> None:
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "context.md", "세금계산서", StubAdapter())
        self.assertEqual(ctx.exception.code, "draft_type_invalid")

    def test_missing_input_raises_draft_input_missing(self) -> None:
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "does-not-exist.md", "견적서", StubAdapter())
        self.assertEqual(ctx.exception.code, "draft_input_missing")

    def test_directory_input_raises_draft_input_missing(self) -> None:
        _write(self.repo, "folder/.keep", "")
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "folder", "견적서", StubAdapter())
        self.assertEqual(ctx.exception.code, "draft_input_missing")

    def test_outside_repo_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside_tmp:
            outside = Path(outside_tmp) / "outside.md"
            outside.write_text("외부 파일", encoding="utf-8")
            with self.assertRaises(DraftFlowError) as ctx:
                run_draft(self.repo, str(outside), "견적서", StubAdapter())
            self.assertEqual(ctx.exception.code, "draft_input_invalid")

    def test_oversized_input_is_rejected(self) -> None:
        big = self.repo / "big.md"
        big.write_text("x" * (200 * 1024 + 1), encoding="utf-8")
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "big.md", "견적서", StubAdapter())
        self.assertEqual(ctx.exception.code, "draft_input_too_large")

    def test_binary_input_is_rejected(self) -> None:
        _write(self.repo, "logo.bin", b"\x00\x01\x02\x89PNG\r\n")
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "logo.bin", "견적서", StubAdapter())
        self.assertEqual(ctx.exception.code, "draft_input_invalid")

    def test_non_utf8_input_is_rejected(self) -> None:
        _write(self.repo, "euckr.txt", "한글".encode("euc-kr"))
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "euckr.txt", "견적서", StubAdapter())
        self.assertEqual(ctx.exception.code, "draft_input_invalid")

    def test_empty_input_is_rejected(self) -> None:
        _write(self.repo, "empty.md", "")
        with self.assertRaises(DraftFlowError) as ctx:
            run_draft(self.repo, "empty.md", "견적서", StubAdapter())
        self.assertEqual(ctx.exception.code, "draft_input_invalid")

    def test_run_draft_command_writes_markdown_out_path(self) -> None:
        out = self.repo / "out" / "quote.md"
        code = run_draft_command(
            self.repo,
            "context.md",
            "견적서",
            adapter=StubAdapter(answers=[_EXTRACTION_OUTPUT, "초안 완료"]),
            out_path=out,
        )
        self.assertEqual(code, 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# 문서 초안 보고서", text)
        self.assertIn("## 견적서 초안 (DRAFT)", text)
        self.assertIn("초안 완료", text)
        self.assertIn("## 산출 근거 (플로우 계산)", text)

    def test_run_draft_command_prints_status_line_marker_two_phases(self) -> None:
        sink = io.StringIO()
        with mock.patch("sys.stdout", sink):
            code = run_draft_command(
                self.repo,
                "context.md",
                "견적서",
                adapter=StubAdapter(answers=[_EXTRACTION_OUTPUT, "초안 완료"]),
            )
        self.assertEqual(code, 0)
        captured = sink.getvalue()
        self.assertIn("DRAFT run=", captured)
        self.assertIn("status=completed", captured)
        self.assertIn("requests=2", captured)
        self.assertIn(f"p01_run={_COMPLETED_RUN_ID}", captured)
        self.assertIn("events=6", captured)

    def test_review_command_status_line_parity(self) -> None:
        _write(self.repo, "src/app.py", "def main():\n    pass\n")
        sink = io.StringIO()
        with mock.patch("sys.stdout", sink):
            code = run_review_command(
                self.repo, ["src/app.py"], adapter=StubAdapter()
            )
        self.assertEqual(code, 0)
        captured = sink.getvalue()
        self.assertIn("REVIEW run=", captured)
        self.assertIn("status=completed", captured)
        self.assertIn(f"p01_run={_COMPLETED_RUN_ID}", captured)
        self.assertIn("events=3", captured)

    def test_run_draft_command_without_engine_config_fails_closed(self) -> None:
        code = run_draft_command(self.repo, "context.md", "견적서", environ={})
        self.assertEqual(code, 2)

    def test_run_draft_command_invalid_doc_type_fails_closed(self) -> None:
        code = run_draft_command(self.repo, "context.md", "세금계산서", environ={})
        self.assertEqual(code, 2)

    def test_cli_subcommand_wires_draft_doc_type_choices(self) -> None:
        self.assertEqual(set(DRAFT_DOC_TYPES), {"견적서", "발주서"})
        args = parser().parse_args(
            ["repo", "draft", "input.md", "--doc-type", "발주서", "--out", "o.md"]
        )
        self.assertEqual(args.mode, "draft")
        self.assertEqual(args.input, "input.md")
        self.assertEqual(args.doc_type, "발주서")
        self.assertEqual(args.out, "o.md")

    def test_cli_main_runs_draft_with_adapter(self) -> None:
        code = main(
            [str(self.repo), "draft", "context.md", "--doc-type", "견적서"],
            adapter=StubAdapter(answers=[_EXTRACTION_OUTPUT, "초안 완료"]),
        )
        self.assertEqual(code, 0)

    def test_end_to_end_through_real_adapter_and_fake_transport(self) -> None:
        transport = CorrelatedTransport(
            answers=[
                _EXTRACTION_FULL_TOTALS,
                "견적서 초안 완료: 거래 맥락에 근거했습니다.",
            ]
        )
        adapter = p01_adapter_from_environment(
            {
                "P01_ENGINE_BASE_URL": _ENGINE_BASE_URL,
                "P01_ENGINE_CALLER_ID": "b54-draft-e2e",
                "P01_ENGINE_CREDENTIAL": _FAKE_CREDENTIAL,
            },
            transport=transport,
        )
        out = self.repo / "e2e.md"
        code = run_draft_command(
            self.repo,
            "context.md",
            "견적서",
            adapter=adapter,
            out_path=out,
        )
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())
        self.assertIn(
            "견적서 초안 완료: 거래 맥락에 근거했습니다.", out.read_text(encoding="utf-8")
        )
        self.assertEqual(len(transport.requests), 2)
        for sent in transport.requests:
            self.assertEqual(sent["url"], f"{_ENGINE_BASE_URL}/internal/v1/orchestrate")
            payload = json.loads(sent["body"].decode("utf-8"))
            self.assertEqual(
                payload["agent"]["model_policy"],
                {"model": "sensenova/sensenova-6.8-flash-lite"},
            )
            self.assertNotIn("provider", json.dumps(payload).lower())
            self.assertNotIn("credential", payload["agent"])
            self.assertNotIn(_FAKE_CREDENTIAL, sent["body"].decode("utf-8"))
            self.assertEqual(
                sent["headers"]["X-Padiem-Engine-Credential"], _FAKE_CREDENTIAL
            )
        first_content = json.loads(
            transport.requests[0]["body"].decode("utf-8")
        )["messages"][0]["content"]
        second_content = json.loads(
            transport.requests[1]["body"].decode("utf-8")
        )["messages"][0]["content"]
        self.assertIn("거래 맥락 추출", first_content)
        self.assertIn("한빛상사", first_content)
        for phrase in _ANTI_HALLUCINATION_PHRASES:
            self.assertIn(phrase, first_content)
        self.assertIn("산출표", second_content)
        self.assertIn("1700000", second_content)
        for phrase in _ANTI_HALLUCINATION_PHRASES:
            self.assertIn(phrase, second_content)


if __name__ == "__main__":
    unittest.main()
