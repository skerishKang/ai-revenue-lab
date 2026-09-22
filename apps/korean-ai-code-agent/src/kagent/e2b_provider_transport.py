"""Real E2B transport shape + pre-live acceptance gate for Cloud M1 (#1405 phase 1).

The repository already owns the launch *decision* (``e2b_sandbox.py``): it validates a canonical
``SandboxLeaseRequest``, builds an explicit-deny launch payload, and treats provider termination as
something observed rather than something returned. What it never had is the layer that would speak
to E2B. This module is that layer, written so that speaking to E2B stays impossible until an owner
decides otherwise.

```text
WHAT THIS FILE IS
  A production-shaped HTTPS transport for the E2B sandbox API: the wire-name mapping, TTL/plan
  mapping, credential-binding boundary, live-execution gate, and the pre-live probe packet.

WHAT IT IS NOT
  Not a live path. No composition root in this repository constructs LiveE2BSandboxTransport, no
  credential binding is configured, and no owner authorization record exists. Every transport in
  this tree is therefore either a scripted test fake or a fail-closed refusal.
```

Two separations are load-bearing, and both are tested rather than asserted in prose:

* **Client construction is not a provider call.** ``LiveE2BSandboxTransport.__init__`` validates the
  authorization, the binding and the request port, and opens nothing. The first byte leaves the
  process only inside ``E2BHttpRequestPort.request``, and only after the gate is checked.
* **A binding name is not a credential.** This module accepts and emits binding *names*
  (``PADIEM_E2B_SANDBOX_TOKEN``) and never a value. A value arrives at call time from an injected
  credential port as ``bytes``, goes straight to the request port, and is never stored, projected,
  formatted or logged on any path here.

Provider facts were read from ``docs.e2b.dev`` on 2026-09-20 and are recorded as documentation, not
as measurement. Two disagreements are written down instead of smoothed over: the documented create
``timeout`` default is 15 seconds where the prototype records 300, and E2B's documented field names
are camelCase (``allowInternetAccess``, ``network.denyOut``) where the canonical launch payload is
snake_case. Translating between those shapes is this module's job; until an authorized probe observes
a real answer it keeps ``E2B_WIRE_CONTRACT_LIVE_VERIFIED = False``.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import ssl
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Protocol

from .contracts import (
    SANDBOX_LEASE_MAX_TTL_SECONDS,
    SANDBOX_LEASE_MIN_TTL_SECONDS,
    ContractError,
    _aware_utc,
    _safe_id,
    exact_commit_revision,
)
from .e2b_sandbox import (
    E2BControlProvenance,
    E2B_DENY_ALL_ENCODING,
    E2B_LIVE_EXECUTION_READY,
    E2B_NEVER_ACCEPTED_KEYS,
    E2B_PAYLOAD_KEYS,
    E2B_REAL_PROVIDER_CALLS,
    E2B_REAL_SANDBOX_ALLOCATIONS,
    E2B_TERMINAL_PROVIDER_STATES,
    E2B_TIMEOUT_DEFAULT_ACTION,
)
from .sandbox import SandboxUnavailableError
from .sandbox_provider_evidence import capability_control_names
from .sandbox_provider_probe import (
    CloudM1ProviderLaunchProfile,
    ProbeMethod,
    SandboxProviderCandidate,
    SandboxProviderLiveProbePlan,
    build_candidate_launch_profile,
    build_live_probe_plan,
)
from .security import contains_credential_material, redact_secrets

# ---------------------------------------------------------------------------
# Pinned API shape. Documentation-sourced; never live-verified in this child.
# ---------------------------------------------------------------------------

E2B_API_SCHEME = "https"
E2B_API_HOST = "api.e2b.app"
E2B_API_PORT = 443
#: Header NAME. No constant, literal or field here could hold its value.
E2B_CREDENTIAL_HEADER_NAME = "X-API-Key"
#: Platform secret binding NAME only, following the repo's binding convention.
E2B_CREDENTIAL_BINDING_NAME = "PADIEM_E2B_SANDBOX_TOKEN"
#: The only environment name this module may look at. No prefix scan, no dump.
E2B_CREDENTIAL_ENV_NAMES = (E2B_CREDENTIAL_BINDING_NAME,)

E2B_CREATE_PATH = "/sandboxes"
E2B_TIMEOUT_PATH_TEMPLATE = "/sandboxes/{sandbox_id}/timeout"
E2B_DELETE_PATH_TEMPLATE = "/sandboxes/{sandbox_id}"
E2B_LIST_PATH = "/v2/sandboxes"

#: Documented status codes for the endpoints above.
E2B_STATUS_CREATED = 201
E2B_STATUS_NO_CONTENT = 204
E2B_STATUS_UNAUTHORIZED = 401
E2B_STATUS_NOT_FOUND = 404
E2B_STATUS_SERVER_ERRORS = (500, 503, 504)

E2B_MAX_REQUEST_BYTES = 16 * 1024
E2B_MAX_RESPONSE_BYTES = 256 * 1024
E2B_TRANSPORT_TIMEOUT_SECONDS = 30
E2B_MAX_PROVIDER_REASON_CHARS = 256
E2B_CREDENTIAL_MIN_BYTES = 16
E2B_CREDENTIAL_MAX_BYTES = 512

#: Documented defaults, kept as data so a provider change is visible instead of inherited.
E2B_DOCUMENTED_CREATE_TIMEOUT_SECONDS = 15
E2B_PROTOTYPE_RECORDED_TIMEOUT_DEFAULT_SECONDS = 300
E2B_DOCUMENTED_ALLOW_INTERNET_ACCESS_DEFAULT = True
E2B_DOCUMENTED_UPDATE_NETWORK_SEMANTICS = "REPLACES_NOT_MERGES"
#: E2B's docs state no position on the link-local metadata address; recorded as a question.
E2B_DOCUMENTED_METADATA_ADDRESS_STATEMENT = "NOT_DOCUMENTED"

E2B_PLAN_CONTINUOUS_MAX_SECONDS = {"hobby": 3_600, "pro": 86_400}

#: Provider states that are documented as not executing. ``paused`` is one of them and is
#: deliberately not terminal: E2B gives a paused sandbox no TTL at all, so a pause is a persistence
#: channel the adapter forbids, never an ending it may record as reclaimed.
E2B_NON_RUNNING_PROVIDER_STATES = ("paused",) + E2B_TERMINAL_PROVIDER_STATES

#: Live-gate state. These are the assertions the review gates read.
LIVE_CREDENTIAL_BOUND = False
E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED = False
# E2B_LIVE_EXECUTION_READY is imported, not restated: one flag, one authority (#2800/#2802 rule).
E2B_WIRE_CONTRACT_LIVE_VERIFIED = False
E2B_OWNER_LIVE_GATE_REQUIRED = True
E2B_PROCESS_TREE_KILL_ATTESTED = False
#: Nothing in this file has ever been pointed at a datacenter, in tests or anywhere else.
E2B_TRANSPORT_REAL_CALLS_IN_TEST_OR_CI = 0

#: The literal an owner-supplied field holds until the owner supplies it.
E2B_OWNER_REQUIRED = "OWNER_REQUIRED"

E2B_BINDING_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
E2B_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
#: A ref is a correlation label, never a destination. Rejecting a URL-shaped value keeps the
#: pinned-origin promise honest even in a field that is only ever projected.
E2B_REF_FORBIDDEN_FRAGMENTS = ("://", "localhost", "127.0.0.1", "@")
E2B_ALLOWED_METHODS = frozenset({"GET", "POST", "DELETE"})

#: One documented fact per row, with the page it came from and the date it was read.
E2B_DOCUMENTED_API_FACTS: Mapping[str, str] = {
    "base_origin": "docs.e2b.dev/api-reference retrieved 2026-09-20: https://api.e2b.app, "
                   "header X-API-Key",
    "create": "docs.e2b.dev/api-reference/sandboxes/create-sandbox retrieved 2026-09-20: "
              "POST /sandboxes; templateID required; timeout integer default 15; autoPause "
              "boolean default false; allowInternetAccess boolean; network object; metadata "
              "object; envVars object; responses 201/400/401/500/503/504; body sandboxID",
    "set_timeout": "docs.e2b.dev/api-reference/sandboxes/set-sandbox-timeout retrieved "
                   "2026-09-20: POST /sandboxes/{sandboxID}/timeout; body timeout integer; "
                   "204/401/404/500",
    "delete": "docs.e2b.dev/api-reference/sandboxes/delete-sandbox retrieved 2026-09-20: "
              "DELETE /sandboxes/{sandboxID}; no body; 204 success; 404 not found",
    "list": "docs.e2b.dev/api-reference retrieved 2026-09-20: GET /sandboxes deprecated, use "
            "GET /v2/sandboxes; fields sandboxID, state, startedAt, endAt",
    "network": "docs.e2b.dev/network/internet-access retrieved 2026-09-20: egress enabled by "
               "default via allowInternetAccess; allowOut/denyOut lists; updateNetwork replaces "
               "rules; create-only fields cannot change afterwards",
    "metadata_address": "docs.e2b.dev/network/internet-access and /faq/security-and-compliance "
                        "searched 2026-09-20: no statement about 169.254.169.254",
}

#: canonical launch payload key -> documented provider field name.
#:
#: The prototype's payload is the repository's canonical shape; these are the provider's names.
#: Encoding lives here so the launch decision and the wire encoding can each be reviewed on their
#: own, and a provider rename becomes one reviewable row instead of a silent behaviour change.
E2B_WIRE_FIELD_MAP: Mapping[str, str] = {
    "template": "templateID",
    "timeout": "timeout",
    "allow_internet_access": "allowInternetAccess",
    "network": "network",
    "metadata": "metadata",
    "envs": "envVars",
}

#: Canonical fields that exist to prove a negative, and therefore never reach the wire. Each is
#: either E2B-side-unneeded (the request already states the deny) or forbidden-by-decision.
E2B_WIRE_OMITTED_KEYS = (
    "allow_public_traffic",
    "auto_pause",
    "auto_resume",
    "control_provenance",
    "fork_source",
    "host_mounts",
    "materialization",
    "privileged",
    "public_ports",
    "requested_at",
    "runtime_socket",
    "secrets",
    "snapshot",
    "timeout_action",
    "volume_mounts",
)


class E2BWireError(ContractError):
    """A provider-facing shape was wrong; refused before any byte leaves the process."""


class E2BPlan(str, Enum):
    HOBBY = "hobby"
    PRO = "pro"


class E2BTargetEnvironment(str, Enum):
    """The only environment a first probe may touch.

    ``PRODUCTION`` is a member so a caller can be *refused* rather than coerced: an unlabelled
    string cannot smuggle a production probe past the gate.
    """

    NON_PRODUCTION = "non_production"
    PRODUCTION = "production"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ref(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or not E2B_REF_RE.match(value):
        raise E2BWireError(f"{field_name} must be a bounded safe reference")
    if any(fragment in value for fragment in E2B_REF_FORBIDDEN_FRAGMENTS):
        raise E2BWireError(f"{field_name} must be a reference, not an endpoint")
    if contains_credential_material(value):
        raise E2BWireError(f"{field_name} must be a reference, never credential material")
    return value


def _text(value: object, field_name: str, *, limit: int = 512) -> str:
    """A description, not an identifier: bounded, trimmed, and credential-free.

    ``task`` and ``verification_command`` are human-readable plan text. They may hold spaces and
    flags, which an identifier grammar would reject, so they get their own ceiling and the same
    credential-material refusal every other projected field gets.
    """
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise E2BWireError(f"{field_name} must be bounded description text")
    if contains_credential_material(value):
        raise E2BWireError(f"{field_name} must not contain credential material")
    return value


def _revision_or_placeholder(value: object, field_name: str) -> str:
    """Either the canonical immutable commit, or the literal that says the owner has not chosen.

    A mutable ref is the one value this field must never accept: Cloud M1 binds one exact revision,
    and a probe plan that named ``main`` would describe a launch the canonical contract refuses.
    """
    if value == E2B_OWNER_REQUIRED:
        return E2B_OWNER_REQUIRED
    if not isinstance(value, str):
        raise E2BWireError(f"{field_name} must be an exact commit or {E2B_OWNER_REQUIRED}")
    return exact_commit_revision(value, field_name)


def _binding_name(value: object, field_name: str) -> str:
    """A binding name is an identifier, not a secret: uppercase grammar, no credential shape.

    Refusing a value-shaped string here is what keeps ``credential_binding_name`` safe to project
    into a report, and stops a caller parking the real key in a field named as a name.
    """
    if not isinstance(value, str) or not E2B_BINDING_NAME_RE.match(value):
        raise E2BWireError(
            f"{field_name} must be a platform secret binding name, not a credential value"
        )
    if contains_credential_material(value):
        raise E2BWireError(f"{field_name} must be a binding name, never credential material")
    return value


def _sandbox_id(value: object, field_name: str = "sandbox_id") -> str:
    """Reuse the canonical lease identifier grammar rather than minting a second one.

    A provider id that cannot be expressed as a canonical lease id cannot become one, which is the
    point: the alternative would be a provider-shaped escape hatch around ``_safe_id``. No second
    pattern is layered on top of it -- a duplicate grammar adds the appearance of a check, not the
    check itself.
    """
    try:
        return _safe_id(value if isinstance(value, str) else "", field_name)
    except ContractError as exc:
        raise E2BWireError(f"{field_name} is not a usable sandbox identifier") from exc


def _aware(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise E2BWireError(f"{field_name} must be a datetime")
    return _aware_utc(value, field_name)


def _strict_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise E2BWireError(f"{field_name} must be a boolean")
    return value


def _bounded_int(value: object, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise E2BWireError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise E2BWireError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _provider_reason(body: bytes) -> str:
    """Provider error text is untrusted display data: decoded leniently, redacted, bounded."""
    text = body.decode("utf-8", errors="replace")
    return redact_secrets(text)[:E2B_MAX_PROVIDER_REASON_CHARS]


def _json_object(body: bytes) -> Mapping[str, Any]:
    parsed = _json(body)
    if not isinstance(parsed, dict):
        raise SandboxUnavailableError("E2B provider response had an unexpected shape")
    return parsed


def _json_array(body: bytes) -> tuple[Any, ...]:
    parsed = _json(body)
    if not isinstance(parsed, list):
        raise SandboxUnavailableError("E2B sandbox inventory had an unexpected shape")
    return tuple(parsed)


def _json(body: bytes) -> Any:
    try:
        return json.loads(body.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise SandboxUnavailableError("E2B provider response was not readable JSON") from exc


def _refusal(operation: str, response: E2BHttpResponse) -> SandboxUnavailableError:
    if response.status == E2B_STATUS_UNAUTHORIZED:
        # Deliberately no provider text: a 401 body is the likeliest place to echo a credential.
        return SandboxUnavailableError(
            f"E2B {operation} was refused by the provider: credential binding was rejected"
        )
    return SandboxUnavailableError(
        f"E2B {operation} failed: status {response.status}; reason {_provider_reason(response.body)!r}"
    )


def _path_for(template: str, sandbox_id: str) -> str:
    return template.format(sandbox_id=_sandbox_id(sandbox_id))


# ---------------------------------------------------------------------------
# request port: the only thing that can put bytes on a wire
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class E2BHttpResponse:
    """One provider answer, bounded before anything reads it."""

    status: int
    body: bytes = b""

    def __post_init__(self) -> None:
        object.__setattr__(self, "status",
                           _bounded_int(self.status, "status", minimum=100, maximum=599))
        if not isinstance(self.body, bytes):
            raise E2BWireError("provider body must be raw bytes")
        if len(self.body) > E2B_MAX_RESPONSE_BYTES:
            raise E2BWireError("provider response exceeds the bounded read limit")

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def not_found(self) -> bool:
        return self.status == E2B_STATUS_NOT_FOUND


class E2BHttpRequestPort(Protocol):
    """Issue one pinned-origin HTTPS request. Constructing a port is not calling one."""

    def request(
        self,
        *,
        method: str,
        path: str,
        credential: bytes,
        body: bytes | None,
        timeout_seconds: int,
    ) -> E2BHttpResponse:
        ...


class UnconfiguredE2BHttpRequestPort:
    """Production-safe default: refusing is the only behaviour available.

    An empty answer is deliberately absent. "This account has nothing running" is a claim about the
    provider, not a refusal to answer, and a fail-closed port must not be able to make it.
    """

    def request(
        self,
        *,
        method: str,
        path: str,
        credential: bytes,
        body: bytes | None,
        timeout_seconds: int,
    ) -> E2BHttpResponse:
        raise SandboxUnavailableError(
            "E2B request port is not configured; no provider request was made"
        )


class StdlibE2BHttpRequestPort:
    """Pinned-origin HTTPS/443 using the OS trust store, stdlib only.

    The host is a module constant rather than an argument: nothing can point this port at another
    endpoint, which is the same reason the launch adapter takes no base URL. Redirects cannot be
    followed (no redirect handler exists on this path), the response is read under an explicit byte
    ceiling, and every transport failure normalizes to ``SandboxUnavailableError`` so a caller's
    sweep records the lease as unsettled instead of guessing.
    """

    def __init__(self, *, tls_context: ssl.SSLContext | None = None) -> None:
        if tls_context is not None and not isinstance(tls_context, ssl.SSLContext):
            raise E2BWireError("tls_context must be an ssl.SSLContext or omitted")
        self._context = tls_context or ssl.create_default_context()

    def request(
        self,
        *,
        method: str,
        path: str,
        credential: bytes,
        body: bytes | None,
        timeout_seconds: int,
    ) -> E2BHttpResponse:
        if method not in E2B_ALLOWED_METHODS:
            raise E2BWireError("only the documented E2B methods may be issued")
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise E2BWireError("E2B request path must be a single absolute path")
        if not isinstance(credential, bytes):
            raise SandboxUnavailableError("E2B credential binding resolved to an unusable value")
        if not E2B_CREDENTIAL_MIN_BYTES <= len(credential) <= E2B_CREDENTIAL_MAX_BYTES:
            # Shape only. The value is never stored, returned, formatted or logged here.
            raise SandboxUnavailableError("E2B credential binding resolved to an unusable value")
        if body is not None and len(body) > E2B_MAX_REQUEST_BYTES:
            raise E2BWireError("E2B request body exceeds the bounded write limit")
        timeout = _bounded_int(
            timeout_seconds, "timeout_seconds", minimum=1, maximum=120
        )

        connection: http.client.HTTPSConnection | None = None
        try:
            connection = http.client.HTTPSConnection(
                E2B_API_HOST,
                port=E2B_API_PORT,
                timeout=timeout,
                context=self._context,
            )
            connection.request(
                method,
                path,
                body=body,
                headers={
                    E2B_CREDENTIAL_HEADER_NAME: credential.decode("ascii"),
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            raw = response.read(E2B_MAX_RESPONSE_BYTES + 1)
            if len(raw) > E2B_MAX_RESPONSE_BYTES:
                raise SandboxUnavailableError("E2B provider response exceeded the bounded read")
            return E2BHttpResponse(status=response.status, body=raw)
        except SandboxUnavailableError:
            raise
        except (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException) as exc:
            # The exception type is the only thing carried forward: provider text is untrusted and
            # could itself reflect a credential.
            raise SandboxUnavailableError("E2B provider is unavailable") from exc
        finally:
            if connection is not None:
                connection.close()


class EnvironmentE2BCredentialPort:
    """Resolve the one allowlisted binding name to bytes, at call time.

    Nothing else in the environment is readable through this object: there is no prefix scan, no
    dump, and no path that hands the value back to a projection. An unconfigured binding is a
    refusal, which is today's state and is what ``LIVE_CREDENTIAL_BOUND = False`` records.
    """

    def __init__(
        self,
        *,
        binding: str = E2B_CREDENTIAL_BINDING_NAME,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._binding = _binding_name(binding, "binding")
        if self._binding not in E2B_CREDENTIAL_ENV_NAMES:
            raise E2BWireError("this transport reads only its own allowlisted binding name")
        # Injectable so a test can drive the unset/short/valid branches without touching the
        # process environment. Left unset, the production path reads the one allowlisted name.
        self._environ = environ if environ is not None else os.environ

    @property
    def binding_name(self) -> str:
        return self._binding

    def resolve(self) -> bytes:
        raw = self._environ.get(self._binding)
        if not raw:
            raise SandboxUnavailableError(
                f"E2B credential binding {self._binding} is not configured; "
                "no provider request may be made"
            )
        try:
            value = raw.encode("ascii")
        except UnicodeEncodeError as exc:
            raise SandboxUnavailableError(
                f"E2B credential binding {self._binding} resolved to an unusable value"
            ) from exc
        if not E2B_CREDENTIAL_MIN_BYTES <= len(value) <= E2B_CREDENTIAL_MAX_BYTES:
            raise SandboxUnavailableError(
                f"E2B credential binding {self._binding} resolved to an unusable value"
            )
        return value


# ---------------------------------------------------------------------------
# the gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class E2BLiveAuthorization:
    """The owner decision, as data.

    Today no honest instance of this class exists: the owner has not authorized a live probe, so
    ``owner_authorized`` has no ``True`` to carry. The shape is validated regardless, because the
    useful property is that the authorization which eventually arrives cannot be sloppy — a
    production target, more than one allocation, an over-TTL lifetime, egress on, a long window or a
    value-shaped credential field each make construction itself fail.
    """

    owner_authorized: bool
    provider_formally_selected: bool
    target_environment: E2BTargetEnvironment
    plan: E2BPlan
    credential_binding_name: str
    spend_cap_usd_milli: int
    max_sandbox_allocations: int
    max_provider_execution_paths: int
    ttl_seconds: int
    network_policy_off: bool
    repository_ref: str
    exact_revision: str
    written_consent_ref: str
    authority_ref: str
    authorized_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner_authorized",
                           _strict_bool(self.owner_authorized, "owner_authorized"))
        object.__setattr__(self, "provider_formally_selected",
                           _strict_bool(self.provider_formally_selected, "provider_formally_selected"))
        if not isinstance(self.target_environment, E2BTargetEnvironment):
            raise E2BWireError("target_environment must be an E2BTargetEnvironment")
        if not isinstance(self.plan, E2BPlan):
            raise E2BWireError("plan must be an E2BPlan")
        object.__setattr__(self, "credential_binding_name",
                           _binding_name(self.credential_binding_name, "credential_binding_name"))
        object.__setattr__(self, "spend_cap_usd_milli",
                           _bounded_int(self.spend_cap_usd_milli, "spend_cap_usd_milli",
                                        minimum=1, maximum=10_000_000))
        object.__setattr__(self, "max_sandbox_allocations",
                           _bounded_int(self.max_sandbox_allocations, "max_sandbox_allocations",
                                        minimum=1, maximum=1))
        object.__setattr__(self, "max_provider_execution_paths",
                           _bounded_int(self.max_provider_execution_paths,
                                        "max_provider_execution_paths", minimum=1, maximum=1))
        object.__setattr__(self, "ttl_seconds",
                           _bounded_int(self.ttl_seconds, "ttl_seconds",
                                        minimum=SANDBOX_LEASE_MIN_TTL_SECONDS,
                                        maximum=SANDBOX_LEASE_MAX_TTL_SECONDS))
        if self.ttl_seconds > E2B_PLAN_CONTINUOUS_MAX_SECONDS[self.plan.value]:
            raise E2BWireError("ttl_seconds exceeds the documented continuous maximum for this plan")
        object.__setattr__(self, "network_policy_off",
                           _strict_bool(self.network_policy_off, "network_policy_off"))
        object.__setattr__(self, "repository_ref", _ref(self.repository_ref, "repository_ref"))
        object.__setattr__(self, "exact_revision",
                           _revision_or_placeholder(self.exact_revision, "exact_revision"))
        object.__setattr__(self, "written_consent_ref",
                           _ref(self.written_consent_ref, "written_consent_ref"))
        object.__setattr__(self, "authority_ref", _ref(self.authority_ref, "authority_ref"))
        observed = _aware(self.authorized_at, "authorized_at")
        ends = _aware(self.expires_at, "expires_at")
        object.__setattr__(self, "authorized_at", observed)
        object.__setattr__(self, "expires_at", ends)
        if ends <= observed:
            raise E2BWireError("live authorization expiry must follow its issue time")
        if ends - observed > timedelta(days=7):
            raise E2BWireError("live authorization must be short-lived; one probe needs no more")

    @property
    def blocked_reasons(self) -> tuple[str, ...]:
        """Why this authorization may not open the gate, in priority order.

        The repository flags come first on purpose: owner authorization is data a caller supplies,
        but "this code is not wired to be live" is a reviewed source decision, and while it stands
        nothing can arm a transport from a call site.
        """
        reasons: list[str] = []
        if E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED is not True:
            reasons.append("no composition root wires an E2B live transport")
        if LIVE_CREDENTIAL_BOUND is not True:
            reasons.append("the E2B credential binding is not configured")
        if E2B_LIVE_EXECUTION_READY is not True:
            reasons.append("E2B live execution is not marked ready")
        if E2B_WIRE_CONTRACT_LIVE_VERIFIED is not True:
            reasons.append("the documented wire contract has never been observed live")
        if not self.owner_authorized:
            reasons.append("the owner has not authorized a live probe")
        if not self.provider_formally_selected:
            reasons.append("E2B is not formally selected as a provider")
        if self.target_environment is not E2BTargetEnvironment.NON_PRODUCTION:
            reasons.append("a first probe may not target production")
        if not self.network_policy_off:
            reasons.append("a first probe may not enable network egress")
        return tuple(reasons)

    @property
    def armed(self) -> bool:
        return not self.blocked_reasons

    def require_armed(self, now: datetime) -> None:
        """Refuse before I/O, and re-check the window at the moment of the call.

        A window is checked rather than trusted: an authorization issued for one probe and left
        lying around must not keep working after its own expiry.
        """
        reasons = self.blocked_reasons
        if reasons:
            raise SandboxUnavailableError("E2B live gate is closed: " + "; ".join(reasons))
        observed = _aware(now, "now")
        if observed < self.authorized_at or observed >= self.expires_at:
            raise SandboxUnavailableError("E2B live authorization window is not open")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-e2b-live-authorization.v1",
            "owner_authorized": self.owner_authorized,
            "provider_formally_selected": self.provider_formally_selected,
            "target_environment": self.target_environment.value,
            "plan": self.plan.value,
            "credential_binding_name": self.credential_binding_name,
            "spend_cap_usd_milli": self.spend_cap_usd_milli,
            "max_sandbox_allocations": self.max_sandbox_allocations,
            "max_provider_execution_paths": self.max_provider_execution_paths,
            "ttl_seconds": self.ttl_seconds,
            "network_policy_off": self.network_policy_off,
            "repository_ref": self.repository_ref,
            "requested_revision": self.exact_revision,
            "written_consent_ref": self.written_consent_ref,
            "authority_ref": self.authority_ref,
            "authorized_at": self.authorized_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "armed": self.armed,
            "blocked_reasons": list(self.blocked_reasons),
            "credential_value": None,
            "provider_endpoint": E2B_API_HOST,
            "real_provider_calls": E2B_REAL_PROVIDER_CALLS,
            "real_sandbox_allocations": E2B_REAL_SANDBOX_ALLOCATIONS,
            "process_tree_kill_attested": False,
            "physical_kill_claim_prohibited": True,
            "production_claim": False,
        }


# ---------------------------------------------------------------------------
# wire encoding and decoding
# ---------------------------------------------------------------------------


def encode_e2b_create_body(launch_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the canonical deny-shaped launch payload into the documented request body.

    Explicit and closed in both directions: a payload that has drifted from ``E2B_PAYLOAD_KEYS`` is
    refused before encoding, the documented fields are written rather than defaulted, and the
    repository-only fields never cross the boundary. E2B's documented defaults for egress (enabled)
    and ``timeout`` (15 seconds) are both the opposite of what this lane needs, so both are always
    stated.
    """
    if not isinstance(launch_payload, Mapping):
        raise E2BWireError("launch payload must be a mapping")
    if set(launch_payload) != set(E2B_PAYLOAD_KEYS):
        raise E2BWireError("launch payload shape is closed; it changed without a decision")
    if set(launch_payload) & set(E2B_NEVER_ACCEPTED_KEYS):
        raise E2BWireError("launch payload carries never-accepted keys")
    if launch_payload["allow_internet_access"] is not False:
        raise E2BWireError("launch must deny outbound internet access")
    network = launch_payload["network"]
    if not isinstance(network, Mapping) or network != {"deny_out": [E2B_DENY_ALL_ENCODING]}:
        raise E2BWireError("launch must carry the explicit all-traffic deny rule")
    if launch_payload["envs"] or launch_payload["secrets"]:
        raise E2BWireError("no credential may be readable by sandbox code")
    if launch_payload["timeout_action"] != E2B_TIMEOUT_DEFAULT_ACTION:
        raise E2BWireError("launch timeout must be wired to kill")
    metadata = launch_payload["metadata"]
    if not isinstance(metadata, Mapping):
        raise E2BWireError("launch metadata must be a mapping")
    timeout = _bounded_int(
        launch_payload["timeout"], "timeout",
        minimum=SANDBOX_LEASE_MIN_TTL_SECONDS, maximum=SANDBOX_LEASE_MAX_TTL_SECONDS,
    )

    return {
        "templateID": _ref(launch_payload["template"], "template"),
        "timeout": timeout,
        "allowInternetAccess": False,
        # Documented as allowOut/denyOut. denyOut is written even though egress is already denied:
        # if a provider later reinterprets allowInternetAccess, this launch cannot widen with it.
        "network": {"denyOut": [str(item) for item in network["deny_out"]]},
        "metadata": dict(metadata),
        # envVars is omitted rather than sent empty. The canonical payload guarantees it is empty,
        # and an absent key is a smaller provider surface than a field this lane never uses.
    }


