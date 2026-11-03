"""Canonical MCP OAuth resource/issuer metadata; no request or DB dependency."""
from __future__ import annotations

from urllib.parse import urlsplit

from .same_origin_guard import expected_browser_origin


MCP_RESOURCE_PATH = "/api/mcp"
PROTECTED_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"
AUTHORIZATION_SERVER_METADATA_PATH = "/.well-known/oauth-authorization-server"
AUTHORIZE_PATH = "/oauth/authorize"
AUTHORIZE_INFO_PATH = "/oauth/authorize/info"
TOKEN_PATH = "/oauth/token"
REGISTER_PATH = "/oauth/register"
REVOKE_PATH = "/oauth/revoke"
MCP_OAUTH_SCOPE = "mcp:pc"
TOKEN_ENDPOINT_AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")


def _origin(settings) -> str | None:
    return expected_browser_origin(settings)


def issuer(settings) -> str | None:
    return _origin(settings)


def canonical_resource(settings) -> str | None:
    origin = _origin(settings)
    return origin + MCP_RESOURCE_PATH if origin else None


def protected_resource_metadata_url(settings) -> str | None:
    origin = _origin(settings)
    return origin + PROTECTED_RESOURCE_METADATA_PATH if origin else None


def normalize_resource(value, settings) -> str | None:
    """The canonical MCP server URI, accepting origin or /api/mcp forms."""
    canonical = canonical_resource(settings)
    if canonical is None:
        return None
    if value is None or (isinstance(value, str) and not value.strip()):
        return canonical
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parsed, target = urlsplit(value), urlsplit(canonical)
        if (
            parsed.scheme.lower() != target.scheme
            or parsed.hostname is None
            or (parsed.hostname or "").lower() != (target.hostname or "").lower()
            or parsed.port != target.port
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment
            or parsed.path not in ("", "/", MCP_RESOURCE_PATH)
        ):
            return None
    except ValueError:
        return None
    return canonical


def _help_url(settings) -> str | None:
    origin = _origin(settings)
    return origin + "/help.html#mcp" if origin else None


def protected_resource_metadata(settings) -> dict:
    return {
        "resource": canonical_resource(settings),
        "authorization_servers": [issuer(settings)],
        "scopes_supported": [MCP_OAUTH_SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "PADIEM MCP",
        "resource_documentation": _help_url(settings),
    }


def authorization_server_metadata(settings) -> dict:
    origin = _origin(settings)
    return {
        "issuer": origin,
        "authorization_endpoint": origin + AUTHORIZE_PATH,
        "token_endpoint": origin + TOKEN_PATH,
        "registration_endpoint": origin + REGISTER_PATH,
        "revocation_endpoint": origin + REVOKE_PATH,
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": list(TOKEN_ENDPOINT_AUTH_METHODS),
        "revocation_endpoint_auth_methods_supported": list(TOKEN_ENDPOINT_AUTH_METHODS),
        "scopes_supported": [MCP_OAUTH_SCOPE],
        "authorization_response_iss_parameter_supported": True,
        "client_id_metadata_document_supported": False,
        "service_documentation": _help_url(settings),
    }


def authorization_challenge(settings, *, invalid_token: bool = False) -> str | None:
    metadata = protected_resource_metadata_url(settings)
    if metadata is None:
        return None
    challenge = (
        'Bearer realm="padiem-mcp", resource_metadata="' + metadata + '", '
        'scope="' + MCP_OAUTH_SCOPE + '"'
    )
    if invalid_token:
        challenge += ', error="invalid_token"'
    return challenge
