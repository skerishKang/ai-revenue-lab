"""Single GitHub App OAuth port composition shared by every Chat runtime.

The Worker (worker.py) and the COM2 CPython host (app/local_cpython.py)
compose the connector ports here so both lanes always bind the same class
pair behind the same reviewed fail-closed gate: a runtime without the App
client secret, without a database, or without a product session secret
strong enough to seal token rows composes no ports at all, and the routes
keep answering the reviewed ``github_connector_unavailable`` 503 instead of
starting half-bound or refusing the host at boot.
"""
from __future__ import annotations


def compose_github_oauth_ports(*, db, session_secret, client_secret,
                               provider_transport=None):
    """Return ``(store, provider, unbound_reason)``.

    ``unbound_reason`` is ``None`` when the pair is bound; otherwise one of
    ``secret_absent`` / ``store_unavailable`` / ``session_secret_weak`` and
    both ports are ``None``. No material or length enters any log.
    """
    secret = client_secret.strip() if isinstance(client_secret, str) else ""
    if not secret:
        return None, None, "secret_absent"
    if db is None:
        return None, None, "store_unavailable"
    if not isinstance(session_secret, str) or len(session_secret) < 32:
        return None, None, "session_secret_weak"
    from .github_oauth_store import D1GitHubOAuthStore
    from .github_oauth_provider import GitHubAppOAuthProvider
    store = D1GitHubOAuthStore(db, session_secret=session_secret)
    provider = GitHubAppOAuthProvider(client_secret=secret,
                                      transport=provider_transport)
    return store, provider, None
