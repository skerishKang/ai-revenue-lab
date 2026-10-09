"""#3733 regression: preserve one exact customer quantity even if B14 omits it.

No provider network, billing, production mutation or final quote writes.
"""
from __future__ import annotations

import json

import pytest

from app.b66_quote_conversation import B66QuoteConversationInterpreter


class OneAnswer:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        return {"answer": json.dumps({
            "recipient": {"company": "대한건설"},
            "items": self.items,
            "taxMode": "EXCLUSIVE",
            "missing": [],  # not authoritative
        }, ensure_ascii=False)}


def skill():
    return {
        "variableSchema": {"recipient": True, "items": True, "taxMode": True},
        "fixedDefaults": {"taxMode": "EXCLUSIVE"},
    }


@pytest.mark.asyncio
async def test_live_partial_exact_quantity_is_preserved_without_inventing_price():
    model = OneAnswer([{"name": "배관", "unit": "미터"}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message="대한건설에 배관 100미터, 부가세 별도",
        skill=skill(),
        model_id="google/gemini-3.5-flash-lite",
    )
    assert model.calls == 1
    assert quote.result_origin == "registered_model_completion"
    assert quote.items[0]["qty"] == 100
    assert quote.items[0]["unit"] == "미터"
    assert "unitPrice" not in quote.items[0]
    assert quote.missing == ("unitPrice",)


@pytest.mark.parametrize("text", [
    "대한건설에 배관 약 100미터, 부가세 별도",
    "대한건설에 배관 대충 100미터 정도, 부가세 별도",
    "대한건설에 배관 100미터 내외, 부가세 별도",
    "대한건설에 배관 100~120미터, 부가세 별도",
    "대한건설에 배관 한 100미터쯤, 부가세 별도",
])
@pytest.mark.asyncio
async def test_estimates_and_ranges_are_never_promoted_to_exact_quantity(text):
    model = OneAnswer([{"name": "배관", "qty": 100}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message=text, skill=skill(),
    )
    assert quote.items[0].get("qty") is None
    assert "qty" in quote.missing


@pytest.mark.asyncio
async def test_conflicting_model_quantity_is_rejected_not_replaced():
    model = OneAnswer([{"name": "배관", "qty": 200, "unitPrice": 18000}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message="대한건설에 배관 100미터, 미터당 18000원",
        skill=skill(),
    )
    assert quote.items[0].get("qty") is None
    assert quote.missing == ("qty",)
    assert quote.items[0]["unitPrice"] == 18000


@pytest.mark.asyncio
async def test_complete_customer_number_stays_unchanged():
    model = OneAnswer([{"name": "배관", "qty": 100, "unitPrice": 18000}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message="대한건설에 배관 100미터, 미터당 18000원",
        skill=skill(),
    )
    assert quote.missing == ()
    assert quote.items[0]["qty"] == 100


@pytest.mark.asyncio
async def test_unknown_item_name_is_not_deduced_by_nearby_number():
    model = OneAnswer([{"name": "밸브"}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message="대한건설에 배관 100미터, 부가세 별도",
        skill=skill(),
    )
    assert "qty" in quote.missing
    assert quote.items[0].get("qty") is None


@pytest.mark.parametrize("message", [
    "대한건설에 배관 100mL, 부가세 별도",
    "대한건설에 배관 100미터와 밸브 5개, 부가세 별도",
    "대한건설에 배관 100미터, 밸브 5개, 부가세 별도",
])
@pytest.mark.asyncio
async def test_unsafe_unit_prefix_or_multiple_quantity_candidates_remain_missing(message):
    model = OneAnswer([{"name": "배관"}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message=message, skill=skill(),
    )
    assert quote.items[0].get("qty") is None
    assert "qty" in quote.missing


@pytest.mark.asyncio
async def test_multiple_items_never_receive_automatically_assigned_quantities():
    model = OneAnswer([{"name": "배관"}, {"name": "밸브"}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message="대한건설에 배관 100미터, 밸브 5개",
        skill=skill(),
    )
    assert all("qty" not in item for item in quote.items)
    assert "qty" in quote.missing


@pytest.mark.asyncio
async def test_later_customer_correction_never_overwritten_by_first_utterance():
    model = OneAnswer([{"name": "배관", "qty": 120, "unitPrice": 18000}])
    quote = await B66QuoteConversationInterpreter(model).interpret(
        message=(
            "대한건설에 배관 100미터, 부가세 별도\n"
            "추가 질문: 최종 수량은 몇 미터인가요?\n답변: 120미터"
        ),
        skill=skill(),
    )
    assert quote.items[0]["qty"] == 120
    assert quote.missing == ()
