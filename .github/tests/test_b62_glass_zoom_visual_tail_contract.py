"""#5210: the Glass Zoom visual-tail lane must measure the product's pause
latency, and a failing suite's assertion must survive the COM2 runner's bounded
diagnostic window.

Three contracts:

1. ``b62_glass_zoom_visual_qa.py`` dispatches the scroll-up wheel and reads the
   measurement start clock.  Dispatching is a host-to-page round trip, so
   reading the clock in a *second* round trip adds that host latency to the
   measured pause window.  On a loaded runner the host round trip alone can
   exceed the unchanged 200 ms ceiling, so the suite then measures the
   runner instead of the product.  The clock must be captured inside the same
   in-page evaluation that dispatches the wheel, and that timestamp must be
   the measurement start.

2. ``b62_browser_qa_tail_parallel.py`` runs the three visual-tail suites and
   keeps every suite and its hard failure fan-in.  The COM2 runner only keeps
   the last N log lines, so a failing suite's assertion has to be repeated
   after all suites have printed, otherwise the failure text is lost.

3. The Glass Zoom suite measures the conversation motion clock, not the chat
   transport.  COM2 run 39498783280 failed it exactly at the suite's unchanged
   15 s answer wait (``Page.wait_for_function: Timeout 15000ms exceeded``) on
   the 1-CPU offline container, while the identical suite passes on the 2-core
   hosted lane at the same head (21.77 s, ``B62_VISUAL_TAIL_FAIL_COUNT=0``).
   The answer therefore comes from the same kind of in-page route mock the
   sibling suites already use, and the wait budget, the predicate, the real
   clicks and the 200 ms / 2500 ms thresholds stay untouched.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
ZOOM = ROOT / ".github/scripts/b62_glass_zoom_visual_qa.py"
TIMING = ROOT / ".github/scripts/b62_visual_timing.py"
TAIL = ROOT / ".github/scripts/b62_browser_qa_tail_parallel.py"
PLANNER = ROOT / ".github/scripts/b62_browser_qa_path_plan.py"
CANARY = ROOT / ".github/workflows/com2-b62-generic-browser-canary.yml"
CONTRACT_TEST = ".github/tests/test_b62_glass_zoom_visual_tail_contract.py"

# The text the suite's answer wait requires, and the text the mock runtime
# answers with.
PREVIEW_MARKER = "지금은 미리보기 환경입니다"

if "playwright.async_api" not in sys.modules:
    _playwright = types.ModuleType("playwright")
    _async_api = types.ModuleType("playwright.async_api")
    _async_api.Page = object
    _playwright.async_api = _async_api
    sys.modules["playwright"] = _playwright
    sys.modules["playwright.async_api"] = _async_api

# Sibling CI contract tests install their own partial `playwright.async_api`
# stub and whichever is collected first owns sys.modules, so the names this
# suite imports are added to whatever module object is already registered.
_api = sys.modules.get("playwright.async_api")
if _api is None:
    _api = types.ModuleType("playwright.async_api")
    _playwright = sys.modules.setdefault("playwright", types.ModuleType("playwright"))
    _playwright.async_api = _api
    sys.modules["playwright.async_api"] = _api
for _name in ("Browser", "BrowserContext", "Locator", "Page", "Route", "async_playwright"):
    if not hasattr(_api, _name):
        setattr(_api, _name, object)

# Importing the suite would otherwise create its evidence directory under
# the read-only checkout of the plan job.
os.environ.setdefault(
    "B62_QA_OUT_DIR", tempfile.mkdtemp(prefix="b62-zoom-tail-contract-")
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The suite imports its timing helper as a sibling module, exactly as it does
# when it runs from its own directory.
_load_module("b62_visual_timing", TIMING)
zoom = _load_module("b62_glass_zoom_qa", ZOOM)

_spec = importlib.util.spec_from_file_location("b62_qa_tail", TAIL)
tail = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tail)


def _function(tree: ast.Module, name: str) -> ast.AsyncFunctionDef:
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )


def _preview_wait_call(source: str) -> ast.Call:
    """The answer wait whose predicate requires the preview text."""

    tree = ast.parse(source)
    capture = _function(tree, "_capture")
    for node in ast.walk(capture):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "wait_for_function"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and PREVIEW_MARKER in node.args[0].value
        ):
            return node
    raise AssertionError("the preview answer wait is missing")


def _preview_wait_budget(source: str) -> int:
    node = _preview_wait_call(source)
    for keyword in node.keywords:
        if keyword.arg == "timeout":
            return int(keyword.value.value)
    raise AssertionError("the preview answer wait has no explicit timeout")


def _capture_order(source: str) -> dict[str, int]:
    """Statement indexes of the route-mock install, the composer readiness wait
    and the real send click inside ``_capture``."""

    tree = ast.parse(source)
    capture = _function(tree, "_capture")
    order = {"install": -1, "readiness": -1, "send": -1}
    for index, statement in enumerate(capture.body):
        dumped = ast.dump(statement)
        if order["install"] < 0 and "_install_preview_stream" in dumped:
            order["install"] = index
        if order["readiness"] < 0 and "PadiemChatInteractionPresentation" in dumped:
            order["readiness"] = index
        if order["send"] < 0 and "sendButton" in dumped and "click" in dumped:
            order["send"] = index
    return order


def _send_click(source: str) -> ast.Call:
    """The real click on the product's send button."""

    tree = ast.parse(source)
    capture = _function(tree, "_capture")
    for node in ast.walk(capture):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "click"
            and "sendButton" in ast.dump(node)
        ):
            return node
    raise AssertionError("the send click is missing")


