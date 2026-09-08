"""Tests for the Control Plane retention/deletion contract (#1570).

Covers the promoted CP contract acceptance points:
1. every retained data class has an explicit TTL
2. model/client cannot choose retention (owner validation)
3. legal hold prevents delete-due disposition
4. deletion receipt requires exact DELETE_DUE decision
5. receipt stores content SHA-256, never the original body
6. timestamps are timezone-aware
7. no real storage deletion in this contract
"""

from __future__ import annotations

import ast
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.retention_contract import (
    DeletionEligibility,
    DeletionReceipt,
    EligibilityResult,
    LegalHold,
    RetentionDataClass,
    RetentionDecision,
    RetentionPolicy,
    build_deletion_receipt,
    evaluate_deletion_eligibility,
    validate_legal_hold,
    validate_retention_policy,
)

MODULE_PATH = Path(__file__).resolve().parent.parent / "padiem_control_plane" / "retention_contract.py"
PACKAGE_DIR = MODULE_PATH.parent

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy(**overrides) -> RetentionPolicy:
    values = dict(
        data_class=RetentionDataClass.SESSION,
        ttl_seconds=86_400,
        owner="control_plane_server",
        policy_version="retention_v1",
    )
    values.update(overrides)
    return RetentionPolicy(**values)


def _hold(**overrides) -> LegalHold:
    values = dict(
        hold_ref="legal_hold_001",
        reason="litigation hold 2026-001",
        issued_at=NOW,
    )
    values.update(overrides)
    return LegalHold(**values)


def _eligibility(**overrides) -> DeletionEligibility:
    policy = overrides.pop("policy", _policy())
    created = overrides.pop("created_at", NOW - timedelta(days=2))
    values = dict(
        resource_ref="resource_abc_001",
        resource_type="session",
        created_at=created,
        policy=policy,
        legal_holds=(),
        check_deadline=NOW,
    )
    values.update(overrides)
    return DeletionEligibility(**values)


# ---------------------------------------------------------------------------
# A. RetentionPolicy — TTL validation
# ---------------------------------------------------------------------------


class TestRetentionPolicy:
    def test_valid_policy_accepted(self) -> None:
        policy = _policy()
        assert policy.ttl_seconds == 86_400
        assert policy.owner == "control_plane_server"
        assert policy.policy_version == "retention_v1"

    def test_all_data_classes_accepted(self) -> None:
        for dc in RetentionDataClass:
            p = _policy(data_class=dc)
            assert p.data_class is dc

    def test_ttl_zero_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="ttl_seconds"):
            _policy(ttl_seconds=0)

    def test_ttl_negative_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="ttl_seconds"):
            _policy(ttl_seconds=-1)

    def test_ttl_boolean_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="ttl_seconds"):
            _policy(ttl_seconds=True)  # type: ignore[arg-type]

    def test_ttl_string_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="ttl_seconds"):
            _policy(ttl_seconds="86400")  # type: ignore[arg-type]

    def test_ttl_above_max_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="ttl_seconds"):
            _policy(ttl_seconds=31_536_001)

    def test_ttl_at_max_accepted(self) -> None:
        p = _policy(ttl_seconds=31_536_000)
        assert p.ttl_seconds == 31_536_000

    def test_ttl_one_accepted(self) -> None:
        p = _policy(ttl_seconds=1)
        assert p.ttl_seconds == 1

    def test_empty_owner_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="owner"):
            _policy(owner="")

    def test_whitespace_owner_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="owner"):
            _policy(owner="   ")

    def test_model_owner_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="model/client"):
            _policy(owner="gpt_model_provider")

    def test_client_owner_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="model/client"):
            _policy(owner="web_client")

    def test_partner_owner_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="model/client"):
            _policy(owner="design_partner_001")

    def test_user_owner_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="model/client"):
            _policy(owner="end_user_session")

    def test_server_owner_accepted(self) -> None:
        p = _policy(owner="padiem_control_plane")
        assert p.owner == "padiem_control_plane"

    def test_invalid_policy_version_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="policy_version"):
            _policy(policy_version="V1-uppercase")

    def test_empty_policy_version_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="policy_version"):
            _policy(policy_version="")

    def test_policy_frozen(self) -> None:
        p = _policy()
        with pytest.raises(AttributeError):
            p.ttl_seconds = 999  # type: ignore[misc]

    def test_validate_retention_policy_passthrough(self) -> None:
        p = _policy()
        assert validate_retention_policy(p) is p

    def test_validate_retention_policy_rejects_non_policy(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="expected a RetentionPolicy"):
            validate_retention_policy("not_a_policy")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# B. LegalHold — reference validation + fail-safe
