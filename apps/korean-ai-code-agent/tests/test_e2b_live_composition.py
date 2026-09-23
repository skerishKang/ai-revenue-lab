"""#2923 — the E2B live transport composition root must wire the stack and change nothing else.

`e2b_provider_transport.py` already owned every live-layer authority; what it never had was the one
place that assembles them, which is why `E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED` read `False`.
`e2b_live_composition.py` adds that place. Five properties are pinned here, in this order of
importance:

1. **Construction is inert.** Building the composition performs zero provider requests, zero
   credential resolutions, zero sandbox allocations and zero clock reads, and it never reads the
   allowlisted binding name out of the environment. Every scripted port in this file records zero
   calls on those paths, and the socket layer is replaced with a spy for the duration.
2. **The gate is still shut, and shut by repository state.** A composed object refuses every verb
   before any I/O. A fully-formed owner record with `owner_authorized` and
   `provider_formally_selected` both `True` does not open it, because credential binding, live
   readiness and live wire verification are the reviewed half of the decision.
3. **The caller surface carries no endpoint and no credential.** The composition root takes an
   authorization record and a clock and nothing else; the endpoint, binding name and template are
   read from source, and the parameter list is pinned as data so a review can diff it.
4. **There is no second stack.** The composed objects are the canonical classes and
   `E2BLiveComposition` refuses to hold anything else. The new module defines no transport, no
   adapter and no port, restates no wire constant, and the composition-root flag still has exactly
   one definition site in the tree.
5. **Nothing real was called.** The real-call counters stay at zero, and no projection carries a
   credential value.

Only one reviewed flag moved, and it is the one this issue is about: the transport module's own
`test_e2b_provider_transport.py` records the composition root as wired while the other three gate
flags stay `False`. That is asserted there, not duplicated here.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from unittest import mock

from kagent import e2b_live_composition as composition_module
from kagent import e2b_provider_transport as transport_module
from kagent.contracts import (
    ExecutionMode,
    NetworkPolicy,
    SandboxLeaseRequest,
)
from kagent.e2b_live_composition import (
    E2B_CLOUD_M1_TEMPLATE,
    E2B_COMPOSITION_CONSTRUCTION_CREDENTIAL_READS,
    E2B_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS,
    E2B_COMPOSITION_CONSTRUCTION_SANDBOX_ALLOCATIONS,
    E2B_COMPOSITION_PARAMETERS,
    E2B_LIVE_COMPOSITION_CONTRACT_VERSION,
    E2BLiveComposition,
    build_e2b_live_composition,
)
from kagent.e2b_provider_transport import (
    E2B_API_HOST,
    E2B_CREDENTIAL_BINDING_NAME,
    E2B_CREDENTIAL_ENV_NAMES,
    E2B_TRANSPORT_REAL_CALLS_IN_TEST_OR_CI,
    E2BLiveAuthorization,
    E2BPlan,
    E2BTargetEnvironment,
    E2BWireError,
    EnvironmentE2BCredentialPort,
    LiveE2BSandboxTransport,
    StdlibE2BHttpRequestPort,
)
from kagent.e2b_sandbox import (
    E2B_PROVIDER_CANDIDATE,
    E2B_REAL_PROVIDER_CALLS,
    E2B_REAL_SANDBOX_ALLOCATIONS,
    E2BCloudM1Adapter,
)
from kagent.sandbox import SandboxUnavailableError
from kagent.sandbox_provider_probe import SandboxProviderCandidate
from kagent.security import contains_credential_material

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "kagent" / "e2b_live_composition.py"
SRC_DIR = ROOT / "src" / "kagent"

T0 = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
REVISION = "4d13151efb6ed6e629790fbd41cc1cc94a7561fc"
CONTENT_REF = "content-rev-0001"
#: A fixture with the shape of a key. It is not, and never was, a real credential.
FIXTURE_VALUE = "e2b-fixture-not-a-key-value-2923"
#: The three repository reasons that must survive #2923, and the one that must not.
SYSTEM_REASONS = (
    "the E2B credential binding is not configured",
    "E2B live execution is not marked ready",
    "the documented wire contract has never been observed live",
)
RETIRED_REASON = "no composition root wires an E2B live transport"


def module_source() -> str:
    return MODULE_PATH.read_text(encoding="utf-8")


def module_tree() -> ast.Module:
    return ast.parse(module_source())


def lease_request(run_id: str = "run_2923") -> SandboxLeaseRequest:
    return SandboxLeaseRequest(
        run_id=run_id,
        execution_mode=ExecutionMode.CLOUD,
        repository_ref="skerishKang/ai-revenue-lab",
        requested_revision=REVISION,
        network_policy=NetworkPolicy.OFF,
    )


def owner_record(**overrides: object) -> E2BLiveAuthorization:
    """A record in the exact shape an owner would issue — still not enough to open the gate."""
    fields: dict[str, object] = {
        "owner_authorized": True,
        "provider_formally_selected": True,
        "target_environment": E2BTargetEnvironment.NON_PRODUCTION,
        "plan": E2BPlan.HOBBY,
        "credential_binding_name": E2B_CREDENTIAL_BINDING_NAME,
        "spend_cap_usd_milli": 500,
        "max_sandbox_allocations": 1,
        "max_provider_execution_paths": 1,
        "ttl_seconds": 900,
        "network_policy_off": True,
        "repository_ref": "skerishKang/ai-revenue-lab",
        "exact_revision": REVISION,
        "written_consent_ref": "issue:2923/owner-consent-placeholder",
        "authority_ref": "authority:cloud-m1/e2b/one-shot",
        "authorized_at": T0,
        "expires_at": T0 + timedelta(hours=1),
    }
    fields.update(overrides)
    return E2BLiveAuthorization(**fields)  # type: ignore[arg-type]


class SocketSpy:
    """Stands in for ``http.client.HTTPSConnection``. It can only fail loudly."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("a socket was opened where none may be")


