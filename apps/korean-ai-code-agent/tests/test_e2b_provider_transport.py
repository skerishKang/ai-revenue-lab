"""#1405 phase 1 — the E2B live transport must map the documented wire and must stay silent.

Four properties are pinned here, in this order of importance:

1. The live gate is closed by repository state, not by caller arguments, and no verb performs any
   I/O while it is closed. Every scripted port in this file records zero calls on those paths.
2. The wire mapping is the documented E2B shape (``templateID``, ``allowInternetAccess``,
   ``network.denyOut``), built from the canonical launch payload, never from caller-supplied keys.
3. Termination, expiry and cancellation come from a state observation. An acknowledged kill without
   one leaves the lease active and unresolved — proved through the real transport class, not only
   through a scripted fake.
4. Credential handling is binding-name-only end to end: no value in a payload, a projection, a
   message, or an attribute of any object these tests build.

Tests that need to see the wire mapping work patch the four repository gate flags open. That patch
is evidence for the claim it makes: the gate is held by those constants and by nothing a caller can
pass, so arming is a reviewed edit to ``e2b_provider_transport.py`` plus an owner decision.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from kagent import e2b_provider_transport as transport_module
from kagent.contracts import (
    SANDBOX_LEASE_MAX_TTL_SECONDS,
    ContractError,
    ExecutionMode,
    NetworkPolicy,
    SandboxLeaseRequest,
    SandboxLeaseState,
)
from kagent.e2b_provider_transport import (
    E2B_API_HOST,
    E2B_CREDENTIAL_BINDING_NAME,
    E2B_CREDENTIAL_HEADER_NAME,
    E2B_CREATE_PATH,
    E2B_DELETE_PATH_TEMPLATE,
    E2B_DOCUMENTED_CREATE_TIMEOUT_SECONDS,
    E2B_LIST_PATH,
    E2B_LIVE_EXECUTION_READY,
    E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED,
    E2B_MAX_REQUEST_BYTES,
    E2B_MAX_RESPONSE_BYTES,
    E2B_OWNER_REQUIRED,
    E2B_PLAN_CONTINUOUS_MAX_SECONDS,
    E2B_STATUS_CREATED,
    E2B_TRANSPORT_REAL_CALLS_IN_TEST_OR_CI,
    E2B_WIRE_FIELD_MAP,
    E2B_WIRE_OMITTED_KEYS,
    E2BHttpResponse,
    E2BLiveAuthorization,
    E2BPlan,
    E2BPreLiveProbeReadinessPacket,
    E2BTargetEnvironment,
    E2BWireError,
    EnvironmentE2BCredentialPort,
    LiveE2BSandboxTransport,
    StdlibE2BHttpRequestPort,
    UnconfiguredE2BHttpRequestPort,
    build_e2b_pre_live_probe_packet,
    decode_e2b_create_response,
    decode_e2b_kill,
    decode_e2b_list,
    decode_e2b_state,
    e2b_launch_profile_for_cloud_m1,
    e2b_live_probe_plan,
    e2b_live_transport_readiness,
    encode_e2b_create_body,
)
from kagent.e2b_sandbox import (
    E2B_CONTROL_PROVENANCE,
    E2BAdapterError,
    E2BCloudM1Adapter,
    E2BControlProvenance,
    E2B_NEVER_ACCEPTED_KEYS,
    E2B_PAYLOAD_KEYS,
    E2B_REAL_PROVIDER_CALLS,
    build_e2b_launch_payload,
)
from kagent.sandbox import SandboxLeaseError, SandboxUnavailableError
from kagent.sandbox_provider_evidence import capability_control_names
from kagent.sandbox_provider_probe import SandboxProviderCandidate
from kagent.sandbox_reclamation import LeaseReclamationOutcome, reap_expired_leases
from kagent.security import contains_credential_material

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "src" / "kagent" / "e2b_provider_transport.py"

T0 = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
REVISION = "abcdef1234567890abcdef1234567890abcdef12"
#: A fixture with the shape of a key. It is not, and never was, a real credential.
CREDENTIAL = b"e2b-fixture-not-a-key-value"

GATE_FLAGS = (
    "E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED",
    "LIVE_CREDENTIAL_BOUND",
    "E2B_LIVE_EXECUTION_READY",
    "E2B_WIRE_CONTRACT_LIVE_VERIFIED",
)


def lease_request(run_id: str = "run_1", **overrides: object) -> SandboxLeaseRequest:
    fields: dict[str, object] = {
        "run_id": run_id,
        "execution_mode": ExecutionMode.CLOUD,
        "repository_ref": "skerishKang/ai-revenue-lab",
        "requested_revision": REVISION,
        "network_policy": NetworkPolicy.OFF,
    }
    fields.update(overrides)
    return SandboxLeaseRequest(**fields)  # type: ignore[arg-type]


def launch_payload(**overrides: object) -> dict:
    payload = build_e2b_launch_payload(
        lease_request(), template="claw-m1-base", content_ref="content-rev-0001", now=T0
    )
    payload.update(overrides)
    return payload


def authorization(**overrides: object) -> E2BLiveAuthorization:
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
        "written_consent_ref": "issue:1405/owner-consent-placeholder",
        "authority_ref": "authority:cloud-m1/e2b/one-shot",
        "authorized_at": T0,
        "expires_at": T0 + timedelta(hours=1),
    }
    fields.update(overrides)
    return E2BLiveAuthorization(**fields)  # type: ignore[arg-type]


def response(status: int, body: bytes = b"") -> E2BHttpResponse:
    return E2BHttpResponse(status=status, body=body)


class ScriptedRequestPort:
    """The only request port these tests use. It cannot reach a network."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._responses: dict[str, tuple[int, bytes]] = {}

    def queue(self, key: str, status: int, body: bytes = b"") -> None:
        # key is the wire identity a call is matched on, e.g. "POST /sandboxes".
        self._responses[key] = (status, body)

    def request(self, *, method: str, path: str, credential: bytes, body, timeout_seconds):
        self.calls.append({
            "method": method,
            "path": path,
            "credential": credential,
            "body": body,
            "timeout_seconds": timeout_seconds,
        })
        status, raw = self._responses.get(f"{method} {path}", (E2B_STATUS_CREATED, b"{}"))
        return response(status, raw)


class ScriptedCredentialPort:
    def __init__(self, *, value: bytes = CREDENTIAL) -> None:
        self._value = value
        self.resolutions = 0

    @property
    def binding_name(self) -> str:
        return E2B_CREDENTIAL_BINDING_NAME

    def resolve(self) -> bytes:
        self.resolutions += 1
        return self._value


class ArmingMixin(unittest.TestCase):
    """Patches the four gate flags for the duration of a test, then restores them."""

    def setUp(self) -> None:
        self._arming = mock.patch.multiple(
            transport_module, **{name: True for name in GATE_FLAGS}
        )
        self._arming.start()
        self.addCleanup(self._arming.stop)

    def build(self, *, port=None, credential=None, auth=None, clock=lambda: T0):
        return LiveE2BSandboxTransport(
            request_port=port if port is not None else ScriptedRequestPort(),
            credential_port=credential if credential is not None else ScriptedCredentialPort(),
            authorization=auth if auth is not None else authorization(),
            clock=clock,
        )


# ---------------------------------------------------------------------------
# 1. the gate
# ---------------------------------------------------------------------------


