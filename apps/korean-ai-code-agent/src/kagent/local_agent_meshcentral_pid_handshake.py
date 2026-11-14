"""The pid a queued PC command actually runs under, carried back before its work.

The marker file names the dispatch, but its name is not in the process command line:
the agent runs a queued command through ``powershell -Command -`` and feeds the body on
standard input, while ``-File`` puts only the staged script path in the command line.
A process-table lookup by marker name therefore has nothing to match on a real PC.

The wrapper is the process that holds the agent's one command child, and its ``$PID`` is
the authority a stop needs. It prints that number once, before the command body, on the
same transcript this connector already reads. The value is tagged with a per-run random
token so an echoed script line cannot be mistaken for the answer.
"""
from __future__ import annotations

import re

#: The line prefix. The per-run token follows it, then ``=`` and the pid.
PID_HANDSHAKE_PREFIX = "__PADIEM_PID__"

_PID_TOKEN = re.compile(r"^[0-9a-f]{16,64}$")


def checked_pid_token(token: str) -> str:
    if not isinstance(token, str) or _PID_TOKEN.fullmatch(token) is None:
        raise ValueError("the pid handshake token is not a per-run value")
    return token


def pid_handshake_statement(token: str) -> str:
    """The one complete statement that prints this wrapper's own pid, and flushes it.

    ``[Console]::WriteLine`` is used instead of ``Write-Output`` so the line is not
    captured by the command's ``Out-String`` envelope and does not wait for the host's
    formatting pipeline. It is one statement, which is what the agent's stdin console
    requires.
    """
    checked = checked_pid_token(token)
    return (
        "[Console]::WriteLine('" + PID_HANDSHAKE_PREFIX + checked + "=' + $PID); "
        "[Console]::Out.Flush();"
    )


def parse_pid_handshake(raw: bytes | bytearray, token: str) -> int | None:
    """The pid this token announced, or ``None`` when the line has not arrived."""
    checked = checked_pid_token(token)
    if not isinstance(raw, (bytes, bytearray)):
        return None
    needle = (PID_HANDSHAKE_PREFIX + checked + "=").encode("ascii")
    matches = re.findall(re.escape(needle) + rb"([1-9][0-9]{0,8})", bytes(raw))
    return int(matches[0]) if matches else None


def strip_pid_handshake(raw: bytes | bytearray, token: str) -> bytes:
    """Remove the resolved handshake line from a transcript, leaving user output alone.

    The echoed script contains the token and ``$PID`` rather than a number, so this
    pattern cannot remove the echo; only the line the wrapper actually printed matches.
    """
    checked = checked_pid_token(token)
    data = bytes(raw)
    needle = (PID_HANDSHAKE_PREFIX + checked + "=").encode("ascii")
    pattern = re.compile(
        rb"[^\r\n]*" + re.escape(needle) + rb"[1-9][0-9]{0,8}[^\r\n]*(?:\r?\n|\r)?"
    )
    return pattern.sub(b"", data, count=1)
