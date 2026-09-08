"""Tests for the promoted Core cancellation teardown barrier (#1540).

Covers the promoted contract acceptance points:
1. cancellation binds exactly one execution key
2. cancellation forces teardown as the only permitted next transition
3. forward/output transitions are prohibited after cancellation
4. exact cancellation replay is idempotent; conflicting replay is rejected
5. terminal execution rejects new cancellation
6. teardown cannot be skipped; success -> CANCELLED_CLEANED_UP,
   failure -> TEARDOWN_FAILED
7. no P01 cancellation authority is minted; no auto resume/retry/redispatch
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import padiem_ai_core
from padiem_ai_core.cancellation_barrier import (
    TEARDOWN_TRANSITION,
    CancellationBarrier,
    CancellationBarrierError,
    CancellationBarrierState,
    CancellationProjection,
    is_terminal_barrier_state,
)

MODULE_PATH = Path(__file__).resolve().parent.parent / "padiem_ai_core" / "cancellation_barrier.py"

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def barrier(key: str = "exec_run_1") -> CancellationBarrier:
    return CancellationBarrier(execution_key=key)


def cancel(target: CancellationBarrier, **overrides):
    values = {
        "cancellation_ref": "cancel_1",
        "execution_key": target.execution_key,
        "observed_at": NOW,
    }
    values.update(overrides)
    return target.request_cancellation(**values)


class TestPackageRootExport:
    def test_package_root_exports_cancellation_barrier_facade(self) -> None:
        assert padiem_ai_core.CancellationBarrier is CancellationBarrier
        assert padiem_ai_core.CancellationBarrierError is CancellationBarrierError
        assert padiem_ai_core.CancellationBarrierState is CancellationBarrierState
        assert padiem_ai_core.CancellationProjection is CancellationProjection
        assert padiem_ai_core.TEARDOWN_TRANSITION == "teardown"
        assert padiem_ai_core.is_terminal_barrier_state is is_terminal_barrier_state


class TestCancellationForcesTeardown:
    def test_cancel_before_work_forces_teardown(self) -> None:
        target = barrier()
        projection = cancel(target)

        assert projection.state is CancellationBarrierState.AWAITING_TEARDOWN
        assert projection.next_transition == TEARDOWN_TRANSITION
        assert projection.cancellation_ref == "cancel_1"
        assert target.state is CancellationBarrierState.AWAITING_TEARDOWN
        assert target.is_terminal is False

        final = target.record_teardown(succeeded=True)
        assert final.state is CancellationBarrierState.CANCELLED_CLEANED_UP
        assert final.terminal == "cancelled_cleaned_up"
        assert final.next_transition is None
        assert target.is_terminal is True

    def test_teardown_after_progress_still_reaches_clean_terminal(self) -> None:
        target = barrier()
        target.guard_transition(kind="forward_work")
        target.guard_transition(kind="output_publish")
        cancel(target, observed_at=NOW + timedelta(seconds=3))

        final = target.record_teardown(succeeded=True)
        assert final.state is CancellationBarrierState.CANCELLED_CLEANED_UP

    def test_teardown_failure_after_cancel_is_visible(self) -> None:
        target = barrier()
        cancel(target)

        final = target.record_teardown(succeeded=False)
        assert final.state is CancellationBarrierState.TEARDOWN_FAILED
        assert final.terminal == "teardown_failed"
        assert target.is_terminal is True

    def test_teardown_cannot_be_skipped_or_repeated(self) -> None:
        target = barrier()
        with pytest.raises(CancellationBarrierError) as info:
            target.record_teardown(succeeded=True)
        assert info.value.code == "teardown_without_cancellation"

        cancel(target)
        target.record_teardown(succeeded=True)
        with pytest.raises(CancellationBarrierError) as repeat:
            target.record_teardown(succeeded=True)
        assert repeat.value.code == "teardown_without_cancellation"


class TestPostCancelOutputProhibited:
    @pytest.mark.parametrize("kind", ["forward_work", "output_publish", "verification", "artifact"])
    def test_forward_output_kinds_rejected_after_cancel(self, kind: str) -> None:
        target = barrier()
        cancel(target)
        with pytest.raises(CancellationBarrierError) as info:
            target.guard_transition(kind=kind)
        assert info.value.code == "post_cancel_output_prohibited"

    def test_teardown_kind_permitted_after_cancel(self) -> None:
        target = barrier()
        cancel(target)
        target.guard_transition(kind="teardown")

    def test_terminal_rejects_every_transition(self) -> None:
        target = barrier()
        cancel(target)
        target.record_teardown(succeeded=True)
        for kind in ("teardown", "forward_work"):
            with pytest.raises(CancellationBarrierError) as info:
                target.guard_transition(kind=kind)
            assert info.value.code == "terminal_transition_rejected"


class TestCorrelationAndReplay:
    def test_exact_replay_is_idempotent(self) -> None:
        target = barrier()
        first = cancel(target)
        replay = cancel(target)
        assert first == replay
        assert target.state is CancellationBarrierState.AWAITING_TEARDOWN

    def test_conflicting_ref_rejected(self) -> None:
        target = barrier()
        cancel(target)
        with pytest.raises(CancellationBarrierError) as info:
            cancel(target, cancellation_ref="cancel_2")
        assert info.value.code == "conflicting_cancellation"

    def test_same_ref_different_moment_rejected(self) -> None:
        target = barrier()
        cancel(target)
        with pytest.raises(CancellationBarrierError) as info:
            cancel(target, observed_at=NOW + timedelta(seconds=1))
        assert info.value.code == "conflicting_cancellation"

    def test_wrong_execution_key_rejected(self) -> None:
        target = barrier()
        with pytest.raises(CancellationBarrierError) as info:
            cancel(target, execution_key="exec_other")
        assert info.value.code == "cancellation_correlation_mismatch"
        assert target.state is CancellationBarrierState.ACTIVE
        assert target.cancellation_ref is None

    def test_post_terminal_cancel_rejected(self) -> None:
        cleaned = barrier("exec_clean")
        cancel(cleaned)
        cleaned.record_teardown(succeeded=True)
        with pytest.raises(CancellationBarrierError) as info:
            cancel(cleaned, observed_at=NOW + timedelta(seconds=5))
        assert info.value.code == "terminal_cancellation_rejected"

        failed = barrier("exec_failed")
        cancel(failed)
        failed.record_teardown(succeeded=False)
        with pytest.raises(CancellationBarrierError) as failed_info:
            cancel(failed, observed_at=NOW + timedelta(seconds=5))
        assert failed_info.value.code == "terminal_cancellation_rejected"


class TestInputValidation:
    def test_unsafe_execution_key_rejected(self) -> None:
        with pytest.raises(CancellationBarrierError) as info:
            CancellationBarrier(execution_key="not a key!")
        assert info.value.code == "invalid_execution_key"

    def test_unsafe_cancellation_ref_rejected(self) -> None:
        target = barrier()
        with pytest.raises(CancellationBarrierError):
            cancel(target, cancellation_ref="cancel 1!")

    def test_naive_observed_at_rejected(self) -> None:
        target = barrier()
        with pytest.raises(CancellationBarrierError) as info:
            cancel(target, observed_at=datetime(2026, 9, 8, 12, 0))
        assert info.value.code == "invalid_observed_at"

    def test_non_boolean_teardown_outcome_rejected(self) -> None:
        target = barrier()
        cancel(target)
        with pytest.raises(CancellationBarrierError) as info:
            target.record_teardown(succeeded="yes")  # type: ignore[arg-type]
        assert info.value.code == "invalid_teardown_outcome"


class TestNoAuthorityExpansion:
    def test_public_dict_claims_no_p01_authority_and_no_automation(self) -> None:
        rendered = barrier().projection().to_public_dict()
        assert rendered["p01_cancellation_authority"] is False
        assert rendered["post_cancellation_output_supported"] is False
        assert rendered["automatic_resume"] is False
        assert rendered["automatic_retry"] is False
        assert rendered["automatic_redispatch"] is False

    def test_barrier_exposes_no_resume_retry_redispatch(self) -> None:
        target = barrier()
        assert not hasattr(target, "resume")
        assert not hasattr(target, "retry")
        assert not hasattr(target, "redispatch")
        assert not hasattr(target, "mint_p01_cancellation")


class TestModulePurity:
    def test_no_io_or_connector_calls(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        call_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    call_names.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    call_names.append(node.func.attr)
        forbidden = {"request", "fetch", "connect", "open", "write", "delete", "unlink"}
        found = sorted(forbidden & set(call_names))
        assert not found, f"module must not call IO/connector operations: {found}"

    def test_no_product_or_provider_authority(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8").lower()
        for token in (
            "cloud_m1", "cloudm1", "b54", "draft_pr", "draft-pr",
            "sandbox_provider", "repository_ref", "workspace",
            "model_policy", "routing", "credential", "secret",
        ):
            assert token not in source, f"module must not carry product/provider term: {token}"

    def test_no_p01_cancellation_minting(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert "p01" not in node.name.lower()

    def test_module_imports_only_allowed_packages(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    imports.append(node.module.split(".")[0])
        allowed = {"__future__", "dataclasses", "datetime", "enum", "re", "typing"}
        unexpected = sorted(set(imports) - allowed)
        assert not unexpected, f"unexpected imports: {unexpected}"

    def test_terminal_states_are_exactly_the_two_contract_terminals(self) -> None:
        assert is_terminal_barrier_state(CancellationBarrierState.CANCELLED_CLEANED_UP)
        assert is_terminal_barrier_state(CancellationBarrierState.TEARDOWN_FAILED)
        assert not is_terminal_barrier_state(CancellationBarrierState.ACTIVE)
        assert not is_terminal_barrier_state(CancellationBarrierState.AWAITING_TEARDOWN)
