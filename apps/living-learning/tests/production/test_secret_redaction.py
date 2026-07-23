"""Secret redaction contracts (URLs never leak passwords)."""

from __future__ import annotations

from app.production.database import redact_url, is_postgres_url


def test_redact_password_in_url():
    url = "postgresql://user:supersecretpw@host.example:5432/db"
    redacted = redact_url(url)
    assert "supersecretpw" not in redacted
    assert "***" in redacted
    assert "host.example" in redacted


def test_redact_url_without_password_unchanged():
    url = "postgresql://host.example:5432/db"
    assert redact_url(url) == url


def test_redact_bad_url_never_raises():
    assert redact_url("not a url :: %%") == "<redacted>" or isinstance(redact_url("::"), str)


def test_is_postgres_url():
    assert is_postgres_url("postgresql://u:p@h/db")
    assert is_postgres_url("postgres://u:p@h/db")
    assert not is_postgres_url("sqlite:///x.db")
    assert not is_postgres_url("")
