from __future__ import annotations

import warnings

# Suppress known third-party deprecation warnings BEFORE importing TestClient.
# These are upstream library warnings that our test suite does not control.
# When running with -W error::Warning (or conftest simplefilter), these
# filters must be added BEFORE the warning fires, so they take precedence.
warnings.filterwarnings("ignore", message=r"Using .httpx. with .starlette.testclient")
warnings.filterwarnings("ignore", message=r"Setting per-request cookies")

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)
