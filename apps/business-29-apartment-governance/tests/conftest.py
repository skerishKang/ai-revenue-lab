"""Test fixtures — local SQLite only, no network, no real DB accounts."""

import os

# Ensure the app engine defaults to an unused in-memory DB before import.
os.environ.setdefault("B29_DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, inspect  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services import seed_synthetic  # noqa: E402

ADMIN = {"X-Synthetic-Actor": "chair-synthetic", "X-Synthetic-Role": "admin"}
REP = {"X-Synthetic-Actor": "rep-synthetic", "X-Synthetic-Role": "rep"}
OFFICE = {"X-Synthetic-Actor": "office-synthetic", "X-Synthetic-Role": "office"}
AUDITOR = {"X-Synthetic-Actor": "auditor-synthetic", "X-Synthetic-Role": "auditor"}
RESIDENT = {"X-Synthetic-Actor": "resident-synthetic", "X-Synthetic-Role": "resident"}
REVIEWER = {"X-Synthetic-Actor": "reviewer-synthetic", "X-Synthetic-Role": "reviewer"}


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    models.Base.metadata.create_all(eng)
    yield eng
    models.Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def session(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = Session()
    yield db
    db.close()


@pytest.fixture()
def client(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def tables(engine):
    return set(inspect(engine).get_table_names())


def make_community(client, headers=ADMIN):
    r = client.post("/api/communities", json={"name": "솔빛마루 2단지", "households": 420}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def make_meeting(client, community_id, headers=ADMIN):
    r = client.post(
        "/api/meetings",
        json={"community_id": community_id, "title": "2026년 3분기 합성 대표회의", "quarter": "2026 Q3"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def state(client, meeting_id, headers=ADMIN) -> str:
    r = client.get(f"/api/meetings/{meeting_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["meeting"]["state"]