def decode_e2b_create_response(response: E2BHttpResponse) -> dict[str, Any]:
    """Accept only a 201 carrying a usable sandbox id; everything else refuses."""
    if response.status != E2B_STATUS_CREATED:
        raise _refusal("create", response)
    fields = _json_object(response.body)
    sandbox_id = fields.get("sandboxID")
    if not isinstance(sandbox_id, str) or not sandbox_id:
        raise SandboxUnavailableError("E2B create response carried no usable sandbox id")
    # "running" here is the documented create-then-run shape restated, not an observation: state()
    # is the only producer of that claim, and the adapter never reads terminality from this body.
    return {"sandbox_id": _sandbox_id(sandbox_id), "state": "running"}


def decode_e2b_state(response: E2BHttpResponse, sandbox_id: str) -> dict[str, Any]:
    """Observe one sandbox from the account inventory. Never inferred from a call's return.

    E2B documents no per-sandbox state endpoint, so the inventory is the observation channel. 404
    and absence from a successfully-read inventory both report the documented terminal answer for a
    gone sandbox, which is the one case where a missing sandbox is legitimate evidence that a
    reservation ended. ``endAt`` is ignored for this decision: a scheduled end is a lifetime signal,
    not an observation that the workload stopped.
    """
    wanted = _sandbox_id(sandbox_id)
    if response.not_found:
        return {"state": "not_found", "running": False}
    if not response.ok:
        raise _refusal("state", response)
    for entry in _json_array(response.body):
        if not isinstance(entry, Mapping):
            raise SandboxUnavailableError("E2B sandbox inventory is malformed")
        if entry.get("sandboxID") != wanted:
            continue
        state = entry.get("state")
        if not isinstance(state, str) or not state.strip():
            raise SandboxUnavailableError("E2B sandbox state is unobservable")
        normalized = state.strip().lower()
        return {"state": normalized,
                "running": normalized not in E2B_NON_RUNNING_PROVIDER_STATES}
    return {"state": "not_found", "running": False}


