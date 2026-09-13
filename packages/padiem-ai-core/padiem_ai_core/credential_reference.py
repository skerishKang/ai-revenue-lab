"""Shared non-secret credential binding-name grammar (#2103 ACT-1).

Core owns the single grammar for a *credential binding name* — the opaque,
non-secret identifier a lane uses to address server-owned credential material.
A binding name is the address of a secret, never the secret itself.

Authority separation this contract preserves (#2103 ACT-0 findings):

* ``apps/korean-ai-platform`` (Business 14) owns runtime resolution of
  platform-managed environment bindings. ``platform_secret`` reads one
  server-owned environment variable named by the binding; ``request_byok`` is
  request-scoped and intentionally not satisfied by that server plane;
  ``none`` needs no credential at all.
* ``padiem_control_plane.product_tier_routes`` declares product tier routes
  together with non-secret binding names only. It never resolves secrets.
* The Control Plane identity/entitlement plane owns subject grants, expiry,
  and route entitlements. It holds no route-credential material.

Deliberately out of scope for this module:

* no credential-mode enum unification — ``CredentialSource`` and
  ``ProductCredentialMode`` are adjacent but not proven to be identical
  authority semantics, so this module defines no mode vocabulary at all;
* no secret resolver, no environment read, no provider call, no storage;
* no vault, no issuance/rotation/revocation API, no expiry semantics;
* no route-selection behavior of any kind.

Consuming lanes keep their own per-lane length sublimits on top of this
grammar. The Control Plane product declaration contract retains its
``<=63``-character binding-name sublimit; this module does not widen it.

This module is standard-library only, network-free, environment-free, and
holds no secret material.
"""

from __future__ import annotations

import re

#: Credential material never crosses this boundary. Every value reachable from
#: this module is a non-secret binding name or a length/format rule.
RAW_SECRET_IN_CONTRACT = False

#: Canonical binding-name grammar. A single uppercase letter followed by 2-127
#: characters drawn from uppercase letters, digits, and underscore: total
#: length 3-128. Provider-qualified identifiers (``kilo/foo``, ``agent:x``)
#: and secret-shaped values (``sk-live-...``) do not match.
CREDENTIAL_BINDING_PATTERN = r"^[A-Z][A-Z0-9_]{2,127}$"

CREDENTIAL_BINDING_MIN_LENGTH = 3
CREDENTIAL_BINDING_MAX_LENGTH = 128

_CREDENTIAL_BINDING_RE = re.compile(CREDENTIAL_BINDING_PATTERN)


class CredentialReferenceError(ValueError):
    """Raised when a credential binding name violates the shared grammar.

    Fail closed: a non-conforming name is never accepted and never
    normalized. The message names the violated rule but never echoes the
    submitted value, so a caller that mistakenly passes secret material
    cannot leak it through an exception or a log line.
    """


def validate_credential_binding_name(name: str) -> str:
    """Validate a non-secret credential binding name and return it unchanged.

    The return value is the same string object that was passed in: validation
    never copies, strips, or normalizes, so a caller cannot mistake a validated
    name for a canonicalized one.
    """
    if not isinstance(name, str):
        raise CredentialReferenceError("credential binding name must be a string")
    if not _CREDENTIAL_BINDING_RE.match(name):
        if not name:
            raise CredentialReferenceError("credential binding name must not be empty")
        if len(name) < CREDENTIAL_BINDING_MIN_LENGTH:
            raise CredentialReferenceError(
                "credential binding name is shorter than "
                f"{CREDENTIAL_BINDING_MIN_LENGTH} characters"
            )
        if len(name) > CREDENTIAL_BINDING_MAX_LENGTH:
            raise CredentialReferenceError(
                "credential binding name is longer than "
                f"{CREDENTIAL_BINDING_MAX_LENGTH} characters"
            )
        raise CredentialReferenceError(
            "credential binding name must start with an uppercase letter and "
            "use only uppercase letters, digits, and underscore"
        )
    return name
