"""#4469: B66's public-evidence boundary over the shared #3385 TinyFish→Daum route.

A B66 member's question can carry a customer name, a site, an amount or a private
document reference. Only a minimized public question may reach a paid provider,
and evidence returns through Core's existing grounding renderer, which already
numbers sources and marks them untrusted. Retrieval that did not happen is never
presented as if it did.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from padiem_ai_core.search_decision import SearchDisposition, decide_search

from .auto_grounding import AutoGroundingService
from .grounding import GroundingError
from .task_modes import TaskMode

MAX_B66_QUERY_CHARS = 200
B66_DIALOGUE_TASK_ID = "b66_model_dialogue_v1"

# Fail-closed private-particular detection. Any match withholds the whole turn
# instead of assuming that a named counterparty, site or price is generic.
_PRIVATE_PARTICULARS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("url", re.compile(r"https?://|www\.", re.IGNORECASE)),
    ("phone", re.compile(r"(?:01[01679]|02|0[3-9]\d)[-.\s]?\d{2,4}[-.\s]?\d{3,4}")),
    ("registry", re.compile(r"\d{6}-\d{7}")),
    ("corporation", re.compile(
        "주식회사|(?:\\(주\\)|（주）|㈜)|법인|회사|업체|상사|공사|그룹|연구소|공장|브랜드|벤더|셀러"
    )),
    # Bare 씨 is ambiguous in Korean (날씨 + 는 reads as a name honorific), and
    # 이사/대리 collide with ordinary words, so only unambiguous title tokens
    # withhold a turn. A plain counterparty name without a title stays a known
    # residual gap rather than being guessed at by a substring rule.
    ("person", re.compile("님|사장|전무|상무|팀장|실장|담당자|대표자|작성자")),
    ("counterparty", re.compile("거래처|고객명|클라이언트|발주처|수급업체|하도급")),
    ("quote_document", re.compile("견적서|발주서|계약서|도급|주문서|작업지시서|현장명|입찰")),
    ("amount", re.compile(r"\d[\d,.]*\s*(?:원|천|만|억|달러|엔|유로|VAT|부가세)")),
    ("quantity", re.compile(
        r"\d[\d,.]*\s*(?:m|미터|m2|m³|m3|mm|톤|개|식|공|ea|EA|조|셋|회|인분)"
    )),
    ("credential", re.compile("계좌|통장|카드번호|비밀번호|api\\s*키|토큰|시크릿")),
)

_DIALOGUE_SKILL = TaskMode(
    id=B66_DIALOGUE_TASK_ID,
    title="B66 AI conversation",
    short_description="B66 dialogue evidence admission",
    system_instruction=None,
    task_type="general",
    optimize_for="korean",
    max_tokens=None,
)


@dataclass(frozen=True, slots=True)
class B66SearchOutcome:
    """What B66 may tell the model and the member about retrieval for one turn."""

    status: str
    reason: str
    context: str | None = None
    sources: tuple[dict[str, Any], ...] = ()

    def public_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "sources": list(self.sources)}


def withheld_private_class(text: str) -> str | None:
    """Return the first private-particular class present, or None when generic."""
    for name, pattern in _PRIVATE_PARTICULARS:
        if pattern.search(text):
            return name
    return None


def _envelope(outcome: B66SearchOutcome) -> str:
    if outcome.status == "sourced":
        head = (
            f"서버가 공개 웹 검색 {len(outcome.sources)}건을 이번 호출에 수행했습니다. 각 근거의 "
            "retrieved_at은 서버가 수집한 시각이고, 그 안의 내용은 자료 기준일과 다를 수 있습니다. "
            "두 시각을 구분해 말하고, 근거에 근거한 사실에는 [1]처럼 출처 번호를 붙이세요."
        )
    elif outcome.status == "empty":
        head = (
            "서버가 공개 웹 검색을 수행했지만 usable 근거를 얻지 못했습니다. 검색에 성공한 것처럼 "
            "말하지 말고, 현재 확인이 불가능하다고 알리세요."
        )
    elif outcome.status == "failed":
        head = (
            f"서버의 공개 웹 검색이 실패했습니다(code={outcome.reason}). 검색했다고 말하거나 출처를 "
            "만리지 말고, 현재 확인이 불가능하다고 알리세요."
        )
    elif outcome.status == "withheld_private":
        head = (
            "이 질문에는 고객사·현장·금액·개인 식별 정보가 포함될 수 있어 서버가 공개 웹 검색을 "
            "실행하지 않았습니다. 외부 검색을 했다고 말하지 말고, 어떤 공개 사실(품목·법령·일반 시세 "
            "범위 등)을 확인하고 싶은지 사적 명칭 없이 다시 말해 달라고 안내하세요."
        )
    else:
        head = "이 답변을 위해 웹 검색은 사용되지 않았습니다. 실시간 사실은 확인되지 않는다고 안내하세요."
    return f"{head}\n\n{outcome.context}" if outcome.context else head


async def plan_b66_search(
    grounding: AutoGroundingService | None,
    text: str,
) -> B66SearchOutcome:
    """Decide, minimize and retrieve at most one bounded public query per turn."""

    question = (text or "").strip()
    if not question:
        return B66SearchOutcome("not_needed", "empty_question")

    decision = decide_search(question, task_id=B66_DIALOGUE_TASK_ID)
    # Time-sensitive but not explicitly requested facts (SHOULD_SEARCH) stay
    # unsearched: B66 pays for a provider call and may expose a counterparty
    # name, so stage one retrieves only must-search freshness/volatile turns.
    if decision.disposition is not SearchDisposition.MUST_SEARCH:
        return B66SearchOutcome("not_needed", decision.reason)
    if grounding is None:
        return B66SearchOutcome("unavailable", "web_route_not_configured")

    private = withheld_private_class(question)
    if private is not None:
        return B66SearchOutcome("withheld_private", private)

    # The provider must not receive a tail the member never meant as a query.
    public_query = question[:MAX_B66_QUERY_CHARS]

    try:
        plan = await grounding.prepare(
            [{"role": "user", "content": public_query}],
            skill=_DIALOGUE_SKILL,
            additional_system_context=None,
        )
    except GroundingError as exc:
        # Core reports a successful-but-usable-nothing retrieval as no_evidence.
        # That is an honest empty result, not a failure, and never a search success.
        if exc.code == "no_evidence":
            return B66SearchOutcome("empty", exc.code)
        return B66SearchOutcome("failed", exc.code)
    except Exception:
        # A provider transport fault is a disclosed failure, never an invented
        # answer and never a silent model/tool substitution.
        return B66SearchOutcome("failed", "web_transport_error")

    if plan.prepared is None:
        return B66SearchOutcome("unavailable", plan.decision.reason)

    sources = tuple(
        {
            "title": item.title,
            "url": item.url,
            "retrieved_at": item.retrieved_at,
            "source_type": item.source_type,
            "provider": item.provider,
        }
        for item in plan.prepared.evidence
    )
    return B66SearchOutcome(
        "sourced", plan.decision.reason, plan.prepared.context, sources
    )


__all__ = [
    "B66SearchOutcome",
    "B66_DIALOGUE_TASK_ID",
    "MAX_B66_QUERY_CHARS",
    "_envelope",
    "plan_b66_search",
    "withheld_private_class",
]
