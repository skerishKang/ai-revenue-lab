from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from math import ceil
from pathlib import Path
import sys
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
from kagent.contracts import ClawRunStatus, ExecutionMode, RunProjection
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
    MAX_REVIEW_CHUNK_CHARS,
    MAX_REVIEW_FILE_BYTES,
    MAX_REVIEW_FILES,
    MAX_REVIEW_FILES_PER_CHUNK,
    ReviewFlowError,
    ReviewOutcome,
    _chunk_review_files,
    run_review,
    run_review_command,
)

_FAKE_CREDENTIAL = "b54-review-credential-" + ("0" * 32)
_COMPLETED_RUN_ID = "review_run_001"
_ENGINE_BASE_URL = "https://padiem-ai-engine.internal"
_TRUNCATION_MARKER = "(생성 창 초과로 잘림)"

_TRUNCATED_ANSWER = (
    "리뷰 관찰: 함수 분리가 부족하고 중복 코드가 존재하며 "
    "유닛 테스트가 없어서 회귀 위험이 크고 오류 처리가 누락되어 있습니다 "
    "보안 검토가 필요하며 의존성 갱신도 이루어지지 않았습니다 "
    "또한 상태 관리가 전역 변수로 되어 있어 동시성 문제가 발생할 수 있고 "
    "로깅 구조가 일관되지 않으며 성능 최적화 여지도 있고 문서화가 미흡합니다"
)
_COMPLETE_ANSWER = (
    "함수 분리가 부족하지만 현재 동작은 정상입니다.\n"
    "위험: LOW — 소규모 개선 제안만 존재합니다."
)


class CorrelatedTransport:
    """Network-free transport that answers with a public result correlated to
    the actual outgoing request, so the real adapter's correlation checks pass."""

    def __init__(self) -> None:
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
                answer="리뷰 완료: 저장소에 심각한 버그는 없습니다.",
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


class StubAdapter:
    """Duck-typed adapter surface for validation-only review tests."""

    def __init__(self, answer: str = "리뷰 완료") -> None:
        self.answer = answer
        self.runs = []

    async def execute(self, run):
        self.runs.append(run)
        run.transition(ClawRunStatus.PREPARING, summary="리뷰 실행 준비")
        run.transition(ClawRunStatus.RUNNING, summary="리뷰 실행")
        run.transition(ClawRunStatus.COMPLETED, summary="리뷰 완료")
        return ClawOrchestrationOutcome(
            projection=RunProjection(
                run_id=run.run_id,
                task_id=run.intent.task_id,
                status=ClawRunStatus.COMPLETED,
                execution_mode=ExecutionMode.LOCAL,
            ),
            answer=self.answer,
            p01_run_id=_COMPLETED_RUN_ID,
            p01_event_count=3,
        )


class ScriptedAdapter:
    """Per-request scripted adapter for aggregation/failure/truncation tests.

    ``fail_at`` raises a ``P01AdapterError`` on that 1-based run;
    ``fail_every_from`` raises on that run and every later one (so a flow
    retry of the same request also fails); ``failed_outcome_at`` returns a
    FAILED (non-exception) outcome instead.
    """

    def __init__(
        self,
        answers: list[str] | None = None,
        *,
        fail_at: int | None = None,
        failed_outcome_at: int | None = None,
        fail_every_from: int | None = None,
    ) -> None:
        self.answers = list(answers or [])
        self.fail_at = fail_at
        self.failed_outcome_at = failed_outcome_at
        self.fail_every_from = fail_every_from
        self.runs = []

    async def execute(self, run):
        self.runs.append(run)
        run.transition(ClawRunStatus.PREPARING, summary="리뷰 실행 준비")
        run.transition(ClawRunStatus.RUNNING, summary="리뷰 실행")
        index = len(self.runs)
        if self.fail_at == index or (
            self.fail_every_from is not None and index >= self.fail_every_from
        ):
            run.transition(ClawRunStatus.FAILED, summary="엔진 요청 실패")
            raise P01AdapterError("p01_engine_request_failed", "엔진 요청 실패")
        if self.failed_outcome_at == index:
            run.transition(ClawRunStatus.FAILED, summary="실행 실패")
            return ClawOrchestrationOutcome(
                projection=RunProjection(
                    run_id=run.run_id,
                    task_id=run.intent.task_id,
                    status=ClawRunStatus.FAILED,
                    execution_mode=ExecutionMode.LOCAL,
                ),
                answer=None,
                p01_run_id=_COMPLETED_RUN_ID,
                p01_event_count=2,
            )
        run.transition(ClawRunStatus.COMPLETED, summary="리뷰 완료")
        answer = self.answers.pop(0) if self.answers else "리뷰 완료"
        return ClawOrchestrationOutcome(
            projection=RunProjection(
                run_id=run.run_id,
                task_id=run.intent.task_id,
                status=ClawRunStatus.COMPLETED,
                execution_mode=ExecutionMode.LOCAL,
            ),
            answer=answer,
            p01_run_id=_COMPLETED_RUN_ID,
            p01_event_count=3,
        )


