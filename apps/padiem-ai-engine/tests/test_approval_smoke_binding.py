"""Canonical provider-free approval pause/resume fixture tests (#3317).

Network-free. These tests exercise the real Core ToolRuntime approval block,
Engine continuation issuance, first-party decision verifier, #3318 exact Tool
authorization delta, and resumed ToolRuntime execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from padiem_ai_core import (
    ApprovalOutcome,
    ToolInvocation,
    ToolRuntimeError,
)

from app.approval_smoke_binding import (
    APPROVAL_SMOKE_AGENT_ID,
    APPROVAL_SMOKE_APP_ID,
    APPROVAL_SMOKE_CANONICAL_TOOL_ID,
    APPROVAL_SMOKE_ENABLE_ENV,
    APPROVAL_SMOKE_RUNTIME_TOOL_ID,
    approval_smoke_tool_spec,
    build_approval_smoke_binding,
    with_approval_smoke_binding,
)
from app.approval_verifier import (
    AuthenticatedFirstPartyApprovalDecisionVerifier,
)
from app.orchestration_continuation import InMemoryContinuationStore
from app.orchestration_service import OrchestrationEngineService


def _run_payload(binding) -> dict:
    authority = binding.resolve_authority(APPROVAL_SMOKE_AGENT_ID)
    profile = authority.compiled.runtime_profile
    return {
        "app_id": APPROVAL_SMOKE_APP_ID,
        "agent": {
            "id": profile.id,
            "title": profile.title,
            "description": profile.description,
            "system_instruction": profile.system_instruction,
            "task_type": profile.task_type,
            "optimize_for": profile.optimize_for,
            "max_tokens": profile.max_tokens,
            "model_policy": {"model": "test/provider-free"},
        },
        "messages": [
            {
                "role": "user",
                "content": "Run the approval smoke fixture.",
            }
        ],
        "trace_id": "tr_approval_smoke_1",
        "execution_context": {
            "trace_id": "tr_approval_smoke_1",
            "timeout_seconds": 5.0,
        },
        "agent_plan": {
            "agent_id": APPROVAL_SMOKE_AGENT_ID,
            "steps": [
                {
                    "step_id": "step_1",
                    "objective": "Confirm synthetic approval smoke",
                    "tool_id": APPROVAL_SMOKE_RUNTIME_TOOL_ID,
                }
            ],
        },
        "tool_arguments": {
            "step_1": {
                "nonce": "approval-smoke-1",
            }
        },
        "subject_id": "subject:approval-smoke",
        "require_evidence": False,
        "require_verification": False,
    }


def _resume_payload(payload: dict, continuation_ref: str, decision: dict) -> dict:
    """Project the initial run onto the canonical resume wire surface."""
    resumed = {
        key: value
        for key, value in payload.items()
        if key not in {"require_evidence", "require_verification"}
    }
    resumed["continuation_ref"] = continuation_ref
    resumed["decision"] = decision
    return resumed


def _decision(pause, outcome: str = "approved") -> dict:
    # The actual first-party verifier enforces the pause time window.
    decided_at = max(
        pause.created_at,
        datetime.now(timezone.utc),
    )
    if decided_at > pause.expires_at:
        decided_at = pause.created_at
    return {
        "decision_id": "dec_approval_smoke_1",
        "pause_id": pause.pause_id,
        "outcome": outcome,
        "authority_ref": "user:approval-smoke",
        "evidence_ref": "session:approval-smoke",
        "decided_at": decided_at.isoformat(),
    }


class _ProviderBombRuntime:
    async def run(self, _request):
        raise AssertionError("provider/fallback runtime must not run in approval smoke")


def _service(binding):
    store = InMemoryContinuationStore()
    service = OrchestrationEngineService(
        runtime_factory=lambda _app_id: _ProviderBombRuntime(),
        b14_service_bound=True,
        continuation_store=store,
        approval_decision_verifier=(
            AuthenticatedFirstPartyApprovalDecisionVerifier()
        ),
        tool_binding_resolver=lambda app_id: (
            binding if app_id == APPROVAL_SMOKE_APP_ID else None
        ),
    )
    return service, store


def test_smoke_tool_is_provider_free_zero_side_effect_and_requires_confirmation() -> None:
    binding = build_approval_smoke_binding()
    authority = binding.resolve_authority(APPROVAL_SMOKE_AGENT_ID)
    spec = approval_smoke_tool_spec()

    assert spec.side_effect.value == "none"
    assert spec.approval_policy.value == "user_confirmation"
    assert spec.user_visible is False
    assert binding.registry.canonical_tool_ids == (
        APPROVAL_SMOKE_CANONICAL_TOOL_ID,
    )

    with pytest.raises(ToolRuntimeError) as exc:
        import asyncio

        asyncio.run(
            binding.tool_runtime.execute(
                ToolInvocation(
                    tool_id=APPROVAL_SMOKE_RUNTIME_TOOL_ID,
                    arguments={"nonce": "blocked-before-approval"},
                ),
                authority.compiled.runtime_profile,
                authority.authorization,
            )
        )
    assert exc.value.code == "tool_user_confirmation_required"


@pytest.mark.asyncio
async def test_real_toolruntime_pause_to_verified_resume_completes_without_provider() -> None:
    binding = build_approval_smoke_binding()
    service, store = _service(binding)
    payload = _run_payload(binding)

    paused = await service.orchestrate_payload(payload)
    assert paused.status_code == 200
    assert paused.body["ok"] is True
    orch = paused.body["orchestration"]
    assert orch["execution"]["metadata"]["status"] == "paused"
    continuation_ref = orch["continuation_ref"]
    assert continuation_ref.startswith("cont_")

    record = store.resolve(
        app_id=APPROVAL_SMOKE_APP_ID,
        continuation_ref=continuation_ref,
    )
    assert record.pause.tool_id == APPROVAL_SMOKE_RUNTIME_TOOL_ID
    assert record.pause.requirement.value == "user_confirmation"

    resume_payload = _resume_payload(
        payload,
        continuation_ref,
        _decision(record.pause),
    )

    resumed = await service.resume_payload(resume_payload)
    assert resumed.status_code == 200
    assert resumed.body["ok"] is True
    resumed_orch = resumed.body["orchestration"]
    assert resumed_orch["execution"]["metadata"]["status"] == "completed"
    events = resumed_orch["execution"]["metadata"]["tool_events"]
    assert any(
        event["tool_id"] == APPROVAL_SMOKE_RUNTIME_TOOL_ID
        and event["status"] == "completed"
        for event in events
    )

    with pytest.raises(Exception) as consumed:
        store.resolve(
            app_id=APPROVAL_SMOKE_APP_ID,
            continuation_ref=continuation_ref,
        )
    assert getattr(consumed.value, "code", None) == "continuation_consumed"


@pytest.mark.asyncio
async def test_denied_real_pause_is_consumed_without_tool_execution() -> None:
    binding = build_approval_smoke_binding()
    service, store = _service(binding)
    payload = _run_payload(binding)

    paused = await service.orchestrate_payload(payload)
    continuation_ref = paused.body["orchestration"]["continuation_ref"]
    record = store.resolve(
        app_id=APPROVAL_SMOKE_APP_ID,
        continuation_ref=continuation_ref,
    )

    resume_payload = _resume_payload(
        payload,
        continuation_ref,
        _decision(record.pause, outcome="denied"),
    )

    denied = await service.resume_payload(resume_payload)
    assert denied.status_code == 409
    assert denied.body["error"]["code"] == "approval_denied"

    with pytest.raises(Exception) as consumed:
        store.resolve(
            app_id=APPROVAL_SMOKE_APP_ID,
            continuation_ref=continuation_ref,
        )
    assert getattr(consumed.value, "code", None) == "continuation_consumed"


def test_fixture_is_disabled_by_default_and_preserves_existing_resolver_identity() -> None:
    sentinel = object()

    def base(app_id: str):
        return sentinel if app_id == "existing-app" else None

    class EmptyEnv:
        pass

    class ExplicitOff:
        PADIEM_ENGINE_APPROVAL_SMOKE_ENABLED = "0"

    assert with_approval_smoke_binding(EmptyEnv(), base) is base
    assert with_approval_smoke_binding(ExplicitOff(), base) is base


def test_fixture_enable_is_deployment_owned_and_does_not_replace_other_apps() -> None:
    sentinel = object()

    def base(app_id: str):
        return sentinel if app_id == "existing-app" else None

    class Enabled:
        PADIEM_ENGINE_APPROVAL_SMOKE_ENABLED = "1"

    resolver = with_approval_smoke_binding(Enabled(), base)
    assert resolver is not None
    assert resolver(APPROVAL_SMOKE_APP_ID).app_id == APPROVAL_SMOKE_APP_ID
    assert resolver("existing-app") is sentinel
    assert resolver("unknown") is None


def test_current_wrangler_does_not_enable_smoke_fixture() -> None:
    root = Path(__file__).resolve().parents[1]
    config = (root / "wrangler.toml").read_text(encoding="utf-8")
    assert APPROVAL_SMOKE_ENABLE_ENV not in config


def test_fixture_source_has_no_network_provider_or_secret_adapter() -> None:
    source = Path(__file__).resolve().parents[1] / "app" / "approval_smoke_binding.py"
    text = source.read_text(encoding="utf-8").lower()
    for forbidden in (
        "httpx",
        "urllib",
        "fetch(",
        "b14execution",
        "credential",
        "secret",
        "provider_call",
    ):
        assert forbidden not in text
