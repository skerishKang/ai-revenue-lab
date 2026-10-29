"""padiem-broker — the COM2 skeleton of the Local Agent broker (#5573 Stage 2-C).

The service is a thin transport around the SAME durable broker code the
Cloudflare Durable Object composes: `LocalAgentBrokerDurableRuntime`, the device
HTTP service, the text/office/profile stores and the pairing mixin. Only two
pieces are new here — the SQLite storage adapter (`storage.py`) and this entry
point. No broker rule is re-implemented.

Door rules (mirroring the #6149 target ingress):
* `POST /internal/rpc/<method>` only, guarded by the shared v1 service proof;
* an explicit allowlist of the Stage 2-C lanes — queue-owned dispatch methods
  (poll/admit/enqueue_command/reconcile) are not exposed here;
* the service refuses to start without its proof secret and pepper file;
* errors never echo payloads, credentials or method inventories.
"""
from __future__ import annotations

import os
import types
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from canonical_broker_pairing_rpc import (
    CanonicalBrokerPairingRPC,
    armed_durable_pairing_authority,
)
from internal_rpc_ingress import handle_internal_rpc
from local_agent_broker_android_profile import (
    BrokerAndroidSafProfileStore,
    android_saf_profile_rpc,
    android_saf_profiles_rpc,
)
from local_agent_broker_device_http import LocalAgentBrokerDeviceHttpService
from local_agent_broker_durable_runtime import LocalAgentBrokerDurableRuntime
from local_agent_broker_installed_profile import (
    BrokerInstalledExecutionProfileStore,
    installed_execution_profile_rpc,
)
from local_agent_broker_office_chunks import (
    compose_broker_office_chunks,
    read_broker_office_part_rpc,
)
from local_agent_broker_text_results import (
    compose_broker_text_results,
    read_verified_file_text_rpc,
)

from storage import SqLiteDurableStorage

#: The Stage 2-C lanes (design §1). Queue-owned dispatch lives in the mesh
#: queue and is deliberately absent.
BROKER_RPC_METHODS: frozenset[str] = frozenset({
    # device HTTP / sessions
    "handle_device_http",
    "open_session",
    "authenticate_device_session",
    "terminal_command_result",
    "device_truth",
    "device_directory",
    # enrollment / pairing (each method keeps its own default-off env gate)
    "install_pairing_schema",
    "issue_enrollment_challenge",
    "get_enrollment_binding",
    "verify_enrollment_bootstrap",
    "gateway_bootstrap_rpc",
    "recovery_verdict",
    "redeem_enrollment",
    # reads
    "read_verified_file_text",
    "read_office_artifact_part",
    "installed_execution_profile",
    "android_saf_profile",
    "android_saf_profiles",
    # credential maintenance + command material
    "rotate_credential",
    "revoke_binding",
    "enqueue_command_with_material",
    "store_command_material",
    "resolve_command_material",
    "acknowledge",
    "set_owner_usage",
})

_PROOF_SECRET_ENV = "PADIEM_BROKER_RPC_INGRESS_SECRET"
_PROOF_SECRET_FILE_ENV = "PADIEM_BROKER_RPC_INGRESS_SECRET_FILE"
_PEPPER_ENV = "LOCAL_AGENT_BROKER_PEPPER"
_PEPPER_FILE_ENV = "LOCAL_AGENT_BROKER_PEPPER_FILE"
_AUTHORITY_REF_ENV = "LOCAL_AGENT_BROKER_AUTHORITY_REF"
_DB_PATH_ENV = "PADIEM_BROKER_DB_PATH"
_MIN_SECRET_CHARS = 32
_MIN_PEPPER_CHARS = 32


class BrokerConfigError(RuntimeError):
    pass


def _secret_value(environ: dict[str, str], inline_env: str, file_env: str, *, label: str) -> str:
    inline = str(environ.get(inline_env, "")).strip()
    if inline:
        return inline
    path_text = str(environ.get(file_env, "")).strip()
    if not path_text:
        raise BrokerConfigError(f"{label} is required ({inline_env} or {file_env})")
    path = Path(path_text)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BrokerConfigError(f"{label} file is not readable") from exc
    if not value:
        raise BrokerConfigError(f"{label} file is empty")
    return value


def _broker_env(environ: dict[str, str], *, pepper: str, authority_ref: str) -> Any:
    """The Worker env shape the reused code expects, from LOCAL_AGENT_* vars."""

    values = {
        key: value for key, value in environ.items()
        if key.startswith("LOCAL_AGENT_") or key.startswith("PADIEM_BROKER_")
    }
    values[_AUTHORITY_REF_ENV] = authority_ref
    values[_PEPPER_ENV] = pepper
    return types.SimpleNamespace(**values)


