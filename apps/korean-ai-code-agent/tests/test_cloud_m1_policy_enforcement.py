"""Cloud M1 policy enforcement and provider-neutral conformance (#1405 A/B).

The threat model states the controls; these tests pin that the policy the
conformance gate actually validates against can express them, refuses a
provider that reports more than the ceiling allows, refuses an artifact kind
the server never authorized, and can prove a "sanitized" terminal-output claim
against the bytes it was made from. Everything here is deterministic and
provider-free: no socket, no credential, no real sandbox.
"""

from __future__ import annotations

import dataclasses
import hashlib
import unittest

from kagent.contracts import ContractError
from kagent.sandbox_conformance import (
    PRODUCTION_SANDBOX_CLAIM,
    REAL_SANDBOX_PROVIDER_CALLS,
    REAL_SANDBOX_PROVIDER_SELECTED,
    SANDBOX_ALLOWED_ARTIFACT_KINDS,
    SandboxAppliedLimits,
    SandboxArtifactManifest,
    SandboxArtifactRef,
    SandboxProviderCapabilities,
    SandboxSecurityPolicy,
    sanitize_terminal_output,
)
from kagent.sandbox_conformance_harness import (
    IsolationPrimitive,
    SandboxProviderConformanceHarness,
)

_DIGEST = hashlib.sha256(b"cloud-m1-policy-enforcement").hexdigest()

# Carries a CSI colour sequence, an OSC title and a stray control byte, so the
# sanitized form is strictly shorter than the raw form and a proof that only
# re-derives correctly can tell them apart.
_RAW_TERMINAL = "build \x1b[31mFAILED\x1b[0m\rlink \x1b]0;title\x07done\nnext\ttab"


def _manifest(artifacts: tuple[SandboxArtifactRef, ...], *, output_bytes: int = 0) -> SandboxArtifactManifest:
    return SandboxArtifactManifest(
        run_id="run_policy_enforcement",
        lease_id="lease_policy_enforcement",
        artifacts=artifacts,
        terminal_output_bytes=output_bytes,
        terminal_output_sanitized=True,
    )


def _artifact(artifact_id: str, kind: str, size_bytes: int = 512) -> SandboxArtifactRef:
    return SandboxArtifactRef(artifact_id, kind, size_bytes, _DIGEST)


def _conforming_capabilities(**overrides: object) -> SandboxProviderCapabilities:
    fields = {
        field.name
        for field in dataclasses.fields(SandboxProviderCapabilities)
        if field.name not in {"provider_id", "isolation_primitive"}
    }
    values: dict[str, object] = {name: True for name in fields}
    values.update(overrides)
    return SandboxProviderCapabilities(
        provider_id="conformance-fake",
        isolation_primitive=IsolationPrimitive.MICROVM,
        **values,  # type: ignore[arg-type]
    )


class SandboxResourceCeilingTests(unittest.TestCase):
    def test_enforced_policy_states_the_resource_ceiling(self):
        policy = SandboxSecurityPolicy()
        self.assertEqual(policy.max_cpu_cores, 4)
        self.assertEqual(policy.max_memory_mb, 8192)
        self.assertEqual(policy.max_disk_mb, 10240)
        self.assertEqual(policy.max_process_count, 256)

    def test_ceiling_cannot_be_widened_past_the_documented_range(self):
        for field_name, too_big in (
            ("max_cpu_cores", 65),
            ("max_memory_mb", 65537),
            ("max_disk_mb", 102401),
            ("max_process_count", 2049),
        ):
            with self.subTest(field=field_name):
                with self.assertRaises(ContractError):
                    SandboxSecurityPolicy(**{field_name: too_big})


