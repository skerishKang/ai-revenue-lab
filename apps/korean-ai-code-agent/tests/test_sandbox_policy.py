from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import unittest

from kagent.contracts import (
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.sandbox import DeterministicFakeSandboxProvider, SandboxLeaseError
from kagent.sandbox_policy import (
    CLOUD_WORKSPACE_PATH_POLICY_DEFAULT_DENY,
    CLOUD_WORKSPACE_PATH_POLICY_PERFORMS_NO_FILESYSTEM_RESOLUTION,
    CLOUD_WORKSPACE_PATH_POLICY_PROVES_SYMLINK_SAFETY,
    CLOUD_WORKSPACE_REPARSE_TRAVERSAL_ALLOWED,
    CLOUD_WORKSPACE_ROOT_WILDCARD_EXPRESSIBLE,
    CLOUD_WORKSPACE_SYMLINK_TRAVERSAL_ALLOWED,
    CLOUD_WORKSPACE_TRAVERSAL_FOLLOWING_CONFIGURABLE,
    CLOUD_WORKSPACE_WRITABLE_WORKSPACE_BOOL_IS_AUTHORITY,
    CloudWorkspacePathDecision,
    CloudWorkspacePathPolicy,
    CloudWorkspacePathRule,
    IsolationPrimitive,
    PRODUCTION_SANDBOX_CLAIM,
    REAL_SANDBOX_PROVIDER_CALLS,
    REAL_SANDBOX_PROVIDER_SELECTED,
    SandboxArtifactManifest,
    SandboxArtifactPolicy,
    SandboxArtifactRef,
    SandboxFilesystemPolicy,
    SandboxLeaseSecurityPolicy,
    SandboxNetworkPolicy,
    SandboxProviderAcceptanceGate,
    SandboxProviderAssessment,
    SandboxProviderCapabilities,
    SandboxResourceLimits,
    VerifiedDiffEvidenceContract,
    WorkspacePathOperation,
)


class SandboxPolicyContractTests(unittest.TestCase):
    def test_network_policy_default_off(self):
        self.assertTrue(SandboxNetworkPolicy.OFF.is_deny_by_default)
        self.assertEqual(SandboxNetworkPolicy.OFF.value, "off")
        policy = SandboxLeaseSecurityPolicy()
        self.assertEqual(policy.network_policy, SandboxNetworkPolicy.OFF)
        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(network_policy=SandboxNetworkPolicy.RESTRICTED)

    def test_filesystem_policy_disallows_host_mounts_and_socket(self):
        fs = SandboxFilesystemPolicy()
        self.assertFalse(fs.host_mounts_allowed)
        self.assertFalse(fs.runtime_socket_exposed)
        self.assertFalse(fs.workspace_reuse_allowed)
        self.assertTrue(fs.checkout_hooks_disabled)

        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(host_mounts_allowed=True)
        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(runtime_socket_exposed=True)
        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(workspace_reuse_allowed=True)
        with self.assertRaises(ContractError):
            SandboxFilesystemPolicy(checkout_hooks_disabled=False)

    def test_security_policy_disallows_privileged_and_secret_inheritance(self):
        policy = SandboxLeaseSecurityPolicy()
        self.assertFalse(policy.privileged_runtime_allowed)
        self.assertFalse(policy.host_secret_inheritance_allowed)
        self.assertFalse(policy.provider_metadata_access_allowed)

        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(privileged_runtime_allowed=True)
        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(host_secret_inheritance_allowed=True)
        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(provider_metadata_access_allowed=True)

    def test_resource_limits_bounds(self):
        limits = SandboxResourceLimits()
        self.assertEqual(limits.max_cpu_cores, 4)
        self.assertEqual(limits.max_ttl_seconds, 3600)
        with self.assertRaises(ContractError):
            SandboxResourceLimits(max_ttl_seconds=5000)
        with self.assertRaises(ContractError):
            SandboxResourceLimits(max_cpu_cores=0)

    def test_artifact_policy_bounds_and_sanitization(self):
        art_policy = SandboxArtifactPolicy()
        self.assertTrue(art_policy.terminal_output_sanitized)
        with self.assertRaises(ContractError):
            SandboxArtifactPolicy(terminal_output_sanitized=False)
        with self.assertRaises(ContractError):
            SandboxArtifactPolicy(max_artifact_bytes=200 * 1024 * 1024)

    def test_acceptance_gate_validates_lease_request(self):
        gate = SandboxProviderAcceptanceGate()
        valid_req = SandboxLeaseRequest(
            run_id="run_101",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="skerishKang/example",
            requested_revision="1234567890abcdef",
            ttl_seconds=1200,
            network_policy=NetworkPolicy.OFF,
        )
        gate.validate_lease_request(valid_req)

        # Missing exact requested revision
        with self.assertRaises(ContractError):
            gate.validate_lease_request(
                SandboxLeaseRequest(
                    run_id="run_102",
                    execution_mode=ExecutionMode.CLOUD,
                    repository_ref="skerishKang/example",
                    requested_revision=None,
                    network_policy=NetworkPolicy.OFF,
                )
            )

        # Non-default network policy
        with self.assertRaises(ContractError):
            gate.validate_lease_request(
                SandboxLeaseRequest(
                    run_id="run_103",
                    execution_mode=ExecutionMode.CLOUD,
                    repository_ref="skerishKang/example",
                    requested_revision="1234567890abcdef",
                    network_policy=NetworkPolicy.RESTRICTED,
                )
            )

    def test_verified_diff_evidence_contract(self):
        evidence = VerifiedDiffEvidenceContract(
            run_id="run_101",
            lease_id="lease_101",
            repository_ref="skerishKang/ai-revenue-lab",
            input_revision="1234567890abcdef1234567890abcdef12345678",
            changed_files=("apps/kagent/src/app.py", "tests/test_app.py"),
            unified_diff_sha256="a" * 64,
            verification_command_id="pytest_allowlisted",
            verification_exit_code=0,
            verification_output_sha256="b" * 64,
            terminal_reason="completed",
            final_revision_ref="final_sha_123",
        )
        safe = evidence.safe_dict()
        self.assertEqual(safe["run_id"], "run_101")
        self.assertFalse(safe["raw_diff_in_projection"])
        self.assertFalse(safe["raw_terminal_output_in_projection"])

    def test_one_active_lease_and_no_resurrection(self):
        now = datetime(2026, 9, 8, 0, 0, tzinfo=timezone.utc)
        provider = DeterministicFakeSandboxProvider(clock=lambda: now)
        req = SandboxLeaseRequest(
            run_id="run_lifecycle",
            execution_mode=ExecutionMode.CLOUD,
            repository_ref="repo/test",
            requested_revision="abcdef123",
            ttl_seconds=600,
        )
        lease = provider.allocate(req)
        self.assertEqual(lease.state, SandboxLeaseState.RESERVED)

        # Cannot allocate second lease for same active run
        with self.assertRaises(SandboxLeaseError):
            provider.allocate(req)

        # Release lease
        released = provider.release(lease.lease_id, run_id="run_lifecycle")
        self.assertEqual(released.state, SandboxLeaseState.RELEASED)

        # Cannot resurrect or re-release released lease
        with self.assertRaises(SandboxLeaseError):
            provider.release(lease.lease_id, run_id="run_lifecycle")

    def test_zero_real_provider_mutation_in_act_a(self):
        self.assertFalse(REAL_SANDBOX_PROVIDER_SELECTED)
        self.assertEqual(REAL_SANDBOX_PROVIDER_CALLS, 0)
        self.assertFalse(PRODUCTION_SANDBOX_CLAIM)


class CloudWorkspacePathRuleTests(unittest.TestCase):
    """#2755 invariants 1-3, 5: what a single rule is even allowed to say."""

    def test_canonical_relative_read_only_rule_accepted(self):
        rule = CloudWorkspacePathRule("src/app.py", readable=True)
        self.assertEqual(rule.path_prefix_relative, "src/app.py")
        self.assertEqual(rule.granted_operations, frozenset({WorkspacePathOperation.READ}))

    def test_canonical_relative_write_rule_accepted(self):
        rule = CloudWorkspacePathRule(
            "src",
            readable=True,
            writable=True,
            create_allowed=True,
            delete_allowed=True,
        )
        self.assertEqual(
            rule.granted_operations,
            frozenset(WorkspacePathOperation),
        )

    def test_rule_normalizes_outer_whitespace_only(self):
        self.assertEqual(
            CloudWorkspacePathRule("  src/lib  ", readable=True).path_prefix_relative, "src/lib"
        )

    def test_rule_requiring_at_least_one_grant(self):
        with self.assertRaises(ContractError):
            CloudWorkspacePathRule("src")

    def test_rule_rejects_non_boolean_flags(self):
        for flag in ("readable", "writable", "create_allowed", "delete_allowed"):
            with self.subTest(flag=flag):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule("src", **{flag: 1})

    def test_absolute_posix_and_home_paths_rejected(self):
        for value in ("/abs/path", "/src", "~/secrets", "~"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, readable=True)

    def test_windows_drive_and_unc_forms_rejected(self):
        for value in ("C:/Windows", "d:/repo/src", "C:\\Users", "//server/share/x"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, readable=True)

    def test_parent_traversal_rejected(self):
        for value in ("..", "../out", "src/../../etc/passwd", "a/../b"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, readable=True)

    def test_backslash_and_control_characters_rejected_under_posix_wire_contract(self):
        for value in ("src\\app.py", "a/b\\c", "src\\sub\\x", "src/app\x00py", "src/app\npy", "src/app\tpy"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, readable=True)

    def test_empty_and_redundant_segments_rejected(self):
        # PurePosixPath would silently collapse these; refusing them is the point.
        for value in ("", "   ", "a//b", "./a", "a/.", "a/", "src//app.py"):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, readable=True)

    def test_wildcards_rejected_so_root_wide_grant_is_not_expressible(self):
        for value in ("*", "src/*", "*/app.py", "src/?.py", "src/[a]pp", "src/{app}", "."):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, writable=True)
        self.assertFalse(CLOUD_WORKSPACE_ROOT_WILDCARD_EXPRESSIBLE)

    def test_credential_sensitive_material_rejected_case_insensitively(self):
        for value in (
            "src/.env",
            "src/.ENV",
            "repo/.git/config",
            "keys/id_rsa",
            "a/credentials.json",
            "x/service.pem",
            "x/SERVICE.PEM",
            "deploy/tls.key",
            "cfg/.aws/credentials",
        ):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, readable=True)

    def test_path_length_bounded(self):
        CloudWorkspacePathRule("a" * 512, readable=True)
        with self.assertRaises(ContractError):
            CloudWorkspacePathRule("a" * 513, readable=True)

    def test_non_string_path_rejected(self):
        for value in (None, 123, b"src", ["src"], ("src",)):
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(value, readable=True)


