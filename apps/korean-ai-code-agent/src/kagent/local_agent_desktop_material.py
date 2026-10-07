"""#3436 B2d — the bounded trusted-local Desktop session material channel.

The Desktop main process is the only consumer of the current canonical device
session material. This module adds **one** request/response exchange over the
existing supervised stdio boundary the resident already shares with the shell
(#3140 pairing handoff uses the same pipe) — no second socket, no TCP listener,
no generic RPC:

    PUBLIC_INBOUND_PORT=0
    LAN_BIND=0
    UPNP=0
    GENERIC_LOCAL_RPC=0
    DESKTOP_SESSION_OPEN=0

The resident answers with a projection of state it already holds:

    current host session (canonical broker session, opened by the host)
    -> existing protected credential store load (CANONICAL_CREDENTIAL_STORE_REUSED)
    -> one bounded base64 response line on stdout

No value is minted here, no session is opened here, and nothing is persisted:
the credential crosses the pipe once per request and is dropped. The response
line is the *only* place the credential appears; refusals carry a bounded,
secret-free reason code and never a credential, a session id or a binding ref
(RAW_CREDENTIAL_LOGGED=0). The Desktop-side capture redacts this line from any
retained output buffer, so no log, evidence file or diagnostics projection can
pick it up (RAW_CREDENTIAL_SECOND_PERSISTENCE=0).
"""

from __future__ import annotations

import base64
import json
import sys
import threading
from collections.abc import Callable
from typing import Any

from .contracts import ContractError

MATERIAL_REQUEST_CONTRACT_VERSION = "claw-desktop-session-material-request.v1"
MATERIAL_RESPONSE_CONTRACT_VERSION = "claw-desktop-session-material.v1"
MATERIAL_REQUEST_KIND = "desktop_device_session_material"
MATERIAL_RESPONSE_EVENT = "desktop_device_session_material"

# #3611 — the second and last request kind on this same pipe. The Desktop trusted
# main cannot itself be the one-shot authority (it owns no durable store), so it
# asks the resident — which owns the canonical durable row — to redeem the open
# before any view exists. This is the *only* place an approved open becomes
# durable, so there is exactly one ADMITTED -> EXECUTING owner.
REDEMPTION_REQUEST_CONTRACT_VERSION = "claw-browser-open-redemption-request.v1"
REDEMPTION_RESPONSE_CONTRACT_VERSION = "claw-browser-open-redemption.v1"
REDEMPTION_REQUEST_KIND = "browser_open_redemption"
REDEMPTION_RESPONSE_EVENT = "browser_open_redemption"

#: The complete, closed set of request kinds this pipe accepts. Anything else is
#: refused without a guess — there is no generic command dispatch here.
DESKTOP_REQUEST_KINDS = frozenset({MATERIAL_REQUEST_KIND, REDEMPTION_REQUEST_KIND})

#: Exactly the correlation the Desktop redemption port already needs. No raw URL,
#: no raw P01 payload, no credential, no cookie, no grant object, no page content.
REDEMPTION_REQUEST_FIELDS = ("redemptionRef", "requestFingerprint", "openId", "runRef")

MAX_REDEMPTION_RESPONSE_LINE_CHARS = 2_048

#: The dispatcher's own bound. A redemption request carries a contract version,
#: a kind, a 64-char fingerprint and three ids, which does not fit the material
#: request's 256-char bound, so the dispatcher gets its own — still tiny — limit.
#: The material parser keeps its original, narrower bound.
MAX_DESKTOP_REQUEST_LINE_CHARS = 512

MAX_REQUEST_LINE_CHARS = 256
#: 16 KiB of raw credential is 21 848 base64 characters; the envelope around it
#: is small, so 32 KiB is a hard stop, not headroom for growth.
MAX_RESPONSE_LINE_CHARS = 32_768
MAX_CREDENTIAL_BYTES = 16_384
#: Before redemption the resident reads stdin looking for the pairing handoff;
#: unrelated lines are skipped so a premature material request cannot kill the
#: pairing flow. The bound keeps a hostile stdin from spinning the scan.
MAX_PREHANDOFF_SKIP_LINES = 16


