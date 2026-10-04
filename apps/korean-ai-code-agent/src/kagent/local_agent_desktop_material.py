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
    """Answers exactly one request kind on the existing supervised stdin pipe.

    The responder starts only after the resident host is built and online, so it
    can never consume the pairing handoff line: the main thread reads the
    handoff before redemption, and this daemon loop reads only what comes after
    it. Every line produces exactly one bounded response line; a request this
    module does not define is refused, never guessed at.
    """

    def __init__(
        self,
        *,
        material_projection: Callable[[], dict[str, Any]],
        reader: Any | None = None,
        emit: Callable[[str], None] | None = None,
    ) -> None:
        if not callable(material_projection):
            raise ContractError("material_projection must be callable")
        self._projection = material_projection
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
            parse_material_request(raw)
        except ContractError as exc:
            return material_refusal_line(str(exc))
        try:
            projection = self._projection()
        except ContractError as exc:
            return material_refusal_line(str(exc))
        except Exception:
            return material_refusal_line("material_refused")
        return material_response_line(projection)


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
