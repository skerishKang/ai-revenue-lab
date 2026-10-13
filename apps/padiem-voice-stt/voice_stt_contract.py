"""Shared speech-to-text (STT) contract for PADIEM Chat, Claw and B66.

Source of truth
---------------
This module is the PADIEM-side port of the proven Global Classroom STT
implementation (``skerishKang/global-classroom``):

- ``hooks/useInterviewLive.ts``      -> provider order, fallback lifecycle, turn model
- ``utils/liveTranscriptTurn.ts``    -> chunk merge, turn buffer, handoff buffer,
                                        tail flush, Groq chunk cut, stall flush,
                                        recognition-language resolution
- ``netlify/functions/transcribe.mts`` -> server-side Groq Whisper transport
- ``skerishKang/global-classroom#87`` -> long-utterance truncation regression

What is reused is the **contract** (transcript event model, utterance identity,
dedup rules, provider fallback order and the server-side transport shape). The
React hook, the Netlify runtime and any product UI are deliberately **not**
copied: PADIEM Chat/Claw run a plain browser shell on Cloudflare Workers and B66
runs Cloudflare Pages, so only the runtime-agnostic rules travel.

This module has **zero third-party dependencies** and never imports the
Cloudflare ``workers`` runtime, so it is importable and unit-testable on plain
CPython. ``worker.py`` is the thin Workers adapter over it.

Security invariants
-------------------
- No API key value is ever read, stored, logged, returned or embedded here.
  Only the *binding name* constants below describe where a server-side secret
  is expected to live; the value stays inside the Cloudflare Secrets Store.
- A long-lived provider key never leaves the server. The browser receives, at
  most, a short-lived Gemini Live ephemeral token.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Iterable, Sequence

# ---------------------------------------------------------------------------
# Provider order and fallback contract
# ---------------------------------------------------------------------------

CONTRACT_VERSION = "padiem.voice.stt.v1"


class SttProvider(str, Enum):
    """The three STT backends, in the order they are tried."""

    GEMINI_LIVE = "gemini_live"
    BROWSER_SPEECH = "browser_speech"
    GROQ_WHISPER = "groq_whisper"


#: Default/fallback order, preserved from Global Classroom (#87):
#: Gemini Live Transcribe -> browser SpeechRecognition -> Groq Whisper.
#: Translation/answer models are a different authority and never substitute here.
STT_PROVIDER_ORDER: tuple[SttProvider, ...] = (
    SttProvider.GEMINI_LIVE,
    SttProvider.BROWSER_SPEECH,
    SttProvider.GROQ_WHISPER,
)


def next_provider(current: SttProvider | None) -> SttProvider | None:
    """Return the next provider in the fallback chain, or ``None`` at the end.

    The chain is **one-way within a single microphone run**: Global Classroom
    never auto-returns from Browser/Groq back to Gemini once it has fallen back
    (#87), because a flapping provider would re-segment an utterance mid-flight.
    A fresh run (``current=None``) starts at the top of the chain again.
    """
    if current is None:
        return STT_PROVIDER_ORDER[0]
    try:
        index = STT_PROVIDER_ORDER.index(current)
    except ValueError:
        return STT_PROVIDER_ORDER[0]
    if index + 1 >= len(STT_PROVIDER_ORDER):
        return None
    return STT_PROVIDER_ORDER[index + 1]


def provider_is_server_side(provider: SttProvider) -> bool:
    """True when the provider requires a server-side secret (never the browser)."""
    return provider in (SttProvider.GEMINI_LIVE, SttProvider.GROQ_WHISPER)


def normalize_http_method(value: object) -> str:
    """Normalise a request method to an upper-case string.

    The ``workers`` runtime exposes ``http.HTTPMethod``; ``.name`` is explicit
    and stable, whereas ``str()`` semantics for enum members differ across
    Python versions (IntEnum silently renders the integer).
    """
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()
    return str(value).upper()


def route_path(url: object) -> str:
    """Return the path component of an absolute request URL.

    ``str(request.url)`` is an absolute URL, so ``urlsplit`` rather than treating
    the whole string as a path. Returns ``""`` for anything unparseable, which
    routes to the bounded ``not_found`` mismatch branch.
    """
    if not isinstance(url, str):
        url = str(url)
    try:
        from urllib.parse import urlsplit

        return urlsplit(url).path
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Secret binding names (names only — never values)
# ---------------------------------------------------------------------------

#: The Cloudflare Secrets Store resource id is intentionally NOT stored here.
#: It is a non-secret resource locator, and ``wrangler.toml`` is the only source
#: of it in this repository. Duplicating it in Python only creates a second copy
#: that secret scanners flag for entropy without adding any behaviour.

#: Existing binding name, already declared in
#: ``apps/korean-ai-platform/wrangler.toml``. Declaring a binding in repository
#: config is NOT runtime verification — it only proves the reference exists in
#: the manifest.
GEMINI_API_KEY_BINDING = "PADIEM_GEMINI_API_KEY"

#: Owner-reported only. A repository manifest entry for Groq is absent from every
#: PADIEM ``wrangler.toml``, so this exact secret_name is *inferred* from the
#: ``PADIEM_<PROVIDER>_API_KEY`` convention. It is not proven to exist, no live
#: binding is attached, and no provider availability is implied. It must be
#: confirmed against the live store before the transcribe route can succeed. No
#: key is created, requested or read here.
GROQ_API_KEY_BINDING = "PADIEM_GROQ_API_KEY"
GROQ_API_KEY_BINDING_VERIFIED = False

#: Deployment gate names for this shared service. Both are read from trusted
#: Worker bindings only, never from request input.
VOICE_STT_ENABLED_BINDING = "PADIEM_VOICE_STT_ENABLED"
#: Service Binding that must supply an authenticated caller identity and a cost
#: authorization. It does not exist yet and must not be switched on to pass tests.
#:
#: Attaching *any* object under this name proves nothing on its own: there is no
#: production service-binding authorization contract implemented against which a
#: verdict could be verified, so a binding — approving, denying or empty — is
#: never treated as authorization. Paid routes stay unreachable until the real
#: caller authority is implemented in its own integration slice.
VOICE_STT_CALLER_GUARD_BINDING = "VOICE_STT_CALLER_GUARD"
VOICE_STT_SERVICE_BINDING = "VOICE_STT_SERVICE"


@dataclass(frozen=True)
class CallerAuthorization:
    """The only value that may unlock a paid route — never produced today.

    This records what a *real* caller authority must hand to the Worker before a
    paid provider request: an authenticated server-owned actor, the tenant it
    acts for, the exact route it was admitted for, and a per-request cost
    reservation identity with a positive authorized amount.

    It is constructed **nowhere in the Worker**. The route gate
    (``worker._require_caller_authorization``) always raises, so no request — and
    no attached binding — can obtain one. The test suite builds instances
    explicitly to exercise the paid pipeline in isolation, and those instances
    never originate from ``env`` or from request input.
    """

    actor: str
    tenant: str
    route: str
    reservation_id: str
    amount_usd: float

    def admits(self, route: str) -> bool:
        """True only for the exact route this authorization was admitted for."""
        return (
            isinstance(self.actor, str)
            and bool(self.actor.strip())
            and isinstance(self.tenant, str)
            and bool(self.tenant.strip())
            and isinstance(self.reservation_id, str)
            and bool(self.reservation_id.strip())
            and isinstance(self.amount_usd, (int, float))
            and not isinstance(self.amount_usd, bool)
            and self.amount_usd > 0
            and self.route == route
        )


# ---------------------------------------------------------------------------
# Safe error codes (bounded; never carry a secret, a key or a provider trace)
# ---------------------------------------------------------------------------


class VoiceSttError(Exception):
    """A bounded, client-safe STT failure. ``code`` is one of ``VOICE_STT_CODES``."""

    def __init__(self, code: str, status: int = 400):
        if code not in VOICE_STT_CODES:
            raise ValueError(f"unregistered voice STT code: {code}")
        self.code = code
        self.status = status
        super().__init__(code)


VOICE_STT_CODES: frozenset[str] = frozenset(
    {
        "not_found",
        "method_not_allowed",
        "unsupported_media_type",
        "request_too_large",
        "invalid_content_length",
        "invalid_json",
        "unsupported_field",
        "invalid_language",
        "invalid_audio",
        "empty_audio",
        "audio_too_large",
        "stt_key_missing",
        "stt_unavailable",
        "stt_failed",
        "live_token_unavailable",
        # Deployment gates: fail closed before any Secret read or provider call.
        "voice_stt_disabled",
        "caller_guard_unavailable",
        # No verified caller-identity / cost-reservation authority exists, so a
        # paid route is unreachable regardless of what the guard binding says.
        "caller_authorization_unimplemented",
    }
)

STATUS_BY_CODE: dict[str, int] = {
    "not_found": 404,
    "method_not_allowed": 405,
    "unsupported_media_type": 415,
    "request_too_large": 413,
    "invalid_content_length": 400,
    "invalid_json": 400,
    "unsupported_field": 400,
    "invalid_language": 400,
    "invalid_audio": 400,
    "empty_audio": 400,
    "audio_too_large": 413,
    "stt_key_missing": 503,
    "stt_unavailable": 503,
    "stt_failed": 502,
    "live_token_unavailable": 503,
    "voice_stt_disabled": 503,
    "caller_guard_unavailable": 503,
    "caller_authorization_unimplemented": 503,
}


def status_for_code(code: str) -> int:
    """Bounded HTTP status for a registered code, or 400 when unregistered."""
    if code not in VOICE_STT_CODES:
        raise ValueError(f"unregistered voice STT code: {code}")
    return STATUS_BY_CODE[code]


# ---------------------------------------------------------------------------
# Transcript event model (interim preview vs authoritative final)
# ---------------------------------------------------------------------------


class TranscriptKind(str, Enum):
    INTERIM = "interim"
    FINAL = "final"


@dataclass(frozen=True)
class TranscriptEvent:
    """One transcript observation.

    Only ``kind == FINAL`` may become authoritative user input. An ``INTERIM``
    preview is display-only and must never be submitted, appended to a message
    input as final text, or fed to an answer/quotation lane (#4643, #3404).
    """

    utterance_id: str
    kind: TranscriptKind
    text: str
    provider: SttProvider
    language: str | None = None
    sequence: int = 0

    @property
    def is_authoritative(self) -> bool:
        return self.kind is TranscriptKind.FINAL and bool(self.text.strip())


# ---------------------------------------------------------------------------
# Utterance identity
# ---------------------------------------------------------------------------

_MAX_SESSION_ID = 96
_SAFE_ID_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.:")


def make_utterance_id(session_id: str, generation: int, turn_index: int) -> str:
    """Deterministic utterance identity: ``session:generation:turn``.

    Global Classroom keyed a row as ``${seq}-${Date.now()}-${prev.length}``
    (#87). A clock inside the identity makes the same utterance look new after a
    provider fallback or a session rotation, which is exactly how duplicate final
    rows appear. A deterministic id lets the fallback re-emit an utterance under
    the *same* identity, so the deduper can drop the duplicate instead of the
    user seeing the sentence twice.
    """
    if not isinstance(session_id, str) or not session_id or len(session_id) > _MAX_SESSION_ID:
        raise ValueError("invalid session id")
    if any(ch not in _SAFE_ID_CHARS for ch in session_id):
        raise ValueError("invalid session id")
    if generation < 0 or turn_index < 0:
        raise ValueError("generation and turn_index must be non-negative")
    return f"{session_id}:{generation}:{turn_index}"


# ---------------------------------------------------------------------------
# Chunk merge + turn buffer (ported from liveTranscriptTurn.ts)
# ---------------------------------------------------------------------------


def merge_transcript_chunk(previous: str, incoming: str) -> str:
    """Merge a chunk that may be a delta or a cumulative hypothesis.

    Some Live backends emit cumulative hypotheses, others emit deltas. Accept
    both without duplicating an already-seen prefix/suffix.
    """
    if not incoming:
        return previous
    if not previous:
        return incoming
    if incoming.startswith(previous):
        return incoming
    if previous.endswith(incoming):
        return previous
    return previous + incoming


@dataclass
class TranscriptTurnBuffer:
    """One Live turn is one row (#87).

    Chunks merge into the open turn and commit only at the turn boundary, so an
    ordinary thinking pause cannot split one sentence into several final rows.
    """

    _pending: str = ""

    @property
    def pending(self) -> str:
        return self._pending

    def merge(self, chunk: str | None) -> str:
        if not chunk:
            return self._pending
        self._pending = merge_transcript_chunk(self._pending, str(chunk))
        return self._pending

    def finish_turn(self) -> str | None:
        """Commit the open turn. Idempotent: a second call returns ``None``."""
        text = self._pending.strip()
        self._pending = ""
        return text or None

    def reset(self) -> None:
        self._pending = ""


# ---------------------------------------------------------------------------
# Final-row dedup across fallback / reconnect
# ---------------------------------------------------------------------------


@dataclass
class TranscriptDeduper:
    """Drop duplicate authoritative finals produced by fallback or reconnect.

    Global Classroom's failure mode was not only truncation: when a provider
    failed mid-utterance the same speech could be finalized by the browser
    fallback and then re-finalized by Groq Whisper, surfacing the sentence twice.
    Because an utterance keeps one deterministic identity across provider
    switches (see :func:`make_utterance_id`), committing by identity is enough.

    Two distinct utterances that happen to share the same text (e.g. "네", "네")
    keep distinct ids and are both kept.
    """

    _committed: set[str] = field(default_factory=set)

    def accept(self, event: TranscriptEvent) -> bool:
        """True when the event should be surfaced; False when it is a duplicate."""
        if event.kind is TranscriptKind.INTERIM:
            return True
        if event.utterance_id in self._committed:
            return False
        self._committed.add(event.utterance_id)
        return True

    def forget(self, utterance_id: str) -> None:
        self._committed.discard(utterance_id)

    def reset(self) -> None:
        self._committed.clear()


@dataclass
class UtteranceSubmissionGuard:
    """Ensure one authoritative utterance is submitted **at most once**.

    The deduper stops a duplicate *row*; this guard stops a duplicate *send*.
    Stage 1 (review-to-send) and stage 2 (live turns) both submit a final
    utterance, and a replayed final, a double click on Send, or a fallback that
    re-finalises after the user already sent must not submit twice.

    ``claim`` is the only way to submit. If the submission is rejected by the
    product lane, ``release`` lets the same utterance be retried deliberately.
    """

    _submitted: set[str] = field(default_factory=set)

    def claim(self, utterance_id: str) -> bool:
        """Reserve the single submission slot for this utterance."""
        if utterance_id in self._submitted:
            return False
        self._submitted.add(utterance_id)
        return True

    def release(self, utterance_id: str) -> None:
        """Return the slot (only after an explicit, user-visible retry)."""
        self._submitted.discard(utterance_id)

    def submitted(self, utterance_id: str) -> bool:
        return utterance_id in self._submitted

    def reset(self) -> None:
        self._submitted.clear()


# ---------------------------------------------------------------------------
# Audio handoff buffer across a Live session rotation (#87)
# ---------------------------------------------------------------------------


@dataclass
class AudioHandoffBuffer:
    """Bounded buffer that keeps a long utterance intact across a rotation.

    Rotating a Live session means awaiting a fresh ephemeral token and a new
    WebSocket. The outgoing session is invalidated before that await, so frames
    handed to it during the gap are transcribed and thrown away. Buffering the
    gap and replaying it into the new session keeps a sentence that straddles the
    boundary intact. Overflow is counted and never silent.
    """

    max_frames: int
    _frames: list[object] = field(default_factory=list)
    _capturing: bool = False
    _dropped: int = 0

    @property
    def capturing(self) -> bool:
        return self._capturing

    @property
    def size(self) -> int:
        return len(self._frames)

    @property
    def dropped_frames(self) -> int:
        return self._dropped

    def start(self) -> None:
        self._capturing = True

    def push(self, frame: object) -> bool:
        """Capture one frame. False means the cap was hit and it was dropped."""
        if not self._capturing:
            return False
        if len(self._frames) >= self.max_frames:
            self._dropped += 1
            return False
        self._frames.append(frame)
        return True

    def release(self) -> list[object]:
        pending = self._frames
        self._frames = []
        self._capturing = False
        return pending

    def reset(self) -> None:
        self._frames = []
        self._capturing = False


#: One microphone frame is 2048 samples (128ms at the 16kHz the Live API
#: expects), so 40 frames cover ~5.1s of connect latency while staying bounded.
LIVE_AUDIO_HANDOFF_FRAMES = 40


# ---------------------------------------------------------------------------
# Tail flush: finalise audio a retired Live session still holds (#87)
# ---------------------------------------------------------------------------

#: Drain window bounded against a measured 261ms provider tail observation.
LIVE_TAIL_FLUSH_DRAIN_MS = 1_200


@dataclass
class LiveTailFlush:
    """One-shot drain of a retired Live session's cached tail.

    Gemini's activity detection closes a turn only after it has *received*
    enough silence. A stream that simply stops never delivers that silence, so
    the tail of the sentence stays cached inside the session and dies with the
    socket. Measured on one 28.7s utterance: stopping the stream transcribed
    51/64 ground-truth words and lost the final clause, while the same audio plus
    ``audioStreamEnd`` transcribed 62/64. This flush issues that signal.
    """

    on_settled: Callable[[str | None], None]
    send_audio_stream_end: Callable[[], None]
    deadline_ms: int = LIVE_TAIL_FLUSH_DRAIN_MS
    set_timer: Callable[[Callable[[], None], int], object] = None  # type: ignore[assignment]
    clear_timer: Callable[[object], None] = None  # type: ignore[assignment]
    _settled: bool = False
    _tail: str = ""
    _timer: object | None = None

    def __post_init__(self) -> None:
        # No threading default: this module must import inside the Cloudflare
        # Workers (Pyodide) runtime, which has no ``threading``. A real client
        # injects its own timer; the no-op default simply means "no deadline",
        # so only an explicit boundary settles the flush.
        if self.set_timer is None:
            self.set_timer = lambda _cb, _ms: None  # type: ignore[assignment]
        if self.clear_timer is None:
            self.clear_timer = lambda _t: None  # type: ignore[assignment]
        self._timer = self.set_timer(self._settle, self.deadline_ms)
        try:
            self.send_audio_stream_end()
        except Exception:
            self._settle()

    @property
    def armed(self) -> bool:
        return not self._settled

    def accept(self, text: str | None, finished: bool = False) -> bool:
        """Feed one observation from the draining session.

        A backend may deliver the tail as several deltas *or* as cumulative
        hypotheses, so chunks merge and only a turn boundary settles. A bare
        boundary with no captured text must not close an empty tail.
        """
        if self._settled:
            return False
        chunk = text if isinstance(text, str) else ""
        if not chunk.strip():
            if not finished or not self._tail:
                return False
            self._settle()
            return True
        self._tail = merge_transcript_chunk(self._tail, chunk)
        if finished:
            self._settle()
        return True

    def cancel(self) -> None:
        """Stop waiting, but still report anything already captured."""
        self._settle()

    def _settle(self) -> None:
        if self._settled:
            return
        self._settled = True
        if self._timer is not None:
            self.clear_timer(self._timer)  # type: ignore[arg-type]
            self._timer = None
        tail = self._tail.strip()
        self.on_settled(tail or None)


# ---------------------------------------------------------------------------
# Groq Whisper fallback chunk boundary (#87)
# ---------------------------------------------------------------------------

#: The old fixed 5500ms stop clipped speech mid-sentence. Cut at a real pause
#: once a minimum window is captured, with a hard maximum that bounds payload.
GROQ_MIN_CHUNK_MS = 4_000
GROQ_SILENCE_CUT_MS = 700
GROQ_MAX_CHUNK_MS = 20_000


def should_cut_groq_chunk(elapsed_ms: int, silence_ms: int) -> bool:
    """True when a Groq fallback chunk should be closed and transcribed."""
    if elapsed_ms >= GROQ_MAX_CHUNK_MS:
        return True
    if elapsed_ms < GROQ_MIN_CHUNK_MS:
        return False
    return silence_ms >= GROQ_SILENCE_CUT_MS


# ---------------------------------------------------------------------------
# Stalled-turn safety net
# ---------------------------------------------------------------------------

#: If the Live turn boundary never arrives, a turn whose last chunk is older
#: than this window and still has pending text is committed as-is.
TRANSCRIPT_TURN_STALL_MS = 2_500


def should_flush_stalled_turn(has_pending: bool, since_last_chunk_ms: int) -> bool:
    return has_pending and since_last_chunk_ms >= TRANSCRIPT_TURN_STALL_MS


# ---------------------------------------------------------------------------
# Browser SpeechRecognition language resolution (#87)
# ---------------------------------------------------------------------------


def resolve_recognition_language(
    hint: str | None = None,
    observed: str | None = None,
    navigator_language: str | None = None,
) -> str:
    """Browser SpeechRecognition has no language identity of its own.

    Prefer the explicit source hint, then the language the Live transcriber or
    detector actually observed, and only then the browser locale. Blindly using
    ``navigator.language`` constrained a ko-KR browser listening to English (#87).

    ``auto`` is skipped rather than treated as a value: an explicit "auto" hint
    must fall through to the observed language instead of masking it.
    """
    for candidate in (hint, observed):
        if candidate and candidate != "auto":
            return candidate
    return navigator_language or "ko-KR"


# ---------------------------------------------------------------------------
# Server-side Groq Whisper transport (ported from netlify/functions/transcribe.mts)
# ---------------------------------------------------------------------------

GROQ_STT_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
#: Ordered like Global Classroom: turbo first, then the full model.
GROQ_STT_MODELS: tuple[str, ...] = ("whisper-large-v3-turbo", "whisper-large-v3")
GROQ_STT_ALLOWED_HOST = "api.groq.com"

#: Decoded-audio ceiling, matching Global Classroom's 3 MiB guard.
MAX_AUDIO_BYTES = 3 * 1024 * 1024
#: Base64 inflates by ~4/3, so the JSON envelope gets a little headroom.
MAX_REQUEST_BYTES = 5 * 1024 * 1024

#: Upstream budget in milliseconds. A stalled provider must not pin a Worker
#: request forever, and a browser must not wait on a socket that never answers.
GROQ_REQUEST_TIMEOUT_MS = 25_000
LIVE_TOKEN_REQUEST_TIMEOUT_MS = 8_000

#: Ceiling for an upstream *response body*. Both upstreams answer with a tiny
#: JSON document (a transcript, or one ephemeral-token object), so anything
#: approaching this size is a malfunctioning or hostile provider, not data.
#: The ceiling applies to the body read that runs *inside* the request budget.
MAX_UPSTREAM_RESPONSE_BYTES = 256 * 1024


def parse_declared_content_length(raw: object) -> int | None:
    """Validate a declared ``Content-Length`` header.

    Returns the byte count, or ``None`` when the header is absent (chunked
    transfer). A negative, non-integer or otherwise malformed declared length is
    an error, not a value to fall back on — a negative length reads as "no limit"
    to a naive check.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise VoiceSttError("invalid_content_length", 400)
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise VoiceSttError("invalid_content_length", 400)
    if value < 0:
        raise VoiceSttError("invalid_content_length", 400)
    return value


async def read_bounded_body(
    read_chunk: Callable[[int], object],
    max_bytes: int,
) -> bytes:
    """Accumulate a body incrementally, never holding more than ``max_bytes``.

    ``read_chunk(limit)`` must return up to ``limit`` bytes, or ``None`` for end
    of body. The caller always asks for one byte more than the remaining budget,
    so an oversized body is rejected the moment it proves to be oversized
    instead of after it has been fully materialised in memory. Without a declared
    ``Content-Length`` (chunked request) this is the only bound available.
    """
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = read_chunk(max_bytes - total + 1)
        if hasattr(chunk, "__await__"):
            chunk = await chunk
        if chunk is None or chunk == b"" or chunk == "":
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        elif isinstance(chunk, (bytearray, memoryview)):
            chunk = bytes(chunk)
        if not isinstance(chunk, bytes):
            raise VoiceSttError("invalid_json", 400)
        total += len(chunk)
        if total > max_bytes:
            raise VoiceSttError("request_too_large", 413)
        parts.append(chunk)
    return b"".join(parts)

SUPPORTED_LANGUAGES: tuple[str, ...] = ("ko", "en", "auto")
DEFAULT_LANGUAGE = "auto"

_AUDIO_MIME_EXTENSION: tuple[tuple[str, str], ...] = (
    ("webm", "webm"),
    ("mp4", "m4a"),
    ("m4a", "m4a"),
    ("wav", "wav"),
    ("mpeg", "mp3"),
    ("mp3", "mp3"),
    ("ogg", "ogg"),
)


@dataclass(frozen=True)
class AudioPayload:
    mime_type: str
    extension: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)


def _extension_for(mime_type: str) -> str:
    for needle, extension in _AUDIO_MIME_EXTENSION:
        if needle in mime_type:
            return extension
    return "webm"


def parse_audio_data_url(data_url: object) -> AudioPayload | None:
    """Decode a ``data:audio/...;base64,...`` URL, or ``None`` when unsupported."""
    if not isinstance(data_url, str):
        return None
    prefix = "data:"
    if not data_url.startswith(prefix):
        return None
    header, sep, payload = data_url[len(prefix):].partition(",")
    if not sep or ";base64" not in header:
        return None
    media_type = header.split(";", 1)[0].strip().lower()
    if not media_type.startswith("audio/"):
        return None
    import base64

    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        return None
    if not raw:
        return None
    return AudioPayload(mime_type=media_type, extension=_extension_for(media_type), data=raw)


def normalize_language(value: object) -> str | None:
    """Return a supported language tag, or ``None`` when it is not one."""
    if value is None or value == "":
        return DEFAULT_LANGUAGE
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate if candidate in SUPPORTED_LANGUAGES else None


#: Fields the browser may send to the transcription endpoint. Anything else is
#: rejected so a client cannot smuggle a provider URL, model or key through.
TRANSCRIBE_REQUEST_FIELDS: frozenset[str] = frozenset(
    {"audioDataUrl", "language", "sessionId", "utteranceId"}
)


def validate_transcribe_request(payload: object) -> tuple[str, AudioPayload]:
    """Validate a transcription request body, or raise :class:`VoiceSttError`.

    Returns ``(language, audio)``. The caller never learns a provider URL, model
    or credential from this path; those stay server-side constants.
    """
    if not isinstance(payload, dict):
        raise VoiceSttError("invalid_json", 400)
    if set(payload) - TRANSCRIBE_REQUEST_FIELDS:
        raise VoiceSttError("unsupported_field", 400)
    language = normalize_language(payload.get("language"))
    if language is None:
        raise VoiceSttError("invalid_language", 400)
    audio = parse_audio_data_url(payload.get("audioDataUrl"))
    if audio is None:
        raise VoiceSttError("invalid_audio", 400)
    if audio.size > MAX_AUDIO_BYTES:
        raise VoiceSttError("audio_too_large", 413)
    return language, audio


def build_groq_multipart_body(
    model: str,
    audio: AudioPayload,
    language: str,
    boundary: str,
) -> tuple[str, bytes]:
    """Build the multipart/form-data body for one Groq transcription request.

    Pure bytes so the Workers adapter performs no encoding logic of its own and
    the exact payload shape is unit-testable without the Workers runtime.
    """
    if model not in GROQ_STT_MODELS:
        raise ValueError("unregistered Groq STT model")
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("unsupported language")

    crlf = b"\r\n"
    out = bytearray()

    def part(headers: Sequence[tuple[str, str]], body: bytes) -> None:
        out.extend(b"--" + boundary.encode("ascii") + crlf)
        for name, value in headers:
            out.extend(f"{name}: {value}".encode("utf-8") + crlf)
        out.extend(crlf)
        out.extend(body)
        out.extend(crlf)

    filename = f"padiem-voice.{audio.extension}"
    part(
        (
            ("Content-Disposition", f'form-data; name="file"; filename="{filename}"'),
            ("Content-Type", audio.mime_type),
        ),
        audio.data,
    )
    part((("Content-Disposition", 'form-data; name="model"'),), model.encode("utf-8"))
    if language != "auto":
        part((("Content-Disposition", 'form-data; name="language"'),), language.encode("utf-8"))
    part((("Content-Disposition", 'form-data; name="response_format"'),), b"json")
    part((("Content-Disposition", 'form-data; name="temperature"'),), b"0")
    out.extend(b"--" + boundary.encode("ascii") + b"--" + crlf)

    content_type = f"multipart/form-data; boundary={boundary}"
    return content_type, bytes(out)


def parse_groq_transcription_response(status: int, body: object) -> tuple[bool, str, str]:
    """Return ``(ok, text, code)`` for one Groq transcription response.

    ``code`` is a bounded, client-safe code; a provider message is never echoed
    to the browser because it can carry account or quota detail.
    """
    if not isinstance(body, dict):
        return False, "", "stt_failed"
    if status < 200 or status >= 300:
        return False, "", "stt_failed"
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return False, "", "stt_failed"
    return True, text.strip(), ""


def groq_model_sequence() -> tuple[str, ...]:
    """The Groq model fallback order (turbo first, then the full model)."""
    return GROQ_STT_MODELS


# ---------------------------------------------------------------------------
# Gemini Live STT contract (server mints a short-lived token; browser never
# receives a long-lived key)
# ---------------------------------------------------------------------------

GEMINI_LIVE_STT_MODEL = "gemini-3.5-transcribe-live"
#: Official REST endpoint for minting ephemeral tokens. Google's current
#: documentation and the curl example both use ``/v1beta/auth_tokens``, and
#: ephemeral tokens are documented as working only with the ``v1beta`` API
#: version. The ``v1alpha`` spelling used by the reference SDK call is a
#: *session connect* version, not the token endpoint version.
GEMINI_LIVE_TOKEN_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"
GEMINI_LIVE_ALLOWED_HOST = "generativelanguage.googleapis.com"

#: How much silence ends a turn. Gemini's automatic activity detection defaults
#: to 800ms; 650ms cut ordinary 0.7-1.5s thinking pauses into separate
#: utterances, so a long sentence was emitted as several final rows. 1300ms
#: keeps typical pauses inside one utterance at ~0.5s of extra final latency.
GEMINI_LIVE_VAD_SILENCE_MS = 1_300

#: Live sessions have a vendor-documented ~10 minute limit. Rotate before it
#: instead of letting the session end and permanently dropping to fallback.
GEMINI_LIVE_SESSION_ROTATE_MS = 9 * 60_000 + 20_000


def live_turn_boundary_reached(
    gap_silence_ms: int,
    vad_silence_ms: int = GEMINI_LIVE_VAD_SILENCE_MS,
) -> bool:
    """True when Gemini's automatic activity detection would close a turn.

    With the old 650ms window an ordinary 0.7-1.5s thinking pause closed the
    turn, so one long sentence became several partial final rows (#87). The
    1300ms window keeps those pauses inside a single turn.
    """
    return gap_silence_ms >= vad_silence_ms


def count_utterance_splits(
    intra_sentence_pauses_ms: Sequence[int],
    vad_silence_ms: int = GEMINI_LIVE_VAD_SILENCE_MS,
) -> int:
    """Number of extra final rows a long utterance would be split into.

    Zero means the whole sentence stays one row. This is the direct measure of
    the #87 regression, so it is part of the contract rather than a test-local
    helper.
    """
    return sum(1 for gap in intra_sentence_pauses_ms if live_turn_boundary_reached(gap, vad_silence_ms))


@dataclass(frozen=True)
class LiveSessionConfig:
    """The Live STT session parameters the browser must request."""

    model: str = GEMINI_LIVE_STT_MODEL
    vad_silence_ms: int = GEMINI_LIVE_VAD_SILENCE_MS
    rotate_after_ms: int = GEMINI_LIVE_SESSION_ROTATE_MS
    response_modalities: tuple[str, ...] = ("TEXT",)
    input_audio_transcription_mode: str = "VERBATIM"

    def to_public_dict(self) -> dict[str, object]:
        """Browser-safe description: no key, no token, no vendor account id."""
        return {
            "model": self.model,
            "vad_silence_ms": self.vad_silence_ms,
            "rotate_after_ms": self.rotate_after_ms,
            "response_modalities": list(self.response_modalities),
            "input_audio_transcription_mode": self.input_audio_transcription_mode,
        }


#: Ephemeral token lifetime. The total token is valid for 30 minutes; the
#: window in which the holder may *start* a new Live session is 1 minute.
#: These match the documented defaults, not a duration string sent to Google.
GEMINI_LIVE_TOKEN_EXPIRE_MINUTES = 30
GEMINI_LIVE_TOKEN_NEW_SESSION_EXPIRE_MINUTES = 1


def format_rfc3339_utc(epoch_ms: int) -> str:
    """Render epoch milliseconds as an absolute RFC3339 UTC timestamp.

    ``2026-10-14T05:00:00Z`` — exactly the shape Google's ``auth_tokens`` REST
    example uses for ``expireTime`` / ``newSessionExpireTime``. A relative
    duration such as ``"1800s"`` is rejected by the API, which is what the first
    ### CENTRAL defect was.
    """
    if not isinstance(epoch_ms, int) or isinstance(epoch_ms, bool) or epoch_ms <= 0:
        raise ValueError("epoch_ms must be a positive integer")
    seconds, millis = divmod(epoch_ms, 1000)
    stamp = datetime.datetime.fromtimestamp(seconds, tz=datetime.timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%S") + (f".{millis:03d}" if millis else "") + "Z"


def _now_epoch_ms() -> int:
    """Current wall clock in epoch milliseconds.

    A single indirection so tests can substitute a fixed clock instead of
    asserting against a value that moves between two calls.
    """
    return int(time.time() * 1000)


def build_live_token_request_body(
    model: str = GEMINI_LIVE_STT_MODEL,
    now_epoch_ms: int | None = None,
) -> dict[str, object]:
    """Body for minting a short-lived, model-locked Gemini Live auth token.

    Shape matches Google's current REST reference and the proven Global
    Classroom implementation (``netlify/functions/live-token.ts``), minus the
    Netlify runtime: the server owns the long-lived key and returns only the
    ephemeral token.

    - ``expireTime`` / ``newSessionExpireTime`` are **absolute RFC3339
      timestamps**, not durations.
    - the model is bound through ``liveConnectConstraints.model`` so the client
      cannot open a Live session against any other model.
    - ``uses`` stays 1 so a token starts at most one session.
    """
    if now_epoch_ms is None:
        now_epoch_ms = _now_epoch_ms()
    expire = now_epoch_ms + GEMINI_LIVE_TOKEN_EXPIRE_MINUTES * 60_000
    new_session = now_epoch_ms + GEMINI_LIVE_TOKEN_NEW_SESSION_EXPIRE_MINUTES * 60_000
    return {
        "uses": 1,
        "expireTime": format_rfc3339_utc(expire),
        "newSessionExpireTime": format_rfc3339_utc(new_session),
        "liveConnectConstraints": {"model": model},
    }


def extract_live_token(body: object) -> str | None:
    """Extract the ephemeral token from a Gemini auth-token response."""
    if not isinstance(body, dict):
        return None
    token = body.get("name")
    return token if isinstance(token, str) and token else None


# ---------------------------------------------------------------------------
# Product capability descriptor (which products may use the shared service)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductVoiceCapability:
    """One product's *declared* server permission surface (names only).

    ``secret_binding_names`` are the Secret bindings that product's own Worker
    is expected to hold. ``uses_shared_stt_service`` means the product reaches
    STT through the shared voice Worker's Service Binding instead of holding a
    provider key itself.
    """

    product: str
    worker_config_path: str
    secret_binding_names: tuple[str, ...] = ()
    uses_shared_stt_service: bool = True


#: Chat and Claw share the Padiem Chat Worker; B66 standalone reaches voice
#: through the same Chat bridge. All three therefore consume the shared voice
#: service rather than each holding a provider key.
PRODUCT_VOICE_CAPABILITIES: tuple[ProductVoiceCapability, ...] = (
    ProductVoiceCapability(
        product="chat",
        worker_config_path="apps/padiem-chat/wrangler.toml",
        uses_shared_stt_service=True,
    ),
    ProductVoiceCapability(
        product="claw",
        worker_config_path="apps/padiem-chat/wrangler.toml",
        uses_shared_stt_service=True,
    ),
    ProductVoiceCapability(
        product="b66",
        worker_config_path="reference/business-66-padiem-quote-v1/_worker.js",
        uses_shared_stt_service=True,
    ),
)


def iter_provider_chain() -> Iterable[SttProvider]:
    """Yield the provider chain in order (helper for tests and docs)."""
    return iter(STT_PROVIDER_ORDER)
