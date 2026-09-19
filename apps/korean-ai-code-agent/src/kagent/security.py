"""KAgent credential boundary.

Two security semantics used to share one implementation, which made them impossible to
reason about separately. ``redact_secrets`` was being used in dozens of places as a
detector — ``redact_secrets(value) != value`` — even though a redactor and a gate need
opposite judgement: a redactor must not damage ordinary prose, while a gate must fail
closed on credential material. Growing one regex set silently changed both.

They are now separate entry points over one credential grammar:

```text
contains_credential_material(text) -> bool   reject raw credential material
redact_secrets(text)               -> str    presentation-safe copy, idempotent
```

The grammar is shape-based, never keyword-presence-based: naming ``password`` in a
sentence is not a credential, so benign documentation prose stays both unflagged and
byte-identical. ``tests/test_security.py`` pins both directions.

Relative to the three patterns this replaces, detection is broader on every credential
shape they matched (verified case by case, including the glued ``Authorization:Bearer``
and quoted-value cases those patterns only partly masked), and it closes the JSON quoted
assignment and truncated-excerpt shapes they missed entirely.

Two deliberate narrowings are pinned by test. A 1-2 character value inside a sentence
(``password: ab in the config``) now reads as prose, against the trio. And a scheme word
with nothing token-shaped after it (``Bearer short``) now reads as prose, against the
stricter duplicate grammar this module replaces at the GitHub draft-PR gate. Both shapes
are named as acceptable prose in #2784.
"""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"
_REDACTED_KEY = "[REDACTED_KEY]"

_KEYWORD = (
    r"api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|id[_-]?token|auth[_-]?token"
    r"|bearer[_-]?token|client[_-]?secret|secret[_-]?key|access[_-]?key|secret|token"
    r"|password|passwd|passphrase|pwd|private[_-]?key|credential"
)

# Two assignment shapes, separated because a quoted value may contain spaces and an
# unquoted one may not. A single pattern would either leak the tail of
# {"api_key": "multi word secret"} or over-match prose.
#
# The quoted shape is deliberately tolerant at both ends, because both truncations occur in
# this product's inputs: an excerpt can start mid-object, so the key loses its opening
# quote, and a bounded read can stop inside a value, so the value never gets a closing one.
# Either cut used to hide a complete credential. What stays required is a quote immediately
# after the separator — that is the mark of a value rather than a sentence, and it is what
# keeps the benign-prose corpus clean.
_QUOTED_ASSIGN_RE = re.compile(
    r"""(?xi)
    ["']?            # opening quote of the key, absent when the text starts mid-object
    (?:%s)
    ["']?            # closing quote of the key
    \s*[:=]\s*
    (["'])           # opening quote of the value: required, this defines the shape
    ([^"']{1,})      # the value itself, spaces included
    (?:\1|\Z)        # matching close, or an excerpt that ended inside the value
    """
    % _KEYWORD
)
_PLAIN_ASSIGN_RE = re.compile(
    r"(?i)(?:%s)\s*([=:])([ \t]*)([\"']?)([^\s\"']{1,})" % _KEYWORD
)
# A value is credential material when it is quoted, tightly attached to an `=`, long
# enough not to be an English word, or terminated like a field rather than followed by
# more sentence. That last test keeps "pwd=ab" caught, as it was before, while
# "the password: at least eight characters is the rule" stays clean.
_VALUE_LENGTH_FLOOR = 6
_FIELD_END_RE = re.compile(r"""(?:[;,)}\]"']|\r?\n|&|\Z)""")


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Collapse overlapping and touching spans so one value is masked exactly once.

    The quoted and plain shapes both fire on ``password = 'multi word'`` — the plain rule
    sees the first word, the quoted rule sees the whole value. Masking them independently
    would splice the marker into the middle of the text.
    """
    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _assignment_spans(text: str) -> list[tuple[int, int]]:
    """Character spans holding a credential value, for detection and masking alike."""
    spans: list[tuple[int, int]] = []
    for match in _QUOTED_ASSIGN_RE.finditer(text):
        spans.append(match.span(2))
    for match in _PLAIN_ASSIGN_RE.finditer(text):
        sep, gap, quote, value = match.groups()
        terminated = bool(_FIELD_END_RE.match(text[match.end(4) :]))
        tight = sep == "=" and gap == ""
        if bool(quote) or terminated or tight or len(value) >= _VALUE_LENGTH_FLOOR:
            spans.append(match.span(4))
    return _merge_spans(spans)


_TAG_RE = re.compile(r"(?i)<(%s)>\s*(\S{6,}?)\s*</\1>" % _KEYWORD)

# An explicit authorization header name carries its own credential context, so any value
# there counts, as it did before. A bare scheme word is ordinary vocabulary and must be
# followed by something token-shaped, so "this document explains bearer tokens" is clean.
_AUTH_HEADER_RE = re.compile(
    r"(?i)(\b(?:proxy-)?authorization\s*:\s*(?:bearer|basic|digest)\s*)([^\s]+)"
)
_BARE_SCHEME_RE = re.compile(
    r"(?i)\b(bearer|basic|digest)\s+([A-Za-z0-9+/=_\-.]{16,})"
)
_COOKIE_RE = re.compile(r"(?i)\bset-cookie\s*:\s*(\S{16,})")
# Between `scheme://user:` and `@host` the position *is* the password field, so no length
# heuristic is needed here — a one-character password is still a credential. A short cookie
# value is not, which is why that rule above keeps a floor instead.
_URL_CREDENTIALS_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^/\s:@]+:)([^@\s]+)@")

# Provider key material. No leading \b anywhere: a value glued to preceding alphanumerics
# was invisible to the previous detector, and that is the gap this module exists to close.
# The 8-char floor matches the pattern being replaced.
_PROVIDER_RE = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{16,}"
    r"|AIza[0-9A-Za-z_\-]{30,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{12,}"
    r"|sk_live_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9._\-]{8,})"
)
_PEM_START_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
# Masking only the header line would leave the key body in place, which is the part that
# matters, so the redactor replaces the whole block and falls back to the marker when the
# closing line is absent (truncated log, sliced excerpt).
_PEM_BLOCK_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace each value span, highest offset first, so earlier spans stay valid."""
    result = text
    for start, end in sorted(spans, reverse=True):
        result = result[:start] + _REDACTED + result[end:]
    return result