class BrokerComposition(CanonicalBrokerPairingRPC):
    """The DO entrypoint's composition, without the Workers classes.

    Every method below is the same delegation `local_agent_broker_worker.py`
    performs; the pairing mixin above supplies the enrollment RPCs.
    """

    def __init__(self, *, storage: SqLiteDurableStorage, env: Any):
        self.env = env
        self._storage = storage
        self._runtime = LocalAgentBrokerDurableRuntime(storage=storage, env=env)
        self.http_state = self._runtime.http_state
        self.material_store = self._runtime.material_store
        authority_ref = self._runtime.authority_ref()
        self.office_chunks = compose_broker_office_chunks(
            storage=storage, state_port=self._runtime.state_port,
            authority_ref=authority_ref, env=env,
        )
        self.text_results = compose_broker_text_results(
            storage=storage, state_port=self._runtime.state_port, authority_ref=authority_ref,
        )
        self.execution_profiles = BrokerInstalledExecutionProfileStore(
            storage=storage, state_port=self._runtime.state_port, authority_ref=authority_ref,
        )
        self.android_profiles = BrokerAndroidSafProfileStore(
            storage=storage, state_port=self._runtime.state_port, authority_ref=authority_ref,
        )
        self._device_http = LocalAgentBrokerDeviceHttpService(
            state_port=self._runtime.state_port,
            pepper=str(env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8"),
            authority_ref=authority_ref,
            rpc_factory=self._runtime.facade,
            http_state=self._runtime.http_state,
            material_resolver=self._runtime.material_store,
            session_open_transaction=storage.transactionSync,
            office_chunks=self.office_chunks,
            text_results=self.text_results,
            execution_profiles=self.execution_profiles,
            android_profiles=self.android_profiles,
            owner_usage_gate=self._runtime.owner_usage.paused,
            pairing_authority=armed_durable_pairing_authority(
                env=env, storage=storage, state_port=self._runtime.state_port,
                authority_ref=authority_ref,
                pepper=str(env.LOCAL_AGENT_BROKER_PEPPER).encode("utf-8"),
            ),
        )

    # --- device / session lane -------------------------------------------
    async def handle_device_http(self, envelope: dict) -> dict:
        return self._device_http.handle(envelope)

    async def open_session(self, payload: dict) -> dict:
        return self._runtime.open_session(payload)

    async def authenticate_device_session(self, payload: dict) -> dict:
        return self._runtime.authenticate_device_session(payload)

    async def terminal_command_result(self, payload: dict) -> dict:
        return self._runtime.terminal_command_result(payload)

    async def device_truth(self, payload: dict) -> dict:
        return self._runtime.device_truth(payload)

    async def device_directory(self, payload: dict) -> dict:
        return self._runtime.device_directory(payload)

    # --- reads ------------------------------------------------------------
    async def read_verified_file_text(self, payload: dict) -> dict:
        return read_verified_file_text_rpc(self.text_results, payload)

    async def read_office_artifact_part(self, payload: dict) -> dict:
        return read_broker_office_part_rpc(self.office_chunks, payload)

    async def installed_execution_profile(self, payload: dict) -> dict:
        return installed_execution_profile_rpc(self.execution_profiles, payload)

    async def android_saf_profile(self, payload: dict) -> dict:
        return android_saf_profile_rpc(self.android_profiles, payload)

    async def android_saf_profiles(self, payload: dict) -> dict:
        return android_saf_profiles_rpc(self.android_profiles, payload)

    # --- credential maintenance + material --------------------------------
    async def rotate_credential(self, payload: dict) -> dict:
        return self._runtime.rotate_credential(payload)

    async def revoke_binding(self, payload: dict) -> dict:
        return self._runtime.revoke_binding(payload)

    async def enqueue_command_with_material(self, payload: dict) -> dict:
        wire = payload.get("payload")
        material = payload.get("material")
        if not isinstance(wire, dict) or not isinstance(material, dict):
            return {"ok": False, "error": {"code": "invalid_rpc_payload", "message": "envelope required"}}
        return self._runtime.enqueue_command_with_material(wire, material)

    async def store_command_material(self, payload: dict) -> dict:
        return self._runtime.store_command_material(payload)

    async def resolve_command_material(self, payload: dict) -> dict:
        return self._runtime.resolve_command_material(payload)

    async def acknowledge(self, payload: dict) -> dict:
        return self._runtime.acknowledge(payload)

    async def set_owner_usage(self, payload: dict) -> dict:
        return self._runtime.set_owner_usage(payload)


def build_app(
    *, environ: dict[str, str] | None = None, db_path: str | None = None
) -> Starlette:
    envs = dict(os.environ if environ is None else environ)
    secret = _secret_value(envs, _PROOF_SECRET_ENV, _PROOF_SECRET_FILE_ENV, label="RPC ingress secret")
    if len(secret) < _MIN_SECRET_CHARS:
        raise BrokerConfigError(f"RPC ingress secret must be at least {_MIN_SECRET_CHARS} characters")
    pepper = _secret_value(envs, _PEPPER_ENV, _PEPPER_FILE_ENV, label="broker pepper")
    if len(pepper) < _MIN_PEPPER_CHARS:
        raise BrokerConfigError(f"broker pepper must be at least {_MIN_PEPPER_CHARS} characters")
    authority_ref = str(envs.get(_AUTHORITY_REF_ENV, "")).strip()
    if not authority_ref:
        raise BrokerConfigError(f"{_AUTHORITY_REF_ENV} is required")
    path = db_path or str(envs.get(_DB_PATH_ENV, "")).strip()
    if not path:
        raise BrokerConfigError(f"{_DB_PATH_ENV} is required")

    storage = SqLiteDurableStorage.open(path)
    composition = BrokerComposition(
        storage=storage, env=_broker_env(envs, pepper=pepper, authority_ref=authority_ref),
    )

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "padiem-broker"})

    async def rpc_endpoint(request: Request) -> JSONResponse:
        handled = await handle_internal_rpc(
            request, secret=secret, allowed_methods=BROKER_RPC_METHODS,
            dispatcher=composition,
        )
        if handled is None:
            return JSONResponse(
                {"ok": False, "error": {"code": "not_found", "message": "Not Found"}},
                status_code=404, headers={"cache-control": "no-store"},
            )
        status, payload, headers = handled
        return JSONResponse(payload, status_code=status, headers=headers)

    app = Starlette(routes=[
        Route("/health", health, methods=["GET"]),
        Route("/internal/rpc/{method}", rpc_endpoint, methods=["POST"]),
    ])
    app.state.broker = composition
    app.state.broker_storage = storage
    return app