class GateClosedByRepositoryStateTests(unittest.TestCase):
    def test_repository_reports_the_live_gate_closed(self) -> None:
        self.assertIs(E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED, False)
        self.assertIs(E2B_LIVE_EXECUTION_READY, False)
        self.assertIs(E2B_REAL_PROVIDER_CALLS, 0)
        self.assertIs(E2B_TRANSPORT_REAL_CALLS_IN_TEST_OR_CI, 0)
        self.assertIs(transport_module.LIVE_CREDENTIAL_BOUND, False)
        self.assertIs(transport_module.E2B_WIRE_CONTRACT_LIVE_VERIFIED, False)
        self.assertIs(transport_module.E2B_OWNER_LIVE_GATE_REQUIRED, True)

        readiness = e2b_live_transport_readiness()
        for key in ("composition_root_wired", "credential_bound", "live_execution_ready",
                    "wire_contract_live_verified"):
            with self.subTest(key=key):
                self.assertIs(readiness[key], False)
        self.assertIs(readiness["owner_live_gate_required"], True)
        self.assertEqual(readiness["real_provider_calls"], 0)
        self.assertEqual(readiness["request_port_default"], "UnconfiguredE2BHttpRequestPort")
        self.assertFalse(readiness["production_claim"])

    def test_no_verb_touches_a_socket_while_the_gate_is_closed(self) -> None:
        port = ScriptedRequestPort()
        credential = ScriptedCredentialPort()
        transport = LiveE2BSandboxTransport(
            request_port=port, credential_port=credential,
            authorization=authorization(), clock=lambda: T0,
        )
        for verb, args in (
            ("create", (launch_payload(),)),
            ("state", ("sbx_1",)),
            ("kill", ("sbx_1",)),
            ("list_running", ()),
        ):
            with self.subTest(verb=verb):
                with self.assertRaises(SandboxUnavailableError) as caught:
                    getattr(transport, verb)(*args)
                self.assertIn("live gate is closed", str(caught.exception))
        with self.assertRaises(SandboxUnavailableError):
            transport.extend_lifetime("sbx_1", ttl_seconds=900)
        self.assertEqual(port.calls, [])
        # The credential is never even resolved while the gate stands.
        self.assertEqual(credential.resolutions, 0)

    def test_authorization_cannot_be_argued_with(self) -> None:
        """Under real flags no field combination on the authorization can arm anything."""
        for owner in (True, False):
            for selected in (True, False):
                for environment in E2BTargetEnvironment:
                    for plan in E2BPlan:
                        for network_off in (True, False):
                            record = authorization(
                                owner_authorized=owner, provider_formally_selected=selected,
                                target_environment=environment, plan=plan,
                                network_policy_off=network_off,
                            )
                            with self.subTest(owner=owner, selected=selected,
                                              environment=environment.value, plan=plan.value,
                                              network_off=network_off):
                                self.assertIs(record.armed, False)
                                self.assertTrue(record.blocked_reasons)
                                with self.assertRaises(SandboxUnavailableError):
                                    record.require_armed(T0)

    def test_no_authorization_refuses_before_the_gate_is_consulted(self) -> None:
        port = ScriptedRequestPort()
        credential = ScriptedCredentialPort()
        transport = LiveE2BSandboxTransport(request_port=port, credential_port=credential,
                                           clock=lambda: T0)
        with self.assertRaises(SandboxUnavailableError) as caught:
            transport.list_running()
        self.assertIn("no owner authorization was supplied", str(caught.exception))
        self.assertEqual(port.calls, [])
        self.assertEqual(credential.resolutions, 0)

    def test_gate_flags_are_written_only_at_their_declaration(self) -> None:
        offenders: list[str] = []
        for path in sorted((ROOT / "src" / "kagent").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # A module-level assignment in the file that declares it is a declaration; the same
            # name written anywhere else, or anywhere below module level, is a reassignment.
            declared = {
                target.id
                for node in tree.body
                if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Name) and target.id in GATE_FLAGS
            }
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if (isinstance(target, ast.Name) and target.id in GATE_FLAGS
                                and target.id not in declared):
                            offenders.append(f"{path.name}:{node.lineno}:{target.id}")
                elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                    target = getattr(node, "target", None)
                    if isinstance(target, ast.Name) and target.id in GATE_FLAGS:
                        offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [], "gate flags must be constants nobody reassigns")
        # And the readiness flag has exactly one declaring module: the prototype.
        declarations = [
            path.name
            for path in sorted((ROOT / "src" / "kagent").glob("*.py"))
            if any(
                isinstance(target, ast.Name) and target.id == "E2B_LIVE_EXECUTION_READY"
                for node in ast.parse(path.read_text(encoding="utf-8")).body
                if isinstance(node, ast.Assign)
                for target in node.targets
            )
        ]
        self.assertEqual(declarations, ["e2b_sandbox.py"])

    def test_closed_gate_stops_the_adapter_before_any_call(self) -> None:
        # The adapter's allocate path is the first thing a real launch would touch; with the gate
        # closed it must fail before the transport records a single request.
        port = ScriptedRequestPort()
        transport = LiveE2BSandboxTransport(
            request_port=port, credential_port=ScriptedCredentialPort(),
            authorization=authorization(), clock=lambda: T0,
        )
        adapter = E2BCloudM1Adapter(transport, template="claw-m1-base", clock=lambda: T0)
        with self.assertRaises(SandboxUnavailableError):
            adapter.allocate(lease_request(), content_ref="content-rev-0001")
        self.assertEqual(port.calls, [])
        self.assertEqual(adapter.active_leases(), ())

    def test_no_product_module_constructs_the_live_transport(self) -> None:
        offenders = [
            path.name
            for path in sorted((ROOT / "src" / "kagent").glob("*.py"))
            if path.name != "e2b_provider_transport.py"
            and ("LiveE2BSandboxTransport" in path.read_text(encoding="utf-8")
                 or "StdlibE2BHttpRequestPort" in path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])


class ArmingTests(ArmingMixin):
    def test_patching_only_the_flags_arms_the_transport(self) -> None:
        record = authorization()
        self.assertTrue(record.armed)
        self.assertEqual(record.blocked_reasons, ())
        record.require_armed(T0)
        transport = self.build()
        self.assertTrue(transport.safe_dict()["gate_armed"])

    def test_window_is_still_enforced_once_flags_are_open(self) -> None:
        port = ScriptedRequestPort()
        transport = self.build(
            port=port,
            auth=authorization(authorized_at=T0 - timedelta(minutes=5),
                               expires_at=T0 - timedelta(minutes=1)),
        )
        with self.assertRaises(SandboxUnavailableError) as caught:
            transport.list_running()
        self.assertIn("window is not open", str(caught.exception))
        self.assertEqual(port.calls, [])

    def test_window_end_is_exclusive(self) -> None:
        port = ScriptedRequestPort()
        transport = self.build(port=port, clock=lambda: authorization().expires_at)
        with self.assertRaises(SandboxUnavailableError):
            transport.list_running()
        self.assertEqual(port.calls, [])

    def test_credential_is_still_required_once_flags_are_open(self) -> None:
        port = ScriptedRequestPort()
        transport = LiveE2BSandboxTransport(
            request_port=port, authorization=authorization(), clock=lambda: T0
        )
        with self.assertRaises(SandboxUnavailableError) as caught:
            transport.list_running()
        self.assertIn("no credential port was wired", str(caught.exception))
        self.assertEqual(port.calls, [])


# ---------------------------------------------------------------------------
# 2. wire mapping
# ---------------------------------------------------------------------------