def _write(repo: Path, name: str, content: bytes | str) -> Path:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    kwargs = {} if isinstance(content, bytes) else {"encoding": "utf-8"}
    with open(path, mode, **kwargs) as handle:
        handle.write(content)
    return path


class RepositoryReviewFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _write(self.repo, "src/app.py", "def main():\n    print('hi')\n")
        _write(self.repo, "src/util.py", "def helper():\n    return 1\n")
        _write(self.repo, "README.md", "# 예제 저장소\n")
        _write(self.repo, "assets/logo.bin", b"\x00\x01\x02\x89PNG\r\n")
        _write(self.repo, "assets/euckr.txt", "한글".encode("euc-kr"))
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

    def test_happy_path_splits_small_files_across_bounded_chunks_and_aggregates(
        self,
    ) -> None:
        adapter = ScriptedAdapter(
            answers=[
                "app.py 리뷰.\n위험: MEDIUM — 테스트 부족.\n"
                "util.py 리뷰.\n위험: LOW — 단순 함수.\n",
                "README 리뷰.\n위험: LOW — 문서 수준.",
            ]
        )
        outcome = run_review(self.repo, ["src/*.py", "README.md"], adapter)

        self.assertIsInstance(outcome, ReviewOutcome)
        self.assertEqual(
            outcome.reviewed, ("src/app.py", "src/util.py", "README.md")
        )
        self.assertEqual(outcome.failed, ())
        self.assertEqual(outcome.skipped, ())
        self.assertEqual(outcome.truncated, ())
        self.assertEqual(outcome.p01_run_id, _COMPLETED_RUN_ID)
        self.assertEqual(outcome.p01_event_count, 6)
        self.assertEqual(len(outcome.p01_runs), 2)
        self.assertEqual(len(adapter.runs), 2)
        self.assertTrue(
            all(run.status is ClawRunStatus.COMPLETED for run in adapter.runs)
        )
        self.assertEqual(
            [run.run_id for run in adapter.runs],
            [run_id for run_id, _, _ in outcome.p01_runs],
        )
        report = outcome.report_text()
        self.assertIn("## 리뷰 결과", report)
        self.assertIn("src/app.py", report)
        self.assertIn("src/util.py", report)
        self.assertIn("README.md", report)
        self.assertIn("## 통합 위험 목록", report)
        self.assertIn("MEDIUM", report)
        self.assertIn("LOW", report)

    def test_small_files_share_one_chunk_request(self) -> None:
        _write(self.repo, "tiny/a.py", "x = 1\n")
        _write(self.repo, "tiny/b.py", "y = 2\n")
        adapter = StubAdapter()
        run_review(self.repo, ["tiny/*.py"], adapter)

        self.assertEqual(len(adapter.runs), 1)
        self.assertIn("a.py", adapter.runs[0].intent.task)
        self.assertIn("b.py", adapter.runs[0].intent.task)

    def test_many_small_files_are_split_into_bounded_chunks(self) -> None:
        for index in range(5):
            _write(self.repo, f"many/f{index}.py", f"v{index} = {index}\n")
        adapter = StubAdapter()
        outcome = run_review(self.repo, ["many/*.py"], adapter)

        self.assertEqual(len(adapter.runs), 3)
        self.assertLessEqual(len(outcome.reviewed), 5)
        self.assertEqual(len(outcome.reviewed), 5)
        self.assertEqual(MAX_REVIEW_FILES_PER_CHUNK, 2)

    def test_single_large_file_is_forced_into_budget_sized_parts(self) -> None:
        content = "a" * 12_500  # no newlines → deterministic size on all platforms
        _write(self.repo, "big.py", content)
        adapter = StubAdapter()
        outcome = run_review(self.repo, ["big.py"], adapter)

        expected_parts = ceil(len(content) / MAX_REVIEW_CHUNK_CHARS)
        self.assertEqual(outcome.reviewed, ("big.py",))
        self.assertEqual(outcome.failed, ())
        self.assertEqual(outcome.skipped, ())
        self.assertEqual(len(adapter.runs), expected_parts)
        self.assertEqual(len(outcome.sections), expected_parts)
        for run in adapter.runs:
            task = run.intent.task
            self.assertLessEqual(len(task), 12_000)
            self.assertIn("big.py (파트", task)
            self.assertIn("400자 이내", task)
        report = outcome.report_text()
        self.assertIn("(파트 1/", report)
        self.assertIn(f"(파트 {expected_parts}/{expected_parts})", report)

    def test_sliced_parts_cover_the_whole_file(self) -> None:
        content = "abcdefgh" * 1_500  # exactly 12,000 chars
        chunks = _chunk_review_files([("big.py", content)])

        part_count = ceil(len(content) / MAX_REVIEW_CHUNK_CHARS)
        self.assertEqual(len(chunks), part_count)
        rebuilt: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            self.assertEqual(len(chunk), 1)
            part = chunk[0]
            self.assertEqual(part.rel_path, "big.py")
            self.assertEqual(part.display_name, f"big.py (파트 {index}/{part_count})")
            rebuilt.append(part.content)
            self.assertLessEqual(
                sum(len(part.content) for part in chunk), MAX_REVIEW_CHUNK_CHARS
            )
            self.assertLessEqual(len(chunk), MAX_REVIEW_FILES_PER_CHUNK)
        self.assertEqual("".join(rebuilt), content)

    def test_large_file_between_small_files_keeps_small_chunks_intact(self) -> None:
        reviewed = [
            ("a.py", "x" * 100),
            ("big.py", "y" * 17_000),
            ("b.py", "z" * 100),
        ]
        chunks = _chunk_review_files(reviewed)

        self.assertEqual([part.rel_path for part in chunks[0]], ["a.py"])
        self.assertEqual([part.rel_path for part in chunks[-1]], ["b.py"])
        self.assertEqual(len(chunks), 7)
        self.assertTrue(
            all(
                [part.rel_path for part in chunk] == ["big.py"]
                for chunk in chunks[1:-1]
            )
        )
        self.assertTrue(
            all(
                "파트" in chunk[0].part_label for chunk in chunks[1:-1]
            )
        )

    def test_guard_all_chunk_tasks_stay_within_task_bound_real_readme(self) -> None:
        readme = Path(__file__).resolve().parents[3] / "README.md"
        if not readme.is_file():
            self.skipTest("repo root README.md not available")
        readme_text = readme.read_text(encoding="utf-8")
        self.assertGreater(len(readme_text), MAX_REVIEW_CHUNK_CHARS)
        _write(self.repo, "README.md", readme_text)
        for index in range(3):
            _write(
                self.repo,
                f"src/source_{index}.py",
                f"# module {index}\n" + ("x" * 5_900),
            )
        adapter = StubAdapter()
        outcome = run_review(
            self.repo,
            ["README.md", "src/source_0.py", "src/source_1.py", "src/source_2.py"],
            adapter,
        )

        self.assertEqual(outcome.failed, ())
        self.assertEqual(len(outcome.reviewed), 4)
        self.assertGreater(len(adapter.runs), 1)
        for run in adapter.runs:
            self.assertLessEqual(len(run.intent.task), 12_000)

    def test_review_prompt_includes_bounded_length_guidance(self) -> None:
        adapter = StubAdapter()
        run_review(self.repo, ["src/app.py"], adapter)

        task = adapter.runs[0].intent.task
        self.assertIn("2-3문장", task)
        self.assertIn("400자 이내", task)

    def test_review_prompt_carries_file_contents_in_task(self) -> None:
        adapter = StubAdapter()
        run_review(self.repo, ["src/app.py"], adapter)

        task = adapter.runs[0].intent.task
        self.assertIn("src/app.py", task)
        self.assertIn("def main():", task)

    def test_binary_and_non_utf8_files_are_skipped_not_silently_dropped(self) -> None:
        adapter = StubAdapter()
        outcome = run_review(self.repo, ["assets/*", "src/*.py"], adapter)

        self.assertEqual(outcome.reviewed, ("src/app.py", "src/util.py"))
        reasons = dict(outcome.skipped)
        self.assertIn("assets/logo.bin", reasons)
        self.assertIn("바이너리", reasons["assets/logo.bin"])
        self.assertIn("assets/euckr.txt", reasons)
        self.assertIn("인코딩", reasons["assets/euckr.txt"])

    def test_missing_target_raises_review_target_missing(self) -> None:
        with self.assertRaises(ReviewFlowError) as ctx:
            run_review(self.repo, ["does-not-exist.py"], StubAdapter())
        self.assertEqual(ctx.exception.code, "review_target_missing")

    def test_glob_with_no_matches_raises_review_target_missing(self) -> None:
        with self.assertRaises(ReviewFlowError) as ctx:
            run_review(self.repo, ["missing/*.py"], StubAdapter())
        self.assertEqual(ctx.exception.code, "review_target_missing")

    def test_directory_target_raises_review_target_missing(self) -> None:
        with self.assertRaises(ReviewFlowError) as ctx:
            run_review(self.repo, ["src"], StubAdapter())
        self.assertEqual(ctx.exception.code, "review_target_missing")

    def test_traversal_outside_repo_is_rejected(self) -> None:
        with self.assertRaises(ReviewFlowError) as ctx:
            run_review(self.repo, [str(self.repo.parent)], StubAdapter())
        self.assertEqual(ctx.exception.code, "review_target_invalid")

    def test_over_file_count_limit_is_rejected(self) -> None:
        for index in range(MAX_REVIEW_FILES + 1):
            _write(self.repo, f"many/f{index:03d}.txt", "x")
        with self.assertRaises(ReviewFlowError) as ctx:
            run_review(self.repo, ["many/*.txt"], StubAdapter())
        self.assertEqual(ctx.exception.code, "review_input_too_large")

    def test_over_single_file_size_limit_is_rejected(self) -> None:
        _write(self.repo, "big.txt", "x" * (MAX_REVIEW_FILE_BYTES + 1))
        with self.assertRaises(ReviewFlowError) as ctx:
            run_review(self.repo, ["big.txt"], StubAdapter())
        self.assertEqual(ctx.exception.code, "review_input_too_large")

    def test_repo_with_no_reviewable_text_raises_review_target_missing(self) -> None:
        with self.assertRaises(ReviewFlowError) as ctx:
            run_review(self.repo, ["assets/logo.bin"], StubAdapter())
        self.assertEqual(ctx.exception.code, "review_target_missing")

    def test_one_file_failure_does_not_fail_whole_run(self) -> None:
        _write(self.repo, "src/extra.py", "def extra():\n    return 2\n")
        _write(self.repo, "src/pass.py", "def okay():\n    return 3\n")
        _write(self.repo, "src/fail.py", "def boom():\n    return 4\n")
        adapter = ScriptedAdapter(
            answers=["src/app.py 리뷰 정상.\n위험: LOW — 문제 없음."],
            fail_every_from=3,
        )
        outcome = run_review(
            self.repo,
            [
                "src/app.py",
                "src/util.py",
                "src/extra.py",
                "src/pass.py",
                "src/fail.py",
            ],
            adapter,
        )

        self.assertEqual(
            outcome.failed, (("src/fail.py", "p01_engine_request_failed"),)
        )
        self.assertEqual(len(outcome.sections), 2)
        self.assertEqual(
            outcome.reviewed,
            (
                "src/app.py",
                "src/util.py",
                "src/extra.py",
                "src/pass.py",
                "src/fail.py",
            ),
        )
        report = outcome.report_text()
        self.assertIn("실패: src/fail.py — p01_engine_request_failed", report)
        self.assertIn("src/fail.py — 리뷰 요청 실패", report)
        self.assertIn("### src/app.py, src/util.py", report)
        code = run_review_command(
            self.repo,
            [
                "src/app.py",
                "src/util.py",
                "src/extra.py",
                "src/pass.py",
                "src/fail.py",
            ],
            adapter=ScriptedAdapter(
                answers=["정상"],
                fail_every_from=3,
            ),
        )
        self.assertEqual(code, 0)

    def test_one_file_failed_status_does_not_fail_whole_run(self) -> None:
        _write(self.repo, "src/extra.py", "def extra():\n    return 2\n")
        _write(self.repo, "src/pass.py", "def okay():\n    return 3\n")
        _write(self.repo, "src/fail.py", "def boom():\n    return 4\n")
        adapter = ScriptedAdapter(
            answers=["src/app.py 리뷰 정상.\n위험: LOW — 문제 없음."],
            failed_outcome_at=3,
        )
        outcome = run_review(
            self.repo,
            [
                "src/app.py",
                "src/util.py",
                "src/extra.py",
                "src/pass.py",
                "src/fail.py",
            ],
            adapter,
        )

        self.assertEqual(outcome.failed, (("src/fail.py", "failed"),))
        self.assertEqual(len(outcome.sections), 2)

    def test_requests_are_paced_between_orchestration_requests(self) -> None:
        _write(self.repo, "src/extra.py", "def extra():\n    return 2\n")
        adapter = StubAdapter()
        outcome = run_review(self.repo, ["src/*.py", "README.md"], adapter)

        self.assertEqual(len(adapter.runs), 2)
        self.assertEqual(outcome.failed, ())
        self.assertEqual(self.sleep_calls, [FLOW_PACING_SECONDS])

    def test_retryable_engine_failure_retries_once_after_wait(self) -> None:
        adapter = ScriptedAdapter(fail_at=1)
        outcome = run_review(self.repo, ["src/app.py"], adapter)

        self.assertEqual(len(adapter.runs), 2)
        self.assertEqual(outcome.failed, ())
        self.assertEqual(len(outcome.sections), 1)
        self.assertEqual(self.sleep_calls, [FLOW_RETRY_WAIT_SECONDS])

    def test_retryable_failure_exhausted_is_recorded_as_failed(self) -> None:
        adapter = ScriptedAdapter(fail_every_from=1)
        outcome = run_review(self.repo, ["src/app.py"], adapter)

        self.assertEqual(len(adapter.runs), 2)
        self.assertEqual(
            outcome.failed, (("src/app.py", "p01_engine_request_failed"),)
        )
        self.assertEqual(outcome.sections, ())
        self.assertEqual(self.sleep_calls, [FLOW_RETRY_WAIT_SECONDS])

    def test_contract_error_on_over_bound_task_is_isolated_without_traceback(
        self,
    ) -> None:
        _write(self.repo, "big.txt", "y" * 15_000)
        stderr_sink = io.StringIO()
        with (
            mock.patch.object(review_flow_module, "MAX_REVIEW_CHUNK_CHARS", 100_000),
            redirect_stderr(stderr_sink),
            redirect_stdout(io.StringIO()),
        ):
            outcome = run_review(self.repo, ["big.txt"], StubAdapter())
            code = run_review_command(
                self.repo, ["big.txt"], adapter=StubAdapter()
            )

        self.assertEqual(
            outcome.failed, (("big.txt", "review_task_too_large"),)
        )
        self.assertEqual(outcome.sections, ())
        self.assertEqual(outcome.p01_runs, ())
        self.assertEqual(outcome.reviewed, ("big.txt",))
        self.assertEqual(code, 0)
        self.assertNotIn("Traceback", stderr_sink.getvalue())
        self.assertIn("실패: big.txt — review_task_too_large", outcome.report_text())

    def test_truncated_answer_is_marked_not_hidden(self) -> None:
        adapter = ScriptedAdapter(answers=[_TRUNCATED_ANSWER])
        outcome = run_review(self.repo, ["src/app.py"], adapter)

        self.assertEqual(outcome.truncated, ("src/app.py",))
        self.assertIn(_TRUNCATION_MARKER, outcome.report_text())
        section_text = outcome.sections[0][1]
        self.assertTrue(section_text.endswith(_TRUNCATION_MARKER))

    def test_complete_answer_is_not_marked_truncated(self) -> None:
        adapter = ScriptedAdapter(answers=[_COMPLETE_ANSWER])
        outcome = run_review(self.repo, ["src/app.py"], adapter)

        self.assertEqual(outcome.truncated, ())
        self.assertNotIn(_TRUNCATION_MARKER, outcome.report_text())

    def test_aggregate_risk_list_extracts_risk_lines(self) -> None:
        _write(self.repo, "src/extra.py", "def extra():\n    return 2\n")
        _write(self.repo, "src/next.py", "def nxt():\n    return 3\n")
        adapter = ScriptedAdapter(
            answers=[
                "app.py 리뷰.\n위험: HIGH — 민감정보 로깅.",
                "next.py 리뷰.\n위험: MEDIUM — 예외 삼킴.",
            ]
        )
        outcome = run_review(
            self.repo,
            ["src/app.py", "src/util.py", "src/extra.py", "src/next.py"],
            adapter,
        )

        report = outcome.report_text()
        risk_section = report.split("## 통합 위험 목록", 1)[1]
        self.assertIn("HIGH", risk_section)
        self.assertIn("MEDIUM", risk_section)
        self.assertIn("민감정보 로깅", risk_section)
        self.assertIn("예외 삼킴", risk_section)

    def test_run_review_command_writes_markdown_out_path(self) -> None:
        out = self.repo / "out" / "report.md"
        code = run_review_command(
            self.repo,
            ["src/app.py"],
            adapter=StubAdapter(),
            out_path=out,
        )
        self.assertEqual(code, 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn("# 저장소 리뷰 보고서", text)
        self.assertIn("## 리뷰 결과", text)

    def test_run_review_command_without_engine_config_fails_closed(self) -> None:
        code = run_review_command(
            self.repo, ["src/app.py"], environ={}
        )
        self.assertEqual(code, 2)

    def test_command_prints_utf8_report_even_with_ansi_codepage_stdout(self) -> None:
        sink = io.BytesIO()
        original = sys.stdout
        wrapper = io.TextIOWrapper(sink, encoding="cp1252")
        sys.stdout = wrapper
        try:
            code = run_review_command(
                self.repo, ["src/app.py"], adapter=StubAdapter()
            )
            wrapper.flush()
        finally:
            sys.stdout = original
        self.assertEqual(code, 0)
        captured = sink.getvalue().decode("utf-8")
        self.assertIn("## 리뷰 결과", captured)
        self.assertIn("src/app.py", captured)

    def test_end_to_end_through_real_adapter_and_fake_transport(self) -> None:
        _write(self.repo, "src/extra.py", "def extra():\n    return 2\n")
        _write(self.repo, "src/last.py", "def last():\n    return 3\n")
        transport = CorrelatedTransport()
        adapter = p01_adapter_from_environment(
            {
                "P01_ENGINE_BASE_URL": _ENGINE_BASE_URL,
                "P01_ENGINE_CALLER_ID": "b54-review-e2e",
                "P01_ENGINE_CREDENTIAL": _FAKE_CREDENTIAL,
            },
            transport=transport,
        )
        out = self.repo / "e2e.md"
        code = run_review_command(
            self.repo,
            ["src/app.py", "src/util.py", "src/extra.py", "src/last.py"],
            adapter=adapter,
            out_path=out,
        )
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())
        self.assertIn(
            "리뷰 완료: 저장소에 심각한 버그는 없습니다.", out.read_text(encoding="utf-8")
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
        self.assertIn("src/app.py", first_content)
        self.assertIn("src/util.py", first_content)
        self.assertIn("src/last.py", second_content)


if __name__ == "__main__":
    unittest.main()
