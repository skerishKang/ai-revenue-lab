"""Canonical read-only per-product access projection for the PADIEM home (#4546).

Parent issue #4428 requires the PADIEM customer home to show only the services
the user can actually use *per server authority*.  This module is the
versioned, bounded, read-only **contract** for that question.  It performs no
network I/O, no storage, no session minting, and it grants nothing.

Authority basis, verified 2026-10-13 against ``origin/main`` = ``007e68e1a``:

* ``GET /api/auth/status`` (``apps/padiem-chat/app/auth_routes.py``) projects
  the B62 presentation session only (``ready`` / ``authenticated`` /
  ``session_state`` / ``user``).  A ``signed_in`` state is **not** a
  product-access fact and is never read here.
* The canonical identity authority (``identity_authority_worker.py``,
  ``identity_authority_durable.py``) knows exactly two PADIEM product ids —
  ``b62`` and ``b54-padiem-claw`` — and stores identity links, canonical auth
  sessions, tenants and tenant memberships.  It stores **no** product-access
  or entitlement row, so no browser-readable product grant exists.
* ``EntitlementSnapshot`` / ``engine_entitlement_producer.py`` /
  ``engine_admission_authority.py`` are internal Engine execution-policy
  inputs.  Their own docstrings state they are not browser assertions.
* PADIEM Engine has **no canonical product id**: it is a backend service
  boundary with no customer screen.  It is therefore not requestable here and
  a request naming it is refused as an unknown product.

Because no verified product-access authority exists yet, this module ships
with an **empty** authority registry: every product resolves to
``unavailable`` with ``authority="none"``.  Wiring a real source is a reviewed
code change at the call site (a future CENTRAL-owned route), never a runtime
switch and never a temporary allow list.  The status taxonomy is closed:
``available`` requires an explicit current server allow, ``denied`` an
explicit verified denial, and everything else (absent, unconfigured,
unreadable, stale, cross-subject, malformed) is ``unavailable`` — never a
false green and never an invented denial.

Browser-safety contract: the projected payload is a closed key set
(:data:`PRODUCT_ACCESS_ENTRY_BROWSER_KEYS`).  It never carries owner,
workspace, tenant, session, profile, credential, plan, or cross-product
(B66) facts, and it is served ``no-store`` (see
:data:`PRODUCT_ACCESS_RESPONSE_HEADERS`).

This module is pure contract: no storage, no network, no side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import re
from types import MappingProxyType
from typing import Protocol

from .contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)


PRODUCT_ACCESS_PROJECTION_VERSION = "product-access-projection-v1"

# Canonical PADIEM product ids known to the identity authority.  Reused
# verbatim; no second product registry is created here.
PADIEM_CHAT_PRODUCT_ID = "b62"
PADIEM_CLAW_PRODUCT_ID = "b54-padiem-claw"

# The only products the customer home may ask about.  PADIEM Engine has no
# canonical product id and is deliberately absent; B66 is a separate
# brand/account and is deliberately absent.
PADIEM_HOME_PRODUCT_IDS: tuple[str, ...] = (
    PADIEM_CHAT_PRODUCT_ID,
    PADIEM_CLAW_PRODUCT_ID,
)

MAX_PRODUCT_ACCESS_ITEMS = 8
MAX_FINDING_CLOCK_SKEW = timedelta(minutes=5)

_AUTHORITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REASON_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ProductAccessContractError(ControlPlaneContractError):
    """Fail-closed violation of the product-access projection contract."""


class ProductAccessState(str, Enum):
    """Closed three-state taxonomy.  There is no fourth answer."""

    AVAILABLE = "available"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


# Closed machine-readable provenance vocabulary.
PRODUCT_ACCESS_REASONS = frozenset(
    {
        "no_authenticated_subject",
        "subject_not_eligible",
        "no_registered_authority",
        "authority_read_failed",
        "authority_response_invalid",
        "authority_product_mismatch",
        "authority_subject_mismatch",
        "authority_not_yet_valid",
        "authority_finding_stale",
        "authority_unconfirmed",
        "server_allow_confirmed",
        "server_denial_confirmed",
    }
)

PRODUCT_ACCESS_ENTRY_BROWSER_KEYS = frozenset(
    {
        "product_id",
        "access",
        "authority",
        "reason",
        "expires_at",
    }
)
PRODUCT_ACCESS_PROJECTION_BROWSER_KEYS = frozenset({"version", "products"})

# Required response headers for the future read-only route.  Minted here so
# the transport owner does not have to re-derive the caching rule.
PRODUCT_ACCESS_RESPONSE_HEADERS = MappingProxyType({"cache-control": "no-store"})

# Shipped authority registry.  Empty on purpose: no verified product-access
# authority exists yet, so the projection can only answer ``unavailable``.
# A wired deployment passes its own reviewed source mapping explicitly; this
# module never mutates the mapping and never falls back to a default source.
PRODUCT_ACCESS_AUTHORITY_SOURCES: Mapping[str, "ProductAccessAuthoritySource"] = (
    MappingProxyType({})
)

# Provenance used when no authority source is registered at all.
NO_AUTHORITY = "none"


def _error(code: str, message: str) -> ProductAccessContractError:
    return ProductAccessContractError(code, message)


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or not _AUTHORITY_RE.fullmatch(value):
        raise _error(
            "invalid_product_access_field",
            f"{name} must be a bounded safe identifier",
        )
    return value


def _aware(name: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise _error(
            "invalid_product_access_field",
            f"{name} must be timezone-aware",
        )
    return value


@dataclass(frozen=True, slots=True)
class ProductAccessFinding:
    """One authority source's answer for one (product, subject) pair.

    A finding is the only way a source may speak.  It carries no owner,
    workspace, tenant, session, plan, role, or B66 fact, so none of those can
    reach the browser even if a source wanted to send them.
    """

    product_id: str
    subject: CanonicalSubjectRef
    state: ProductAccessState
    authority: str
    issued_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.product_id not in PADIEM_HOME_PRODUCT_IDS:
            raise _error(
                "unknown_product_id",
                "a finding may only name a requestable PADIEM home product",
            )
        if not isinstance(self.subject, CanonicalSubjectRef):
            raise _error(
                "invalid_product_access_subject",
                "finding subject must be CanonicalSubjectRef",
            )
        if not isinstance(self.state, ProductAccessState):
            raise _error(
                "invalid_product_access_state",
                "finding state must be ProductAccessState",
            )
        object.__setattr__(self, "authority", _identifier("authority", self.authority))
        object.__setattr__(self, "issued_at", _aware("issued_at", self.issued_at))
        if self.expires_at is not None:
            object.__setattr__(
                self, "expires_at", _aware("expires_at", self.expires_at)
            )
            if self.expires_at <= self.issued_at:
                raise _error(
                    "invalid_product_access_field",
                    "finding expires_at must be after issued_at",
                )


class ProductAccessAuthoritySource(Protocol):
    """Server-only boundary for one product's access authority.

    Implementations are injected by a reviewed call site.  They own their own
    storage, session reconciliation and scoping; this module only validates
    and projects what they return.
    """

    authority: str

    def read_product_access(
        self,
        *,
        product_id: str,
        subject: CanonicalSubjectRef,
        now: datetime,
    ) -> ProductAccessFinding: ...


@dataclass(frozen=True, slots=True)
class ProductAccessEntry:
    """One product's projected, browser-safe access answer."""

    product_id: str
    access: ProductAccessState
    authority: str
    reason: str
    expires_at: datetime | None = None

    def to_browser_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "product_id": self.product_id,
            "access": self.access.value,
            "authority": self.authority,
            "reason": self.reason,
        }
        if self.expires_at is not None:
            payload["expires_at"] = (
                self.expires_at.astimezone(timezone.utc).isoformat()
            )
        return payload


