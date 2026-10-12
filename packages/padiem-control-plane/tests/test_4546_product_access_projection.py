"""Read-only per-product access projection contract tests (#4546).

These tests verify the *contract mechanics* with explicitly injected synthetic
authority sources.  They deliberately do **not** assert that any real PADIEM
product is ``available`` or ``denied``: no verified product-access authority
exists yet, so the shipped default projection must answer ``unavailable`` for
every product.  Real product-truth tests belong to the reviewed central
integration that wires an authority source.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path

import pytest

from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from padiem_control_plane.product_access_projection import (
    MAX_PRODUCT_ACCESS_ITEMS,
    NO_AUTHORITY,
    PADIEM_CHAT_PRODUCT_ID,
    PADIEM_CLAW_PRODUCT_ID,
    PADIEM_HOME_PRODUCT_IDS,
    PRODUCT_ACCESS_AUTHORITY_SOURCES,
    PRODUCT_ACCESS_ENTRY_BROWSER_KEYS,
    PRODUCT_ACCESS_PROJECTION_AUTHORITY_REGISTRY_WIRED,
    PRODUCT_ACCESS_PROJECTION_B66_VISIBLE,
    PRODUCT_ACCESS_PROJECTION_CUSTOMER_GATE_COMPLETE,
    PRODUCT_ACCESS_PROJECTION_GRANTS_NOTHING,
    PRODUCT_ACCESS_PROJECTION_MUTATES_STATE,
    PRODUCT_ACCESS_PROJECTION_P01_APPROVAL,
    PRODUCT_ACCESS_PROJECTION_PC_AUTHORITY,
    PRODUCT_ACCESS_PROJECTION_READS_ENVIRONMENT,
    PRODUCT_ACCESS_PROJECTION_READS_NETWORK,
    PRODUCT_ACCESS_RESPONSE_HEADERS,
    PRODUCT_ACCESS_PROJECTION_VERSION,
    ProductAccessContractError,
    ProductAccessFinding,
    ProductAccessState,
    build_product_access_projection,
)


MODULE_PATH = Path(inspect.getfile(build_product_access_projection))
MODULE_SOURCE = MODULE_PATH.read_text(encoding="utf-8")
# The scan covers the contract code only; the trailing guarantee constants are
# asserted directly as booleans further down.
SCANNED_SOURCE = MODULE_SOURCE.split("# Read-only guarantees", 1)[0]
CONTRACT_DOC = (
    MODULE_PATH.parents[3]
    / "docs"
    / "architecture"
    / "PADIEM_PRODUCT_ACCESS_PROJECTION_4546_20261013.md"
)

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


def _subject(subject_id: str = "usr_canonical_a") -> CanonicalSubjectRef:
    return CanonicalSubjectRef(
        subject_type=SubjectType.USER,
        subject_id=subject_id,
    )


def _finding(
    product_id: str = PADIEM_CHAT_PRODUCT_ID,
    subject: CanonicalSubjectRef | None = None,
    state: ProductAccessState = ProductAccessState.AVAILABLE,
    *,
    authority: str = "cp-product-access-v1",
    issued_at: datetime = NOW - timedelta(minutes=1),
    expires_at: datetime | None = NOW + timedelta(hours=1),
) -> ProductAccessFinding:
    return ProductAccessFinding(
        product_id=product_id,
        subject=subject if subject is not None else _subject(),
        state=state,
        authority=authority,
        issued_at=issued_at,
        expires_at=expires_at,
    )


class _Source:
    """Synthetic authority source; never promoted to product truth."""

    def __init__(
        self,
        authority: str = "cp-product-access-v1",
        *,
        finding: ProductAccessFinding | None = None,
        error: Exception | None = None,
    ) -> None:
        self.authority = authority
        self._finding = finding
        self._error = error
        self.calls: list[dict[str, object]] = []

    def read_product_access(
        self,
        *,
        product_id: str,
        subject: CanonicalSubjectRef,
        now: datetime,
    ) -> ProductAccessFinding:
        self.calls.append(
            {"product_id": product_id, "subject": subject, "now": now}
        )
        if self._error is not None:
            raise self._error
        # Returns whatever was configured, including malformed values: the
        # projection is what must refuse them, not the test double.
        return self._finding


class _SubjectKeyedSource:
    """Allows exactly one subject, denies everyone else."""

    authority = "cp-product-access-v1"

    def __init__(self, allowed_subject_id: str) -> None:
        self.allowed_subject_id = allowed_subject_id

    def read_product_access(
        self,
        *,
        product_id: str,
        subject: CanonicalSubjectRef,
        now: datetime,
    ) -> ProductAccessFinding:
        state = (
            ProductAccessState.AVAILABLE
            if subject.subject_id == self.allowed_subject_id
            else ProductAccessState.DENIED
        )
        return ProductAccessFinding(
            product_id=product_id,
            subject=subject,
            state=state,
            authority=self.authority,
            issued_at=now - timedelta(seconds=30),
            expires_at=now + timedelta(hours=1),
        )


def test_shipped_authority_registry_is_empty_and_nothing_is_available() -> None:
    assert dict(PRODUCT_ACCESS_AUTHORITY_SOURCES) == {}
    assert PRODUCT_ACCESS_PROJECTION_AUTHORITY_REGISTRY_WIRED is False
    assert PRODUCT_ACCESS_PROJECTION_CUSTOMER_GATE_COMPLETE is False

    projection = build_product_access_projection(_subject(), now=NOW)
    payload = projection.to_browser_dict()

    assert payload["version"] == PRODUCT_ACCESS_PROJECTION_VERSION
    assert projection.available_product_ids == ()
    assert [entry["product_id"] for entry in payload["products"]] == list(
        PADIEM_HOME_PRODUCT_IDS
    )
    for entry in payload["products"]:
        assert entry["access"] == "unavailable"
        assert entry["authority"] == NO_AUTHORITY
        assert entry["reason"] == "no_registered_authority"


def test_logged_out_subject_never_receives_available() -> None:
    allow = _Source(finding=_finding())
    projection = build_product_access_projection(
        None,
        sources={PADIEM_CHAT_PRODUCT_ID: allow},
        now=NOW,
    )

    assert projection.available_product_ids == ()
    assert allow.calls == []
    for entry in projection.products:
        assert entry.access is ProductAccessState.UNAVAILABLE
        assert entry.reason == "no_authenticated_subject"


@pytest.mark.parametrize(
    "subject_type",
    [SubjectType.ANONYMOUS, SubjectType.ACCOUNT],
)
def test_non_user_subject_is_not_eligible(subject_type: SubjectType) -> None:
    allow = _Source(finding=_finding())
    projection = build_product_access_projection(
        CanonicalSubjectRef(subject_type=subject_type, subject_id="usr_x"),
        sources={PADIEM_CHAT_PRODUCT_ID: allow},
        now=NOW,
    )

    assert projection.available_product_ids == ()
    assert allow.calls == []
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)
    assert entry is not None
    assert entry.access is ProductAccessState.UNAVAILABLE
    assert entry.reason == "subject_not_eligible"


@pytest.mark.parametrize("subject", ["usr_canonical_a", {"subject_id": "usr_a"}, 7])
def test_a_non_subject_argument_is_refused(subject: object) -> None:
    with pytest.raises(ProductAccessContractError) as excinfo:
        build_product_access_projection(subject, now=NOW)  # type: ignore[arg-type]
    assert excinfo.value.code == "invalid_product_access_subject"


def test_user_a_and_user_b_are_isolated() -> None:
    source = _SubjectKeyedSource("usr_canonical_a")

    for_a = build_product_access_projection(
        _subject("usr_canonical_a"),
        sources={PADIEM_CHAT_PRODUCT_ID: source},
        now=NOW,
    )
    for_b = build_product_access_projection(
        _subject("usr_canonical_b"),
        sources={PADIEM_CHAT_PRODUCT_ID: source},
        now=NOW,
    )

    assert for_a.entry_for(PADIEM_CHAT_PRODUCT_ID).access is (
        ProductAccessState.AVAILABLE
    )
    assert for_b.entry_for(PADIEM_CHAT_PRODUCT_ID).access is (
        ProductAccessState.DENIED
    )


def test_explicit_current_allow_is_projected_as_available() -> None:
    finding = _finding(
        expires_at=NOW + timedelta(hours=2),
    )
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(finding=finding)},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)
    payload = projection.to_browser_dict()["products"][0]

    assert entry.access is ProductAccessState.AVAILABLE
    assert entry.reason == "server_allow_confirmed"
    assert entry.authority == "cp-product-access-v1"
    assert payload["expires_at"] == (NOW + timedelta(hours=2)).isoformat()


def test_explicit_denial_is_projected_as_denied_only_with_authority() -> None:
    finding = _finding(state=ProductAccessState.DENIED)
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(finding=finding)},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)

    assert entry.access is ProductAccessState.DENIED
    assert entry.reason == "server_denial_confirmed"
    assert entry.authority == "cp-product-access-v1"


def test_unset_product_authority_is_unavailable_not_denied() -> None:
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(finding=_finding())},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CLAW_PRODUCT_ID)

    assert entry.access is ProductAccessState.UNAVAILABLE
    assert entry.reason == "no_registered_authority"
    assert entry.authority == NO_AUTHORITY


def test_a_finding_without_expiry_is_accepted() -> None:
    projection = build_product_access_projection(
        _subject(),
        sources={
            PADIEM_CHAT_PRODUCT_ID: _Source(
                finding=_finding(expires_at=None)
            )
        },
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)
    payload = projection.to_browser_dict()["products"][0]

    assert entry.access is ProductAccessState.AVAILABLE
    assert "expires_at" not in payload


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("authority unavailable"),
        ProductAccessContractError("authority_read_failed", "boom"),
        TimeoutError("authority timed out"),
    ],
)
def test_authority_source_failure_is_unavailable(error: Exception) -> None:
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(error=error)},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)

    assert entry.access is ProductAccessState.UNAVAILABLE
    assert entry.reason == "authority_read_failed"
    assert entry.access is not ProductAccessState.AVAILABLE
    assert entry.access is not ProductAccessState.DENIED


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (None, "authority_response_invalid"),
        ({"product_id": PADIEM_CHAT_PRODUCT_ID}, "authority_response_invalid"),
        (
            _finding(product_id=PADIEM_CLAW_PRODUCT_ID),
            "authority_product_mismatch",
        ),
        (
            _finding(subject=_subject("usr_canonical_b")),
            "authority_subject_mismatch",
        ),
        (
            _finding(authority="cp-someone-elses-authority"),
            "authority_response_invalid",
        ),
    ],
)
def test_malformed_authority_response_is_unavailable(
    raw: object, reason: str
) -> None:
    source = _Source(finding=_finding())
    source._finding = raw  # type: ignore[assignment]
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: source},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)

    assert entry.access is ProductAccessState.UNAVAILABLE
    assert entry.reason == reason


def test_stale_allow_is_never_projected_as_available() -> None:
    stale = _finding(expires_at=NOW - timedelta(seconds=1))
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(finding=stale)},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)

    assert entry.access is ProductAccessState.UNAVAILABLE
    assert entry.reason == "authority_finding_stale"


def test_premature_finding_is_never_projected_as_available() -> None:
    premature = _finding(
        issued_at=NOW + timedelta(hours=6),
        expires_at=NOW + timedelta(hours=12),
    )
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(finding=premature)},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)

    assert entry.access is ProductAccessState.UNAVAILABLE
    assert entry.reason == "authority_not_yet_valid"


def test_an_allow_expires_on_the_next_read() -> None:
    source = _Source(finding=_finding(expires_at=NOW + timedelta(minutes=30)))

    before = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: source},
        now=NOW,
    )
    after = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: source},
        now=NOW + timedelta(minutes=31),
    )

    assert before.entry_for(PADIEM_CHAT_PRODUCT_ID).access is (
        ProductAccessState.AVAILABLE
    )
    assert after.entry_for(PADIEM_CHAT_PRODUCT_ID).access is (
        ProductAccessState.UNAVAILABLE
    )
    assert after.entry_for(PADIEM_CHAT_PRODUCT_ID).reason == (
        "authority_finding_stale"
    )


def test_source_reported_unavailable_keeps_its_provenance() -> None:
    finding = _finding(state=ProductAccessState.UNAVAILABLE)
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(finding=finding)},
        now=NOW,
    )
    entry = projection.entry_for(PADIEM_CHAT_PRODUCT_ID)

    assert entry.access is ProductAccessState.UNAVAILABLE
    assert entry.reason == "authority_unconfirmed"
    assert entry.authority == "cp-product-access-v1"


@pytest.mark.parametrize(
    "product_id",
    [
        "padiem-engine",
        "engine",
        "padiem_engine",
        "b63",
        "b66",
        "b66-quote",
        "chat",
        "claw",
        "",
        "b62 ",
    ],
)
def test_unknown_product_request_is_refused(product_id: str) -> None:
    with pytest.raises(ProductAccessContractError) as excinfo:
        build_product_access_projection(
            _subject(),
            product_ids=(product_id,),
            now=NOW,
        )
    assert excinfo.value.code == "unknown_product_id"


def test_only_the_two_canonical_padiem_products_are_requestable() -> None:
    assert PADIEM_HOME_PRODUCT_IDS == (PADIEM_CHAT_PRODUCT_ID, PADIEM_CLAW_PRODUCT_ID)
    assert PADIEM_CHAT_PRODUCT_ID == "b62"
    assert PADIEM_CLAW_PRODUCT_ID == "b54-padiem-claw"


@pytest.mark.parametrize(
    "product_ids",
    [
        "b62",
        42,
        ("b62", 7),
        ("b62", "unknown-product"),
    ],
)
def test_invalid_product_id_shapes_are_refused(product_ids: object) -> None:
    with pytest.raises(ProductAccessContractError):
        build_product_access_projection(
            _subject(),
            product_ids=product_ids,  # type: ignore[arg-type]
            now=NOW,
        )


def test_duplicate_requests_are_deduplicated_and_bounded() -> None:
    projection = build_product_access_projection(
        _subject(),
        product_ids=(PADIEM_CHAT_PRODUCT_ID, PADIEM_CHAT_PRODUCT_ID),
        now=NOW,
    )
    assert len(projection.products) == 1

    too_many = (PADIEM_CHAT_PRODUCT_ID, PADIEM_CLAW_PRODUCT_ID) * 5
    with pytest.raises(ProductAccessContractError) as excinfo:
        build_product_access_projection(
            _subject(),
            product_ids=too_many,
            now=NOW,
        )
    assert excinfo.value.code == "product_access_request_too_large"


def test_an_empty_product_request_is_refused() -> None:
    with pytest.raises(ProductAccessContractError) as excinfo:
        build_product_access_projection(
            _subject(),
            product_ids=(),
            now=NOW,
        )
    assert excinfo.value.code == "invalid_product_access_request"


def test_source_registered_for_an_unknown_product_is_refused() -> None:
    with pytest.raises(ProductAccessContractError) as excinfo:
        build_product_access_projection(
            _subject(),
            sources={"b66": _Source(finding=_finding())},  # type: ignore[dict-item]
            now=NOW,
        )
    assert excinfo.value.code == "unknown_product_id"


def test_workspace_or_tenant_fact_cannot_reach_the_browser_payload() -> None:
    finding = _finding()
    projection = build_product_access_projection(
        _subject(),
        sources={PADIEM_CHAT_PRODUCT_ID: _Source(finding=finding)},
        now=NOW,
    )
    payload = projection.to_browser_dict()
    serialized = json.dumps(payload).lower()

    assert set(payload) == {"version", "products"}
    for entry in payload["products"]:
        assert set(entry) <= PRODUCT_ACCESS_ENTRY_BROWSER_KEYS
    for forbidden in (
        "tenant",
        "workspace",
        "owner",
        "session",
        "subject_id",
        "email",
        "secret",
        "token",
        "credential",
        "b66",
        "membership",
        "role",
        "plan",
        "subscription",
        "credit",
        "p01",
        "dispatch",
        "broker",
        "device",
    ):
        assert forbidden not in serialized


def test_browser_payload_is_json_safe_and_ordered() -> None:
    projection = build_product_access_projection(
        _subject(),
        sources={
            PADIEM_CHAT_PRODUCT_ID: _Source(finding=_finding()),
        },
        product_ids=(
            PADIEM_CLAW_PRODUCT_ID,
            PADIEM_CHAT_PRODUCT_ID,
            PADIEM_CLAW_PRODUCT_ID,
        ),
        now=NOW,
    )
    payload = projection.to_browser_dict()

    assert json.loads(json.dumps(payload)) == payload
    assert [entry["product_id"] for entry in payload["products"]] == [
        PADIEM_CLAW_PRODUCT_ID,
        PADIEM_CHAT_PRODUCT_ID,
    ]
    assert payload["version"] == "product-access-projection-v1"


def test_access_values_stay_inside_the_closed_taxonomy() -> None:
    projection = build_product_access_projection(
        _subject(),
        sources={
            PADIEM_CHAT_PRODUCT_ID: _Source(finding=_finding()),
            PADIEM_CLAW_PRODUCT_ID: _Source(
                finding=_finding(
                    product_id=PADIEM_CLAW_PRODUCT_ID,
                    state=ProductAccessState.DENIED,
                )
            ),
        },
        now=NOW,
    )
    payload = projection.to_browser_dict()

    allowed = {state.value for state in ProductAccessState}
    assert {entry["access"] for entry in payload["products"]} <= allowed
    assert len(allowed) == 3


def test_projection_accepts_no_role_membership_or_workspace_argument() -> None:
    parameters = set(
        inspect.signature(build_product_access_projection).parameters
    )
    assert parameters == {"subject", "product_ids", "sources", "now"}

    finding_fields = set(ProductAccessFinding.__dataclass_fields__)
    assert finding_fields == {
        "product_id",
        "subject",
        "state",
        "authority",
        "issued_at",
        "expires_at",
    }


def test_projection_is_read_only_and_mints_no_authority() -> None:
    assert PRODUCT_ACCESS_PROJECTION_MUTATES_STATE is False
    assert PRODUCT_ACCESS_PROJECTION_GRANTS_NOTHING is True
    assert PRODUCT_ACCESS_PROJECTION_READS_NETWORK is False
    assert PRODUCT_ACCESS_PROJECTION_READS_ENVIRONMENT is False
    assert PRODUCT_ACCESS_PROJECTION_PC_AUTHORITY is False
    assert PRODUCT_ACCESS_PROJECTION_P01_APPROVAL is False
    assert PRODUCT_ACCESS_PROJECTION_B66_VISIBLE is False

    imports = {
        line.split()[1]
        for line in MODULE_SOURCE.splitlines()
        if line.startswith("from .")
    }
    assert imports == {".contracts"}

    for forbidden in (
        "def grant",
        "grant_access",
        "install_entitlement_snapshot",
        "establish_auth_session",
        "create_tenant",
        "assign_tenant_membership",
        "resolve_active_memberships",
        "evaluate_pc_access",
        "pc_dispatch_requirements",
        "produce_authenticated_user_engine_entitlement",
    ):
        assert forbidden not in SCANNED_SOURCE

    for forbidden in (
        "fetch(",
        "xmlhttprequest",
        "os.environ",
        "subprocess",
        "socket",
        "open(",
        "sqlite",
        "insert into",
        "update ",
        "delete from",
        "p01",
        "dispatch",
        "broker",
        "device",
    ):
        assert forbidden not in SCANNED_SOURCE.lower()


def test_read_only_route_headers_are_declared() -> None:
    assert dict(PRODUCT_ACCESS_RESPONSE_HEADERS) == {
        "cache-control": "no-store"
    }


def test_contract_document_declares_the_feature_off_state() -> None:
    assert CONTRACT_DOC.exists()
    document = CONTRACT_DOC.read_text(encoding="utf-8")
    assert "PRODUCT_ACCESS_PROJECTION_CONTRACT=IMPLEMENTED" in document
    assert "AUTHORITY_WIRED=NO" in document
    assert "CUSTOMER_HOME_ACCESS_GATE=UNVERIFIED" in document
    assert "no_registered_authority" in document


def test_contract_error_is_a_control_plane_contract_error() -> None:
    error = ProductAccessContractError("unknown_product_id", "refused")
    assert isinstance(error, ControlPlaneContractError)
    assert error.code == "unknown_product_id"
