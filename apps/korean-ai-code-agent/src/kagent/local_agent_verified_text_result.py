"""#4139 — the Windows device side of the canonical verified TXT result.

The broker half of this contract is LOCAL1's #4705 canonical store
(``local_agent_broker_text_results.BrokerTextResultStore``): exactly one device
route and two closed wire shapes. This module is the *producer/sender* half —
the call the Windows Resident makes to hand a real, already-authorized PC text
read back to the conversation. There is no second TXT upload path.

    ONE_DEVICE_ROUTE=/text-result · SECOND_TXT_UPLOAD_PATH=0
    GENERIC_STDOUT_TRUSTED=0 · TRUNCATION_AS_COMPLETENESS=0
    NEW_CREDENTIAL=0 · NEW_BROKER=0 · NEW_DEVICE_AUTH=0

Wire contract, byte-identical to #4705's ``record()`` schema:

* ``declared`` state — exactly ``contract_version``, ``command_id``, ``run_id``,
  ``request_fingerprint``, ``state="pending"``. It exists so the Claw reader can
  answer "this command *is* a text read, the body is still coming" instead of
  reconstructing a terminal-only message, so it is sent before the body.
* ``content`` state — the same five keys plus ``content_utf8``,
  ``content_sha256`` (lowercase SHA-256 of the *actual* UTF-8 bytes) and
  ``content_bytes`` (that byte count, at most 768).

Both states post to the same authenticated device route with the canonical
device credential, so the broker verifies the binding, the credential
generation and the successful acknowledged execution of this exact command
before any payload is treated as a result. The device asserts only the command
it is reporting, that command's admitted request fingerprint, and the bytes.

The 768-byte bound is the merged consumer's bound
(``claw_local_task_result_projection.verify_broker_file_text``): a file larger
than that is **refused**, never truncated — a truncated body labelled complete
would be a false claim about a customer's file.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .contracts import ContractError
from .local_agent_control_plane_https import (
    ControlPlaneHttpsOperation,
    PinnedHttpsJsonRequestPort,
)
from .local_agent_secure_transport import OutboundTransportConfig

#: The one canonical device route this lane may use. Mirrors
#: ``local_agent_broker_text_results.TEXT_RESULT_DEVICE_ROUTE`` in #4705.
TEXT_RESULT_DEVICE_ROUTE = "/text-result"
#: Mirrors ``local_agent_broker_text_results.TEXT_RESULT_WIRE_VERSION``.
TEXT_RESULT_CONTRACT_VERSION = "claw-local-agent-text-result.v1"
#: Mirrors #4705's ``MAX_TEXT_RESULT_BYTES`` and the merged consumer's bound.
MAX_VERIFIED_TEXT_RESULT_BYTES = 768
#: The only control characters a staged body may carry.
_SAFE_CONTROL_CHARACTERS = "\n\r\t"

STATE_PENDING = "pending"
STATE_CONTENT = "content"

#: Byte-identical to the broker's own ``safe_ref`` pattern, so a reference this
#: sender accepts is never one the canonical route must refuse.
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_NO_CONTENT_KEYS = frozenset(
    {"contract_version", "command_id", "run_id", "request_fingerprint", "state"}
)
_CONTENT_KEYS = _NO_CONTENT_KEYS | frozenset(
    {"content_utf8", "content_sha256", "content_bytes"}
)
#: The broker's own answer for one staged result (#4705 ``record()``).
_STORED_KEYS = frozenset({"stored", "reused", "state", "content_present"})


class VerifiedTextResultRefused(ValueError):
    """Bounded local refusal. Never carries document content or credentials."""


def _ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_REF_RE.fullmatch(value) is None:
        raise VerifiedTextResultRefused(f"{field_name} must be a bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise VerifiedTextResultRefused(f"{field_name} must be lowercase SHA-256")
    return value


def bounded_utf8_text(content: Any) -> str:
    """Validate one real text read against the canonical transport bound.

    Strict UTF-8, at most ``MAX_VERIFIED_TEXT_RESULT_BYTES`` bytes once encoded,
    and no control characters besides newline, carriage return and tab. An
    oversized read is refused: nothing here truncates.
    """
    if not isinstance(content, str):
        raise VerifiedTextResultRefused("verified file text must be text")
    try:
        raw = content.encode("utf-8")
    except UnicodeEncodeError:
        raise VerifiedTextResultRefused("verified file text is not UTF-8 encodable") from None
    if len(raw) > MAX_VERIFIED_TEXT_RESULT_BYTES:
        raise VerifiedTextResultRefused("verified file text exceeds the bounded size")
    if any(ord(character) < 32 and character not in _SAFE_CONTROL_CHARACTERS for character in content):
        raise VerifiedTextResultRefused("verified file text carries a control character")
    return content


def decode_bounded_utf8_content(
    content: Any, max_bytes: int = MAX_VERIFIED_TEXT_RESULT_BYTES,
) -> str:
    """Decode the *actual bytes* read from the authorized file, or refuse.

    The bytes are the authority: a file that is not UTF-8, or that is larger
    than the bound, is refused rather than repaired, transcoded or truncated.
    #4139: the bound is a parameter so the Mesh read lane can use the shared
    6 MB wire envelope while the Windows Resident lane keeps its own.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise VerifiedTextResultRefused("verified file read must return bytes")
    raw = bytes(content)
    if len(raw) > max_bytes:
        raise VerifiedTextResultRefused("verified file text exceeds the bounded size")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise VerifiedTextResultRefused("verified file text is not UTF-8") from None
    return bounded_utf8_text(text)