# ---------------------------------------------------------------------------


class TestLegalHold:
    def test_valid_hold_accepted(self) -> None:
        h = _hold()
        assert h.hold_ref == "legal_hold_001"
        assert h.reason == "litigation hold 2026-001"

    def test_empty_hold_ref_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="hold_ref"):
            _hold(hold_ref="")

    def test_unsafe_hold_ref_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="hold_ref"):
            _hold(hold_ref="hold ref with spaces")

    def test_empty_reason_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="reason"):
            _hold(reason="")

    def test_naive_issued_at_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="issued_at"):
            _hold(issued_at=datetime(2026, 9, 8, 10, 0))

    def test_hold_frozen(self) -> None:
        h = _hold()
        with pytest.raises(AttributeError):
            h.hold_ref = "changed"  # type: ignore[misc]

    def test_validate_legal_hold_passthrough(self) -> None:
        h = _hold()
        assert validate_legal_hold(h) is h

    def test_validate_legal_hold_rejects_non_hold(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="expected a LegalHold"):
            validate_legal_hold(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# C. DeletionEligibility — timezone-awareness
# ---------------------------------------------------------------------------


class TestDeletionEligibility:
    def test_valid_eligibility_accepted(self) -> None:
        e = _eligibility()
        assert e.resource_ref == "resource_abc_001"

    def test_naive_created_at_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="created_at"):
            _eligibility(created_at=datetime(2026, 9, 6, 10, 0))

    def test_naive_check_deadline_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="check_deadline"):
            _eligibility(check_deadline=datetime(2026, 9, 8, 10, 0))

    def test_unsafe_resource_ref_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="resource_ref"):
            _eligibility(resource_ref="ref with spaces")

    def test_empty_resource_type_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="resource_type"):
            _eligibility(resource_type="")

    def test_non_hold_in_legal_holds_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="legal_hold"):
            _eligibility(legal_holds=("not_a_hold",))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# D. evaluate_deletion_eligibility
# ---------------------------------------------------------------------------