class _FakeRequest:
    def __init__(self, post_data: str) -> None:
        self.post_data = post_data


class _FakeRoute:
    def __init__(self, post_data: str = "{}") -> None:
        self.request = _FakeRequest(post_data)
        self.status: int | None = None
        self.content_type: str | None = None
        self.body: str | None = None
        self.headers: dict | None = None

    async def fulfill(self, *, status, content_type, body, headers=None) -> None:
        self.status = status
        self.content_type = content_type
        self.body = body
        self.headers = headers or {}


class _FakePage:
    def __init__(self) -> None:
        self.patterns: list[str] = []
        self.handlers: dict[str, object] = {}

    async def route(self, pattern: str, handler) -> None:
        self.patterns.append(pattern)
        self.handlers[pattern] = handler



def _canary_selector(workflow_source: str):
    """Rebuild the canary's changed-file selector from its AST.

    The workflow writes the selector as one Python assignment inside a heredoc
    over the PR's changed-file paths.  Parsing it into prefix clauses and exact
    path clauses keeps the contract independent of the literal form -- both
    ``p == 'x'`` and ``p in ('x', 'y')`` are accepted -- without executing
    workflow code.
    """
    assignments = [
        line.strip()
        for line in workflow_source.splitlines()
        if line.strip().startswith("hit=")
    ]
    if len(assignments) != 1:
        raise AssertionError(
            f"expected exactly one selector assignment, got {len(assignments)}"
        )
    body = ast.parse(assignments[0][len("hit="):], mode="eval").body
    if not isinstance(body, ast.BoolOp) or not isinstance(body.op, ast.Or):
        raise AssertionError("the selector must be an `or` of scope clauses")

    prefixes: set[str] = set()
    exacts: set[str] = set()
    fanout = None
    for node in ast.walk(body):
        if isinstance(node, ast.Compare):
            left = node.left
            is_len_rows = (
                isinstance(left, ast.Call)
                and isinstance(left.func, ast.Name)
                and left.func.id == "len"
                and isinstance(left.args[0], ast.Name)
                and left.args[0].id == "rows"
            )
            if is_len_rows and isinstance(node.ops[0], ast.GtE):
                fanout = node.comparators[0].value
                continue
            if not (isinstance(left, ast.Name) and left.id == "p"):
                continue
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
                    exacts.add(comparator.value)
                elif isinstance(op, ast.In) and isinstance(comparator, ast.Tuple):
                    for element in comparator.elts:
                        if not isinstance(element, ast.Constant):
                            raise AssertionError("non-literal path in the selector")
                        exacts.add(element.value)
                else:
                    raise AssertionError(f"unsupported clause on p: {ast.dump(node)}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "startswith"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "p"
        ):
            prefixes.add(node.args[0].value)

    if not prefixes or not exacts or not isinstance(fanout, int):
        raise AssertionError(
            f"incomplete selector: prefixes={sorted(prefixes)} exacts={sorted(exacts)} fanout={fanout}"
        )

    def select(paths):
        paths = set(paths)
        if len(paths) >= fanout:
            return True
        return any(
            any(p.startswith(prefix) for prefix in prefixes) or p in exacts for p in paths
        )

    return select


