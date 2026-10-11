"""#3566 / #3382 — an explicitly selected model id must reach the Engine wire unchanged.

The identifiers below are inert, test-only strings chosen only to satisfy the P01
*grammar* gate. P01 and the Engine validate syntax; B14's catalog stays the later
availability authority, so nothing here asserts that a model is registered,
selectable, or owner-approved, and nothing is added to any catalog or tier
declaration. Every transport is a fake: no provider, no Engine, no network.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import unittest

from padiem_ai_core.b14_execution import B14RouteMetadata
from padiem_ai_core.contracts import RunMetadata, RunStatus
from padiem_ai_core.execution_runtime import ExecutionResult, _normalize_model_policy
from padiem_ai_core.orchestration import OrchestrationResult
from padiem_ai_core.orchestration_events import (
    OrchestrationEventKind,
    public_orchestration_event,
)
from padiem_ai_engine_client import EngineTransportResponse, PadiemAiEngineClient
from padiem_control_plane.product_tier_routes import ProductTierLabel

from kagent.contracts import ClawTaskIntent, ExecutionMode
from kagent.p01_adapter import (
    P01_AGENT_ID,
    P01_APP_ID,
    P01AdapterError,
    P01DispatchClass,
    P01RequestFactory,
)
from kagent.p01_orchestration_client import P01EngineOrchestrationClient
from kagent.runs import ClawRun

from model_route_fixture import SyntheticPlusRouteTestCase

_FAKE_CREDENTIAL = "b54-test-credential-" + ("0" * 32)
_RUN_ID = "run_p01_explicit_model"

# Two deliberately different shapes (dotted + hyphen vs colon + underscore + two
# slashes) so a green run cannot come from one literal the port happens to echo.
INERT_EXPLICIT_MODEL_IDS = (
    "testowner/example-model.v1",
    "z9/provider:route_second/2",
)


class _FakeEngineTransport:
    """Network-free transport: records the exact bytes sent, replays a canned response."""

    def __init__(self, response: EngineTransportResponse) -> None:
        self._response = response
        self.requests: list[dict] = []

    async def request(self, *, method, url, headers, body):
        self.requests.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body}
        )
        return self._response


def _new_run() -> ClawRun:
    intent = ClawTaskIntent(
        task_id="task_p01_explicit_model",
        task="명시 모델 전달을 검증해줘",
        repository_ref="skerishKang/example",
        execution_mode=ExecutionMode.LOCAL,
    )
    return ClawRun.create(_RUN_ID, intent)


def _build(*, selected_model_id=None, product_tier=ProductTierLabel.PLUS):
    return P01RequestFactory(product_tier=product_tier).build(
        _new_run(),
        product_tier=product_tier,
        selected_model_id=selected_model_id,
    )


def _success_body(request) -> dict:
    kinds = (
        OrchestrationEventKind.RUN_STARTED,
        OrchestrationEventKind.CONTEXT_PREPARED,
        OrchestrationEventKind.RUN_COMPLETED,
    )
    events = [
        public_orchestration_event(
            event_id=f"evt_{sequence:03d}",
            run_id=_RUN_ID,
            trace_id=request.context.trace_id,
            app_id=request.app_id,
            kind=kind,
            sequence=sequence,
            message=None,
            timestamp_iso="2026-09-05T10:00:00+00:00",
        )
        for sequence, kind in enumerate(kinds, start=1)
    ]
    return OrchestrationResult(
        execution_result=ExecutionResult(
            answer="완료 답변",
            route=B14RouteMetadata(),
            metadata=RunMetadata(
                trace_id=request.context.trace_id,
                app_id=request.app_id,
                agent_id=P01_AGENT_ID,
                session_id=request.execution_request.session_id,
                status=RunStatus.COMPLETED,
            ),
        ),
        context=request.context,
        app_id=request.app_id,
        subject_id=None,
        plan=None,
        activated_skill=None,
        resolved_tool_ids=(),
        evidence_graph=None,
        claim_assessments=(),
        grounded_citations=(),
        events=tuple(events),
    ).to_public_dict()


def _send(bundle, *, policy_override=None):
    """Drive the real P01 wire serializer against the fake transport.

    Returns the transport and, when the port legitimately refuses, the refusal.
    Any other failure propagates instead of being reported as a refusal.
    """

    request = bundle.orchestration_request
    if policy_override is not None:
        agent = replace(request.execution_request.agent, model_policy=policy_override)
        request = replace(
            request, execution_request=replace(request.execution_request, agent=agent)
        )
    transport = _FakeEngineTransport(
        EngineTransportResponse(
            status=200,
            body=json.dumps(
                {"ok": True, "orchestration": _success_body(request)}, ensure_ascii=False
            ).encode("utf-8"),
        )
    )
    port = P01EngineOrchestrationClient(
        PadiemAiEngineClient(
            transport=transport,
            app_id=P01_APP_ID,
            caller_id="b54-kagent",
            credential=_FAKE_CREDENTIAL,
        )
    )
    try:
        asyncio.run(port.run(request))
    except P01AdapterError as refusal:
        return transport, refusal
    return transport, None


class P01ExplicitModelPropagationTests(SyntheticPlusRouteTestCase):
    def test_explicit_selection_replaces_the_route_derived_default(self) -> None:
        default_model = _build().execution_request.agent.model_policy["model"]
        self.assertEqual(default_model, self.plus_route_model)

        for model_id in INERT_EXPLICIT_MODEL_IDS:
            with self.subTest(model_id=model_id):
                agent = _build(selected_model_id=model_id).execution_request.agent
                self.assertEqual(agent.model_policy, {"model": model_id, "max_retries": 0})
                self.assertNotEqual(agent.model_policy["model"], default_model)
                # Core consumes the exact string: stripped, never defaulted or rewritten.
                model, _temperature, routing = _normalize_model_policy(agent)
                self.assertEqual(model, model_id)
                self.assertEqual(routing.max_retries, 0)

    def test_explicit_selection_reaches_the_engine_wire_byte_exact(self) -> None:
        for model_id in INERT_EXPLICIT_MODEL_IDS:
            with self.subTest(model_id=model_id):
                transport, refusal = _send(_build(selected_model_id=model_id))
                self.assertIsNone(refusal)
                self.assertEqual(len(transport.requests), 1)
                payload = json.loads(transport.requests[0]["body"].decode("utf-8"))
                self.assertEqual(
                    payload["agent"]["model_policy"], {"model": model_id, "max_retries": 0}
                )
                self.assertEqual(payload["agent"]["id"], P01_AGENT_ID)
                self.assertNotIn("b14/auto", json.dumps(payload).lower())

    def test_syntax_only_admission_does_not_claim_registration(self) -> None:
        # The executable set the fixture installs holds the Plus identity only, so
        # these ids are admitted by grammar. Availability stays B14's decision, and
        # the port must not silently swap in the default route.
        for model_id in INERT_EXPLICIT_MODEL_IDS:
            with self.subTest(model_id=model_id):
                self.assertNotEqual(model_id, self.plus_route_model)
                transport, refusal = _send(_build(selected_model_id=model_id))
                self.assertIsNone(refusal)
                self.assertEqual(len(transport.requests), 1)
                payload = json.loads(transport.requests[0]["body"].decode("utf-8"))
                self.assertEqual(payload["agent"]["model_policy"]["model"], model_id)

    def test_invalid_explicit_selection_is_refused_before_any_request(self) -> None:
        for bad_id in (
            "b14/auto",
            "padiem-profile/plus",
            "bad id with spaces",
            "",
            "x" * 200,
        ):
            with self.subTest(model_id=bad_id):
                with self.assertRaises(P01AdapterError) as ctx:
                    _build(selected_model_id=bad_id)
                self.assertEqual(ctx.exception.code, "invalid_selected_model")
                self.assertEqual(
                    ctx.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED
                )

    def test_explicit_choice_on_a_non_plus_tier_is_refused_without_dispatch(self) -> None:
        for tier in (ProductTierLabel.PRO, ProductTierLabel.MAX):
            with self.subTest(tier=tier.value):
                with self.assertRaises(P01AdapterError) as ctx:
                    _build(selected_model_id=INERT_EXPLICIT_MODEL_IDS[0], product_tier=tier)
                self.assertEqual(ctx.exception.code, "explicit_model_tier_unsupported")
                self.assertEqual(
                    ctx.exception.dispatch_class, P01DispatchClass.NOT_DISPATCHED
                )

    def test_core_legal_extra_policy_field_is_pinned_out_of_the_p01_wire(self) -> None:
        # temperature/provider_order/max_attempts are legal model_policy fields for
        # Core but routing authority the P01 wire refuses; the refusal must happen
        # before a single Engine request exists.
        for model_id in INERT_EXPLICIT_MODEL_IDS:
            for override in (
                {"model": model_id, "max_retries": 0, "temperature": 0.7},
                {"model": model_id, "max_retries": 0, "provider_order": ["test"]},
                {"model": model_id, "max_retries": 0, "max_attempts": 3},
            ):
                with self.subTest(model_id=model_id, policy=sorted(override)):
                    transport, refusal = _send(
                        _build(selected_model_id=model_id), policy_override=override
                    )
                    self.assertIsNotNone(refusal)
                    self.assertEqual(refusal.code, "p01_authority_pinning")
                    self.assertEqual(refusal.dispatch_class, P01DispatchClass.NOT_DISPATCHED)
                    self.assertEqual(transport.requests, [])


if __name__ == "__main__":
    unittest.main()