def decode_e2b_kill(response: E2BHttpResponse) -> bool:
    """An acknowledgement, never an outcome. The adapter must still observe state.

    404 counts as acknowledgement of intent, not as proof: a sandbox that is already absent may
    have been reaped by its own TTL. Only ``state()`` can end a lease.
    """
    if response.ok or response.not_found:
        return True
    raise _refusal("kill", response)


def decode_e2b_list(response: E2BHttpResponse) -> tuple[Mapping[str, Any], ...]:
    """The account's sandbox inventory, projected to correlation fields only."""
    if not response.ok:
        raise _refusal("list", response)
    observed: list[Mapping[str, Any]] = []
    for entry in _json_array(response.body):
        if not isinstance(entry, Mapping):
            raise SandboxUnavailableError("E2B sandbox inventory is malformed")
        sandbox_id = entry.get("sandboxID")
        state = entry.get("state")
        if not isinstance(sandbox_id, str) or not isinstance(state, str) or not state.strip():
            raise SandboxUnavailableError("E2B sandbox inventory is malformed")
        started_at = entry.get("startedAt")
        end_at = entry.get("endAt")
        observed.append({
            "sandbox_id": _sandbox_id(sandbox_id),
            "state": state.strip().lower(),
            "started_at": started_at if isinstance(started_at, str) else None,
            "end_at": end_at if isinstance(end_at, str) else None,
        })
    return tuple(observed)


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------