class GlassZoomPauseClockContract(unittest.TestCase):
    def test_the_wheel_dispatch_returns_the_page_clock_of_the_dispatch(self):
        source = ZOOM.read_text(encoding="utf-8")
        tree = ast.parse(source)
        wheel = _function(tree, "_wheel_up")
        # The wheel is dispatched and the clock is read in one in-page
        # evaluation, and the function returns that timestamp.
        returns = [node for node in ast.walk(wheel) if isinstance(node, ast.Return)]
        self.assertTrue(returns, "the wheel dispatch must return the page clock")
        returned = returns[0].value
        if isinstance(returned, ast.Await):
            returned = returned.value
        self.assertIsInstance(returned, ast.Call)
        self.assertEqual(returned.func.attr, "evaluate")
        expression = returned.args[0]
        self.assertIsInstance(expression, ast.Constant)
        body = expression.value
        self.assertIn("dispatchEvent", body)
        self.assertIn("performance.now()", body)
        # The clock read must happen inside the same evaluation as the
        # dispatch, not in a separate host round trip.
        self.assertEqual(body.count("performance.now()"), 1)

    def test_the_pause_window_starts_at_the_wheel_dispatch_clock(self):
        source = ZOOM.read_text(encoding="utf-8")
        tree = ast.parse(source)
        motion = _function(tree, "_assert_conversation_motion")
        wheels = [
            node
            for node in ast.walk(motion)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_wheel_up"
        ]
        self.assertEqual(len(wheels), 1, "the scroll-up wheel must be dispatched once")
        # The dispatch result is bound to the measurement start.
        assigned = [
            node
            for node in ast.walk(motion)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "wheel_observed"
                for target in node.targets
            )
        ]
        self.assertEqual(len(assigned), 1)
        value = assigned[0].value
        if isinstance(value, ast.Await):
            value = value.value
        self.assertIsInstance(value, ast.Call)
        self.assertEqual(value.func.id, "_wheel_up")
        # The settle measurement uses that timestamp as its start.
        starts = [
            node
            for node in ast.walk(motion)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "wait_state_settled"
        ]
        self.assertTrue(starts)
        start = next(
            keyword.value
            for keyword in starts[0].keywords
            if keyword.arg == "started_ms"
        )
        self.assertIsInstance(start, ast.Name)
        self.assertEqual(start.id, "wheel_observed")

    def test_the_pause_budget_is_unchanged(self):
        source = ZOOM.read_text(encoding="utf-8")
        self.assertIn("lo_ms=0,", source)
        self.assertIn("hi_ms=200,", source)
        self.assertIn("hi_ms=2_500,", source)
        # The suite keeps every original assertion.
        for message in (
            "user scroll-up did not pause auto-follow",
            "DOM growth resumed follow while user was reading history",
            "viewport moved while auto-follow was paused",
            "latest-answer growth was not followed",
        ):
            self.assertIn(message, source)


