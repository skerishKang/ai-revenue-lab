"""Safe handling of PostgreSQL connection URLs.

A connection URL may embed a password (``postgres://user:pass@host/db``). These
helpers ensure the password is never written to logs, exception messages, repr
output, or test artifacts. Only the redacted form (``...:***@...``) is ever
surfaced, and even that is avoided in error messages, which stay generic.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Return *url* with any embedded password replaced by ``***``.

    Safe to log. If the URL cannot be parsed it is returned as ``<redacted>``
    rather than risking leakage of an unparseable-but-credential-bearing string.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<redacted>"
    if parts.password:
        netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return url


def is_postgres_url(url: str) -> bool:
    """True when *url* uses a recognized PostgreSQL scheme.

    Recognizes ``postgres://`` and ``postgresql://`` (and the ``+driver``
    variants such as ``postgresql+psycopg://``). This is used only to validate an
    explicitly configured backend; the backend is never *inferred* from the URL
    shape alone.
    """
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return False
    return scheme == "postgres" or scheme.startswith("postgresql")