class WireEncodingTests(unittest.TestCase):
    def test_documented_field_names_and_values(self) -> None:
        body = encode_e2b_create_body(launch_payload())
        self.assertEqual(set(body),
                         {"templateID", "timeout", "allowInternetAccess", "network", "metadata"})
        self.assertEqual(body["templateID"], "claw-m1-base")
        self.assertIs(body["allowInternetAccess"], False)
        self.assertEqual(body["network"], {"denyOut": ["0.0.0.0/0"]})
        self.assertEqual(body["timeout"], 900)
        self.assertEqual(set(body["metadata"]),
                         {"run_id", "repository_ref", "requested_revision"})

    def test_timeout_is_always_written_never_inherited(self) -> None:
        self.assertEqual(E2B_DOCUMENTED_CREATE_TIMEOUT_SECONDS, 15)
        for ttl in (60, 900, SANDBOX_LEASE_MAX_TTL_SECONDS):
            with self.subTest(ttl=ttl):
                self.assertEqual(encode_e2b_create_body(launch_payload(timeout=ttl))["timeout"], ttl)

    def test_credential_bearing_fields_never_cross_the_boundary(self) -> None:
        body = encode_e2b_create_body(launch_payload())
        self.assertNotIn("envVars", body)
        self.assertNotIn("secrets", body)
        for key in E2B_WIRE_OMITTED_KEYS:
            self.assertNotIn(key, body)
        self.assertEqual(
            set(E2B_PAYLOAD_KEYS) - set(E2B_WIRE_FIELD_MAP) - set(E2B_WIRE_OMITTED_KEYS), set()
        )

    def test_deny_rule_is_stated_even_though_egress_is_already_denied(self) -> None:
        body = encode_e2b_create_body(launch_payload())
        self.assertIs(body["allowInternetAccess"], False)
        self.assertEqual(body["network"]["denyOut"], ["0.0.0.0/0"])

    def test_closed_payload_shape_refuses_drift(self) -> None:
        cases = (
            ({"extra_key": 1}, "shape is closed"),
            ({"timeout": "900"}, "must be an integer"),
            ({"timeout": 0}, "must be between"),
            ({"timeout": SANDBOX_LEASE_MAX_TTL_SECONDS + 1}, "must be between"),
            ({"timeout": True}, "must be an integer"),
            ({"allow_internet_access": True}, "deny outbound"),
            ({"network": {}}, "all-traffic deny rule"),
            ({"network": {"deny_out": ["10.0.0.0/8"]}}, "all-traffic deny rule"),
            ({"network": "off"}, "all-traffic deny rule"),
            ({"envs": {"TOKEN": "x"}}, "readable by sandbox code"),
            ({"secrets": ("vault:one",)}, "readable by sandbox code"),
            ({"timeout_action": "keep_alive"}, "wired to kill"),
            ({"metadata": "run_1"}, "must be a mapping"),
        )
        for mutation, needle in cases:
            with self.subTest(mutation=list(mutation)):
                payload = launch_payload()
                payload.update(mutation)
                if "extra_key" in mutation:
                    payload.pop("template")  # keep the drift to one key so the shape check fires
                with self.assertRaises((E2BWireError, ContractError)) as caught:
                    encode_e2b_create_body(payload)
                self.assertIn(needle, str(caught.exception))

    def test_never_accepted_keys_are_disjoint_from_the_canonical_shape(self) -> None:
        # A never-accepted key can only arrive by changing the closed shape, so the shape check is
        # what fires; the intersection guard under it is defence in depth, not a second path.
        self.assertEqual(set(E2B_NEVER_ACCEPTED_KEYS) & set(E2B_PAYLOAD_KEYS), set())
        payload = launch_payload()
        payload["api_key"] = "value"
        with self.assertRaises(E2BWireError) as caught:
            encode_e2b_create_body(payload)
        self.assertIn("shape is closed", str(caught.exception))

    def test_non_mapping_input_refused(self) -> None:
        for bad in (None, [], "payload", 7):
            with self.subTest(bad=bad):
                with self.assertRaises(E2BWireError):
                    encode_e2b_create_body(bad)  # type: ignore[arg-type]

    def test_wire_map_is_the_only_provider_naming_authority(self) -> None:
        self.assertEqual(transport_module.E2B_WIRE_FIELD_MAP["template"], "templateID")
        self.assertEqual(transport_module.E2B_WIRE_FIELD_MAP["allow_internet_access"],
                         "allowInternetAccess")
        self.assertNotIn("deny_out", encode_e2b_create_body(launch_payload())["network"])
        self.assertNotIn("allow_internet_access", encode_e2b_create_body(launch_payload()))


class ResponseDecodeTests(unittest.TestCase):
    def test_create_accepts_only_201_with_a_usable_id(self) -> None:
        good = decode_e2b_create_response(
            response(E2B_STATUS_CREATED,
                     b'{"sandboxID":"sbx_ABC-123","clientID":"c","envdVersion":"2"}')
        )
        self.assertEqual(good, {"sandbox_id": "sbx_ABC-123", "state": "running"})
        # A usable body on every row, so a pass can only come from the status rule and not from an
        # absent sandbox id.
        usable = json.dumps({"sandboxID": "sbx_1"}).encode()
        for status in (200, 204, 400, 401, 404, 500, 503, 504):
            with self.subTest(status=status):
                with self.assertRaises(SandboxUnavailableError) as caught:
                    decode_e2b_create_response(response(status, usable))
                if status == 401:
                    # The auth branch is the one that carries no provider status text at all.
                    self.assertIn("credential binding was rejected", str(caught.exception))
                else:
                    self.assertIn(f"status {status}", str(caught.exception))

    def test_create_without_a_usable_id_refuses(self) -> None:
        for body in (b"{}", b'{"sandboxID":""}', b'{"sandboxID":null}', b"[]", b"not json",
                     b'{"sandboxID":"sbx/one"}', b'{"sandboxID":"has space"}',
                     b'{"sandboxID":"' + b"x" * 200 + b'"}'):
            with self.subTest(body=body[:40]):
                with self.assertRaises((SandboxUnavailableError, E2BWireError)):
                    decode_e2b_create_response(response(E2B_STATUS_CREATED, body))

    def test_unauthorized_never_echoes_the_provider_body(self) -> None:
        leak = b'{"message":"bad X-API-Key: not-a-real-anything"}'
        with self.assertRaises(SandboxUnavailableError) as caught:
            decode_e2b_create_response(response(401, leak))
        self.assertNotIn("not-a-real-anything", str(caught.exception))
        self.assertIn("credential binding was rejected", str(caught.exception))

    def test_other_refusals_carry_a_bounded_redacted_reason(self) -> None:
        with self.assertRaises(SandboxUnavailableError) as caught:
            decode_e2b_create_response(
                response(500, b"api_key=not-a-real-anything")
            )
        message = str(caught.exception)
        self.assertIn("status 500", message)
        # The fixture is a sentinel the repository's own detector treats as credential material; it
        # matches no provider's key format, so surviving redaction here would be a gate defect.
        self.assertNotIn("not-a-real-anything", message)
        self.assertIn("[REDACTED]", message)
        self.assertLess(len(message), 700)

    def test_state_is_read_from_the_inventory_not_from_a_return_value(self) -> None:
        inventory = json.dumps([{
            "sandboxID": "sbx_1", "state": "running",
            "startedAt": "2026-09-20T10:00:00Z", "endAt": "2026-09-20T10:15:00Z",
        }]).encode()
        # A scheduled endAt is a lifetime signal, never an observation that the workload stopped.
        self.assertEqual(decode_e2b_state(response(200, inventory), "sbx_1"),
                         {"state": "running", "running": True})
        for state in ("killed", "finished", "terminated"):
            with self.subTest(state=state):
                row = json.dumps([{"sandboxID": "sbx_1", "state": state}]).encode()
                self.assertEqual(decode_e2b_state(response(200, row), "sbx_1"),
                                 {"state": state, "running": False})

    def test_pause_is_reported_as_what_it_is(self) -> None:
        paused = json.dumps([{"sandboxID": "sbx_1", "state": "paused"}]).encode()
        self.assertEqual(decode_e2b_state(response(200, paused), "sbx_1"),
                         {"state": "paused", "running": False})

    def test_absence_and_404_are_the_documented_terminal_observation(self) -> None:
        self.assertEqual(decode_e2b_state(response(404, b"{}"), "sbx_1"),
                         {"state": "not_found", "running": False})
        other = json.dumps([{"sandboxID": "sbx_other", "state": "running"}]).encode()
        self.assertEqual(decode_e2b_state(response(200, other), "sbx_1"),
                         {"state": "not_found", "running": False})

    def test_state_refuses_to_guess(self) -> None:
        cases = (
            (response(503, b"{}"), "status 503"),
            (response(200, b"not json"), "readable JSON"),
            (response(200, b'{"sandboxID":"sbx_1"}'), "unexpected shape"),
            (response(200, b'[{"sandboxID":"sbx_1"}]'), "state is unobservable"),
            (response(200, b'[{"sandboxID":"sbx_1","state":"  "}]'), "state is unobservable"),
            (response(200, b'["sbx_1"]'), "malformed"),
        )
        for answered, needle in cases:
            with self.subTest(needle=needle):
                with self.assertRaises(SandboxUnavailableError) as caught:
                    decode_e2b_state(answered, "sbx_1")
                self.assertIn(needle, str(caught.exception))

    def test_kill_is_an_acknowledgement_not_an_outcome(self) -> None:
        for answered in (response(204), response(200), response(404, b"{}")):
            with self.subTest(status=answered.status):
                self.assertIs(decode_e2b_kill(answered), True)
        for status in (401, 500, 503, 504):
            with self.subTest(status=status):
                with self.assertRaises(SandboxUnavailableError):
                    decode_e2b_kill(response(status, b"{}"))

    def test_list_projects_correlation_fields_only(self) -> None:
        body = json.dumps([{
            "sandboxID": "sbx_1", "state": "RUNNING", "startedAt": "s", "endAt": None,
            "envVars": {"SECRET": "leak-value"}, "cpuCount": 2,
        }]).encode()
        rows = decode_e2b_list(response(200, body))
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"sandbox_id", "state", "started_at", "end_at"})
        self.assertEqual(rows[0]["state"], "running")
        self.assertNotIn("leak-value", json.dumps([dict(row) for row in rows]))

    def test_list_refuses_malformed_or_unauthorized(self) -> None:
        for answered in (response(401, b"{}"), response(200, b"{}"), response(200, b"[1]"),
                         response(200, b'[{"sandboxID":"sbx_1"}]')):
            with self.subTest(status=answered.status):
                with self.assertRaises(SandboxUnavailableError):
                    decode_e2b_list(answered)

    def test_http_response_is_bounded(self) -> None:
        with self.assertRaises(E2BWireError):
            response(200, b"x" * (E2B_MAX_RESPONSE_BYTES + 1))
        for status in (0, 99, 600, True, "200"):
            with self.subTest(status=status):
                with self.assertRaises((E2BWireError, ContractError)):
                    response(status, b"")  # type: ignore[arg-type]
        with self.assertRaises(E2BWireError):
            response(200, "text body")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. credential boundary