class ExplodingFunctionSpy:
    def __init__(self, message: str) -> None:
        self.calls = 0
        self._message = message

    def __call__(self, *args: object, **kwargs: object) -> Any:
        self.calls += 1
        raise AssertionError(self._message)


class RecordingEnviron(dict):
    """An ``os.environ`` stand-in that records every name looked up in it."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        super().__init__(initial or {})
        self.reads: list[str] = []

    def get(self, key: str, default: object = None) -> Any:
        self.reads.append(key)
        return super().get(key, default)

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        self.reads.append(str(key))
        return super().__contains__(key)


def socket_watch() -> mock._patch:
    """Replace the socket constructor everywhere the stdlib port could reach it."""
    return mock.patch("http.client.HTTPSConnection", SocketSpy)


# ---------------------------------------------------------------------------
# 1. construction is inert
# ---------------------------------------------------------------------------


class ConstructionIsInertTests(unittest.TestCase):
    def test_construction_performs_no_provider_request(self) -> None:
        request_spy = ExplodingFunctionSpy("a provider request was issued during construction")
        with mock.patch.object(StdlibE2BHttpRequestPort, "request", request_spy):
            with socket_watch():
                build_e2b_live_composition()
            self.assertEqual(request_spy.calls, 0)

    def test_construction_performs_no_credential_resolution(self) -> None:
        resolve_spy = ExplodingFunctionSpy("a credential was resolved during construction")
        with mock.patch.object(EnvironmentE2BCredentialPort, "resolve", resolve_spy):
            build_e2b_live_composition()
        self.assertEqual(resolve_spy.calls, 0)

    def test_construction_does_not_load_the_tls_trust_store(self) -> None:
        with mock.patch.object(
            transport_module.ssl, "create_default_context",
            side_effect=AssertionError("TLS trust store loaded during construction"),
        ) as create_context:
            composition = build_e2b_live_composition()
        create_context.assert_not_called()
        self.assertIs(composition.request_port._context, None)


    def test_construction_performs_no_sandbox_allocation(self) -> None:
        allocate_spy = ExplodingFunctionSpy("a sandbox was allocated during construction")
        with mock.patch.object(E2BCloudM1Adapter, "allocate", allocate_spy):
            build_e2b_live_composition()
        self.assertEqual(allocate_spy.calls, 0)

    def test_construction_does_not_call_the_clock(self) -> None:
        reads: list[int] = []

        def clock() -> datetime:
            reads.append(1)
            return T0

        build_e2b_live_composition(clock=clock)
        self.assertEqual(reads, [])

    def test_construction_never_reads_the_allowlisted_binding_name(self) -> None:
        guard = RecordingEnviron({E2B_CREDENTIAL_BINDING_NAME: FIXTURE_VALUE})
        with mock.patch.object(transport_module.os, "environ", guard):
            composition = build_e2b_live_composition()
        # The port holds the binding *name* as configured source; the value path is resolve(),
        # which construction does not take. Nothing looked the name up in the environment.
        self.assertEqual(composition.credential_port.binding_name, E2B_CREDENTIAL_BINDING_NAME)
        self.assertNotIn(E2B_CREDENTIAL_BINDING_NAME, guard.reads)

    def test_the_construction_counters_stay_at_zero(self) -> None:
        self.assertEqual(E2B_COMPOSITION_CONSTRUCTION_PROVIDER_REQUESTS, 0)
        self.assertEqual(E2B_COMPOSITION_CONSTRUCTION_CREDENTIAL_READS, 0)
        self.assertEqual(E2B_COMPOSITION_CONSTRUCTION_SANDBOX_ALLOCATIONS, 0)


# ---------------------------------------------------------------------------
# 2. the gate is still shut, and shut by repository state
# ---------------------------------------------------------------------------


class GateStaysClosedTests(unittest.TestCase):
    def test_missing_authorization_fails_closed_before_request(self) -> None:
        composition = build_e2b_live_composition(clock=lambda: T0)
        request_spy = ExplodingFunctionSpy("a request was issued without an authorization")
        with mock.patch.object(StdlibE2BHttpRequestPort, "request", request_spy):
            with self.assertRaises(SandboxUnavailableError) as caught:
                composition.transport.create({"templateID": "claw-m1-base"})
            # The adapter is the product-facing path and translates a transport refusal into
            # fixed text on purpose (``_transport_call`` clears the exception chain), so the
            # reason is asserted on the transport and the refusal itself on the adapter. The
            # request spy is what proves neither path reached the provider.
            with self.assertRaises(SandboxUnavailableError) as adapter_caught:
                composition.adapter.allocate(lease_request(), content_ref=CONTENT_REF)
        self.assertEqual(request_spy.calls, 0)
        self.assertIn("live gate is closed", str(caught.exception))
        self.assertIn("no owner authorization was supplied", str(caught.exception))
        self.assertIn("provider create call did not run", str(adapter_caught.exception))
        self.assertIs(composition.gate_armed, False)

    def test_a_complete_owner_record_alone_does_not_open_the_gate(self) -> None:
        composition = build_e2b_live_composition(authorization=owner_record(), clock=lambda: T0)
        self.assertIs(composition.gate_armed, False)
        reasons = composition.blocked_reasons
        for reason in SYSTEM_REASONS:
            with self.subTest(reason=reason):
                self.assertIn(reason, reasons)
        # The reason this issue retired is gone; the moving flag was truthful and nothing else moved.
        self.assertNotIn(RETIRED_REASON, reasons)

    def test_every_transport_verb_refuses_while_the_flags_are_closed(self) -> None:
        composition = build_e2b_live_composition(authorization=owner_record(), clock=lambda: T0)
        with socket_watch():
            for verb, args in (
                ("create", ({"templateID": "t"},)),
                ("state", ("sbx_1",)),
                ("kill", ("sbx_1",)),
                ("list_running", ()),
            ):
                with self.subTest(verb=verb):
                    with self.assertRaises(SandboxUnavailableError) as caught:
                        getattr(composition.transport, verb)(*args)
                    self.assertIn("live gate is closed", str(caught.exception))
            with self.assertRaises(SandboxUnavailableError) as adapter_caught:
                composition.adapter.allocate(lease_request(), content_ref=CONTENT_REF)
            self.assertIn("provider create call did not run", str(adapter_caught.exception))

    def test_the_composed_default_clock_refuses_rather_than_inventing_time(self) -> None:
        composition = build_e2b_live_composition(authorization=owner_record())
        request_spy = ExplodingFunctionSpy("a request was issued by a transport with no clock")
        with mock.patch.object(StdlibE2BHttpRequestPort, "request", request_spy):
            with self.assertRaises(SandboxUnavailableError) as caught:
                composition.adapter.allocate(lease_request(), content_ref=CONTENT_REF)
        self.assertEqual(request_spy.calls, 0)
        self.assertIn("requires an injected clock", str(caught.exception))

    def test_repository_flags_alone_do_not_open_the_gate(self) -> None:
        """Opening the four flags still leaves the owner's decision outstanding."""
        with mock.patch.multiple(
            transport_module,
            E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED=True,
            LIVE_CREDENTIAL_BOUND=True,
            E2B_LIVE_EXECUTION_READY=True,
            E2B_WIRE_CONTRACT_LIVE_VERIFIED=True,
        ):
            composition = build_e2b_live_composition(clock=lambda: T0)
            self.assertIs(composition.safe_dict()["composition_root_wired"], True)
            self.assertIs(composition.gate_armed, False)
            with self.assertRaises(SandboxUnavailableError) as caught:
                composition.transport.create({"templateID": "claw-m1-base"})
        self.assertIn("no owner authorization was supplied", str(caught.exception))


