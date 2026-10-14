"""#4139 focused: TXT approval material issuance, digest ports and wire compat.

Covers the missing supply path only: owner-named intent -> closed receipt ->
Broker validator -> Resident parser -> plan source. No live deploy, no
second approval store, no fixture-as-provider.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "padiem-chat"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "padiem-control-plane"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "korean-ai-code-agent" / "src"))

from app.connector_txt_approval_material import (  # noqa: E402
    TXT_READ_APPROVAL_AUTHORITY_REF,
    TXT_READ_LOCAL_POLICY_REF,
    TXT_READ_RECEIPT_FORMAT,
    OwnerTxtApprovalProof,
    TxtApprovalMaterialError,
    command_material_fingerprint_for,
    mint_txt_read_receipt,
    normalize_txt_relative_path,
)

NOW = datetime(2026, 10, 15, 5, 0, 0, tzinfo=timezone.utc)


def _proof(**overrides):
    args = {
        "owner_id": "owner-1",
        "workspace_id": "workspace-1",
        "device_id": "device-1",
        "binding_ref": "binding-1",
        "credential_generation": 1,
        "consent_id": "consent-1",
        "run_id": "run-conversation-1",
    }
    args.update(overrides)
    return OwnerTxtApprovalProof(**args)


def _mint(**overrides):
    proof = overrides.pop("approval", None)
    if proof is None:
        proof_args = {k: overrides.pop(k) for k in (
            "owner_id", "workspace_id", "device_id", "binding_ref",
            "credential_generation", "consent_id", "run_id",
        ) if k in overrides}
        proof = _proof(**proof_args)
    args = {
        "approval": proof,
        "root_ref": "root.docs",
        "path_relative": r"notes\report.txt",
        "now": NOW,
    }
    args.update(overrides)
    return mint_txt_read_receipt(**args)


def test_path_normalization_matches_resident_rule():
    from kagent.contracts import ContractError as ResidentRefused
    from kagent.windows_local_filesystem import (
        _relative_file_path as resident_normalize,
    )

    assert normalize_txt_relative_path("notes/report.txt") == r"notes\report.txt"
    # Bit-identical outcomes with the Resident canonical rule, accept or refuse.
    for candidate in ("notes/report.txt", r"notes\report.txt", "a/./b.txt",
                      "/abs.txt", "C:\\x.txt", "..\\x.txt", "a\\..\\x.txt",
                      "notes.pdf", "", "   ", "x" * 1025, ".", ".."):
        try:
            expected = resident_normalize(candidate)
        except ResidentRefused:
            expected = None
        try:
            actual = normalize_txt_relative_path(candidate)
        except TxtApprovalMaterialError:
            actual = None
        assert actual == expected, candidate
    for bad in ("", "   ", "C:\\x.txt", "..\\x.txt", "a\\..\\x.txt",
                "x" * 1025):
        with pytest.raises(TxtApprovalMaterialError):
            normalize_txt_relative_path(bad)


def test_mint_produces_closed_receipt_with_exact_constants():
    issued = _mint()
    receipt = issued["receipt"]
    assert receipt["format"] == TXT_READ_RECEIPT_FORMAT
    assert receipt["local_policy_ref"] == TXT_READ_LOCAL_POLICY_REF
    assert receipt["approval_decision"]["authority_ref"] == TXT_READ_APPROVAL_AUTHORITY_REF
    assert receipt["approval_pause"]["tool_id"] == "local.filesystem.read"
    assert receipt["approval_pause"]["requirement"] == "user_confirmation"
    assert receipt["approval_pause"]["approval_scope"] == ["filesystem.read"]
    assert receipt["approval_decision"]["outcome"] == "approved"
    args = receipt["exact_tool_arguments"]
    assert args["operation"] == "read"
    assert args["path_relative"] == r"notes\report.txt"
    assert args["content_bytes"] == 0 and args["content_sha256"] is None
    assert issued["material"]["p01_approval_payload"] == receipt
    assert issued["enqueue"]["command_id"] == receipt["command_id"]
    assert issued["material"]["argv"] == ["python", "-V"]
    # Wire fits the durable bound with wide margin.
    wire = {"contract_version": "claw-local-command-material.v2",
            "command_id": "c", "binding_ref": "b", "sequence": 1,
            "request_fingerprint": "a" * 64, "revision_ref": "r",
            "material": issued["material"]}
    assert len(json.dumps(wire).encode("utf-8")) < 196_608


def test_digest_port_matches_resident_canonical_algorithm():
    from kagent.local_agent import LocalCommandRequest
    from kagent.windows_local_executor import command_request_fingerprint

    material_fp = command_material_fingerprint_for(
        request_id="req-1", run_id="run-conversation-1", device_id="device-1",
        root_ref="root.docs", argv=["python", "-V"], cwd_relative=".",
        requested_at=NOW, timeout_seconds=30,
    )
    assert material_fp == command_request_fingerprint(LocalCommandRequest(
        request_id="req-1", run_id="run-conversation-1", device_id="device-1",
        root_ref="root.docs", argv=("python", "-V"), cwd_relative=".",
        requested_at=NOW, timeout_seconds=30,
    ))


def test_proof_contract_rejects_unverified_caller_material():
    with pytest.raises(TxtApprovalMaterialError):
        mint_txt_read_receipt(
            approval="not-a-proof", root_ref="root.docs",
            path_relative=r"notes\report.txt", now=NOW,
        )
    with pytest.raises(TxtApprovalMaterialError):
        _proof(credential_generation=0)
    with pytest.raises(TxtApprovalMaterialError):
        _proof(device_id="has space")
    # run_id must be identifier-clean: a detached free-form mint is refused.
    with pytest.raises(TxtApprovalMaterialError):
        _proof(run_id="has space")


def test_bilateral_policy_constant_matches_resident_factory():
    from kagent.verified_engine_text_read_plan_source import (
        TXT_READ_LOCAL_POLICY_REF as RESIDENT_POLICY_REF,
    )
    assert RESIDENT_POLICY_REF == TXT_READ_LOCAL_POLICY_REF


def test_issuance_output_passes_broker_validator_and_resident_parser():
    import local_agent_broker_material_store as broker_store
    from kagent.local_agent_command_material import validate_txt_approval_receipt

    issued = _mint()
    broker_store.validate_txt_approval_receipt(issued["receipt"])
    validate_txt_approval_receipt(issued["receipt"])


def test_rejections_stay_fail_closed():
    with pytest.raises(TxtApprovalMaterialError):
        _mint(path_relative="notes/report.pdf")
    with pytest.raises(TxtApprovalMaterialError):
        _mint(path_relative="..\\secret.txt")
    with pytest.raises(TxtApprovalMaterialError):
        _mint(root_ref="has space")
    with pytest.raises(TxtApprovalMaterialError):
        _mint(device_id="")
    with pytest.raises(TxtApprovalMaterialError):
        _mint(now="not-a-datetime")