class AppliedLimitsTests(unittest.TestCase):
    def test_limits_within_the_ceiling_are_accepted(self):
        SandboxSecurityPolicy().require_within_bounds(
            SandboxAppliedLimits(cpu_cores=4, memory_mb=8192, disk_mb=10240, process_count=256)
        )

    def test_each_dimension_is_named_when_it_exceeds_the_ceiling(self):
        cases = (
            (SandboxAppliedLimits(cpu_cores=8, memory_mb=1024, disk_mb=1024, process_count=64), "cpu_cores"),
            (SandboxAppliedLimits(cpu_cores=1, memory_mb=65536, disk_mb=1024, process_count=64), "memory_mb"),
            (SandboxAppliedLimits(cpu_cores=1, memory_mb=1024, disk_mb=999999, process_count=64), "disk_mb"),
            (SandboxAppliedLimits(cpu_cores=1, memory_mb=1024, disk_mb=1024, process_count=4096), "process_count"),
        )
        for limits, dimension in cases:
            with self.subTest(dimension=dimension):
                with self.assertRaisesRegex(ContractError, dimension):
                    SandboxSecurityPolicy().require_within_bounds(limits)

    def test_harness_scores_reported_limits_instead_of_trusting_the_booleans(self):
        harness = SandboxProviderConformanceHarness()
        accepted = harness.evaluate_capabilities(
            _conforming_capabilities(),
            applied_limits=SandboxAppliedLimits(cpu_cores=2, memory_mb=4096, disk_mb=5120, process_count=128),
        )
        self.assertTrue(accepted.overall_conforming)
        limits_case = next(r for r in accepted.results if r.case_id == "case_resource_limits_within_policy")
        self.assertTrue(limits_case.passed)

        # The four *_limit_enforced booleans stay True here: only the reported
        # numbers fail, which is the point of checking what was applied.
        refused = harness.evaluate_capabilities(
            _conforming_capabilities(),
            applied_limits=SandboxAppliedLimits(cpu_cores=32, memory_mb=4096, disk_mb=5120, process_count=128),
        )
        self.assertFalse(refused.overall_conforming)
        self.assertIn("resource_limits_within_policy", refused.failed_controls)
        limits_case = next(r for r in refused.results if r.case_id == "case_resource_limits_within_policy")
        self.assertFalse(limits_case.passed)

    def test_no_limit_values_cannot_reach_acceptance(self):
        """CENTRAL blocker 1: four true booleans alone must not conform.

        Before this check the case was simply not created when a provider reported no
        numbers, so a fully-declared candidate still reached overall_conforming.
        """
        harness = SandboxProviderConformanceHarness()
        report = harness.evaluate_capabilities(_conforming_capabilities())
        self.assertFalse(report.overall_conforming)
        self.assertIn("resource_limits_reported", report.failed_controls)
        case = next(r for r in report.results if r.case_id == "case_resource_limits_reported")
        self.assertFalse(case.passed)
        self.assertIn("no CPU/memory/disk/process limit values", case.message)

    def test_limits_are_scored_before_any_boolean_shortcut(self):
        """Within ceiling passes, exceeding fails, absent fails — one axis, three outcomes."""
        harness = SandboxProviderConformanceHarness()
        caps = _conforming_capabilities()
        self.assertTrue(
            harness.evaluate_capabilities(
                caps,
                applied_limits=SandboxAppliedLimits(cpu_cores=1, memory_mb=512, disk_mb=512, process_count=16),
            ).overall_conforming
        )
        self.assertFalse(
            harness.evaluate_capabilities(
                caps,
                applied_limits=SandboxAppliedLimits(cpu_cores=64, memory_mb=512, disk_mb=512, process_count=16),
            ).overall_conforming
        )
        self.assertFalse(harness.evaluate_capabilities(caps).overall_conforming)


