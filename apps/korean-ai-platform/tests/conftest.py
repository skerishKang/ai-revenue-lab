from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app):
    return TestClient(app)