# ---------------------------------------------------------------------------
# 3. the caller surface carries no endpoint and no credential
# ---------------------------------------------------------------------------


class CallerSurfaceIsPinnedTests(unittest.TestCase):
    FORBIDDEN_PARAMETERS = (
        "api_url",
        "base_url",
        "domain",
        "endpoint",
        "host",
        "hostname",
        "port",
        "path",
        "url",
        "binding",
        "binding_name",
        "env",
        "env_name",
        "environment",
        "token",
        "api_key",
        "secret",
        "credential",
        "credential_value",
        "value",
        "template",
        "transport",
        "request_port",
        "credential_port",
    )

    def test_the_composition_root_parameter_surface_is_pinned(self) -> None:
        import inspect

        parameters = tuple(inspect.signature(build_e2b_live_composition).parameters)
        self.assertEqual(parameters, E2B_COMPOSITION_PARAMETERS)
        self.assertEqual(set(parameters), {"authorization", "clock"})
        for name in parameters:
            with self.subTest(parameter=name):
                self.assertNotIn(name, self.FORBIDDEN_PARAMETERS)

    def test_the_module_declares_no_endpoint_constant_of_its_own(self) -> None:
        source = module_source()
        self.assertNotIn("api.e2b.app", source)
        self.assertNotIn("https://", source)
        self.assertNotIn("PADIEM_E2B_SANDBOX_TOKEN", source)
        assigned = {
            target.id
            for node in ast.walk(module_tree())
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for name in ("E2B_API_HOST", "E2B_API_PORT", "E2B_CREDENTIAL_BINDING_NAME",
                     "E2B_CREDENTIAL_HEADER_NAME", "E2B_CREDENTIAL_ENV_NAMES"):
            with self.subTest(name=name):
                self.assertNotIn(name, assigned)

    def test_the_endpoint_and_binding_come_from_the_transport_module(self) -> None:
        composition = build_e2b_live_composition()
        projection = composition.safe_dict()
        self.assertEqual(projection["provider_endpoint"], E2B_API_HOST)
        self.assertEqual(projection["provider_endpoint"], "api.e2b.app")
        self.assertEqual(projection["credential_binding_name"], E2B_CREDENTIAL_BINDING_NAME)
        self.assertEqual(E2B_CREDENTIAL_ENV_NAMES, (E2B_CREDENTIAL_BINDING_NAME,))
        self.assertEqual(composition.credential_binding_name, E2B_CREDENTIAL_BINDING_NAME)

    def test_a_caller_cannot_pass_an_authorization_shaped_lookalike(self) -> None:
        for bad in ("authorized", {"owner_authorized": True}, 1):
            with self.subTest(value=bad):
                with self.assertRaises(E2BWireError):
                    build_e2b_live_composition(authorization=bad)  # type: ignore[arg-type]

    def test_a_caller_cannot_pass_a_non_callable_clock(self) -> None:
        with self.assertRaises(E2BWireError):
            build_e2b_live_composition(clock=T0)  # type: ignore[arg-type]

    def test_no_projection_carries_a_credential_value(self) -> None:
        composition = build_e2b_live_composition(authorization=owner_record(), clock=lambda: T0)
        dumped = json.dumps(composition.safe_dict(), sort_keys=True)
        self.assertNotIn(FIXTURE_VALUE, dumped)
        # Name only: the projection may say which binding, never what is in it.
        self.assertIs(composition.safe_dict()["credential_value"], None)
        self.assertIs(contains_credential_material(dumped), False)

    def test_the_transport_projection_agrees_with_the_composition_projection(self) -> None:
        """One authority: both projections read the same flags and the same endpoint."""
        composition = build_e2b_live_composition(authorization=owner_record(), clock=lambda: T0)
        transport_projection = composition.transport.safe_dict()
        composition_projection = composition.safe_dict()
        self.assertEqual(
            transport_projection["provider_endpoint"], composition_projection["provider_endpoint"]
        )
        self.assertEqual(
            transport_projection["credential_binding_name"],
            composition_projection["credential_binding_name"],
        )
        self.assertEqual(
            transport_projection["blocked_reasons"], composition_projection["blocked_reasons"]
        )
        self.assertEqual(transport_projection["gate_armed"], composition_projection["gate_armed"])


# ---------------------------------------------------------------------------
# 4. there is no second stack
# ---------------------------------------------------------------------------


class NoSecondAuthorityTests(unittest.TestCase):
    def test_the_module_defines_no_transport_adapter_or_port(self) -> None:
        defined = {
            node.name for node in module_tree().body if isinstance(node, ast.ClassDef)
        }
        self.assertEqual(defined, {"E2BLiveComposition"})
        source = module_source()
        for forbidden in ("def request(", "def resolve(", "class Live", "class Stdlib",
                          "class Environment", "class E2BCloudM1Adapter"):
            with self.subTest(fragment=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_module_exposes_exactly_one_builder(self) -> None:
        functions = {
            node.name
            for node in module_tree().body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(functions, {"build_e2b_live_composition", "_no_wall_clock"})

    def test_there_is_exactly_one_construction_path_per_object(self) -> None:
        """A second builder would be a second stack, however it is spelled.

        Counted structurally rather than by reading the file: every construction call must live
        inside the one builder, and there must be exactly one call site per canonical object.
        """
        tree = module_tree()
        watchers = ("E2BCloudM1Adapter", "LiveE2BSandboxTransport", "StdlibE2BHttpRequestPort",
                    "EnvironmentE2BCredentialPort", "E2BLiveComposition")
        for watcher in watchers:
            with self.subTest(constructed=watcher):
                callers: list[str] = []
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    called = node.func
                    name = called.id if isinstance(called, ast.Name) else None
                    if name != watcher:
                        continue
                    owner = "<module>"
                    for candidate in ast.walk(tree):
                        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
                            child is node for child in ast.walk(candidate)
                        ):
                            owner = candidate.name
                    callers.append(owner)
                self.assertEqual(len(callers), 1, callers)
                self.assertEqual(callers, ["build_e2b_live_composition"])

    def test_the_composed_stack_holds_the_canonical_classes_only(self) -> None:
        composition = build_e2b_live_composition(authorization=owner_record(), clock=lambda: T0)
        self.assertIsInstance(composition.transport, LiveE2BSandboxTransport)
        self.assertIsInstance(composition.request_port, StdlibE2BHttpRequestPort)
        self.assertIsInstance(composition.credential_port, EnvironmentE2BCredentialPort)
        self.assertIsInstance(composition.adapter, E2BCloudM1Adapter)
        # The adapter was built on the one transport this root built; the private read is
        # deliberate, because "the adapter reuses the transport" is exactly the claim at stake.
        self.assertIs(composition.adapter._transport, composition.transport)
        self.assertIs(composition.transport._request_port, composition.request_port)
        self.assertIs(composition.transport._credential_port, composition.credential_port)

    def test_a_lookalike_object_cannot_be_smuggled_into_the_composition(self) -> None:
        composition = build_e2b_live_composition()
        for field, replacement in (
            ("transport", object()),
            ("adapter", object()),
            ("request_port", object()),
            ("credential_port", object()),
            ("authorization", "owner-said-yes"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(E2BWireError):
                    dataclasses.replace(composition, **{field: replacement})

    def test_the_composition_root_flag_has_one_definition_site_in_the_tree(self) -> None:
        sites: dict[str, list[str]] = {}
        for path in sorted(SRC_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        sites.setdefault(target.id, []).append(path.name)
        for name in ("E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED", "LIVE_CREDENTIAL_BOUND",
                     "E2B_WIRE_CONTRACT_LIVE_VERIFIED", "E2B_OWNER_LIVE_GATE_REQUIRED"):
            with self.subTest(name=name):
                self.assertEqual(len(sites.get(name, [])), 1, sites.get(name))
        self.assertEqual(sites["E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED"], ["e2b_provider_transport.py"])

    def test_the_single_composition_root_flag_is_true_and_the_rest_are_not(self) -> None:
        self.assertIs(transport_module.E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED, True)
        self.assertIs(transport_module.LIVE_CREDENTIAL_BOUND, False)
        self.assertIs(transport_module.E2B_LIVE_EXECUTION_READY, False)
        self.assertIs(transport_module.E2B_WIRE_CONTRACT_LIVE_VERIFIED, False)
        self.assertIs(transport_module.E2B_OWNER_LIVE_GATE_REQUIRED, True)

    def test_no_provider_selection_is_made_here(self) -> None:
        composition = build_e2b_live_composition()
        self.assertIs(E2B_PROVIDER_CANDIDATE, SandboxProviderCandidate.E2B)
        self.assertEqual(composition.provider_candidate, SandboxProviderCandidate.E2B)
        self.assertEqual(composition.safe_dict()["provider_candidate"], "e2b")
        self.assertIs(composition.safe_dict()["production_claim"], False)
        # A candidate name is not a selection, and the selection field only ever arrives as the
        # owner's data — which the gate tests above prove is insufficient on its own.
        self.assertEqual(E2B_CLOUD_M1_TEMPLATE, "claw-m1-base")
        self.assertEqual(E2B_LIVE_COMPOSITION_CONTRACT_VERSION, "claw-e2b-live-composition.v1")


# ---------------------------------------------------------------------------
# 5. nothing real was called
# ---------------------------------------------------------------------------


class RealCallsStayAtZeroTests(unittest.TestCase):
    def test_the_real_call_counters_are_untouched(self) -> None:
        self.assertEqual(E2B_REAL_PROVIDER_CALLS, 0)
        self.assertEqual(E2B_REAL_SANDBOX_ALLOCATIONS, 0)
        self.assertEqual(E2B_TRANSPORT_REAL_CALLS_IN_TEST_OR_CI, 0)
        build_e2b_live_composition(authorization=owner_record(), clock=lambda: T0)
        self.assertEqual(E2B_REAL_PROVIDER_CALLS, 0)
        self.assertEqual(E2B_REAL_SANDBOX_ALLOCATIONS, 0)

    def test_the_module_takes_no_credential_argument_and_binds_nothing(self) -> None:
        source = module_source()
        for forbidden in ("os.environ", "getenv", "environ[", "load_dotenv", "credentials("):
            with self.subTest(fragment=forbidden):
                self.assertNotIn(forbidden, source)

    def test_the_composition_is_reproducible_and_side_effect_free(self) -> None:
        first = build_e2b_live_composition().safe_dict()
        second = build_e2b_live_composition().safe_dict()
        self.assertEqual(first, second)
        self.assertIs(first["gate_armed"], False)


if __name__ == "__main__":
    unittest.main()
