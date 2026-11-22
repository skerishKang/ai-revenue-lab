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

import base64

__all__ = ["PS_SINGLE_QUOTES", "ps_literal", "ps_utf8_literal"]

#: Every character PowerShell accepts as a single quote.
PS_SINGLE_QUOTES = frozenset("'‘’‚‛")


def ps_literal(value: str) -> str:
    """A single-quoted PowerShell literal whose content is exactly ``value``."""
    if not isinstance(value, str):
        raise TypeError("a PowerShell string value must be str")
    if "\x00" in value:
        raise ValueError("a PowerShell string value may not carry NUL")
    return "'" + "".join(ch + ch if ch in PS_SINGLE_QUOTES else ch for ch in value) + "'"


def ps_utf8_literal(value: str) -> str:
    """An ASCII-only PowerShell expression yielding exactly ``value``.

    A command can reach a PC through a PowerShell console whose input decoder is
    the machine's legacy code page (cp949 on a Korean Windows installation). A
    Korean path or query written into the command text as characters is then
    decoded as mojibake before PowerShell ever sees it, so the PC fails to find
    the folder and answers an error instead of the expected JSON.

    Base64 of the UTF-8 bytes carries the value as ASCII instead. The PC rebuilds
    the exact Python string with an explicit UTF-8 decoder, whatever code page
    the console used. The bytes are the value: no quoting, wildcard or code-page
    rule can change it. Callers keep their own validation, length and scope
    checks; this helper does not grant access to anything.
    """
    if not isinstance(value, str):
        raise TypeError("a PowerShell string value must be str")
    try:
        encoded = base64.b64encode(value.encode("utf-8")).decode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("a PowerShell string value must be valid Unicode") from exc
    return ("[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String("
            + ps_literal(encoded) + "))")