class CloudWorkspacePathPolicyTests(unittest.TestCase):
    """#2755 invariants 4, 6-11 and the minimum-test matrix."""

    READ = WorkspacePathOperation.READ
    WRITE = WorkspacePathOperation.WRITE
    CREATE = WorkspacePathOperation.CREATE
    DELETE = WorkspacePathOperation.DELETE

    def policy(self, *rules: CloudWorkspacePathRule) -> CloudWorkspacePathPolicy:
        return CloudWorkspacePathPolicy(rules=tuple(rules))

    def test_default_policy_denies_everything(self):
        policy = CloudWorkspacePathPolicy()
        for operation in (self.READ, self.WRITE, self.CREATE, self.DELETE):
            with self.subTest(operation=operation):
                self.assertFalse(policy.authorize("src/app.py", operation))
        self.assertTrue(CLOUD_WORKSPACE_PATH_POLICY_DEFAULT_DENY)

    def test_unmatched_path_denied_while_matched_path_allowed(self):
        policy = self.policy(CloudWorkspacePathRule("src", readable=True))
        self.assertTrue(policy.authorize("src/app.py", self.READ))
        self.assertFalse(policy.authorize("docs/readme.md", self.READ))

    def test_read_only_rule_denies_write_create_delete(self):
        policy = self.policy(CloudWorkspacePathRule("src", readable=True))
        decision = policy.decide("src/app.py")
        self.assertTrue(decision.readable)
        self.assertFalse(decision.writable)
        self.assertFalse(decision.create_allowed)
        self.assertFalse(decision.delete_allowed)
        self.assertEqual(
            decision.denied_operations, frozenset({self.WRITE, self.CREATE, self.DELETE})
        )

    def test_write_rule_does_not_imply_delete_unless_explicit(self):
        write_only = self.policy(CloudWorkspacePathRule("out", readable=True, writable=True))
        self.assertTrue(write_only.authorize("out/report.txt", self.WRITE))
        self.assertFalse(write_only.authorize("out/report.txt", self.DELETE))
        self.assertFalse(write_only.authorize("out/report.txt", self.CREATE))

        with_delete = self.policy(
            CloudWorkspacePathRule("out", readable=True, writable=True, delete_allowed=True)
        )
        self.assertTrue(with_delete.authorize("out/report.txt", self.DELETE))

    def test_create_is_independent_of_write(self):
        write_only = self.policy(CloudWorkspacePathRule("out", writable=True))
        self.assertTrue(write_only.authorize("out/existing.txt", self.WRITE))
        self.assertFalse(write_only.authorize("out/new.txt", self.CREATE))

    def test_writable_workspace_true_grants_no_path_write_authority(self):
        fs = SandboxFilesystemPolicy()
        self.assertTrue(fs.writable_workspace)

        lease = SandboxLeaseSecurityPolicy()
        self.assertTrue(lease.filesystem_policy.writable_workspace)
        self.assertEqual(lease.path_policy.rules, ())
        for operation in (self.READ, self.WRITE, self.CREATE, self.DELETE):
            with self.subTest(operation=operation):
                self.assertFalse(lease.path_policy.authorize("src/app.py", operation))

        self.assertFalse(CLOUD_WORKSPACE_WRITABLE_WORKSPACE_BOOL_IS_AUTHORITY)

    def test_existing_filesystem_threat_model_booleans_still_enforced(self):
        for kwargs in (
            {"host_mounts_allowed": True},
            {"runtime_socket_exposed": True},
            {"workspace_reuse_allowed": True},
            {"checkout_hooks_disabled": False},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ContractError):
                    SandboxFilesystemPolicy(**kwargs)
        with self.assertRaises(ContractError):
            SandboxLeaseSecurityPolicy(path_policy="not-a-policy")

    def test_duplicate_prefix_rules_rejected(self):
        with self.assertRaises(ContractError):
            self.policy(
                CloudWorkspacePathRule("src", readable=True),
                CloudWorkspacePathRule("src", writable=True),
            )

    def test_duplicate_rejected_after_normalization(self):
        with self.assertRaises(ContractError):
            self.policy(
                CloudWorkspacePathRule("  src  ", readable=True),
                CloudWorkspacePathRule("src", writable=True),
            )

    def test_nested_rule_may_narrow_but_never_widen(self):
        narrowed = self.policy(
            CloudWorkspacePathRule("src", readable=True, writable=True),
            CloudWorkspacePathRule("src/vendor", readable=True),
        )
        self.assertTrue(narrowed.authorize("src/app.py", self.WRITE))
        self.assertFalse(narrowed.authorize("src/vendor/lib.js", self.WRITE))
        self.assertTrue(narrowed.authorize("src/vendor/lib.js", self.READ))

        with self.assertRaises(ContractError) as caught:
            self.policy(
                CloudWorkspacePathRule("src", readable=True),
                CloudWorkspacePathRule("src/secret", writable=True),
            )
        self.assertIn("may not grant", str(caught.exception))

    def test_sibling_rules_do_not_constrain_each_other(self):
        policy = self.policy(
            CloudWorkspacePathRule("src", readable=True),
            CloudWorkspacePathRule("out", writable=True),
        )
        self.assertTrue(policy.authorize("src/app.py", self.READ))
        self.assertTrue(policy.authorize("out/report.txt", self.WRITE))
        self.assertFalse(policy.authorize("out/report.txt", self.READ))

    def test_prefix_matching_is_segment_aware(self):
        policy = self.policy(CloudWorkspacePathRule("src", readable=True))
        self.assertFalse(policy.authorize("srcdir/app.py", self.READ))
        self.assertFalse(policy.authorize("notsrc/x", self.READ))
        self.assertTrue(policy.authorize("src/a/b/c", self.READ))

    def test_rule_count_bounded(self):
        at_limit = tuple(
            CloudWorkspacePathRule(f"dir{index}", readable=True) for index in range(64)
        )
        CloudWorkspacePathPolicy(rules=at_limit)
        with self.assertRaises(ContractError):
            CloudWorkspacePathPolicy(rules=at_limit + (CloudWorkspacePathRule("dir999", readable=True),))

    def test_rules_must_be_rule_objects(self):
        with self.assertRaises(ContractError):
            CloudWorkspacePathPolicy(rules=("src",))
        with self.assertRaises(ContractError):
            CloudWorkspacePathPolicy(rules=[CloudWorkspacePathRule("src", readable=True)])

    def test_denied_defaults_are_not_escalatable(self):
        for kwargs in (
            {"default_read": True},
            {"default_write": True},
            {"default_create": True},
            {"default_delete": True},
        ):
            with self.subTest(**kwargs):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathPolicy(**kwargs)

    def test_identical_input_produces_identical_decision(self):
        rules = (
            CloudWorkspacePathRule("src", readable=True, writable=True),
            CloudWorkspacePathRule("src/vendor", readable=True),
        )
        first = self.policy(*rules).decide("src/vendor/a.js")
        second = self.policy(*rules).decide("src/vendor/a.js")
        self.assertEqual(first, second)
        self.assertEqual(first.safe_dict(), second.safe_dict())

    def test_resolution_is_independent_of_rule_declaration_order(self):
        forward = (
            CloudWorkspacePathRule("src", readable=True, writable=True, delete_allowed=True),
            CloudWorkspacePathRule("src/vendor", readable=True, writable=True),
            CloudWorkspacePathRule("src/vendor/lock", readable=True),
        )
        reversed_ = tuple(reversed(forward))
        for path in ("src/app.py", "src/vendor/a.js", "src/vendor/lock/x"):
            for operation in (self.READ, self.WRITE, self.CREATE, self.DELETE):
                with self.subTest(path=path, operation=operation):
                    self.assertEqual(
                        self.policy(*forward).authorize(path, operation),
                        self.policy(*reversed_).authorize(path, operation),
                    )

    def test_deep_nesting_intersects_every_covering_rule(self):
        policy = self.policy(
            CloudWorkspacePathRule("a", readable=True, writable=True, create_allowed=True),
            CloudWorkspacePathRule("a/b", readable=True, create_allowed=True),
            CloudWorkspacePathRule("a/b/c", readable=True),
        )
        decision = policy.decide("a/b/c/d.txt")
        self.assertTrue(decision.readable)
        self.assertFalse(decision.writable)
        self.assertFalse(decision.create_allowed)
        self.assertFalse(decision.delete_allowed)
        self.assertEqual(decision.matched_rule_prefixes, ("a", "a/b", "a/b/c"))

        # Each level really is consulted: the middle grant survives its own narrowing.
        self.assertTrue(policy.authorize("a/b/direct.txt", self.CREATE))
        self.assertTrue(policy.authorize("a/top.txt", self.WRITE))

    def test_a_descendant_may_not_add_an_operation_its_ancestor_denies(self):
        # Deliberate strictness (#2755 invariant 7): write authority is only ever
        # expressed top-down, so a nested rule cannot smuggle an operation back in.
        for ancestor_grants, descendant_grants in (
            ({"readable": True}, {"create_allowed": True}),
            ({"readable": True}, {"delete_allowed": True}),
            ({"readable": True, "writable": True}, {"delete_allowed": True}),
        ):
            with self.subTest(ancestor=ancestor_grants, descendant=descendant_grants):
                with self.assertRaises(ContractError):
                    self.policy(
                        CloudWorkspacePathRule("a", **ancestor_grants),
                        CloudWorkspacePathRule("a/b", **descendant_grants),
                    )

    def test_authorize_rejects_non_enum_operation(self):
        policy = self.policy(CloudWorkspacePathRule("src", readable=True))
        for invalid in ("read", None, 1):
            with self.subTest(operation=invalid):
                with self.assertRaises(ContractError):
                    policy.authorize("src/app.py", invalid)

    def test_decide_rejects_unsafe_path(self):
        policy = self.policy(CloudWorkspacePathRule("src", readable=True))
        for invalid in ("/etc/passwd", "../outside", "src/../../x", "C:/x", "src//x"):
            with self.subTest(path=invalid):
                with self.assertRaises(ContractError):
                    policy.decide(invalid)

    def test_safe_projection_contains_only_relative_paths_and_booleans(self):
        policy = self.policy(
            CloudWorkspacePathRule("src", readable=True, writable=True),
            CloudWorkspacePathRule("src/vendor", readable=True),
        )
        projections = {
            "policy": policy.safe_dict(),
            "rule": policy.rules[0].safe_dict(),
            "decision": policy.decide("src/vendor/a.js").safe_dict(),
        }
        forbidden = (
            "host",
            "mount",
            "endpoint",
            "credential",
            "socket",
            "secret",
            "password",
            "token",
            "device",
            "driver",
            "image",
            "abs",
        )

        def walk(node: object, trail: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    self.assertIsInstance(key, str)
                    leaked = [token for token in forbidden if token in key.lower()]
                    self.assertEqual(leaked, [], f"{trail}.{key}")
                    walk(value, f"{trail}.{key}")
            elif isinstance(node, (list, tuple)):
                for item in node:
                    walk(item, trail)
            elif isinstance(node, str):
                self.assertFalse(node.startswith("/"))
                self.assertNotIn("\\", node)
                self.assertNotIn("..", node)
                self.assertNotIn(":", node)
            else:
                self.assertIsInstance(node, bool, trail)

        for name, projection in projections.items():
            with self.subTest(projection=name):
                walk(projection, name)

    def test_decision_is_a_frozen_value_object(self):
        decision = self.policy(CloudWorkspacePathRule("src", readable=True)).decide("src/a.py")
        self.assertIsInstance(decision, CloudWorkspacePathDecision)
        with self.assertRaises(AttributeError):
            decision.readable = False


class CloudWorkspacePathTraversalDenyTests(unittest.TestCase):
    """#2755 review blocker: a lexical prefix match cannot see a symlink.

    ``workspace/link/file.txt`` is unremarkable as a string even when ``link`` points
    at ``/outside``. These tests pin the contract that Cloud M1 never follows such a
    link, and that no caller or provider configuration can turn that back on.
    """

    READ = WorkspacePathOperation.READ

    def policy(self, **kwargs: object) -> CloudWorkspacePathPolicy:
        return CloudWorkspacePathPolicy(
            rules=(CloudWorkspacePathRule("workspace", readable=True, writable=True),),
            **kwargs,
        )

    def test_traversal_following_defaults_are_deny(self):
        policy = self.policy()
        self.assertFalse(policy.follow_symlinks)
        self.assertFalse(policy.follow_reparse_points)

    def test_enabled_traversal_is_rejected_for_both_flags(self):
        for flag in ("follow_symlinks", "follow_reparse_points"):
            with self.subTest(flag=flag):
                with self.assertRaises(ContractError) as caught:
                    self.policy(**{flag: True})
                self.assertIn("must be false", str(caught.exception))

    def test_non_boolean_traversal_values_are_rejected(self):
        for flag in ("follow_symlinks", "follow_reparse_points"):
            for value in (1, 0, None, "no", (),):
                with self.subTest(flag=flag, value=value):
                    with self.assertRaises(ContractError):
                        self.policy(**{flag: value})

    def test_replace_cannot_escalate_the_traversal_denial(self):
        policy = self.policy()
        for flag in ("follow_symlinks", "follow_reparse_points"):
            with self.subTest(flag=flag):
                with self.assertRaises(ContractError):
                    replace(policy, **{flag: True})

    def test_frozen_policy_rejects_direct_attribute_assignment(self):
        policy = self.policy()
        for flag in ("follow_symlinks", "follow_reparse_points"):
            with self.subTest(flag=flag):
                with self.assertRaises(AttributeError):
                    setattr(policy, flag, True)

    def test_explicitly_disabled_traversal_is_accepted(self):
        policy = CloudWorkspacePathPolicy(
            follow_symlinks=False, follow_reparse_points=False
        )
        self.assertFalse(policy.follow_symlinks)
        self.assertFalse(policy.follow_reparse_points)

    def test_projection_exposes_only_the_false_traversal_state(self):
        projection = self.policy().safe_dict()
        self.assertIs(projection["follow_symlinks"], False)
        self.assertIs(projection["follow_reparse_points"], False)
        forbidden = (
            "host",
            "mount",
            "endpoint",
            "credential",
            "socket",
            "secret",
            "provider",
            "runtime",
            "inode",
            "device",
            "driver",
            "resolved",
            "realpath",
        )
        leaked = [key for key in projection if any(t in key.lower() for t in forbidden)]
        self.assertEqual(leaked, [])
        for rule in projection["rules"]:
            leaked = [key for key in rule if any(t in key.lower() for t in forbidden)]
            self.assertEqual(leaked, [])

    def test_policy_is_link_blind_so_following_cannot_be_judged_per_path(self):
        # A symlinked segment and an ordinary segment decide identically. The policy
        # cannot tell them apart, which is exactly why following must be refused
        # outright instead of evaluated per path.
        policy = self.policy()
        ordinary = policy.decide("workspace/dir/file.txt")
        via_link = policy.decide("workspace/link/file.txt")
        self.assertEqual(ordinary.readable, via_link.readable)
        self.assertEqual(ordinary.writable, via_link.writable)
        self.assertEqual(ordinary.matched_rule_prefixes, via_link.matched_rule_prefixes)

    def test_permitted_lexical_decision_is_not_symlink_safety_proof(self):
        policy = self.policy()
        self.assertTrue(policy.authorize("workspace/link/file.txt", self.READ))
        self.assertFalse(policy.follow_symlinks)
        self.assertFalse(CLOUD_WORKSPACE_PATH_POLICY_PROVES_SYMLINK_SAFETY)
        self.assertFalse(CLOUD_WORKSPACE_SYMLINK_TRAVERSAL_ALLOWED)
        self.assertFalse(CLOUD_WORKSPACE_REPARSE_TRAVERSAL_ALLOWED)
        self.assertFalse(CLOUD_WORKSPACE_TRAVERSAL_FOLLOWING_CONFIGURABLE)
        self.assertTrue(CLOUD_WORKSPACE_PATH_POLICY_PERFORMS_NO_FILESYSTEM_RESOLUTION)

    def test_traversal_gate_does_not_change_existing_path_decision_semantics(self):
        policy = self.policy()
        self.assertTrue(policy.authorize("workspace/app.py", self.READ))
        self.assertFalse(policy.authorize("workspace/app.py", WorkspacePathOperation.DELETE))
        self.assertFalse(policy.authorize("other/app.py", self.READ))
        self.assertFalse(CloudWorkspacePathPolicy().authorize("workspace/app.py", self.READ))

    def test_traversal_gate_does_not_relax_nested_or_root_rules(self):
        with self.assertRaises(ContractError):
            CloudWorkspacePathPolicy(
                rules=(
                    CloudWorkspacePathRule("src", readable=True),
                    CloudWorkspacePathRule("src/x", writable=True),
                )
            )
        for unexpressible in ("*", "/", "."):
            with self.subTest(prefix=unexpressible):
                with self.assertRaises(ContractError):
                    CloudWorkspacePathRule(unexpressible, writable=True)

    def test_writable_workspace_bool_still_grants_no_traversal_either(self):
        lease = SandboxLeaseSecurityPolicy()
        self.assertTrue(lease.filesystem_policy.writable_workspace)
        self.assertFalse(lease.path_policy.follow_symlinks)
        self.assertFalse(lease.path_policy.follow_reparse_points)
        self.assertFalse(
            lease.path_policy.authorize("workspace/link/file.txt", self.READ)
        )


if __name__ == "__main__":
    unittest.main()