class GlassZoomAnswerSourceContract(unittest.TestCase):
    """The answer must not be a live server round trip inside the measurement.

    COM2 run 39498783280 failed the Glass Zoom suite exactly at the suite's
    unchanged 15 s answer wait (``Page.wait_for_function: Timeout 15000ms
    exceeded``) on the 1-CPU offline container, while the identical suite
    passes on the 2-core hosted lane at the same head (21.77 s,
    ``B62_VISUAL_TAIL_FAIL_COUNT=0``).  The suite measures the conversation
    motion clock, so the answer is served from the same kind of in-page route
    mock the sibling suites already use.  The wait budget, the predicate, the
    real clicks and the 200 ms / 2500 ms thresholds stay untouched.
    """

    def test_the_answer_is_served_by_an_in_page_route_mock(self):
        page = _FakePage()
        requests: list[dict] = []
        asyncio.run(zoom._install_preview_stream(page, requests))
        self.assertEqual(page.patterns, ["**/api/chat/stream"])
        route = _FakeRoute('{"mode": "auto", "messages": []}')
        asyncio.run(page.handlers["**/api/chat/stream"](route))
        self.assertEqual(route.status, 200)
        self.assertTrue(str(route.content_type).startswith("text/event-stream"))
        body = str(route.body)
        # The mock runtime's own SSE frame shape.
        self.assertIn("event: delta\n", body)
        self.assertIn("event: done\n", body)
        delta = json.loads(body.split("event: delta\ndata: ", 1)[1].split("\n\n", 1)[0])
        self.assertIn(PREVIEW_MARKER, delta["delta"])
        done = json.loads(body.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0])
        self.assertTrue(done["done"])
        # The product's own chat request is still the request that is answered.
        self.assertEqual(requests, [{"mode": "auto", "messages": []}])

    def test_the_mocked_answer_carries_the_text_the_wait_requires(self):
        source = ZOOM.read_text(encoding="utf-8")
        # The answered text and the waited-for text are the same marker, so the
        # wait can still succeed without the live server.
        self.assertIn(PREVIEW_MARKER, zoom.PREVIEW_ANSWER)
        self.assertIn(PREVIEW_MARKER, source)

    def test_the_answer_wait_budget_and_predicate_are_unchanged(self):
        source = ZOOM.read_text(encoding="utf-8")
        # The 15 s budget is not relaxed; only the answer's origin changed.
        self.assertEqual(_preview_wait_budget(source), 15_000)
        predicate = _preview_wait_call(source).args[0].value
        self.assertIn(PREVIEW_MARKER, predicate)
        self.assertIn("#messageList .assistant-content", predicate)
        # The real click on the send button stays a click.
        order = _capture_order(source)
        self.assertGreaterEqual(order["install"], 0)
        self.assertGreaterEqual(order["send"], 0)

    def test_the_route_mock_is_installed_before_the_send(self):
        source = ZOOM.read_text(encoding="utf-8")
        order = _capture_order(source)
        self.assertGreaterEqual(order["install"], 0, "the answer route mock must be installed")
        self.assertGreaterEqual(order["send"], 0, "the real send click must stay")
        self.assertLess(order["install"], order["send"])

    def test_the_send_waits_for_the_composer_interaction_surface(self):
        source = ZOOM.read_text(encoding="utf-8")
        order = _capture_order(source)
        self.assertGreaterEqual(order["readiness"], 0, "the composer readiness wait must exist")
        self.assertLess(order["readiness"], order["send"])

    def test_the_send_click_does_not_wait_for_a_navigation(self):
        # The product's send is a fetch and performs no navigation, so the
        # click must not wait for one: Playwright's generic post-click
        # navigation wait consumed the whole 30 s click budget on the 1-CPU
        # COM2 lane (run 39514816394).  The click itself stays a real click.
        source = ZOOM.read_text(encoding="utf-8")
        click = _send_click(source)
        keywords = {keyword.arg: keyword.value for keyword in click.keywords}
        self.assertIn("no_wait_after", keywords)
        self.assertIs(keywords["no_wait_after"].value, True)

    def test_a_failure_carries_the_page_diagnostic(self):
        # The COM2 runner keeps only the last log lines, so the failure text
        # itself has to carry the page state.
        source = ZOOM.read_text(encoding="utf-8")
        self.assertIn("ZOOM_DIAG=", source)
        self.assertIn("_attach_diagnostic(exc,", source)

    def test_mutations_are_detected(self):
        source = ZOOM.read_text(encoding="utf-8")
        # 1. A widened answer budget is detected.
        widened = source.replace("timeout=15_000,", "timeout=30_000,")
        self.assertNotEqual(widened, source)
        self.assertNotEqual(_preview_wait_budget(widened), 15_000)

        # 2. A removed route-mock install is detected.
        removed = source.replace("    await _install_preview_stream(page, chat_requests)\n", "")
        self.assertNotEqual(removed, source)
        self.assertEqual(_capture_order(removed)["install"], -1)

        # 3. A removed composer readiness wait is detected.
        no_readiness = source.replace(
            '    await page.wait_for_function("() => Boolean(window.PadiemChatInteractionPresentation)")\n',
            "",
        )
        self.assertNotEqual(no_readiness, source)
        self.assertEqual(_capture_order(no_readiness)["readiness"], -1)

        # 4. A click that waits for a navigation again is detected.
        waits = source.replace("click(no_wait_after=True)", "click()")
        self.assertNotEqual(waits, source)
        self.assertNotIn("no_wait_after", {k.arg for k in _send_click(waits).keywords})

        # 5. An answer that lost the preview marker is detected, because the
        #    wait could then never succeed.
        with patch.object(zoom, "PREVIEW_ANSWER", "답변이 아직 준비되지 않았습니다."):
            payload = zoom._preview_stream_payload()
        self.assertNotIn(PREVIEW_MARKER, payload)

        # 6. A wait predicate that no longer watches the assistant content is
        #    detected: the wait would observe the wrong surface.
        changed = source.replace("#messageList .assistant-content", "#messageList .user-content")
        self.assertNotEqual(changed, source)
        self.assertNotIn(
            "#messageList .assistant-content",
            _preview_wait_call(changed).args[0].value,
        )