@dataclass(frozen=True, slots=True)
class VerifiedTextResult:
    """One bounded text read, correlated to the command that produced it."""

    command_id: str
    run_id: str
    request_fingerprint: str
    content_utf8: str
    content_sha256: str
    content_bytes: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", _ref(self.command_id, "command_id"))
        object.__setattr__(self, "run_id", _ref(self.run_id, "run_id"))
        object.__setattr__(
            self, "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )
        object.__setattr__(self, "content_utf8", bounded_utf8_text(self.content_utf8))
        raw = self.content_utf8.encode("utf-8")
        if self.content_bytes != len(raw):
            raise VerifiedTextResultRefused("verified file text byte count mismatch")
        if self.content_sha256 != hashlib.sha256(raw).hexdigest():
            raise VerifiedTextResultRefused("verified file text digest mismatch")

    def pending_payload(self) -> dict[str, Any]:
        """The declaration the reader needs *before* the body arrives."""
        return {
            "contract_version": TEXT_RESULT_CONTRACT_VERSION,
            "command_id": self.command_id,
            "run_id": self.run_id,
            "request_fingerprint": self.request_fingerprint,
            "state": STATE_PENDING,
        }

    def content_payload(self) -> dict[str, Any]:
        """The body, with the digest and byte count of the actual bytes."""
        return {
            **self.pending_payload(),
            "state": STATE_CONTENT,
            "content_utf8": self.content_utf8,
            "content_sha256": self.content_sha256,
            "content_bytes": self.content_bytes,
        }

    def safe_dict(self) -> dict[str, Any]:
        """Operational projection. Never the document body."""
        return {
            "contract_version": TEXT_RESULT_CONTRACT_VERSION,
            "route": TEXT_RESULT_DEVICE_ROUTE,
            "command_id": self.command_id,
            "run_id": self.run_id,
            "request_fingerprint": self.request_fingerprint,
            "content_bytes": self.content_bytes,
            "content_sha256": self.content_sha256,
            "content_present": True,
            "generic_stdout_trusted": False,
            "truncated_as_complete": False,
        }


def build_verified_text_result(
    *,
    command_id: str,
    run_id: str,
    request_fingerprint: str,
    content: Any,
    max_bytes: int = MAX_VERIFIED_TEXT_RESULT_BYTES,
) -> VerifiedTextResult:
    """Build the correlated result from the *bytes actually read*."""
    text = decode_bounded_utf8_content(content, max_bytes)
    raw = text.encode("utf-8")
    return VerifiedTextResult(
        command_id=command_id,
        run_id=run_id,
        request_fingerprint=request_fingerprint,
        content_utf8=text,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        content_bytes=len(raw),
    )


class LocalAgentTextResultPublisher:
    """The one sender: existing pinned-TLS device transport, one route.

    A retry re-sends the *same* payload — the same correlation and the same
    bytes — through :meth:`deliver`/:meth:`replay`. Nothing here re-executes a
    task, re-reads a file, mints a command or invents a second route, and a
    refused or unanswered upload is never reported as content that reached Claw.
    """

    def __init__(
        self,
        *,
        transport: PinnedHttpsJsonRequestPort,
        config: OutboundTransportConfig,
    ) -> None:
        if not callable(getattr(transport, "post", None)):
            raise ContractError("trusted pinned HTTPS transport required")
        if not isinstance(config, OutboundTransportConfig):
            raise ContractError("canonical outbound transport config required")
        self._transport = transport
        self._config = config

    def _post(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        payload: dict[str, Any],
        expected_state: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        binding_ref = _ref(binding_ref, "binding_ref")
        if not isinstance(credential, bytes) or not credential:
            raise ContractError("canonical device credential required")
        if payload.get("state") != expected_state:
            raise VerifiedTextResultRefused("text result wire state mismatch")
        wire = {
            "binding_ref": binding_ref,
            "credential_b64": base64.b64encode(credential).decode("ascii"),
            **payload,
        }
        if frozenset(wire) - {"binding_ref", "credential_b64"} != (
            _CONTENT_KEYS if expected_state == STATE_CONTENT else _NO_CONTENT_KEYS
        ):
            raise VerifiedTextResultRefused("text result wire schema mismatch")
        response = self._transport.post(
            config=self._config,
            operation=ControlPlaneHttpsOperation.TEXT_RESULT,
            payload=wire,
            timeout_seconds=timeout_seconds,
        )
        if type(response) is not dict or response.get("ok") is not True:
            raise VerifiedTextResultRefused("broker refused the authenticated text result")
        stored = response.get("text_result")
        if type(stored) is not dict or frozenset(stored) != _STORED_KEYS:
            raise VerifiedTextResultRefused("broker text result receipt schema mismatch")
        if stored["stored"] is not True or stored["state"] != expected_state:
            raise VerifiedTextResultRefused("broker did not store the reported text state")
        if expected_state == STATE_CONTENT and stored["content_present"] is not True:
            raise VerifiedTextResultRefused("broker stored no text body")
        return stored

    def declare_pending(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        run_id: str,
        request_fingerprint: str,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        """Declare the read before its body, so the conversation waits."""
        result = VerifiedTextResult(
            command_id=command_id,
            run_id=run_id,
            request_fingerprint=request_fingerprint,
            content_utf8="",
            content_sha256=hashlib.sha256(b"").hexdigest(),
            content_bytes=0,
        )
        return self._post(
            binding_ref=binding_ref,
            credential=credential,
            payload=result.pending_payload(),
            expected_state=STATE_PENDING,
            timeout_seconds=timeout_seconds,
        )

    def deliver(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        result: VerifiedTextResult,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        """Upload the real body. Success means the broker stored it."""
        if not isinstance(result, VerifiedTextResult):
            raise VerifiedTextResultRefused("canonical verified text result required")
        return self._post(
            binding_ref=binding_ref,
            credential=credential,
            payload=result.content_payload(),
            expected_state=STATE_CONTENT,
            timeout_seconds=timeout_seconds,
        )

    def replay(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        result: VerifiedTextResult,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        """Retry the identical upload after a transport failure.

        Same correlation, same bytes, no re-read and no new command; the
        canonical broker treats an exact replay as inert rather than as a second
        result.
        """
        return self.deliver(
            binding_ref=binding_ref,
            credential=credential,
            result=result,
            timeout_seconds=timeout_seconds,
        )


__all__ = [
    "MAX_VERIFIED_TEXT_RESULT_BYTES",
    "STATE_CONTENT",
    "STATE_PENDING",
    "TEXT_RESULT_CONTRACT_VERSION",
    "TEXT_RESULT_DEVICE_ROUTE",
    "LocalAgentTextResultPublisher",
    "VerifiedTextResult",
    "VerifiedTextResultRefused",
    "bounded_utf8_text",
    "build_verified_text_result",
    "decode_bounded_utf8_content",
]

SECOND_TXT_UPLOAD_PATH = False
GENERIC_STDOUT_TRUSTED = False
TRUNCATION_AS_COMPLETENESS = False
NEW_BROKER = False
NEW_DEVICE_AUTH = False
NEW_CREDENTIAL = False
