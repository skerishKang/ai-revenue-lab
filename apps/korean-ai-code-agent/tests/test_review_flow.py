from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

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

from kagent.contracts import ClawRunStatus, ExecutionMode, RunProjection
from kagent.p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    ClawOrchestrationOutcome,
)
from kagent.p01_run_flow import p01_adapter_from_environment
from kagent.review_flow import (
    MAX_REVIEW_FILE_BYTES,
    MAX_REVIEW_FILES,
    ReviewFlowError,
    ReviewOutcome,
    run_review,
    run_review_command,
)

_FAKE_CREDENTIAL = "b54-review-credential-" + ("0" * 32)
_COMPLETED_RUN_ID = "review_run_001"
_ENGINE_BASE_URL = "https://padiem-ai-engine.internal"


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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_happy_path_collects_files_and_returns_report(self) -> None:
        adapter = StubAdapter()
        outcome = run_review(self.repo, ["src/*.py", "README.md"], adapter)

        self.assertIsInstance(outcome, ReviewOutcome)
        self.assertEqual(outcome.reviewed, ("src/app.py", "src/util.py", "README.md"))
        self.assertEqual(outcome.skipped, ())
        self.assertEqual(outcome.p01_run_id, _COMPLETED_RUN_ID)
        self.assertEqual(outcome.p01_event_count, 3)
        self.assertEqual(outcome.projection.status, ClawRunStatus.COMPLETED)
        self.assertEqual(len(adapter.runs), 1)
        self.assertEqual(adapter.runs[0].status, ClawRunStatus.COMPLETED)
        report = outcome.report_text()
        self.assertIn("src/app.py", report)
        self.assertIn("## 리뷰 결과", report)
        self.assertIn("리뷰 완료", report)

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
            ["src/*.py"],
            adapter=adapter,
            out_path=out,
        )
        self.assertEqual(code, 0)
        self.assertTrue(out.exists())
        self.assertIn("리뷰 완료: 저장소에 심각한 버그는 없습니다.", out.read_text(encoding="utf-8"))
        self.assertEqual(len(transport.requests), 1)
        sent = transport.requests[0]
        self.assertEqual(sent["url"], f"{_ENGINE_BASE_URL}/internal/v1/orchestrate")
        payload = json.loads(sent["body"].decode("utf-8"))
        self.assertEqual(
            payload["agent"]["model_policy"],
            {"model": "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"},
        )
        self.assertNotIn("provider", json.dumps(payload).lower())
        self.assertNotIn("credential", payload["agent"])
        self.assertNotIn(_FAKE_CREDENTIAL, sent["body"].decode("utf-8"))
        self.assertEqual(sent["headers"]["X-Padiem-Engine-Credential"], _FAKE_CREDENTIAL)
        self.assertIn("src/app.py", payload["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