@dataclass(frozen=True, slots=True)
class ProductAccessProjection:
    """The whole versioned read-only projection for one caller."""

    version: str
    products: tuple[ProductAccessEntry, ...]

    def to_browser_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "products": [entry.to_browser_dict() for entry in self.products],
        }

    def entry_for(self, product_id: str) -> ProductAccessEntry | None:
        return next(
            (
                entry
                for entry in self.products
                if entry.product_id == product_id
            ),
            None,
        )

    @property
    def available_product_ids(self) -> tuple[str, ...]:
        return tuple(
            entry.product_id
            for entry in self.products
            if entry.access is ProductAccessState.AVAILABLE
        )


def _unavailable(
    product_id: str,
    *,
    authority: str,
    reason: str,
    expires_at: datetime | None = None,
) -> ProductAccessEntry:
    return ProductAccessEntry(
        product_id=product_id,
        access=ProductAccessState.UNAVAILABLE,
        authority=authority,
        reason=reason,
        expires_at=expires_at,
    )


def _source_authority(source: ProductAccessAuthoritySource) -> str:
    try:
        authority = source.authority
    except Exception:  # noqa: BLE001 - a broken source must fail closed
        return NO_AUTHORITY
    if not isinstance(authority, str) or not _AUTHORITY_RE.fullmatch(authority):
        return NO_AUTHORITY
    return authority