# ---------------------------------------------------------------------------


class CredentialBoundaryTests(unittest.TestCase):
    def test_binding_names_are_names_not_values(self) -> None:
        self.assertEqual(EnvironmentE2BCredentialPort().binding_name, E2B_CREDENTIAL_BINDING_NAME)
        # Every row is a name-shaped string that fails the binding grammar for a different
        # reason: lowercase, dashes, a wrong provider, empty, a suffix, or not a string at all.
        for bad in ("padiem_e2b_api_key", "PADIEM-E2B-API", "OTHER_PROVIDER", "",
                    E2B_CREDENTIAL_BINDING_NAME + "-suffix", 12):
            with self.subTest(bad=bad):
                with self.assertRaises(E2BWireError):
                    EnvironmentE2BCredentialPort(binding=bad)  # type: ignore[arg-type]

    def test_binding_grammar_refuses_before_the_credential_screen(self) -> None:
        # An assignment-shaped value can never satisfy the uppercase binding grammar, so the
        # credential screen under it is defence in depth rather than a second reachable path.
        # Recorded as a test so nobody later reads the ordering as an unverified claim.
        value = "api_key=not-a-real-anything"
        self.assertIs(contains_credential_material(value), True)
        with self.assertRaises(E2BWireError) as caught:
            transport_module._binding_name(value, "credential_binding_name")
        self.assertIn("binding name", str(caught.exception))

    def test_only_the_allowlisted_binding_is_readable(self) -> None:
        self.assertEqual(transport_module.E2B_CREDENTIAL_ENV_NAMES, (E2B_CREDENTIAL_BINDING_NAME,))
        reads = [
            node for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8")))
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
            and node.attr == "environ"
        ]
        self.assertEqual(len(reads), 1, "exactly one environment read is allowed")
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("environ.items", source)
        self.assertNotIn("environ.keys", source)
        self.assertNotIn("environ[", source)

    def test_unset_binding_refuses_by_name_and_never_by_value(self) -> None:
        port = EnvironmentE2BCredentialPort(environ={})
        with self.assertRaises(SandboxUnavailableError) as caught:
            port.resolve()
        self.assertIn(E2B_CREDENTIAL_BINDING_NAME, str(caught.exception))
        self.assertIn("not configured", str(caught.exception))

    def test_usable_value_shape_is_checked_without_retaining_it(self) -> None:
        short = EnvironmentE2BCredentialPort(environ={E2B_CREDENTIAL_BINDING_NAME: "short"})
        with self.assertRaises(SandboxUnavailableError) as caught:
            short.resolve()
        self.assertIn("unusable value", str(caught.exception))
        self.assertNotIn("short", str(caught.exception))

        good_environ = {E2B_CREDENTIAL_BINDING_NAME: CREDENTIAL.decode()}
        good = EnvironmentE2BCredentialPort(environ=good_environ)
        self.assertEqual(good.resolve(), CREDENTIAL)
        # The port keeps a reference to the mapping it was handed and no credential of its own.
        self.assertNotIn(CREDENTIAL, list(vars(good).values()))
        self.assertIs(vars(good)["_environ"], good_environ)
        self.assertNotIn("_value", vars(good))

        non_ascii = EnvironmentE2BCredentialPort(
            environ={E2B_CREDENTIAL_BINDING_NAME: "키" * 20}
        )
        with self.assertRaises(SandboxUnavailableError):
            non_ascii.resolve()

    def test_request_port_validates_credential_shape_before_connecting(self) -> None:
        factory = mock.MagicMock(name="HTTPSConnection")
        with mock.patch.object(transport_module.http.client, "HTTPSConnection", factory):
            for bad in ("string-not-bytes", b"short", b"x" * 600, None):
                with self.subTest(bad=type(bad).__name__):
                    with self.assertRaises((SandboxUnavailableError, E2BWireError)):
                        StdlibE2BHttpRequestPort().request(
                            method="GET", path=E2B_LIST_PATH, credential=bad, body=None,
                            timeout_seconds=30,
                        )
        factory.assert_not_called()


# ---------------------------------------------------------------------------
# 4. the stdlib request port, with no socket
# ---------------------------------------------------------------------------


class StdlibRequestPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = mock.MagicMock(name="HTTPSConnection")
        patcher = mock.patch.object(transport_module.http.client, "HTTPSConnection", self.factory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _call(self, **overrides: object):
        kwargs: dict[str, object] = {
            "method": "GET", "path": E2B_LIST_PATH, "credential": CREDENTIAL,
            "body": None, "timeout_seconds": 30,
        }
        kwargs.update(overrides)
        return StdlibE2BHttpRequestPort().request(**kwargs)  # type: ignore[arg-type]

    def test_every_shape_guard_refuses_before_connecting(self) -> None:
        cases = (
            {"method": "PUT"}, {"method": "PATCH"}, {"method": "post"},
            {"path": "sandboxes"}, {"path": "//evil.example/x"},
            {"path": "https://evil.example/sandboxes"}, {"path": 12}, {"path": ""},
            {"body": b"x" * (E2B_MAX_REQUEST_BYTES + 1)},
            {"timeout_seconds": 0}, {"timeout_seconds": 121}, {"timeout_seconds": True},
        )
        for kwargs in cases:
            with self.subTest(**{k: str(v)[:24] for k, v in kwargs.items()}):
                with self.assertRaises((E2BWireError, SandboxUnavailableError)):
                    self._call(**kwargs)
                self.factory.assert_not_called()

    def test_connection_is_pinned_to_the_documented_origin(self) -> None:
        connection = self.factory.return_value
        connection.getresponse.return_value = mock.Mock(status=204, read=mock.Mock(return_value=b""))
        answered = self._call(method="DELETE",
                              path=E2B_DELETE_PATH_TEMPLATE.format(sandbox_id="sbx_1"))
        self.assertEqual(self.factory.call_args.args, (E2B_API_HOST,))
        self.assertEqual(self.factory.call_args.kwargs["port"], 443)
        self.assertEqual(answered.status, 204)
        sent = connection.request.call_args
        self.assertEqual(sent.args[:2], ("DELETE", "/sandboxes/sbx_1"))
        self.assertEqual(sent.kwargs["headers"][E2B_CREDENTIAL_HEADER_NAME], CREDENTIAL.decode())
        self.assertNotIn("Host", sent.kwargs["headers"])
        self.assertEqual(sent.kwargs["body"], None)
        connection.close.assert_called_once()

    def test_tls_context_must_be_a_tls_context(self) -> None:
        with self.assertRaises(E2BWireError):
            StdlibE2BHttpRequestPort(tls_context=object())

    def test_oversized_provider_answer_is_dropped_and_closed(self) -> None:
        connection = self.factory.return_value
        connection.getresponse.return_value = mock.Mock(
            status=200, read=mock.Mock(return_value=b"x" * (E2B_MAX_RESPONSE_BYTES + 1))
        )
        with self.assertRaises(SandboxUnavailableError) as caught:
            self._call()
        self.assertIn("bounded read", str(caught.exception))
        connection.close.assert_called_once()

    def test_transport_failure_normalizes_without_provider_text(self) -> None:
        connection = self.factory.return_value
        connection.request.side_effect = OSError(
            "reset by peer api_key=not-a-real-anything"
        )
        with self.assertRaises(SandboxUnavailableError) as caught:
            self._call()
        self.assertEqual(str(caught.exception), "E2B provider is unavailable")
        connection.close.assert_called_once()

    def test_redirect_is_reported_not_followed(self) -> None:
        connection = self.factory.return_value
        connection.getresponse.return_value = mock.Mock(status=301, read=mock.Mock(return_value=b""))
        self.assertEqual(self._call().status, 301)
        self.assertEqual(connection.request.call_count, 1)

    def test_default_port_refuses_without_answering(self) -> None:
        with self.assertRaises(SandboxUnavailableError) as caught:
            UnconfiguredE2BHttpRequestPort().request(
                method="GET", path=E2B_LIST_PATH, credential=CREDENTIAL, body=None,
                timeout_seconds=30,
            )
        self.assertIn("no provider request was made", str(caught.exception))
        segment = MODULE.read_text(encoding="utf-8").split(
            "class UnconfiguredE2BHttpRequestPort"
        )[1].split("class StdlibE2BHttpRequestPort")[0]
        # An empty inventory would be a claim about the provider, not a refusal to answer.
        self.assertNotIn("return ()", segment)


# ---------------------------------------------------------------------------
# 5. the armed transport, end to end with the adapter
# ---------------------------------------------------------------------------


class ArmedWireMappingTests(ArmingMixin):
    def test_verbs_issue_exactly_the_documented_calls(self) -> None:
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes", 201, json.dumps({"sandboxID": "sbx_9"}).encode())
        port.queue("GET /v2/sandboxes", 200,
                   json.dumps([{"sandboxID": "sbx_9", "state": "running"}]).encode())
        port.queue("DELETE /sandboxes/sbx_9", 204, b"")
        transport = self.build(port=port)

        self.assertEqual(transport.create(launch_payload())["sandbox_id"], "sbx_9")
        self.assertEqual(transport.state("sbx_9")["state"], "running")
        self.assertIs(transport.kill("sbx_9"), True)
        self.assertEqual([row["sandbox_id"] for row in transport.list_running()], ["sbx_9"])

        self.assertEqual([call["method"] for call in port.calls], ["POST", "GET", "DELETE", "GET"])
        self.assertEqual([call["path"] for call in port.calls], [
            E2B_CREATE_PATH, E2B_LIST_PATH,
            E2B_DELETE_PATH_TEMPLATE.format(sandbox_id="sbx_9"), E2B_LIST_PATH,
        ])
        self.assertEqual(port.calls[0]["credential"], CREDENTIAL)
        self.assertEqual(json.loads(port.calls[0]["body"]), encode_e2b_create_body(launch_payload()))
        self.assertIs(json.loads(port.calls[0]["body"])["allowInternetAccess"], False)

    def test_lifetime_extension_uses_the_documented_timeout_endpoint(self) -> None:
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes/sbx_1/timeout", 204, b"")
        transport = self.build(port=port)
        self.assertIs(transport.extend_lifetime("sbx_1", ttl_seconds=600), True)
        self.assertEqual(port.calls[0]["path"], "/sandboxes/sbx_1/timeout")
        self.assertEqual(json.loads(port.calls[0]["body"]), {"timeout": 600})
        with self.assertRaises((E2BWireError, ContractError)):
            transport.extend_lifetime("sbx_1", ttl_seconds=59)
        self.assertEqual(len(port.calls), 1)

    def test_provider_failure_propagates_after_one_call(self) -> None:
        port = ScriptedRequestPort()
        port.queue("GET /v2/sandboxes", 503,
                   b'{"message":"overloaded api_key=not-a-real-anything"}')
        transport = self.build(port=port)
        with self.assertRaises(SandboxUnavailableError) as caught:
            transport.list_running()
        message = str(caught.exception)
        # A 5xx reason is kept for diagnostics, but only after redaction: the credential-shaped
        # part of the same body must not survive it. A 401 keeps no body text at all.
        self.assertIn("status 503", message)
        self.assertIn("overloaded", message)
        self.assertNotIn("not-a-real-anything", message)
        self.assertIn("[REDACTED]", message)
        self.assertEqual(len(port.calls), 1)

    def test_construction_performs_no_call(self) -> None:
        port = ScriptedRequestPort()
        transport = self.build(port=port)
        self.assertEqual(port.calls, [])
        self.assertNotIn(CREDENTIAL.decode(), json.dumps(transport.safe_dict()))
        self.assertIsNone(transport.safe_dict()["credential_value"])

    def test_missing_clock_refuses_instead_of_reading_a_wall_clock(self) -> None:
        transport = self.build(clock=None)
        with self.assertRaises(SandboxUnavailableError) as caught:
            transport.list_running()
        self.assertIn("injected clock", str(caught.exception))

    def test_unusable_injected_parts_are_refused_at_construction(self) -> None:
        with self.assertRaises(E2BWireError):
            LiveE2BSandboxTransport(clock="not callable")
        with self.assertRaises(E2BWireError):
            LiveE2BSandboxTransport(authorization={"owner_authorized": True})
        with self.assertRaises(E2BWireError):
            LiveE2BSandboxTransport(request_port=object())


class AdapterThroughRealTransportTests(ArmingMixin):
    def _release_flow(self, *, state_after_kill: tuple[int, bytes]):
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes", 201, json.dumps({"sandboxID": "sbx_1"}).encode())
        port.queue("DELETE /sandboxes/sbx_1", 204, b"")
        port.queue("GET /v2/sandboxes", *state_after_kill)
        adapter = E2BCloudM1Adapter(self.build(port=port), template="claw-m1-base",
                                   clock=lambda: T0)
        lease = adapter.allocate(lease_request(), content_ref="content-rev-0001")
        self.assertEqual((lease.lease_id, lease.state), ("sbx_1", SandboxLeaseState.RESERVED))
        self.assertEqual(lease.expires_at - lease.created_at, timedelta(seconds=900))
        outcome: object
        try:
            outcome = adapter.release(lease.lease_id, run_id="run_1").state
        except SandboxLeaseError as exc:
            outcome = ("refused", str(exc))
        return outcome, adapter.active_leases(), adapter.termination_evidence(lease.lease_id)

    def test_observed_terminal_state_ends_the_lease(self) -> None:
        outcome, active, evidence = self._release_flow(
            state_after_kill=(200, json.dumps([{"sandboxID": "sbx_1", "state": "killed"}]).encode())
        )
        self.assertEqual(outcome, SandboxLeaseState.RELEASED)
        self.assertEqual(tuple(active), ())
        self.assertTrue(evidence.terminal_state_observed)
        self.assertFalse(evidence.physical_process_tree_kill_attested)

    def test_kill_acknowledgement_alone_leaves_the_lease_active(self) -> None:
        outcome, active, evidence = self._release_flow(
            state_after_kill=(200, json.dumps([{"sandboxID": "sbx_1", "state": "running"}]).encode())
        )
        self.assertEqual(outcome[0], "refused")
        self.assertIn("unresolved", outcome[1])
        self.assertEqual([lease.state for lease in active], [SandboxLeaseState.RESERVED])
        self.assertTrue(evidence.unresolved)
        self.assertFalse(evidence.reservation_terminated)

    def test_gone_sandbox_is_an_observation_not_a_guess(self) -> None:
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes", 201, json.dumps({"sandboxID": "sbx_1"}).encode())
        port.queue("DELETE /sandboxes/sbx_1", 404, b"{}")
        port.queue("GET /v2/sandboxes", 404, b"{}")
        adapter = E2BCloudM1Adapter(self.build(port=port), template="claw-m1-base",
                                   clock=lambda: T0)
        adapter.allocate(lease_request(), content_ref="content-rev-0001")
        self.assertEqual(adapter.release("sbx_1", run_id="run_1").state,
                         SandboxLeaseState.RELEASED)
        evidence = adapter.termination_evidence("sbx_1")
        self.assertEqual(evidence.provider_terminal_state, "not_found")
        self.assertTrue(evidence.terminal_state_observed)
        self.assertEqual(evidence.safe_dict()["real_provider_calls"], 0)

    def test_unreachable_provider_leaves_the_lease_for_reconciliation(self) -> None:
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes", 201, json.dumps({"sandboxID": "sbx_1"}).encode())
        port.queue("DELETE /sandboxes/sbx_1", 500, b"{}")
        adapter = E2BCloudM1Adapter(self.build(port=port), template="claw-m1-base",
                                   clock=lambda: T0)
        adapter.allocate(lease_request(), content_ref="content-rev-0001")
        report = reap_expired_leases(adapter, now=T0 + timedelta(seconds=901), limit=50)
        self.assertEqual(report.reclaimed_count, 0)
        self.assertEqual(report.unresolved_count, 1)
        self.assertFalse(report.fully_reclaimed)
        self.assertEqual(report.records[0].outcome, LeaseReclamationOutcome.RECONCILIATION_REQUIRED)
        self.assertTrue(report.records[0].reason)
        self.assertEqual([lease.state for lease in adapter.active_leases()],
                         [SandboxLeaseState.RESERVED])

    def test_one_active_lease_per_run_survives_a_retry(self) -> None:
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes", 201, json.dumps({"sandboxID": "sbx_1"}).encode())
        adapter = E2BCloudM1Adapter(self.build(port=port), template="claw-m1-base",
                                   clock=lambda: T0)
        adapter.allocate(lease_request("run_1"), content_ref="content-rev-0001")
        with self.assertRaises(SandboxLeaseError):
            adapter.allocate(lease_request("run_1"), content_ref="content-rev-0001")
        self.assertEqual(sum(1 for call in port.calls if call["method"] == "POST"), 1)
        self.assertEqual(len(adapter.active_leases()), 1)

    def test_pause_is_refused_through_the_real_transport(self) -> None:
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes", 201, json.dumps({"sandboxID": "sbx_1"}).encode())
        port.queue("DELETE /sandboxes/sbx_1", 204, b"")
        port.queue("GET /v2/sandboxes", 200,
                   json.dumps([{"sandboxID": "sbx_1", "state": "paused"}]).encode())
        adapter = E2BCloudM1Adapter(self.build(port=port), template="claw-m1-base",
                                   clock=lambda: T0)
        adapter.allocate(lease_request(), content_ref="content-rev-0001")
        with self.assertRaises(SandboxLeaseError) as caught:
            adapter.release("sbx_1", run_id="run_1")
        self.assertIn("forbids pause/resume", str(caught.exception))

    def test_launch_shape_still_comes_from_the_canonical_builder(self) -> None:
        port = ScriptedRequestPort()
        port.queue("POST /sandboxes", 201, json.dumps({"sandboxID": "sbx_1"}).encode())
        adapter = E2BCloudM1Adapter(self.build(port=port), template="claw-m1-base",
                                   clock=lambda: T0)
        adapter.allocate(lease_request(ttl_seconds=SANDBOX_LEASE_MAX_TTL_SECONDS),
                         content_ref="content-rev-0001")
        body = json.loads(port.calls[0]["body"])
        self.assertEqual(body["timeout"], SANDBOX_LEASE_MAX_TTL_SECONDS)
        # A second run asking for egress is refused by the canonical gate before the transport is
        # reached: use a fresh run so the refusal is demonstrably about the network policy and not
        # about lease bookkeeping. The gate speaks ContractError; the adapter speaks its own type.
        with self.assertRaises((E2BAdapterError, ContractError)):
            adapter.allocate(lease_request("run_2", network_policy=NetworkPolicy.RESTRICTED),
                             content_ref="content-rev-0001")
        self.assertEqual(sum(1 for call in port.calls if call["method"] == "POST"), 1)
        self.assertEqual([lease.run_id for lease in adapter.active_leases()], ["run_1"])


# ---------------------------------------------------------------------------
# 6. probe packet + acceptance matrix
# ---------------------------------------------------------------------------


class ProbePacketTests(unittest.TestCase):
    NAMED_LIVE_CONTROLS = (
        "checkout_hooks_disabled",
        "provider_metadata_blocked",
        "cancellation_kills_workload",
        "teardown_guaranteed",
        "artifact_allowlist_enforced",
        "terminal_output_bounded",
    )

    def setUp(self) -> None:
        self.packet = build_e2b_pre_live_probe_packet()
        self.matrix = {row["control"]: row for row in self.packet.acceptance_matrix()}

    def test_packet_carries_every_owner_gate_field(self) -> None:
        payload = self.packet.safe_dict()
        for field in ("target_environment", "plan", "credential_binding_name", "spend_cap",
                      "ttl_seconds", "max_sandbox_allocations", "max_provider_execution_paths",
                      "network_policy", "repository_ref", "exact_revision", "task",
                      "verification_command", "expected_changed_files",
                      "expected_diff_evidence", "teardown_check", "abort_conditions"):
            self.assertIn(field, payload)
        self.assertEqual(payload["max_sandbox_allocations"], 1)
        self.assertEqual(payload["max_provider_execution_paths"], 1)
        self.assertEqual(payload["network_policy"], "OFF")
        self.assertEqual(payload["credential_binding_name"], E2B_CREDENTIAL_BINDING_NAME)
        self.assertIsNone(payload["credential_value"])
        self.assertEqual(payload["real_provider_calls"], 0)
        self.assertEqual(payload["real_sandbox_allocations"], 0)
        self.assertFalse(payload["live_execution_ready"])
        self.assertFalse(payload["provider_formally_selected"])
        self.assertFalse(payload["production_claim"])

    def test_owner_decisions_are_placeholders_not_guesses(self) -> None:
        self.assertEqual(self.packet.target_environment, E2B_OWNER_REQUIRED)
        self.assertEqual(self.packet.plan, E2B_OWNER_REQUIRED)
        self.assertEqual(self.packet.spend_cap, E2B_OWNER_REQUIRED)
        self.assertEqual(self.packet.abort_conditions[:2],
                         ("abort:provider-allocates-more-than-one-sandbox",
                          "abort:provider-reports-egress-allowed"))
        self.assertTrue(self.packet.unresolved_owner_fields)
        self.assertFalse(self.packet.ready_for_owner_approval)

    def test_packet_refuses_a_wider_launch(self) -> None:
        for field, value, needle in (
            ("network_policy", "RESTRICTED", "network-off"),
            ("max_sandbox_allocations", 2, "must be between"),
            ("max_provider_execution_paths", 2, "must be between"),
            ("ttl_seconds", 59, "must be between"),
            ("ttl_seconds", SANDBOX_LEASE_MAX_TTL_SECONDS + 1, "must be between"),
            ("credential_binding_name", "padiem_e2b_api_key", "binding name"),
            ("abort_conditions", (), "abort conditions"),
            ("abort_conditions", ("",), "must be a bounded safe reference"),
            ("repository_ref", "https://evil.example/x", "not an endpoint"),
            ("candidate", "modal", "E2B-specific"),
        ):
            with self.subTest(field=field):
                overrides = {field: SandboxProviderCandidate.MODAL if field == "candidate" else value}
                with self.assertRaises((E2BWireError, ContractError)) as caught:
                    dataclasses.replace(self.packet, **overrides)
                self.assertIn(needle, str(caught.exception))

    def test_matrix_covers_every_required_control(self) -> None:
        required = tuple(capability_control_names())
        self.assertEqual(set(self.matrix), set(required))
        self.assertGreaterEqual(len(required), 26)

    def test_named_controls_are_unverified_with_a_probe_method(self) -> None:
        for control in self.NAMED_LIVE_CONTROLS:
            with self.subTest(control=control):
                row = self.matrix[control]
                self.assertEqual(row["live_status"], "UNVERIFIED_LIVE")
                self.assertEqual(row["provenance"], E2BControlProvenance.UNVERIFIED_LIVE.value)
                self.assertEqual(row["acceptance_basis_required"],
                                 "live_provider_probe_or_trusted_attestation")
                self.assertNotEqual(row["probe_method"], "adapter_assertion")

    def test_documented_and_measured_never_blend(self) -> None:
        for control, row in self.matrix.items():
            with self.subTest(control=control):
                self.assertNotIn(row["live_status"],
                                 {"VERIFIED", "LIVE_OBSERVED", "MEASURED", "CONFORMANCE_PASS"})
                self.assertNotEqual(row["provenance"], "verified")
                if row["provenance"] == E2BControlProvenance.PROVIDER_DOCUMENTED.value:
                    self.assertEqual(row["live_status"], "PROVIDER_DOCUMENTED_NOT_MEASURED")
                elif row["provenance"] == E2BControlProvenance.ADAPTER_BORNE.value:
                    self.assertEqual(row["live_status"], "ADAPTER_BORNE_NOT_LIVE_VERIFIED")

    def test_provenance_gap_is_reported_not_hidden(self) -> None:
        unlabelled = {control for control, row in self.matrix.items()
                      if row["live_status"] == "UNLABELLED_BY_ADAPTER"}
        self.assertEqual(unlabelled, set(capability_control_names()) - set(E2B_CONTROL_PROVENANCE))
        self.assertTrue(unlabelled)

    def test_canonical_profile_and_plan_are_reused(self) -> None:
        profile = e2b_launch_profile_for_cloud_m1()
        self.assertIs(profile.candidate, SandboxProviderCandidate.E2B)
        self.assertIs(profile.live_execution_ready, False)
        self.assertTrue(profile.request_shape_ready)
        plan = e2b_live_probe_plan(profile)
        self.assertIs(plan.candidate, SandboxProviderCandidate.E2B)
        self.assertEqual({probe.control for probe in plan.probes}, set(capability_control_names()))
        self.assertFalse(plan.safe_dict()["real_provider_call_executed"])
        profile.validate_lease_request(lease_request())
        with self.assertRaises(ContractError):
            profile.validate_lease_request(lease_request(network_policy=NetworkPolicy.RESTRICTED))

    def test_authorized_packet_shape_is_still_not_live_ready(self) -> None:
        filled = dataclasses.replace(
            self.packet,
            target_environment="non_production",
            plan="hobby",
            spend_cap="500-usd-milli",
            exact_revision=REVISION,
            task="print canonical marker",
            verification_command="python -m kagent.cli verify-sandbox-diff",
            expected_changed_files="README.md",
            expected_diff_evidence="sha256:diff",
            teardown_check="provider reports not_found",
        )
        self.assertTrue(filled.ready_for_owner_approval)
        payload = filled.safe_dict()
        self.assertFalse(payload["live_execution_ready"])
        self.assertFalse(payload["provider_formally_selected"])
        self.assertEqual(payload["real_provider_calls"], 0)


class AuthorizationShapeTests(unittest.TestCase):
    def test_malformed_authorizations_fail_at_construction(self) -> None:
        cases = (
            {"owner_authorized": "yes"}, {"provider_formally_selected": 1},
            {"network_policy_off": None}, {"target_environment": "non_production"},
            {"plan": "hobby"}, {"credential_binding_name": "padiem_e2b_api_key"},
            {"credential_binding_name": "PADIEM-OTHER"}, {"spend_cap_usd_milli": 0},
            {"spend_cap_usd_milli": -1}, {"max_sandbox_allocations": 2},
            {"max_provider_execution_paths": 3}, {"ttl_seconds": 59},
            {"ttl_seconds": SANDBOX_LEASE_MAX_TTL_SECONDS + 1}, {"ttl_seconds": True},
            {"exact_revision": "main"}, {"authority_ref": "https://evil.example/x"},
            {"written_consent_ref": ""}, {"authorized_at": T0.replace(tzinfo=None)},
            {"expires_at": T0}, {"expires_at": T0 + timedelta(days=30)},
            {"repository_ref": 12},
        )
        for overrides in cases:
            with self.subTest(fields=list(overrides)):
                with self.assertRaises((E2BWireError, ContractError)):
                    authorization(**overrides)

    def test_production_target_is_valid_data_but_never_armed(self) -> None:
        record = authorization(target_environment=E2BTargetEnvironment.PRODUCTION)
        self.assertIn("a first probe may not target production", record.blocked_reasons)
        with mock.patch.multiple(transport_module,
                                 **{name: True for name in GATE_FLAGS}):
            self.assertIs(record.armed, False)
            with self.assertRaises(SandboxUnavailableError):
                record.require_armed(T0)

    def test_egress_on_authorization_never_arms(self) -> None:
        record = authorization(network_policy_off=False)
        with mock.patch.multiple(transport_module, **{name: True for name in GATE_FLAGS}):
            self.assertIs(record.armed, False)
            self.assertIn("a first probe may not enable network egress", record.blocked_reasons)

    def test_projection_is_name_only(self) -> None:
        payload = authorization().safe_dict()
        self.assertIsNone(payload["credential_value"])
        self.assertEqual(payload["provider_endpoint"], E2B_API_HOST)
        self.assertEqual(payload["credential_binding_name"], E2B_CREDENTIAL_BINDING_NAME)
        self.assertFalse(payload["process_tree_kill_attested"])
        self.assertTrue(payload["physical_kill_claim_prohibited"])
        self.assertFalse(payload["production_claim"])
        self.assertNotIn("owner_authorized", payload["blocked_reasons"])

    def test_plan_bounds_are_documented_facts(self) -> None:
        self.assertEqual(E2B_PLAN_CONTINUOUS_MAX_SECONDS, {"hobby": 3_600, "pro": 86_400})
        self.assertEqual(SANDBOX_LEASE_MAX_TTL_SECONDS, E2B_PLAN_CONTINUOUS_MAX_SECONDS["hobby"])


class NoSecondAuthorityTests(unittest.TestCase):
    SOURCE = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.SOURCE = MODULE.read_text(encoding="utf-8")

    def test_canonical_authorities_are_imported_not_recopied(self) -> None:
        for needle in ("_safe_id", "SANDBOX_LEASE_MIN_TTL_SECONDS",
                       "SANDBOX_LEASE_MAX_TTL_SECONDS", "E2B_TERMINAL_PROVIDER_STATES",
                       "E2B_PAYLOAD_KEYS", "E2B_NEVER_ACCEPTED_KEYS",
                       "capability_control_names", "build_live_probe_plan",
                       "build_candidate_launch_profile", "contains_credential_material",
                       "redact_secrets", "_aware_utc"):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.SOURCE)

    def test_no_duplicate_contracts(self) -> None:
        for forbidden in (
            "class SandboxLease", "class SandboxLeaseState", "class NetworkPolicy",
            "_SAFE_ID_RE = ", "EXACT_COMMIT_REVISION_RE", "^[0-9a-f]{40}",
            "SANDBOX_LEASE_MAX_TTL_SECONDS = ", "SANDBOX_LEASE_MIN_TTL_SECONDS = ",
            "E2B_TERMINAL_PROVIDER_STATES = ", "class IsolationPrimitive",
        ):
            with self.subTest(fragment=forbidden):
                self.assertNotIn(forbidden, self.SOURCE)

    def test_pinned_endpoint_is_not_an_argument(self) -> None:
        for forbidden in ("base_url", "api_url", "endpoint: str", "host: str =", "host: str",
                          "sandbox_domain", "self._host"):
            with self.subTest(fragment=forbidden):
                self.assertNotIn(forbidden, self.SOURCE)
        self.assertIn('E2B_API_HOST = "api.e2b.app"', self.SOURCE)


