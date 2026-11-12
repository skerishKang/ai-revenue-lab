"""One way to put a Python string into PowerShell command text (#7559, #7560).

PowerShell closes a single-quoted string on five characters, not one: the ASCII
apostrophe and the four typographic single quotes U+2018, U+2019, U+201A and
U+201B (``CodeGeneration.IsSingleQuote``). Doubling only ``'`` leaves the other
four able to end the string and run what follows as a statement.

:func:`ps_literal` doubles every one of the five, which is PowerShell's own
escaping rule (``CodeGeneration.EscapeSingleQuotedStringContent``). Inside a
single-quoted string nothing else is special: backtick, ``$(``, ``;`` and line
breaks are plain text. Every command builder that places a path, a search term
or a name in PowerShell text uses this one function.

It is not a validator: callers keep their own path, length and control
character rules.
"""
from __future__ import annotations

__all__ = ["PS_SINGLE_QUOTES", "ps_literal"]

#: Every character PowerShell accepts as a single quote.
PS_SINGLE_QUOTES = frozenset("'‘’‚‛")


def ps_literal(value: str) -> str:
    """A single-quoted PowerShell literal whose content is exactly ``value``."""
    if not isinstance(value, str):
        raise TypeError("a PowerShell string value must be str")
    if "\x00" in value:
        raise ValueError("a PowerShell string value may not carry NUL")
    return "'" + "".join(ch + ch if ch in PS_SINGLE_QUOTES else ch for ch in value) + "'"