class VisualTailFailureEvidenceContract(unittest.TestCase):
    def test_all_three_suites_and_the_failure_fan_in_are_unchanged(self):
        self.assertEqual(
            tail.SCRIPTS,
            (
                "b62_glass_shell_visual_qa.py",
                "b62_glass_zoom_visual_qa.py",
                "b62_chat_gutter_visual_qa.py",
            ),
        )
        self.assertEqual(tail.MAX_PARALLEL, 1)
        self.assertEqual(tail.TIMEOUT_SECONDS, 240)

    def test_a_failing_suite_repeats_its_evidence_after_every_suite_printed(self):
        source = TAIL.read_text(encoding="utf-8")
        self.assertIn("B62_VISUAL_TAIL_FAILURE=", source)
        self.assertIn("B62_VISUAL_TAIL_FAILURE_LINE=", source)
        # The repeated failure evidence must be printed after the per-case
        # block, so it lands inside the COM2 runner's bounded log window.
        failure_block = source.index("B62_VISUAL_TAIL_FAILURE=")
        case_block = source.index("B62_VISUAL_TAIL_CASE=")
        self.assertLess(case_block, failure_block)
        self.assertLess(failure_block, source.index("B62_VISUAL_TAIL_EXECUTED="))

    def test_the_repeated_evidence_carries_the_assertion_text(self):
        printed: list[str] = []

        results = [
            ("b62_glass_shell_visual_qa.py", 0, 10.0, "shell PASS\n"),
            (
                "b62_glass_zoom_visual_qa.py",
                1,
                20.0,
                "Traceback (most recent call last):\n"
                "AssertionError: user scroll-up did not pause auto-follow at zoom\n",
            ),
            ("b62_chat_gutter_visual_qa.py", 0, 5.0, "gutter PASS\n"),
        ]
        original = tail.execute
        tail.execute = lambda name: next(r for r in results if r[0] == name)
        try:
            import io
            import os
            from contextlib import redirect_stdout

            buffer = io.StringIO()
            with patch.dict(os.environ, {"PADIEM_CHAT_RUNTIME_MODE": "mock"}):
                with redirect_stdout(buffer):
                    self.assertEqual(tail.main(), 1)
            printed.append(buffer.getvalue())
        finally:
            tail.execute = original
        output = "".join(printed)
        self.assertIn("B62_VISUAL_TAIL_STATUS_b62_glass_zoom_visual_qa.py=FAIL", output)
        self.assertIn("B62_VISUAL_TAIL_FAILURE=b62_glass_zoom_visual_qa.py", output)
        self.assertIn(
            "B62_VISUAL_TAIL_FAILURE_LINE=AssertionError: user scroll-up did not pause auto-follow at zoom",
            output,
        )
        self.assertIn("B62_VISUAL_TAIL_EXECUTED=3", output)
        self.assertIn("B62_VISUAL_TAIL_FAIL_COUNT=1", output)
        # The failure evidence is repeated after every suite printed, so it
        # survives a bounded diagnostic window.
        self.assertLess(
            output.index("B62_VISUAL_TAIL_CASE=b62_glass_shell_visual_qa.py"),
            output.index("B62_VISUAL_TAIL_FAILURE=b62_glass_zoom_visual_qa.py"),
        )
        self.assertLess(
            output.index("B62_VISUAL_TAIL_FAILURE=b62_glass_zoom_visual_qa.py"),
            output.index("B62_VISUAL_TAIL_EXECUTED=3"),
        )