def _validate_sources(
    sources: Mapping[str, ProductAccessAuthoritySource] | None,
) -> Mapping[str, ProductAccessAuthoritySource]:
    if sources is None:
        return PRODUCT_ACCESS_AUTHORITY_SOURCES
    if not isinstance(sources, Mapping):
        raise _error(
            "invalid_product_access_authority_sources",
            "authority sources must be a mapping of product id to source",
        )
    for product_id in sources:
        if product_id not in PADIEM_HOME_PRODUCT_IDS:
            raise _error(
                "unknown_product_id",
                "an authority source may only be registered for a requestable product",
            )
    return sources


def _requested_products(
    product_ids: tuple[str, ...] | list[str] | None,
) -> tuple[str, ...]:
    if product_ids is None:
        return PADIEM_HOME_PRODUCT_IDS
    if isinstance(product_ids, str) or not isinstance(product_ids, (tuple, list)):
        raise _error(
            "invalid_product_access_request",
            "requested product ids must be a tuple or list of product ids",
        )
    if len(product_ids) > MAX_PRODUCT_ACCESS_ITEMS:
        raise _error(
            "product_access_request_too_large",
            "requested product count exceeds the bounded limit",
        )
    ordered: list[str] = []
    for product_id in product_ids:
        if not isinstance(product_id, str):
            raise _error(
                "unknown_product_id",
                "requested product ids must be strings",
            )
        if product_id not in PADIEM_HOME_PRODUCT_IDS:
            raise _error(
                "unknown_product_id",
                "requested product id is not a requestable PADIEM home product",
            )
        if product_id not in ordered:
            ordered.append(product_id)
    if not ordered:
        raise _error(
            "invalid_product_access_request",
            "at least one requestable product id is required",
        )
    return tuple(ordered)


def _resolve_without_subject(product_id: str) -> ProductAccessEntry:
    return _unavailable(
        product_id,
        authority=NO_AUTHORITY,
        reason="no_authenticated_subject",
    )


def _resolve_ineligible_subject(product_id: str) -> ProductAccessEntry:
    return _unavailable(
        product_id,
        authority=NO_AUTHORITY,
        reason="subject_not_eligible",
    )


def _resolve_with_source(
    product_id: str,
    subject: CanonicalSubjectRef,
    source: ProductAccessAuthoritySource,
    *,
    now: datetime,
) -> ProductAccessEntry:
    authority = _source_authority(source)
    # "none" is the reserved no-authority sentinel, not an attestable
    # source. An absent/malformed source.authority must NEVER be sufficient
    # to project an explicit allow or denial, even if its finding also says
    # authority="none". Refuse before reading an unidentifiable source.
    if authority == NO_AUTHORITY:
        return _unavailable(
            product_id,
            authority=NO_AUTHORITY,
            reason="authority_response_invalid",
        )
    try:
        finding = source.read_product_access(
            product_id=product_id,
            subject=subject,
            now=now,
        )
    except Exception:  # noqa: BLE001 - any source failure must fail closed
        return _unavailable(
            product_id,
            authority=authority or NO_AUTHORITY,
            reason="authority_read_failed",
        )

    if not isinstance(finding, ProductAccessFinding):
        return _unavailable(
            product_id,
            authority=authority or NO_AUTHORITY,
            reason="authority_response_invalid",
        )
    if finding.product_id != product_id:
        return _unavailable(
            product_id,
            authority=authority or NO_AUTHORITY,
            reason="authority_product_mismatch",
        )
    if finding.subject != subject:
        return _unavailable(
            product_id,
            authority=authority or NO_AUTHORITY,
            reason="authority_subject_mismatch",
        )
    if finding.authority != authority:
        return _unavailable(
            product_id,
            authority=authority or NO_AUTHORITY,
            reason="authority_response_invalid",
        )
    if finding.issued_at > now + MAX_FINDING_CLOCK_SKEW:
        return _unavailable(
            product_id,
            authority=finding.authority,
            reason="authority_not_yet_valid",
        )
    if finding.expires_at is not None and finding.expires_at <= now:
        return _unavailable(
            product_id,
            authority=finding.authority,
            reason="authority_finding_stale",
        )

    if finding.state is ProductAccessState.AVAILABLE:
        return ProductAccessEntry(
            product_id=product_id,
            access=ProductAccessState.AVAILABLE,
            authority=finding.authority,
            reason="server_allow_confirmed",
            expires_at=finding.expires_at,
        )
    if finding.state is ProductAccessState.DENIED:
        return ProductAccessEntry(
            product_id=product_id,
            access=ProductAccessState.DENIED,
            authority=finding.authority,
            reason="server_denial_confirmed",
            expires_at=finding.expires_at,
        )
    return _unavailable(
        product_id,
        authority=finding.authority,
        reason="authority_unconfirmed",
        expires_at=finding.expires_at,
    )


