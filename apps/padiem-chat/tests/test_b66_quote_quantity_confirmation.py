"""#3916: approximate quantities are NOT finalized from model numeric guesses."""
from __future__ import annotations

import json

import pytest

from app.b66_quote_conversation import B66QuoteConversationInterpreter


def _skill():
    return {
        "fixedDefaults": {"taxMode": "EXCLUSIVE"},
        "variableSchema": {"recipient": True, "items": True, "taxMode": True},
    }


class _FixedModel:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        return {
            "answer": json.dumps(
                {
                    "recipient": {"company": "대한건설"},
                    "items": self.items,
                    "taxMode": "EXCLUSIVE",
                    "missing": [],  # untrusted advisory metadata
                },
                ensure_ascii=False,
            )
        }


@pytest.mark.parametrize(
    ("message", "qty"),
    [
        ("대한건설 배관 약 100개, 단가 2000원", 100),
        ("대한건설 배관 대충 100개 정도, 단가 2000원", 100),
        ("대한건설 배관 100개 내외, 단가 2000원", 100),
        ("대한건설 배관 100~120개, 단가 2000원", 100),
        ("대한건설 배관 100~120개, 단가 2000원", 110),
        ("대한건설 배관 한 100개쯤, 단가 2000원", 100),
        ("대한건설 배관 약 100미터, 단가 2000원", 100),
    ],
)
@pytest.mark.asyncio
async def test_approximate_source_qty_is_removed_from_final_facts(message, qty):
    provider = _FixedModel([{"name": "배관", "qty": qty, "unitPrice": 2000}])
    projection = await B66QuoteConversationInterpreter(provider).interpret(
        message=message, skill=_skill(), model_id="test/selected-model"
    )
    assert provider.calls == 1
    assert projection.result_origin == "registered_model_completion"
    assert projection.safe_dict()["items"] == [{"name": "배관", "unitPrice": 2000}]
    assert projection.missing == ("qty",)
    assert "confirmed" not in json.dumps(projection.safe_dict())


@pytest.mark.parametrize("message", [
    "대한건설 배관 정확히 100개, 단가 2000원",
    "대한건설 배관 100개, 단가 2000원",
])
@pytest.mark.asyncio
async def test_exact_quantity_stays_finalizable(message):
    provider = _FixedModel([{"name": "배관", "qty": 100, "unitPrice": 2000}])
    result = await B66QuoteConversationInterpreter(provider).interpret(
        message=message, skill=_skill()
    )
    assert result.missing == ()
    assert result.items[0]["qty"] == 100


@pytest.mark.asyncio
async def test_confirmed_followup_quantity_must_be_numeric_and_match_output():
    first = "대한건설 배관 대충 100개 정도, 단가 2000원"
    question = "\n추가 질문: 최종 수량을 숫자와 단위로 알려 주세요.\n답변: "
    for reply, model_qty, expected in [
        ("네", 100, None),             # bare yes is not numeric confirmation
        ("100개", 100, 100),          # explicit original estimate
        ("120개 확정", 120, 120),     # user corrects the estimate
        ("120개 확정", 100, None),    # model incorrectly kept old number
        ("120개 정도", 120, None),    # second estimate is still not final
    ]:
        model = _FixedModel([{"name": "배관", "qty": model_qty, "unitPrice": 2000}])
        result = await B66QuoteConversationInterpreter(model).interpret(
            message=first + question + reply, skill=_skill()
        )
        assert result.items[0].get("qty") == expected
        assert ("qty" in result.missing) is (expected is None)


@pytest.mark.asyncio
async def test_confirmed_reply_survives_later_price_followup():
    message = (
        "대한건설 배관 약 100개\n"
        "추가 질문: 최종 수량은?\n답변: 120개\n"
        "추가 질문: 단가는?\n답변: 개당 2000원"
    )
    model = _FixedModel([{"name": "배관", "qty": 120, "unitPrice": 2000}])
    result = await B66QuoteConversationInterpreter(model).interpret(
        message=message, skill=_skill()
    )
    assert result.missing == ()
    assert result.items[0]["qty"] == 120


@pytest.mark.asyncio
async def test_multi_item_guard_preserves_unrelated_exact_quantities():
    original = "대한건설 배관 약 100개, 밸브 정확히 5개 단가 2000원"
    model = _FixedModel([
        {"name": "배관", "qty": 100, "unitPrice": 2000},
        {"name": "밸브", "qty": 5, "unitPrice": 2000},
    ])
    interpreter = B66QuoteConversationInterpreter(model)
    first = await interpreter.interpret(message=original, skill=_skill())
    assert first.items[0].get("qty") is None
    assert first.items[1]["qty"] == 5
    assert first.missing == ("qty",)

    # When a customer supplies a different exact figure, do not wipe out the
    # separate confirmed item merely because the estimate was originally 100.
    confirmed = _FixedModel([
        {"name": "배관", "qty": 120, "unitPrice": 2000},
        {"name": "밸브", "qty": 5, "unitPrice": 2000},
    ])
    second = await B66QuoteConversationInterpreter(confirmed).interpret(
        message=original + "\n추가 질문: 배관 최종 수량은?\n답변: 120개",
        skill=_skill(),
    )
    assert [item["qty"] for item in second.items] == [120, 5]
    assert second.missing == ()


@pytest.mark.asyncio
async def test_approximate_price_and_tax_are_not_invented_during_qty_confirmation():
    model = _FixedModel([{"name": "배관", "qty": 100}])
    result = await B66QuoteConversationInterpreter(model).interpret(
        message="대한건설 배관 대충 100개 정도, 가격은 적당히",
        skill=_skill(),
    )
    item = result.safe_dict()["items"][0]
    assert "qty" not in item
    assert "unitPrice" not in item
    assert result.missing == ("qty", "unitPrice")