class VisualTailScopeSelectionContract(unittest.TestCase):
    """A change to a lane's own script must select that lane.

    The generic Browser lane runs the visual-tail suites itself, so a change
    to one of them has to select the hosted Browser QA lane and the COM2
    Generic Browser canary.  The hosted planner covers the lane-owned suites
    through PLAN_FILES, and the COM2 canary through its changed-file filter.
    """

    LANE_SCRIPTS = (
        ".github/scripts/b62_browser_visual_qa.py",
        ".github/scripts/b62_glass_shell_visual_qa.py",
        ".github/scripts/b62_glass_zoom_visual_qa.py",
        ".github/scripts/b62_chat_gutter_visual_qa.py",
        ".github/scripts/b62_browser_qa_tail_parallel.py",
    )

    def test_the_hosted_planner_selects_every_lane_for_a_lane_script_change(self):
        source = PLANNER.read_text(encoding="utf-8")
        for script in self.LANE_SCRIPTS:
            self.assertIn(f'"{script}"', source, script)

    def test_the_com2_generic_browser_canary_selects_its_own_scripts(self):
        selector = _canary_selector(CANARY.read_text(encoding="utf-8"))
        for script in self.LANE_SCRIPTS:
            self.assertTrue(selector({script}), script)
            self.assertTrue(selector({script, "docs/README.md"}), script)
        # #5425 added the lane contract test itself, so a QA-only change to it
        # still selects the canary.
        self.assertTrue(selector({CONTRACT_TEST}), CONTRACT_TEST)
        # The existing product-surface clauses stay in place.
        self.assertTrue(selector({"apps/padiem-chat/static/app.css"}))
        self.assertTrue(selector({"packages/padiem-ai-core/x.py"}))
        self.assertTrue(selector({"packages/padiem-control-plane/x.py"}))
        self.assertTrue(selector({"apps/korean-ai-code-agent/x.py"}))
        self.assertTrue(selector({"apps/padiem-ai-engine/clients/python/x.py"}))
        # A change outside the lane does not select it.
        self.assertFalse(selector({"apps/padiem-ai-engine/app/main.py"}))
        self.assertFalse(selector({"docs/operations/NOTE.md"}))

    def test_the_canary_still_requires_an_open_same_repository_pr_head(self):
        source = CANARY.read_text(encoding="utf-8")
        self.assertIn("p['state']=='open'", source)
        self.assertIn("p['head']['sha']==sha", source)
        self.assertIn("p['head']['repo']['full_name']==repo", source)


if __name__ == "__main__":
    unittest.main()
