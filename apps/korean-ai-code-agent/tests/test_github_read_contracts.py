from __future__ import annotations

import unittest

from kagent.contracts import ContractError
from kagent.github_read_contracts import (
    EXTERNAL_GITHUB_TEXT_IS_UNTRUSTED,
    GITHUB_APP_PREFERRED,
    PERSONAL_ACCESS_TOKEN_PREFERRED,
    REAL_GITHUB_READ_CONFIGURED,
    REPOSITORY_ALLOWLIST_REQUIRED,
    DeterministicFakeGitHubReadPort,
    GitHubContextKind,
    GitHubContextReadRequest,
    GitHubInstallationBinding,
    GitHubReadCapability,
    GitHubReadService,
    GitHubRepositoryReadRequest,
)


SHA = "a" * 40


def binding(**kwargs):
    values = dict(
        binding_ref="binding_1",
        installation_ref="installation_1",
        actor_ref="actor_1",
        workspace_ref="workspace_1",
        allowed_repositories=("skerishKang/ai-revenue-lab",),
    )
    values.update(kwargs)
    return GitHubInstallationBinding(**values)


class GitHubReadContractTests(unittest.TestCase):
    def test_github_app_binding_requires_nonempty_exact_repository_allowlist(self):
        item = binding()
        rendered = item.safe_dict()
        self.assertTrue(rendered["github_app"])
        self.assertEqual(rendered["allowed_repositories"], ["skerishKang/ai-revenue-lab"])
        self.assertFalse(rendered["raw_installation_token"])
        self.assertFalse(rendered["raw_private_key"])
        self.assertFalse(rendered["personal_access_token"])
        with self.assertRaises(ContractError):
            binding(allowed_repositories=())
        with self.assertRaises(ContractError):
            binding(github_app=False)

    def test_repository_outside_installation_allowlist_fails_before_port_call(self):
        port = DeterministicFakeGitHubReadPort()
        service = GitHubReadService(binding(), port)
        with self.assertRaises(ContractError):
            service.read_repository(
                GitHubRepositoryReadRequest(
                    request_id="request_1",
                    repository="other/repository",
                    exact_revision=SHA,
                )
            )
        self.assertEqual(port.repository_reads, [])

    def test_exact_revision_repository_snapshot_is_correlated_and_safe(self):
        port = DeterministicFakeGitHubReadPort()
        service = GitHubReadService(binding(), port)
        snapshot = service.read_repository(
            GitHubRepositoryReadRequest(
                request_id="request_1",
                repository="skerishKang/ai-revenue-lab",
                exact_revision=SHA,
            )
        )
        self.assertEqual(snapshot.requested_revision, SHA)
        self.assertEqual(snapshot.observed_revision, SHA)
        self.assertEqual(snapshot.default_branch, "main")
        self.assertFalse(snapshot.safe_dict()["repository_contents_embedded"])
        self.assertEqual(len(port.repository_reads), 1)

    def test_mutable_or_short_revision_is_rejected(self):
        for revision in ("main", "abc1234", "b" * 39, "g" * 40):
            with self.subTest(revision=revision):
                with self.assertRaises(ContractError):
                    GitHubRepositoryReadRequest(
                        request_id="request_1",
                        repository="skerishKang/ai-revenue-lab",
                        exact_revision=revision,
                    )

    def test_issue_and_pull_request_context_are_bounded_and_marked_untrusted(self):
        port = DeterministicFakeGitHubReadPort()
        service = GitHubReadService(binding(), port)
        for kind in (GitHubContextKind.ISSUE, GitHubContextKind.PULL_REQUEST):
            with self.subTest(kind=kind):
                snapshot = service.read_context(
                    GitHubContextReadRequest(
                        request_id=f"request_{kind.value}",
                        repository="skerishKang/ai-revenue-lab",
                        kind=kind,
                        number=42,
                    )
                )
                rendered = snapshot.safe_dict()
                self.assertTrue(rendered["untrusted_external_content"])
                self.assertFalse(rendered["raw_credentials"])
                self.assertLessEqual(len(snapshot.text), 20_000)

    def test_check_status_read_is_bound_to_exact_revision(self):
        port = DeterministicFakeGitHubReadPort()
        service = GitHubReadService(binding(), port)
        snapshot = service.read_context(
            GitHubContextReadRequest(
                request_id="request_checks",
                repository="skerishKang/ai-revenue-lab",
                kind=GitHubContextKind.CHECK_STATUS,
                exact_revision=SHA,
            )
        )
        self.assertEqual(snapshot.exact_revision, SHA)
        self.assertFalse(snapshot.safe_dict()["untrusted_external_content"])

    def test_missing_capability_fails_before_port_call(self):
        port = DeterministicFakeGitHubReadPort()
        service = GitHubReadService(
            binding(capabilities=(GitHubReadCapability.REPOSITORY_METADATA, GitHubReadCapability.TREE_FILE_BLOB)),
            port,
        )
        with self.assertRaises(ContractError):
            service.read_context(
                GitHubContextReadRequest(
                    request_id="request_issue",
                    repository="skerishKang/ai-revenue-lab",
                    kind=GitHubContextKind.ISSUE,
                    number=1,
                )
            )
        self.assertEqual(port.context_reads, [])

    def test_issue_pr_and_check_request_shapes_fail_closed(self):
        with self.assertRaises(ContractError):
            GitHubContextReadRequest(
                request_id="request_issue",
                repository="skerishKang/ai-revenue-lab",
                kind=GitHubContextKind.ISSUE,
                number=None,
            )
        with self.assertRaises(ContractError):
            GitHubContextReadRequest(
                request_id="request_check",
                repository="skerishKang/ai-revenue-lab",
                kind=GitHubContextKind.CHECK_STATUS,
                number=1,
                exact_revision=SHA,
            )
        with self.assertRaises(ContractError):
            GitHubContextReadRequest(
                request_id="request_check",
                repository="skerishKang/ai-revenue-lab",
                kind=GitHubContextKind.CHECK_STATUS,
            )

    def test_provider_output_credentials_are_redacted_in_context_snapshot(self):
        from kagent.github_read_contracts import GitHubContextSnapshot

        snapshot = GitHubContextSnapshot(
            request_id="request_1",
            repository="skerishKang/ai-revenue-lab",
            kind=GitHubContextKind.ISSUE,
            context_ref="issue:1",
            text="token=topsecretvalue",
            item_count=1,
        )
        self.assertNotIn("topsecretvalue", snapshot.text)

    def test_authority_nonclaims_are_explicit(self):
        self.assertTrue(GITHUB_APP_PREFERRED)
        self.assertFalse(PERSONAL_ACCESS_TOKEN_PREFERRED)
        self.assertFalse(REAL_GITHUB_READ_CONFIGURED)
        self.assertTrue(REPOSITORY_ALLOWLIST_REQUIRED)
        self.assertTrue(EXTERNAL_GITHUB_TEXT_IS_UNTRUSTED)


if __name__ == "__main__":
    unittest.main()
