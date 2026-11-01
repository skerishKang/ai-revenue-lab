from __future__ import annotations

import base64
from datetime import datetime, timezone
import re
from typing import Any

from .contracts import ControlPlaneContractError
from .local_agent_broker_admission_http import AdmissionEnabledLocalAgentBrokerHttpHandler
from .local_agent_broker_http import (
    MAX_LOCAL_AGENT_HTTP_BODY_BYTES,
    LocalAgentBrokerHttpHandler,
    LocalAgentBrokerHttpResponse,
    TrustedLocalAgentHttpAuthContext,
)
from .local_agent_broker_pairing import (
    MAX_PAIRING_CREDENTIAL_BYTES,
    MAX_PAIRING_TTL_SECONDS,
    MIN_PAIRING_TTL_SECONDS,
    PAIRING_CODE_HEX_CHARS,
    PAIRING_PROOF_TRANSCRIPT,
    PROOF_REF_RE,
    BrokerPairingAuthorityPort,
    BrokerPairingChallenge,
    BrokerPairingEnrollment,
)

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_PAIRING_CODE_RE = re.compile(rf"^[0-9a-f]{{{PAIRING_CODE_HEX_CHARS}}}$")

PAIRING_CHALLENGE_ROUTE = "/v1/broker/pairings/challenge"
PAIRING_REDEEM_ROUTE = "/v1/broker/pairings/redeem"
_PAIRING_ROUTES = frozenset({PAIRING_CHALLENGE_ROUTE, PAIRING_REDEEM_ROUTE})

_CHALLENGE_REQUEST_KEYS = frozenset({"account_ref", "workspace_ref", "now", "ttl_seconds"})
_REDEEM_REQUEST_KEYS = frozenset({"challenge_id", "device_id", "proof_ref", "now"})
_CHALLENGE_RESPONSE_KEYS = frozenset(
    {"ok", "challenge", "pairing_code", "pairing_code_returned_once", "proof_transcript"}
)
_ENROLLMENT_RESPONSE_KEYS = frozenset({"ok", "enrollment", "credential_b64", "credential_returned_once"})


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a bounded safe reference")
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