class LiveE2BSandboxTransport:
    """Satisfies ``E2BSandboxTransport`` against the documented E2B API.

    Every verb checks the gate first and performs no I/O while it is closed, so the live path needs
    both an owner-issued ``E2BLiveAuthorization`` and a reviewed change to the repository flags that
    record wiring, credential binding, readiness and live wire verification. Construction opens
    nothing.

    ``list_running`` is reconciliation support for the canonical contract's cross-run-reuse and
    teardown controls; the adapter itself never treats an inventory read as a termination.
    """

    provider_candidate = SandboxProviderCandidate.E2B
    live_execution_ready = E2B_LIVE_EXECUTION_READY

    def __init__(
        self,
        *,
        request_port: E2BHttpRequestPort | None = None,
        credential_port: EnvironmentE2BCredentialPort | None = None,
        authorization: E2BLiveAuthorization | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if clock is not None and not callable(clock):
            raise E2BWireError("clock must be callable or omitted")
        if authorization is not None and not isinstance(authorization, E2BLiveAuthorization):
            raise E2BWireError("authorization must be an E2BLiveAuthorization")
        if request_port is not None and not callable(getattr(request_port, "request", None)):
            raise E2BWireError("request_port must implement request()")
        # A missing clock is refused at use rather than silently reading a wall clock, which is the
        # rule the launch adapter already holds itself to.
        self._clock = clock if clock is not None else _no_clock
        self._request_port = request_port if request_port is not None else UnconfiguredE2BHttpRequestPort()
        self._credential_port = credential_port
        self._authorization = authorization

    # -- gate -----------------------------------------------------------------

    def _authorize(self) -> bytes:
        """Check the gate, then resolve the credential. Both before any socket."""
        if self._authorization is None:
            raise SandboxUnavailableError(
                "E2B live gate is closed: no owner authorization was supplied to this transport"
            )
        self._authorization.require_armed(self._now())
        if self._credential_port is None:
            raise SandboxUnavailableError("E2B live gate is closed: no credential port was wired")
        return self._credential_port.resolve()

    def _call(
        self,
        *,
        method: str,
        path: str,
        credential: bytes,
        body: Mapping[str, Any] | None,
    ) -> E2BHttpResponse:
        raw = None if body is None else json.dumps(
            dict(body), separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return self._request_port.request(
            method=method,
            path=path,
            credential=credential,
            body=raw,
            timeout_seconds=E2B_TRANSPORT_TIMEOUT_SECONDS,
        )

    def _now(self) -> datetime:
        return _aware(self._clock(), "clock")

    # -- E2BSandboxTransport --------------------------------------------------

    def create(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        credential = self._authorize()
        body = encode_e2b_create_body(payload)
        response = self._call(method="POST", path=E2B_CREATE_PATH, credential=credential, body=body)
        return decode_e2b_create_response(response)

    def state(self, sandbox_id: str) -> Mapping[str, Any]:
        credential = self._authorize()
        response = self._call(method="GET", path=E2B_LIST_PATH, credential=credential, body=None)
        return decode_e2b_state(response, sandbox_id)

    def kill(self, sandbox_id: str) -> bool:
        credential = self._authorize()
        response = self._call(
            method="DELETE",
            path=_path_for(E2B_DELETE_PATH_TEMPLATE, sandbox_id),
            credential=credential,
            body=None,
        )
        return decode_e2b_kill(response)

    def list_running(self) -> tuple[Mapping[str, Any], ...]:
        credential = self._authorize()
        response = self._call(method="GET", path=E2B_LIST_PATH, credential=credential, body=None)
        return decode_e2b_list(response)

    # -- provider capability the canonical ports imply but the prototype omits --

    def extend_lifetime(self, sandbox_id: str, *, ttl_seconds: int) -> bool:
        """Move the provider-side TTL alongside a canonical ``renew``.

        The adapter's ``renew`` extends the lease in the repository's own terms; E2B will still end
        the sandbox on its original timer unless told otherwise, so renew-and-extend needs this
        second leg. It is acknowledgement-only, exactly like ``kill``: it does not prove anything
        about a workload, and it never mints a sandbox.
        """
        credential = self._authorize()
        timeout = _bounded_int(
            ttl_seconds, "ttl_seconds",
            minimum=SANDBOX_LEASE_MIN_TTL_SECONDS, maximum=SANDBOX_LEASE_MAX_TTL_SECONDS,
        )
        response = self._call(
            method="POST",
            path=_path_for(E2B_TIMEOUT_PATH_TEMPLATE, sandbox_id),
            credential=credential,
            body={"timeout": timeout},
        )
        if response.ok or response.not_found:
            return True
        raise _refusal("timeout", response)

    def safe_dict(self) -> dict[str, Any]:
        blocked = (
            list(self._authorization.blocked_reasons)
            if self._authorization is not None
            else ["no authorization supplied to this transport"]
        )
        return {
            "contract_version": "claw-e2b-live-transport.v1",
            "provider_candidate": self.provider_candidate.value,
            "live_execution_ready": self.live_execution_ready,
            "gate_armed": bool(self._authorization is not None and self._authorization.armed),
            "blocked_reasons": blocked,
            "request_port_is_unconfigured": isinstance(
                self._request_port, UnconfiguredE2BHttpRequestPort
            ),
            "credential_port_configured": self._credential_port is not None,
            "credential_binding_name": E2B_CREDENTIAL_BINDING_NAME,
            "credential_value": None,
            "provider_endpoint": E2B_API_HOST,
            "real_provider_calls": E2B_REAL_PROVIDER_CALLS,
            "real_sandbox_allocations": E2B_REAL_SANDBOX_ALLOCATIONS,
            "process_tree_kill_attested": False,
            "physical_kill_claim_prohibited": True,
            "production_claim": False,
        }


def _no_clock() -> datetime:
    raise SandboxUnavailableError(
        "E2B live transport requires an injected clock; it never reads a wall clock itself"
    )


def e2b_live_transport_readiness() -> dict[str, Any]:
    """Why no live transport exists in this build, as data a reviewer can check.

    Deliberately not a factory: a function that could return an armed transport would be the
    composition root, and the composition root is the owner's decision, not this child's.
    """
    return {
        "composition_root_wired": E2B_LIVE_TRANSPORT_COMPOSITION_ROOT_WIRED,
        "credential_bound": LIVE_CREDENTIAL_BOUND,
        "live_execution_ready": E2B_LIVE_EXECUTION_READY,
        "wire_contract_live_verified": E2B_WIRE_CONTRACT_LIVE_VERIFIED,
        "owner_live_gate_required": E2B_OWNER_LIVE_GATE_REQUIRED,
        "real_provider_calls": E2B_REAL_PROVIDER_CALLS,
        "real_sandbox_allocations": E2B_REAL_SANDBOX_ALLOCATIONS,
        "request_port_default": UnconfiguredE2BHttpRequestPort.__name__,
        "production_claim": False,
    }


# ---------------------------------------------------------------------------
# pre-live probe packet + acceptance matrix
# ---------------------------------------------------------------------------

#: The controls CENTRAL named, each with the probe method that could settle it. Everything else in
#: the canonical capability list falls back to an adapter assertion until its probe is written.
E2B_LIVE_CONTROL_PROBE_METHODS: Mapping[str, ProbeMethod] = {
    "checkout_hooks_disabled": ProbeMethod.IN_SANDBOX_NEGATIVE_TEST,
    "provider_metadata_blocked": ProbeMethod.IN_SANDBOX_NEGATIVE_TEST,
    "cancellation_kills_workload": ProbeMethod.LIFECYCLE_OBSERVATION,
    "teardown_guaranteed": ProbeMethod.LIFECYCLE_OBSERVATION,
    "artifact_allowlist_enforced": ProbeMethod.ARTIFACT_VERIFICATION,
    "terminal_output_bounded": ProbeMethod.ARTIFACT_VERIFICATION,
}


@dataclass(frozen=True, slots=True)
class E2BPreLiveProbeReadinessPacket:
    """The exact one-shot plan, with the owner's decisions left as visible placeholders.

    Fields only the owner can supply carry the literal ``OWNER_REQUIRED`` string rather than a
    guess, so ``ready_for_owner_approval`` is False by construction here and no reader can mistake a
    completed-looking plan for an authorized one.
    """

    candidate: SandboxProviderCandidate
    target_environment: str
    plan: str
    credential_binding_name: str
    spend_cap: str
    ttl_seconds: int
    max_sandbox_allocations: int
    max_provider_execution_paths: int
    network_policy: str
    repository_ref: str
    exact_revision: str
    task: str
    verification_command: str
    expected_changed_files: str
    expected_diff_evidence: str
    teardown_check: str
    abort_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, SandboxProviderCandidate):
            raise E2BWireError("packet candidate must be a SandboxProviderCandidate")
        if self.candidate is not SandboxProviderCandidate.E2B:
            raise E2BWireError("this packet is E2B-specific")
        object.__setattr__(self, "credential_binding_name",
                           _binding_name(self.credential_binding_name, "credential_binding_name"))
        if self.network_policy != "OFF":
            raise E2BWireError("the probe packet may only describe a network-off launch")
        object.__setattr__(self, "max_sandbox_allocations",
                           _bounded_int(self.max_sandbox_allocations, "max_sandbox_allocations",
                                        minimum=1, maximum=1))
        object.__setattr__(self, "max_provider_execution_paths",
                           _bounded_int(self.max_provider_execution_paths,
                                        "max_provider_execution_paths", minimum=1, maximum=1))
        object.__setattr__(self, "ttl_seconds",
                           _bounded_int(self.ttl_seconds, "ttl_seconds",
                                        minimum=SANDBOX_LEASE_MIN_TTL_SECONDS,
                                        maximum=SANDBOX_LEASE_MAX_TTL_SECONDS))
        object.__setattr__(self, "repository_ref", _ref(self.repository_ref, "repository_ref"))
        object.__setattr__(self, "exact_revision",
                           _revision_or_placeholder(self.exact_revision, "exact_revision"))
        # Plan and amount fields are enumerable tokens; the task and evidence fields are prose, so
        # they take the bounded-text rule instead of an identifier grammar. Both paths still screen
        # for credential material.
        for field in ("target_environment", "plan", "spend_cap"):
            _ref(getattr(self, field), field)
        for field in ("task", "verification_command", "expected_changed_files",
                      "expected_diff_evidence", "teardown_check"):
            _text(getattr(self, field), field)
        if not isinstance(self.abort_conditions, tuple) or not self.abort_conditions:
            raise E2BWireError("a probe without abort conditions is not a probe plan")
        for index, condition in enumerate(self.abort_conditions):
            _ref(condition, f"abort_conditions[{index}]")

    @property
    def unresolved_owner_fields(self) -> tuple[str, ...]:
        return tuple(
            name
            for name in ("target_environment", "plan", "spend_cap", "exact_revision", "task",
                         "verification_command", "expected_changed_files", "expected_diff_evidence",
                         "teardown_check")
            if getattr(self, name) == E2B_OWNER_REQUIRED
        )

    @property
    def ready_for_owner_approval(self) -> bool:
        return not self.unresolved_owner_fields

    def acceptance_matrix(self) -> tuple[Mapping[str, str], ...]:
        """One row per required Cloud M1 control, with what would settle it.

        ``E2B_CONTROL_PROVENANCE`` and the canonical capability list are read here rather than
        copied, so the gap between the controls this adapter can name and the controls Cloud M1
        requires shows up in the output instead of being smoothed away. Nothing in this matrix can
        read as live-verified: ``live_status`` has no ``LIVE_OBSERVED`` producer.
        """
        from .e2b_sandbox import E2B_CONTROL_PROVENANCE

        labelled = dict(E2B_CONTROL_PROVENANCE)
        rows: list[Mapping[str, str]] = []
        for control in capability_control_names():
            provenance = labelled.get(control, "unlabelled_by_adapter")
            live_status = {
                E2BControlProvenance.ADAPTER_BORNE.value: "ADAPTER_BORNE_NOT_LIVE_VERIFIED",
                E2BControlProvenance.PROVIDER_DOCUMENTED.value: "PROVIDER_DOCUMENTED_NOT_MEASURED",
                E2BControlProvenance.UNVERIFIED_LIVE.value: "UNVERIFIED_LIVE",
                "unlabelled_by_adapter": "UNLABELLED_BY_ADAPTER",
            }.get(provenance, "UNVERIFIED_LIVE")
            method = E2B_LIVE_CONTROL_PROBE_METHODS.get(control)
            rows.append({
                "control": control,
                "provenance": provenance,
                "live_status": live_status,
                "probe_method": (method or ProbeMethod.ADAPTER_ASSERTION).value,
                "acceptance_basis_required": "live_provider_probe_or_trusted_attestation",
            })
        return tuple(rows)

    def safe_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "claw-e2b-pre-live-probe-readiness-packet.v1",
            "provider_candidate": self.candidate.value,
            "target_environment": self.target_environment,
            "plan": self.plan,
            "credential_binding_name": self.credential_binding_name,
            "spend_cap": self.spend_cap,
            "ttl_seconds": self.ttl_seconds,
            "max_sandbox_allocations": self.max_sandbox_allocations,
            "max_provider_execution_paths": self.max_provider_execution_paths,
            "network_policy": self.network_policy,
            "repository_ref": self.repository_ref,
            "exact_revision": self.exact_revision,
            "task": self.task,
            "verification_command": self.verification_command,
            "expected_changed_files": self.expected_changed_files,
            "expected_diff_evidence": self.expected_diff_evidence,
            "teardown_check": self.teardown_check,
            "abort_conditions": list(self.abort_conditions),
            "unresolved_owner_fields": list(self.unresolved_owner_fields),
            "ready_for_owner_approval": self.ready_for_owner_approval,
            "live_execution_ready": False,
            "provider_formally_selected": False,
            "real_provider_calls": E2B_REAL_PROVIDER_CALLS,
            "real_sandbox_allocations": E2B_REAL_SANDBOX_ALLOCATIONS,
            "credential_value": None,
            "production_claim": False,
        }


def build_e2b_pre_live_probe_packet(*, ttl_seconds: int = 900) -> E2BPreLiveProbeReadinessPacket:
    """The packet as this child can honestly fill it: every owner-only field is a placeholder."""
    return E2BPreLiveProbeReadinessPacket(
        candidate=SandboxProviderCandidate.E2B,
        target_environment=E2B_OWNER_REQUIRED,
        plan=E2B_OWNER_REQUIRED,
        credential_binding_name=E2B_CREDENTIAL_BINDING_NAME,
        spend_cap=E2B_OWNER_REQUIRED,
        ttl_seconds=ttl_seconds,
        max_sandbox_allocations=1,
        max_provider_execution_paths=1,
        network_policy="OFF",
        repository_ref="skerishKang/ai-revenue-lab",
        exact_revision=E2B_OWNER_REQUIRED,
        task=E2B_OWNER_REQUIRED,
        verification_command=E2B_OWNER_REQUIRED,
        expected_changed_files=E2B_OWNER_REQUIRED,
        expected_diff_evidence=E2B_OWNER_REQUIRED,
        teardown_check=E2B_OWNER_REQUIRED,
        abort_conditions=(
            "abort:provider-allocates-more-than-one-sandbox",
            "abort:provider-reports-egress-allowed",
            "abort:provider-reports-public-url-or-open-port",
            "abort:provider-metadata-address-reachable",
            "abort:terminal-state-unobservable",
            "abort:credential-material-in-provider-response-or-logs",
            "abort:spend-cap-approached",
        ),
    )


def e2b_launch_profile_for_cloud_m1(
    *, max_ttl_seconds: int = SANDBOX_LEASE_MAX_TTL_SECONDS
) -> CloudM1ProviderLaunchProfile:
    """Reuse the canonical profile builder instead of restating its settings.

    Returned as-is, including its hardcoded ``live_execution_ready`` False: the profile is the plan
    of record for what a probe must satisfy, not an authorization to run one.
    """
    return build_candidate_launch_profile(
        SandboxProviderCandidate.E2B, max_ttl_seconds=max_ttl_seconds
    )


def e2b_live_probe_plan(
    profile: CloudM1ProviderLaunchProfile | None = None,
    *,
    evidence_ttl_seconds: int = 3_600,
) -> SandboxProviderLiveProbePlan:
    """The full canonical probe plan, which refuses to cover anything less than every control."""
    return build_live_probe_plan(
        profile or e2b_launch_profile_for_cloud_m1(),
        evidence_ttl_seconds=evidence_ttl_seconds,
    )


__all__ = [
    "E2BHttpResponse",
    "E2BLiveAuthorization",
    "E2BPlan",
    "E2BPreLiveProbeReadinessPacket",
    "E2BTargetEnvironment",
    "EnvironmentE2BCredentialPort",
    "LiveE2BSandboxTransport",
    "StdlibE2BHttpRequestPort",
    "UnconfiguredE2BHttpRequestPort",
    "build_e2b_pre_live_probe_packet",
    "decode_e2b_create_response",
    "decode_e2b_kill",
    "decode_e2b_list",
    "decode_e2b_state",
    "e2b_launch_profile_for_cloud_m1",
    "e2b_live_probe_plan",
    "e2b_live_transport_readiness",
    "encode_e2b_create_body",
]
