"""#4139 focused: real TXT plan-source factory over issuance-built receipts.

Uses the actual Chat issuance output (imported, not duplicated) as the only
receipt origin, then drives the REAL VerifiedEngineTextReadPlanSource end to
end: resolver scoping, redeemer reconstruction, plan correlation, absence and
mismatch behavior. No live Broker, no approval minted here.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "apps" / "padiem-chat"))

from app.connector_txt_approval_material import (  # noqa: E402
    TXT_READ_LOCAL_POLICY_REF,
    OwnerTxtApprovalProof,
    mint_txt_read_receipt,
)

from kagent.contracts import ContractError  # noqa: E402
from kagent.local_agent_pairing import (  # noqa: E402
    DeviceBinding,
    DeviceCommandEnvelope,
    DeviceLifecycle,
)
from kagent.local_resident_verified_text_delivery import (  # noqa: E402
    AdmittedTextReadContext,
)
from kagent.verified_engine_text_read_plan_source import (  # noqa: E402
    BrokerMaterialTxtReceiptRedeemer,
    _resolve_txt_read_scope,
    make_verified_text_plan_source,
)

NOW = datetime(2026, 10, 15, 5, 0, 0, tzinfo=timezone.utc)


def _binding():
    return DeviceBinding(
        device_id="device-1", binding_ref="binding-1", account_ref="acc-1",
        workspace_ref="ws-1", credential_ref="cred-1", credential_generation=1,
        issued_at=NOW - timedelta(hours=1),
        credential_expires_at=NOW + timedelta(hours=1),
        state=DeviceLifecycle.ONLINE,
    )


def _issued(**overrides):
    proof_args = {
        "owner_id": "owner-1",
        "workspace_id": "ws-1",
        "device_id": "device-1",
        "binding_ref": "binding-1",
        "credential_generation": 1,
        "consent_id": "consent-1",
        "run_id": "run-conversation-1",
    }
    proof_args.update(overrides.pop("proof", {}))
    path_relative = overrides.pop("path_relative", r"notes\report.txt")
    return mint_txt_read_receipt(
        approval=OwnerTxtApprovalProof(**proof_args),
        root_ref="root.docs",
        path_relative=path_relative,
        now=NOW,
        **overrides,
    )


def _command(issued):
    return DeviceCommandEnvelope(
        command_id=issued["receipt"]["command_id"],
        run_id="run-conversation-1",
        tool_request_ref=issued["tool_request_ref"],
        binding_ref="binding-1", sequence=1, issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5), revision_ref="revision-1",
    )


def _admitted(issued):
    return AdmittedTextReadContext(
        admission_ref="admission-1",
        evidence_ref=issued["receipt"]["evidence_ref"],
        request_id=issued["material"]["request_id"],
        command_fingerprint="b" * 64,
        admitted_at=NOW + timedelta(seconds=5),
    )


def test_factory_builds_working_source_with_bilateral_policy():
    source = make_verified_text_plan_source()
    assert callable(source.approved_plan_for_admitted_command)
    assert source._policy_ref == TXT_READ_LOCAL_POLICY_REF


def test_absent_receipt_yields_no_plan_not_a_refusal():
    source = make_verified_text_plan_source()
    plan = source.approved_plan_for_admitted_command(
        binding=_binding(), command=_command(_issued()), admitted=_admitted(_issued()),
    )
    assert plan is None


def test_issuance_receipt_yields_correlated_plan():
    issued = _issued()
    source = make_verified_text_plan_source()
    binding, command, admitted = _binding(), _command(issued), _admitted(issued)
    plan = source.approved_plan_for_admitted_command(
        binding=binding, command=command, admitted=admitted,
        receipt=issued["material"]["p01_approval_payload"],
    )
    assert plan is not None
    assert plan.binding_ref == "binding-1"
    assert plan.command_id == issued["receipt"]["command_id"]
    assert plan.file_request.path_relative == r"notes\report.txt"
    assert plan.file_request.root_ref == "root.docs"
    assert plan.file_evidence.local_policy_ref == TXT_READ_LOCAL_POLICY_REF


def test_receipt_for_another_command_is_refused_not_repurposed():
    issued = _issued()
    other = _issued(path_relative=r"notes\other.txt")
    source = make_verified_text_plan_source()
    with pytest.raises(ContractError):
        source.approved_plan_for_admitted_command(
            binding=_binding(), command=_command(issued), admitted=_admitted(issued),
            receipt=other["material"]["p01_approval_payload"],
        )


def test_wrong_policy_receipt_is_refused():
    issued = _issued()
    receipt = dict(issued["material"]["p01_approval_payload"])
    receipt["local_policy_ref"] = "foreign-policy"
    source = make_verified_text_plan_source()
    with pytest.raises(ContractError):
        source.approved_plan_for_admitted_command(
            binding=_binding(), command=_command(issued), admitted=_admitted(issued),
            receipt=receipt,
        )


def test_resolver_and_redeemer_units():
    issued = _issued()
    binding, command, admitted = _binding(), _command(issued), _admitted(issued)
    assert _resolve_txt_read_scope(
        binding=binding, command=command, admitted=admitted) is None
    scoped = _resolve_txt_read_scope(
        binding=binding, command=command, admitted=admitted,
        receipt=issued["material"]["p01_approval_payload"])
    assert scoped is not None
    assert scoped.root_ref == "root.docs"
    assert scoped.request_fingerprint == issued["request_fingerprint"]
    redeemer = BrokerMaterialTxtReceiptRedeemer()
    redeemed = redeemer.redeem_for_trusted_command(scoped)
    assert redeemed.binding is scoped
    assert redeemed.receipt.pause.tool_id == "local.filesystem.read"
    assert str(redeemed.receipt.verified_decision.outcome) == "ApprovalOutcome.APPROVED"


def test_wire_to_plan_end_to_end_through_parser():
    """Issuance -> Broker wire -> Resident parser -> Resolved -> plan.

    The only hop not executed here is the Broker durable store itself, whose
    closed validation is pinned separately against the same issuance output.
    """
    from kagent.local_agent import LocalCommandRequest
    from kagent.local_agent_command_material import (
        OutboundCommandMaterialRequest,
        parse_command_material_wire_projection,
    )
    from kagent.local_agent_pairing import DeviceSession
    from kagent.windows_local_executor import command_request_fingerprint

    issued = _issued()
    binding = _binding()
    session = DeviceSession(
        session_id="session-1", device_id="device-1", binding_ref="binding-1",
        account_ref="acc-1", workspace_ref="ws-1",
        issued_at=NOW, expires_at=NOW + timedelta(minutes=30),
    )
    material_request = LocalCommandRequest(
        request_id=issued["material"]["request_id"],
        run_id=issued["material"]["run_id"],
        device_id="device-1", root_ref="root.docs",
        argv=tuple(issued["material"]["argv"]),
        cwd_relative=".", requested_at=NOW, timeout_seconds=30,
    )
    material_fp = command_request_fingerprint(material_request)
    command = DeviceCommandEnvelope(
        command_id=issued["receipt"]["command_id"],
        run_id=issued["material"]["run_id"],
        tool_request_ref=issued["tool_request_ref"],
        binding_ref="binding-1", sequence=1, issued_at=NOW + timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=10), revision_ref="revision-1",
    )
    outbound = OutboundCommandMaterialRequest(
        request_ref="request-ref-1", session=session, command=command,
        request_fingerprint=material_fp, requested_at=NOW + timedelta(seconds=2),
    )
    wire = {
        "contract_version": "claw-local-command-material.v2",
        "command_id": command.command_id,
        "binding_ref": command.binding_ref,
        "sequence": command.sequence,
        "request_fingerprint": material_fp,
        "revision_ref": command.revision_ref,
        "material": issued["material"],
    }
    resolved = parse_command_material_wire_projection(
        wire, outbound_request=outbound)
    assert resolved.approval_receipt is not None
    admitted = AdmittedTextReadContext(
        admission_ref="admission-1",
        evidence_ref=issued["receipt"]["evidence_ref"],
        request_id=issued["material"]["request_id"],
        command_fingerprint=material_fp,
        admitted_at=NOW + timedelta(seconds=5),
    )
    source = make_verified_text_plan_source()
    plan = source.approved_plan_for_admitted_command(
        binding=binding, command=command, admitted=admitted,
        receipt=resolved.approval_receipt,
    )
    assert plan is not None
    assert plan.file_request.path_relative == r"notes\report.txt"
    assert plan.run_id == issued["material"]["run_id"]
