from app.pilot.catalog import CatalogModel, select_by_optimize


def model(
    model_id: str,
    *,
    input_price: float | None,
    output_price: float | None,
    korean_score: int = 4,
    latency_ms: int = 500,
    sort_order: int = 10,
) -> CatalogModel:
    return CatalogModel(
        model_id=model_id,
        upstream_model=model_id,
        display_name=model_id,
        provider="Test Provider",
        provider_type="external",
        input_price_usd_per_1m=input_price,
        output_price_usd_per_1m=output_price,
        context_window=100_000,
        korean_score=korean_score,
        latency_ms=latency_ms,
        capabilities=frozenset({"chat"}),
        sort_order=sort_order,
    )


def test_cost_ranking_keeps_unknown_after_known_zero_and_known_paid() -> None:
    known_zero = model("known-zero", input_price=0.0, output_price=0.0)
    known_paid = model("known-paid", input_price=0.2, output_price=0.8)
    partial = model("partial", input_price=0.2, output_price=None, sort_order=20)
    unknown = model("unknown", input_price=None, output_price=None, sort_order=30)

    ranked = select_by_optimize(
        [unknown, known_paid, partial, known_zero],
        optimize_for="cost",
        allow_external=True,
    )

    assert [item.model_id for item in ranked] == [
        "known-zero",
        "known-paid",
        "partial",
        "unknown",
    ]


def test_balanced_ranking_preserves_korean_priority_but_not_unknown_equals_free() -> None:
    known_zero = model("known-zero", input_price=0.0, output_price=0.0)
    known_paid = model("known-paid", input_price=0.2, output_price=0.8)
    unknown = model("unknown", input_price=None, output_price=None)

    ranked = select_by_optimize(
        [unknown, known_paid, known_zero],
        optimize_for="balanced",
        allow_external=True,
    )

    assert [item.model_id for item in ranked] == [
        "known-zero",
        "known-paid",
        "unknown",
    ]


def test_balanced_ranking_does_not_replace_existing_quality_first_policy() -> None:
    higher_korean_unknown = model(
        "higher-korean-unknown",
        input_price=None,
        output_price=None,
        korean_score=5,
    )
    lower_korean_known = model(
        "lower-korean-known",
        input_price=0.1,
        output_price=0.1,
        korean_score=4,
    )

    ranked = select_by_optimize(
        [lower_korean_known, higher_korean_unknown],
        optimize_for="balanced",
        allow_external=True,
    )

    assert [item.model_id for item in ranked] == [
        "higher-korean-unknown",
        "lower-korean-known",
    ]


def test_provider_order_remains_stronger_than_cost_ranking() -> None:
    expensive_preferred = CatalogModel(
        model_id="preferred",
        upstream_model="preferred",
        display_name="preferred",
        provider="Preferred Provider",
        provider_type="external",
        input_price_usd_per_1m=10.0,
        output_price_usd_per_1m=10.0,
        context_window=100_000,
        korean_score=4,
        latency_ms=500,
        capabilities=frozenset({"chat"}),
    )
    cheap_other = CatalogModel(
        model_id="other",
        upstream_model="other",
        display_name="other",
        provider="Other Provider",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        context_window=100_000,
        korean_score=4,
        latency_ms=500,
        capabilities=frozenset({"chat"}),
    )

    ranked = select_by_optimize(
        [cheap_other, expensive_preferred],
        optimize_for="cost",
        allow_external=True,
        provider_order=["Preferred Provider"],
    )

    assert [item.model_id for item in ranked] == ["preferred", "other"]