class ArtifactExportAllowlistTests(unittest.TestCase):
    def test_allowlisted_kinds_are_accepted(self):
        policy = SandboxSecurityPolicy()
        artifacts = tuple(_artifact(f"artifact_{index}", kind) for index, kind in enumerate(policy.allowed_artifact_kinds))
        _manifest(artifacts).validate_against(policy)

    def test_unlisted_kind_is_refused_even_when_size_and_count_are_in_policy(self):
        policy = SandboxSecurityPolicy(max_artifact_bytes=4096, max_artifact_count=10)
        with self.assertRaisesRegex(ContractError, "allowlist"):
            _manifest((_artifact("artifact_1", "core_dump"),)).validate_against(policy)

    def test_allowlist_itself_cannot_be_emptied_or_duplicated(self):
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(allowed_artifact_kinds=())
        with self.assertRaises(ContractError):
            SandboxSecurityPolicy(allowed_artifact_kinds=("diff", "diff"))

    def test_the_two_policy_views_agree_on_the_allowlist(self):
        """sandbox_policy.py must not keep a second copy that can drift."""
        from kagent import sandbox_policy

        canonical = SandboxSecurityPolicy()
        self.assertEqual(sandbox_policy.SandboxArtifactPolicy().allowed_artifact_kinds, canonical.allowed_artifact_kinds)
        limits = sandbox_policy.SandboxResourceLimits()
        self.assertEqual(limits.max_cpu_cores, canonical.max_cpu_cores)
        self.assertEqual(limits.max_memory_mb, canonical.max_memory_mb)
        self.assertEqual(limits.max_disk_mb, canonical.max_disk_mb)
        self.assertEqual(limits.max_process_count, canonical.max_process_count)


class TerminalOutputSanitizationTests(unittest.TestCase):
    RAW = "build \x1b[31mFAILED\x1b[0m\rlink \x1b]0;title\x07done\x07\x1b[?25l\x08\nnext\ttab"

    def test_control_sequences_and_control_characters_are_removed(self):
        sanitized = sanitize_terminal_output(self.RAW, limit=4096)
        for needle in ("\x1b", "\r", "\x08", "\x07", "[31m", "]0;title", "[?25l"):
            self.assertNotIn(needle, sanitized, needle)
        self.assertIn("build FAILED", sanitized)
        # Legitimate layout survives; only control machinery is removed.
        self.assertIn("\n", sanitized)
        self.assertIn("\t", sanitized)

    def test_sanitization_is_idempotent(self):
        once = sanitize_terminal_output(self.RAW, limit=4096)
        self.assertEqual(sanitize_terminal_output(once, limit=4096), once)

    def test_an_unterminated_escape_never_survives_as_a_live_sequence(self):
        # ESC itself lies inside the stripped control range, so a truncated
        # sequence cannot be reassembled with following text by a later renderer.
        # An unterminated OSC may still leave its payload as inert characters, which
        # is what this pins — not a claim that every body byte is removed.
        self.assertEqual(sanitize_terminal_output("tail\x1b", limit=64), "tail")
        without_esc = sanitize_terminal_output("x\x1b]0;t", limit=64)
        self.assertNotIn("\x1b", without_esc)
        self.assertEqual(without_esc, "x0;t")

    def test_oversize_output_is_refused_rather_than_truncated(self):
        with self.assertRaisesRegex(ContractError, "exceeds"):
            sanitize_terminal_output("x" * 4096, limit=1024)

    def test_a_sanitization_claim_is_provable_and_falsifiable(self):
        policy = SandboxSecurityPolicy(max_artifact_bytes=4096, max_artifact_count=10)
        sanitized = sanitize_terminal_output(self.RAW, limit=policy.max_terminal_output_bytes)
        honest = _manifest((_artifact("artifact_1", "diff"),), output_bytes=len(sanitized.encode("utf-8")))
        self.assertEqual(honest.require_sanitized_output(self.RAW, policy), sanitized)

        overclaimed = _manifest((_artifact("artifact_1", "diff"),), output_bytes=len(sanitized.encode("utf-8")) + 1)
        with self.assertRaisesRegex(ContractError, "sanitized output length"):
            overclaimed.require_sanitized_output(self.RAW, policy)

        raw_as_fact = _manifest((_artifact("artifact_1", "diff"),), output_bytes=len(self.RAW.encode("utf-8")))
        with self.assertRaisesRegex(ContractError, "sanitized output length"):
            raw_as_fact.require_sanitized_output(self.RAW, policy)

    def test_limit_argument_is_validated(self):
        for bad in (0, -1, True, "4096"):
            with self.subTest(limit=bad):
                with self.assertRaises(ContractError):
                    sanitize_terminal_output("plain text", limit=bad)  # type: ignore[arg-type]