def parse_material_request(raw: str) -> dict[str, Any]:
    """Parse and bound-check one material request. Fails closed."""

    line = raw.strip()
    if not line:
        raise ContractError("empty material request")
    if len(line) > MAX_REQUEST_LINE_CHARS:
        raise ContractError("material request exceeds the bound")
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ContractError("material request is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ContractError("material request must be a JSON object")
    if parsed.get("contract_version") != MATERIAL_REQUEST_CONTRACT_VERSION:
        raise ContractError("unsupported material request contract version")
    if parsed.get("request") != MATERIAL_REQUEST_KIND:
        raise ContractError("unknown material request kind")
    extra = set(parsed) - {"contract_version", "request"}
    if extra:
        raise ContractError("material request carries unknown fields")
    return {"contract_version": MATERIAL_REQUEST_CONTRACT_VERSION, "request": MATERIAL_REQUEST_KIND}


def parse_desktop_request(raw: str) -> dict[str, Any]:
    """Parse one request from the closed two-kind set. Fails closed.

    The kind is a literal comparison against ``DESKTOP_REQUEST_KINDS``; there is
    deliberately no version negotiation, no wildcard and no fallthrough, so a new
    caller cannot reach any handler by inventing a kind.
    """

    line = raw.strip()
    if not line:
        raise ContractError("empty desktop request")
    if len(line) > MAX_DESKTOP_REQUEST_LINE_CHARS:
        raise ContractError("desktop request exceeds the bound")
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ContractError("desktop request is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ContractError("desktop request must be a JSON object")
    kind = parsed.get("request")
    if kind not in DESKTOP_REQUEST_KINDS:
        raise ContractError("unknown desktop request kind")
    if kind == MATERIAL_REQUEST_KIND:
        # The material kind keeps its own, narrower bound and closed shape.
        parse_material_request(line)
        return {"kind": MATERIAL_REQUEST_KIND, "payload": {}}
    if parsed.get("contract_version") != REDEMPTION_REQUEST_CONTRACT_VERSION:
        raise ContractError("unsupported redemption request contract version")
    extra = set(parsed) - {"contract_version", "request", *REDEMPTION_REQUEST_FIELDS}
    if extra:
        raise ContractError("redemption request carries unknown fields")
    payload: dict[str, str] = {}
    for field in REDEMPTION_REQUEST_FIELDS:
        value = parsed.get(field)
        if not isinstance(value, str) or not value or len(value) > 512:
            raise ContractError("redemption request correlation is not a bounded string")
        payload[field] = value
    return {"kind": REDEMPTION_REQUEST_KIND, "payload": payload}


def redemption_response_line(**fields: Any) -> str:
    """The bounded redemption answer. Correlation only — never content."""

    line = json.dumps(
        {
            "event": REDEMPTION_RESPONSE_EVENT,
            "contract_version": REDEMPTION_RESPONSE_CONTRACT_VERSION,
            **fields,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(line) > MAX_REDEMPTION_RESPONSE_LINE_CHARS:
        raise ContractError("redemption response exceeds the bound")
    return line


def redemption_ok_line(*, redemption_ref: str, request_fingerprint: str) -> str:
    return redemption_response_line(
        ok=True, redemption_ref=redemption_ref, request_fingerprint=request_fingerprint
    )


def redemption_refusal_line(*, redemption_ref: str, request_fingerprint: str, reason: str) -> str:
    return redemption_response_line(
        ok=False,
        redemption_ref=redemption_ref,
        request_fingerprint=request_fingerprint,
        reason=reason,
    )


def redemption_refusal_reason(exc: Exception) -> str:
    """One bounded, content-free reason code for a refused redemption."""

    code = getattr(exc, "code", None)
    if isinstance(code, str) and code in {
        "command_not_admitted",
        "command_already_started",
        "command_already_settled",
        "command_expired",
        "redemption_not_authorized",
        "redemption_unavailable",
    }:
        return code
    return "redemption_refused"


def refusal_reason(exc: Exception) -> str:
    """One bounded, secret-free reason code for a refused projection."""

    message = str(exc).lower()
    if "expired" in message:
        return "credential_expired"
    if "not stored" in message or "missing" in message:
        return "credential_store_missing"
    if "not online" in message:
        return "resident_not_online"
    if "no current broker session" in message:
        return "session_missing"
    if "not current" in message:
        return "session_not_current"
    if "does not match" in message:
        return "binding_mismatch"
    return "material_refused"


def material_response_line(projection: dict[str, Any]) -> str:
    """The one bounded response line. The credential exists only here."""

    fields = {
        "event": MATERIAL_RESPONSE_EVENT,
        "contract_version": MATERIAL_RESPONSE_CONTRACT_VERSION,
        **projection,
    }
    line = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    if len(line) > MAX_RESPONSE_LINE_CHARS:
        raise ContractError("material response exceeds the bound")
    return line


def material_refusal_line(reason: str) -> str:
    """A refused answer: no credential, no session id, no binding ref."""

    fields = {
        "event": MATERIAL_RESPONSE_EVENT,
        "contract_version": MATERIAL_RESPONSE_CONTRACT_VERSION,
        "ok": False,
        "reason": refusal_reason(ContractError(reason)),
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


class ResidentDesktopMaterialResponder:
    """The single reader of the supervised stdin pipe, with a closed dispatcher.

    The responder starts only after the resident host is built and online, so it
    can never consume the pairing handoff line: the main thread reads the
    handoff before redemption, and this daemon loop reads only what comes after
    it.

    It answers exactly two literal request kinds — ``desktop_device_session_material``
    (#3436 B2d) and ``browser_open_redemption`` (#3611). Every line produces
    exactly one bounded response line, and an unrecognised kind is refused rather
    than guessed at. There is deliberately **one** reader thread: a second thread
    reading the same stdin would race this one and misroute replies.

        READER_THREADS=1
        REQUEST_KINDS=2
        GENERIC_COMMAND_DISPATCH=NO
        UNKNOWN_KIND=FAIL_CLOSED
    """

    def __init__(
        self,
        *,
        material_projection: Callable[[], dict[str, Any]],
        redemption: Callable[..., None] | None = None,
        reader: Any | None = None,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        if not callable(material_projection):
            raise ContractError("material_projection must be callable")
        if redemption is not None and not callable(redemption):
            raise ContractError("redemption must be callable when supplied")
        self._projection = material_projection
        self._redemption = redemption
        self._reader = reader if reader is not None else sys.stdin
        self._emit = emit if emit is not None else self._write_stdout_line
        self._thread: threading.Thread | None = None

    @staticmethod
    def _write_stdout_line(line: str) -> None:
        # Shares the process-wide emit lock so a material line can never
        # interleave with a status line from another thread.
        from .local_agent_resident_process import _EMIT_LOCK

        with _EMIT_LOCK:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def start(self) -> None:
        if self._thread is not None:
            raise ContractError("material responder is already running")
        self._thread = threading.Thread(
            target=self._serve, name="claw-b2d-material-responder", daemon=True
        )
        self._thread.start()

    def _serve(self) -> None:
        while True:
            try:
                raw = self._reader.readline()
            except (OSError, ValueError):
                return
            if not raw:
                return  # EOF: the supervised pipe closed.
            try:
                line = self.respond(raw)
            except Exception:  # pragma: no cover — respond() never raises
                return
            try:
                self._emit(line)
            except (OSError, ValueError):
                return

    def respond(self, raw: str) -> str:
        """One bounded answer for one bounded request. Testable without a thread."""

        try:
            request = parse_desktop_request(raw)
        except ContractError as exc:
            # An unknown kind is refused. The answer keeps only the material
            # event shape so a hostile caller cannot learn which kinds exist,
            # and it never names a correlation it was not given.
            return material_refusal_line(str(exc))
        if request["kind"] == REDEMPTION_REQUEST_KIND:
            return self._respond_redemption(request["payload"])
        try:
            projection = self._projection()
        except ContractError as exc:
            return material_refusal_line(str(exc))
        except Exception:
            return material_refusal_line("material_refused")
        return material_response_line(projection)

    def _respond_redemption(self, payload: dict[str, str]) -> str:
        """Delegate the one atomic durable transition, then answer.

        The refuse path answers with a bounded reason code and correlation only:
        no URL, no approval payload, no credential and no page content can appear
        on this line, because none of them is representable in it.
        """

        redemption_ref = payload["redemptionRef"]
        request_fingerprint = payload["requestFingerprint"]
        if self._redemption is None:
            return redemption_refusal_line(
                redemption_ref=redemption_ref,
                request_fingerprint=request_fingerprint,
                reason="redemption_unavailable",
            )
        try:
            # The wire uses camelCase JSON keys; the Python callable stays
            # snake_case. The mapping is explicit and total — no **kwargs spread,
            # so a future field cannot reach the authority by accident.
            self._redemption(
                redemption_ref=redemption_ref,
                request_fingerprint=request_fingerprint,
                open_id=payload["openId"],
                run_ref=payload["runRef"],
            )
        except Exception as exc:
            return redemption_refusal_line(
                redemption_ref=redemption_ref,
                request_fingerprint=request_fingerprint,
                reason=redemption_refusal_reason(exc),
            )
        return redemption_ok_line(
            redemption_ref=redemption_ref, request_fingerprint=request_fingerprint
        )


def project_session_material(
    *,
    session_id: str,
    binding_ref: str,
    credential: bytes,
    credential_generation: int,
    expires_at: Any,
) -> dict[str, Any]:
    """The closed response payload — exactly the three material values.

    The mission's narrowest contract: sessionId/bindingRef/credentialB64 plus
    the two facts the Desktop needs to drop a stale line (generation, expiry).
    No account_ref, no workspace_ref, no user id, no tenant, no paths — the
    server derives owner/workspace from the broker session itself.
    """

    if not isinstance(credential, bytes) or not credential or len(credential) > MAX_CREDENTIAL_BYTES:
        raise ContractError("device credential must be non-empty bounded bytes")
    iso = expires_at.isoformat().replace("+00:00", "Z")
    if not isinstance(iso, str) or not iso.endswith("Z"):
        raise ContractError("credential expiry must be a timezone-aware timestamp")
    return {
        "ok": True,
        "session_id": str(session_id),
        "binding_ref": str(binding_ref),
        "credential_b64": base64.b64encode(credential).decode("ascii"),
        "credential_generation": int(credential_generation),
        "expires_at": iso,
    }


MATERIAL_REQUEST_KIND_SENTINEL = True
DESKTOP_MATERIAL_CHANNEL_SECOND_AUTHORITY = 0
DESKTOP_MATERIAL_CHANNEL_INBOUND_LISTENER = 0
RAW_CREDENTIAL_LOGGED = 0
RAW_CREDENTIAL_SECOND_PERSISTENCE = 0

# --- #3611 additions -------------------------------------------------------
DESKTOP_BOUNDED_DISPATCHER_SINGLE_READER = True
DESKTOP_REQUEST_KIND_COUNT = len(DESKTOP_REQUEST_KINDS)
GENERIC_COMMAND_DISPATCH = False
UNKNOWN_REQUEST_KIND_FAILS_CLOSED = True
SECOND_STDIN_READER_THREAD = 0
BROWSER_OPEN_REDEMPTION_TRANSPORT_KINDS_ADDED = 1
REDEMPTION_TRANSPORT_CARRIES_RAW_URL = False
REDEMPTION_TRANSPORT_CARRIES_P01_PAYLOAD = False
REDEMPTION_TRANSPORT_CARRIES_CREDENTIAL = False
REDEMPTION_TRANSPORT_CARRIES_PAGE_CONTENT = False