# Applied in order. Assignment first so "token=sk-…" is masked once, at the separator.
_REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (_AUTH_HEADER_RE, r"\1" + _REDACTED),
    (_COOKIE_RE, lambda m: m.group(0).split(":", 1)[0] + ": " + _REDACTED),
    (_URL_CREDENTIALS_RE, r"\1" + _REDACTED),
    (_TAG_RE, lambda m: f"<{m.group(1)}>{_REDACTED}</{m.group(1)}>"),
    (_PEM_BLOCK_RE, lambda m: _REDACTED_KEY),
    (_PROVIDER_RE, _REDACTED_KEY),
    (_BARE_SCHEME_RE, r"\1 " + _REDACTED),
)

_DETECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    _AUTH_HEADER_RE,
    _BARE_SCHEME_RE,
    _COOKIE_RE,
    _URL_CREDENTIALS_RE,
    _TAG_RE,
    _PROVIDER_RE,
    _PEM_START_RE,
)


def _require_text(value: object, function_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{function_name} requires a string, got {type(value).__name__}")
    return value


def contains_credential_material(text: str) -> bool:
    """True when the text carries raw credential material and must not be accepted.

    Shape-driven on purpose. Words such as password, token or secret are documentation
    vocabulary in this product, and treating their presence as a credential would reject
    legitimate run input.
    """
    value = _require_text(text, "contains_credential_material")
    if not value:
        return False
    if _assignment_spans(value):
        return True
    return any(pattern.search(value) for pattern in _DETECTION_PATTERNS)


def redact_secrets(text: str) -> str:
    """Return a presentation-safe copy with credential material replaced by markers.

    Idempotent: a redacted string stays byte-identical under a second pass, because
    several call sites redact text an upstream path may already have redacted.
    """
    value = _require_text(text, "redact_secrets")
    redacted = _mask_spans(value, _assignment_spans(value))
    for pattern, replacement in _REDACTION_RULES:
        redacted = pattern.sub(replacement, redacted)
    return redacted
