"""#3930 opt-in P01 adapter live callback and terminal authority regression."""
import unittest

from padiem_ai_core.orchestration_events import OrchestrationEventKind
from kagent.contracts import ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import P01AdapterError, P01CoreOrchestrationAdapter, P01DispatchClass
from kagent.runs import ClawRun
from model_route_fixture import SyntheticPlusRouteTestCase
from test_p01_adapter import _ResultFactory


def local_run():
    intent = ClawTaskIntent(
        task_id="task_3930_live", task="P01 이벤트를 검증해줘",
        repository_ref="repo", execution_mode=ExecutionMode.LOCAL,
    )
    return ClawRun.create("run_3930_live", intent)


class LiveRunner:
    def __init__(self, kinds, *, mutate_terminal=False):
        self.kinds = kinds
        self.mutate_terminal = mutate_terminal
        self.run_called = 0
        self.stream_called = 0

    async def run(self, request):
        self.run_called += 1
        raise AssertionError("legacy route must not be invoked")

    async def run_stream(self, request, *, on_event):
        self.stream_called += 1
        result = _ResultFactory.result(request, self.kinds)
        for event in result.events:
            await on_event(event)
        if self.mutate_terminal:
            return _ResultFactory.result(request, [
                OrchestrationEventKind.RUN_STARTED, OrchestrationEventKind.RUN_FAILED
            ])
        return result


class AdapterLiveSseTests(SyntheticPlusRouteTestCase, unittest.IsolatedAsyncioTestCase):
    async def test_live_nonterminal_events_then_single_verified_terminal(self):
        runner = LiveRunner([
            OrchestrationEventKind.RUN_STARTED, OrchestrationEventKind.TOOL_STARTED,
            OrchestrationEventKind.TOOL_COMPLETED, OrchestrationEventKind.RUN_COMPLETED,
        ])
        seen = []
        async def capture(event):
            seen.append(event.kind.value)
        run = local_run()
        outcome = await P01CoreOrchestrationAdapter(runner).execute(run, on_event=capture)
        self.assertEqual(outcome.answer, "완료 답변")
        self.assertEqual(seen, ["run_started", "tool_started", "tool_completed", "run_completed"])
        self.assertEqual(outcome.p01_event_count, 4)
        self.assertEqual(runner.stream_called, 1)
        self.assertEqual(runner.run_called, 0)

    async def test_no_terminal_callback_without_valid_result(self):
        runner = LiveRunner([
            OrchestrationEventKind.RUN_STARTED, OrchestrationEventKind.RUN_COMPLETED,
        ], mutate_terminal=True)
        seen = []
        async def capture(event):
            seen.append(event.kind.value)
        with self.assertRaises(P01AdapterError):
            await P01CoreOrchestrationAdapter(runner).execute(local_run(), on_event=capture)
        self.assertEqual(seen, ["run_started"])

    async def test_missing_stream_is_not_dispatched(self):
        class OnlyCompleted:
            async def run(self, request):
                raise AssertionError("completed forbidden")
        async def capture(event):
            raise AssertionError("unexpected event")
        with self.assertRaises(P01AdapterError) as error:
            await P01CoreOrchestrationAdapter(OnlyCompleted()).execute(local_run(), on_event=capture)
        self.assertEqual(error.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED)