def _positive_int(value: Any, field_name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be an integer between {minimum} and {maximum} without coercion")
    return value


def _closed_mapping(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or frozenset(value) != expected:
        raise ValueError(f"{label} schema mismatch")
    return value


def _json_content_type(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Local Agent HTTP content-type is required")
    if value.split(";", 1)[0].strip().lower() != "application/json":
        raise ValueError("Local Agent HTTP content-type must be application/json")


class PairingEnabledLocalAgentBrokerHttpHandler(LocalAgentBrokerHttpHandler):
    """M2e handler plus the two proof-based broker pairing routes.

    ``/v1/broker/pairings/challenge`` is issued for an already authenticated
    account/workspace caller (the signed-in cloud/browser session). The returned
    one-time pairing code is the only secret a user carries to the desktop agent.

    ``/v1/broker/pairings/redeem`` is reachable by a device that has no broker
    credential yet. It is authenticated by the HMAC-SHA256 challenge proof plus a
    trusted TLS attestation, and account/workspace scope always comes from the
    stored server-side challenge, never from anything the redeeming device claims.
    """

    def __init__(self, *, pairing_authority: BrokerPairingAuthorityPort, **kwargs: Any) -> None:
        for method_name in ("issue_challenge", "redeem"):
            if not callable(getattr(pairing_authority, method_name, None)):
                raise ValueError("pairing_authority must implement issue_challenge and redeem")
        super().__init__(**kwargs)
        self._pairing_authority = pairing_authority

    def _pairing_auth(
        self,
        auth: TrustedLocalAgentHttpAuthContext | None,
        *,
        require_authenticated: bool,
    ) -> LocalAgentBrokerHttpResponse | None:
        if auth is None or not isinstance(auth, TrustedLocalAgentHttpAuthContext):
            return self._error(
                401,
                "local_agent_http_auth_required",
                "trusted Local Agent pairing context is required",
            )
        if auth.tls_verified is not True:
            return self._error(403, "local_agent_http_tls_required", "trusted TLS termination is required")
        if require_authenticated and auth.authenticated is not True:
            return self._error(
                401,
                "local_agent_http_auth_required",
                "authenticated Local Agent pairing access is required",
            )
        return None

    def _handle_pairing_challenge(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _CHALLENGE_REQUEST_KEYS, "pairing challenge request")
        _timestamp(payload["now"], "client_now")  # request evidence only; server clock owns issuance
        account_ref = _ref(payload["account_ref"], "account_ref")
        workspace_ref = _ref(payload["workspace_ref"], "workspace_ref")
        if account_ref != auth.account_ref:
            raise PermissionError("pairing challenge account does not match authenticated account")
        if workspace_ref != auth.workspace_ref:
            raise PermissionError("pairing challenge workspace does not match authenticated workspace")
        ttl_seconds = _positive_int(
            payload["ttl_seconds"],
            "ttl_seconds",
            minimum=MIN_PAIRING_TTL_SECONDS,
            maximum=MAX_PAIRING_TTL_SECONDS,
        )
        challenge, pairing_code = self._pairing_authority.issue_challenge(
            account_ref=auth.account_ref,
            workspace_ref=auth.workspace_ref,
            now=server_now,
            ttl_seconds=ttl_seconds,
        )
        if not isinstance(challenge, BrokerPairingChallenge):
            raise ValueError("pairing authority returned an invalid challenge")
        if challenge.account_ref != auth.account_ref or challenge.workspace_ref != auth.workspace_ref:
            raise PermissionError("pairing challenge escaped authenticated account/workspace scope")
        if challenge.issued_at != server_now:
            raise ValueError("pairing challenge must use the exact server-owned issuance time")
        if challenge.expires_at <= server_now:
            raise ValueError("pairing challenge expiry must follow server-owned issuance time")
        if not isinstance(pairing_code, str) or not _PAIRING_CODE_RE.fullmatch(pairing_code):
            raise ValueError("pairing authority returned an invalid pairing code")
        body = {
            "ok": True,
            "challenge": challenge.safe_dict(),
            "pairing_code": pairing_code,
            "pairing_code_returned_once": True,
            "proof_transcript": PAIRING_PROOF_TRANSCRIPT,
        }
        _closed_mapping(body, _CHALLENGE_RESPONSE_KEYS, "pairing challenge response")
        return LocalAgentBrokerHttpResponse(200, body)

    def _handle_pairing_redeem(
        self,
        auth: TrustedLocalAgentHttpAuthContext,
        payload: dict[str, Any],
        *,
        server_now: datetime,
    ) -> LocalAgentBrokerHttpResponse:
        payload = _closed_mapping(payload, _REDEEM_REQUEST_KEYS, "pairing redeem request")
        _timestamp(payload["now"], "client_now")  # request evidence only; server clock owns redemption
        challenge_id = _ref(payload["challenge_id"], "challenge_id")
        device_id = _ref(payload["device_id"], "device_id")
        proof_ref = payload["proof_ref"]
        if not isinstance(proof_ref, str) or not PROOF_REF_RE.fullmatch(proof_ref):
            raise ValueError("pairing proof must be a canonical HMAC-SHA256 proof reference")
        if auth.authenticated is True and auth.principal_ref != device_id:
            raise PermissionError("an authenticated pairing principal may only redeem its own device")
        enrollment, credential = self._pairing_authority.redeem(
            challenge_id=challenge_id,
            device_id=device_id,
            proof_ref=proof_ref,
            now=server_now,
        )
        if not isinstance(enrollment, BrokerPairingEnrollment):
            raise ValueError("pairing authority returned an invalid enrollment")
        if enrollment.device_id != device_id or enrollment.challenge_id != challenge_id:
            raise ValueError("pairing enrollment does not correlate with the redeemed challenge")
        if enrollment.issued_at != server_now:
            raise ValueError("pairing enrollment must use the exact server-owned issuance time")
        if not isinstance(credential, bytes) or not credential or len(credential) > MAX_PAIRING_CREDENTIAL_BYTES:
            raise ValueError("pairing authority returned invalid credential material")
        body = {
            "ok": True,
            "enrollment": enrollment.safe_dict(),
            "credential_b64": base64.b64encode(credential).decode("ascii"),
            "credential_returned_once": True,
        }
        _closed_mapping(body, _ENROLLMENT_RESPONSE_KEYS, "pairing enrollment response")
        return LocalAgentBrokerHttpResponse(200, body)

    def handle(
        self,
        *,
        method: str,
        route: str,
        content_type: str,
        body: bytes,
        auth: TrustedLocalAgentHttpAuthContext | None,
    ) -> LocalAgentBrokerHttpResponse:
        if route not in _PAIRING_ROUTES:
            return super().handle(
                method=method,
                route=route,
                content_type=content_type,
                body=body,
                auth=auth,
            )

        denied = self._pairing_auth(auth, require_authenticated=route == PAIRING_CHALLENGE_ROUTE)
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
        if len(body) > MAX_LOCAL_AGENT_HTTP_BODY_BYTES:
            return self._error(413, "local_agent_http_body_too_large", "Local Agent broker request body exceeds size bound")
        try:
            payload = self._decode(body)
            server_now = self._server_now()
            if route == PAIRING_CHALLENGE_ROUTE:
                return self._handle_pairing_challenge(auth, payload, server_now=server_now)
            return self._handle_pairing_redeem(auth, payload, server_now=server_now)
        except PermissionError:
            return self._error(
                403,
                "local_agent_http_scope_mismatch",
                "authenticated Local Agent scope does not match request",
            )
        except ControlPlaneContractError as exc:
            return self._error(400, exc.code, exc.safe_message)
        except (KeyError, TypeError, ValueError):
            return self._error(400, "local_agent_http_invalid_request", "Local Agent broker request is invalid")
        except RuntimeError:
            return self._error(503, "local_agent_http_dependency_unavailable", "Local Agent broker dependency is unavailable")

    def safe_dict(self) -> dict[str, Any]:
        return {
            **super().safe_dict(),
            "pairing_routes": sorted(_PAIRING_ROUTES),
            "pairing_proof_algorithm": "HMAC-SHA256",
            "pairing_proof_transcript": PAIRING_PROOF_TRANSCRIPT,
            "pairing_challenge_requires_authenticated_scope": True,
            "pairing_redeem_requires_tls_attestation": True,
            "pairing_redeem_requires_device_credential": False,
            "pairing_redeem_proof_verified_before_binding": True,
            "self_asserted_account_workspace_authority": False,
            "pairing_code_reusable": False,
            "raw_pairing_code_logged": False,
            "raw_device_credential_logged": False,
            "production_pairing_endpoint_configured": False,
            "production_ready": False,
        }


class PairingAndAdmissionLocalAgentBrokerHttpHandler(
    PairingEnabledLocalAgentBrokerHttpHandler,
    AdmissionEnabledLocalAgentBrokerHttpHandler,
):
    """Both M2 extension route families available on one deployable edge handler.

    Each mixin handles only its own routes and delegates every other route, so a
    single deployment boundary can serve pairing redemption and server-owned
    admission without duplicating either authority.
    """

    def safe_dict(self) -> dict[str, Any]:
        return {
            **super().safe_dict(),
            "pairing_and_admission_composed": True,
            "single_deployable_edge_handler": True,
        }


PAIRING_HTTP_BOUNDARY = True
PAIRING_CHALLENGE_ROUTES = (PAIRING_CHALLENGE_ROUTE, PAIRING_REDEEM_ROUTE)
PAIRING_CHALLENGE_REQUIRES_AUTHENTICATED_SCOPE = True
PAIRING_REDEEM_REQUIRES_TLS_ATTESTATION = True
PAIRING_REDEEM_REQUIRES_DEVICE_CREDENTIAL = False
PAIRING_REDEEM_PROOF_VERIFIED_BEFORE_BINDING = True
PAIRING_CODE_REUSABLE = False
SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY = False
RAW_PAIRING_CODE_LOGGED = False
RAW_DEVICE_CREDENTIAL_LOGGED = False
PUBLIC_PAIRING_EDGE_SERVICE_CONFIGURED = False
PRODUCTION_PAIRING_ENDPOINT_CONFIGURED = False
PRODUCTION_MUTATION = False
PRODUCTION_READY = False