def _resolve_product(
    product_id: str,
    subject: CanonicalSubjectRef | None,
    sources: Mapping[str, ProductAccessAuthoritySource],
    *,
    now: datetime,
) -> ProductAccessEntry:
    if subject is None:
        return _resolve_without_subject(product_id)
    if subject.subject_type is not SubjectType.USER:
        return _resolve_ineligible_subject(product_id)

    source = sources.get(product_id)
    if source is None:
        return _unavailable(
            product_id,
            authority=NO_AUTHORITY,
            reason="no_registered_authority",
        )
    return _resolve_with_source(product_id, subject, source, now=now)


def build_product_access_projection(
    subject: CanonicalSubjectRef | None,
    *,
    product_ids: tuple[str, ...] | list[str] | None = None,
    sources: Mapping[str, ProductAccessAuthoritySource] | None = None,
    now: datetime | None = None,
) -> ProductAccessProjection:
    """Project the read-only, browser-safe per-product access answer.

    ``subject`` is the server-resolved canonical subject (``None`` for a
    guest).  ``sources`` must be supplied explicitly by a reviewed call site;
    when omitted, the shipped empty registry is used and every product is
    ``unavailable``.  Unknown or non-PADIEM product ids are refused rather
    than answered, and no failure path can produce ``available`` or
    ``denied``.
    """

    observed_at = (
        datetime.now(timezone.utc)
        if now is None
        else _aware("now", now).astimezone(timezone.utc)
    )
    if subject is not None and not isinstance(subject, CanonicalSubjectRef):
        raise _error(
            "invalid_product_access_subject",
            "subject must be CanonicalSubjectRef or None",
        )
    authority_sources = _validate_sources(sources)
    requested = _requested_products(product_ids)

    products = tuple(
        _resolve_product(
            product_id,
            subject,
            authority_sources,
            now=observed_at,
        )
        for product_id in requested
    )
    for entry in products:
        if entry.reason not in PRODUCT_ACCESS_REASONS:
            raise _error(
                "invalid_product_access_reason",
                "projected reason is outside the closed vocabulary",
            )
    return ProductAccessProjection(
        version=PRODUCT_ACCESS_PROJECTION_VERSION,
        products=products,
    )


# Read-only guarantees, asserted by the tests and by the contract doc.
PRODUCT_ACCESS_PROJECTION_MUTATES_STATE = False
PRODUCT_ACCESS_PROJECTION_GRANTS_NOTHING = True
PRODUCT_ACCESS_PROJECTION_READS_NETWORK = False
PRODUCT_ACCESS_PROJECTION_READS_ENVIRONMENT = False
PRODUCT_ACCESS_PROJECTION_AUTHORITY_REGISTRY_WIRED = False
PRODUCT_ACCESS_PROJECTION_CUSTOMER_GATE_COMPLETE = False
PRODUCT_ACCESS_PROJECTION_B66_VISIBLE = False
PRODUCT_ACCESS_PROJECTION_PC_AUTHORITY = False
PRODUCT_ACCESS_PROJECTION_P01_APPROVAL = False
