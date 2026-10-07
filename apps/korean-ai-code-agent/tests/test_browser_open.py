"""#3611 — `browser.open` open-only boundary tests.

These tests are contract-level and hermetic: no browser, no network, no real
profile, no model call. The URL policy vectors are shared with the Desktop host
mirror so the two implementations cannot drift silently.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from padiem_ai_core.agent_approval import (
    ApprovalOutcome,
    ApprovalPause,
    ApprovalRequirement,
    VerifiedApprovalDecision,
)
from padiem_ai_core.web_runtime import normalize_public_url

from kagent.browser_open import (
    BROWSER_CONTROL_IMPLEMENTED,
    BROWSER_OPEN_HOST_REF,
    BROWSER_OPEN_IMPLEMENTED,
    BROWSER_OPEN_PAGE_DERIVED_BYTES,
    BROWSER_OPEN_RECEIPT_FIELDS,
    BROWSER_OPEN_TOOL_ID,
    BROWSER_OPEN_USES_EXISTING_P01,
    COOKIE_IMPORT_SUPPORTED,
    CREDENTIAL_IMPORT_SUPPORTED,
    MAX_BROWSER_OPEN_REDIRECTS,
    PERSISTENT_BROWSER_PROFILE_SUPPORTED,
    SECOND_APPROVAL_AUTHORITY,
    USER_BROWSER_PROFILE_REUSE_SUPPORTED,
    BrowserOpenGrantConsumer,
    BrowserOpenOutcome,
    BrowserOpenReceipt,
    BrowserOpenRefusal,
    BrowserOpenRequest,
    TrustedBrowserOpenGrant,
    UnconfiguredBrowserOpenHostPort,
    authorize_browser_open,
    browser_open_fingerprint,
    run_browser_open,
)
from kagent.contracts import ContractError
from kagent.local_agent import LocalAgentDeviceProfile, LocalAgentPlatform, LocalRoot
from kagent.local_agent_permissions import (
    CapabilityRule,
    DevicePermissionProfile,
    LocalCapability,
    LocalPolicyMode,
    RootPermissionPolicy,
    default_device_permission_profile,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
SAFE_URL = "https://example.com/report?id=7#section"


def _root() -> LocalRoot:
    return LocalRoot(root_ref="root_work", windows_path="E:\\work")


def _device() -> LocalAgentDeviceProfile:
    return LocalAgentDeviceProfile(
        device_id="device_3611",
        workspace_ref="workspace_3611",
        platform=LocalAgentPlatform.WINDOWS,
        roots=(_root(),),
    )


def _profile(browser_mode: LocalPolicyMode = LocalPolicyMode.ASK) -> DevicePermissionProfile:
    base = default_device_permission_profile(device=_device())
    global_rules = tuple(
        CapabilityRule(LocalCapability.BROWSER_OPEN, browser_mode)
        if rule.capability is LocalCapability.BROWSER_OPEN
        else rule
        for rule in base.global_rules
    )
    return DevicePermissionProfile(
        device_id=base.device_id,
        workspace_ref=base.workspace_ref,
        roots=tuple(
            RootPermissionPolicy(root.root_ref, root.rules) for root in base.roots
        ),
        global_rules=global_rules,
    )


def _request(**overrides: object) -> BrowserOpenRequest:
    values: dict[str, object] = {
        "open_id": "open_1",
        "run_id": "run_3611",
        "device_id": "device_3611",
        "ticket_ref": "ticket_3611",
        "target_url": SAFE_URL,
        "requested_at": NOW,
        "ttl_seconds": 300,
    }
    values.update(overrides)
    return BrowserOpenRequest(**values)  # type: ignore[arg-type]


def _pause(request: BrowserOpenRequest, *, expires_in: int = 600) -> ApprovalPause:
    return ApprovalPause(
        pause_id="pause_3611",
        run_id=request.run_id,
        agent_runtime_id="runtime_3611",
        tool_id=BROWSER_OPEN_TOOL_ID,
        invocation_sha256=browser_open_fingerprint(request),
        requirement=ApprovalRequirement.USER_CONFIRMATION,
        step_index=1,
        created_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=expires_in),
    )


def _decision(
    pause: ApprovalPause, *, outcome: ApprovalOutcome = ApprovalOutcome.APPROVED
) -> VerifiedApprovalDecision:
    return VerifiedApprovalDecision(
        decision_id="decision_3611",
        pause_id=pause.pause_id,
        outcome=outcome,
        authority_ref="p01.engine.service.binding",
        evidence_ref="evidence_3611",
        decided_at=NOW - timedelta(seconds=1),
    )


def _grant(
    request: BrowserOpenRequest | None = None,
    *,
    browser_mode: LocalPolicyMode = LocalPolicyMode.ASK,
    outcome: ApprovalOutcome = ApprovalOutcome.APPROVED,
    pause_expires_in: int = 600,
) -> tuple[BrowserOpenRequest, TrustedBrowserOpenGrant]:
    request = request or _request()
    pause = _pause(request, expires_in=pause_expires_in)
    grant = authorize_browser_open(
        request=request,
        profile=_profile(browser_mode),
        device=_device(),
        pause=pause,
        decision=_decision(pause, outcome=outcome),
        now=NOW,
        host_lease_ref="host_lease_1",
    )
    return request, grant


def _receipt(request: BrowserOpenRequest, grant: TrustedBrowserOpenGrant, **overrides: object) -> BrowserOpenReceipt:
    values: dict[str, object] = {
        "open_id": request.open_id,
        "run_id": request.run_id,
        "device_id": request.device_id,
        "host_lease_ref": grant.host_lease_ref,
        "requested_url_normalized": request.normalized_url,
        "final_url_normalized": request.normalized_url,
        "load_outcome": BrowserOpenOutcome.LOADED,
        "redirect_count": 1,
        "dialogs_suppressed": 0,
        "opened_at": NOW,
        "closed_at": NOW + timedelta(seconds=2),
        "elapsed_ms": 2000,
        "host_ref": BROWSER_OPEN_HOST_REF,
        "request_fingerprint": grant.request_fingerprint,
        "p01_approval_ref": grant.p01_approval_ref,
        "admission_ref": "admission_1",
        "revision_ref": "revision_1",
    }
    values.update(overrides)
    return BrowserOpenReceipt(**values)  # type: ignore[arg-type]


class _RecordingHost:
    def __init__(self, receipt_factory=None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._receipt_factory = receipt_factory

    def open(self, *, request, grant, now):
        self.calls.append((request.open_id, grant.grant_id))
        if self._receipt_factory is not None:
            return self._receipt_factory(request, grant)
        return _receipt(request, grant)


class BrowserOpenPolicyTests(unittest.TestCase):
    def test_public_url_is_normalized_by_the_canonical_policy(self) -> None:
        request = _request()
        self.assertEqual(request.normalized_url, normalize_public_url(SAFE_URL))
        self.assertEqual(request.normalized_url, "https://example.com/report?id=7")

    def test_non_public_targets_fail_closed_before_any_host_or_network(self) -> None:
        for target, why in (
            ("http://localhost:3000/dashboard", "loopback literal"),
            ("https://127.0.0.1/", "loopback address"),
            ("https://10.0.0.5/", "private address"),
            ("https://169.254.169.254/latest/meta-data", "link-local metadata"),
            ("https://metadata.google.internal/", "metadata host"),
            ("https://service.internal/", "internal suffix"),
            ("file:///C:/Users/limone/secrets.txt", "file scheme"),
            ("padiem://pair?code=secret", "padiem scheme has no authority here"),
            ("javascript:alert(1)", "script scheme"),
            ("data:text/html,<h1>x</h1>", "data scheme"),
            ("https://user:pass@example.com/", "userinfo"),
            ("not-a-url", "missing scheme"),
            ("https://example.com:99999/", "invalid port"),
            ("https://" + "a" * 2100 + "/", "over length"),
        ):
            with self.subTest(target=target, why=why):
                with self.assertRaises(BrowserOpenRefusal) as ctx:
                    _request(target_url=target)
                self.assertEqual(ctx.exception.code, "policy_denied")

    def test_ttl_is_bounded(self) -> None:
        with self.assertRaises(ContractError):
            _request(ttl_seconds=30)
        with self.assertRaises(ContractError):
            _request(ttl_seconds=901)

    def test_capability_is_fixed_and_not_a_parameter(self) -> None:
        request = _request()
        self.assertIs(request.capability, LocalCapability.BROWSER_OPEN)
        self.assertEqual(request.capability.value, "browser.open")
        self.assertFalse(hasattr(request, "capability_override"))
        self.assertNotIn("selector", request.safe_dict())
        self.assertNotIn("script", request.safe_dict())

    def test_safe_dict_carries_no_page_derived_material(self) -> None:
        payload = _request().safe_dict()
        for forbidden in ("title", "html", "dom", "screenshot", "cookies", "form_values"):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(payload["page_derived_bytes"], 0)
        self.assertFalse(payload["cookie_material"])
        self.assertFalse(payload["credential_material"])


class BrowserOpenAuthorizationTests(unittest.TestCase):
    def test_grant_requires_the_canonical_p01_approval(self) -> None:
        request = _request()
        pause = _pause(request)
        with self.assertRaises(BrowserOpenRefusal) as ctx:
            authorize_browser_open(
                request=request,
                profile=_profile(),
                device=_device(),
                pause=pause,
                decision=_decision(pause, outcome=ApprovalOutcome.DENIED),
                now=NOW,
                host_lease_ref="host_lease_1",
            )
        self.assertEqual(ctx.exception.code, "grant_rejected")

    def test_local_policy_deny_wins_even_with_an_approved_decision(self) -> None:
        request = _request()
        pause = _pause(request)
        with self.assertRaises(BrowserOpenRefusal) as ctx:
            authorize_browser_open(
                request=request,
                profile=_profile(LocalPolicyMode.DENY),
                device=_device(),
                pause=pause,
                decision=_decision(pause),
                now=NOW,
                host_lease_ref="host_lease_1",
            )
        self.assertEqual(ctx.exception.code, "policy_denied")

    def test_approval_must_bind_the_exact_request(self) -> None:
        request = _request()
        other = _request(target_url="https://example.org/other")
        pause = _pause(other)
        with self.assertRaises(BrowserOpenRefusal) as ctx:
            authorize_browser_open(
                request=request,
                profile=_profile(),
                device=_device(),
                pause=pause,
                decision=_decision(pause),
                now=NOW,
                host_lease_ref="host_lease_1",
            )
        self.assertEqual(ctx.exception.code, "grant_rejected")

    def test_pause_must_be_a_browser_open_pause_for_the_same_run(self) -> None:
        request = _request()
        pause = replace(_pause(request), tool_id="windows.execute")
        with self.assertRaises(ContractError):
            authorize_browser_open(
                request=request,
                profile=_profile(),
                device=_device(),
                pause=pause,
                decision=_decision(pause),
                now=NOW,
                host_lease_ref="host_lease_1",
            )

        pause = replace(_pause(request), run_id="run_other")
        with self.assertRaises(ContractError):
            authorize_browser_open(
                request=request,
                profile=_profile(),
                device=_device(),
                pause=pause,
                decision=_decision(pause),
                now=NOW,
                host_lease_ref="host_lease_1",
            )

    def test_expired_pause_is_refused(self) -> None:
        request = _request()
        pause = _pause(request, expires_in=-1)
        with self.assertRaises(BrowserOpenRefusal) as ctx:
            authorize_browser_open(
                request=request,
                profile=_profile(),
                device=_device(),
                pause=pause,
                decision=_decision(pause),
                now=NOW,
                host_lease_ref="host_lease_1",
            )
        self.assertEqual(ctx.exception.code, "grant_rejected")

    def test_grant_lifetime_is_bounded_by_the_pause_and_the_ttl(self) -> None:
        request = _request(ttl_seconds=120)
        pause = _pause(request, expires_in=900)
        grant = authorize_browser_open(
            request=request,
            profile=_profile(),
            device=_device(),
            pause=pause,
            decision=_decision(pause),
            now=NOW,
            host_lease_ref="host_lease_1",
        )
        self.assertEqual((grant.expires_at - grant.issued_at).total_seconds(), 120)
        self.assertLessEqual(grant.expires_at, pause.expires_at)

    def test_grant_rejects_a_non_canonical_url(self) -> None:
        _, grant = _grant()
        with self.assertRaises(ContractError):
            replace(grant, normalized_url="https://example.com/report?id=7#section")
        with self.assertRaises(ContractError):
            replace(grant, normalized_url="http://localhost/")
        with self.assertRaises(ContractError):
            replace(grant, normalized_url="https://user:pass@example.com/")

    def test_grant_cannot_be_repointed_at_another_url(self) -> None:
        # A grant may only carry the canonical policy value, but "canonical" is not
        # enough: repointing it at a different public URL must break the binding to
        # the approved request so it can never be spent on that open.
        request, grant = _grant()
        repointed = replace(grant, normalized_url="https://example.com/other")
        self.assertFalse(repointed.bound_request(request))
        self.assertFalse(repointed.bound_request(_request(target_url="https://example.com/other")))

    def test_grant_binds_run_workspace_and_device(self) -> None:
        request, grant = _grant()
        self.assertTrue(grant.bound_request(request))
        self.assertFalse(grant.bound_request(replace(request, run_id="run_other")))
        self.assertFalse(grant.bound_request(_request(target_url="https://example.org/x")))

    def test_grant_safe_dict_declares_no_control_or_page_material(self) -> None:
        _, grant = _grant()
        payload = grant.safe_dict()
        self.assertTrue(payload["one_shot"])
        self.assertFalse(payload["browser_control"])
        self.assertEqual(payload["page_derived_bytes"], 0)
        self.assertEqual(payload["p01_approval_ref"], "decision_3611")
        self.assertEqual(payload["evidence_ref"], "evidence_3611")


class BrowserOpenOneShotTests(unittest.TestCase):
    def test_grant_replay_is_denied(self) -> None:
        request, grant = _grant()
        consumer = BrowserOpenGrantConsumer()
        host = _RecordingHost()
        run_browser_open(request=request, grant=grant, consumer=consumer, host=host, now=NOW)
        with self.assertRaises(BrowserOpenRefusal) as ctx:
            run_browser_open(request=request, grant=grant, consumer=consumer, host=host, now=NOW)
        self.assertEqual(ctx.exception.code, "grant_rejected")
        self.assertEqual(len(host.calls), 1)
        self.assertEqual(consumer.consumed_count, 1)

    def test_expired_grant_never_reaches_the_host(self) -> None:
        request, grant = _grant()
        consumer = BrowserOpenGrantConsumer()
        host = _RecordingHost()
        with self.assertRaises(BrowserOpenRefusal) as ctx:
            run_browser_open(
                request=request,
                grant=grant,
                consumer=consumer,
                host=host,
                now=grant.expires_at + timedelta(seconds=1),
            )
        self.assertEqual(ctx.exception.code, "grant_rejected")
        self.assertEqual(host.calls, [])

    def test_grant_from_another_request_never_reaches_the_host(self) -> None:
        _, grant = _grant()
        other = _request(open_id="open_2")
        host = _RecordingHost()
        with self.assertRaises(BrowserOpenRefusal):
            run_browser_open(
                request=other,
                grant=grant,
                consumer=BrowserOpenGrantConsumer(),
                host=host,
                now=NOW,
            )
        self.assertEqual(host.calls, [])

    def test_unconfigured_host_fails_closed(self) -> None:
        request, grant = _grant()
        with self.assertRaises(BrowserOpenRefusal) as ctx:
            run_browser_open(
                request=request,
                grant=grant,
                consumer=BrowserOpenGrantConsumer(),
                host=UnconfiguredBrowserOpenHostPort(),
                now=NOW,
            )
        self.assertEqual(ctx.exception.code, "host_unavailable")

    def test_host_receipt_correlation_is_enforced(self) -> None:
        request, grant = _grant()
        bad = _RecordingHost(lambda req, gr: _receipt(req, gr, run_id="run_other"))
        with self.assertRaises(ContractError):
            run_browser_open(
                request=request,
                grant=grant,
                consumer=BrowserOpenGrantConsumer(),
                host=bad,
                now=NOW,
            )


class BrowserOpenReceiptTests(unittest.TestCase):
    def test_receipt_field_set_is_pinned_and_page_derived_free(self) -> None:
        request, grant = _grant()
        receipt = _receipt(request, grant)
        self.assertEqual(set(receipt.safe_dict()) - {"page_content_included", "cookie_included", "credential_included", "dom_api_exposed", "network_scope"}, {
            "open_id",
            "run_id",
            "device_id",
            "host_lease_ref",
            "requested_url_normalized",
            "final_url_normalized",
            "load_outcome",
            "redirect_count",
            "dialogs_suppressed",
            "opened_at",
            "closed_at",
            "elapsed_ms",
            "host_ref",
            "request_fingerprint",
            "p01_approval_ref",
            "admission_ref",
            "revision_ref",
        })
        payload = receipt.safe_dict()
        for forbidden in ("title", "text", "html", "dom", "screenshot", "pdf", "dialog_text", "form_values"):
            self.assertNotIn(forbidden, payload)
        self.assertFalse(payload["page_content_included"])
        self.assertFalse(payload["cookie_included"])
        self.assertFalse(payload["credential_included"])
        self.assertFalse(payload["dom_api_exposed"])
        self.assertEqual(payload["network_scope"], "approved_url_fetch_only")

    def test_receipt_redirect_budget_is_enforced(self) -> None:
        request, grant = _grant()
        with self.assertRaises(ContractError):
            _receipt(request, grant, redirect_count=MAX_BROWSER_OPEN_REDIRECTS + 1)

    def test_receipt_final_url_must_be_canonical_or_absent(self) -> None:
        request, grant = _grant()
        receipt = _receipt(request, grant, final_url_normalized=None)
        self.assertIsNone(receipt.final_url_normalized)
        with self.assertRaises(ContractError):
            _receipt(request, grant, final_url_normalized="https://example.com/redirected#frag")
        with self.assertRaises(ContractError):
            _receipt(request, grant, final_url_normalized="http://127.0.0.1/admin")

    def test_receipt_rejects_a_non_public_final_url(self) -> None:
        request, grant = _grant()
        with self.assertRaises(ContractError):
            _receipt(request, grant, final_url_normalized="http://169.254.169.254/")


class BrowserOpenBoundaryDeclarationTests(unittest.TestCase):
    def test_module_declares_the_open_only_boundary(self) -> None:
        self.assertTrue(BROWSER_OPEN_IMPLEMENTED)
        self.assertFalse(BROWSER_CONTROL_IMPLEMENTED)
        self.assertEqual(BROWSER_OPEN_PAGE_DERIVED_BYTES, 0)
        self.assertTrue(BROWSER_OPEN_USES_EXISTING_P01)
        self.assertFalse(SECOND_APPROVAL_AUTHORITY)
        self.assertFalse(PERSISTENT_BROWSER_PROFILE_SUPPORTED)
        self.assertFalse(USER_BROWSER_PROFILE_REUSE_SUPPORTED)
        self.assertFalse(COOKIE_IMPORT_SUPPORTED)
        self.assertFalse(CREDENTIAL_IMPORT_SUPPORTED)
        self.assertEqual(len(BROWSER_OPEN_RECEIPT_FIELDS), 22)

    def test_source_declares_no_control_or_content_extraction_primitive(self) -> None:
        source = (Path(__file__).resolve().parents[1] / "src" / "kagent" / "browser_open.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "executeJavaScript",
            "capturePage",
            "printToPDF",
            "claimTab",
            "cookieStore",
            "localStorage",
            "sessionStorage",
        ):
            self.assertNotIn(forbidden, source, f"{forbidden} must not appear in the open-only path")


class SharedUrlPolicyVectorTests(unittest.TestCase):
    """The Desktop host mirrors this policy; the shared vectors keep them aligned."""

    @staticmethod
    def _vectors() -> dict:
        root = Path(__file__).resolve().parents[3]
        path = (
            root
            / "apps"
            / "padiem-desktop-shell"
            / "tests"
            / "vectors"
            / "public-url-policy-vectors.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    def test_vectors_match_the_canonical_python_policy(self) -> None:
        payload = self._vectors()
        vectors = payload["vectors"]
        self.assertGreaterEqual(len(vectors), 20)
        for vector in vectors:
            with self.subTest(url=vector["input"]):
                try:
                    normalized = normalize_public_url(vector["input"])
                except ValueError:
                    self.assertEqual(vector["python"], "reject", f"unexpected rejection: {vector['why']}")
                    continue
                self.assertEqual(vector["python"], "allow", f"unexpected acceptance: {vector['why']}")
                self.assertEqual(normalized, vector["python_normalized"])

    def test_host_mirror_never_allows_what_the_canonical_policy_rejects(self) -> None:
        payload = self._vectors()
        for vector in payload["vectors"]:
            if vector.get("ts") == "allow":
                self.assertEqual(
                    vector["python"],
                    "allow",
                    f"host mirror is weaker than the canonical policy for {vector['input']}",
                )


if __name__ == "__main__":  # pragma: no cover - manual invocation
    unittest.main()
