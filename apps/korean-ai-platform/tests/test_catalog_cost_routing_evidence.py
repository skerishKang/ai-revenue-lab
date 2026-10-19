import pytest
from app.pilot.catalog import CatalogModel
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
def test_configured_combined_per_1k_cost_is_truthful_and_unknown_stays_none() -> None:
    known = model("known", input_price=0.30, output_price=2.50)
    known_zero = model("known-zero", input_price=0.0, output_price=0.0)
    partial = model("partial", input_price=0.30, output_price=None)
    unknown = model("unknown", input_price=None, output_price=None)
    assert known.cost_usd_per_1k() == pytest.approx(0.0028)
    assert known_zero.cost_usd_per_1k() == 0.0
    assert partial.cost_usd_per_1k() is None
    assert unknown.cost_usd_per_1k() is None