class HarnessSanitizationProofTests(unittest.TestCase):
    """CENTRAL blocker 2: the acceptance path must not award a pass to a self-asserted flag."""

    def _manifest_for(self, raw: str, limit: int = 4096) -> SandboxArtifactManifest:
        sanitized = sanitize_terminal_output(raw, limit=limit)
        return _manifest((_artifact("artifact_1", "diff"),), output_bytes=len(sanitized.encode("utf-8")))

    def test_proven_sanitized_output_is_accepted(self):
        harness = SandboxProviderConformanceHarness()
        manifest = self._manifest_for(_RAW_TERMINAL)
        self.assertTrue(harness.evaluate_artifact_manifest(manifest, raw_terminal_output=_RAW_TERMINAL))

    def test_self_asserted_boolean_alone_fails_closed(self):
        harness = SandboxProviderConformanceHarness()
        manifest = self._manifest_for(_RAW_TERMINAL)
        self.assertFalse(harness.evaluate_artifact_manifest(manifest))

    def test_a_run_with_no_output_still_has_to_offer_evidence(self):
        harness = SandboxProviderConformanceHarness()
        empty = _manifest((_artifact("artifact_1", "diff"),), output_bytes=0)
        self.assertTrue(harness.evaluate_artifact_manifest(empty, raw_terminal_output=""))
        self.assertFalse(harness.evaluate_artifact_manifest(empty))

    def test_mismatched_sanitized_length_is_refused(self):
        harness = SandboxProviderConformanceHarness()
        manifest = self._manifest_for(_RAW_TERMINAL)
        inflated = _manifest(
            (_artifact("artifact_1", "diff"),),
            output_bytes=manifest.terminal_output_bytes + 1,
        )
        self.assertFalse(harness.evaluate_artifact_manifest(inflated, raw_terminal_output=_RAW_TERMINAL))

    def test_the_proof_measures_sanitized_bytes_not_raw_bytes(self):
        """The raw form is longer here, so a shallow check would accept the wrong number."""
        harness = SandboxProviderConformanceHarness()
        raw_length_manifest = _manifest(
            (_artifact("artifact_1", "diff"),),
            output_bytes=len(_RAW_TERMINAL.encode("utf-8")),
        )
        self.assertNotEqual(len(_RAW_TERMINAL.encode("utf-8")), self._manifest_for(_RAW_TERMINAL).terminal_output_bytes)
        self.assertFalse(
            harness.evaluate_artifact_manifest(raw_length_manifest, raw_terminal_output=_RAW_TERMINAL)
        )

    def test_oversize_output_fails_through_the_harness(self):
        policy = SandboxSecurityPolicy(max_terminal_output_bytes=1024)
        harness = SandboxProviderConformanceHarness(policy)
        oversized = _manifest((_artifact("artifact_1", "diff"),), output_bytes=2048)
        self.assertFalse(
            harness.evaluate_artifact_manifest(oversized, raw_terminal_output="y" * 2048)
        )


class ProviderNeutralityTests(unittest.TestCase):
    def test_no_real_provider_is_selected_or_called_by_this_boundary(self):
        self.assertIs(REAL_SANDBOX_PROVIDER_SELECTED, False)
        self.assertEqual(REAL_SANDBOX_PROVIDER_CALLS, 0)
        self.assertIs(PRODUCTION_SANDBOX_CLAIM, False)

    def test_allowlist_default_is_the_documented_export_set(self):
        self.assertEqual(SANDBOX_ALLOWED_ARTIFACT_KINDS, ("diff", "test_report", "junit_xml", "log"))


if __name__ == "__main__":
    unittest.main()
