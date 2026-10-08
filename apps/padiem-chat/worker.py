"""Cloudflare Python Worker entrypoint for Padiem Chat (Business 62).

The deployed Starlette application is built from Cloudflare Worker bindings,
not from browser input and not from stale import-time process environment.
Provider/model execution remains Business 14 authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

# The Core B14StreamingClient owns a real httpx.AsyncClient.  Its injected
# Service-Binding transport must use that same httpx Request/Response/stream
# type family; app.httpx_compat is only for app-owned JS-fetch clients.
import httpx
from padiem_ai_core.b14_execution import MAX_B14_RESPONSE_BYTES
from app.service_binding_response import (
    ServiceBindingResponseError,
    ServiceBindingResponseTooLarge,
    cloudflare_chunk_bytes,
    read_bounded_service_binding_body,
)
from app.claw_automation_due_workspace_discovery import (
    compose_canonical_due_workspace_discovery,
)
from app.claw_automation_owner_resolution import ClawAutomationOwnerResolver
from app.claw_automation_scheduled_execution import (
    compose_scheduled_automation_execution,
)
from app.claw_automation_store import D1ClawAutomationStore
from app.claw_local_access_composition import (
    build_claw_local_access_source_with_diagnostic,
)
from app.desktop_conversation_authority import (
    build_desktop_device_session_authority_with_diagnostic,
)
from app.claw_p01_composition import (
    build_claw_p01_adapter,
    build_claw_p01_lanes_with_diagnostic,
)
from app.claw_task_alert_store import D1ClawTaskAlertStore
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.b66_registered_model_boundary import (
    B14QuoteExactModelExecutor,
    B66RegisteredModelCompletion,
)
from app.b66_b14_free_first_resolver import B14FreeFirstQuoteModelResolver
from app.config import ConfigError
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from app.calendar_read_activation_engine import CloudflareCalendarReadActivationEngineClient
from app.calendar_read_state_engine import CloudflareCalendarReadStateEngineClient
from app.control_plane_identity_shadow import D1IdentityShadowStore
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.dispatch_quota import (
    DispatchAwareB14Client,
    DispatchAwareUsageCounterStore,
    _refund_active_reservation,
)
from app.grounding import GroundedChatService
from app.history import D1HistoryStore
from app.claw_local_task_result_composition import (
    build_local_task_result_source_with_diagnostic,
)
from app.main import create_app
from app.orchestration_routes import install_orchestration_routes
from app.project_files import D1ProjectFileStore
from app.saved_outputs import D1SavedOutputStore
from app.usage_gate import D1UsageCounterStore, UsageGate
from app.worker_config import (
    B14_SERVICE_BINDING_NAME,
    B66_PDF_RENDERER_SERVICE_BINDING_NAME,
    D1_BINDING_NAME,
    GOOGLE_OAUTH_SERVICE_BINDING_NAME,
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    WORKSPACE_R2_BINDING_NAME,
    apply_live_deadman_switch,
    binding_value,
    response_headers_for_path,
    settings_from_worker_bindings,
    p01_engine_config_from_worker_bindings,
)
from app.worker_orchestration import build_orchestration_bridge
from kagent.claw_automation import ClawAutomationTickRuntime
from kagent.claw_automation_trigger import ClawAutomationTriggerBoundary
from workers import Request, Response, WorkerEntrypoint

_worker_app = None
_AUTOMATION_SCHEDULER_ENABLED_ENV = "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED"
BACKGROUND_SCHEDULER_SOURCE_READY = True
CRON_SOURCE_DECLARATION = False
PRODUCTION_CRON_ACTIVATION = False
PRODUCTION_MUTATION = False


def _automation_source_enabled(env: Any) -> bool:
    value = getattr(env, _AUTOMATION_SCHEDULER_ENABLED_ENV, False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return value is True


async def run_scheduled_automation_source(
    env: Any, *, now: datetime | None = None, execution_ports: Any | None = None
) -> Any:
    if not _automation_source_enabled(env):
        return None
    db_binding = binding_value(env, D1_BINDING_NAME)
    identity_binding = binding_value(env, IDENTITY_AUTHORITY_SERVICE_BINDING_NAME)
    if db_binding is None or identity_binding is None:
        return None
    try:
        store = D1ClawAutomationStore(db_binding)
        identity_authority = CloudflareControlPlaneIdentityAuthority(identity_binding)
        boundary = ClawAutomationTriggerBoundary(ClawAutomationTickRuntime(store))
        discovery = compose_canonical_due_workspace_discovery(
            automation_store=store,
            control_plane_identity_authority=identity_authority,
            trigger_boundary=boundary,
        )
        if execution_ports is None:
            adapter = build_claw_p01_adapter(env, request_factory=Request)
            if adapter is None:
                return None
            shadow_store = D1IdentityShadowStore(db_binding)
            owner_resolver = ClawAutomationOwnerResolver(
                owner_authority=identity_authority,
                session_authority=identity_authority,
                shadow_store=shadow_store,
                # #3247: the production owner identity source. Background rules
                # carry a canonical subject, so resolution derives identity from
                # Control Plane canonical facts through this authority.
                canonical_owner_authority=identity_authority,
            )
            history_store = D1HistoryStore(db_binding)
            task_alert_store = D1ClawTaskAlertStore(db_binding)
        else:
            adapter = getattr(execution_ports, "adapter", None)
            owner_resolver = getattr(execution_ports, "owner_resolver", None)
            history_store = getattr(execution_ports, "history_store", None)
            task_alert_store = getattr(execution_ports, "task_alert_store", None)
            if any(
                value is None
                for value in (adapter, owner_resolver, history_store, task_alert_store)
            ):
                return None
        return await compose_scheduled_automation_execution(
            discovery=discovery,
            boundary=boundary,
            store=store,
            adapter=adapter,
            owner_resolver=owner_resolver,
            history_store=history_store,
            task_alert_store=task_alert_store,
            now=now or datetime.now(timezone.utc),
        )
    except Exception:
        return None


def _apply_headers(
    response: Any,
    path: str,
    *,
    b66_quote_base_url: str | None = None,
) -> Any:
    for name, value in response_headers_for_path(
        path,
        b66_quote_base_url=b66_quote_base_url,
    ).items():
        response.headers[name] = value
    return response


class CloudflareB66PdfRendererClient:
    """Private render-only adapter over the dedicated PDF Worker binding."""

    def __init__(self, binding: Any):
        if binding is None:
            raise ValueError("B66 PDF renderer service binding is required")
        self.binding = binding

    async def render_pdf(
        self, *, saved_skill_id: str, skill_fingerprint: str,
        profile_fingerprint: str, render_model: dict[str, Any],
    ) -> tuple[int, bytes, str]:
        request = Request(
            "https://padiem-b66-pdf-renderer/internal/v1/render",
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps({
                "saved_skill_id": saved_skill_id,
                "skill_fingerprint": skill_fingerprint,
                "profile_fingerprint": profile_fingerprint,
                "render_model": render_model,
            }, ensure_ascii=False, separators=(",", ":")),
        )
        response = await self.binding.fetch(request.js_object)
        status = int(response.status)
        content_type = response.headers.get("content-type") or ""
        try:
            body = await read_bounded_service_binding_body(response, max_bytes=32 * 1024 * 1024)
        except (ServiceBindingResponseTooLarge, ServiceBindingResponseError) as exc:
            raise RuntimeError("B66 PDF renderer response could not be read") from exc
        return status, body, str(content_type)


class CloudflareB14ServiceTransport:
    """HTTP-shaped adapter over a Cloudflare Worker Service Binding.

    Routing authority is the fixed `B14_SERVICE` binding. The URL is still fully
    qualified because the Fetcher API expects an absolute URL, but service-binding
    configuration — not the hostname — selects the target Worker.
    """

    def __init__(self, binding: Any):
        if binding is None:
            raise ValueError("B14 service binding is required")
        self.binding = binding

    async def get_json(self, path: str) -> tuple[int, bytes]:
        """Read only two fixed B14 model authority endpoints over Service Binding."""
        if path not in (
            "/api/pilot/models",
            "/api/pilot/provider-readiness",
        ):
            raise ValueError("unsupported B14 model-authority read endpoint")
        request = Request(
            "https://b14.internal" + path,
            method="GET",
        )
        response = await self.binding.fetch(request.js_object)
        status = int(response.status)
        try:
            body = await read_bounded_service_binding_body(
                response, max_bytes=131072,
            )
        except (ServiceBindingResponseTooLarge, ServiceBindingResponseError):
            raise RuntimeError("bounded B14 model authority read unavailable") from None
        return status, body

    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, bytes]:
        request = Request(
            url,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False),
        )
        response = await self.binding.fetch(request.js_object)
        status = int(response.status)
        try:
            body = await read_bounded_service_binding_body(
                response,
                max_bytes=MAX_B14_RESPONSE_BYTES,
            )
        except ServiceBindingResponseTooLarge:
            # Core owns the public "response too large" classification. Return
            # one bounded sentinel byte beyond its configured ceiling so that
            # classification remains unchanged without consuming the rest of
            # the Service Binding stream.
            return status, bytes(MAX_B14_RESPONSE_BYTES + 1)
        except ServiceBindingResponseError as exc:
            raise RuntimeError(
                "Business 14 Service Binding response could not be read."
            ) from exc
        return status, body


class _CloudflareReadableByteStream(httpx.AsyncByteStream):
    """Expose a Service Binding Response body to httpx without buffering it."""

    def __init__(self, body: Any):
        if body is None:
            raise httpx.ProtocolError("Business 14 Service Binding response body is unavailable.")
        self._body = body
        self._reader: Any | None = None
        self._closed = False
        self._finished = False

    def _reader_or_create(self) -> Any:
        if self._reader is None:
            try:
                self._reader = self._body.getReader()
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding stream reader is unavailable."
                ) from exc
        return self._reader

    @staticmethod
    def _to_bytes(value: Any) -> bytes:
        try:
            return cloudflare_chunk_bytes(value)
        except ServiceBindingResponseError as exc:
            raise httpx.ReadError(
                "Business 14 Service Binding returned an unsupported stream chunk."
            ) from exc

    async def __aiter__(self):
        reader = self._reader_or_create()
        try:
            while True:
                result = await reader.read()
                if bool(getattr(result, "done", False)):
                    self._finished = True
                    return
                chunk = self._to_bytes(getattr(result, "value", None))
                if chunk:
                    yield chunk
        except httpx.HTTPError:
            raise
        except Exception as exc:
            raise httpx.ReadError(
                "Business 14 Service Binding stream read failed.",
            ) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        reader = self._reader
        if reader is None:
            return

        try:
            if not self._finished:
                cancel = getattr(reader, "cancel", None)
                if callable(cancel):
                    await cancel()
        except Exception:
            pass
        finally:
            release_lock = getattr(reader, "releaseLock", None)
            if callable(release_lock):
                try:
                    release_lock()
                except Exception:
                    pass


class CloudflareB14StreamingServiceTransport(httpx.AsyncBaseTransport):
    """Progressive httpx transport backed by the fixed B14 Service Binding."""

    def __init__(self, binding: Any):
        if binding is None:
            raise ValueError("B14 service binding is required")
        self.binding = binding

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = await request.aread()
            body_text = bytes(body).decode("utf-8")
        except Exception as exc:
            raise httpx.RequestError(
                "Business 14 streaming request could not be encoded.",
                request=request,
            ) from exc

        try:
            service_request = Request(
                str(request.url),
                method="POST",
                headers={"Content-Type": "application/json"},
                body=body_text,
            )
        except Exception as exc:
            raise httpx.RequestError(
                "Business 14 streaming request could not be constructed.",
                request=request,
            ) from exc

        try:
            service_response = await self.binding.fetch(service_request.js_object)
        except Exception as exc:
            raise httpx.ConnectError(
                "Business 14 Service Binding is unavailable.",
                request=request,
            ) from exc

        try:
            status_code = int(service_response.status)
            content_type = service_response.headers.get("content-type")
            response_body = service_response.body
        except Exception as exc:
            raise httpx.ProtocolError(
                "Business 14 Service Binding returned malformed response metadata.",
                request=request,
            ) from exc

        try:
            headers: dict[str, str] = {}
            if content_type is not None:
                headers["content-type"] = str(content_type)

            return httpx.Response(
                status_code=status_code,
                headers=headers,
                stream=_CloudflareReadableByteStream(response_body),
                request=request,
            )
        except Exception as exc:
            raise httpx.ProtocolError(
                "Business 14 Service Binding response could not be adapted.",
                request=request,
            ) from exc


class _CloudflareExternalFetchByteStream(httpx.AsyncByteStream):
    """Expose a JavaScript fetch Response body to real httpx incrementally."""

    def __init__(
        self,
        body: Any,
        *,
        request: httpx.Request,
        timeout_signal: Any | None,
    ):
        if body is None:
            raise httpx.ProtocolError(
                "Worker fetch response body is unavailable.",
                request=request,
            )
        self._body = body
        self._request = request
        self._timeout_signal = timeout_signal
        self._reader: Any | None = None
        self._closed = False
        self._finished = False

    def _reader_or_create(self) -> Any:
        if self._reader is None:
            try:
                self._reader = self._body.getReader()
            except Exception as exc:
                raise httpx.ReadError(
                    "Worker fetch response body reader is unavailable.",
                    request=self._request,
                ) from exc
        return self._reader

    def _timed_out(self) -> bool:
        if self._timeout_signal is None:
            return False
        try:
            return bool(self._timeout_signal.aborted)
        except Exception:
            return False

    async def __aiter__(self):
        reader = self._reader_or_create()
        try:
            while True:
                result = await reader.read()
                if bool(getattr(result, "done", False)):
                    self._finished = True
                    return
                chunk = _CloudflareReadableByteStream._to_bytes(
                    getattr(result, "value", None)
                )
                if chunk:
                    yield chunk
        except httpx.HTTPError:
            raise
        except Exception as exc:
            if self._timed_out():
                raise httpx.ReadTimeout(
                    "Worker fetch timed out while reading the response body.",
                    request=self._request,
                ) from exc
            raise httpx.ReadError(
                "Worker fetch response body read failed.",
                request=self._request,
            ) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        reader = self._reader
        if reader is None:
            return
        try:
            if not self._finished:
                cancel = getattr(reader, "cancel", None)
                if callable(cancel):
                    await cancel()
        except Exception:
            pass
        finally:
            release_lock = getattr(reader, "releaseLock", None)
            if callable(release_lock):
                try:
                    release_lock()
                except Exception:
                    pass


class _CloudflareEmptyAsyncByteStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        if False:
            yield b""

    async def aclose(self) -> None:
        return None


class CloudflareExternalHttpTransport(httpx.AsyncBaseTransport):
    """Real-httpx transport backed by Workers' JavaScript fetch API.

    Core Firecrawl/Daum providers own a real httpx.AsyncClient, so this adapter
    deliberately stays in the same real-httpx type family while replacing only
    the unsupported socket-backed network boundary with Workers fetch.
    """

    def __init__(
        self,
        *,
        fetch_impl: Any | None = None,
        abort_signal_api: Any | None = None,
    ):
        if fetch_impl is None or abort_signal_api is None:
            try:
                from js import AbortSignal as js_abort_signal  # type: ignore
                from js import fetch as js_fetch  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "Worker external HTTP transport requires the Workers JS runtime."
                ) from exc
            fetch_impl = js_fetch if fetch_impl is None else fetch_impl
            abort_signal_api = (
                js_abort_signal if abort_signal_api is None else abort_signal_api
            )
        self._fetch = fetch_impl
        self._abort_signal_api = abort_signal_api

    @staticmethod
    def _timeout_seconds(request: httpx.Request) -> float | None:
        timeout = request.extensions.get("timeout")
        if not isinstance(timeout, dict):
            return None
        # Core web providers put the full provider deadline in the read timeout.
        # Treat it as one fetch/body deadline because Workers fetch does not
        # expose separate connect/read socket phases.
        raw = timeout.get("read")
        if raw is None:
            raw = timeout.get("connect")
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 else None

    def _timeout_signal(self, request: httpx.Request) -> Any | None:
        seconds = self._timeout_seconds(request)
        if seconds is None:
            return None
        milliseconds = max(1, int(round(seconds * 1000)))
        try:
            return self._abort_signal_api.timeout(milliseconds)
        except Exception as exc:
            raise httpx.RequestError(
                "Worker fetch timeout signal is unavailable.",
                request=request,
            ) from exc

    @staticmethod
    async def _headers(
        js_headers: Any,
        *,
        request: httpx.Request,
    ) -> dict[str, str]:
        try:
            result: dict[str, str] = {}
            entries = js_headers.entries()
            while True:
                entry = entries.next()
                if hasattr(entry, "__await__"):
                    entry = await entry
                if bool(getattr(entry, "done", False)):
                    break
                pair = getattr(entry, "value", None)
                if pair is None:
                    continue
                result[str(pair[0])] = str(pair[1])
            return result
        except Exception:
            pass

        try:
            result = {}
            for key in js_headers:
                result[str(key)] = str(js_headers.get(key))
            return result
        except Exception as exc:
            raise httpx.ProtocolError(
                "Worker external fetch returned malformed response headers.",
                request=request,
            ) from exc

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = bytes(await request.aread())
            transport_managed = {
                "host",
                "content-length",
                "transfer-encoding",
                "connection",
            }
            headers = {
                str(k): str(v)
                for k, v in request.headers.items()
                if str(k).lower() not in transport_managed
            }
        except Exception as exc:
            raise httpx.RequestError(
                "Worker fetch request could not be encoded.",
                request=request,
            ) from exc

        init: dict[str, Any] = {
            "method": request.method,
            "headers": headers,
            "redirect": "manual",
        }
        if body:
            init["body"] = body

        timeout_signal = self._timeout_signal(request)
        if timeout_signal is not None:
            init["signal"] = timeout_signal

        try:
            try:
                from js import Object as _JsObject  # type: ignore
                from pyodide.ffi import to_js as _to_js  # type: ignore
            except (ImportError, ModuleNotFoundError):
                js_init = init
            else:
                js_init = _to_js(
                    init,
                    dict_converter=_JsObject.fromEntries,
                    create_pyproxies=False,
                )
            js_response = await self._fetch(str(request.url), js_init)
        except Exception as exc:
            timed_out = False
            if timeout_signal is not None:
                try:
                    timed_out = bool(timeout_signal.aborted)
                except Exception:
                    timed_out = False
            if timed_out:
                raise httpx.ReadTimeout(
                    "Worker fetch timed out before response headers.",
                    request=request,
                ) from exc
            raise httpx.ConnectError(
                "Worker external fetch is unavailable.",
                request=request,
            ) from exc

        try:
            status_code = int(js_response.status)
            response_headers = await self._headers(
                js_response.headers,
                request=request,
            )
            response_body = getattr(js_response, "body", None)
        except httpx.ProtocolError:
            raise
        except Exception as exc:
            raise httpx.ProtocolError(
                "Worker external fetch returned malformed response metadata.",
                request=request,
            ) from exc

        stream: httpx.AsyncByteStream
        if response_body is None:
            stream = _CloudflareEmptyAsyncByteStream()
        else:
            stream = _CloudflareExternalFetchByteStream(
                response_body,
                request=request,
                timeout_signal=timeout_signal,
            )

        return httpx.Response(
            status_code=status_code,
            headers=response_headers,
            stream=stream,
            request=request,
        )


class Default(WorkerEntrypoint):
    async def scheduled(self, event: Any, env: Any, ctx: Any) -> None:
        del event, ctx
        await run_scheduled_automation_source(env)

    async def fetch(self, request: Any) -> Any:
        import asgi

        global _worker_app
        path = urlparse(request.url).path

        if _worker_app is None:
            try:
                settings = apply_live_deadman_switch(settings_from_worker_bindings(self.env))
                db_binding = binding_value(self.env, D1_BINDING_NAME)
                b14_binding = binding_value(self.env, B14_SERVICE_BINDING_NAME)
                b66_pdf_binding = binding_value(self.env, B66_PDF_RENDERER_SERVICE_BINDING_NAME)
                identity_binding = binding_value(self.env, IDENTITY_AUTHORITY_SERVICE_BINDING_NAME)
                google_oauth_binding = binding_value(self.env, GOOGLE_OAUTH_SERVICE_BINDING_NAME)
                # Private Claw workspace bytes (#2266). Resolved from trusted
                # Worker bindings only; absent until #2259/#2246 activation, in
                # which case WorkspaceDocumentStore stays None (fail closed).
                r2_binding = binding_value(self.env, WORKSPACE_R2_BINDING_NAME)

                history_store = D1HistoryStore(db_binding) if db_binding is not None else None
                project_file_store = D1ProjectFileStore(db_binding) if db_binding is not None else None
                saved_output_store = D1SavedOutputStore(db_binding) if db_binding is not None else None
                identity_shadow_store = D1IdentityShadowStore(db_binding) if db_binding is not None else None
                identity_authority = (
                    CloudflareControlPlaneIdentityAuthority(identity_binding)
                    if identity_binding is not None
                    else None
                )
                google_oauth_workspace_truth = (
                    CloudflareGoogleOAuthWorkspaceTruth(google_oauth_binding)
                    if google_oauth_binding is not None
                    else None
                )
                base_usage_store = D1UsageCounterStore(db_binding) if db_binding is not None else None
                usage_store = (
                    DispatchAwareUsageCounterStore(base_usage_store)
                    if base_usage_store is not None
                    else None
                )
                service_transport = (
                    CloudflareB14ServiceTransport(b14_binding)
                    if b14_binding is not None
                    else None
                )
                stream_transport = (
                    CloudflareB14StreamingServiceTransport(b14_binding)
                    if b14_binding is not None
                    else None
                )
                web_transport = CloudflareExternalHttpTransport()
                b66_pdf_renderer_client = (
                    CloudflareB66PdfRendererClient(b66_pdf_binding)
                    if b66_pdf_binding is not None
                    else None
                )
                _worker_app = create_app(
                    settings=settings,
                    history_store=history_store,
                    d1_binding=db_binding,
                    r2_binding=r2_binding,
                    web_transport=web_transport,
                    b66_pdf_renderer_client=b66_pdf_renderer_client,
                )
                _worker_app.state.control_plane_identity_authority = identity_authority
                _worker_app.state.identity_shadow_store = identity_shadow_store
                # #3257: the Worker's real runtime env is the execution-target
                # authority. The Create route resolves the served revision from
                # this injected env only — never from a request value or the
                # global process environment. With the live version-metadata
                # binding not yet activated, resolution fails closed (503) and
                # no rule is saved. NOTE: this scope only has ``self.env``
                # (bindings are read from it above); a bare ``env`` name here
                # would crash the Worker on first initialization.
                _worker_app.state.claw_automation_execution_target_authority = self.env
                # #3190: reuse the existing P01_ENGINE_SERVICE binding; no second
                # Engine binding authority. Missing/malformed binding -> None ->
                # the Drive case-folder routes fail closed with 503.
                try:
                    from app.drive_case_folder_engine import (
                        CloudflareDriveCaseFolderEngineClient,
                    )
                    from app.worker_config import P01_ENGINE_SERVICE_BINDING_NAME

                    engine_binding = binding_value(self.env, P01_ENGINE_SERVICE_BINDING_NAME)
                    drive_case_folder_engine_client = (
                        CloudflareDriveCaseFolderEngineClient(engine_binding)
                        if engine_binding is not None
                        else None
                    )
                except Exception:
                    drive_case_folder_engine_client = None
                _worker_app.state.drive_case_folder_engine_client = drive_case_folder_engine_client
                # #2952: Calendar READ activation reuses the existing P01 Engine
                # Service Binding and caller credential. No second Engine authority.
                try:
                    p01_config = p01_engine_config_from_worker_bindings(self.env)
                    calendar_read_activation_client = (
                        CloudflareCalendarReadActivationEngineClient(
                            p01_config.service_binding,
                            caller_id=p01_config.caller_id,
                            credential=p01_config.credential,
                            request_factory=Request,
                        )
                        if p01_config is not None
                        else None
                    )
                except Exception:
                    calendar_read_activation_client = None
                _worker_app.state.calendar_read_activation_client = calendar_read_activation_client
                # Persisted Calendar READ grant state (#2952 follow-up): the
                # read-only half, over the same P01 Engine Service Binding and
                # caller credential. No second Engine authority; an
                # unconfigured binding leaves the state surface absent rather
                # than inventing a grant answer.
                try:
                    p01_config_state = p01_engine_config_from_worker_bindings(self.env)
                    calendar_read_state_engine_client = (
                        CloudflareCalendarReadStateEngineClient(
                            p01_config_state.service_binding,
                            caller_id=p01_config_state.caller_id,
                            credential=p01_config_state.credential,
                            request_factory=Request,
                        )
                        if p01_config_state is not None
                        else None
                    )
                except Exception:
                    calendar_read_state_engine_client = None
                _worker_app.state.calendar_read_state_engine_client = calendar_read_state_engine_client
                _worker_app.state.project_file_store = project_file_store
                _worker_app.state.saved_output_store = saved_output_store
                _worker_app.state.usage_gate = UsageGate(settings, usage_store)
                _worker_app.state.usage_gate_enforced = True
                _worker_app.state.b14_client = DispatchAwareB14Client(
                    settings,
                    service_transport=service_transport,
                    stream_transport=stream_transport,
                    require_service_binding=settings.runtime_mode == "b14",
                )
                # #3760: quote extraction selects one exact, evidenced-free
                # route from B14's already-registered authority. Never pass
                # ordinary quote text into the B62 Plus/Pro/Max HOLD resolver;
                # never synthesize b14/auto or a hidden retry/fallback.
                _worker_app.state.b66_quote_interpreter = B66QuoteConversationInterpreter(
                    B66RegisteredModelCompletion(
                        resolver=B14FreeFirstQuoteModelResolver(service_transport),
                        executor=B14QuoteExactModelExecutor(
                            _worker_app.state.b14_client
                        ),
                        refund_pre_dispatch=_refund_active_reservation,
                    )
                )
                _worker_app.state.grounded_chat = GroundedChatService(
                    _worker_app.state.b14_client,
                    _worker_app.state.web_provider,
                )
                _worker_app.state.b14_service_bound = b14_binding is not None
                _worker_app.state.identity_authority_service_bound = identity_binding is not None
                _worker_app.state.google_oauth_workspace_truth = google_oauth_workspace_truth
                _worker_app.state.google_oauth_service_bound = google_oauth_binding is not None
                (
                    _worker_app.state.claw_p01_adapter,
                    _worker_app.state.claw_p01_continuation_client,
                    _worker_app.state.claw_p01_composition_diagnostic,
                ) = build_claw_p01_lanes_with_diagnostic(
                    self.env,
                    request_factory=Request,
                )
                # #3094: compose the concrete canonical local-access source
                # from a trusted broker-authority binding only. When the
                # trusted runtime is absent (today's deploy) the composition
                # yields None and the app keeps the fail-closed unconfigured
                # source installed by create_app.
                claw_local_access_source, _claw_local_access_diag = (
                    build_claw_local_access_source_with_diagnostic(self.env)
                )
                if claw_local_access_source is not None:
                    _worker_app.state.claw_local_access_source = claw_local_access_source
                # #3436 B2c: compose the canonical device-session authority for
                # the GET-only Desktop conversation surface from the same
                # trusted broker binding. When the trusted runtime is absent
                # (today's deploy) the composition yields None and the app
                # keeps the fail-closed unconfigured authority installed by
                # create_app; no browser-cookie or self-asserted fallback
                # exists on this surface.
                _desktop_device_session_authority, _desktop_auth_diag = (
                    build_desktop_device_session_authority_with_diagnostic(self.env)
                )
                if _desktop_device_session_authority is not None:
                    _worker_app.state.desktop_device_session_authority = (
                        _desktop_device_session_authority
                    )
                # #3139: compose the Local Runner return leg from the same
                # trusted broker binding and the real D1 history store. Absent
                # either, the composition yields None and the route keeps the
                # fail-closed unconfigured source installed by create_app.
                _local_task_result_source, _local_task_result_diag = (
                    build_local_task_result_source_with_diagnostic(self.env, history_store)
                )
                _worker_app.state.local_task_result_source = _local_task_result_source
                _worker_app.state.local_task_result_diagnostic = _local_task_result_diag
                install_orchestration_routes(
                    _worker_app,
                    build_orchestration_bridge(
                        self.env,
                        settings=settings,
                        db_binding=db_binding,
                        request_factory=Request,
                    ),
                )
            except ConfigError:
                response = Response(
                    "Padiem Chat runtime configuration is invalid.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                return _apply_headers(response, path)

        response = await asgi.fetch(_worker_app, request.js_object, self.env)
        return _apply_headers(
            response,
            path,
            b66_quote_base_url=getattr(_worker_app.state, "b66_quote_base_url", None),
        )
