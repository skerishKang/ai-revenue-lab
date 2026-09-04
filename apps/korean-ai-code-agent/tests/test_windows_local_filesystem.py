from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
    tool_invocation_digest,
)

from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_permissions import (
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalPermissionRequest,
    LocalPolicyMode,
    RootPermissionPolicy,
    default_device_permission_profile,
)
from kagent.windows_local_filesystem import (
    ADMIN_ELEVATION_SUPPORTED,
    CANONICAL_P01_APPROVAL_REUSED,
    DIRECTORY_ENUMERATION_SUPPORTED,
    FILESYSTEM_DELETE_FILE_ONLY,
    FILESYSTEM_READ_IMPLEMENTED,
    FILESYSTEM_WRITE_IMPLEMENTED,
    MAX_SELECTED_ROOT_FILE_BYTES,
    PRODUCTION_REMOTE_CONTROL_CLAIMED,
    RAW_HOST_CREDENTIAL_DISCOVERY,
    REAL_SELECTED_ROOT_FILE_IO_IMPLEMENTED,
    RECURSIVE_DELETE_SUPPORTED,
    SECOND_APPROVAL_AUTHORITY,
    DeterministicFakeWindowsFileAuthorizationPort,
    DeterministicWindowsFileAuthorityEvidencePort,
    LocalFileOperation,
    LocalFileRequest,
    P01LocalPermissionWindowsFileAuthorizationPort,
    WindowsFileAuthorityEvidence,
    WindowsSelectedRootFileRuntime,
    file_request_fingerprint,
    windows_file_tool_invocation,
)

NOW = datetime(2026, 9, 4, 3, 0, tzinfo=timezone.utc)


def device(root_path: str = r"C:\workspace\repo") -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_file_1",
        workspace_ref="workspace_file_1",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(LocalRoot(root_ref="repo", windows_path=root_path),),
    )


def request(
    operation: LocalFileOperation,
    *,
    path_relative: str = r"notes\status.txt",
    content: bytes | None = None,
    action_id: str = "file_action_1",
    requested_at: datetime | None = None,
) -> LocalFileRequest:
    return LocalFileRequest(
        action_id=action_id,
        run_id="run_file_1",
        device_id="device_file_1",
        root_ref="repo",
        operation=operation,
        path_relative=path_relative,
        requested_at=requested_at or NOW - timedelta(minutes=1),
        content=content,
    )


def permission_request(file_request: LocalFileRequest) -> LocalPermissionRequest:
    return LocalPermissionRequest(
        action_id=f"permission_{file_request.action_id}",
        run_id=file_request.run_id,
        device_id=file_request.device_id,
        capability=file_request.capability,
        target_ref=file_request_fingerprint(file_request),
        root_ref=file_request.root_ref,
    )


def approval_pause(
    file_request: LocalFileRequest,
    *,
    expires_at: datetime | None = None,
    scope: tuple[str, ...] | None = None,
) -> ApprovalPause:
    invocation = windows_file_tool_invocation(file_request)
    return ApprovalPause(
        pause_id=f"pause_{file_request.action_id}",
        run_id=file_request.run_id,
        agent_runtime_id="agent_file_1",
        tool_id=invocation.tool_id,
        invocation_sha256=tool_invocation_digest(invocation),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW - timedelta(minutes=2),
        expires_at=expires_at or NOW + timedelta(minutes=10),
        approval_scope=scope if scope is not None else (file_request.capability.value,),
    )


def approval_decision(
    file_request: LocalFileRequest,
    *,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
) -> VerifiedApprovalDecision:
    return VerifiedApprovalDecision(
        decision_id=f"decision_{file_request.action_id}",
        pause_id=f"pause_{file_request.action_id}",
        outcome=outcome,
        authority_ref="p01_file_authority_1",
        evidence_ref="p01_file_evidence_1",
        decided_at=NOW - timedelta(seconds=30),
    )


def evidence(
    file_request: LocalFileRequest,
    *,
    permission: LocalPermissionRequest | None = None,
    pause: ApprovalPause | None = None,
    decision: VerifiedApprovalDecision | None = None,
    expires_at: datetime | None = None,
) -> WindowsFileAuthorityEvidence:
    return WindowsFileAuthorityEvidence(
        evidence_ref=f"authority_{file_request.action_id}",
        request_fingerprint=file_request_fingerprint(file_request),
        permission_request=permission or permission_request(file_request),
        approval_pause=pause or approval_pause(file_request),
        approval_decision=decision or approval_decision(file_request),
        local_policy_ref="local_file_policy_v1",
        expires_at=expires_at or NOW + timedelta(minutes=5),
    )