class FixtureHygieneTests(unittest.TestCase):
    """Synthetic fixtures must not imitate real credentials.

    GitGuardian gates merge on exactly this. Two rules are cheap enough to enforce in-repo: no
    literal may carry a provider's key format, and no literal may look like an opaque token by
    ending in a long digit run -- which is what the earlier `...-000000` / `...-0123456789ab`
    fixtures did, and what the sentinel spellings below avoid.
    """

    PROVIDER_KEY_SHAPES = (
        r"(?:sk|ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{10,}",
        r"\bsk-[A-Za-z0-9]{12,}",
        r"glpat-[A-Za-z0-9_-]{10,}",
        r"xox[baprs]-[A-Za-z0-9-]{10,}",
        r"(?:AKIA|ASIA)[0-9A-Z]{12,}",
        r"ya29\.[A-Za-z0-9_-]{10,}",
        r"SG\.[A-Za-z0-9_-]{10,}",
        r"eyJ[A-Za-z0-9_-]{10,}",
        r"(?i)bearer\s+[A-Za-z0-9_.+-]{16,}",
    )
    TOKEN_LIKE_DIGIT_RUN = re.compile(r"[0-9]{6,}")
    # The canonical exact-commit fixture is 40 hex characters by contract; it is a revision, not a
    # credential, and is the only digit-heavy literal these rules allow.
    DECLARED_EXCEPTIONS = frozenset({REVISION})

    def _literals(self) -> set[str]:
        found: set[str] = set()
        for path in (MODULE, Path(__file__)):
            for node in ast.walk(ast.parse(Path(path).read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
                    value = node.value
                    found.add(value.decode("utf-8", errors="replace")
                              if isinstance(value, bytes) else value)
        return found

    def test_no_fixture_imitates_a_provider_key_format(self) -> None:
        for literal in self._literals():
            for shape in self.PROVIDER_KEY_SHAPES:
                with self.subTest(shape=shape[:24], literal=literal[:40]):
                    self.assertIsNone(re.search(shape, literal))

    def test_token_like_literals_are_declared(self) -> None:
        offenders = sorted(
            literal
            for literal in self._literals()
            if len(literal) >= 16
            and self.TOKEN_LIKE_DIGIT_RUN.search(literal)
            and " " not in literal
            and literal not in self.DECLARED_EXCEPTIONS
        )
        self.assertEqual(
            offenders, [],
            "credential-shaped fixtures must not imitate real keys; use a word sentinel",
        )


class ModulePurityTests(unittest.TestCase):
    THIRD_PARTY_FORBIDDEN = {"e2b", "requests", "httpx", "aiohttp", "urllib3", "socket",
                             "subprocess", "threading", "time"}

    def _tree(self) -> ast.Module:
        return ast.parse(MODULE.read_text(encoding="utf-8"))

    def _absolute_imports(self) -> set[str]:
        found: set[str] = set()
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Import):
                found |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
        return found

    STDLIB_ALLOWED = {"__future__", "http", "json", "os", "re", "ssl", "dataclasses",
                      "datetime", "enum", "typing", "collections"}

    def test_no_provider_sdk_and_no_third_party_dependency(self) -> None:
        imported = self._absolute_imports()
        self.assertEqual(imported & self.THIRD_PARTY_FORBIDDEN, set())
        tops = {name.split(".")[0] for name in imported}
        allowed = self.STDLIB_ALLOWED | {"kagent"}
        self.assertTrue(tops <= allowed, f"unexpected top-level imports: {sorted(tops - allowed)}")

    def test_socket_capable_code_is_confined_to_the_request_port(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        start = source.index("class StdlibE2BHttpRequestPort")
        end = source.index("class EnvironmentE2BCredentialPort")
        self.assertEqual(source.count("HTTPSConnection("), 1)
        self.assertTrue(start < source.index("HTTPSConnection(") < end)
        for fragment in ("import socket", "create_connection", "urlopen", "subprocess",
                         "getenv", "environ[", "environ.items", "print(", "logging"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)

    def test_no_wall_clock_reads(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotIn("datetime.now", source)
        self.assertNotIn("time.time", source)
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"sleep", "time", "print", "open"})

    def test_credential_value_is_never_formatted_or_returned_beyond_one_header(self) -> None:
        source = MODULE.read_text(encoding="utf-8")
        for fragment in ('f"{credential}"', "str(credential)", "repr(credential)",
                         "credential +", "+ credential", "credential}", "{credential",
                         "self._value = value"):
            with self.subTest(fragment=fragment):
                self.assertNotIn(fragment, source)
        self.assertEqual(source.count('credential.decode("ascii")'), 1)


if __name__ == "__main__":
    unittest.main()
