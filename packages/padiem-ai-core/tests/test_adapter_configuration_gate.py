"""Tests for the external adapter configuration gate (#1567).

Covers the promoted Core contract acceptance points:
1. UNCONFIGURED never satisfies a live gate
2. DETERMINISTIC_FAKE never satisfies a live gate
3. CONNECTED requires issued/expires timestamps and authority-evidence refs
4. stale probes (expired) fail closed
5. future probes (issued ahead of clock) fail closed
6. missing adapters are visible in the result
7. per-capability required adapter sets match the issue definition
8. no real connector calls, no security certification, no deployment approval
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from padiem_ai_core.adapter_configuration_gate import (
    AdapterConfigurationGateError,
    AdapterProbe,
    AdapterProbeState,
    CapabilityGateResult,
    ExternalAdapterKind,
    LiveCapability,
    evaluate_capability_gate,
    required_adapters_for,
)

MODULE_PATH = Path(__file__).resolve().parent.parent / "padiem_ai_core" / "adapter_configuration_gate.py"

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _connected_probe(
    kind: ExternalAdapterKind,
    *,
    issued: datetime = NOW - timedelta(hours=1),
    expires: datetime = NOW + timedelta(hours=23),
    refs: tuple[str, ...] = ("authority:cp_identity@1",),
) -> AdapterProbe:
    return AdapterProbe(
        adapter_kind=kind,
        state=AdapterProbeState.CONNECTED,
        issued_at=issued,
        expires_at=expires,
        authority_evidence_refs=refs,
    )


def _unconfigured_probe(kind: ExternalAdapterKind) -> AdapterProbe:
    return AdapterProbe(adapter_kind=kind, state=AdapterProbeState.UNCONFIGURED)


def _fake_probe(kind: ExternalAdapterKind) -> AdapterProbe:
    return AdapterProbe(adapter_kind=kind, state=AdapterProbeState.DETERMINISTIC_FAKE)


def _stale_probe(kind: ExternalAdapterKind) -> AdapterProbe:
    return AdapterProbe(
        adapter_kind=kind,
        state=AdapterProbeState.CONNECTED,
        issued_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(hours=1),
        authority_evidence_refs=("authority:stale@1",),
    )


def _future_probe(kind: ExternalAdapterKind) -> AdapterProbe:
    return AdapterProbe(
        adapter_kind=kind,
        state=AdapterProbeState.CONNECTED,
        issued_at=NOW + timedelta(hours=2),
        expires_at=NOW + timedelta(days=30),
        authority_evidence_refs=("authority:future@1",),
    )


def _all_connected_probes(kinds: tuple[ExternalAdapterKind, ...]) -> tuple[AdapterProbe, ...]:
    return tuple(_connected_probe(k) for k in kinds)


# ---------------------------------------------------------------------------
# A. Probe construction and validation
# ---------------------------------------------------------------------------


class TestAdapterProbe:
    def test_unconfigured_probe_accepted(self) -> None:
        p = _unconfigured_probe(ExternalAdapterKind.B14_MODEL_EXECUTION)
        assert p.state is AdapterProbeState.UNCONFIGURED
        assert p.issued_at is None

    def test_fake_probe_accepted(self) -> None:
        p = _fake_probe(ExternalAdapterKind.SANDBOX_PROVIDER)
        assert p.state is AdapterProbeState.DETERMINISTIC_FAKE

    def test_connected_probe_with_valid_fields(self) -> None:
        p = _connected_probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY)
        assert p.state is AdapterProbeState.CONNECTED
        assert p.issued_at is not None
        assert p.expires_at is not None
        assert len(p.authority_evidence_refs) == 1

    def test_connected_without_issued_at_rejected(self) -> None:
        with pytest.raises(AdapterConfigurationGateError, match="issued_at"):
            AdapterProbe(
                adapter_kind=ExternalAdapterKind.B14_MODEL_EXECUTION,
                state=AdapterProbeState.CONNECTED,
                expires_at=NOW + timedelta(hours=1),
                authority_evidence_refs=("ref:1",),
            )

    def test_connected_without_expires_at_rejected(self) -> None:
        with pytest.raises(AdapterConfigurationGateError, match="expires_at"):
            AdapterProbe(
                adapter_kind=ExternalAdapterKind.B14_MODEL_EXECUTION,
                state=AdapterProbeState.CONNECTED,
                issued_at=NOW - timedelta(hours=1),
                authority_evidence_refs=("ref:1",),
            )

    def test_connected_without_authority_refs_rejected(self) -> None:
        with pytest.raises(AdapterConfigurationGateError, match="authority_evidence_ref"):
            AdapterProbe(
                adapter_kind=ExternalAdapterKind.B14_MODEL_EXECUTION,
                state=AdapterProbeState.CONNECTED,
                issued_at=NOW - timedelta(hours=1),
                expires_at=NOW + timedelta(hours=1),
            )

    def test_connected_with_naive_timestamps_rejected(self) -> None:
        with pytest.raises(AdapterConfigurationGateError, match="timezone-aware"):
            AdapterProbe(
                adapter_kind=ExternalAdapterKind.B14_MODEL_EXECUTION,
                state=AdapterProbeState.CONNECTED,
                issued_at=datetime(2026, 9, 8, 10, 0),
                expires_at=datetime(2026, 9, 9, 10, 0),
                authority_evidence_refs=("ref:1",),
            )

    def test_connected_with_unsafe_ref_rejected(self) -> None:
        with pytest.raises(AdapterConfigurationGateError, match="safe identifier"):
            AdapterProbe(
                adapter_kind=ExternalAdapterKind.B14_MODEL_EXECUTION,
                state=AdapterProbeState.CONNECTED,
                issued_at=NOW - timedelta(hours=1),
                expires_at=NOW + timedelta(hours=1),
                authority_evidence_refs=("bad ref!",),
            )

    def test_probe_frozen(self) -> None:
        p = _connected_probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY)
        with pytest.raises(AttributeError):
            p.state = AdapterProbeState.UNCONFIGURED  # type: ignore[misc]


# ---------------------------------------------------------------------------
# B. ExternalAdapterKind enum completeness
# ---------------------------------------------------------------------------


class TestExternalAdapterKind:
    def test_all_eight_kinds_defined(self) -> None:
        expected = {
            "control_plane_identity",
            "control_plane_entitlement",
            "b14_model_execution",
            "sandbox_provider",
            "github_repository_read",
            "github_draft_write",
            "communication_outbound",
            "accounting_read",
        }
        assert {k.value for k in ExternalAdapterKind} == expected


# ---------------------------------------------------------------------------
# C. Per-capability required adapter sets
# ---------------------------------------------------------------------------


class TestCapabilityRequirements:
    def test_managed_cloud_run_requires_five(self) -> None:
        req = required_adapters_for(LiveCapability.MANAGED_CLOUD_RUN)
        assert req == (
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.B14_MODEL_EXECUTION,
            ExternalAdapterKind.SANDBOX_PROVIDER,
            ExternalAdapterKind.GITHUB_REPOSITORY_READ,
        )

    def test_draft_pr_output_requires_six(self) -> None:
        req = required_adapters_for(LiveCapability.DRAFT_PR_OUTPUT)
        assert req == (
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.B14_MODEL_EXECUTION,
            ExternalAdapterKind.SANDBOX_PROVIDER,
            ExternalAdapterKind.GITHUB_REPOSITORY_READ,
            ExternalAdapterKind.GITHUB_DRAFT_WRITE,
        )

    def test_business_messaging_requires_three(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        assert req == (
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.COMMUNICATION_OUTBOUND,
        )

    def test_finance_projection_live_read_requires_three(self) -> None:
        req = required_adapters_for(LiveCapability.FINANCE_PROJECTION_LIVE_READ)
        assert req == (
            ExternalAdapterKind.CONTROL_PLANE_IDENTITY,
            ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT,
            ExternalAdapterKind.ACCOUNTING_READ,
        )


# ---------------------------------------------------------------------------
# D. Gate evaluation — UNCONFIGURED/FAKE never satisfy
# ---------------------------------------------------------------------------


class TestGateEvaluation:
    def test_all_connected_satisfies(self) -> None:
        req = required_adapters_for(LiveCapability.MANAGED_CLOUD_RUN)
        probes = _all_connected_probes(req)
        result = evaluate_capability_gate(LiveCapability.MANAGED_CLOUD_RUN, probes, now=NOW)
        assert result.satisfied is True
        assert result.missing_adapters == ()
        assert result.stale_probes == ()
        assert result.future_probes == ()

    def test_unconfigured_never_satisfies(self) -> None:
        req = required_adapters_for(LiveCapability.MANAGED_CLOUD_RUN)
        probes = list(_all_connected_probes(req))
        probes[0] = _unconfigured_probe(req[0])
        result = evaluate_capability_gate(LiveCapability.MANAGED_CLOUD_RUN, tuple(probes), now=NOW)
        assert result.satisfied is False
        assert req[0] in result.unconfigured_adapters

    def test_fake_never_satisfies(self) -> None:
        req = required_adapters_for(LiveCapability.MANAGED_CLOUD_RUN)
        probes = list(_all_connected_probes(req))
        probes[1] = _fake_probe(req[1])
        result = evaluate_capability_gate(LiveCapability.MANAGED_CLOUD_RUN, tuple(probes), now=NOW)
        assert result.satisfied is False
        assert req[1] in result.fake_adapters

    def test_stale_probe_fails_closed(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = list(_all_connected_probes(req))
        probes[0] = _stale_probe(req[0])
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, tuple(probes), now=NOW)
        assert result.satisfied is False
        assert req[0] in result.stale_probes

    def test_future_probe_fails_closed(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = list(_all_connected_probes(req))
        probes[0] = _future_probe(req[0])
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, tuple(probes), now=NOW)
        assert result.satisfied is False
        assert req[0] in result.future_probes

    def test_missing_adapter_visible(self) -> None:
        req = required_adapters_for(LiveCapability.FINANCE_PROJECTION_LIVE_READ)
        # Only provide 2 of 3 required
        probes = (
            _connected_probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY),
            _connected_probe(ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT),
        )
        result = evaluate_capability_gate(LiveCapability.FINANCE_PROJECTION_LIVE_READ, probes, now=NOW)
        assert result.satisfied is False
        assert ExternalAdapterKind.ACCOUNTING_READ in result.missing_adapters

    def test_extra_probes_ignored(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = _all_connected_probes(req) + (_connected_probe(ExternalAdapterKind.SANDBOX_PROVIDER),)
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, probes, now=NOW)
        assert result.satisfied is True

    def test_draft_pr_requires_github_draft_write(self) -> None:
        probes = [
            p
            for p in _all_connected_probes(
                required_adapters_for(LiveCapability.DRAFT_PR_OUTPUT)
            )
            if p.adapter_kind != ExternalAdapterKind.GITHUB_DRAFT_WRITE
        ]
        result = evaluate_capability_gate(
            LiveCapability.DRAFT_PR_OUTPUT, tuple(probes), now=NOW
        )
        assert result.satisfied is False
        assert ExternalAdapterKind.GITHUB_DRAFT_WRITE in result.missing_adapters

    def test_mixed_state_partial_satisfaction(self) -> None:
        req = required_adapters_for(LiveCapability.MANAGED_CLOUD_RUN)
        probes = (
            _connected_probe(ExternalAdapterKind.CONTROL_PLANE_IDENTITY),
            _fake_probe(ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT),
            _stale_probe(ExternalAdapterKind.B14_MODEL_EXECUTION),
            _unconfigured_probe(ExternalAdapterKind.SANDBOX_PROVIDER),
            # GitHub read missing entirely
        )
        result = evaluate_capability_gate(LiveCapability.MANAGED_CLOUD_RUN, probes, now=NOW)
        assert result.satisfied is False
        assert len(result.connected_adapters) == 1
        assert ExternalAdapterKind.CONTROL_PLANE_IDENTITY in result.connected_adapters
        assert ExternalAdapterKind.CONTROL_PLANE_ENTITLEMENT in result.fake_adapters
        assert ExternalAdapterKind.B14_MODEL_EXECUTION in result.stale_probes
        assert ExternalAdapterKind.SANDBOX_PROVIDER in result.unconfigured_adapters
        assert ExternalAdapterKind.GITHUB_REPOSITORY_READ in result.missing_adapters

    def test_result_frozen(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = _all_connected_probes(req)
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, probes, now=NOW)
        with pytest.raises(AttributeError):
            result.satisfied = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# E. Probe temporal boundary precision
# ---------------------------------------------------------------------------


class TestTemporalBoundaries:
    def test_probe_expiring_exactly_now_is_still_connected(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = list(_all_connected_probes(req))
        probes[0] = _connected_probe(
            req[0],
            issued=NOW - timedelta(hours=1),
            expires=NOW,  # exactly now: expires_at < now is False, so still connected
        )
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, tuple(probes), now=NOW)
        assert result.satisfied is True

    def test_probe_expiring_one_second_before_now_is_stale(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = list(_all_connected_probes(req))
        probes[0] = _connected_probe(
            req[0],
            issued=NOW - timedelta(hours=1),
            expires=NOW - timedelta(seconds=1),
        )
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, tuple(probes), now=NOW)
        assert result.satisfied is False
        assert req[0] in result.stale_probes

    def test_probe_issued_exactly_at_skew_boundary_is_connected(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = list(_all_connected_probes(req))
        probes[0] = _connected_probe(
            req[0],
            issued=NOW + timedelta(seconds=30),  # exactly at skew boundary
            expires=NOW + timedelta(days=1),
        )
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, tuple(probes), now=NOW)
        # issued_at > now + skew → future; 30 > 30 is False, so boundary is connected
        assert result.satisfied is True

    def test_probe_issued_one_second_past_skew_boundary_is_future(self) -> None:
        req = required_adapters_for(LiveCapability.BUSINESS_MESSAGING)
        probes = list(_all_connected_probes(req))
        probes[0] = _connected_probe(
            req[0],
            issued=NOW + timedelta(seconds=31),
            expires=NOW + timedelta(days=1),
        )
        result = evaluate_capability_gate(LiveCapability.BUSINESS_MESSAGING, tuple(probes), now=NOW)
        assert result.satisfied is False
        assert req[0] in result.future_probes


# ---------------------------------------------------------------------------
# F. Module purity: no IO, no real connector calls
# ---------------------------------------------------------------------------


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

    def test_no_security_certification_or_deployment_approval(self) -> None:
        """Module must not define security certification or deployment approval logic."""
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name.lower()
                assert "security_certification" not in name
                assert "deployment_approval" not in name
            if isinstance(node, ast.ClassDef):
                name = node.name.lower()
                assert "security_certification" not in name
                assert "deployment_approval" not in name

    def test_no_real_connector_call(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8").lower()
        assert "real_connector_call" not in source or "REAL_CONNECTOR_CALL = NO" in MODULE_PATH.read_text(encoding="utf-8")

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
        allowed = {"__future__", "dataclasses", "datetime", "enum", "re", "padiem_ai_core"}
        unexpected = sorted(set(imports) - allowed)
        assert not unexpected, f"unexpected imports: {unexpected}"


# ---------------------------------------------------------------------------
# G. Enum completeness
# ---------------------------------------------------------------------------


class TestEnumCompleteness:
    def test_probe_states(self) -> None:
        assert set(AdapterProbeState) == {
            AdapterProbeState.UNCONFIGURED,
            AdapterProbeState.DETERMINISTIC_FAKE,
            AdapterProbeState.CONNECTED,
        }

    def test_live_capabilities(self) -> None:
        assert set(LiveCapability) == {
            LiveCapability.MANAGED_CLOUD_RUN,
            LiveCapability.DRAFT_PR_OUTPUT,
            LiveCapability.BUSINESS_MESSAGING,
            LiveCapability.FINANCE_PROJECTION_LIVE_READ,
        }
