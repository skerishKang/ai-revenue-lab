from __future__ import annotations

import warnings

# Suppress starlette httpx+testclient deprecation BEFORE importing TestClient
warnings.filterwarnings("ignore", message=r"Using .httpx. with .starlette.testclient")

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app

# After starlette is loaded and its warning is suppressed, convert all
# remaining warnings to errors (equivalent to -W error::Warning).
warnings.simplefilter("error")


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)
