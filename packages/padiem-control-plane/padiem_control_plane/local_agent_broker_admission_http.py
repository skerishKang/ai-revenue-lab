from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable

from .local_agent_broker_http import (
    LocalAgentBrokerHttpHandler,
    LocalAgentBrokerHttpResponse,
    TrustedLocalAgentHttpAuthContext,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ROUTE_ADMISSION = "/admission"
_ADMISSION_REQUEST_KEYS = frozenset(
    {"session_id", "binding_ref", "credential_b64", "command_id", "request_fingerprint", "now"}
)
_ADMISSION_KEYS = frozenset(
    {
        "admission_ref",
        "authority_ref",
        "command_id",
        "session_id",
        "binding_ref",
        "run_id",
        "tool_request_ref",
        "sequence",
        "request_fingerprint",
        "evidence_ref",
        "accepted_at",
        "expires_at",
        "raw_argv",
        "raw_device_credential",
    }
)

AdmissionReferenceFactory = Callable[[], tuple[str, str]]


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be ISO-8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be valid ISO-8601 text") from exc
    return _aware(parsed, field_name)


def _closed_mapping(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != expected:
        raise ValueError(f"{label} schema mismatch")
    return value


def _json_content_type(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Local Agent HTTP content-type is required")
    if value.split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("Local Agent HTTP content-type must be application/json")


def _iso(value: datetime) -> str:
    return _aware(value, "timestamp").isoformat().replace("+00:00", "Z")


class AdmissionEnabledLocalAgentBrokerHttpHandler(LocalAgentBrokerHttpHandler):
    """M2e handler plus one server-owned canonical broker admission transition.

    The device identifies the exact current queued command/fingerprint but cannot
    supply admission/evidence references. Those references come exclusively from
    an injected trusted server factory. The canonical broker RPC remains the sole
    owner of the queued -> admitted state transition and replay/sequence rules.
    """

    def __init__(self, *, admission_reference_factory: AdmissionReferenceFactory, **kwargs: Any) -> None:
        if not callable(admission_reference_factory):
            raise ValueError("admission_reference_factory must be callable")
        super().__init__(**kwargs)
        self._admission_reference_factory = admission_reference_factory

    def _references(self) -> tuple[str, str]:
        refs = self._admission_reference_factory()
        if type(refs) is not tuple or len(refs) != 2:
            raise ValueError("admission reference factory must return exactly two references")
        admission_ref = _ref(refs[0], "admission_ref")
        evidence_ref = _ref(refs[1], "evidence_ref")
        if admission_ref == evidence_ref:
            raise ValueError("admission_ref and evidence_ref must be distinct")
        return admission_ref, evidence_ref

    def _handle_admission(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _ADMISSION_REQUEST_KEYS, "admission request")
        _timestamp(payload["now"], "client_now")  # request evidence only; server clock owns admission time
        command_id = _ref(payload["command_id"], "command_id")
        binding_ref = _ref(payload["binding_ref"], "binding_ref")
        fingerprint = _digest(payload["request_fingerprint"], "request_fingerprint")
        self._load_scoped_session(auth=auth, payload=payload, server_now=server_now)
        auth_result = self._authenticate_session_via_rpc(payload, server_now=server_now)
        if auth_result["ok"] is False:
            return LocalAgentBrokerHttpResponse(200, auth_result)

        admission_ref, evidence_ref = self._references()
        result = self._rpc_result(
            self._rpc.admit_command(
                {
                    "admission_ref": admission_ref,
                    "evidence_ref": evidence_ref,
                    "session_id": payload["session_id"],
                    "binding_ref": binding_ref,
                    "credential_b64": payload["credential_b64"],
                    "command_id": command_id,
                    "request_fingerprint": fingerprint,
                    "now": _iso(server_now),
                }
            ),
            "admission",
        )
        if result["ok"] is False:
            return LocalAgentBrokerHttpResponse(200, result)

        admission = _closed_mapping(result["admission"], _ADMISSION_KEYS, "broker admission")
        if _ref(admission["admission_ref"], "admission_ref") != admission_ref:
            raise ValueError("broker admission_ref mismatch")
        if _ref(admission["evidence_ref"], "evidence_ref") != evidence_ref:
            raise ValueError("broker evidence_ref mismatch")
        if _ref(admission["session_id"], "session_id") != _ref(payload["session_id"], "session_id"):
            raise ValueError("broker admission session mismatch")
        if _ref(admission["binding_ref"], "binding_ref") != binding_ref:
            raise ValueError("broker admission binding mismatch")
        if _ref(admission["command_id"], "command_id") != command_id:
            raise ValueError("broker admission command mismatch")
        if _digest(admission["request_fingerprint"], "request_fingerprint") != fingerprint:
            raise ValueError("broker admission fingerprint mismatch")
        if admission["raw_argv"] is not False or admission["raw_device_credential"] is not False:
            raise ValueError("broker admission attempted raw authority expansion")
        if _timestamp(admission["accepted_at"], "accepted_at") != server_now:
            raise ValueError("broker admission must use exact server-owned accepted_at")
        expires_at = _timestamp(admission["expires_at"], "expires_at")
        if expires_at <= server_now:
            raise ValueError("broker admission expiry must follow acceptance")
        _ref(admission["authority_ref"], "authority_ref")
        _ref(admission["run_id"], "run_id")
        _ref(admission["tool_request_ref"], "tool_request_ref")
        sequence = admission["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("broker admission sequence must be a positive integer")
        return LocalAgentBrokerHttpResponse(200, {"ok": True, "admission": admission})

    def handle(
        self,
        *,
        method: str,
        route: str,
        content_type: str,
        body: bytes,
        auth: TrustedLocalAgentHttpAuthContext | None,
    ) -> LocalAgentBrokerHttpResponse:
        if route != _ROUTE_ADMISSION:
            return super().handle(
                method=method,
                route=route,
                content_type=content_type,
                body=body,
                auth=auth,
            )

        denied = self._auth(auth)
        if denied is not None:
            return denied
        assert auth is not None
        if method != "POST":
            return self._error(405, "local_agent_http_post_required", "Local Agent broker routes accept POST only")
        try:
            _json_content_type(content_type)
        except (TypeError, ValueError):
            return self._error(415, "local_agent_http_json_required", "Local Agent broker routes require application/json")
        if not isinstance(body, bytes) or not body:
            return self._error(400, "local_agent_http_invalid_json", "Local Agent broker request body is invalid")
        try:
            payload = self._decode(body)
            server_now = self._server_now()
            return self._handle_admission(auth, payload, server_now=server_now)
        except PermissionError:
            return self._error(403, "local_agent_http_scope_mismatch", "authenticated Local Agent scope does not match request")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return self._error(400, "local_agent_http_invalid_request", "Local Agent broker request is invalid")
        except RuntimeError:
            return self._error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")

    def safe_dict(self) -> dict[str, Any]:
        return {
            **super().safe_dict(),
            "admission_route": _ROUTE_ADMISSION,
            "server_owned_admission_refs": True,
            "client_admission_authority": False,
            "canonical_broker_admission_reused": True,
            "server_admission_time_authority": True,
            "raw_admission_argv": False,
            "raw_admission_device_credential": False,
            "production_endpoint_configured": False,
            "production_ready": False,
        }


PHYSICAL_ADMISSION_HTTP_BOUNDARY = True
SERVER_OWNED_ADMISSION_REFS = True
CLIENT_ADMISSION_AUTHORITY = False
CANONICAL_BROKER_ADMISSION_REUSED = True
SERVER_ADMISSION_TIME_AUTHORITY = True
RAW_ADMISSION_ARGV = False
RAW_ADMISSION_DEVICE_CREDENTIAL = False
PRODUCTION_ENDPOINT_CONFIGURED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