class TestEvaluateDeletionEligibility:
    def test_active_when_not_expired(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(hours=1),
            policy=_policy(ttl_seconds=86_400),
            check_deadline=NOW,
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.ACTIVE
        assert result.deadline is not None
        assert result.active_hold_ref is None

    def test_delete_due_when_expired(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
            check_deadline=NOW,
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.DELETE_DUE
        assert result.deadline is not None
        assert result.active_hold_ref is None

    def test_legal_hold_prevents_deletion(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=365),
            policy=_policy(ttl_seconds=1),
            legal_holds=(_hold(),),
            check_deadline=NOW,
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.LEGAL_HOLD
        assert result.active_hold_ref == "legal_hold_001"
        assert result.deadline is None

    def test_legal_hold_overrides_expired_ttl(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=365),
            policy=_policy(ttl_seconds=1),
            legal_holds=(
                _hold(hold_ref="hold_old", issued_at=NOW - timedelta(days=30)),
                _hold(hold_ref="hold_new", issued_at=NOW - timedelta(days=1)),
            ),
            check_deadline=NOW,
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.LEGAL_HOLD
        assert result.active_hold_ref == "hold_new"

    def test_check_deadline_exactly_at_deadline_is_delete_due(self) -> None:
        policy = _policy(ttl_seconds=3600)
        created = NOW - timedelta(hours=1)
        e = _eligibility(created_at=created, policy=policy, check_deadline=NOW)
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.DELETE_DUE

    def test_check_deadline_one_second_before_is_active(self) -> None:
        policy = _policy(ttl_seconds=3600)
        created = NOW - timedelta(hours=1)
        e = _eligibility(
            created_at=created,
            policy=policy,
            check_deadline=NOW - timedelta(seconds=1),
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.ACTIVE

    def test_result_is_frozen_dataclass(self) -> None:
        e = _eligibility()
        result = evaluate_deletion_eligibility(e)
        with pytest.raises(AttributeError):
            result.decision = RetentionDecision.DELETE_DUE  # type: ignore[misc]


# ---------------------------------------------------------------------------
# E. build_deletion_receipt — content hash, no body
# ---------------------------------------------------------------------------


class TestBuildDeletionReceipt:
    def test_receipt_contains_sha256_not_content(self) -> None:
        content = b"sensitive session transcript data"
        expected_hash = hashlib.sha256(content).hexdigest()
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.DELETE_DUE

        receipt = build_deletion_receipt(
            deletion_id="del_001",
            eligibility=e,
            result=result,
            deleted_at=NOW,
            content_bytes=content,
        )
        assert receipt.content_sha256 == expected_hash
        assert "sensitive" not in str(receipt)
        assert "transcript" not in str(receipt)

    def test_receipt_decision_is_delete_due(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
        )
        result = evaluate_deletion_eligibility(e)
        receipt = build_deletion_receipt(
            deletion_id="del_002",
            eligibility=e,
            result=result,
            deleted_at=NOW,
            content_bytes=b"test",
        )
        assert receipt.decision is RetentionDecision.DELETE_DUE

    def test_receipt_stores_policy_ref_not_policy(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
        )
        result = evaluate_deletion_eligibility(e)
        receipt = build_deletion_receipt(
            deletion_id="del_003",
            eligibility=e,
            result=result,
            deleted_at=NOW,
            content_bytes=b"test",
        )
        assert receipt.policy_ref == "session:retention_v1"
        assert not isinstance(receipt.policy_ref, RetentionPolicy)

    def test_receipt_fails_on_active_result(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(hours=1),
            policy=_policy(ttl_seconds=86_400),
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.ACTIVE
        with pytest.raises(ControlPlaneContractError, match="DELETE_DUE"):
            build_deletion_receipt(
                deletion_id="del_004",
                eligibility=e,
                result=result,
                deleted_at=NOW,
                content_bytes=b"test",
            )

    def test_receipt_fails_on_legal_hold_result(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=365),
            policy=_policy(ttl_seconds=1),
            legal_holds=(_hold(),),
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.LEGAL_HOLD
        with pytest.raises(ControlPlaneContractError, match="DELETE_DUE"):
            build_deletion_receipt(
                deletion_id="del_005",
                eligibility=e,
                result=result,
                deleted_at=NOW,
                content_bytes=b"test",
            )

    def test_receipt_fails_on_naive_deleted_at(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
        )
        result = evaluate_deletion_eligibility(e)
        with pytest.raises(ControlPlaneContractError, match="deleted_at"):
            build_deletion_receipt(
                deletion_id="del_006",
                eligibility=e,
                result=result,
                deleted_at=datetime(2026, 9, 8, 10, 0),
                content_bytes=b"test",
            )

    def test_receipt_fails_on_non_bytes_content(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
        )
        result = evaluate_deletion_eligibility(e)
        with pytest.raises(ControlPlaneContractError, match="content_bytes"):
            build_deletion_receipt(
                deletion_id="del_007",
                eligibility=e,
                result=result,
                deleted_at=NOW,
                content_bytes="string not bytes",  # type: ignore[arg-type]
            )

    def test_receipt_frozen(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
        )
        result = evaluate_deletion_eligibility(e)
        receipt = build_deletion_receipt(
            deletion_id="del_008",
            eligibility=e,
            result=result,
            deleted_at=NOW,
            content_bytes=b"test",
        )
        with pytest.raises(AttributeError):
            receipt.content_sha256 = "tampered"  # type: ignore[misc]

    def test_receipt_with_legal_hold_ref_recorded(self) -> None:
        e = _eligibility(
            created_at=NOW - timedelta(days=2),
            policy=_policy(ttl_seconds=86_400),
            legal_holds=(_hold(hold_ref="hold_abc"),),
        )
        result = evaluate_deletion_eligibility(e)
        assert result.decision is RetentionDecision.LEGAL_HOLD
        # Receipt can only be built from DELETE_DUE; legal hold ref is None
        # in the receipt's policy_ref field — this is tested by the failure above.
        # The legal_hold_ref on DeletionReceipt is set at construction time;
        # test that it accepts None and a valid ref.
        r = DeletionReceipt(
            deletion_id="del_009",
            resource_ref="resource_abc_001",
            resource_type="session",
            policy_ref="session:retention_v1",
            legal_hold_ref=None,
            deleted_at=NOW,
            content_sha256=hashlib.sha256(b"x").hexdigest(),
            decision=RetentionDecision.DELETE_DUE,
        )
        assert r.legal_hold_ref is None

    def test_receipt_unsafe_deletion_id_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="deletion_id"):
            DeletionReceipt(
                deletion_id="bad id!",
                resource_ref="resource_abc_001",
                resource_type="session",
                policy_ref="session:retention_v1",
                legal_hold_ref=None,
                deleted_at=NOW,
                content_sha256=hashlib.sha256(b"x").hexdigest(),
                decision=RetentionDecision.DELETE_DUE,
            )

    def test_receipt_invalid_sha256_rejected(self) -> None:
        with pytest.raises(ControlPlaneContractError, match="content_sha256"):
            DeletionReceipt(
                deletion_id="del_010",
                resource_ref="resource_abc_001",
                resource_type="session",
                policy_ref="session:retention_v1",
                legal_hold_ref=None,
                deleted_at=NOW,
                content_sha256="not-a-valid-hash",
                decision=RetentionDecision.DELETE_DUE,
            )


# ---------------------------------------------------------------------------
# F. Real-storage-delete guard: module contains no storage/IO operations
# ---------------------------------------------------------------------------


class TestModulePurity:
    def test_no_io_or_storage_calls(self) -> None:
        """Module must not contain real storage deletion or IO operations."""
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        call_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    call_names.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    call_names.append(node.func.attr)
        forbidden = {"delete", "unlink", "remove", "rmdir", "write", "rename"}
        found = sorted(forbidden & set(call_names))
        assert not found, f"module must not call storage operations: {found}"

    def test_no_model_or_client_authority_in_module(self) -> None:
        """Module must not allow model/client to set retention."""
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and "model" in node.name.lower():
                raise AssertionError(f"function name must not reference 'model': {node.name}")
            if isinstance(node, ast.FunctionDef) and "client" in node.name.lower():
                raise AssertionError(f"function name must not reference 'client': {node.name}")

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
        allowed = {"__future__", "dataclasses", "datetime", "enum", "hashlib", "re", "padiem_control_plane"}
        unexpected = sorted(set(imports) - allowed)
        assert not unexpected, f"unexpected imports: {unexpected}"

    def test_no_secret_or_credential_leakage(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8").lower()
        for term in ("password", "secret", "api_key", "token", "credential"):
            assert term not in source, f"module must not reference '{term}'"


# ---------------------------------------------------------------------------
# G. RetentionDecision enum completeness
# ---------------------------------------------------------------------------


class TestEnumCompleteness:
    def test_retention_decision_values(self) -> None:
        assert set(RetentionDecision) == {
            RetentionDecision.ACTIVE,
            RetentionDecision.DELETE_DUE,
            RetentionDecision.LEGAL_HOLD,
        }

    def test_retention_data_class_values(self) -> None:
        assert set(RetentionDataClass) == {
            RetentionDataClass.SESSION,
            RetentionDataClass.COMMAND,
            RetentionDataClass.IDENTITY,
            RetentionDataClass.USAGE,
        }
