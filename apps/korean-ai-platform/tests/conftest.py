from __future__ import annotations

import warnings

# Suppress known third-party deprecation warnings BEFORE importing TestClient.
# These are upstream library warnings that our test suite does not control.
# When running with -W error::Warning (or conftest simplefilter), these
# filters must be added BEFORE the warning fires, so they take precedence.
warnings.filterwarnings("ignore", message=r"Using .httpx. with .starlette.testclient")
warnings.filterwarnings("ignore", message=r"Setting per-request cookies")
warnings.filterwarnings("ignore", message=r"The `route` decorator is deprecated")

import pytest
from starlette.testclient import TestClient

from app.factory import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# Legacy catalog entries for tests written before decision #1933.
#
# #1933 reduced the production catalog to a single Kilo Gateway route. Several
# contracts (legacy capability tags, hard privacy policy, platform-owned
# credential plane, provider readiness) were written against the wider catalog.
# These fixtures reinstall the historical entries inside a single test so those
# contracts stay genuinely validated instead of silently collapsing to a single
# candidate. They never alter the committed catalog.
# ---------------------------------------------------------------------------
GEMINI_MODEL_ID = "google/gemini-2.5-flash"
AGNES_MODEL_ID = "agnes-ai/agnes-2.5-flash"


def _gemini_catalog_model():
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id=GEMINI_MODEL_ID,
        upstream_model=GEMINI_MODEL_ID,
        display_name="Google: Gemini 2.5 Flash",
        provider="Google",
        provider_type="external",
        input_price_usd_per_1m=0.30,
        output_price_usd_per_1m=2.50,
        currency="usd",
        context_window=1048576,
        korean_score=5,
        latency_ms=750,
        capabilities=frozenset({"chat", "image", "long_context", "coding"}),
        region="외부",
        sort_order=10,
        credential_source="openrouter",
        platform_provider_id="",
    )


def _agnes_catalog_model():
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id=AGNES_MODEL_ID,
        upstream_model="agnes-2.5-flash",
        display_name="Agnes AI: Agnes 2.5 Flash",
        provider="Agnes AI",
        provider_type="platform",
        input_price_usd_per_1m=None,
        output_price_usd_per_1m=None,
        currency="usd",
        context_window=200000,
        korean_score=4,
        latency_ms=900,
        capabilities=frozenset({"chat"}),
        region="외부",
        sort_order=70,
        credential_source="platform_secret",
        platform_provider_id="agnes-ai",
    )


def _install_catalog_models(monkeypatch, *models):
    """Install extra catalog entries across every module that imported the globals.

    Production modules import ``CATALOG_MODELS``/``CATALOG_BY_ID`` by name, so a
    single monkeypatch on ``app.pilot.catalog`` is not enough. This sweeps the
    already-imported bindings so routing, readiness and capability code all see
    the same synthetic catalog for the duration of one test.
    """
    import sys
    import types

    import app.pilot.catalog as cat

    extended = [*list(cat.CATALOG_MODELS), *models]
    by_id = {m.model_id: m for m in extended}

    targets = {cat}
    for module in sys.modules.values():
        if not isinstance(module, types.ModuleType):
            continue
        if module.__name__.startswith("app.") and (
            hasattr(module, "CATALOG_MODELS") or hasattr(module, "CATALOG_BY_ID")
        ):
            targets.add(module)

    for module in targets:
        if hasattr(module, "CATALOG_MODELS"):
            monkeypatch.setattr(module, "CATALOG_MODELS", extended)
        if hasattr(module, "CATALOG_BY_ID"):
            monkeypatch.setattr(module, "CATALOG_BY_ID", by_id)

    return extended[-1] if models else extended[0]


@pytest.fixture()
def gemini_catalog_entry(monkeypatch):
    """Install the historical Gemini route (paid, image-capable)."""
    return _install_catalog_models(monkeypatch, _gemini_catalog_model())
@pytest.fixture()
def agnes_catalog_entry(monkeypatch):
    """Install the historical Agnes route (platform_secret, no free tag)."""
    return _install_catalog_models(monkeypatch, _agnes_catalog_model())


OX_ALPHA_MODEL_ID = "stealth/ox-alpha"


def _ox_alpha_catalog_model():
    from app.pilot.catalog import CatalogModel

    return CatalogModel(
        model_id=OX_ALPHA_MODEL_ID,
        upstream_model=OX_ALPHA_MODEL_ID,
        display_name="Ox Alpha",
        provider="Stealth",
        provider_type="external",
        input_price_usd_per_1m=0.0,
        output_price_usd_per_1m=0.0,
        currency="usd",
        context_window=1048576,
        korean_score=4,
        latency_ms=2000,
        capabilities=frozenset({"chat", "image", "long_context", "coding", "free"}),
        region="외부",
        sort_order=60,
        credential_source="openrouter",
        platform_provider_id="",
    )


@pytest.fixture()
def ox_alpha_catalog_entry(monkeypatch):
    """Install the historical free image-capable route used by multimodal tests."""
    return _install_catalog_models(monkeypatch, _ox_alpha_catalog_model())
