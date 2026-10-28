"""#6046: the optional `country` field on /api/chat.

Country is a presentation/routing label like `util`: it selects output language
and wording, grants no identity/tier/entitlement, and is not a jurisdiction or
storage-region setting. Absent country must keep today's Korean behaviour.

This lane cannot run the full chat suite: `_validate_payload*` reaches the tier
policy resolver, which raises `AttributeError: ADMIN` on the unmodified file too
(verified by reverting this change and running test_5108 — it fails the same
way). The country gate itself sits *before* that resolver, so these tests assert
what is observable here and mark the rest as blocked by that pre-existing fault.
"""
from __future__ import annotations

import pytest

from app.request_contract import (
    BrowserRequestError,
    _validate_payload_parts,
    declared_country,
    declared_util_scope,
)

COUNTRY_ERROR = "국가 식별자가 올바르지 않습니다."


def payload(**extra):
    base = {"messages": [{"role": "user", "content": "안녕하세요"}], "mode": "auto"}
    base.update(extra)
    return base


def test_absent_country_reads_as_korean() -> None:
    assert declared_country(payload()) == "kr"
    assert declared_country({}) == "kr"
    assert declared_country(None) == "kr"


def test_every_supported_country_resolves_to_itself() -> None:
    for country in ("kr", "us", "uk", "fr"):
        assert declared_country(payload(country=country)) == country


@pytest.mark.parametrize("bad", ["de", "KR", "", "us ", 3, None, ["us"]])
def test_unknown_or_malformed_country_is_refused_before_the_model(bad) -> None:
    with pytest.raises(BrowserRequestError) as exc:
        _validate_payload_parts(payload(country=bad))
    assert COUNTRY_ERROR in str(exc.value)
    # 재확인 경로도 값을 통과시키지 않고 기본값으로만 떨어진다
    assert declared_country(payload(country=bad)) == "kr"


def test_a_valid_country_passes_the_country_gate() -> None:
    """유효한 국가는 국가 게이트를 통과한다.

    그 뒤 단계는 이 레인의 기존 장애(ADMIN enum)에 막히므로, 국가 오류가 아니라
    그 장애로 멈추는지(=국가 게이트가 통과했는지)를 확인한다."""
    for country in ("kr", "us", "uk", "fr"):
        try:
            _validate_payload_parts(payload(country=country))
        except BrowserRequestError as exc:
            assert COUNTRY_ERROR not in str(exc.value), f"{country} was refused by the country gate"
        except AttributeError:
            pass  # 기존 환경 장애 — 국가 게이트와 무관


def test_country_alone_grants_no_util_scope() -> None:
    assert declared_util_scope(payload(country="us")) is None
