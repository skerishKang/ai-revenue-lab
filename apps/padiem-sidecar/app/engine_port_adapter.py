"""B53 server-mediated EnginePort adapter (#2204 S8-ACT1).

Implements the canonical IP-SIDECAR :class:`EnginePort` contract over the
existing Engine-defined caller contract (``x-padiem-engine-caller`` /
``x-padiem-engine-credential``). The caller id/credential and the reviewed
capability routes are server-only deployment state: they never reach browser
config, public diagnostics, errors, or logs.

Boundary locks:
- B53 never consumes the Control Plane identity binding, the model-service
  binding, provider credentials, or Engine authentication policy.
- B53 never calls the Control Plane or the model service directly; the only
  destination is the Engine authenticated ingress execute path.
- The transport is an injected server-side seam; no public Engine hostname is
  hard-coded here, and this module performs no network I/O by itself.
- Tenant/subject/app authority stays with Engine and the Control Plane;
  browser-supplied payload cannot mint or override it.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from padiem_embedded_runtime.engine_port import EnginePort
from padiem_embedded_runtime.errors import SidecarContractError

REVIEWED_ENGINE_CAPABILITIES = frozenset({"context.project", "notice.render"})

ENGINE_EXECUTE_PATH = "/internal/v1/execute"
CALLER_ID_HEADER = "x-padiem-engine-caller"
CALLER_CREDENTIAL_HEADER = "x-padiem-engine-credential"

MAX_CAPABILITY_TEXT_CHARS = 8_000
_MAX_AGENT_FIELD_CHARS = 256

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

ENGINE_CALLER_ID_ENV = "PADIEM_SIDECAR_ENGINE_CALLER_ID"
ENGINE_CALLER_CREDENTIAL_ENV = "PADIEM_SIDECAR_ENGINE_CALLER_CREDENTIAL"
ENGINE_APP_ID_ENV = "PADIEM_SIDECAR_ENGINE_APP_ID"
ENGINE_MODEL_ROUTES_ENV = "PADIEM_SIDECAR_ENGINE_MODEL_ROUTES_JSON"

_REVIEWED_AGENT_DEFINITIONS: Mapping[str, Mapping[str, object]] = {
    "context.project": {
        "id": "padiem-sidecar-context-project",
        "title": "Padiem Sidecar context projection",
        "description": "Projects one bounded sidecar context text for the product surface.",
        "system_instruction": "Return a concise projection of the provided sidecar context text.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 1024,
    },
    "notice.render": {
        "id": "padiem-sidecar-notice-render",
        "title": "Padiem Sidecar notice render",
        "description": "Renders one bounded sidecar notice text for the product surface.",
        "system_instruction": "Return the provided sidecar notice text rendered for display.",
        "task_type": "general",
        "optimize_for": "balanced",
        "max_tokens": 1024,
    },
}


@dataclass(frozen=True, slots=True)
class EngineIngressResponse:
    """Bounded response returned by an injected server-side Engine ingress transport."""

    status: int
    body: bytes

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int) or not 100 <= self.status <= 599:
            raise SidecarContractError("transport response status must be an HTTP status integer")
        if not isinstance(self.body, bytes):
            raise SidecarContractError("transport response body must be bytes")


class EngineIngressTransport(Protocol):
    """Server-only synchronous transport seam to the Engine authenticated ingress.

    The injected implementation owns the private destination (for example a
    Cloudflare Service Binding adapter in a later Worker composition). This
    module never resolves or hard-codes an Engine host.
    """

    def request(
        self,
        *,
        method: str,
        path: str,
        headers: Mapping[str, str],
        body: bytes,
    ) -> EngineIngressResponse: ...


class EngineCallerConfig:
    """Server-only Engine caller contract state consumed from deployment config.

    Reuses the Engine-defined caller headers and validation bounds. Values are
    never serialized into any public projection, error text, or repr.
    """

    def __init__(
        self,
        *,
        app_id: object,
        caller_id: object,
        credential: object,
        model_routes: object,
    ) -> None:
        self.app_id = _safe_identifier("app_id", app_id)
        self._caller_id = _safe_identifier("caller_id", caller_id)
        self._credential = _credential(credential)
        self._model_routes = _model_routes(model_routes)

    @property
    def caller_id(self) -> str:
        return self._caller_id

    @property
    def credential(self) -> str:
        return self._credential

    def model_route_for(self, capability: str) -> str:
        return self._model_routes[capability]

    def __repr__(self) -> str:
        return "EngineCallerConfig(app_id=<redacted>, caller_id=<redacted>, credential=<redacted>)"

    def to_public_dict(self) -> dict[str, object]:
        return {
            "configured": True,
            "capabilities": sorted(REVIEWED_ENGINE_CAPABILITIES),
            "authority": "engine_remains_final_caller_gate",
        }


class ServerMediatedEnginePort(EnginePort):
    """Canonical EnginePort implementation routed through the Engine ingress.

    Only reviewed Sidecar capabilities map to Engine execute semantics. The
    browser/host payload contributes exactly one bounded text field; every
    authority-bearing field (app id, caller identity, agent route) comes from
    server-only configuration.
    """

    def __init__(self, *, transport: object, caller_config: object) -> None:
        if transport is None or not callable(getattr(transport, "request", None)):
            raise SidecarContractError("engine ingress transport must provide request()")
        if not isinstance(caller_config, EngineCallerConfig):
            raise SidecarContractError("engine caller config must be server-only EngineCallerConfig")
        self._transport = transport
        self._caller = caller_config

    def invoke_capability(self, capability: str, payload: Mapping[str, object]) -> Mapping[str, object]:
        if capability not in REVIEWED_ENGINE_CAPABILITIES:
            raise SidecarContractError(f"capability {capability!r} is not reviewed for B53 engine transport")
        if not isinstance(payload, Mapping):
            raise SidecarContractError("capability payload must be a mapping")
        if set(payload) != {"text"}:
            raise SidecarContractError(
                "capability payload must carry exactly one bounded text field; "
                "authority fields are never browser-supplied"
            )
        text = payload["text"]
        if not isinstance(text, str) or not text.strip():
            raise SidecarContractError("capability text must be a non-empty string")
        if len(text) > MAX_CAPABILITY_TEXT_CHARS:
            raise SidecarContractError("capability text exceeds the bound")

        request_body = json.dumps(
            self._execute_request(capability, text),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            CALLER_ID_HEADER: self._caller.caller_id,
            CALLER_CREDENTIAL_HEADER: self._caller.credential,
        }
        try:
            response = self._transport.request(
                method="POST",
                path=ENGINE_EXECUTE_PATH,
                headers=headers,
                body=request_body,
            )
        except SidecarContractError:
            raise
        except Exception:
            raise SidecarContractError("engine transport failure") from None
        if not isinstance(response, EngineIngressResponse):
            raise SidecarContractError("engine transport returned an invalid response")
        return self._project_success(capability, response)

    def describe(self) -> dict[str, object]:
        """Public-safe diagnostics; caller identity and routes stay server-only."""
        return {
            "kind": "server_mediated_engine_port",
            "destination": "engine_authenticated_ingress",
            "capabilities": sorted(REVIEWED_ENGINE_CAPABILITIES),
            "caller": self._caller.to_public_dict(),
        }

    def _execute_request(self, capability: str, text: str) -> dict[str, object]:
        agent = dict(_REVIEWED_AGENT_DEFINITIONS[capability])
        agent["model_policy"] = {"model": self._caller.model_route_for(capability)}
        return {
            "app_id": self._caller.app_id,
            "agent": agent,
            "messages": [{"role": "user", "content": text.strip()}],
        }

    def _project_success(self, capability: str, response: EngineIngressResponse) -> Mapping[str, object]:
        try:
            body = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SidecarContractError("engine returned an invalid JSON response") from None
        if not isinstance(body, dict):
            raise SidecarContractError("engine returned an invalid response object")
        if body.get("ok") is False:
            error = body.get("error") if isinstance(body.get("error"), Mapping) else {}
            code = error.get("code") if isinstance(error.get("code"), str) and _ERROR_CODE_RE.fullmatch(error["code"]) else "engine_request_failed"
            raise SidecarContractError(f"engine request failed: {code}")
        if not 200 <= response.status < 300:
            raise SidecarContractError("engine request failed")
        answer = body.get("answer")
        if body.get("ok") is not True or not isinstance(answer, str):
            raise SidecarContractError("engine completed-run response is invalid")
        return {"capability": capability, "ok": True, "answer": answer}


def _safe_identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise SidecarContractError(f"{name} must be a bounded safe identifier")
    return value


def _credential(value: object) -> str:
    if not isinstance(value, str) or not 32 <= len(value.encode("utf-8")) <= 512:
        raise SidecarContractError("engine caller credential must contain 32 to 512 bytes")
    return value


def _model_routes(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise SidecarContractError("engine model routes must be a server-only mapping")
    if set(value) != set(REVIEWED_ENGINE_CAPABILITIES):
        raise SidecarContractError("engine model routes must cover exactly the reviewed capabilities")
    return {capability: _safe_identifier(f"model_routes.{capability}", route) for capability, route in value.items()}


def engine_caller_config_from_environ(
    environ: Mapping[str, str] | None = None,
) -> EngineCallerConfig:
    """Build the server-only caller config from deployment environment state; fail closed."""
    env = os.environ if environ is None else environ
    raw_routes = env.get(ENGINE_MODEL_ROUTES_ENV)
    if not isinstance(raw_routes, str) or not raw_routes.strip():
        raise SidecarContractError("engine model routes configuration is missing")
    try:
        routes = json.loads(raw_routes)
    except json.JSONDecodeError:
        raise SidecarContractError("engine model routes configuration is malformed") from None
    return EngineCallerConfig(
        app_id=env.get(ENGINE_APP_ID_ENV),
        caller_id=env.get(ENGINE_CALLER_ID_ENV),
        credential=env.get(ENGINE_CALLER_CREDENTIAL_ENV),
        model_routes=routes,
    )


def build_server_engine_port(
    *,
    transport: object,
    environ: Mapping[str, str] | None = None,
) -> ServerMediatedEnginePort:
    """Explicit server-runtime composition; the fake default stays untouched elsewhere."""
    return ServerMediatedEnginePort(
        transport=transport,
        caller_config=engine_caller_config_from_environ(environ),
    )
