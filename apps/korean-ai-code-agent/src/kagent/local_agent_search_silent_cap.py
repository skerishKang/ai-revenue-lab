"""#8048 — the raised silence cap for a recursive file search.

A recursive walk can run for up to its own 180 s wall-clock bound. The default
60 s silence cap would cut a legitimately long search in half, so this module
names the cap and the marker that identifies a search command. It lives apart
from the executor so that file's size cap is not raised (#7216).
"""
from __future__ import annotations

#: The marker the recursive search script carries. A command that walks
#: subfolders can run for up to its own 180 s wall-clock bound, so its silence
#: cap is raised above the 60 s default. The marker is the search script's own
#: ``$timeLimit=`` assignment, unique to that builder.
RECURSIVE_SEARCH_MARKER = "$timeLimit="
#: The silence cap for a recursive search. The search script ends at its own
#: 180 s bound with a partial result; this cap only keeps the silence bound
#: from firing first.
RECURSIVE_SEARCH_SILENT_CAP_SECONDS = 190.0


def recursive_search_silent_cap(command_text: str | None) -> float | None:
    """The raised silence cap for a recursive search command, else None."""

    if isinstance(command_text, str) and RECURSIVE_SEARCH_MARKER in command_text:
        return RECURSIVE_SEARCH_SILENT_CAP_SECONDS
    return None


__all__ = [
    "RECURSIVE_SEARCH_MARKER",
    "RECURSIVE_SEARCH_SILENT_CAP_SECONDS",
    "recursive_search_silent_cap",
]