def adapter(
    authority: WindowsFileAuthorityEvidence,
    *,
    permissions: DevicePermissionProfile | None = None,
) -> P01LocalPermissionWindowsFileAuthorizationPort:
    return P01LocalPermissionWindowsFileAuthorizationPort(
        permission_profile=permissions or default_device_permission_profile(device=device()),
        evidence_port=DeterministicWindowsFileAuthorityEvidencePort((authority,)),
    )


class WindowsLocalFilesystemContractTests(unittest.TestCase):
    def test_relative_path_is_closed_and_traversal_or_absolute_paths_fail(self) -> None:
        for path in (r"..\outside.txt", r"folder\..\outside.txt", r"C:\outside.txt", r"\\server\share\x.txt"):
            with self.subTest(path=path):
                with self.assertRaises(ContractError):
                    request(LocalFileOperation.READ, path_relative=path)

    def test_write_requires_bounded_bytes_and_read_delete_cannot_smuggle_content(self) -> None:
        with self.assertRaises(ContractError):
            request(LocalFileOperation.WRITE, content=None)
        with self.assertRaises(ContractError):
            request(LocalFileOperation.WRITE, content=b"x" * (MAX_SELECTED_ROOT_FILE_BYTES + 1))
        for operation in (LocalFileOperation.READ, LocalFileOperation.DELETE):
            with self.subTest(operation=operation):
                with self.assertRaises(ContractError):
                    request(operation, content=b"unexpected")

    def test_fingerprint_binds_operation_path_and_write_content_digest(self) -> None:
        first = request(LocalFileOperation.WRITE, content=b"alpha")
        second = request(LocalFileOperation.WRITE, content=b"beta")
        moved = request(LocalFileOperation.WRITE, path_relative=r"notes\other.txt", content=b"alpha")
        self.assertNotEqual(file_request_fingerprint(first), file_request_fingerprint(second))
        self.assertNotEqual(file_request_fingerprint(first), file_request_fingerprint(moved))
        self.assertNotEqual(
            file_request_fingerprint(request(LocalFileOperation.READ)),
            file_request_fingerprint(request(LocalFileOperation.DELETE)),
        )

    def test_exact_request_receives_one_shot_grant_from_canonical_p01_and_recomputed_local_policy(self) -> None:
        file_request = request(LocalFileOperation.WRITE, content=b"approved-content")
        authority = evidence(file_request)
        authorization = adapter(authority)
        grant = authorization.authorize(request=file_request, now=NOW)
        grant.validate(request=file_request, now=NOW)
        self.assertEqual(grant.capability_ref, "filesystem.write")
        self.assertEqual(grant.p01_approval_ref, f"decision_{file_request.action_id}")
        rendered = authority.safe_dict()
        self.assertFalse(rendered["client_permission_decision_authority"])
        self.assertFalse(rendered["raw_file_content"])
        self.assertFalse(rendered["raw_credentials"])
        with self.assertRaisesRegex(ContractError, "already been consumed"):
            authorization.authorize(request=file_request, now=NOW)

    def test_p01_pause_must_bind_exact_content_digest_and_path(self) -> None:
        file_request = request(LocalFileOperation.WRITE, content=b"approved-content")
        altered = request(LocalFileOperation.WRITE, content=b"different-content")
        authority = evidence(file_request, pause=approval_pause(altered))
        with self.assertRaisesRegex(ContractError, "exact file invocation"):
            adapter(authority).authorize(request=file_request, now=NOW)

    def test_permission_evidence_target_root_and_capability_are_exact(self) -> None:
        file_request = request(LocalFileOperation.READ)
        wrong_target = LocalPermissionRequest(
            action_id="permission_wrong",
            run_id=file_request.run_id,
            device_id=file_request.device_id,
            capability=LocalCapability.FILESYSTEM_READ,
            target_ref="0" * 64,
            root_ref=file_request.root_ref,
        )
        with self.assertRaisesRegex(ContractError, "exact request fingerprint"):
            adapter(evidence(file_request, permission=wrong_target)).authorize(request=file_request, now=NOW)

        wrong_capability = LocalPermissionRequest(
            action_id="permission_wrong_capability",
            run_id=file_request.run_id,
            device_id=file_request.device_id,
            capability=LocalCapability.FILESYSTEM_WRITE,
            target_ref=file_request_fingerprint(file_request),
            root_ref=file_request.root_ref,
        )
        with self.assertRaisesRegex(ContractError, "capability mismatch"):
            adapter(evidence(file_request, permission=wrong_capability)).authorize(request=file_request, now=NOW)

    def test_local_deny_wins_even_when_p01_approved(self) -> None:
        file_request = request(LocalFileOperation.READ)
        base = default_device_permission_profile(device=device())
        denied_roots = tuple(
            RootPermissionPolicy(
                root.root_ref,
                tuple(
                    CapabilityRule(
                        rule.capability,
                        LocalPolicyMode.DENY if rule.capability is LocalCapability.FILESYSTEM_READ else rule.mode,
                    )
                    for rule in root.rules
                ),
            )
            for root in base.roots
        )
        denied = DevicePermissionProfile(
            device_id=base.device_id,
            workspace_ref=base.workspace_ref,
            roots=denied_roots,
            global_rules=base.global_rules,
        )
        with self.assertRaisesRegex(ContractError, "local policy denied filesystem.read"):
            adapter(evidence(file_request), permissions=denied).authorize(request=file_request, now=NOW)

    def test_p01_denial_scope_and_expiry_fail_closed(self) -> None:
        file_request = request(LocalFileOperation.DELETE)
        denied = evidence(file_request, decision=approval_decision(file_request, outcome=ApprovalOutcome.DENIED))
        with self.assertRaisesRegex(ContractError, "approved canonical P01 decision"):
            adapter(denied).authorize(request=file_request, now=NOW)

        wrong_scope = evidence(file_request, pause=approval_pause(file_request, scope=("filesystem.read",)))
        with self.assertRaisesRegex(ContractError, "scope"):
            adapter(wrong_scope).authorize(request=file_request, now=NOW)

        expired = evidence(file_request, expires_at=NOW - timedelta(seconds=1))
        with self.assertRaisesRegex(ContractError, "evidence has expired"):
            adapter(expired).authorize(request=file_request, now=NOW)

    def test_unconfigured_authority_fails_closed(self) -> None:
        file_request = request(LocalFileOperation.READ)
        authorization = P01LocalPermissionWindowsFileAuthorizationPort(
            permission_profile=default_device_permission_profile(device=device()),
        )
        with self.assertRaisesRegex(ContractError, "not configured"):
            authorization.authorize(request=file_request, now=NOW)

    def test_non_windows_real_file_io_fails_closed(self) -> None:
        if os.name == "nt":
            self.skipTest("covered by Windows physical I/O tests")
        runtime = WindowsSelectedRootFileRuntime(
            device=device(),
            authorization_port=DeterministicFakeWindowsFileAuthorizationPort(),
        )
        with self.assertRaisesRegex(ContractError, "Windows-only"):
            runtime.perform(request(LocalFileOperation.READ), now=NOW)

    def test_boundary_nonclaims_are_explicit(self) -> None:
        self.assertTrue(REAL_SELECTED_ROOT_FILE_IO_IMPLEMENTED)
        self.assertTrue(FILESYSTEM_READ_IMPLEMENTED)
        self.assertTrue(FILESYSTEM_WRITE_IMPLEMENTED)
        self.assertTrue(FILESYSTEM_DELETE_FILE_ONLY)
        self.assertTrue(CANONICAL_P01_APPROVAL_REUSED)
        self.assertFalse(SECOND_APPROVAL_AUTHORITY)
        self.assertFalse(DIRECTORY_ENUMERATION_SUPPORTED)
        self.assertFalse(RECURSIVE_DELETE_SUPPORTED)
        self.assertFalse(RAW_HOST_CREDENTIAL_DISCOVERY)
        self.assertFalse(ADMIN_ELEVATION_SUPPORTED)
        self.assertFalse(PRODUCTION_REMOTE_CONTROL_CLAIMED)


