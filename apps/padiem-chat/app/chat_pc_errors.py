"""The Chat PC lane's public error type, kept free of heavy imports.

#6792 made ``mcp_gateway_dispatch`` import ``ChatPCDriveError`` from
``chat_pc_drive``, and ``app_factory`` imports ``mcp_gateway_transport`` at
module load. That dragged the whole PC lane into the Worker's cold init, which
``test_5895_worker_import_is_js_free`` exists to prevent. The error only needs
``re``; every existing ``from .chat_pc_drive import ChatPCDriveError`` keeps
working through that module's re-export.
"""

from __future__ import annotations

import re


def _safe_pc_exception_cause(exc: BaseException) -> str:
    """Public diagnostic only: class plus a redacted first-line message."""
    name = type(exc).__name__
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name) is None:
        name = "Exception"
    try:
        message = str(exc).splitlines()[0][:8192]
    except Exception:
        message = "[message unavailable]"
    # Redact before truncation so a cut-off credential cannot escape a match.
    message = re.sub(r"(?i)\b(?:authorization|proxy-authorization|cookie|set-cookie|"
                     r"password|passwd|secret|token|api[ _-]?key|credential|"
                     r"access[_-]?token|refresh[_-]?token|client[_-]?secret|"
                     r"session[_-]?id|private[_-]?key|signature)\b"
                     r"\s*[:=]\s*.*", "[redacted]", message)
    message = re.sub(r"(?i)\b(?:bearer|basic)\s+\S+", "[redacted]", message)
    message = re.sub(r"https?://[^\s]+", "[url redacted]", message, flags=re.I)
    message = re.sub(r"""(["']).*?\1""", "[value redacted]", message)
    message = re.sub(r"[A-Za-z]:[\\/][^\s,;]+|/(?:[^\s/]+/)+[^\s,;]*",
                     "[path redacted]", message)
    message = re.sub(r"[^\s@]+@[^\s@]+", "[email redacted]", message)
    message = re.sub(r"[A-Za-z0-9_+/=.-]{24,}", "[value redacted]", message)
    message = re.sub(r"[^\S ]+|[\x00-\x1f\x7f]", " ", message)
    return name + ": " + message[:120]


class ChatPCDriveError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 503, *, cause: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.status_code = status_code
        self._cause = cause if isinstance(cause, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", cause) else None

    @property
    def cause(self) -> str | None:
        # Exception chaining is attached after construction, so inspect it
        # when the HTTP boundary serializes the error.
        if self.status_code == 503 and self.code.startswith("chat_pc_"):
            diagnostic = _safe_pc_exception_cause(self.__cause__ or self)
            if self._cause is not None:
                name, message = diagnostic.split(": ", 1)
                return name + ": " + self._cause + ": " + message
            return diagnostic
        return self._cause

    def public_error(self) -> dict:
        """The bounded browser error: a fixed code, a fixed message, a safe cause.

        ``cause`` is carried only when it already matches the internal code
        grammar, so an engine or provider blob can never reach the browser
        through this field.
        """
        error = {"code": self.code, "message": self.user_message}
        if self.cause is not None:
            error["cause"] = self.cause
        return error


class ChatPCApprovalPause(Exception):
    """Non-error carrier when the Engine pauses a PC run for user confirmation."""

    def __init__(
        self,
        orchestration: dict,
        conversation_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        super().__init__("approval_paused")
        self.orchestration = dict(orchestration)
        self.conversation_id = conversation_id
        self.run_id = run_id
