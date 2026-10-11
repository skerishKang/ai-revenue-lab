from __future__ import annotations

import pytest

from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.b66_quote_deterministic_fallback import parse_b66_mvp_fallback


def _skill():
    return {
        "fixedDefaults": {"taxMode": "EXCLUSIVE"},
        "variableSchema": {
            "recipient": True,
            "quoteNo": True,
            "issueDate": True,
            "items": True,
            "memo": True,
            "taxMode": True,
        },
    }


class _ProviderServerError(RuntimeError):
    code = "provider_server_error"


class _FailingClient:
    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


def test_fallback_extracts_complete_cgi_smoke_shape():
    raw = parse_b66_mvp_fallback(
        "대한건설에 배관 100미터, 미터당 18,000원, 부가세 별도"
    )
    assert raw == {
        "recipient": {"company": "대한건설"},
        "items": [
            {"name": "배관", "qty": 100, "unit": "미터", "unitPrice": 18000}
        ],
        "missing": [],
        "taxMode": "EXCLUSIVE",
    }


def test_fallback_preserves_partial_item_without_guessing_price():
    raw = parse_b66_mvp_fallback("대한건설에 배관 100미터, 부가세 별도")
    assert raw == {
        "recipient": {"company": "대한건설"},
        "items": [{"name": "배관", "qty": 100, "unit": "미터"}],
        "missing": [],
        "taxMode": "EXCLUSIVE",
    }


def test_fallback_accepts_pending_followup_price_on_second_line():
    raw = parse_b66_mvp_fallback(
        "대한건설에 배관 100미터, 부가세 별도\n미터당 18000원"
    )
    assert raw is not None
    assert raw["items"][0]["unitPrice"] == 18000


@pytest.mark.asyncio
async def test_interpreter_uses_fallback_only_after_model_client_failure():
    client = _FailingClient(_ProviderServerError("provider unavailable"))
    interpreter = B66QuoteConversationInterpreter(client)

    projection = await interpreter.interpret(
        message="대한건설에 배관 100미터, 부가세 별도",
        skill=_skill(),
    )

    assert client.calls == 1
    assert projection.recipient["company"] == "대한건설"
    assert projection.items == ({"name": "배관", "qty": 100, "unit": "미터"},)
    assert projection.tax_mode == "EXCLUSIVE"
    assert projection.missing == ("unitPrice",)
    assert projection.result_origin == "deterministic_fallback"
    assert "result_origin" not in projection.safe_dict()


@pytest.mark.asyncio
async def test_interpreter_fallback_completes_same_pending_quote_facts():
    client = _FailingClient(_ProviderServerError("provider unavailable"))
    interpreter = B66QuoteConversationInterpreter(client)

    projection = await interpreter.interpret(
        message="대한건설에 배관 100미터, 부가세 별도\n미터당 18000원",
        skill=_skill(),
    )

    assert projection.recipient["company"] == "대한건설"
    assert projection.items == (
        {"name": "배관", "qty": 100, "unit": "미터", "unitPrice": 18000},
    )
    assert projection.missing == ()


@pytest.mark.asyncio
async def test_unrecognized_text_preserves_original_upstream_failure():
    original = _ProviderServerError("provider unavailable")
    client = _FailingClient(original)
    interpreter = B66QuoteConversationInterpreter(client)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        await interpreter.interpret(
            message="이건 견적과 관계없는 자유로운 문장입니다",
            skill=_skill(),
        )


@pytest.mark.asyncio
async def test_non_provider_server_error_preserves_existing_failure_contract():
    original = RuntimeError("engine lane unavailable")
    client = _FailingClient(original)
    interpreter = B66QuoteConversationInterpreter(client)

    with pytest.raises(RuntimeError, match="engine lane unavailable"):
        await interpreter.interpret(
            message="????? ?? 100??, ??? ??",
            skill=_skill(),
        )


@pytest.mark.asyncio
async def test_fallback_requires_recipient_and_items_skill_authority():
    original = _ProviderServerError("provider unavailable")
    client = _FailingClient(original)
    interpreter = B66QuoteConversationInterpreter(client)
    skill = _skill()
    skill["variableSchema"]["recipient"] = False

    with pytest.raises(_ProviderServerError):
        await interpreter.interpret(
            message="????? ?? 100??, ??? ??",
            skill=skill,
        )