class _RecordingAuthorization:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def authorize(self, *, request: LocalFileRequest, now: datetime):
        del now
        self.calls.append(request.action_id)
        raise AssertionError("future-dated file request reached authorization")


@unittest.skipUnless(os.name == "nt", "physical selected-root file I/O is Windows-first")
class WindowsLocalFilesystemPhysicalTests(unittest.TestCase):
    def _runtime(self, root_dir: str, authorization=None) -> WindowsSelectedRootFileRuntime:
        return WindowsSelectedRootFileRuntime(
            device=device(root_dir),
            authorization_port=authorization or DeterministicFakeWindowsFileAuthorizationPort(),
        )

    def test_real_read_write_and_file_only_delete_stay_inside_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            notes = Path(root_dir) / "notes"
            notes.mkdir()
            existing = notes / "status.txt"
            existing.write_bytes(b"before")
            runtime = self._runtime(root_dir)

            read_result = runtime.perform(request(LocalFileOperation.READ), now=NOW)
            self.assertEqual(read_result.content, b"before")
            self.assertEqual(read_result.bytes_count, 6)
            self.assertFalse(read_result.safe_dict()["raw_content"])

            write_request = request(
                LocalFileOperation.WRITE,
                path_relative=r"notes\written.bin",
                content=b"after",
                action_id="file_action_write",
            )
            write_result = runtime.perform(write_request, now=NOW)
            self.assertEqual((notes / "written.bin").read_bytes(), b"after")
            self.assertEqual(write_result.bytes_count, 5)
            self.assertIsNone(write_result.content)

            delete_request = request(
                LocalFileOperation.DELETE,
                path_relative=r"notes\written.bin",
                action_id="file_action_delete",
            )
            runtime.perform(delete_request, now=NOW)
            self.assertFalse((notes / "written.bin").exists())

            directory_delete = request(
                LocalFileOperation.DELETE,
                path_relative="notes",
                action_id="file_action_delete_dir",
            )
            with self.assertRaisesRegex(ContractError, "regular file"):
                runtime.perform(directory_delete, now=NOW)
            self.assertTrue(notes.is_dir())

    def test_future_dated_file_request_fails_before_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            Path(root_dir, "notes").mkdir()
            Path(root_dir, "notes", "status.txt").write_bytes(b"safe")
            authorization = _RecordingAuthorization()
            runtime = self._runtime(root_dir, authorization=authorization)
            future = request(LocalFileOperation.READ, requested_at=NOW + timedelta(seconds=1))
            with self.assertRaisesRegex(ContractError, "future-dated"):
                runtime.perform(future, now=NOW)
            self.assertEqual(authorization.calls, [])

    def test_read_limit_fails_closed_without_returning_partial_content(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir:
            notes = Path(root_dir) / "notes"
            notes.mkdir()
            oversized = notes / "status.txt"
            oversized.write_bytes(b"x" * (MAX_SELECTED_ROOT_FILE_BYTES + 1))
            runtime = self._runtime(root_dir)
            with self.assertRaisesRegex(ContractError, "size limit"):
                runtime.perform(request(LocalFileOperation.READ), now=NOW)

    def test_windows_junction_escape_blocks_read_write_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as root_dir, tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir).resolve()
            sentinel = outside / "outside.txt"
            sentinel.write_bytes(b"must-remain-outside")
            junction = Path(root_dir) / "escape"
            created = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                check=False,
                capture_output=True,
                text=True,
                shell=False,
            )
            self.assertEqual(
                created.returncode,
                0,
                msg=f"failed to create Windows junction fixture: {created.stderr or created.stdout}",
            )
            try:
                runtime = self._runtime(root_dir)
                cases = (
                    request(LocalFileOperation.READ, path_relative=r"escape\outside.txt", action_id="junction_read"),
                    request(
                        LocalFileOperation.WRITE,
                        path_relative=r"escape\new.txt",
                        content=b"blocked",
                        action_id="junction_write",
                    ),
                    request(LocalFileOperation.DELETE, path_relative=r"escape\outside.txt", action_id="junction_delete"),
                )
                for file_request in cases:
                    with self.subTest(operation=file_request.operation.value):
                        with self.assertRaisesRegex(ContractError, "symlink or reparse point"):
                            runtime.perform(file_request, now=NOW)
                self.assertEqual(sentinel.read_bytes(), b"must-remain-outside")
                self.assertFalse((outside / "new.txt").exists())
            finally:
                if junction.exists():
                    os.rmdir(junction)


if __name__ == "__main__":
    unittest.main()
